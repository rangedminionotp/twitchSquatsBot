// Tests the shipped capture script. No browser, network or real counters used.
const vm=require('node:vm'), assert=require('node:assert/strict');
(async()=>{
 try {
 const script=require('node:fs').readFileSync(require('node:path').join(__dirname,'../../static/capture/capture.js'),'utf8');
 const source=script.slice(script.indexOf("let cameraMode ="),script.indexOf('const captureSessionId'));
 const disk=new Map();let fail=false;
 const storage={get length(){return disk.size},key:i=>[...disk.keys()][i],getItem:k=>disk.get(k),setItem:(k,v)=>disk.set(k,v),removeItem:k=>disk.delete(k)};
 const make=()=>{const context=vm.createContext({crypto:{randomUUID:()=>Math.random().toString()},localStorage:storage,Date,AbortSignal,showError:()=>{},fetch:async()=>{if(fail)throw Error('offline');return {ok:true}}});vm.runInContext(source+`;this.api={recoverCamera,flushCameraCounts,persistCamera,cameraPending,enable:()=>cameraLeaseUntil=Date.now()+10000,storageOk:()=>cameraStorageOk};`,context);return context.api};
 const p={capture_session_id:'saved-session',count:3,queue_run:'run'};
 const first=make();first.enable();first.cameraPending.set(p.capture_session_id,p);assert.ok(first.persistCamera(p));
 fail=true;await assert.rejects(first.flushCameraCounts());assert.equal(disk.size,1);
 const reloaded=make();reloaded.recoverCamera();assert.equal(reloaded.cameraPending.size,1);reloaded.enable();fail=false;await reloaded.flushCameraCounts();assert.equal(disk.size,0);assert.equal(reloaded.cameraPending.size,0);
 storage.setItem=()=>{throw Error('quota')};assert.equal(reloaded.persistCamera(p),false);assert.equal(reloaded.storageOk(),false);
 console.log('Outbox tests passed: offline retention, reload recovery, acknowledgment cleanup, storage failure pause.');
 }catch(e){console.error(e);process.exitCode=1}
})();
