// Etapa 3 acceptance for review transitions (P2-06) and editorial undo (P2-05).
// This file is intentionally limited to QA_URL:19001 and must never target 9001.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const assert=require('node:assert/strict');

const base=process.env.QA_URL;
assert(base&&new URL(base).port==='19001','Use somente a porta isolada 19001.');

(async()=>{
 const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
 const page=await browser.newPage({viewport:{width:1280,height:900}});
 page.setDefaultTimeout(15000);
 let template;const checks=[];
 const check=async(name,fn)=>{try{await fn();checks.push({name,passed:true});console.log('PASS '+name);}catch(error){checks.push({name,passed:false,error:error.message});console.log('FAIL '+name);}};
 const clone=value=>structuredClone(value);
 const get=async()=>await (await page.request.get(base+'/api/state')).json();
 const put=async state=>{const current=await get();return page.request.put(base+'/api/state',{data:{revision:current.revision,state}});};
 const reset=async(builder)=>{const state=builder?builder():clone(template);assert.equal((await put(state)).status(),200);await page.reload();await page.waitForFunction(()=>state?.editions);};
 const unchangedAfterInvalid=async mutator=>{
   const before=await get(),candidate=clone(before.state);mutator(candidate);
   const response=await page.request.put(base+'/api/state',{data:{revision:before.revision,state:candidate}});
   assert.equal(response.status(),400);assert.deepEqual(await get(),before);
 };
 const open=async route=>{await page.goto(base+'/#'+route);await page.waitForFunction(()=>state?.editions);};
 const waitEditor=()=>page.waitForFunction(()=>editor?.instance?.initialized);
 const singleBlock=()=>({id:'only-block',type:'Matéria',title:'Bloco único preservado',body:'<p><strong>Texto formatado</strong> para recuperar.</p>',photos:[{src:'/images/jardim.jpg',phase:'Depois',caption:'Foto preservada'}],sources:[{id:'r1',revision:1,title:'Jardinagem'}]});
 const editorialState=(two=false)=>{
   const state=clone(template),first=singleBlock();state.editions=[{id:'e1',title:'Informe um',period:'Setembro de 2026',status:'draft',version:1,cover:'/images/jardim.jpg',blocks:two?[first,{id:'second-block',type:'Nota',title:'Segundo bloco',body:'<p>Segundo</p>',photos:[],sources:[]}]:[first]},{id:'e2',title:'Informe dois',period:'Outubro de 2026',status:'draft',version:1,cover:'/images/hall.jpg',blocks:[{id:'other-block',type:'Nota',title:'Outro informe',body:'<p>Não restaurar aqui</p>',photos:[],sources:[]}]}];return state;
 };
 try{
  await page.goto(base);await page.waitForFunction(()=>state?.editions&&typeof seed==='function');template=await page.evaluate(()=>seed());

  await check('P2-06: API rejeita review e ready inválidos sem alterar status ou histórico',async()=>{
   await reset();
   await unchangedAfterInvalid(s=>{const r=s.records[0];r.status='review';r.title='';r.text='';r.textHtml='<p>&nbsp;</p>';r.history=[...(r.history||[]),{at:new Date().toISOString(),text:'Não pode gravar'}];});
   await unchangedAfterInvalid(s=>{const r=s.records[0];r.status='ready';r.title='Registro';r.text='  ';r.textHtml='<div> </div>';r.history=[...(r.history||[]),{at:new Date().toISOString(),text:'Não pode conferir'}];});
  });

  await check('P2-06: fluxo de UI envia registro válido para revisão e depois para conferência',async()=>{
   await reset();await open('novo');await page.waitForFunction(()=>tinymce.get('record-text')?.initialized);
   await page.fill('[name=title]','Registro válido Etapa 3');await page.evaluate(()=>tinymce.get('record-text').setContent('<p>Texto <strong>válido</strong>.</p>'));
   await page.click('button[value=review]');await page.waitForURL(/#registro\//);
   let data=await get(),record=data.state.records.find(r=>r.title==='Registro válido Etapa 3');
   assert.equal(record.status,'review');assert(record.history?.length>0);
   await page.click('#approve-record');await page.waitForFunction(id=>state.records.find(r=>r.id===id)?.status==='ready',record.id);
   data=await get();record=data.state.records.find(r=>r.id===record.id);assert.equal(record.status,'ready');assert(record.history?.length>0);
  });

  await check('P2-05: excluir e desfazer o único bloco restaura objeto completo',async()=>{
   await reset(()=>editorialState());const before=(await get()).state.editions.find(e=>e.id==='e1').blocks[0];before.layout='gallery';
   await open('editor/e1');await waitEditor();await page.click('#delete-block');
   await page.waitForFunction(()=>state.editions.find(e=>e.id==='e1').blocks.length===0);
   assert.equal(await page.locator('#undo-block').count(),1,'Desfazer desapareceu sem blocos.');
   await page.click('#undo-block');await page.waitForFunction(()=>state.editions.find(e=>e.id==='e1').blocks.length===1);
   const after=(await get()).state.editions.find(e=>e.id==='e1').blocks[0];assert.deepEqual(after,before);
  });

  await check('P2-05: múltiplos blocos preservam ordem ao excluir e desfazer',async()=>{
   await reset(()=>editorialState(true));const before=(await get()).state.editions.find(e=>e.id==='e1').blocks.map(b=>b.id);
   await open('editor/e1');await waitEditor();await page.click('#delete-block');await page.waitForFunction(()=>state.editions.find(e=>e.id==='e1').blocks.length===1);
   await page.click('#undo-block');await page.waitForFunction(()=>state.editions.find(e=>e.id==='e1').blocks.length===2);
   assert.deepEqual((await get()).state.editions.find(e=>e.id==='e1').blocks.map(b=>b.id),before);
  });

  await check('P2-05: falha ao restaurar mantém recuperação disponível e não perde bloco',async()=>{
   await reset(()=>editorialState());const before=(await get()).state.editions.find(e=>e.id==='e1').blocks[0];before.layout='gallery';
   await open('editor/e1');await waitEditor();await page.click('#delete-block');await page.waitForFunction(()=>state.editions.find(e=>e.id==='e1').blocks.length===0);
   await page.route('**/api/state',route=>route.request().method()==='PUT'?route.abort():route.continue());
   await page.click('#undo-block');await page.locator('#storage-recovery').waitFor();
   await page.unroute('**/api/state');await page.click('#retry-draft');await page.locator('#storage-recovery').waitFor({state:'detached'});
   await page.waitForFunction(()=>state.editions.find(e=>e.id==='e1').blocks.length===1);
   assert.deepEqual((await get()).state.editions.find(e=>e.id==='e1').blocks[0],before);
  });

  await check('P2-05: troca de informe não restaura no destino nem descarta o desfazer de origem',async()=>{
   await reset(()=>editorialState());const source=(await get()).state.editions.find(e=>e.id==='e1').blocks[0];source.layout='gallery';
   await open('editor/e1');await waitEditor();await page.click('#delete-block');await page.waitForFunction(()=>state.editions.find(e=>e.id==='e1').blocks.length===0);
   await open('editor/e2');await waitEditor();assert.equal(await page.locator('#undo-block').isDisabled(),true);
   assert.equal((await get()).state.editions.find(e=>e.id==='e2').blocks[0].id,'other-block');
   await open('editor/e1');await page.locator('#undo-block').waitFor();await page.click('#undo-block');await page.waitForFunction(()=>state.editions.find(e=>e.id==='e1').blocks.length===1);
   assert.deepEqual((await get()).state.editions.find(e=>e.id==='e1').blocks[0],source);
  });
 }finally{await browser.close();}
 console.log(JSON.stringify({passed:checks.filter(c=>c.passed).length,total:checks.length,checks}));
 process.exitCode=checks.every(c=>c.passed)?0:1;
})().catch(error=>{console.error(error);process.exitCode=1;});
