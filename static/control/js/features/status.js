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
    detail.textContent = status.detail;
    // Camera guidance belongs in the camera card, not above the same counters.
    detail.hidden = !status.target || status.target === 'cameraSummary';
    repair.hidden = detail.hidden;
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
