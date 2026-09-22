import {json, save} from '../api.js';
import {$, jumpTo, diagnosticRow, escapeHtml} from '../render.js';

export function initLeague(ctx) {
$('saveRiot').onclick=async()=>{try{const payload={riot_check_enabled:$('riotEnabled').checked?'1':'0',riot_accounts:$('riotAccounts').value,riot_platform_region:$('platform').value,riot_routing_region:$('routing').value};if($('riotKey').value)payload.riot_api_key=$('riotKey').value;await save(payload);$('riotKey').value='';$('riotMessage').textContent=$('riotEnabled').checked?'League gate settings saved.':'League gate disabled.'}catch(e){$('riotMessage').textContent=e.message}};
$('testRiot').onclick=async()=>{try{$('riotMessage').textContent='Checking every Riot account…';const result=await json('/api/riot/test',{method:'POST'});$('riotMessage').textContent=result.allowed?'ALL IDLE — redeems are allowed':'BLOCKED — '+result.reason}catch(e){$('riotMessage').textContent=e.message}};
function updateRiotFields(){const enabled=$('riotEnabled').checked;$('riotFields').disabled=!enabled;$('riotDisabledMessage').style.display=enabled?'none':'block';if(!enabled)$('riotMessage').textContent='Optional League gate is off.'}
$('riotEnabled').onchange=updateRiotFields;

let loaded = false;
ctx.applyLeagueSettings = settings => {
  // Polling must not overwrite an unsaved form while the user is editing.
  if (loaded) return;
  loaded = true;
  $('riotEnabled').checked = settings.riot_check_enabled === '1';
  $('riotAccounts').value = settings.riot_accounts || '';
  $('platform').value = settings.riot_platform_region || 'na1';
  $('routing').value = settings.riot_routing_region || 'americas';
  updateRiotFields();
};
}
