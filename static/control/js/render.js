export const $ = id => document.getElementById(id);
let revealWorkspace = () => {};
export function jumpTo(element, options = {}){revealWorkspace(element, options);for(let parent=element.parentElement;parent;parent=parent.parentElement){if(parent.tagName==='DETAILS')parent.open=true}element.scrollIntoView({behavior:'instant',block:'start'});element.focus({preventScroll:true})}
// Same-document history: moving between workspaces never reloads editable forms.
export function createWorkspaceHistory(history, {validPage, snapshot, render}) {
  const read = state => validPage(state?.squatWorkspace?.page) ? state.squatWorkspace : null;
  let view = read(history.state) || {page:'live',scrollY:0};
  function write(value, method) {
    view=value;
    history[method]({...history.state,squatWorkspace:value},'');
  }
  function save(extra = {}) { write({...view,...snapshot(),...extra},'replaceState'); }
  if (!read(history.state)) write(view,'replaceState');
  return {
    go(page, {fromSettings, focusId} = {}) {
      if (!validPage(page) || page===view.page) return false;
      const returning = view.page==='settings' && !!fromSettings;
      save(returning ? {connectionTarget:fromSettings} : {});
      write({page,scrollY:0,focusId,returnToSettings:returning},'pushState');
      render(view,false);
      return true;
    },
    back() { if (view.returnToSettings) { save(); history.back(); } },
    restore(state) {
      view=read(state) || {page:'live',scrollY:0};
      render(view,true);
    },
  };
}
export function diagnosticRow(parent,title,detail,good=false){const row=document.createElement('div');row.className='status'+(good?' good':'');const head=document.createElement('strong');head.textContent=title;const body=document.createElement('div');body.textContent=detail;row.append(head,body);parent.append(row)}
export function renderConnectionHealth(parent, health, providers = {}) {
  const activeRow = document.activeElement?.closest?.('.connection-row');
  const focusedTarget = activeRow && parent.contains(activeRow) ? activeRow.dataset.target : null;
  parent.replaceChildren();
  const targets = {Twitch:'login','Channel Points':'reward','Subs / gifts':'subs_settings',Bits:'bits_settings',Streamlabs:'streamlabs_settings',StreamElements:'streamelements_settings'};
  const labels = {connected:'Connected',ready:'Listening',disabled:'Disabled',connecting:'Connecting',disconnected:'Disconnected',attention:'Not listening'};
  function row(name, state, detail = '') {
    const normalized = String(state || 'unknown').toLowerCase();
    const good = ['connected','ready','listening'].includes(normalized);
    const disabled = normalized === 'disabled';
    const targetId = targets[name];
    const line = document.createElement(targetId ? 'a' : 'div'); line.className = 'connection-row';
    if (targetId) {
      line.href = '#' + targetId;
      line.dataset.target = targetId;
      line.title = 'Open ' + name + ' settings';
      line.onclick = event => {
        event.preventDefault();
        const target = $(targetId);
        if (!target) return;
        const connection = target.querySelector?.('.support-connection');
        if (connection) connection.open = true;
        jumpTo(target, {fromSettings:targetId});
      };
    }
    const title = document.createElement('strong'); title.textContent = name;
    const badge = document.createElement('span'); badge.className = 'connection-status';
    badge.dataset.tone = good ? 'good' : disabled ? 'muted' : 'warning';
    badge.textContent = labels[normalized] || (good ? 'Listening' : 'Check connection');
    line.append(title, badge);
    if (!good && !disabled) {
      const note = document.createElement('p'); note.className = 'hint';
      note.textContent = detail || String(state || 'Status unavailable'); line.append(note);
    }
    parent.append(line);
    // Polling should not remove keyboard focus from a settings shortcut.
    if (targetId && targetId === focusedTarget) line.focus({preventScroll:true});
  }
  row('Twitch', health.connection.state, health.connection.message);
  for (const item of health.listeners) row(item.name, item.state, item.message);
  for (const [name,state] of Object.entries(providers)) row({streamlabs:'Streamlabs',streamelements:'StreamElements'}[name] || name,state,state);
}
export function escapeHtml(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}
export function arrangeConsole(){
const queueCard=document.createElement('section');queueCard.className='card';queueCard.innerHTML='<h2>Challenge queue</h2><div id="queueItems"></div><div class="actions"><button class="btn btn-primary" id="queueStart">Start / resume queue</button><button class="btn btn-ghost" id="queuePause">Pause · Webcam</button></div><p id="queueMessage" class="hint" role="status"></p>';
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
  const queueDetails=document.createElement('details');queueDetails.innerHTML='<summary>View queue <span class="chevron" aria-hidden="true"></span></summary>';
  queueDetails.append(queueCard.querySelector('#queueItems'));$('liveQueue').append(queueDetails);
  const modes=camera.querySelector('.actions');modes.className='camera-modes';$('liveCamera').append(modes);
  $('cameraCapture').className='btn btn-ghost';$('cameraCapture').textContent='Free capture';$('cameraWebcam').className='btn btn-ghost';
  const cameraDetails=document.createElement('details');cameraDetails.innerHTML='<summary>Camera details &amp; help <span class="chevron" aria-hidden="true"></span></summary>';
  cameraDetails.append($('cameraControlStatus'),camera.querySelector('.hint'));$('liveCamera').append(cameraDetails);
  live.append(progress.querySelector('.counter-edit'));progress.remove();camera.remove();
  const guide=$('setupGuide');guide.classList.add('setup-strip');guide.querySelector('h2').id='setupTitle';
  const guideHint=document.createElement('span');guideHint.className='hint';guideHint.id='setupSummary';guide.querySelector('.chevron').before(guideHint);
  $('setupConnect').textContent='Manage Twitch account';$('setupLater').textContent='Skip setup for now';$('setupFinish').className='btn btn-secondary';
  const advanced=document.createElement('section');advanced.className='advanced settings-workspace';advanced.id='advancedSettings';
  advanced.setAttribute('aria-label','Settings');
  advanced.innerHTML='<div class="advanced-body"></div>';
  layout.after(advanced);advanced.querySelector('.advanced-body').append(account,health,league,test);
  account.querySelector('h2').textContent='Twitch account';$('login').className='btn btn-secondary';health.querySelector('.hint').textContent='Login and event listening are checked separately. Reconnect in Twitch account if permissions are missing.';$('healthRows').className='health-list';
  account.id='twitchAccountCard';
  test.id='ruleTestCard';test.open=true;
  health.querySelector('.hint').hidden=true;
  const healthHeading=health.querySelector('.card-head');healthHeading.append($('healthRefresh'));
  $('healthRefresh').textContent='Refresh';
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
arrangeWorkspace();

}

// Move existing controls, not copies: IDs, handlers and polling remain intact.
function arrangeWorkspace() {
  const shell = document.querySelector('.shell');
  const layout = document.querySelector('.layout');
  const workspace = document.createElement('div');
  workspace.className = 'workspace';
  const nav = document.createElement('nav');
  nav.className = 'sidebar';
  nav.setAttribute('aria-label', 'Console sections');
  nav.innerHTML = '<a class="sidebar-brand" href="#liveConsole" aria-label="Squat Capture home"><svg class="icon" aria-hidden="true"><use href="#i-activity"/></svg><span>Squat Capture</span></a>';
  const destinations = [
    ['Live control', 'i-activity', 'liveConsole'], ['Setup', 'i-check', 'setupGuide'],
    ['Rewards', 'i-gift', 'reward'], ['Integrations', 'i-game', 'supportCard'],
    ['Activity', 'i-clock', 'activityRows'],
  ];
  for (const [label, icon, target] of destinations) {
    const button = document.createElement('button');
    button.className = 'nav-item'; button.title = label;
    button.setAttribute('aria-label', label);
    button.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#'+icon+'"/></svg><span>'+label+'</span>';
    button.dataset.destination = target;
    nav.append(button);
  }
  nav.querySelector('.nav-item').setAttribute('aria-current', 'location');
  workspace.append(...shell.children); shell.append(nav, workspace);
  const topbar = workspace.querySelector('.topbar');
  topbar.querySelector('.brand').innerHTML = '<span class="breadcrumb">Squat Capture <span aria-hidden="true"> / </span><strong>Live control</strong></span>';
  const heading = document.createElement('div'); heading.className = 'workspace-heading';
  heading.innerHTML = '<div><h1>Live control</h1></div>';
  heading.append($('liveActions').querySelector('a'));
  heading.querySelector('a').textContent = 'Open camera window ↗';
  topbar.after(heading);

  const readiness = document.createElement('section');
  readiness.id = 'setupReadiness'; readiness.className = 'card readiness';
  readiness.setAttribute('aria-labelledby', 'readinessTitle');
  readiness.innerHTML = '<div class="readiness-heading"><div><h2 id="readinessTitle">Setup readiness</h2><p class="hint" id="readinessSummary">Checking your setup…</p></div><button class="btn btn-secondary" id="continueSetup">Continue setup</button></div><div class="readiness-steps">'+
    ['Twitch','Triggers','Camera','OBS'].map((label, index) => '<div class="readiness-step" id="readinessStep'+index+'"><span class="step-number" aria-hidden="true">'+(index+1)+'</span><div><strong>'+label+'</strong><p class="hint">Checking…</p></div></div>').join('')+'</div>';
  heading.after(readiness);
  $('continueSetup').onclick = () => { $('setupGuide').open = true; jumpTo($('setupGuide')); };
  layout.className = 'layout dashboard-grid';
  const main = layout.querySelector('.stack'); const side = layout.querySelector('.side');
  main.classList.add('main-column'); side.classList.add('tool-column');
  const live = $('liveConsole');
  const activity = $('activityRows').closest('details.card');
  activity.id = 'recentActivity';
  main.prepend(live, activity);
  const reward = $('reward').closest('section'); reward.id = 'rewardCard';
  const health = $('healthRows').closest('section'); health.id = 'healthCard';
  const stream = $('overlayUrl').closest('section'); stream.id = 'obsCard';
  stream.querySelector('h2').textContent = 'OBS overlay';
  const camera = document.createElement('section'); camera.className = 'card camera-card'; camera.id = 'cameraCard';
  camera.innerHTML = '<div class="card-head"><span class="step"><svg class="icon" aria-hidden="true"><use href="#i-camera"/></svg></span><h2>Camera</h2></div>';
  side.prepend(camera);
  camera.append($('liveState'), $('liveCamera'));
  $('liveCamera').querySelector('h3').remove();
  const openCamera = document.createElement('a'); openCamera.className = 'btn btn-secondary camera-open';
  openCamera.href = '/camera-overlay'; openCamera.target = '_blank'; openCamera.rel = 'noopener';
  openCamera.textContent = 'Open camera ↗'; camera.append(openCamera);
  $('cameraSummary').classList.add('camera-placeholder');
  side.replaceChildren(camera, reward, stream, health);
  const queue = $('liveQueue'); queue.className = 'queue-sidebar';
  const next = document.createElement('p'); next.className = 'hint next-set';
  next.innerHTML = 'Next set <strong id="queueNext">Checking…</strong>';
  queue.querySelector('h3').after(next);
  const challengeBody = document.createElement('div'); challengeBody.className = 'challenge-body';
  const challengeMain = document.createElement('div'); challengeMain.className = 'challenge-main';
  challengeMain.append($('liveTotals'), live.querySelector('.queue-progress'), $('liveActions'));
  challengeBody.append(challengeMain, queue);
  live.querySelector('.live-bottom').remove();
  live.querySelector('.live-heading').after(challengeBody);
  live.querySelector('h2').textContent = 'Challenge';
  const queueState = document.createElement('span'); queueState.id = 'queueState'; queueState.className = 'badge';
  queueState.textContent = 'Checking queue'; live.querySelector('.live-heading').append(queueState);
  const adjust = document.createElement('button'); adjust.className = 'btn btn-secondary'; adjust.textContent = 'Adjust totals';
  adjust.onclick = () => { live.querySelector('.counter-edit').open = true; jumpTo($('owedInput')); };
  $('liveActions').append(adjust);
  const guide = $('setupGuide'); guide.style.marginBottom = ''; guide.open = false;
  const advanced = $('advancedSettings');
  advanced.querySelector('.advanced-body').prepend($('supportCard'));
  layout.after(guide, advanced);
  installWorkspaceNavigation({nav, workspace, heading, layout, main, side, guide, advanced, readiness});
}

function installWorkspaceNavigation({nav, workspace, heading, layout, main, side, guide, advanced, readiness}) {
  const integrations = document.createElement('section');
  integrations.className = 'integration-page stack';
  integrations.append($('supportCard'), $('riotEnabled').closest('details.card'));
  advanced.before(integrations);
  advanced.querySelector('.advanced-body').append($('healthCard'), $('ruleTestCard'));
  const pages = {
    live: ['Live control', 'Your challenge and camera. Everything else is one click away.'],
    setup: ['Setup', 'Check Twitch, triggers, camera framing and your OBS overlay.'],
    rewards: ['Rewards', 'Choose which Channel Points reward adds a challenge to your queue.'],
    integrations: ['Integrations', 'Configure subscriptions, donations and optional League checks.'],
    activity: ['Activity', 'Review completed reps, counter changes and received events.'],
    settings: ['Settings', 'Manage your Twitch account, connection health and safe rule tests.'],
  };
  const sections = new Map([
    [$('liveConsole'), ['live']], [$('cameraCard'), ['live']],
    [readiness, ['live', 'setup']], [guide, ['setup']], [$('obsCard'), ['setup']],
    [$('rewardCard'), ['rewards']], [integrations, ['integrations']],
    [$('recentActivity'), ['activity']], [advanced, ['settings']],
  ]);
  const destinations = {liveConsole:'live',setupGuide:'setup',reward:'rewards',supportCard:'integrations',activityRows:'activity'};
  const title = heading.querySelector('h1'); title.tabIndex = -1;
  title.id = 'workspaceTitle';
  const mobile = document.createElement('select');
  mobile.className = 'control mobile-navigation'; mobile.setAttribute('aria-label', 'Console section');
  for (const [key, [label]] of Object.entries(pages)) {
    const option = document.createElement('option'); option.value = key; option.textContent = label; mobile.append(option);
  }
  heading.before(mobile);
  const returnBar=document.createElement('div');returnBar.className='workspace-return';returnBar.hidden=true;
  const back=document.createElement('button');back.type='button';back.className='btn btn-secondary';
  back.id='backToSettings';back.textContent='← Back to Settings';returnBar.append(back);heading.before(returnBar);
  let current = 'live';
  function showPage(key, focus = false) {
    if (!pages[key]) return;
    current = key;
    workspace.dataset.page = key;
    const [label, description] = pages[key];
    title.textContent = label;
    workspace.querySelector('.breadcrumb strong').textContent = label;
    document.title = label + ' · Squat Capture';
    for (const [element, views] of sections) element.hidden = !views.includes(key);
    main.hidden = ![...main.children].some(element => !element.hidden);
    side.hidden = ![...side.children].some(element => !element.hidden);
    layout.hidden = main.hidden && side.hidden;
    if (key === 'setup') guide.open = true;
    if (key === 'activity') $('recentActivity').open = true;
    if (key === 'integrations') $('supportCard').open = true;
    for (const button of nav.querySelectorAll('.nav-item')) {
      if (destinations[button.dataset.destination] === key) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    }
    mobile.value = key;
    if (focus) { title.scrollIntoView({behavior:'instant',block:'start'}); title.focus({preventScroll:true}); }
  }
  window.history.scrollRestoration='manual';
  const navigation=createWorkspaceHistory(window.history,{
    validPage:key=>Object.hasOwn(pages,key),
    snapshot:()=>({page:current,scrollY:window.scrollY,focusId:document.activeElement?.id,
      connectionTarget:document.activeElement?.closest?.('.connection-row')?.dataset.target}),
    render:(view,restore)=>{
      showPage(view.page);
      const returning=!!view.returnToSettings && view.page!=='settings';
      returnBar.hidden=!returning;workspace.dataset.returnSettings=String(returning);
      if (!restore) return;
      requestAnimationFrame(()=>{
        const link=[...$('healthRows').querySelectorAll('.connection-row')].find(row=>row.dataset.target===view.connectionTarget);
        const target=link || (view.focusId && $(view.focusId)) || title;
        for(let parent=target.parentElement;parent;parent=parent.parentElement)if(parent.tagName==='DETAILS')parent.open=true;
        if(returning){const connection=target.querySelector?.('.support-connection');if(connection)connection.open=true;}
        target.focus({preventScroll:true});
        window.scrollTo({top:Number.isFinite(view.scrollY)?view.scrollY:0,behavior:'instant'});
      });
    }
  });
  back.onclick=()=>navigation.back();
  window.addEventListener('popstate',event=>navigation.restore(event.state));
  function navigate(key) {
    if (document.body.dataset.authView !== 'dashboard' && key !== 'settings') {
      mobile.value = current;
      jumpTo($('login'));
      return;
    }
    navigation.go(key);
    title.scrollIntoView({behavior:'instant',block:'start'});title.focus({preventScroll:true});
  }
  for (const button of nav.querySelectorAll('.nav-item')) button.onclick = () => navigate(destinations[button.dataset.destination]);
  mobile.onchange = () => navigate(mobile.value);
  nav.querySelector('.sidebar-brand').onclick = event => { event.preventDefault(); navigate('live'); };
  revealWorkspace = (element, options) => {
    for (const [section, views] of sections) {
      if (section.contains(element) && !views.includes(current)) { navigation.go(views[0], {...options,focusId:element.id}); break; }
    }
  };
  navigation.restore(window.history.state);
}

export function renderSetupReadiness(steps) {
  const count = steps.filter(Boolean).length;
  $('setupReadiness').dataset.complete = String(count === 4);
  $('readinessTitle').textContent = count === 4 ? 'Setup complete' : 'Setup · '+count+' of 4';
  $('readinessSummary').textContent = count === 4 ? 'Triggers listening · Camera and OBS checks saved' : (4-count)+' checks remaining';
  $('readinessSummary').hidden = count === 4;
  $('continueSetup').textContent = count === 4 ? 'Manage setup' : 'Continue setup';
  const labels = [['Connected','Connect Twitch'], ['Listening','Choose / check triggers'], ['Framing confirmed','Check framing'], ['Overlay confirmed','Add overlay']];
  steps.forEach((done, i) => {
    const element = $('readinessStep'+i); element.dataset.complete = String(done);
    element.querySelector('.step-number').textContent = done ? '✓' : String(i+1);
    element.querySelector('.hint').textContent = labels[i][done ? 0 : 1];
  });
}
