// Observable API snapshots, separate from DOM and feature handlers.
const snapshots = {};
const listeners = new Set();
const tracked = new Set(['/api/settings', '/api/diagnostics', '/api/camera', '/api/queue']);

export function recordResponse(path, data, error = null) {
  if (!tracked.has(path)) return;
  snapshots[path] = {data, error, time: Date.now()};
  for (const listener of listeners) listener(snapshots);
}

export function subscribe(listener) {
  listeners.add(listener);
  listener(snapshots);
  return () => listeners.delete(listener);
}

// Saved identity/token and the live socket are different facts. A dropped
// connection must not turn an existing streamer's dashboard into a first run.
export function deriveAccount(entry, diagnostics, now = Date.now()) {
  if (!entry) return {kind: 'loading', label: 'Checking Twitch…', action: 'Connect with Twitch', connected: false};
  if (entry.error || now - entry.time > 25000) return {kind: 'unavailable', label: 'Twitch status unavailable', action: 'Check connection', connected: false};
  const {settings, twitch} = entry.data;
  const known = !!(settings.twitch_access_token || settings.broadcaster_login);
  const connected = twitch.state === 'connected';
  const pending = twitch.auth_state === 'pending' || twitch.state === 'authorizing';
  const name = settings.broadcaster_login || 'your account';
  const required = ['Channel Points', settings.subs_enabled === '1' && 'Subs / gifts', settings.bits_enabled === '1' && 'Bits'].filter(Boolean);
  const rows = diagnostics?.health?.listeners;
  const listening = connected && Array.isArray(rows) && required.every(name => rows.some(row => row.name === name && row.state === 'ready'));
  const review = connected && Array.isArray(rows) && !listening;
  return {
    kind: pending ? 'pending' : connected ? (review ? 'review' : 'connected') : known ? 'interrupted' : 'new',
    known, connected, listening, name,
    label: pending ? 'Waiting for Twitch authorization' : connected ? (review ? 'Twitch connection interrupted · Fix' : listening ? 'Twitch connected as ' + name : 'Twitch connected · checking listeners') : known ? 'Twitch connection interrupted' : 'Twitch not connected',
    action: pending ? 'Authorization in progress…' : connected ? (review ? 'Review Twitch permissions' : 'Manage Twitch connection') : known ? 'Reconnect Twitch' : 'Connect with Twitch'
  };
}

export function cameraPresentation(camera) {
  const t = camera.telemetry || {};
  const result = (label, detail, ready = false, error = false) => ({label, detail, ready, error});
  if (!camera.page_connected) return result('Window closed', 'Open the camera window to check your framing.');
  if (t.error_code === 'permission_denied') return result('Permission denied', 'Allow camera access in the camera window, then retry Start Camera.', false, true);
  if (t.error_code === 'camera_unavailable') return result('Camera unavailable', 'Release the camera in OBS / Streamlabs and retry.', false, true);
  if (t.error_code === 'model_failed') return result('Pose model unavailable', 'Check your network and retry Free capture.', false, true);
  if (!t.camera_live) return result('Camera off', 'Click Start Camera in the camera window.');
  if (!t.storage_ok) return result('Saving unavailable', 'Allow local browser storage before capturing reps.', false, true);
  if (camera.mode === 'capture' && (!t.model_ready || t.actual_mode !== 'capture')) return result('Loading pose model', 'Keep the camera window open. First use may take longer.');
  if (['standing','lowering','returning'].includes(t.calibration)) return result('Calibrating', 'Follow the three steps in the camera window. Counting is paused.');
  if (t.actual_mode !== 'capture') return result('Webcam live', 'Start a queued challenge or choose Free capture.', true);
  if (!t.model_ready) return result('Loading pose model', 'Waiting for the first pose result.');
  if (t.calibration==='required') return result('Calibration needed', 'Click Calibrate in the camera window. The demo does not count.');
  if (!t.body_detected) return result('Step into frame', 'Move back until your full body is visible.');
  return result('Capture ready', 'Body detected · ready to count your reps.', true);
}

export function selectedTriggers(settings, diagnostics) {
  const required = [];
  if (settings.target_reward_id) required.push('Channel Points');
  if (settings.subs_enabled === '1') required.push('Subs / gifts');
  if (settings.bits_enabled === '1') required.push('Bits');
  const missing = required.filter(name => !diagnostics.health?.listeners?.some(row => row.name === name && row.state === 'ready'));
  for (const key of ['streamlabs', 'streamelements']) {
    if (settings[key + '_enabled'] === '1') {
      required.push(key);
      if (diagnostics.providers?.[key] !== 'Listening') missing.push(key);
    }
  }
  return {selected: required.length > 0, ready: required.length > 0 && missing.length === 0, missing};
}

// Pure, testable readiness rules. OBS confirmation is never inferred from a URL.
export function deriveStatus(entries, now = Date.now()) {
  const result = (label, detail, target = null, ready = false) => ({label, detail, target, ready});
  const paths = [...tracked];
  if (paths.some(path => entries[path]?.error)) return result('Status unavailable', 'Check that the local app is running. Status will retry automatically.', 'healthRefresh');
  if (paths.some(path => !entries[path])) return result('Checking…', 'Checking Twitch, camera and queue.');
  if (paths.some(path => now - entries[path].time > 25000)) return result('Status outdated', 'Waiting for fresh status. Check the local app connection.', 'healthRefresh');
  const account = entries['/api/settings'].data;
  const diagnostics = entries['/api/diagnostics'].data;
  const camera = entries['/api/camera'].data;
  const queue = entries['/api/queue'].data;
  if (account.twitch.auth_state === 'pending' || account.twitch.state === 'connecting') return result('Connecting', 'Complete Twitch authorization in the browser.', 'login');
  if (account.twitch.state !== 'connected') return result('Twitch disconnected', account.twitch.message || 'Connect or reconnect your Twitch account.', 'login');
  const triggers = selectedTriggers(account.settings, diagnostics);
  if (!triggers.selected) return result('Choose triggers', 'Select a Channel Points reward or enable an auto-add rule.', 'reward');
  if (!triggers.ready) return result('Not listening', triggers.missing.join(', ') + ': check connection and permissions in Settings.', 'healthRefresh');
  if (!camera.page_connected) return result('Open camera', 'Triggers listening. Open the camera window and start your camera.', 'cameraSummary');
  const t = camera.telemetry || {};
  if (t.error_code === 'permission_denied') return result('Camera permission denied', 'Allow camera access in the camera window, then click Start Camera.', 'cameraSummary');
  if (t.error_code === 'camera_unavailable') return result('Camera unavailable', 'Release the camera in OBS / Streamlabs, then retry Start Camera.', 'cameraSummary');
  if (t.error_code === 'model_failed') return result('Pose model unavailable', 'Check your network and retry Free capture in the camera window.', 'cameraSummary');
  if (!t.camera_live) return result('Start camera', 'Start Camera in the camera window. Check browser permissions if needed.', 'cameraSummary');
  if (!t.storage_ok) return result('Saving unavailable', 'Allow local browser storage before capturing reps.', 'cameraSummary');
  if (t.pending > 0) return result('Syncing reps', 'Keep the camera window open until saved reps finish syncing.', 'cameraSummary');
  if (camera.mode === 'capture' && (!t.model_ready || t.actual_mode !== 'capture')) return result('Loading pose model', 'Keep the camera window open. First use may take longer.', 'cameraSummary');
  if (['standing','lowering','returning'].includes(t.calibration)) return result('Calibrating', 'Follow the camera guide. The calibration demo does not count.', 'cameraSummary');
  if (t.actual_mode !== 'capture') return result(queue.items.length ? 'Queue paused' : 'Webcam mode', 'Triggers listening · camera live. Start a challenge or choose Free capture.', null);
  if (!t.model_ready) return result('Loading pose model', 'Waiting for the first pose result.', 'cameraSummary');
  if (t.calibration==='required') return result('Calibration needed', 'Click Calibrate in the camera window before counting.', 'cameraSummary');
  if (!t.body_detected) return result('Step into frame', 'Pose model loaded. Move back until your full body is visible.', 'cameraSummary');
  if (queue.items.length && !queue.active) return result('Queue paused', 'Capture is ready. Resume the queued challenge manually.', null);
  return result(queue.active ? 'Challenge running' : 'Ready', 'Triggers listening · camera ready · pose model loaded', null, true);
}
