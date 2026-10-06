const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path'),crypto=require('node:crypto');
const source=fs.readFileSync(path.join(__dirname,'../public/diagnostics.js'),'utf8');
function harness(responses=[]){
 let now=100000,timerId=0;const timers=new Map(),listeners={},calls=[];
 class Clock extends Date{static now(){return now;}}
 const response=(status=202,retry)=>({status,headers:{get:()=>retry||null}});
 const ctx={Date:Clock,AbortController,Math:Object.assign(Object.create(Math),{random:()=>0}),Set,JSON,location:{hash:'#editor/private-resource',pathname:'/SGC/'},authSession:{user_id:'u'},csrfToken:'test',document:{addEventListener(){}},setTimeout:(fn,delay)=>{const id=++timerId;timers.set(id,{fn,at:now+delay});return id;},clearTimeout:id=>timers.delete(id),window:{crypto:{randomUUID:crypto.randomUUID},fetch:async(...args)=>{calls.push(args);const next=responses.shift();if(next instanceof Error)throw next;if(typeof next==='function')return next(...args);return next||response();},addEventListener:(event,fn)=>listeners[event]=fn}};
 vm.runInNewContext(source,ctx);
 const settle=async()=>{for(let i=0;i<250;i++)await Promise.resolve();};
 return {ctx,listeners,calls,response,settle,async advance(ms){now+=ms;for(const [id,t]of [...timers])if(t.at<=now){timers.delete(id);t.fn();}await settle();},stats:()=>ctx.window.SgcDiagnostics.stats(),body:i=>JSON.parse(calls[i][1].body)};
}
(async()=>{
 const privacy=harness();privacy.listeners.error({message:'SECRET',filename:'PRIVATE',error:new Error('SECRET')});await privacy.settle();
 assert.equal(privacy.body(0).kind,'script_error');assert(!privacy.calls[0][1].body.includes('SECRET'));assert(!privacy.calls[0][1].body.includes('private-resource'));
 for(let i=0;i<40;i++)await privacy.ctx.window.SgcDiagnostics.report('script_error');
 assert.equal(privacy.calls.length,20);await privacy.ctx.window.SgcDiagnostics.report('document_view',null,{type:'edition',id:'view'});assert.equal(privacy.calls.length,21);
 privacy.ctx.authSession=null;await privacy.ctx.window.SgcDiagnostics.report('script_error');assert.equal(privacy.calls.length,21);

 const dedup=harness();dedup.listeners.hashchange();dedup.ctx.window.SgcDiagnostics.routeReport();await dedup.settle();assert.equal(dedup.calls.length,1);assert.equal(dedup.body(0).kind,'document_view');
 dedup.ctx.location.hash='#inicio';dedup.ctx.window.SgcDiagnostics.routeReport();await dedup.settle();dedup.ctx.location.hash='#editor/private-resource';dedup.ctx.window.SgcDiagnostics.routeReport();await dedup.settle();assert.equal(dedup.calls.length,3);

 const retry=harness([{status:429,headers:{get:()=> '2'}}]);await retry.ctx.window.SgcDiagnostics.report('document_view',null,{type:'record',id:'r'});assert.equal(retry.stats().queued,1);await retry.advance(1999);assert.equal(retry.calls.length,1);await retry.advance(1);assert.equal(retry.calls.length,2);assert.equal(retry.stats().queued,0);assert.equal(retry.body(0).reportId,retry.body(1).reportId);
 for(const failed of [new Error('offline'),{status:503,headers:{get:()=> '1'}}]){const h=harness([failed]);await h.ctx.window.SgcDiagnostics.report('document_view',null,{type:'record',id:'r'});assert.equal(h.stats().queued,1);await h.advance(1000);assert.equal(h.stats().accepted,1);assert.equal(h.body(0).reportId,h.body(1).reportId);}
 const timeout=harness([(_url,options)=>new Promise((_resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new Error('timeout'))))]);const waiting=timeout.ctx.window.SgcDiagnostics.report('document_view',null,{type:'record',id:'r'});await timeout.advance(10000);await waiting;assert.equal(timeout.stats().queued,1);await timeout.advance(1000);assert.equal(timeout.stats().accepted,1);

 const priority=harness([{status:429,headers:{get:()=> '1'}}]);await priority.ctx.window.SgcDiagnostics.report('script_error');for(let i=0;i<50;i++)await priority.ctx.window.SgcDiagnostics.report('script_error');await priority.ctx.window.SgcDiagnostics.report('document_view',null,{type:'record',id:'priority'});await priority.advance(1000);assert.equal(priority.body(1).kind,'document_view');assert.equal(priority.stats().queued,0);assert(priority.stats().droppedNoise>0);

 const identity=harness([{status:429,headers:{get:()=> '1'}}]);await identity.ctx.window.SgcDiagnostics.report('document_view',null,{type:'record',id:'old'});identity.ctx.authSession={user_id:'new-user'};await identity.ctx.window.SgcDiagnostics.report('document_view',null,{type:'record',id:'new'});await identity.advance(1000);assert.equal(identity.calls.length,2);assert.equal(identity.body(1).resourceId,'new');assert.equal(identity.stats().droppedIdentity,1);

 const bounded=harness([{status:429,headers:{get:()=> '60'}}]);for(let i=0;i<100;i++)await bounded.ctx.window.SgcDiagnostics.report('document_view',null,{type:'record',id:'r'+i});assert.equal(bounded.stats().queued,80);assert.equal(bounded.stats().droppedCapacity,20);await bounded.advance(300001);assert.equal(bounded.stats().queued,0);assert.equal(bounded.stats().droppedExpired,80);
 const attempts=harness(Array.from({length:8},()=>({status:503,headers:{get:()=> '1'}})));await attempts.ctx.window.SgcDiagnostics.report('document_view',null,{type:'record',id:'r'});for(let i=0;i<7;i++)await attempts.advance(1000);assert.equal(attempts.calls.length,6);assert.equal(attempts.stats().droppedExpired,1);

 let release;const singleton=harness([()=>new Promise(resolve=>release=resolve)]);const first=singleton.ctx.window.SgcDiagnostics.report('document_view',null,{type:'record',id:'a'});await singleton.ctx.window.SgcDiagnostics.report('document_view',null,{type:'record',id:'b'});assert.equal(singleton.calls.length,1);release(singleton.response());await first;await singleton.settle();assert.equal(singleton.calls.length,2);
 const views=harness();for(let i=0;i<35;i++){views.ctx.location.hash='#editor/edition-'+i;views.ctx.window.SgcDiagnostics.routeReport();views.listeners.hashchange();}await views.settle();assert.equal(views.calls.length,35);assert.equal(new Set(views.calls.map((_,i)=>views.body(i).reportId)).size,35);assert.equal(views.stats().accepted,35);
 console.log('PASS: privacy, noise priority, 35 distinct views, route dedup, bounded retries/queue, stable UUIDs, singleton transport and identity isolation');
})().catch(error=>{console.error(error);process.exitCode=1});
