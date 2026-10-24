import assert from 'node:assert/strict';
import {deriveStatus, selectedTriggers, deriveAccount} from '../../static/control/js/state.js';

function fixture() {
  const values = {
    '/api/settings': {settings: {target_reward_id: 'reward'}, twitch: {state: 'connected'}},
    '/api/diagnostics': {health: {listeners: [{name: 'Channel Points', state: 'ready'}]}, providers: {}},
    '/api/camera': {page_connected: true, mode: 'capture', telemetry: {camera_live: true, model_ready: true, body_detected: true, storage_ok: true, actual_mode: 'capture', pending: 0}},
    '/api/queue': {items: [], active: false}
  };
  return Object.fromEntries(Object.entries(values).map(([key, data]) => [key, {data, time: 1000}]));
}

const cases = [
  ['Ready', () => {}],
  ['Connecting', s => {s['/api/settings'].data.twitch.auth_state = 'pending';}],
  ['Twitch disconnected', s => {s['/api/settings'].data.twitch.state = 'disconnected';}],
  ['Stream counter paused', s => {s['/api/diagnostics'].data.health.stream = {state:'attention',message:'Reconnect Twitch'};}],
  ['Choose triggers', s => {s['/api/settings'].data.settings = {};}],
  ['Not listening', s => {s['/api/diagnostics'].data.health.listeners = [];}],
  ['Open camera', s => {s['/api/camera'].data.page_connected = false;}],
  ['Camera permission denied', s => {s['/api/camera'].data.telemetry.error_code = 'permission_denied';}],
  ['Camera unavailable', s => {s['/api/camera'].data.telemetry.error_code = 'camera_unavailable';}],
  ['Pose model unavailable', s => {s['/api/camera'].data.telemetry.error_code = 'model_failed';}],
  ['Start camera', s => {s['/api/camera'].data.telemetry.camera_live = false;}],
  ['Saving unavailable', s => {s['/api/camera'].data.telemetry.storage_ok = false;}],
  ['Syncing reps', s => {s['/api/camera'].data.telemetry.pending = 2;}],
  ['Loading pose model', s => {s['/api/camera'].data.telemetry.model_ready = false;}],
  ['Step into frame', s => {s['/api/camera'].data.telemetry.body_detected = false;}],
  ['Webcam mode', s => {s['/api/camera'].data.mode = 'webcam'; s['/api/camera'].data.telemetry.actual_mode = 'webcam';}],
  ['Queue paused', s => {s['/api/queue'].data.items = [{done: 1, target: 5}];}],
  ['Challenge running', s => {s['/api/queue'].data.active = true;}],
  ['Status unavailable', s => {s['/api/camera'].error = 'Network error';}],
  ['Status outdated', s => {s['/api/camera'].time = -30000;}],
];
for (const [label, change] of cases) {
  const state = fixture(); change(state);
  const actual = deriveStatus(state, 1000);
  assert.equal(actual.label, label);
  assert.equal(actual.ready, ['Ready', 'Challenge running'].includes(label));
}
assert.equal(deriveStatus({}).label, 'Checking…');
assert.equal(selectedTriggers({subs_enabled: '1'}, {health: {listeners: []}}).ready, false);
assert.equal(selectedTriggers({streamlabs_enabled: '1'}, {providers: {streamlabs: 'Listening'}}).ready, true);
assert.equal(selectedTriggers({streamlabs_enabled: '1', bits_enabled: '1'}, {providers: {streamlabs: 'Listening'}}).ready, false);
console.log(`${cases.length + 4} control-state assertions passed`);

const accountEntry = (settings = {}, twitch = {state: 'disconnected'}) => ({time: 1000, data: {settings, twitch}});
assert.equal(deriveAccount(undefined).kind, 'loading');
assert.equal(deriveAccount({error: 'offline'}, null, 1000).kind, 'unavailable');
assert.equal(deriveAccount(accountEntry(), null, 30000).kind, 'unavailable');
assert.equal(deriveAccount(accountEntry(), null, 1000).kind, 'new');
assert.equal(deriveAccount(accountEntry(), null, 1000).action, 'Connect with Twitch');
assert.equal(deriveAccount(accountEntry({broadcaster_login: 'streamer'}), null, 1000).kind, 'interrupted');
assert.equal(deriveAccount(accountEntry({twitch_access_token: 'configured'}), null, 1000).action, 'Reconnect Twitch');
assert.equal(deriveAccount(accountEntry({}, {state: 'authorizing', auth_state: 'pending'}), null, 1000).kind, 'pending');
const connected = accountEntry({broadcaster_login: 'streamer', target_reward_id: 'a'}, {state: 'connected'});
const listening = {health: {stream:{state:'ready'},listeners: [{name: 'Channel Points', state: 'ready'}]}};
assert.equal(deriveAccount(connected, listening, 1000).label, 'Twitch connected as streamer');
assert.equal(deriveAccount(connected, null, 1000).action, 'Manage Twitch connection');
assert.equal(deriveAccount(connected, {health: {listeners: [{name: 'Channel Points', state: 'attention'}]}}, 1000).action, 'Review Twitch permissions');
assert.equal(deriveAccount(connected, {providers: {streamlabs: 'Disconnected'}}, 1000).kind, 'connected');
console.log('12 Twitch onboarding state assertions passed');
assert.equal(deriveAccount(connected, null, 1000).listening, false);
assert.equal(deriveAccount(connected, listening, 1000).listening, true);
assert.equal(deriveAccount(connected, {health: {listeners: []}}, 1000).kind, 'review');
assert.equal(deriveAccount(connected, {health: {listeners: [{name: 'Channel Points', state: 'disabled'}]}}, 1000).listening, false);
assert.equal(deriveAccount(connected, {health: {stream:{state:'attention'},listeners: [{name: 'Channel Points', state: 'ready'}]}}, 1000).kind, 'review');
const subAccount = accountEntry({subs_enabled: '1'}, {state: 'connected'});
assert.equal(deriveAccount(subAccount, listening, 1000).kind, 'review');
console.log('5 listener-status assertions passed');
