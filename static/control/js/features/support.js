import {json, save} from '../api.js';
import {$} from '../render.js';

export function initSupport(ctx) {
  const sources=[['subs','Twitch subs','New / gifted sub'],['bits','Twitch Bits','Bits'],['streamlabs','Streamlabs','donation'],['streamelements','StreamElements','donation']];
  const suffixes=['_squats','_unit','_currency','_channel','_bundle_unit','_bundle_squats'];
  let loaded=false, bundlesSupported=false;
  for(const [key,title,unit] of sources) {
    const block=document.createElement('div');
    block.className='field connection-destination';block.id=key+'_settings';block.tabIndex=-1;
block.innerHTML=`<div class="switch-row"><strong>${title}</strong><label class="switch"><input type="checkbox" id="${key}_enabled" aria-label="Enable ${title}"><span class="slider"></span></label></div><fieldset id="${key}_fields" disabled><div class="grid2">${key==='subs'?'<p class="hint" style="align-self:center">Each new / gifted sub</p>':`<div class="field"><label for="${key}_unit">Per ${unit==='Bits'?'Bits':'amount'}</label><input class="control" id="${key}_unit" type="number" min="${key==='bits'?'1':'0.01'}" step="${key==='bits'?'1':'0.01'}" required></div>`}<div class="field"><label for="${key}_squats">+ Squats owed</label><input class="control" id="${key}_squats" type="number" min="1" step="1" required></div></div>${key==='streamlabs'||key==='streamelements'?`<div class="field"><label for="${key}_currency">Currency</label><input class="control" id="${key}_currency" maxlength="3" placeholder="USD" required></div><details class="counter-edit"><summary>Connection settings <span class="chevron" aria-hidden="true"></span></summary><div class="field"><label for="${key}_token">${key==='streamlabs'?'Socket token':'JWT token'}</label><input class="control" id="${key}_token" type="password" autocomplete="new-password" placeholder="Paste token (stored locally)"></div>${key==='streamelements'?'<div class="field"><label for="streamelements_channel">Channel ID</label><input class="control" id="streamelements_channel" placeholder="StreamElements channel ID"></div>':''}<p class="hint"><a target="_blank" rel="noopener noreferrer" href="${key==='streamlabs'?'https://dev.streamlabs.com/v1/docs/socket-api':'https://docs.streamelements.com/websockets'}">Where to find credentials ↗</a> · Blank keeps saved token.</p></details>`:''}</fieldset><p class="hint" id="${key}_status"></p>`;
    $('supportRules').append(block);
    if(key==='bits') {
      const bundle=document.createElement('div');bundle.className='counter-edit';
      bundle.innerHTML='<div class="switch-row"><strong>Large Cheer bundle</strong><label class="switch"><input type="checkbox" id="bits_bundle_enabled" aria-label="Enable large Cheer bundle"><span class="slider"></span></label></div><fieldset id="bits_bundle_fields" disabled><div class="grid2"><div class="field"><label for="bits_bundle_unit">Bits per bundle</label><input class="control" id="bits_bundle_unit" type="number" min="1" step="1" value="1000" required></div><div class="field"><label for="bits_bundle_squats">Squats per bundle</label><input class="control" id="bits_bundle_squats" type="number" min="1" step="1" value="15" required></div></div></fieldset><p class="hint">Per Cheer: full bundles first, then remaining Bits at the base rate. Smaller remainders do not carry over.</p>';
      $(key+'_fields').append(bundle);
      $('bits_bundle_enabled').onchange=()=>{$('bits_bundle_fields').disabled=!$('bits_bundle_enabled').checked;};
    }
    const connection=block.querySelector('details');
    if(connection)connection.classList.add('support-connection');
    $(key+'_enabled').onchange=()=>{$(key+'_fields').disabled=!$(key+'_enabled').checked;};
  }
  async function refreshSupport() {
    try {
      const data=await json('/api/settings');
      bundlesSupported=Object.hasOwn(data.settings,'bits_bundle_enabled');
      if(!loaded) {
        for(const [key] of sources) {
          $(key+'_enabled').checked=data.settings[key+'_enabled']==='1';
          $(key+'_fields').disabled=!$(key+'_enabled').checked;
          for(const suffix of suffixes) {
            const input=$(key+suffix);
            if(input)input.value=data.settings[key+suffix] ?? input.value ?? '';
          }
          if($(key+'_token'))$(key+'_token').placeholder=data.settings[key+'_token']?'Saved token · leave blank to keep':'Paste token (stored locally)';
        }
        $('bits_bundle_enabled').checked=data.settings.bits_bundle_enabled==='1';
        $('bits_bundle_fields').disabled=!$('bits_bundle_enabled').checked;
        loaded=true;
      }
      for(const [key] of sources)$(key+'_status').textContent=data.settings[key+'_enabled']!=='1'?'Disabled':(data.support?.[key]||data.twitch.message);
    } catch(error) { $('supportMessage').textContent=error.message; }
  }
  $('supportForm').onsubmit=async event=>{
    event.preventDefault();const button=event.submitter;button.disabled=true;
    try {
      if($('bits_enabled').checked && $('bits_bundle_enabled').checked && !bundlesSupported)throw Error('Restart Squat Capture before enabling the new Bits bundle rule.');
      const values={};
      for(const [key] of sources) {
        values[key+'_enabled']=$(key+'_enabled').checked?'1':'0';
        for(const suffix of [...suffixes,'_token']) {
          const input=$(key+suffix);
          if(input && (suffix!=='_token' || input.value.trim()))values[key+suffix]=input.value;
        }
      }
      values.bits_bundle_enabled=$('bits_bundle_enabled').checked?'1':'0';
      await save(values);
      for(const key of ['streamlabs','streamelements'])$(key+'_token').value='';
      $('supportMessage').textContent='Saved. If Sub / Bits were just enabled, reconnect Twitch if permissions are missing.';
      await refreshSupport();
    } catch(error) { $('supportMessage').textContent=error.message; }
    finally { button.disabled=false; }
  };
  refreshSupport();setInterval(refreshSupport,10000);
}
