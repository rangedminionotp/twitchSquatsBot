import assert from 'node:assert/strict';
import {cameraPresentation} from '../../static/control/js/state.js';
import {renderSetupReadiness, renderConnectionHealth, createWorkspaceHistory} from '../../static/control/js/render.js';

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
  assert.equal(nodes.get('readinessSummary').hidden,false);
  assert.equal(nodes.get('readinessStep2').querySelector('.hint').textContent,'Check framing');
  assert.equal(nodes.get('setupReadiness').dataset.complete,'false');
  renderSetupReadiness([true,true,true,true]);
  assert.equal(nodes.get('readinessTitle').textContent,'Setup complete');
  assert.equal(nodes.get('continueSetup').textContent,'Manage setup');
  assert.equal(nodes.get('setupReadiness').dataset.complete,'true');
  assert.equal(nodes.get('readinessSummary').hidden,true,'Completed setup needs no repeated caption');
  assert.equal(nodes.get('readinessStep3').querySelector('.hint').textContent,'Overlay confirmed');
  renderSetupReadiness([false,false,false,false]);
  assert.equal(nodes.get('readinessTitle').textContent,'Setup · 0 of 4');
  assert.equal(nodes.get('readinessStep0').querySelector('.step-number').textContent,'1');
} finally { delete globalThis.document; }
console.log('28 workspace presentation assertions passed');

// Health rows keep real failures visible without repeating healthy captions.
function node() { return {children:[],dataset:{},textContent:'',append(...children){this.children.push(...children)},replaceChildren(){this.children=[]}}; }
globalThis.document={createElement:node};
try {
  const parent=node();
  renderConnectionHealth(parent,{connection:{state:'connected',message:'Listening for events'},listeners:[
    {name:'Channel Points',state:'ready',message:'Listening'},
    {name:'Subs / gifts',state:'attention',message:'Missing permission; reconnect'},
    {name:'Bits',state:'disabled',message:'Disabled'}
  ]},{streamlabs:'Disabled',streamelements:'Connection failed <error>'});
  assert.equal(parent.children.length,6);
  assert.equal(parent.children[0].children[1].textContent,'Connected');
  assert.equal(parent.children[0].children.length,2);
  assert.equal(parent.children[1].children[1].dataset.tone,'good');
  assert.equal(parent.children[2].children[2].textContent,'Missing permission; reconnect');
  assert.equal(parent.children[3].children[1].dataset.tone,'muted');
  assert.equal(parent.children[4].children[0].textContent,'Streamlabs');
  assert.equal(parent.children[5].children[2].textContent,'Connection failed <error>');
  renderConnectionHealth(parent,{connection:{state:'disconnected',message:'Reconnect Twitch'},listeners:[]});
  assert.equal(parent.children.length,1);
  assert.equal(parent.children[0].children[1].dataset.tone,'warning');
  assert.equal(parent.children[0].children[2].textContent,'Reconnect Twitch');
} finally { delete globalThis.document; }
console.log('Settings health presentation passed: connected, disabled, failures and refresh.');

// Shortcuts reveal the right destination without clicking auth or enable controls.
const targetIds=['login','reward','subs_settings','bits_settings','streamlabs_settings','streamelements_settings'];
const destinations=new Map(targetIds.map(id=>[id,{
  parentElement:{tagName:'DETAILS',open:false,parentElement:null},
  connection:{open:false},
  querySelector(){return this.connection;},
  scrollIntoView(){this.scrolled=true;},
  focus(){this.focused=true;},
  click(){throw Error('Navigation must not activate settings');}
}]));
globalThis.document={createElement:node,getElementById:id=>destinations.get(id)};
try {
  const parent=node();
  const health={connection:{state:'connected'},listeners:[{name:'Channel Points',state:'ready'},{name:'Subs / gifts',state:'ready'},{name:'Bits',state:'disabled'}]};
  renderConnectionHealth(parent,health,{streamlabs:'Disabled',streamelements:'Listening'});
  for (const [index,id] of targetIds.entries()) {
    const link=parent.children[index];let prevented=false;
    assert.equal(link.href,'#'+id);
    link.onclick({preventDefault(){prevented=true;}});
    const target=destinations.get(id);
    assert.equal(prevented,true);
    assert.equal(target.scrolled,true);
    assert.equal(target.focused,true);
    assert.equal(target.parentElement.open,true);
    assert.equal(target.connection.open,true);
  }
  // A focused shortcut remains focused after diagnostic polling replaces rows.
  const old=parent.children[4];
  document.activeElement={closest:()=>old};parent.contains=value=>value===old;
  document.createElement=()=>({...node(),focus(){this.focused=true;}});
  renderConnectionHealth(parent,health,{streamlabs:'Disabled'});
  assert.equal(parent.children[4].focused,true);
  destinations.delete('streamlabs_settings');
  assert.doesNotThrow(()=>parent.children[4].onclick({preventDefault(){}}));
} finally { delete globalThis.document; }
console.log('Connection shortcuts passed: six destinations, non-mutating navigation and focus preservation.');

// In-app and browser Back share the same entries and preserve the Settings origin.
const historyEntries=[{unrelated:'preserved'}];let historyIndex=0;
let visibleView={page:'live',scrollY:0}, restoreCalled=false, controller;
const fakeHistory={
  get state(){return historyEntries[historyIndex];},
  replaceState(state){historyEntries[historyIndex]=state;},
  pushState(state){historyEntries.splice(++historyIndex);historyEntries.push(state);},
  back(){historyIndex--;controller.restore(this.state);},
  forward(){historyIndex++;controller.restore(this.state);}
};
const adapter={validPage:key=>['live','settings','integrations','rewards','activity'].includes(key),
  snapshot:()=>visibleView,render:(view,restore)=>{visibleView={...view};restoreCalled=restore;}};
controller=createWorkspaceHistory(fakeHistory,adapter);
controller.restore(fakeHistory.state);
assert.equal(visibleView.page,'live');
assert.equal(fakeHistory.state.unrelated,'preserved');
controller.go('settings');visibleView.scrollY=456;
controller.go('integrations',{fromSettings:'streamlabs_settings',focusId:'streamlabs_settings'});
assert.equal(visibleView.returnToSettings,true);
assert.equal(restoreCalled,false);
controller.back();
assert.equal(visibleView.page,'settings');
assert.equal(visibleView.scrollY,456);
assert.equal(visibleView.connectionTarget,'streamlabs_settings');
assert.equal(restoreCalled,true);
fakeHistory.forward();
assert.equal(visibleView.page,'integrations');
assert.equal(visibleView.returnToSettings,true);
fakeHistory.back();
controller.go('rewards',{fromSettings:'reward',focusId:'reward'});
assert.equal(visibleView.returnToSettings,true);
const lengthBefore=historyEntries.length;
assert.equal(controller.go('rewards'),false);
assert.equal(historyEntries.length,lengthBefore,'Same workspace must not duplicate history');
controller.go('activity');assert.equal(visibleView.returnToSettings,false);
const indexBefore=historyIndex;controller.back();assert.equal(historyIndex,indexBefore,'No contextual back outside shortcut');
assert.equal(controller.go('invalid'),false);
controller=createWorkspaceHistory(fakeHistory,adapter);controller.restore(fakeHistory.state);
assert.equal(visibleView.page,'activity','Reload preserves the selected workspace');
console.log('Workspace history passed: contextual Back, browser Back/Forward, scroll origin, duplicate prevention and reload.');
