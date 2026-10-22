// Viewer controller integration test with fake DOM, camera, pose model and API.
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';

const source=await readFile(new URL('../../static/cloud/viewer.js',import.meta.url),'utf8');
const elements=new Map();
function element(id) {
  if (!elements.has(id)) {
    const value={id,textContent:'',value:'',disabled:false,hidden:false,style:{},options:[],readyState:2,currentTime:0,
      classList:{toggle(){}},replaceChildren(...children){this.options=children;this.value=children[0]?.value||'';},
      async play(){},addEventListener(){}};
    if (id==='skeleton') value.getContext=()=>({clearRect(){},beginPath(){},moveTo(){},lineTo(){},stroke(){},arc(){},fill(){}});
    elements.set(id,value);
  }
  return elements.get(id);
}

let frameCallback, now=1000, detectorStep=0, stopped=0;
const track={stop(){stopped++;},addEventListener(){}};
const stream={getTracks:()=>[track],getVideoTracks:()=>[track]};
const calls=[];
let run={id:'viewer-run',target:20,accepted:0,seq:0,status:'active',calibrated:0,elapsed_ms:0};
let community={channel:'streamer',community_total:10,today:0,daily_limit:100,remaining_today:100,run_target:20,run:null};
const context=vm.createContext({console,AbortSignal,setTimeout,clearTimeout,isSecureContext:true,
  performance:{now:()=>now},Option:function(label,value){this.label=label;this.value=value;},
  location:{reload(){}},window:{addEventListener(){}},requestAnimationFrame:fn=>{frameCallback=fn;},
  document:{getElementById:element,hidden:false,addEventListener(){}},
  navigator:{mediaDevices:{enumerateDevices:async()=>[{kind:'videoinput',label:'Camera',deviceId:'cam'}],getUserMedia:async()=>stream}},
  fetch:async(path,options={})=>{
    const body=options.body?JSON.parse(options.body):undefined; calls.push({path,body});
    let data,status=200;
    if(path==='/api/viewer') data={user:{login:'viewer'},csrf:'csrf',community};
    else if(path==='/api/viewer/start') {community={...community,run};data={run,community};}
    else if(path==='/api/viewer/calibrate') {run={...run,calibrated:1};community={...community,run};data={run,community};}
    else if(path==='/api/viewer/progress') {run={...run,accepted:body.count,seq:body.sequence};community={...community,community_total:11,today:1,remaining_today:99,run};data={run,community};}
    else if(path==='/api/community') data=community;
    else throw Error('Unexpected request '+path);
    return {status,ok:status===200,json:async()=>data};
  }
});

const module=new vm.SourceTextModule(source,{context});
await module.link(async name=>{
  if(name.includes('viewer-core')) return new vm.SourceTextModule(`
    export class ViewerSquatDetector {
      snapshot(){return {stage:'idle',calibration_progress:0,standing_angle:null,squat_angle:null,duration_ms:0};}
      reset(){} beginCalibration(){}
      update(){globalThis.detectorStep=(globalThis.detectorStep||0)+1;return globalThis.detectorStep===1?
        {stage:'ready',calibrated:true,rep:false,calibration_progress:1,standing_angle:165,squat_angle:95,duration_ms:3000}:
        {stage:'tracking',calibrated:false,rep:true,calibration_progress:1,standing_angle:165,squat_angle:95,duration_ms:4000};}
    }`,{context});
  if(name.includes('capture-core')) return new vm.SourceTextModule('export const kneeAngle=()=>100;',{context});
  return new vm.SourceTextModule('export async function loadPose(){return {detectForVideo(){return {landmarks:[[]]};}}}',{context});
});
context.detectorStep=detectorStep;
await module.evaluate();

assert.equal(element('account').textContent,'viewer · signed in');
assert.equal(element('loginPanel').hidden,true);
assert.equal(element('startCamera').disabled,false);
await element('startCamera').onclick();
assert.equal(element('placeholder').hidden,true);
assert.equal(element('calibrate').disabled,false);
await element('calibrate').onclick();
assert.equal(calls.filter(call=>call.path==='/api/viewer/start').length,1);

element('video').currentTime=1; now=5000; frameCallback(now);
await new Promise(resolve=>setTimeout(resolve,0));
const calibration=calls.find(call=>call.path==='/api/viewer/calibrate').body;
assert.deepEqual(Object.keys(calibration).sort(),['duration_ms','run_id','squat_angle','standing_angle']);

element('video').currentTime=2; now=7000; frameCallback(now);
await new Promise(resolve=>setTimeout(resolve,0));
const progress=calls.find(call=>call.path==='/api/viewer/progress').body;
assert.deepEqual(Object.keys(progress).sort(),['count','elapsed_ms','run_id','sequence']);
assert.equal(progress.count,1); assert.equal(progress.sequence,1);
assert.equal(element('communityTotal').textContent,'11');
assert.equal(element('todayCount').textContent,'1 / 100');
assert.ok(!JSON.stringify(calls).includes('landmarks'));

element('stopCamera').onclick();
assert.equal(stopped,1);
console.log('Viewer controller passed: identity, local camera, calibration and metadata-only cumulative progress.');
