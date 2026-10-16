// Controller integration tests with fake DOM, media, model and HTTP. No real camera.
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import {Outbox} from '../../static/cloud/capture-core.mjs';
const source=await readFile(new URL('../../static/cloud/camera.js',import.meta.url),'utf8');
const core=await readFile(new URL('../../static/cloud/capture-core.mjs',import.meta.url),'utf8');
const elements=new Map(), intervals=[];
function element(id){
  if(!elements.has(id)) elements.set(id,{id,textContent:'',value:'',disabled:false,hidden:false,tagName:'BUTTON',readyState:2,currentTime:0,
    replaceChildren(){},async play(){},addEventListener(){}});
  return elements.get(id);
}
const data=new Map();
const storage={get length(){return data.size;},key:i=>[...data.keys()][i],getItem:k=>data.get(k)??null,setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)};
let permission=false, modelFails=true, failProgress=false, uid='11', stopped=0, claimConflict=false, expired=false;
const run={id:'run',viewer:'Viewer',status:'active',accepted:0,done:0,target:3};
const track={stop(){stopped++;},addEventListener(){}};
const stream={getTracks:()=>[track],getVideoTracks:()=>[track]};
const requests=[];
const context=vm.createContext({console,localStorage:storage,isSecureContext:true,crypto:{randomUUID:()=> 'page'},performance:{now:()=>1000},
  AbortSignal,setTimeout,clearTimeout,Option:function(label,value){this.value=value;},confirm:()=>true,
  document:{getElementById:element,body:{classList:{toggle(){}}},addEventListener(){},hidden:false},
  window:{addEventListener(){}},setInterval:fn=>intervals.push(fn),requestAnimationFrame(){},
  navigator:{mediaDevices:{enumerateDevices:async()=>[],getUserMedia:async()=>{if(!permission)throw {name:'NotAllowedError'};return stream;}}},
  fetch:async(path,options)=>{
    requests.push(path);
    let status=200, result;
    if(expired){status=401;result={error:'Login required'};}
    else if(path==='/api/me')result={user:{id:uid,login:'test'},csrf:'csrf',challenge:{...run}};
    else if(path==='/api/capture/claim'){
      if(claimConflict){status=409;result={error:'Another camera owns this challenge'};}
      else result={run:{...run},lease:'lease',lease_seconds:15};
    }else if(path==='/api/capture/progress'){
      if(failProgress)throw Error('Network offline');
      const report=JSON.parse(options.body);run.accepted=run.done=report.count;result={accepted:run.accepted,run:{...run}};
    }else throw Error('Unexpected request '+path);
    return {status,ok:status===200,json:async()=>result};
  },mockLoad:async()=>{if(modelFails)throw Error('model failed');return {detectForVideo:()=>({landmarks:[]})};}
});
const main=new vm.SourceTextModule(source,{context});
await main.link(async name=>new vm.SourceTextModule(name.includes('capture-core')?core:'export const loadPose=globalThis.mockLoad;',{context}));
await main.evaluate();
assert.equal(element('start').disabled,false);
await element('start').onclick(); assert.match(element('status').textContent,/permission denied/);
permission=true; await element('start').onclick(); assert.equal(element('stop').disabled,false);
await element('capture').onclick(); assert.match(element('status').textContent,/model failed/);
modelFails=false; await element('capture').onclick(); assert.equal(element('capture').disabled,true);
element('webcam').onclick(); assert.match(element('hint').textContent,/not counting/);
claimConflict=true; await element('capture').onclick(); assert.match(element('status').textContent,/Another camera/); claimConflict=false;
const outbox=new Outbox(storage,'11'); outbox.save({run_id:'run',lease:'lease',count:1});
failProgress=true; await intervals[0](); assert.equal(element('recovery').hidden,false);assert.equal(outbox.entries().length,1);
failProgress=false; await element('retry').onclick(); assert.equal(outbox.entries().length,0);
outbox.save({run_id:'run',lease:'lease',count:2});
// Permission prompts can remain unanswered indefinitely. A late grant must not
// leave a webcam running after our timeout has returned control to the user.
element('stop').onclick();
let grantLate;
context.navigator.mediaDevices.getUserMedia=()=>new Promise(resolve=>{grantLate=resolve;});
context.setTimeout=(fn,ms)=>setTimeout(fn,ms===15000?0:ms);
await element('start').onclick();
assert.match(element('status').textContent,/permission timed out/);
assert.equal(element('start').disabled,false);
const stoppedBeforeLate=stopped;
grantLate(stream); await new Promise(resolve=>setTimeout(resolve,0));
assert.equal(stopped,stoppedBeforeLate+1,'Late camera permission releases its tracks');
uid='22'; const before=requests.filter(p=>p==='/api/capture/progress').length;
await intervals[0](); assert.match(element('status').textContent,/Account changed/);
assert.ok(stopped>0); assert.equal(outbox.entries().length,1);
assert.equal(requests.filter(p=>p==='/api/capture/progress').length,before,'Never submit another account report');
expired=true; await intervals[0](); assert.equal(element('capture').disabled,true);
assert.equal(outbox.entries().length,1,'Expiry preserves pending reps');
console.log('Cloud camera controller passed: permission/model errors, webcam switching, competing camera, network recovery, account switch and expired session.');
