export const $ = id => document.getElementById(id);
export function jumpTo(element){for(let parent=element.parentElement;parent;parent=parent.parentElement){if(parent.tagName==='DETAILS')parent.open=true}element.scrollIntoView({behavior:'smooth',block:'center'});element.focus()}
export function diagnosticRow(parent,title,detail,good=false){const row=document.createElement('div');row.className='status'+(good?' good':'');const head=document.createElement('strong');head.textContent=title;const body=document.createElement('div');body.textContent=detail;row.append(head,body);parent.append(row)}
export function escapeHtml(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}
export function arrangeConsole(){
const queueCard=document.createElement('section');queueCard.className='card';queueCard.innerHTML='<h2>Challenge queue</h2><p class="hint">Redeems add to overall owed once. Start manually; subs / tips never join this queue.</p><div id="queueItems"></div><div class="actions"><button class="btn btn-primary" id="queueStart">Start / resume queue</button><button class="btn btn-ghost" id="queuePause">Pause · Webcam</button></div><p id="queueMessage" class="hint" role="status"></p>';
// Keep existing controls and event IDs when composing the live console.
function compose(){
  const layout=document.querySelector('.layout'), left=layout.querySelector('.stack'), side=layout.querySelector('.side');
  const progress=$('owed').closest('section'), camera=$('cameraControlStatus').closest('section');
  const account=$('login').closest('section'), health=$('healthRows').closest('section');
  const league=$('riotEnabled').closest('details.card'), test=$('ruleTest').closest('details.card');
  const activity=$('activityRows').closest('details.card'), stream=$('overlayUrl').closest('section');
  const live=document.createElement('section');live.className='card live-console';live.id='liveConsole';live.setAttribute('aria-labelledby','liveTitle');
  live.innerHTML='<div class="live-heading"><h2 id="liveTitle">Live challenge</h2><span id="liveState" class="live-state" role="status">Checking camera…</span></div><div id="liveTotals"></div><div class="live-actions" id="liveActions"></div><div class="queue-progress"><progress id="challengeProgress" value="0" max="1" aria-label="Current challenge progress"></progress><span id="challengeProgressText">No active challenge</span></div><div class="live-bottom"><div id="liveQueue"><h3>Challenge queue <span id="queueCount" class="badge">0 waiting</span></h3></div><div id="liveCamera"><h3>Camera</h3><p id="cameraSummary" class="hint">Checking camera…</p></div></div>';
  document.querySelector('.topbar').after(live);
  $('liveTotals').append(progress.querySelector('.stat-grid'));
  $('liveActions').append(queueCard.querySelector('#queueStart'),queueCard.querySelector('#queuePause'));
  const cameraLink=camera.querySelector('a');cameraLink.className='btn btn-ghost';cameraLink.textContent='Open camera ↗';$('liveActions').append(cameraLink);
  $('queueStart').textContent='Start challenge';$('queuePause').textContent='Pause challenge';
  $('liveQueue').append(queueCard.querySelector('#queueMessage'));
  const queueDetails=document.createElement('details');queueDetails.innerHTML='<summary>View queue <span class="chevron">⌄</span></summary>';
  queueDetails.append(queueCard.querySelector('#queueItems'));$('liveQueue').append(queueDetails);
  const modes=camera.querySelector('.actions');modes.className='camera-modes';$('liveCamera').append(modes);
  $('cameraCapture').className='btn btn-ghost';$('cameraCapture').textContent='Free capture';$('cameraWebcam').className='btn btn-ghost';
  const cameraDetails=document.createElement('details');cameraDetails.innerHTML='<summary>Camera details &amp; help <span class="chevron">⌄</span></summary>';
  cameraDetails.append($('cameraControlStatus'),camera.querySelector('.hint'));$('liveCamera').append(cameraDetails);
  live.append(progress.querySelector('.counter-edit'));progress.remove();camera.remove();
  const guide=$('setupGuide');guide.classList.add('setup-strip');guide.querySelector('h2').id='setupTitle';
  const guideHint=document.createElement('span');guideHint.className='hint';guideHint.id='setupSummary';guide.querySelector('.chevron').before(guideHint);
  $('setupConnect').textContent='Manage Twitch account';$('setupLater').textContent='Skip setup for now';$('setupFinish').className='btn btn-secondary';
  const advanced=document.createElement('details');advanced.className='card advanced';advanced.id='advancedSettings';
  advanced.innerHTML='<summary><h2>Settings &amp; diagnostics</h2><span class="hint">Account · integrations · health</span><span class="chevron">⌄</span></summary><div class="advanced-body"></div>';
  layout.after(advanced);advanced.querySelector('.advanced-body').append(account,health,league,test);
  account.querySelector('h2').textContent='Twitch account';$('login').className='btn btn-secondary';health.querySelector('.hint').textContent='Login and event listening are checked separately. Reconnect in Twitch account if permissions are missing.';$('healthRows').className='health-list';
  const headerActions=document.createElement('div');headerActions.className='header-actions';document.querySelector('.topbar').append(headerActions);headerActions.append($('connectionPill'));
  const manage=document.createElement('button');manage.className='btn btn-text';manage.textContent='Settings';manage.onclick=()=>jumpTo($('login'));headerActions.append(manage);
  $('connection').textContent='';$('connection').setAttribute('role','status');$('saveReward').className='btn btn-secondary';
  stream.querySelector('h2').textContent='Camera & OBS';stream.querySelector('a[href="/squat-popup"]').remove();
  stream.querySelector('.quick-links').firstElementChild.querySelector('.link-label').lastChild.textContent=' Open counter overlay';
  const privacy=document.querySelector('.privacy');stream.append(privacy);
  side.prepend(stream);activity.open=true;side.append(activity);
  $('ruleTest').querySelector('button[type="submit"]').className='btn btn-secondary';
}
compose();

}
