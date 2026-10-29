import {ViewerSquatDetector} from './viewer-core.mjs';
import {kneeAngle} from './capture-core.mjs';
import {loadPose} from './pose.mjs';

const $ = id => document.getElementById(id);
const detector = new ViewerSquatDetector();
const video = $('video'), canvas = $('skeleton'), context = canvas.getContext('2d');
let csrf = '', stream = null, model = null, run = null, community = null;
let mode = 'idle', busy = false, pending = null, sending = false;
let lastVideoTime = -1, lastInference = 0, trackingStarted = 0, elapsedBase = 0;

const stageCopy = {
  standing: ['1','Stand tall and hold','Keep both shoulders and one full leg visible.'],
  squat: ['2','Show your squat depth','Lower to a comfortable depth and hold briefly.'],
  return: ['3','Return to standing','Stand tall once more to finish calibration.'],
  ready: ['✓','Calibration complete','Your personal motion range is ready.'],
  tracking: ['●','Full range tracking','Stand → reach your depth → stand.'],
  idle: ['0','Ready to begin','Start the camera, then follow the calibration prompts.']
};

function status(text, error=false) { $('status').textContent=text; $('status').classList.toggle('error',error); }
function format(value) { return Number(value || 0).toLocaleString(); }
function setMode(next) { mode=next; renderButtons(); }

async function request(path, body) {
  const response = await fetch(path,{cache:'no-store',signal:AbortSignal.timeout(7000),
    ...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)})});
  let data={}; try { data=await response.json(); } catch {}
  if (!response.ok) throw Object.assign(Error(data.error || 'Request failed'),{status:response.status});
  return data;
}

function renderCommunity(value) {
  community=value; if (!value) return;
  $('channel').textContent=value.channel;
  $('communityTotal').textContent=format(value.community_total);
  $('todayCount').textContent=`${value.today ?? 0} / ${value.daily_limit}`;
  $('remaining').textContent=value.remaining_today === 0 ? 'Daily limit reached. Come back tomorrow.' : `${value.remaining_today} contributions remaining today.`;
  $('dailyMeter').style.width=`${Math.min(100,100*(value.today ?? 0)/value.daily_limit)}%`;
  if (run) { $('runCount').textContent=run.accepted; $('runTarget').textContent=`/ ${run.target}`; }
}

function renderButtons() {
  const signedIn=!!csrf, hasCamera=!!stream, capped=community?.remaining_today===0;
  $('startCamera').disabled=busy || !signedIn || hasCamera;
  $('devices').disabled=busy || hasCamera;
  $('stopCamera').disabled=!hasCamera;
  $('calibrate').disabled=busy || !signedIn || !hasCamera || capped || !!pending;
  $('retry').hidden=!pending;
  $('retry').disabled=busy || sending;
  $('cameraBadge').textContent=hasCamera ? (mode==='tracking'?'Counting':mode.startsWith('calibrat')?'Calibrating':'Camera on') : 'Camera off';
  $('cameraBadge').classList.toggle('active',hasCamera);
  $('trackingMetric').textContent=mode==='tracking'?'Active':mode==='paused'?'Paused':mode.startsWith('calibrat')?'Learning':'Idle';
}

function renderDetector(result, angle=null) {
  const copy=stageCopy[result.stage] || stageCopy.idle;
  $('stageIndex').textContent=copy[0]; $('stageLabel').textContent=copy[1]; $('stageHelp').textContent=copy[2];
  $('calibrationMeter').style.width=`${result.calibration_progress*100}%`;
  $('angle').textContent=angle==null?'—°':`${Math.round(angle)}°`;
  $('currentMetric').textContent=angle==null?'—°':`${Math.round(angle)}°`;
  $('standingMetric').textContent=result.standing_angle==null?'—°':`${result.standing_angle}°`;
  $('squatMetric').textContent=result.squat_angle==null?'—°':`${result.squat_angle}°`;
}

async function identity() {
  try {
    const data=await request('/api/viewer'); csrf=data.csrf;
    $('account').textContent=`${data.user.login} · signed in`; $('logout').hidden=false; $('deleteData').hidden=false; $('loginPanel').hidden=true;
    run=data.community.run; renderCommunity(data.community);
    if (run) { $('runCount').textContent=run.accepted; $('runTarget').textContent=`/ ${run.target}`; }
    status('Camera processing is local. Nothing is counted until calibration succeeds.');
  } catch (error) {
    if (error.status!==401) throw error;
    csrf=''; $('account').textContent='Guest'; $('logout').hidden=true; $('deleteData').hidden=true; $('loginPanel').hidden=false;
    try { const data=await request('/api/community'); $('channel').textContent=data.channel; $('communityTotal').textContent=format(data.community_total); }
    catch { $('communityTotal').textContent='—'; }
    status('Sign in with Twitch to contribute.');
  } finally { renderButtons(); }
}

async function listDevices() {
  if (!navigator.mediaDevices?.enumerateDevices) return;
  const selected=$('devices').value;
  const cameras=(await navigator.mediaDevices.enumerateDevices()).filter(device=>device.kind==='videoinput');
  $('devices').replaceChildren(new Option('Default camera',''),...cameras.map((device,index)=>new Option(device.label||`Camera ${index+1}`,device.deviceId)));
  if ([...$('devices').options].some(option=>option.value===selected)) $('devices').value=selected;
}

async function startCamera() {
  if (!isSecureContext || !navigator.mediaDevices?.getUserMedia) throw Error('Camera requires HTTPS or localhost in Chrome, Edge, or another supported browser.');
  const selected=$('devices').value;
  status('Waiting for camera permission…');
  let timer, timedOut=false, acquired;
  try {
    const opening=navigator.mediaDevices.getUserMedia({audio:false,video:{width:{ideal:1280},height:{ideal:720},frameRate:{ideal:24,max:30},...(selected?{deviceId:{exact:selected}}:{})}}).then(value=>{if(timedOut)value.getTracks().forEach(track=>track.stop());return value;});
    acquired=await Promise.race([opening,new Promise((_,reject)=>{timer=setTimeout(()=>{timedOut=true;reject(Object.assign(Error('Camera permission timed out'),{name:'TimeoutError'}));},15000);})]);
  } finally { clearTimeout(timer); }
  stream=acquired; video.srcObject=stream; stream.getVideoTracks()[0].addEventListener('ended',stopCamera);
  await video.play(); await listDevices(); $('placeholder').hidden=true; setMode('camera');
  status('Camera ready. Select Calibrate & play when your full body is visible.');
}

function stopCamera() {
  stream?.getTracks().forEach(track=>track.stop()); stream=null; video.srcObject=null; context.clearRect(0,0,canvas.width,canvas.height);
  $('placeholder').hidden=false; detector.reset(); renderDetector(detector.snapshot()); setMode('idle');
  status('Camera off. Server totals are unchanged.');
}

async function beginCalibration() {
  const data=await request('/api/viewer/start',{}); run=data.run; renderCommunity(data.community);
  $('runCount').textContent=run.accepted; $('runTarget').textContent=`/ ${run.target}`;
  status('Loading the on-device pose model…');
  try { model ||= await loadPose(); } catch { throw Error('Could not load the pose model. Check your connection and try again.'); }
  detector.beginCalibration(performance.now()); renderDetector(detector.snapshot()); setMode('calibrating');
  status('Stand tall and hold still. Calibration normally takes a few seconds.');
}

async function submitCalibration(result) {
  setMode('calibration-submit');
  try {
    const data=await request('/api/viewer/calibrate',{run_id:run.id,standing_angle:result.standing_angle,squat_angle:result.squat_angle,duration_ms:result.duration_ms});
    run=data.run; elapsedBase=run.elapsed_ms; trackingStarted=performance.now(); renderCommunity(data.community); setMode('tracking');
    status('Calibration accepted. Complete a full squat to contribute.');
  } catch (error) { setMode('paused'); status(error.message+' Select Calibrate & play to try again.',true); }
}

async function sendProgress(payload) {
  const wasRetry=!!pending;
  sending=true; renderButtons();
  try {
    const data=await request('/api/viewer/progress',payload); run=data.run; pending=null; renderCommunity(data.community);
    if (run.status==='completed') { setMode('complete'); status(`Run complete — ${run.accepted} squats added. Start another round if you still have allowance.`); }
    else if (wasRetry) { setMode('camera'); status(`Saved rep accepted: ${run.accepted} / ${run.target}. Recalibrate to continue safely.`); }
    else status(`Accepted: ${run.accepted} / ${run.target}. Keep going.`);
  } catch (error) { pending=payload; setMode('paused'); status(`Rep saved for retry: ${error.message}`,true); }
  finally { sending=false; renderButtons(); }
}

function acceptRep(now) {
  if (sending || pending || !run) { status('Waiting for the previous rep to be accepted…'); return; }
  const count=run.accepted+1, sequence=run.seq+1;
  const elapsed=Math.round(elapsedBase+now-trackingStarted);
  $('runCount').textContent=count;
  void sendProgress({run_id:run.id,sequence,count,elapsed_ms:elapsed});
}

function drawPose(points) {
  const width=video.videoWidth,height=video.videoHeight;
  if (!width || !height) return;
  if (canvas.width!==width || canvas.height!==height) {canvas.width=width;canvas.height=height;}
  context.clearRect(0,0,width,height); if (!points) return;
  const links=[[11,12],[11,23],[12,24],[23,24],[23,25],[25,27],[24,26],[26,28]];
  context.lineWidth=Math.max(3,width/300); context.lineCap='round'; context.strokeStyle='#63ead1cc'; context.fillStyle='#d9fff8';
  for (const [a,b] of links) { const p=points[a],q=points[b]; if ((p?.visibility??0)<.55||(q?.visibility??0)<.55) continue; context.beginPath();context.moveTo(p.x*width,p.y*height);context.lineTo(q.x*width,q.y*height);context.stroke(); }
  for (const index of [11,12,23,24,25,26,27,28]) {const p=points[index];if((p?.visibility??0)<.55)continue;context.beginPath();context.arc(p.x*width,p.y*height,Math.max(4,width/220),0,Math.PI*2);context.fill();}
}

function frame(now) {
  requestAnimationFrame(frame);
  if (!model || !stream || !['calibrating','tracking'].includes(mode) || document.hidden || video.readyState<2 || now-lastInference<80 || video.currentTime===lastVideoTime) return;
  lastInference=now; lastVideoTime=video.currentTime;
  try {
    const points=model.detectForVideo(video,now).landmarks[0]; drawPose(points);
    const angle=kneeAngle(points,video.videoWidth,video.videoHeight);
    const result=detector.update(angle,now); renderDetector(result,angle);
    if (result.calibrated && mode==='calibrating') void submitCalibration(result);
    else if (result.rep && mode==='tracking') acceptRep(now);
  } catch (error) { setMode('paused'); status('Local pose tracking paused: '+error.message,true); }
}

async function action(task) { if (busy) return; busy=true;renderButtons();try{await task();}catch(error){status(error.message,true);}finally{busy=false;renderButtons();} }
$('startCamera').onclick=()=>action(startCamera);
$('stopCamera').onclick=stopCamera;
$('calibrate').onclick=()=>action(beginCalibration);
$('retry').onclick=()=>action(async()=>{if(!pending)return;await sendProgress(pending);});
$('logout').onclick=()=>action(async()=>{await request('/api/logout',{});stopCamera();location.reload();});
$('deleteData').onclick=()=>action(async()=>{
  if (!confirm('Delete your Community Squats viewer account, calibration history, flags, and contributions? Your accepted reps will be removed from the community total. This cannot be undone.')) return;
  await request('/api/viewer/delete',{confirm:'DELETE'}); stopCamera(); location.assign('/viewer');
});
document.addEventListener('visibilitychange',()=>{if(document.hidden&&mode==='tracking'){setMode('paused');status('Counting paused while this tab is hidden. Recalibrate to continue.',true);}});
window.addEventListener('pagehide',()=>stream?.getTracks().forEach(track=>track.stop()));

renderDetector(detector.snapshot());
await identity();
requestAnimationFrame(frame);
