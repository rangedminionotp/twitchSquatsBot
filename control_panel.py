CONTROL_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Squat Capture Setup</title><style>
:root{color-scheme:dark;--bg:#0d1016;--panel:#171d29;--accent:#66f0c9;--muted:#95a5c2}*{box-sizing:border-box}
body{margin:0;background:radial-gradient(circle at top,#172638,var(--bg) 55%);color:#f5f7fb;font:16px system-ui,sans-serif}
main{max-width:820px;margin:auto;padding:36px 20px}.card{background:rgba(23,29,41,.94);border:1px solid #293344;border-radius:18px;padding:22px;margin:16px 0}
h1{margin:0 0 6px}h2{font-size:18px}.muted{color:var(--muted)}label{display:block;margin:14px 0 5px}input,select,button{width:100%;padding:12px;border-radius:10px;border:1px solid #39465b;background:#0f141e;color:white;font:inherit}
button{background:var(--accent);color:#07110e;border:0;font-weight:700;cursor:pointer;margin-top:12px}.secondary{background:#2a3547;color:white}.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.status{padding:12px;border-radius:10px;background:#101722;white-space:pre-wrap}.ok{color:var(--accent)}a{color:var(--accent)}@media(max-width:600px){.row{grid-template-columns:1fr}}
</style></head><body><main><h1>Squat Capture</h1><div class="muted">Connect Twitch, select a reward, and add the overlay to OBS.</div>
<section class="card"><h2>1. Twitch application</h2><label>Client ID</label><input id="clientId" placeholder="Create an app at dev.twitch.tv and paste its Client ID">
<button id="save">Save settings</button><button class="secondary" id="login">Connect with Twitch</button><div id="loginHelp" class="status">Login has not started</div></section>
<section class="card"><h2>2. Channel and reward</h2><div id="connection" class="status">Loading status…</div><label>Channel Points reward to watch</label><select id="reward"><option value="">Connect Twitch to load rewards</option></select><button id="saveReward">Save reward</button></section>
<section class="card"><h2>3. Stream pages</h2><div class="row"><a target="_blank" href="/squat-popup">Open action capture</a><a target="_blank" href="/overlay">Open OBS overlay</a></div>
<label>OBS Browser Source URL</label><input id="overlayUrl" readonly><button class="secondary" id="copy">Copy URL</button></section>
<section class="card"><h2>Persistent counters</h2><div class="row"><div><label>Squats owed</label><div id="owed" class="status">0</div></div><div><label>Squats completed</label><div id="completed" class="status ok">0</div></div></div><label>Set squats owed</label><input id="owedInput" type="number" min="0" step="1" value="0"><button id="setOwed">Set owed counter</button><label>Correct completed total</label><input id="completedInput" type="number" min="0" step="1" value="0"><button class="secondary" id="setCompleted">Set completed counter</button><div id="counterMessage" class="muted">Each captured squat subtracts one owed squat and adds one completed squat. Both totals survive restarts.</div></section>
<section class="card"><h2>Running the app</h2><div class="muted">Keep this program running while streaming. Camera processing happens only inside the action-capture page; video is not uploaded to the local service.</div></section>
</main><script>
const $=id=>document.getElementById(id);let settings={};
async function json(url,options){const r=await fetch(url,options);const body=await r.json();if(!r.ok)throw Error(body.error||('HTTP '+r.status));return body}
async function refresh(){try{const data=await json('/api/settings');settings=data.settings;$('clientId').value=settings.twitch_client_id||'';$('overlayUrl').value=location.origin+'/overlay';
$('connection').textContent=(settings.broadcaster_login?'Channel: '+settings.broadcaster_login+'\n':'')+'Status: '+data.twitch.message;$('connection').className='status '+(data.twitch.state==='connected'?'ok':'');
const stats=await json('/api/stats');$('owed').textContent=String(stats.owed_squats||0)+' squats';$('completed').textContent=String(stats.completed_squats||0)+' squats';if(document.activeElement!==$('owedInput'))$('owedInput').value=String(stats.owed_squats||0);if(document.activeElement!==$('completedInput'))$('completedInput').value=String(stats.completed_squats||0);
if(settings.twitch_access_token){await loadRewards()}}catch(e){$('connection').textContent=e.message}}
async function save(extra={}){return json('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.assign({twitch_client_id:$('clientId').value},extra))})}
async function loadRewards(){try{const data=await json('/api/twitch/rewards');$('reward').innerHTML='<option value="">Select a reward</option>'+data.rewards.map(r=>'<option value="'+r.id+'">'+escapeHtml(r.title)+' ('+r.cost+' points)</option>').join('');$('reward').value=settings.target_reward_id||''}catch(e){$('connection').textContent+='\nCould not load rewards: '+e.message}}
function escapeHtml(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}
$('save').onclick=async()=>{try{await save();$('loginHelp').textContent='Settings saved'}catch(e){$('loginHelp').textContent=e.message}};
$('login').onclick=async()=>{try{await save();const d=await json('/api/twitch/login',{method:'POST'});$('loginHelp').innerHTML='Open '+d.verification_uri+' and enter this code: <b>'+d.user_code+'</b>';window.open(d.verification_uri,'_blank');poll()}catch(e){$('loginHelp').textContent=e.message}};
function poll(){const timer=setInterval(async()=>{await refresh();if(settings.twitch_access_token){clearInterval(timer);$('loginHelp').textContent='Twitch connected';}},2000)}
$('saveReward').onclick=async()=>{const option=$('reward').selectedOptions[0];try{await save({target_reward_id:$('reward').value,target_reward_title:option&&option.value?option.textContent.replace(/ \([0-9]+ points\)$/,''):''});$('connection').textContent+='\nReward saved'}catch(e){$('connection').textContent=e.message}};
async function setCounter(field,input){try{const value=Number($(input).value);if(!Number.isInteger(value)||value<0)throw Error('Enter a non-negative whole number');const stats=await json('/api/stats',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({[field]:value})});$('owed').textContent=String(stats.owed_squats)+' squats';$('completed').textContent=String(stats.completed_squats)+' squats';$('counterMessage').textContent='Counters updated'}catch(e){$('counterMessage').textContent=e.message}}
$('setOwed').onclick=()=>setCounter('owed_squats','owedInput');$('setCompleted').onclick=()=>setCounter('completed_squats','completedInput');
$('copy').onclick=()=>navigator.clipboard.writeText($('overlayUrl').value);refresh();setInterval(refresh,10000);
</script></body></html>"""
