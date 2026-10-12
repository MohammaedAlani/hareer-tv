'use strict';
let token = '', timer = null, epoch = 0, loading = false, enabled = false;
const $ = id => document.getElementById(id);
function status(message, error=false) { $('status').textContent=message; $('status').classList.toggle('error',error); }
function logout() { epoch++; token=''; enabled=false; loading=false; clearInterval(timer); $('token').value=''; $('links').value=''; $('jobs').replaceChildren(); $('login').hidden=false; $('dashboard').hidden=true; $('logout').hidden=true; status('Signed out.'); }
async function api(path, options={}) {
  const requestEpoch=epoch;
  const response=await fetch(path,{...options,cache:'no-store',headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},signal:AbortSignal.timeout(20000)});
  const result=await response.json();
  if(!response.ok) { if(response.status===401 && requestEpoch===epoch) {logout();status('Access key not accepted.',true);} throw new Error(result.error || 'Request failed'); }
  return result;
}
function render(jobs) {
  $('jobs').replaceChildren(); $('count').textContent=jobs.length+' shown';
  if(!jobs.length) { const empty=document.createElement('p');empty.textContent='No imports yet. Add your first link above.';$('jobs').append(empty); }
  for(const job of jobs) {
    const article=document.createElement('article');article.className='job';
    const details=document.createElement('div');const title=document.createElement('h3');title.textContent=job.title || 'Video '+job.youtube_id;
    const link=document.createElement('a');link.href=job.source_url;link.textContent=job.source_url;link.target='_blank';link.rel='noopener noreferrer';
    details.append(title,link);
    if(job.error) {const error=document.createElement('p');error.textContent=job.error;details.append(error);}
    const badge=document.createElement('span');badge.className='badge '+job.status;badge.textContent=job.status;
    if(job.status==='failed') {
      const retry=document.createElement('button');retry.textContent='Retry';retry.disabled=!enabled;
      retry.addEventListener('click',async()=>{const current=epoch;retry.disabled=true;try{await api('/api/admin/imports/'+job.id+'/retry',{method:'POST'});if(current===epoch){status('Added back to the queue.');await refresh();}}catch(e){if(current===epoch){status(e.message,true);retry.disabled=!enabled;}}});details.append(document.createElement('br'),retry);
    }
    article.append(details,badge);$('jobs').append(article);
  }
}
async function refresh() {
  if(loading) return;loading=true;const current=epoch;
  try { const data=await api('/api/admin/imports');if(current!==epoch)return;enabled=data.enabled;$('configuration').hidden=enabled;$('submit').disabled=!enabled;render(data.jobs); }
  finally { if(current===epoch)loading=false; }
}
$('login-form').addEventListener('submit',async event=>{
 event.preventDefault();const current=++epoch;token=$('token').value.trim();status('Signing in…');
 try {const data=await api('/api/admin/imports');if(current!==epoch)return;enabled=data.enabled;$('configuration').hidden=enabled;$('submit').disabled=!enabled;render(data.jobs);$('token').value='';$('login').hidden=true;$('dashboard').hidden=false;$('logout').hidden=false;status('');clearInterval(timer);timer=setInterval(()=>{if(!document.hidden)refresh().catch(e=>status(e.message,true));},5000);}
 catch(e){if(current===epoch){token='';status(e.message,true);}}
});
$('import-form').addEventListener('submit',async event=>{
 event.preventDefault();const urls=$('links').value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
 if(!urls.length||urls.length>50){status('Enter between 1 and 50 links.',true);return;}
 const current=epoch;$('submit').disabled=true;
 try{const result=await api('/api/admin/imports',{method:'POST',body:JSON.stringify({urls})});if(current!==epoch)return;$('links').value='';status(result.jobs.length+' video link(s) accepted. Existing links keep their current status.');await refresh();}
 catch(e){if(current===epoch)status(e.message,true);}finally{if(current===epoch)$('submit').disabled=!enabled;}
});
$('refresh').addEventListener('click',()=>refresh().catch(e=>status(e.message,true)));
$('logout').addEventListener('click',logout);
