import {json, save} from '../api.js';
import {$, jumpTo, diagnosticRow, escapeHtml} from '../render.js';

export function initChallenge(ctx) {
async function refreshQueue(){try{const q=await json('/api/queue');$('queueItems').replaceChildren();for(const item of q.items){const row=document.createElement('div');row.className='status';row.textContent=item.viewer+' · '+item.title+' · '+item.done+'/'+item.target;$('queueItems').append(row)}if(!q.items.length)$('queueItems').textContent='Queue clear';const first=q.items[0];$('queueCount').textContent=q.items.length+' queued';$('queueMessage').textContent=q.active?'Running in order · pause keeps the camera on':first?'Ready when you are · start manually':'Redeems will appear here. Subs and tips add to total owed.';$('queueStart').textContent=first?.done?'Resume challenge':'Start challenge';$('challengeProgress').max=first?.target||1;$('challengeProgress').value=first?.done||0;$('challengeProgressText').textContent=first?(first.done+' / '+first.target+' reps · '+Math.round(100*first.done/Math.max(1,first.target))+'%'):'No queued challenge';$('queueStart').disabled=!q.items.length||q.active;$('queuePause').disabled=!q.active}catch(e){$('queueMessage').textContent=e.message;$('queueStart').disabled=true;$('queuePause').disabled=true;$('queueCount').textContent='Unavailable'}}
async function queueAction(action){try{await json('/api/queue',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})});await refreshQueue();await ctx.cameraControl()}catch(e){$('queueMessage').textContent=e.message}}
$('queueStart').onclick=()=>queueAction('start');$('queuePause').onclick=()=>queueAction('pause');refreshQueue();setInterval(refreshQueue,2000);

}
