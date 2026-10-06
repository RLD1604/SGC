'use strict';
(() => {
 const transport=window.fetch.bind(window);
 const pages=new Set(['inicio','registros','novo','nota','registro','revisao','informes','selecionar','editor','previa','publicado','lixeira','owner']);
 const MAX_QUEUE=80,MAX_ATTEMPTS=6,MAX_AGE=300000;
 let queue=[],busy=false,inflight=null,timer=null,identity=null,lastRoute=null,blockedUntil=0;
 let noiseStarted=Date.now(),noiseSent=0;
 const counters={accepted:0,droppedCapacity:0,droppedNoise:0,droppedIdentity:0,droppedExpired:0,rejected:0,retried:0};
 function actor(){return typeof authSession==='undefined'?null:authSession?.user_id||null;}
 function synchronize(){const current=actor();if(current!==identity){counters.droppedIdentity+=queue.length;queue=[];identity=current;lastRoute=null;blockedUntil=0;noiseStarted=Date.now();noiseSent=0;if(timer!==null){clearTimeout(timer);timer=null;}}return current;}
 function remove(item){const index=queue.indexOf(item);if(index>=0)queue.splice(index,1);}
 function schedule(){
  if(timer!==null){clearTimeout(timer);timer=null;}
  if(!queue.length||busy||!actor())return;
  const next=Math.max(blockedUntil,Math.min(...queue.map(item=>item.due)));
  timer=setTimeout(()=>{timer=null;void flush();},Math.max(1,next-Date.now()));
 }
 function retryDelay(response,item){
  const value=response?.headers?.get?.('Retry-After');
  const seconds=value&&/^\d+$/.test(value)?Number(value):null;
  const date=value&&seconds===null?Date.parse(value):NaN;
  const requested=seconds!==null?seconds*1000:Number.isFinite(date)?Math.max(0,date-Date.now()):Math.min(30000,1000*2**(item.attempts-1));
  return Math.max(1000,Math.min(MAX_AGE,requested))+Math.floor(Math.random()*250);
 }
 async function flush(){
  synchronize();
  if(busy||!identity||typeof csrfToken==='undefined'||!csrfToken)return;
  busy=true;
  try{
   while(queue.length){
    const current=synchronize();if(!current)break;
    const now=Date.now();
    for(const item of [...queue])if(now-item.created>=MAX_AGE||item.attempts>=MAX_ATTEMPTS){remove(item);counters.droppedExpired++;}
    if(now<blockedUntil)break;
    const available=queue.filter(item=>item.due<=now);
    const item=available.find(item=>item.body.kind==='document_view')||available[0];if(!item)break;
    if(item.userId!==current){remove(item);counters.droppedIdentity++;continue;}
    inflight=item;item.attempts++;
    let response;
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),10000);
    try{response=await transport('/api/diagnostics/client',{method:'POST',credentials:'same-origin',signal:controller.signal,headers:{'Content-Type':'application/json','X-CSRF-Token':csrfToken},body:JSON.stringify(item.body)});}catch{/* Retain bounded pending reports on transport failure. */}finally{clearTimeout(timeout);}
    inflight=null;
    if(synchronize()!==item.userId){remove(item);continue;}
    if(response?.status===202){remove(item);counters.accepted++;continue;}
    if(!response||response.status===429||response.status===503){
     item.due=Date.now()+retryDelay(response,item);blockedUntil=item.due;counters.retried++;break;
    }
    remove(item);counters.rejected++;
   }
  }finally{inflight=null;busy=false;schedule();}
 }
 function page(){if(location.pathname?.endsWith('/owner.html'))return 'owner';const route=location.hash.replace(/^#/,'').split('/')[0]||'inicio';return pages.has(route)?route:'unknown';}
 async function report(kind,relatedRequestId,resource){
  try{
   const userId=synchronize();if(!userId||typeof csrfToken==='undefined'||!csrfToken)return;
   const now=Date.now();
   if(now-noiseStarted>=60000){noiseStarted=now;noiseSent=0;}
   if(kind!=='document_view'){if(noiseSent>=20){counters.droppedNoise++;return;}noiseSent++;}
   if(queue.length>=MAX_QUEUE){
    const noise=kind==='document_view'?queue.find(item=>item!==inflight&&item.body.kind!=='document_view'):null;
    if(noise){remove(noise);counters.droppedCapacity++;}else{counters.droppedCapacity++;return;}
   }
   const reportId=window.crypto.randomUUID();
   const body={kind,page:page(),reportId};if(resource){body.resourceType=resource.type;body.resourceId=resource.id;}if(relatedRequestId){if(relatedRequestId.startsWith('LOCAL-'))body.clientIncidentId=relatedRequestId.slice(6);else body.relatedRequestId=relatedRequestId;}
   queue.push({userId,body,created:now,due:now,attempts:0});await flush();
  }catch{/* Diagnostics must never block work or report their own failures. */}
 }
 window.SgcDiagnostics={report,flush,stats:()=>{synchronize();return {...counters,queued:queue.length,inflight:!!inflight};}};
 window.addEventListener('online',()=>{blockedUntil=0;void flush();});
 window.addEventListener('error',()=>report('script_error'));
 window.addEventListener('unhandledrejection',()=>report('promise_error'));
 function routeReport(){
  const userId=synchronize();if(!userId||typeof csrfToken==='undefined'||!csrfToken)return;
  const key=userId+'|'+location.pathname+'|'+location.hash;if(key===lastRoute)return;lastRoute=key;
  const [route,id]=location.hash.replace(/^#/,'').split('/');const type=route==='registro'?'record':route==='publicado'?'publication':new Set(['editor','previa']).has(route)?'edition':null;
  if(type&&id)void report('document_view',null,{type,id});else void report('navigation');
 }
 window.addEventListener('hashchange',routeReport);
 window.SgcDiagnostics.routeReport=routeReport;
 document.addEventListener('invalid',()=>report('validation_blocked'),true);
 document.addEventListener('click',event=>{if(event.target.closest('button[type="submit"],#save-editor,#approve-record,#request-fix,#submit-edition,#approve-edition,#publish-edition'))void report('action_attempt');},true);
})();
