import {json} from '../api.js';
import {$} from '../render.js';

export function initProgress() {
  document.querySelector('.stat.owed span').textContent = 'Total owed';
  document.querySelector('.stat.done span').textContent = 'Completed this stream';
  document.querySelector('label[for="completedInput"]').textContent = 'Correct stream completed';
  $('counterMessage').textContent = 'Owed carries over. Stream completed resets on a new Twitch broadcast. Offline reps only reduce owed.';
  const sessionInfo = document.createElement('p');
  sessionInfo.className = 'hint';
  sessionInfo.setAttribute('role', 'status');
  document.querySelector('.stat-grid').after(sessionInfo);
  $('overlayUrl').value = location.origin + '/overlay';

  function renderStats(stats) {
    $('owed').textContent = String(stats.owed_squats || 0);
    $('completed').textContent = String(stats.completed_squats || 0);
    for (const [id, key] of [['owedInput', 'owed_squats'], ['completedInput', 'completed_squats']]) {
      if (document.activeElement !== $(id)) $(id).value = String(stats[key] || 0);
    }
    sessionInfo.textContent = stats.stream_status === 'live' ? 'Live · counting this stream'
      : stats.stream_status === 'offline' ? 'Offline · last stream retained'
      : 'Twitch session unavailable · session counting paused';
  }
  async function refreshStats() {
    try { renderStats(await json('/api/stats')); }
    catch { sessionInfo.textContent = 'Counters unavailable · displayed totals may be outdated'; }
  }
  async function setCounter(field, input) {
    try {
      const value = Number($(input).value);
      if (!Number.isInteger(value) || value < 0) throw Error('Enter a non-negative whole number');
      renderStats(await json('/api/stats', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({[field]: value})
      }));
      $('counterMessage').textContent = 'Counters updated.';
    } catch (error) { $('counterMessage').textContent = error.message; }
  }
  $('setOwed').onclick = () => setCounter('owed_squats', 'owedInput');
  $('setCompleted').onclick = () => setCounter('completed_squats', 'completedInput');
  $('copy').onclick = async () => {
    try {
      await navigator.clipboard.writeText($('overlayUrl').value);
      $('copy').textContent = 'Copied';
      setTimeout(() => $('copy').textContent = 'Copy', 1200);
    } catch { $('copy').textContent = 'Select URL to copy'; }
  };
  refreshStats();
  setInterval(refreshStats, 10000);
}
