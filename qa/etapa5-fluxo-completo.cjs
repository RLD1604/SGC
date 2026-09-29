// Full assisted-workflow smoke test. It may run only on the disposable isolated server.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const assert=require('node:assert/strict');
const base=process.env.QA_URL;
assert(base&&new URL(base).port==='19001','Use somente a candidata isolada na porta 19001.');
const syntheticPng=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=','base64');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
 try{
  const context=await browser.newContext({acceptDownloads:true,viewport:{width:1280,height:900}}),page=await context.newPage();page.setDefaultTimeout(15000);
  const open=async route=>{await page.goto(base+'/#'+route);await page.waitForFunction(()=>state?.editions);};
  const waitRecordEditor=()=>page.waitForFunction(()=>tinymce.get('record-text')?.initialized);
  await open('novo');await waitRecordEditor();
  await page.fill('[name=title]','QA sintético: manutenção da iluminação');await page.fill('[name=local]','Bloco de teste');await page.selectOption('[name=category]','Manutenção');await page.evaluate(()=>{const instance=tinymce.get('record-text');instance.setContent('<p>Registro sintético para a verificação de ponta a ponta.</p>');instance.fire('change');});
  await page.setInputFiles('#photos-input',{name:'foto-sintetica.png',mimeType:'image/png',buffer:syntheticPng});await page.waitForFunction(()=>workingPhotos.length===1&&!document.querySelector('#photos-input').disabled);await page.fill('[data-caption]','Foto sintética de teste');
  await page.click('button[value=review]');await page.waitForURL(/#registro\//);const recordId=await page.evaluate(()=>location.hash.split('/')[1]);
  let record=await page.evaluate(id=>state.records.find(r=>r.id===id),recordId);assert.equal(record.status,'review');assert.equal(record.photos.length,1);
  await page.click('#request-fix');await page.waitForURL(new RegExp('#complemento/'+recordId));await page.waitForFunction(()=>tinymce.get('feedback')?.initialized);await page.evaluate(()=>tinymce.get('feedback').setContent('<p>Complemento sintético: confirme o local atendido.</p>'));await page.click('#save-feedback');await page.waitForURL(new RegExp('#registro/'+recordId));
  record=await page.evaluate(id=>state.records.find(r=>r.id===id),recordId);assert.equal(record.status,'fix');assert.match(record.feedback,/Complemento sintético/);
  await page.click('a[href="#novo/'+recordId+'"]');await waitRecordEditor();await page.fill('[name=local]','Bloco de teste confirmado');await page.click('button[value=review]');await page.waitForURL(new RegExp('#registro/'+recordId));await page.click('#approve-record');await page.waitForFunction(id=>state.records.find(r=>r.id===id)?.status==='ready',recordId);
  await open('informes');await page.click('#new-edition');await page.fill('#edition-title','Informe sintético Etapa 5');await page.fill('#edition-period','Outubro de 2026');await page.click('#create-edition');await page.waitForURL(/#editor\//);const editionId=await page.evaluate(()=>location.hash.split('/')[1]);
  await page.goto(base+'/#selecionar/'+editionId);await page.locator('#select-'+recordId).waitFor();await page.check('#select-'+recordId);await page.click('#add-separate');await page.waitForURL(new RegExp('#editor/'+editionId));await page.waitForFunction(()=>editor?.instance?.initialized);const hasSource=await page.evaluate(id=>state.editions.find(e=>e.id===id).blocks.some(b=>b.sources?.some(s=>s.id===state.records.find(r=>r.title.includes('QA sintético'))?.id)),editionId);assert(hasSource);
  await page.click('#go-preview');await page.waitForURL(new RegExp('#previa/'+editionId));assert.equal(await page.locator('.publication').count(),1);await page.click('#finalize');await page.check('#confirm');await page.click('#confirm-publish');await page.waitForURL(/#publicado\//);
  const downloadEvent=page.waitForEvent('download');await page.click('#download');const download=await downloadEvent;assert.match(download.suggestedFilename(),/\.html$/);const stream=await download.createReadStream();let html='';for await(const chunk of stream)html+=chunk.toString();assert.match(html,/Informe sintético Etapa 5/);assert.match(html,/Foto sintética de teste/);
  console.log('PASS: fluxo sintético completo criou registro com foto, complemento, conferência, informe, prévia e HTML.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
