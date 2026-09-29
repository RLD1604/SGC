// Focused acceptance coverage for Etapa 1 drafts and invalid informe routes.
// Run only through the isolated QA server (port 19001).
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const assert=require('node:assert/strict');
const path=require('node:path');

const base=process.env.QA_URL;
assert(base&&new URL(base).port==='19001','Use somente a porta isolada 19001.');

(async()=>{
 const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
 const page=await browser.newPage({viewport:{width:1280,height:900}});
 page.setDefaultTimeout(15000);
 const image=path.join(__dirname,'../public/images/jardim.jpg');
 const waitApp=()=>page.waitForFunction(()=>state?.editions&&document.querySelector('#main'));
 const open=async route=>{await page.goto(base+'/#'+route);await waitApp();};
 const waitEditor=id=>page.waitForFunction(editorId=>tinymce.get(editorId)?.initialized,id);
 const markEditorDirty=()=>page.evaluate(()=>document.dispatchEvent(new Event('editor-dirty')));
 const serverState=async()=>await (await page.request.get(base+'/api/state')).json();
 const seed=async()=>{
   await open('inicio');
   await page.evaluate(async()=>{state=seed();await persist();});
   await page.reload();await waitApp();
 };
 const leaveAndSave=async target=>{
   await page.click(`nav a[href="#${target}"]`);
   await page.locator('#draft-navigation').waitFor();
   await page.click('#draft-save');
   await page.waitForURL(new RegExp('#'+target+'$'));
 };
 try{
  await seed();
  const ids=await page.evaluate(()=>({recordId:state.records[0].id,editionId:state.editions[0].id}));

  // Complemento: the formatted TinyMCE body must survive the guarded exit and
  // be confirmed in PostgreSQL, not merely remain in the current DOM.
  await open('complemento/'+ids.recordId);await waitEditor('feedback');
  await page.evaluate(()=>tinymce.get('feedback').setContent('<p><strong>Complemento QA</strong></p><ul><li>Confirmar data</li></ul>'));
  await markEditorDirty();
  await leaveAndSave('registros');
  let data=await serverState();
  let record=data.state.records.find(r=>r.id===ids.recordId);
  assert.match(record.feedbackHtml||'',/<strong>Complemento QA<\/strong>/);
  assert.match(record.feedbackHtml||'',/<li>Confirmar data<\/li>/);

  // Informe: title, period and rich body are all draft material. Reload first
  // proves local recovery; saving then proves that a stale copy does not win.
  await open('editor/'+ids.editionId);await page.waitForFunction(()=>editor?.instance?.initialized);
  await page.fill('#title-edition','Informe recuperado Etapa 1');
  await page.fill('#period-edition','Outubro de 2026');
  await page.evaluate(()=>editor.value='<p>Corpo <em>formatado</em> do informe.</p>');
  await markEditorDirty();
  await page.reload();await page.waitForFunction(()=>editor?.instance?.initialized);
  await page.waitForFunction(()=>document.querySelector('#title-edition')?.value==='Informe recuperado Etapa 1');
  assert.equal(await page.inputValue('#period-edition'),'Outubro de 2026');
  assert.match(await page.evaluate(()=>editor.value),/<em>formatado<\/em>/);
  await page.click('#save-editor');
  await page.waitForFunction(()=>document.querySelector('#toast')?.textContent==='Edição salva no PostgreSQL.');
  await page.reload();await page.waitForFunction(()=>editor?.instance?.initialized);
  assert.equal(await page.locator('#storage-recovery').count(),0);
  data=await serverState();
  const edition=data.state.editions.find(e=>e.id===ids.editionId);
  assert.equal(edition.title,'Informe recuperado Etapa 1');
  assert.equal(edition.period,'Outubro de 2026');
  assert.match(edition.blocks[0].body,/<em>formatado<\/em>/);

  // Registro: a real local image plus its phase/caption are restored, then a
  // successful save clears the draft so it cannot appear in another document.
  await open('novo');await waitEditor('record-text');
  await page.fill('[name=title]','Registro com foto recuperada Etapa 1');
  await page.setInputFiles('#photos-input',image);
  await page.waitForFunction(()=>workingPhotos?.length===1&&!document.querySelector('#photos-input')?.disabled);
  await page.selectOption('[data-phase]','Depois');
  await page.fill('[data-caption]','Legenda recuperada Etapa 1');
  await page.click('nav a[href="#registros"]');await page.locator('#draft-navigation').waitFor();
  await page.click('#draft-stay');
  await page.reload();await waitEditor('record-text');
  await page.waitForFunction(()=>workingPhotos?.length===1&&workingPhotos[0].caption==='Legenda recuperada Etapa 1');
  assert.equal(await page.locator('[data-phase]').inputValue(),'Depois');
  await page.click('button[value=draft]');await page.waitForURL(/#registro\//);
  data=await serverState();
  record=data.state.records.find(r=>r.title==='Registro com foto recuperada Etapa 1');
  assert(record&&record.photos.length===1);
  assert.equal(record.photos[0].caption,'Legenda recuperada Etapa 1');
  assert.equal(record.photos[0].phase,'Depois');
  await open('novo');await waitEditor('record-text');
  assert.equal(await page.inputValue('[name=title]'),'');
  assert.equal(await page.evaluate(()=>workingPhotos.length),0);

  // A valid ID must still work on all editorial routes.
  for(const route of ['editor/','selecionar/','previa/'].map(route=>route+ids.editionId)){
    await open(route);
    assert.equal(await page.evaluate(()=>location.hash),'#'+route);
  }

  // An explicit, nonexistent ID must never fall back to e1 on any route.
  for(const route of ['editor/inexistente-etapa1','selecionar/inexistente-etapa1','previa/inexistente-etapa1']){
    await open(route);
    await page.waitForURL(/#informes$/);
    assert.equal(await page.locator('#title-edition').count(),0);
    assert.equal(await page.locator('[data-block]').count(),0);
  }
  console.log('PASS ETAPA 1 DRAFTS: complemento, informe, foto/legenda, limpeza de rascunho e rotas de informe.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
