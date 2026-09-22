import assert from 'node:assert/strict';
import {deriveStatus, selectedTriggers} from '../../static/control/js/state.js';

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
