import {json} from '../api.js';
import {$} from '../render.js';
import {cameraPresentation} from '../state.js';

export function initCamera(ctx) {
  document.querySelector('#cameraControlStatus + .hint').textContent = 'Open one camera window, start the camera and use Streamlabs Window Capture. H hides controls. Redeems queue without interrupting you. Start / resume queue begins challenges; Webcam pauses them. Free capture does not start a paused queue.';
  async function cameraControl(mode) {
    try {
      const state = await json('/api/camera', mode ? {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({mode})
      } : undefined);
      const t = state.telemetry || {};
      const display = cameraPresentation(state);
      $('cameraSummary').textContent = display.detail;
      $('cameraSummary').dataset.error = String(display.error);
      $('liveState').textContent = (display.ready ? '● ' : '○ ') + display.label;
      $('liveState').dataset.ready = String(display.ready);
      $('liveState').dataset.error = String(display.error);
      $('cameraControlStatus').textContent = state.page_connected ? [
        'Requested: '+state.mode+' · Actual: '+(t.actual_mode || 'unknown'),
        'Camera: '+(t.camera_live ? 'live' : 'not started / unavailable'),
        'Model: '+(t.model_ready ? 'ready' : 'not loaded'),
        'Body: '+(t.actual_mode === 'capture' ? (t.body_detected ? 'detected' : 'not detected') : 'not checking in Webcam'),
        'Saving: '+(!t.storage_ok ? 'local storage unavailable' : t.pending ? 'waiting to sync '+t.pending+' batch(es)' : 'all reps synced')
      ].join('\n') : 'Camera page disconnected · status unavailable';
      $('cameraWebcam').setAttribute('aria-pressed', String(state.mode === 'webcam'));
      $('cameraCapture').setAttribute('aria-pressed', String(state.mode === 'capture'));
    } catch (error) {
      $('cameraControlStatus').textContent = error.message;
      $('cameraSummary').textContent = 'Camera status unavailable · check the local app connection.';
      $('cameraSummary').dataset.error = 'true';
      $('liveState').textContent = '○ Camera status unavailable';
      $('liveState').dataset.ready = 'false';
      $('liveState').dataset.error = 'true';
    }
  }
  $('cameraWebcam').onclick = () => cameraControl('webcam');
  $('cameraCapture').onclick = () => cameraControl('capture');
  cameraControl();
  setInterval(() => cameraControl(), 3000);
  ctx.cameraControl = cameraControl;
}
