const providers=['streamlabs','streamelements'];
let initialized=false;
export function renderDonations(values,status,request) {
  const root=document.getElementById('donations');
  if (!initialized) {
    for (const source of providers) {
      const form=document.createElement('form');form.dataset.source=source;
      const title=document.createElement('h3');title.textContent=source==='streamlabs'?'Streamlabs tips':'StreamElements tips';form.append(title);
      const add=(name,label,type,value)=>{
        const wrapper=document.createElement('label');wrapper.textContent=label;
        const input=document.createElement('input');input.name=name;input.type=type;
        if(type==='checkbox')input.checked=!!value;else input.value=value;
        if(type==='password') {input.autocomplete='new-password';input.placeholder='Leave blank to keep saved token';}
        wrapper.append(input);form.append(wrapper);return input;
      };
      const v=values[source];
      add('enabled','Enable this provider','checkbox',v.enabled);
      add('unit','Amount per unit (whole units per donation)','text',v.unit);
      const reps=add('squats','Squats per unit','number',v.squats);reps.min=1;reps.max=100000;
      add('currency','Currency (e.g. USD)','text',v.currency).maxLength=3;
      add('token',source==='streamlabs'?'Socket API token':'JWT token','password','');
      add('channel','StreamElements channel ID (unused for Streamlabs)','text',v.channel);
      add('clear_token','Remove saved token (disable provider first)','checkbox',false);
      const saved=document.createElement('p');saved.textContent=v.token_configured?'A token is saved securely on the server.':'No token saved.';form.append(saved);
      const button=document.createElement('button');button.textContent='Save integration';form.append(button);
      const info=document.createElement('p');info.id=source+'Status';info.setAttribute('role','status');form.append(info);
      const result=document.createElement('p');result.setAttribute('role','status');form.append(result);
      form.onsubmit=async event=>{
        event.preventDefault();button.disabled=true;
        const fields=form.elements;
        const settings=Object.fromEntries(['unit','currency','token','channel'].map(k=>[k,fields.namedItem(k).value.trim()]));
        Object.assign(settings,{enabled:fields.namedItem('enabled').checked,clear_token:fields.namedItem('clear_token').checked,squats:Number(fields.namedItem('squats').value)});
        try {
          const response=await request('/api/donations',{source,settings});
          fields.namedItem('token').value='';fields.namedItem('clear_token').checked=false;
          saved.textContent=response.donations[source].token_configured?'A token is saved securely on the server.':'No token saved.';
          result.textContent='Saved. Connection changes apply within 15 seconds.';
        }catch(error){result.textContent=error.message;}
        finally{button.disabled=false;}
      };
      root.append(form);
    }
    initialized=true;
  }
  for(const source of providers)document.getElementById(source+'Status').textContent=status[source] || 'Disabled / awaiting sync';
}
