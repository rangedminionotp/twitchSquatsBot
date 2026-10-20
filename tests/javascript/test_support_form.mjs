import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const source=await readFile(new URL('../../static/control/js/features/support.js',import.meta.url),'utf8');
async function form(supportsBundles=true) {
  const nodes=new Map(),writes=[];
  class Element {
    constructor(){this.value='';this.checked=false;this.disabled=false;this.children=[];}
    append(node){this.children.push(node);}
    querySelector(){return null;}
    set innerHTML(html){
      for(const match of html.matchAll(/<(?:input|fieldset|p)\b([^>]*\bid="([^"]+)"[^>]*)>/g)){
        const node=new Element();node.value=/\bvalue="([^"]*)"/.exec(match[1])?.[1]||'';
        node.disabled=/\bdisabled\b/.test(match[1]);nodes.set(match[2],node);
      }
    }
  }
  for(const id of ['supportRules','supportForm','supportMessage'])nodes.set(id,new Element());
  const settings={subs_enabled:'1',subs_squats:'10',bits_enabled:'1',bits_unit:'100',bits_squats:'1',
    bits_bundle_enabled:'1',bits_bundle_unit:'1000',bits_bundle_squats:'15',
    streamlabs_enabled:'0',streamlabs_squats:'1',streamlabs_unit:'1',streamlabs_currency:'USD',
    streamelements_enabled:'0',streamelements_squats:'1',streamelements_unit:'1',streamelements_currency:'USD'};
  if(!supportsBundles)for(const key of ['bits_bundle_enabled','bits_bundle_unit','bits_bundle_squats'])delete settings[key];
  const context=vm.createContext({document:{createElement:()=>new Element()},nodes,setInterval(){},
    json:async()=>({settings,twitch:{message:'Listening'}}),
    save:async values=>{writes.push(values);Object.assign(settings,values);}});
  const module=new vm.SourceTextModule(source,{context});
  await module.link(path=>new vm.SourceTextModule(path.includes('api.js')?
    'export const json=globalThis.json, save=globalThis.save;':'export const $=id=>nodes.get(id)??null;',{context}));
  await module.evaluate();module.namespace.initSupport({});
  await new Promise(resolve=>setImmediate(resolve));
  const submit=async()=>nodes.get('supportForm').onsubmit({preventDefault(){},submitter:new Element()});
  return {nodes,writes,submit};
}
const current=await form();
assert.equal(current.nodes.get('bits_bundle_enabled').checked,true);
assert.equal(current.nodes.get('bits_bundle_fields').disabled,false);
assert.equal(current.nodes.get('bits_bundle_unit').value,'1000');
assert.equal(current.nodes.get('bits_bundle_squats').value,'15');
assert.equal(current.nodes.get('streamlabs_fields').disabled,true);
await current.submit();
assert.equal(current.writes[0].bits_bundle_enabled,'1');
assert.equal(current.writes[0].bits_bundle_unit,'1000');
assert.equal(current.writes[0].bits_bundle_squats,'15');
assert.equal(current.writes[0].subs_squats,'10');
assert.equal(current.writes[0].streamlabs_enabled,'0');
assert.equal(Object.hasOwn(current.writes[0],'streamlabs_token'),false,'Blank does not overwrite a token');
current.nodes.get('bits_bundle_enabled').checked=false;
current.nodes.get('bits_bundle_enabled').onchange();
assert.equal(current.nodes.get('bits_bundle_fields').disabled,true);
await current.submit();assert.equal(current.writes[1].bits_bundle_enabled,'0');
const old=await form(false);
old.nodes.get('bits_bundle_enabled').checked=true;
await old.submit();assert.equal(old.writes.length,0,'Do not enable a bundle against an old server');
assert.match(old.nodes.get('supportMessage').textContent,/Restart Squat Capture/);
console.log('Support form passed: saved bundle values, toggles, payloads, token preservation and old-server guard.');
