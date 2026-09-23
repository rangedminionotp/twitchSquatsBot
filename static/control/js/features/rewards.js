import {json, save} from '../api.js';
import {$, jumpTo, diagnosticRow, escapeHtml} from '../render.js';

export function initRewards(ctx) {
async function loadRewards(){try{const data=await json('/api/twitch/rewards');const current=$('reward').value||ctx.settings.target_reward_id||'';$('reward').innerHTML='<option value="">Select a reward</option>'+data.rewards.map(r=>'<option value="'+r.id+'">'+escapeHtml(r.title)+' ('+r.cost+' points)</option>').join('');$('reward').value=current}catch(e){$('connection').textContent+='\nCould not load rewards: '+e.message;$('connection').className='status bad'}}
$('saveReward').onclick=async()=>{if(!ctx.requireTwitch())return;const option=$('reward').selectedOptions[0];try{await save({target_reward_id:$('reward').value,target_reward_title:option&&option.value?option.textContent.replace(/ \([0-9]+ points\)$/,''):''});$('connection').textContent+='\nReward saved.';$('connection').className='status good'}catch(e){$('connection').textContent=e.message;$('connection').className='status bad'}};
ctx.loadRewards=loadRewards;
}
