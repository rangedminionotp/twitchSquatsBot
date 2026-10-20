// Shipped local controller + real detector; fake DOM/camera/model/API only.
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../../static/capture/capture.js',import.meta.url),'utf8');
const detectorSource=await readFile(new URL('../../static/capture/squat-detector.mjs',import.meta.url),'utf8');
const elements=new Map(),intervals=[],documentEvents={},requests=[],disk=new Map();
let now=10000,raf,results,points,mode='webcam',queueRun=null,draws=0,modelFail=false;
function element(id) {
  if(!elements.has(id))elements.set(id,{id,textContent:'',value:'',disabled:false,hidden:false,style:{},dataset:{},events:{},children:[],
    classList:{add(){},remove(){},toggle(){}},append(...items){this.children.push(...items);},appendChild(item){this.children.push(item);},
    addEventListener(name,fn){this.events[name]=fn;},setAttribute(){},getContext(){return {clearRect(){}};},async play(){}});
  return elements.get(id);
}
const storage={get length(){return disk.size;},key:i=>[...disk.keys()][i],getItem:k=>disk.get(k)??null,setItem:(k,v)=>disk.set(k,v),removeItem:k=>disk.delete(k)};
const track={label:'Fake camera',readyState:'live',muted:false,stop(){},getSettings:()=>({deviceId:'test'})};
const video=element('video');video.videoWidth=1280;video.videoHeight=720;video.currentTime=0;
class FakePose { constructor(){if(modelFail)throw Error('Fake model error');}setOptions(){}onResults(fn){results=fn;}async send(){results({poseLandmarks:points});} }
const context=vm.createContext({console,AbortSignal,performance:{now:()=>now},Date:class extends Date{static now(){return now;}},
  crypto:{randomUUID:()=> 'camera-page'},location:{pathname:'/camera-overlay'},localStorage:storage,
  document:{getElementById:element,createElement:tag=>element('created'+elements.size+tag),body:element('body'),head:element('head'),hidden:false,
    addEventListener:(name,fn)=>{documentEvents[name]=fn;}},
  window:{crypto:{randomUUID:()=> 'session'},Pose:FakePose,POSE_CONNECTIONS:[],drawConnectors(){draws++;},drawLandmarks(){},addEventListener(){}},
  navigator:{mediaDevices:{enumerateDevices:async()=>[{kind:'videoinput',deviceId:'test',label:'Fake camera'}],
    getUserMedia:async()=>({getTracks:()=>[track],getVideoTracks:()=>[track]}),addEventListener(){}}},
  requestAnimationFrame:fn=>{raf=fn;},setInterval:fn=>{intervals.push(fn);},
  fetch:async(path,options)=>{
    requests.push({path,body:options?.body?JSON.parse(options.body):null});
    return {ok:true,json:async()=>path==='/api/camera'?{owns_camera:true,mode,queue:{run:queueRun,items:[]}}:{}};
  }
});
const main=new vm.SourceTextModule(source,{context});
await main.link(name=>new vm.SourceTextModule(name.includes('squat-detector')?detectorSource:'export const config={defaultSquatTarget:10};',{context}));
await main.evaluate();
const settle=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
await settle();
element('startButton').events.click();await settle();
assert.equal(element('calibrateButton').disabled,false);
function body(angle=148,rise=.45) {
  const p=Array.from({length:33},()=>({x:.5,y:.3,visibility:.9}));
  for(const [side,[hip,knee,ankle]] of [[23,25,27],[24,26,28]].entries()){
    const x=.44+side*.1;p[hip]={x,y:.84-rise,visibility:.9};
    p[knee]={x:x+rise*720/(2*Math.tan(angle*Math.PI/360)*1280),y:.84-rise/2,visibility:.9};
    p[ankle]={x,y:.84,visibility:.9};p[11+side]={x,y:.70-rise,visibility:.9};
  }return p;
}
async function hold(angle,rise,ms=1000) {
  for(let i=0;i<Math.ceil(ms/50);i++){
    now+=50;video.currentTime+=.05;points=body(angle,rise);
    if(i%20===0)await intervals[0]();
    await raf();await settle();
  }
}
const progress=()=>requests.filter(r=>r.path==='/api/camera/progress');
// Model failure leaves controls usable and never creates a progress report.
modelFail=true;await element('calibrateButton').onclick();
assert.equal(element('calibrationLabel').textContent,'Model unavailable');
assert.equal(element('calibrateButton').disabled,false);modelFail=false;
mode='capture';await intervals[0]();await hold(170,.45,500);
assert.equal(disk.size,0);assert.ok(draws>0,'Skeleton draws in capture mode');
await hold(110,.33);await hold(170,.45);
assert.equal(progress().length,1);assert.equal(progress()[0].body.count,1);assert.equal(progress()[0].body.queue_run,null);
assert.equal(element('count').textContent,'1');assert.equal(disk.size,0);
queueRun='queued-run';await intervals[0]();await hold(170,.45,500);
await hold(110,.33);await hold(170,.45);
assert.equal(progress().length,2);assert.equal(progress()[1].body.queue_run,'queued-run');
assert.equal(progress()[1].body.count,1,'Each queue segment retains its cumulative protocol');
await intervals[0]();assert.equal(requests.filter(r=>r.path==='/api/camera').at(-1).body.telemetry.calibration,'ready');
await hold(110,.33);context.document.hidden=true;documentEvents.visibilitychange();
context.document.hidden=false;await hold(170,.45);assert.equal(progress().length,2,'Hidden-page reset does not count a half rep');
element('cameraSelect').value='new-camera';element('cameraSelect').events.change();await settle();
assert.equal(progress().length,2);
console.log('Local fixed-angle controller passed: skeleton drawing, real rep reports, queue segments, camera switch and visibility.');
