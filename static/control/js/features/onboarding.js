import {$, jumpTo} from '../render.js';
import {subscribe, deriveAccount} from '../state.js';

export function initOnboarding(ctx) {
  const hero = document.createElement('section');
  hero.id = 'twitchOnboarding';
  hero.className = 'card twitch-onboarding';
  hero.setAttribute('aria-labelledby', 'onboardingTitle');
  hero.innerHTML = `<span class="step"><svg class="icon" aria-hidden="true"><use href="#i-chat"/></svg></span>
    <h2 id="onboardingTitle">Checking your Twitch connection…</h2>
    <p id="onboardingDescription">The livestream controls will appear once your account is connected.</p>
    <div id="onboardingActions" class="onboarding-actions"></div>
    <details class="permissions"><summary>What permissions are used?</summary>
      <p>Channel Points: read rewards and redemptions. When enabled, Sub and Bits rules also request subscription and Bits read access. Enabling these later may require reconnecting.</p>
      <p>Authorization happens on Twitch. Squat Capture never asks for your password. You can revoke access in your Twitch account’s Connections settings.</p>
    </details><p class="hint">✓ Runs locally &nbsp; · &nbsp; ✓ Never reads your password</p>
    <div class="onboarding-links"><a href="/camera-overlay" target="_blank" rel="noopener">Camera check ↗</a><a href="/overlay" target="_blank" rel="noopener">OBS overlay ↗</a></div>`;
  $('setupReadiness').before(hero);
  const loginHome = $('login').parentElement;
  const helpHome = $('loginHelp').parentElement;
  const pill = $('connectionPill');
  const twitchIcon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  twitchIcon.setAttribute('class', 'icon');
  twitchIcon.setAttribute('aria-hidden', 'true');
  const iconUse = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  iconUse.setAttribute('href', '#i-chat');
  twitchIcon.append(iconUse);
  pill.prepend(twitchIcon);
  pill.setAttribute('role', 'button'); pill.tabIndex = 0;
  pill.onclick = () => jumpTo($('login'));
  pill.onkeydown = event => { if (['Enter', ' '].includes(event.key)) { event.preventDefault(); pill.click(); } };
  const action = document.createElement('button');
  action.className = 'btn btn-ghost'; action.id = 'headerTwitchAction';
  pill.after(action);
  let latest = {}, account = {}, hadAccount = false;
  function currentAccount() {
    const diagnostics = latest['/api/diagnostics'];
    const fresh = diagnostics && !diagnostics.error && Date.now() - diagnostics.time <= 25000;
    return deriveAccount(latest['/api/settings'], fresh ? diagnostics.data : null);
  }
  ctx.canUseTwitch = () => currentAccount().connected;
  function connectOrManage() {
    if (account.kind === 'unavailable' || account.kind === 'loading') { jumpTo($('healthRefresh')); return; }
    if (account.connected) jumpTo($('login'));
    else { jumpTo($('login')); $('login').click(); }
  }
  action.onclick = connectOrManage;
  ctx.twitchEntry = connectOrManage;
  const dialog = document.createElement('dialog');
  dialog.className = 'connection-dialog';
  dialog.setAttribute('aria-labelledby', 'connectionRequiredTitle');
  dialog.innerHTML = '<h2 id="connectionRequiredTitle">Twitch connection required</h2><p>Connect your Twitch account before starting a challenge or configuring Twitch triggers.</p><div class="actions"><button class="btn btn-twitch" id="requiredConnect">Connect with Twitch</button><button class="btn btn-ghost" id="requiredCancel">Cancel</button></div>';
  document.body.append(dialog);
  $('requiredCancel').onclick = () => dialog.close();
  $('requiredConnect').onclick = () => { dialog.close(); connectOrManage(); };
  ctx.requireTwitch = () => {
    render();
    if (account.connected) return true;
    if (!dialog.open) dialog.showModal();
    return false;
  };
  function render() {
    account = currentAccount();
    // Preserve the last view during a network error, but honor an explicit
    // cleared account snapshot (e.g. credentials revoked/removed).
    if (!['unavailable', 'loading'].includes(account.kind)) hadAccount = !!account.known || account.connected;
    const firstRun = !hadAccount;
    document.body.dataset.authView = firstRun ? 'onboarding' : 'dashboard';
    hero.hidden = account.connected;
    $('liveConsole').hidden = firstRun;
    const unavailable = ['unavailable', 'loading'].includes(account.kind);
    $('onboardingTitle').textContent = unavailable ? (account.kind === 'loading' ? 'Checking your Twitch connection…' : 'Cannot check Twitch right now') : account.kind === 'pending' ? 'Finish connecting on Twitch' : firstRun ? 'Connect Twitch to get started' : 'Restore your Twitch connection';
    $('onboardingDescription').textContent = unavailable ? 'Check that the local app is running. We will retry automatically.' : account.kind === 'pending' ? 'Complete authorization in the Twitch window. Use the link below if it did not open.' : firstRun ? 'Authorize Squat Capture to listen for Channel Point rewards, plus subscriptions and Bits when you enable those rules.' : 'Your counters and queued challenges are preserved. Reconnect to restore Twitch events.';
    $('connectionShort').textContent = account.label;
    const warning = ['interrupted', 'review'].includes(account.kind);
    pill.className = 'connection-pill' + (account.listening ? ' online' : warning ? ' warning' : '');
    pill.title = 'Open Twitch account and connection settings';
    action.textContent = account.kind === 'new' ? 'Connect Twitch' : account.kind === 'review' ? 'Fix connection' : account.action;
    action.className = 'btn ' + (account.kind === 'new' ? 'btn-twitch' : warning ? 'btn-warning' : 'btn-ghost');
    action.hidden = account.kind === 'connected';
    action.disabled = unavailable || account.kind === 'pending' || !!ctx.authBusy;
    $('setupConnect').textContent = account.action;
    $('setupConnect').className = 'btn ' + (firstRun ? 'btn-twitch' : 'btn-ghost');
    $('setupConnect').disabled = unavailable || account.kind === 'pending' || !!ctx.authBusy;
    $('login').className = 'btn ' + (warning ? 'btn-warning' : !account.connected ? 'btn-twitch' : 'btn-secondary');
    $('login').disabled = unavailable || account.kind === 'pending' || !!ctx.authBusy;
    $('login').textContent = account.kind === 'pending' || ctx.authBusy ? 'Authorization in progress…' : account.connected ? 'Reconnect Twitch' : account.action;
    if (account.connected) {
      if ($('login').parentElement !== loginHome) loginHome.append($('login'));
      if ($('loginHelp').parentElement !== helpHome) helpHome.append($('loginHelp'));
    } else {
      if ($('login').parentElement !== $('onboardingActions')) $('onboardingActions').append($('login'));
      if ($('loginHelp').parentElement !== hero) hero.querySelector('.permissions').before($('loginHelp'));
    }
    $('setupTriggers').disabled = !account.connected;
    if (!account.connected) $('queueMessage').textContent = 'Connect Twitch to start queued challenges.';
    const queue = latest['/api/queue'];
    $('queueStart').disabled = !account.connected || !queue?.data?.items?.length || !!queue.data.active || !!queue.error;
  }
  ctx.renderAccount = render;
  subscribe(entries => { latest = entries; render(); });
  setInterval(render, 5000);
}
