const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const assert=require('node:assert/strict');
const base=process.env.QA_URL;
assert(base&&new URL(base).port==='19001','Use somente a porta isolada 19001.');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
 const page=await browser.newPage({viewport:{width:1280,height:900}});page.setDefaultTimeout(12000);
 try{
  await page.goto(base);await page.waitForFunction(()=>state?.editions);
  const initial=await (await page.request.get(base+'/api/state')).json();
  const operation='qa-etapa1-'+Date.now();
  const first=await page.request.put(base+'/api/state',{headers:{'Idempotency-Key':operation},data:initial});
  const repeated=await page.request.put(base+'/api/state',{headers:{'Idempotency-Key':operation},data:initial});
  assert.equal(first.status(),200);assert.equal(repeated.status(),200);assert.deepEqual(await repeated.json(),await first.json());
  const changed=structuredClone(initial);changed.state.editions[0].title='Conteúdo diferente';
  assert.equal((await page.request.put(base+'/api/state',{headers:{'Idempotency-Key':operation},data:changed})).status(),409);

  // A chamada idempotente acima avança a revisão no servidor. Recarregue a
  // aplicação para que o teste de interface comece com a revisão corrente.
  await page.reload();await page.waitForFunction(()=>state?.editions);

  await page.goto(base+'/#novo');await page.waitForFunction(()=>tinymce.get('record-text')?.initialized);
  await page.fill('[name=title]','Rascunho protegido Etapa 1');
  await page.click('nav a[href="#registros"]');await page.locator('#draft-navigation').waitFor();
  assert.equal(await page.inputValue('[name=title]'),'Rascunho protegido Etapa 1');
  await page.click('#draft-stay');assert(page.url().endsWith('#novo'));
  await page.click('nav a[href="#registros"]');await page.click('#draft-save');
  try{await page.waitForURL(/#registros$/);}catch(error){
   console.error('Diagnóstico Salvar e sair:',await page.evaluate(()=>({url:location.href,hash:location.hash,draft:window.activeDraft?{key:window.activeDraft.key,dirty:window.activeDraft.dirty}:null,submitting:document.querySelector('#record-form')?.dataset.submitting,recovery:document.querySelector('#storage-recovery')?.open,dialog:document.querySelector('#draft-navigation')?.open,status:document.querySelector('#draft-status')?.textContent})));
   throw error;
  }
  let data=await (await page.request.get(base+'/api/state')).json();
  assert.equal(data.state.records.filter(r=>r.title==='Rascunho protegido Etapa 1').length,1);

  await page.goto(base+'/#novo');await page.waitForFunction(()=>tinymce.get('record-text')?.initialized);
  await page.fill('[name=title]','Rascunho recuperado na recarga');await page.reload();
  await page.waitForFunction(()=>document.querySelector('[name=title]')?.value==='Rascunho recuperado na recarga');
  await page.click('nav a[href="#registros"]');await page.click('#draft-discard');await page.waitForURL(/#registros$/);

  await page.goto(base+'/#novo');await page.waitForFunction(()=>tinymce.get('record-text')?.initialized);
  await page.fill('[name=title]','Envio único Etapa 1');
  await page.locator('button[value=draft]').dblclick({delay:30});await page.waitForURL(/#registro\//);
  data=await (await page.request.get(base+'/api/state')).json();
  assert.equal(data.state.records.filter(r=>r.title==='Envio único Etapa 1').length,1);

  await page.goto(base+'/#editor/informe-inexistente-etapa1');await page.waitForURL(/#informes$/);
  assert.equal(await page.locator('#title-edition').count(),0);
  console.log('PASS ETAPA 1: rascunho, recarga, descarte, envio único, idempotência e rota inválida.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
