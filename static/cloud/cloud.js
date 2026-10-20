import {renderDonations} from './donations.js';
let csrf = '';
let rulesLoaded = false;
let listenerEnabled = false;
let activeChallenge = null;
let accountId = null;
const ruleFields = {reward_id:'rewardId', reward_reps:'rewardReps', sub_reps:'subReps', gift_reps:'giftReps', bits_unit:'bitsUnit', bits_reps:'bitsReps', bits_bundle_unit:'bitsBundleUnit', bits_bundle_reps:'bitsBundleReps'};
const $ = id => document.getElementById(id);
const overlay = document.body.classList.contains('overlay');
async function request(path, body) {
  const response = await fetch(path, body === undefined ? {cache:'no-store'} : {
    method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}, body:JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) throw Object.assign(new Error(data.error || 'Request failed'), {status:response.status});
  return data;
}
function totals(user) {
  $('owed').textContent = user.owed;
  $('lifetime').textContent = user.lifetime;
}
function streamTotals(stream) {
  $('streamCompleted').textContent = stream.state==='checking' || stream.state==='unavailable' ? '—' : stream.completed;
  $('streamState').textContent = {live:'Live',offline:'Offline · last stream retained',checking:'Checking Twitch stream',unavailable:'Twitch unavailable · lifetime still counts'}[stream.state] || 'Checking';
}
async function refresh() {
  try {
    if (overlay) {
      const data=await request('/api' + location.pathname);
      totals(data); streamTotals(data.stream);
      $('message').textContent = 'Overall owed · Twitch stream completed';
    } else {
      const data = await request('/api/me'); csrf = data.csrf;
      if (accountId && accountId!==data.user.id) { csrf=''; location.reload(); return; }
      accountId=data.user.id;
      $('login').hidden = true; $('account').hidden = false;
      $('name').textContent = 'Connected as ' + data.user.login; totals(data.user);
      streamTotals(data.stream);
      renderDonations(data.donations,data.donation_status,request);
      if (document.activeElement !== $('newOwed')) $('newOwed').value = data.user.owed;
      if (!rulesLoaded) {
        for (const [key,id] of Object.entries(ruleFields)) $(id).value = data.rules[key];
        rulesLoaded = true;
      }
      $('queue').replaceChildren();
      for (const item of data.queue) {
        const row = document.createElement('li');
        row.textContent = item.viewer + ' · ' + item.done + ' / ' + item.target + ' squats';
        $('queue').append(row);
      }
      if (!data.queue.length) $('queue').textContent = 'No queued redemptions.';
      activeChallenge = data.challenge;
      $('challengeStatus').textContent = activeChallenge
        ? `${activeChallenge.status === 'paused' ? 'Paused' : 'Prepared'} · ${activeChallenge.viewer} · ${activeChallenge.done} / ${activeChallenge.target} · ${activeChallenge.camera_connected ? 'Camera lease connected' : 'Open Camera and select Capture'}`
        : 'No active challenge. Challenges start one at a time.';
      $('challengeStart').textContent = activeChallenge?.status === 'paused' ? 'Resume challenge' : 'Start challenge';
      $('challengeStart').disabled = !data.queue.length || activeChallenge?.status === 'active' || activeChallenge?.mode === 'free';
      $('challengePause').disabled = activeChallenge?.status !== 'active';
      $('freeStart').disabled = !!activeChallenge && (activeChallenge.mode!=='free' || activeChallenge.status==='active');
      $('freeEnd').disabled = activeChallenge?.mode!=='free';
      const authLabels = {connected:'Twitch authorization verified',checking:'Checking Twitch authorization',temporarily_unavailable:'Twitch verification unavailable · retrying',reconnect_required:'Reconnect Twitch'};
      $('message').textContent = authLabels[data.authorization.state] || 'Authorization status unknown';
      listenerEnabled = !!data.event_listener.enabled;
      const listenerLabels = {disabled:'Listening off',stopping:'Stopping subscriptions',sync_pending:'Waiting to sync',listening:'Twitch events listening',missing_permission:'Authorize event permissions, then wait for sync',reconnect_required:'Reconnect Twitch',authorization_unavailable:'Checking authorization · retrying',service_unavailable:'Twitch unavailable · retrying',subscription_conflict:'Subscription conflict · needs operator review',rate_limited:'Twitch rate limit · retrying',no_rules:'Select at least one trigger rule',pending_or_attention:'Waiting for Twitch verification · if persistent, stop and re-enable listening',subscription_revoked:'Subscription revoked · review Twitch permissions'};
      $('listenerStatus').textContent = data.events_available ? (listenerLabels[data.event_listener.message] || 'Checking listener') : 'Live events are not enabled on this server.';
      $('eventAuthorize').hidden = !data.events_available;
      $('listenerToggle').disabled = !data.events_available && !listenerEnabled;
      $('listenerToggle').textContent = listenerEnabled ? 'Stop listening' : 'Enable listening';
    }
  } catch (error) {
    if (!overlay && error.status === 401) {
      csrf = ''; $('account').hidden = true; $('login').hidden = false;
      $('message').textContent = 'Sign in to continue. Your session may have expired or Twitch authorization may have been revoked.';
    } else $('message').textContent = error.message + ' · displayed values may be outdated';
  }
}
if (!overlay) {
  $('deleteAccount').onclick=async()=>{
    if(!confirm('Permanently delete your cloud counters, queue, saved tokens and overlay links? This cannot be undone from this app.'))return;
    try{await request('/api/account/delete',{confirm:'DELETE'});location.replace('/');}
    catch(error){$('message').textContent=error.message;}
  };
  $('freeStart').onclick=async()=>{
    try { await request('/api/capture/free',{request_id:crypto.randomUUID(),target:Number($('freeTarget').value)}); await refresh(); }
    catch(error){ $('freeStatus').textContent=error.message; }
  };
  $('freeEnd').onclick=async()=>{
    if (!activeChallenge || !confirm('End this free set? Resolve pending camera reports first. Already accepted reps remain counted.')) return;
    try { await request('/api/capture/end',{run_id:activeChallenge.id}); await refresh(); }
    catch(error){ $('freeStatus').textContent=error.message; }
  };
  $('loadRewards').onclick=async()=>{
    $('loadRewards').disabled=true;
    try {
      const data=await request('/api/rewards');
      $('rewardPicker').replaceChildren(new Option('Select a reward',''),...data.rewards.map(r=>new Option(`${r.title} (${r.cost} points)${r.enabled?'':' · disabled'}`,r.id)));
      $('rewardStatus').textContent='Select a reward, then Save rules.';
    }catch(error){ $('rewardStatus').textContent=error.message; }
    finally{ $('loadRewards').disabled=false; }
  };
  $('rewardPicker').onchange=()=>{ $('rewardId').value=$('rewardPicker').value; };
  $('challengeStart').onclick = async () => {
    $('challengeStart').disabled = true;
    try { await request('/api/challenge/start', {request_id:crypto.randomUUID()}); await refresh(); }
    catch (error) { $('challengeStatus').textContent = error.message; }
  };
  $('challengePause').onclick = async () => {
    if (!activeChallenge) return;
    $('challengePause').disabled = true;
    try { await request('/api/challenge/pause', {run_id:activeChallenge.id}); await refresh(); }
    catch (error) { $('challengeStatus').textContent = error.message; }
  };
  $('rules').onsubmit = async event => {
    event.preventDefault();
    const values = Object.fromEntries(Object.entries(ruleFields).map(([key,id]) => [key,key==='reward_id' ? $(id).value.trim() : Number($(id).value)]));
    try { await request('/api/rules', values); $('rulesMessage').textContent = 'Rules saved. Enabled listeners sync within about a minute.'; }
    catch (error) { $('rulesMessage').textContent = error.message; }
  };
  $('listenerToggle').onclick = async () => {
    $('listenerToggle').disabled = true;
    try { await request('/api/listener', {enabled:!listenerEnabled}); await refresh(); }
    catch (error) { $('listenerStatus').textContent = error.message; $('listenerToggle').disabled = false; }
  };
  $('counter').onsubmit = async event => {
    event.preventDefault();
    try { totals((await request('/api/owed', {owed:Number($('newOwed').value)})).user); $('message').textContent = 'Saved.'; }
    catch (error) { $('message').textContent = error.message; }
  };
  $('rotate').onclick = async () => {
    if (!confirm('Create a new overlay link? Any previous link will stop working.')) return;
    try { const data = await request('/api/overlay/rotate', {}); $('overlayUrl').value = data.url; $('overlayUrl').hidden = false; $('overlayUrl').select(); }
    catch (error) { $('message').textContent = error.message; }
  };
  $('logout').onclick = async () => {
    try { await request('/api/logout', {}); location.replace('/'); }
    catch (error) { $('message').textContent = error.message; }
  };
}
await refresh();
setInterval(refresh, overlay ? 3000 : 10000);
