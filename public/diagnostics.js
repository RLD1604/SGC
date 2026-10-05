'use strict';
(() => {
 const transport=window.fetch.bind(window);
 const pages=new Set(['inicio','registros','novo','nota','registro','revisao','informes','selecionar','editor','previa','publicado','lixeira','owner']);
 let started=Date.now(),sent=0;
 let queue=[];
 async function flush(){
  if(typeof authSession==='undefined'||!authSession?.user_id||typeof csrfToken==='undefined'||!csrfToken)return;
  const pending=queue;queue=[];
  for(const item of pending){
   if(item.userId!==authSession.user_id)continue;
   try{await transport('/api/diagnostics/client',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrfToken},body:JSON.stringify(item.body)});}
   catch{if(queue.length<20)queue.push(item);}
  }
 }
 function page(){if(location.pathname?.endsWith('/owner.html'))return 'owner';const route=location.hash.replace(/^#/,'').split('/')[0]||'inicio';return pages.has(route)?route:'unknown';}
 async function report(kind,relatedRequestId){
  try{
   if(typeof authSession==='undefined'||!authSession?.user_id||typeof csrfToken==='undefined'||!csrfToken)return;
   if(Date.now()-started>=60000){started=Date.now();sent=0;}
   if(sent>=20)return;sent++;
   const body={kind,page:page()};if(relatedRequestId){if(relatedRequestId.startsWith('LOCAL-'))body.clientIncidentId=relatedRequestId.slice(6);else body.relatedRequestId=relatedRequestId;}
   if(queue.length<20)queue.push({userId:authSession.user_id,body});await flush();
  }catch{/* Diagnostics must never block work or report their own failures. */}
 }
 window.SgcDiagnostics={report};
 window.addEventListener('online',flush);
 window.addEventListener('error',()=>report('script_error'));
 window.addEventListener('unhandledrejection',()=>report('promise_error'));
 window.addEventListener('hashchange',()=>report('navigation'));
 document.addEventListener('invalid',()=>report('validation_blocked'),true);
 document.addEventListener('click',event=>{if(event.target.closest('button[type="submit"],#save-editor,#approve-record,#request-fix,#submit-edition,#approve-edition,#publish-edition'))report('action_attempt');},true);
})();
