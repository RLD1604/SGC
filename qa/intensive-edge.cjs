const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const base=process.env.QA_URL;assert(base&&new URL(base).port==='19001');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(8000);const results=[];
 const cleanDraft=async()=>page.evaluate(async()=>{try{if(typeof clearActiveDraft==='function')await clearActiveDraft();}catch{}try{if(typeof closeDraftDialog==='function')closeDraftDialog();}catch{}const recovery=document.querySelector('#storage-recovery');if(recovery)recovery.remove();if(typeof storageBlocked!=='undefined')storageBlocked=false;if(typeof pendingOperation!=='undefined')pendingOperation=null;}).catch(()=>{});
 const check=async(name,fn)=>{try{const detail=await fn();results.push({name,passed:true,detail});}catch(e){results.push({name,passed:false,error:e.message.slice(0,1400)});}finally{await cleanDraft();}console.log((results.at(-1).passed?'PASS ':'FAIL ')+name);};
 const go=async r=>{await page.goto(base+'/#'+r);await page.waitForFunction(()=>state?.editions);};
 try{
 await go('inicio');
 await check('Importação JSON inválida não muda acervo',async()=>{
  const before=await (await page.request.get(base+'/api/state')).json();
  const fc=page.waitForEvent('filechooser');await page.click('#import-file');await (await fc).setFiles({name:'bad.json',mimeType:'application/json',buffer:Buffer.from('{bad')});
  await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('Importação não concluída'));const after=await (await page.request.get(base+'/api/state')).json();assert.deepEqual(after,before);
 });
 await check('Importação por arquivo e repetição idempotente',async()=>{
  const content=JSON.stringify({records:[{id:'imp-qa',title:'Importação arquivo QA',status:'draft',text:'Teste',photos:[],revision:1}],editions:[{id:'imp-e',title:'Importação QA',period:'Teste',blocks:[],version:1}],publications:[]});
  for(let i=0;i<2;i++){const fc=page.waitForEvent('filechooser');await page.click('#import-file');await (await fc).setFiles({name:'valid.json',mimeType:'application/json',buffer:Buffer.from(content)});await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('Importação concluída'));await page.reload();await page.waitForFunction(()=>state?.records);}
  assert.equal(await page.evaluate(()=>state.records.filter(r=>r.title==='Importação arquivo QA').length),1);
 });
 await check('Texto longo, local e responsável longos preservados',async()=>{
  await go('novo');await page.waitForFunction(()=>tinymce.get('record-text')?.initialized);
  await page.fill('[name=title]','Texto longo QA');await page.fill('[name=local]','L'.repeat(5000));await page.fill('[name=who]','W'.repeat(5000));await page.evaluate(()=>tinymce.get('record-text').setContent('<p>'+'Texto comprido. '.repeat(2000)+'</p>'));
  await page.click('button[value=draft]');await page.waitForURL(/#registro\//);await page.reload();await page.waitForFunction(()=>state?.records);
  const r=await page.evaluate(()=>state.records.find(r=>r.id===location.hash.split('/')[1]));assert.equal(r.local.length,5000);assert.equal(r.who.length,5000);assert(r.text.length>20000);
 });
 await check('Dois cliques rápidos não duplicam registro novo',async()=>{
  await go('novo');await page.waitForFunction(()=>tinymce.get('record-text')?.initialized);await page.fill('[name=title]','Duplo clique QA');const previousCount=await page.evaluate(()=>state.records.filter(r=>r.title==='Duplo clique QA').length);
  await page.route('**/api/state',async route=>{if(route.request().method()==='PUT')await new Promise(r=>setTimeout(r,300));await route.continue();});
  await page.locator('button[value=draft]').dblclick({delay:30});await page.waitForURL(/#registro\//);await page.evaluate(()=>saving);await page.unroute('**/api/state');
  const s=await (await page.request.get(base+'/api/state')).json();const count=s.state.records.filter(r=>r.title==='Duplo clique QA').length-previousCount;assert.equal(count,1,'Quantidade criada: '+count);
 });
 await check('Conferir registro vazio deve bloquear aprovação',async()=>{
  await go('novo');await page.waitForFunction(()=>tinymce.get('record-text')?.initialized);await page.click('button[value=draft]');await page.waitForURL(/#registro\//);await page.click('#approve-record');await page.waitForTimeout(300);
  const r=await page.evaluate(()=>state.records.find(r=>r.id===location.hash.split('/')[1]));assert.notEqual(r.status,'ready');
 });
 await check('Carga moderada: 300 registros e pesquisa',async()=>{
  await go('inicio');await page.evaluate(async()=>{state.records=state.records.filter(r=>!r.title.startsWith('Carga QA '));for(let i=0;i<300;i++)state.records.push({id:crypto.randomUUID(),title:'Carga QA '+i,text:'Teste de volume',category:'Serviço',local:'Área '+i,status:'draft',revision:1,photos:[]});await persist();});
  const start=Date.now();await go('registros');await page.fill('#search','Carga QA 299');await page.waitForFunction(()=>document.querySelectorAll('.record-card').length===1);return {milliseconds:Date.now()-start,records:300};
 });
 await check('Oito gravações simultâneas: uma aceita e sete conflitos',async()=>{
  const current=await (await page.request.get(base+'/api/state')).json();
  const replies=await Promise.all(Array.from({length:8},(_,i)=>page.request.put(base+'/api/state',{data:{revision:current.revision,state:current.state}})));
  const statuses=replies.map(r=>r.status());assert.equal(statuses.filter(s=>s===200).length,1);assert.equal(statuses.filter(s=>s===409).length,7);return statuses;
 });
 await go('inicio');
 await check('Registro importado com histórico inválido continua editável',async()=>{
  const payload={records:[{id:'bad-history',title:'Histórico inválido QA',status:'draft',text:'Teste',photos:[],revision:1,history:{}}],editions:[{id:'eh',title:'Teste',blocks:[],version:1}],publications:[]};
  const response=await page.request.post(base+'/api/import',{data:{importId:'bad-history-'+Date.now(),state:payload}});
  if(response.status()===400)return {rejected:true};
  const data=await response.json();const record=data.state.records.find(r=>r.title==='Histórico inválido QA');
  await page.reload();await page.waitForFunction(()=>state?.records);const errors=[];page.on('pageerror',e=>errors.push(e.message));await go('novo/'+record.id);await page.waitForFunction(()=>tinymce.get('record-text')?.initialized);await page.click('button[value=draft]');await page.waitForTimeout(250);assert.equal(errors.length,0,errors.join('; '));assert(page.url().includes('#registro/'));
 });
 }finally{fs.writeFileSync(path.join(process.env.QA_RESULTS_DIR||path.join(__dirname,'results/intensive'),'edge.json'),JSON.stringify(results,null,2));await browser.close();}
 console.log(JSON.stringify(results)); process.exitCode=results.every(c=>c.passed)?0:1;
})().catch(e=>{console.error(e);process.exitCode=1;});
