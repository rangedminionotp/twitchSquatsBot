import {Outbox, SquatDetector, kneeAngle} from './capture-core.mjs';
import {loadPose} from './pose.mjs';

const $ = id => document.getElementById(id);
const video = $('video'), detector = new SquatDetector();
const pageId = crypto.randomUUID();
let uid = '', csrf = '', outbox, stream, model, run, lease = '', until = 0;
let mode = 'webcam', busy = false, generation = 0, lastFrame = -1, lastInference = 0;
let storageOk = true;
function message(text) { $('status').textContent = text; }
function halt(text) {
  generation++; mode='webcam'; lease=''; until=0; detector.reset();
  $('hint').textContent = stream ? 'Webcam · not counting' : 'Camera off';
  if (text) message(text);
}
function stop() {
  halt('Camera off. Saved progress is retained.');
  stream?.getTracks().forEach(track=>track.stop()); stream=null; video.srcObject=null;
  $('hint').textContent='Camera off'; updateButtons();
}
async function request(path, body) {
  const response = await fetch(path, {cache:'no-store',signal:AbortSignal.timeout(5000),
    ...(body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)})});
  const data = await response.json();
  if (response.status===401) { stop(); uid=''; csrf=''; updateButtons(); }
  if (!response.ok) throw Object.assign(Error(data.error || 'Request failed'),{status:response.status});
  return data;
}
async function identity() {
  const data = await request('/api/me');
  if (uid && uid!==data.user.id) { stop(); throw Error('Account changed. Reload this page; previous account reports remain saved.'); }
  if (!uid && outbox) throw Error('Session ended. Sign in in the control panel, then reload this page.');
  uid=data.user.id; csrf=data.csrf;
  if (!outbox) outbox=new Outbox(localStorage,uid);
  $('account').textContent=`${data.user.login} · Cloud camera preview`;
  run=data.challenge;
  $('progress').textContent=run ? `${run.viewer}: ${run.done} / ${run.target} · ${run.status}` : 'No active challenge. Start one from the control panel.';
  return data;
}
function pending() {
  try { return outbox?.entries() || []; }
  catch { storageOk=false; halt(); throw Error('Browser storage is unavailable or damaged. Capture paused; do not clear site data.'); }
}
function updateButtons() {
  let items=[];
  try { items=pending(); } catch (error) { message(error.message); }
  $('start').disabled=busy || !uid || !!stream;
  $('devices').disabled=!!stream || busy;
  $('stop').disabled=!stream;
  $('capture').disabled=busy || !uid || !stream || !storageOk || !!items.length || mode==='capture';
  $('webcam').disabled=!stream;
  $('recovery').hidden=!items.length;
  $('pending').textContent=items.length ? `Saved cumulative total: ${items[0].count}. ${items.length} report(s) need reconciliation. Capture is paused until resolved.` : '';
  for (const id of ['retry','apply','discard']) $(id).disabled=busy || !uid;
}
async function action(task) {
  if (busy) return;
  busy=true; updateButtons();
  try { await task(); }
  catch (error) { halt(error.message + (error.status===401 ? ' Open the control panel to sign in again.' : '')); }
  finally { busy=false; updateButtons(); }
}
async function devices() {
  const selected=$('devices').value;
  let timer;
  let available;
  try {
    available=await Promise.race([navigator.mediaDevices.enumerateDevices(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Camera list unavailable. Try Start camera in Chrome or Edge.')),3000);})]);
  } finally { clearTimeout(timer); }
  const options=available.filter(d=>d.kind==='videoinput');
  $('devices').replaceChildren(new Option('Default camera',''),...options.map((d,i)=>new Option(d.label||`Camera ${i+1}`,d.deviceId)));
  $('devices').value=selected;
}
async function sendSaved(report) {
  const data=await request('/api/capture/progress',{run_id:report.run_id,lease:report.lease,count:report.count});
  outbox.acknowledge(report,data.accepted);
  if (run?.id===report.run_id) {
    run=data.run;
    $('progress').textContent=`${run.viewer}: ${run.done} / ${run.target} · ${run.status}`;
    if (run.status==='completed') halt('Challenge complete. Start the next one manually in the control panel.');
  }
  return data;
}
async function reconcile() {
  for (const report of pending()) await sendSaved(report);
  updateButtons();
}
$('start').onclick=()=>action(async()=>{
  if (!isSecureContext || !navigator.mediaDevices?.getUserMedia) throw Error('Camera requires HTTPS or localhost in a supported browser.');
  await identity();
  const mark=++generation;
  let acquired;
  let timer, expired=false;
  message('Waiting for camera permission… Check your browser permission prompt.');
  try {
    const opening=navigator.mediaDevices.getUserMedia({audio:false,video:{width:{ideal:1280},height:{ideal:720},frameRate:{ideal:24,max:30},...($('devices').value?{deviceId:{exact:$('devices').value}}:{})}}).then(value=>{
      if (expired || mark!==generation) value.getTracks().forEach(track=>track.stop());
      return value;
    });
    acquired=await Promise.race([opening,new Promise((_,reject)=>{timer=setTimeout(()=>{expired=true;reject(Object.assign(Error('timeout'),{name:'TimeoutError'}));},15000);})]);
  } catch (error) {
    if (error.name==='TimeoutError') throw Error('Camera permission timed out. Open this page in Chrome or Edge, allow camera access, then retry.');
    throw Error(error.name==='NotAllowedError' ? 'Camera permission denied. Allow camera access in browser site settings.' : 'Camera unavailable. Release it in OBS/Streamlabs or choose another device.');
  } finally { clearTimeout(timer); }
  if (mark!==generation) { acquired.getTracks().forEach(t=>t.stop()); return; }
  stream=acquired; video.srcObject=stream;
  stream.getVideoTracks()[0].addEventListener('ended',()=>stop());
  await video.play(); await devices();
  $('hint').textContent='Webcam · not counting'; message('Camera ready. Webcam mode does not change counters.');
});
$('stop').onclick=stop;
$('webcam').onclick=()=>{ halt('Webcam only. Challenge remains prepared; pause it from the control panel if needed.'); updateButtons(); };
$('capture').onclick=()=>action(async()=>{
  await identity();
  if (!run || run.status!=='active') throw Error('Start or resume a queued challenge in the control panel first.');
  if (pending().length) throw Error('Resolve saved progress first.');
  const mark=++generation;
  message('Loading pose model… First download may take a moment.');
  try { model ||= await loadPose(); }
  catch { throw Error('Pose model failed to load. Check network/CDN access and retry Capture. Webcam still works.'); }
  if (mark!==generation || !stream) return;
  const started=performance.now();
  const result=await request('/api/capture/claim',{run_id:run.id,page_id:pageId});
  if (mark!==generation || !stream) return;
  run=result.run; lease=result.lease; until=started+result.lease_seconds*1000-2000;
  mode='capture'; detector.reset(); lastFrame=-1;
  message('Pose model ready. Stand with both shoulders and a full leg visible, then squat and stand.');
});
$('retry').onclick=()=>action(async()=>{ halt(); await identity(); await reconcile(); message('Saved report acknowledged. Select Capture to continue.'); });
$('apply').onclick=()=>action(async()=>{
  halt(); await identity();
  const item=pending()[0]; if (!item) return;
  const current=(await request('/api/capture/run?id='+encodeURIComponent(item.run_id))).run;
  if (item.count<=current.accepted) { await sendSaved(item); message('Server already accepted this total.'); return; }
  if (current.status!=='active') throw Error('Resume this saved challenge in the control panel before recovery.');
  if (!confirm(`This report may have missed its lease. Server total: ${current.accepted}. Saved total: ${item.count}. Apply the saved TOTAL to this same challenge? Other camera work may overlap; this is not an extra increment.`)) return;
  const claim=await request('/api/capture/claim',{run_id:item.run_id,page_id:pageId});
  const report=outbox.save({...item,lease:claim.lease});
  await sendSaved(report); message('Saved total reconciled. Select Capture to continue.');
});
$('discard').onclick=()=>action(async()=>{
  halt(); await identity(); const item=pending()[0]; if (!item) return;
  if (!confirm(`Discard saved total ${item.count}? Any reps not already accepted by the server will be lost. This does not undo accepted reps.`)) return;
  outbox.discard(item); message('Unconfirmed report discarded. Server totals are unchanged.');
});
function clean() { const hidden=!$('controls').hidden; $('controls').hidden=hidden; $('show').hidden=!hidden; document.body.classList.toggle('clean',hidden); }
$('hide').onclick=clean; $('show').onclick=clean;
document.addEventListener('keydown',event=>{ if (event.key.toLowerCase()==='h' && !['INPUT','SELECT','TEXTAREA'].includes(event.target.tagName)) clean(); });
document.addEventListener('visibilitychange',()=>{ if (document.hidden) { halt('Capture paused because the camera window became hidden. Keep it visible and select Capture to resume.'); updateButtons(); } });
window.addEventListener('pagehide',stop);

async function poll() {
  if (busy) return;
  await action(async()=>{
    const previous=run?.id;
    await identity();
    if (pending().length) { halt(); await reconcile(); return; }
    if (mode==='capture') {
      if (!run || run.id!==previous || run.status!=='active') { halt('Challenge changed or paused. Select Capture when ready.'); return; }
      const started=performance.now();
      const result=await request('/api/capture/claim',{run_id:run.id,page_id:pageId});
      // Never silently acquire a new generation after our old lease expires.
      if (result.lease!==lease) { halt('Camera lease changed. Select Capture to resume.'); return; }
      until=started+result.lease_seconds*1000-2000;
    }
  });
}
function frame(now) {
  requestAnimationFrame(frame);
  if (mode!=='capture' || !model || !stream) return;
  if (now>=until) { halt('Connection expired. Capture paused; reconnect and select Capture.'); updateButtons(); return; }
  if (busy || document.hidden || video.readyState<2 || now-lastInference<80 || video.currentTime===lastFrame) return;
  try {
    if (pending().length) return;
    lastInference=now; lastFrame=video.currentTime;
    const points=model.detectForVideo(video,now).landmarks[0];
    const angle=kneeAngle(points,video.videoWidth,video.videoHeight);
    $('hint').textContent=angle===null ? 'Person not detected · show shoulders and full leg' : `${Math.round(angle)}° · ${detector.phase==='up'?'Stand tall':'Stand → squat → stand'}`;
    if (!detector.update(angle,now)) return;
    if (performance.now()>=until) { halt('Lease expired during detection. This rep was not recorded.'); return; }
    const report={run_id:run.id,lease,count:run.accepted+1};
    try { outbox.save(report); }
    catch { storageOk=false; throw Error('Cannot save this rep locally. Capture paused; check browser storage.'); }
    void action(async()=>{ await sendSaved(report); });
  } catch (error) { halt('Capture stopped: '+error.message); updateButtons(); }
}
await action(async()=>{ await identity(); if (navigator.mediaDevices) await devices(); if (pending().length) await reconcile(); message('Start camera for webcam mode, or prepare a challenge in the control panel.'); });
requestAnimationFrame(frame);
setInterval(poll,3000);
