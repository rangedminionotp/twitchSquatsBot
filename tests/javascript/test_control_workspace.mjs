import assert from 'node:assert/strict';
import {cameraPresentation} from '../../static/control/js/state.js';
import {renderSetupReadiness} from '../../static/control/js/render.js';

const camera = {page_connected:true, mode:'capture', telemetry:{camera_live:true,storage_ok:true,actual_mode:'capture',model_ready:true,body_detected:true}};
assert.equal(cameraPresentation(camera).label, 'Capture ready');
assert.equal(cameraPresentation(camera).ready, true);
assert.equal(cameraPresentation({...camera,page_connected:false}).label, 'Window closed');
for (const [patch,label] of [
  [{camera_live:false},'Camera off'],
  [{model_ready:false},'Loading pose model'],
  [{body_detected:false},'Step into frame'],
  [{storage_ok:false},'Saving unavailable'],
  [{error_code:'permission_denied'},'Permission denied'],
  [{error_code:'camera_unavailable'},'Camera unavailable'],
  [{error_code:'model_failed'},'Pose model unavailable'],
]) {
  const result = cameraPresentation({...camera,telemetry:{...camera.telemetry,...patch}});
  assert.equal(result.label,label);
  assert.equal(result.ready,false);
}
assert.equal(cameraPresentation({...camera,mode:'webcam',telemetry:{...camera.telemetry,actual_mode:'webcam'}}).label,'Webcam live');
assert.equal(cameraPresentation({...camera,telemetry:{...camera.telemetry,actual_mode:'webcam'}}).label,'Loading pose model');

// A minimal DOM for the presentation-only setup renderer. No API or account data.
const nodes = new Map();
for (const id of ['setupReadiness','readinessTitle','readinessSummary','continueSetup',...Array.from({length:4},(_,i)=>'readinessStep'+i)]) {
  const children = new Map([['.step-number',{textContent:''}],['.hint',{textContent:''}]]);
  nodes.set(id,{textContent:'',dataset:{},querySelector:selector=>children.get(selector)});
}
globalThis.document = {getElementById:id=>nodes.get(id)};
try {
  renderSetupReadiness([true,true,false,false]);
  assert.equal(nodes.get('readinessTitle').textContent,'Setup · 2 of 4');
  assert.equal(nodes.get('readinessStep2').querySelector('.hint').textContent,'Check framing');
  assert.equal(nodes.get('setupReadiness').dataset.complete,'false');
  renderSetupReadiness([true,true,true,true]);
  assert.equal(nodes.get('readinessTitle').textContent,'Setup complete');
  assert.equal(nodes.get('continueSetup').textContent,'Manage setup');
  assert.equal(nodes.get('setupReadiness').dataset.complete,'true');
  assert.equal(nodes.get('readinessStep3').querySelector('.hint').textContent,'Overlay confirmed');
  renderSetupReadiness([false,false,false,false]);
  assert.equal(nodes.get('readinessTitle').textContent,'Setup · 0 of 4');
  assert.equal(nodes.get('readinessStep0').querySelector('.step-number').textContent,'1');
} finally { delete globalThis.document; }
console.log('28 workspace presentation assertions passed');
