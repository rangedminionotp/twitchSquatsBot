import {json, save} from '../api.js';
import {$, jumpTo, diagnosticRow, escapeHtml} from '../render.js';

export function initActivity(ctx) {
async function refreshDiagnostics(){try{const d=await json('/api/diagnostics');$('healthRows').replaceChildren();diagnosticRow($('healthRows'),'Twitch · '+d.health.connection.state,d.health.connection.message,d.health.connection.state==='connected');for(const r of d.health.listeners)diagnosticRow($('healthRows'),r.name,r.message,r.state==='ready');for(const [name,state] of Object.entries(d.providers))diagnosticRow($('healthRows'),name,state,state==='Listening');$('activityRows').replaceChildren();for(const a of d.activity)diagnosticRow($('activityRows'),a.kind+' · '+new Date(a.time).toLocaleTimeString(),a.reason+(a.amount?' · '+a.amount+' reps':''));if(!d.activity.length)$('activityRows').textContent='No counter activity recorded yet.';$('eventRows').replaceChildren();for(const e of d.events)diagnosticRow($('eventRows'),e.source+' · '+new Date(e.time*1000).toLocaleTimeString(),e.reason);if(!d.events.length)$('eventRows').textContent='No support events received since startup.'}catch(e){$('healthRows').textContent='Health check unavailable: '+e.message}}
$('healthRefresh').onclick=refreshDiagnostics;
$('ruleTest').onsubmit=async e=>{e.preventDefault();const button=e.submitter;button.disabled=true;try{const r=await json('/api/test-rule',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source:$('testSource').value,amount:$('testAmount').value,currency:$('testCurrency').value})});$('testResult').textContent='TEST ONLY · +'+r.delta+' owed\n'+r.reason+'\nReal counters unchanged.'}catch(error){$('testResult').textContent=error.message}finally{button.disabled=false}};
refreshDiagnostics();setInterval(refreshDiagnostics,10000);

}
