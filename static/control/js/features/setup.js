import {json, save} from '../api.js';
import {selectedTriggers} from '../state.js';
import {$, jumpTo, diagnosticRow, escapeHtml} from '../render.js';

export function initSetup(ctx) {
let guideLoaded=false,guideBusy=false,guideWasComplete=false;
$('setupOverlay').value=location.origin+'/overlay';
$('setupConnect').onclick=()=>jumpTo($('login'));
$('setupTriggers').onclick=()=>{ $('supportCard').open=true;jumpTo($('reward')) };
$('setupCopy').onclick=async()=>{try{await navigator.clipboard.writeText($('setupOverlay').value);$('setupMessage').textContent='Copied. Paste into an OBS Browser Source.'}catch{$('setupMessage').textContent='Clipboard unavailable. Select and copy the URL manually.'}};
async function refreshGuide(){if(guideBusy)return;try{const [d,h]=await Promise.all([json('/api/settings'),json('/api/diagnostics')]);if(guideBusy)return;const s=d.settings;if(!guideLoaded){$('setupCamera').checked=s.setup_camera_confirmed==='1';$('setupObs').checked=s.setup_obs_confirmed==='1';$('setupGuide').open=s.setup_dismissed!=='1';guideLoaded=true}const connected=d.twitch.state==='connected';const selectedReward=!!s.target_reward_id;const sources=['subs','bits','streamlabs','streamelements'].filter(k=>s[k+'_enabled']==='1');const rules=selectedTriggers(s,h).ready;$('setupTwitch').textContent=connected?'✓ Twitch connected':'○ Connect your Twitch account';$('setupRules').textContent=rules?'✓ Selected triggers are listening':selectedReward||sources.length?'○ Some selected triggers are not listening':'○ Choose a reward or enable support rules';const total=Number(connected)+Number(rules)+Number($('setupCamera').checked)+Number($('setupObs').checked);$('setupProgress').textContent=total===4?'✓ Complete':total+' / 4';$('setupTitle').textContent=total===4?'Setup complete':'Quick setup';$('setupSummary').textContent=total===4?'Camera & OBS checked · Triggers listening · Manage':'Complete the steps below';if(total===4&&!guideWasComplete)$('setupGuide').open=false;guideWasComplete=total===4;$('setupFinish').disabled=total!==4}catch{$('setupMessage').textContent='Setup status unavailable. Check that the app is still running.';$('setupFinish').disabled=true}}
async function saveGuide(values){guideBusy=true;try{await save(values);$('setupMessage').textContent='Setup progress saved.';return true}catch(e){$('setupMessage').textContent=e.message;return false}finally{guideBusy=false;refreshGuide()}}
$('setupCamera').onchange=async()=>{if(!await saveGuide({setup_camera_confirmed:$('setupCamera').checked?'1':'0'}))$('setupCamera').checked=!$('setupCamera').checked};
$('setupObs').onchange=async()=>{if(!await saveGuide({setup_obs_confirmed:$('setupObs').checked?'1':'0'}))$('setupObs').checked=!$('setupObs').checked};
for(const id of ['setupFinish','setupLater'])$(id).onclick=async()=>{if(await saveGuide({setup_dismissed:'1'}))$('setupGuide').open=false};
refreshGuide();setInterval(refreshGuide,10000);

}
