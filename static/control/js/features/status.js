import {$, jumpTo} from '../render.js';
import {subscribe, deriveStatus} from '../state.js';

export function initStatus() {
  const detail = document.createElement('p');
  detail.className = 'hint';
  detail.id = 'readinessDetail';
  detail.setAttribute('role', 'status');
  const repair = document.createElement('button');
  repair.className = 'btn btn-text';
  repair.textContent = 'Show next step';
  repair.hidden = true;
  $('liveTotals').before(detail, repair);
  let snapshots = {};
  function render() {
    const status = deriveStatus(snapshots);
    $('connectionShort').textContent = status.label;
    $('connectionPill').className = 'connection-pill' + (status.ready ? ' online' : '');
    $('connectionPill').title = status.detail;
    detail.textContent = status.detail;
    repair.hidden = !status.target;
    repair.onclick = () => {
      const target = $(status.target);
      // The camera summary is not an input; make it focusable for keyboard users.
      if (target && !target.matches('button,input,select,textarea,a')) target.tabIndex = -1;
      if (target) jumpTo(target);
    };
  }
  subscribe(value => { snapshots = value; render(); });
  // Also revoke Ready when polling stalls (e.g. a sleeping background tab).
  setInterval(render, 5000);
}
