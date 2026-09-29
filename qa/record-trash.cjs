const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const assert=require('node:assert/strict');
const path=require('node:path');
const out=process.env.QA_RESULTS_DIR||path.join(__dirname,'results');
(async()=>{
 const base=process.env.QA_URL;assert(base&&new URL(base).port==='19001','Use the isolated QA database.');
 const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto(base);await page.waitForFunction(()=>state?.editions);
  const before=await page.evaluate(async()=>{
   state=seed();const r=state.records[0];
   state.editions[0].blocks[0].sources=[{id:r.id,revision:r.revision,title:r.title}];
   state.editions[0].blocks[0].photos=structuredClone(r.photos);
   const pub=structuredClone(state.editions[0]);pub.id='pub-trash-test';state.publications=[pub];
   await persist();return structuredClone(state);
  });
  await page.goto(base+'/#registro/r1');await page.click('#trash-record');await page.click('#cancel-trash');
  assert(!await page.evaluate(()=>state.records[0].deletedAt));
  await page.click('#trash-record');await page.click('#confirm-trash');await page.waitForURL(/#registros$/);
  assert.equal(await page.locator('#record-grid a[href="#registro/r1"]').count(),0);
  await page.reload();await page.getByRole('link',{name:'Lixeira (1)',exact:true}).waitFor();
  const trashed=await page.evaluate(()=>structuredClone(state));
  assert(trashed.records.find(r=>r.id==='r1').deletedAt);assert.deepEqual(trashed.editions,before.editions);assert.deepEqual(trashed.publications,before.publications);
  await page.goto(base+'/#selecionar/e1');await page.locator('#add-separate').waitFor();assert.equal(await page.locator('#select-r1').count(),0);
  await page.goto(base+'/#editor/e1');await page.getByText('Registro na lixeira · cópia preservada',{exact:true}).waitFor();
  for(const route of ['novo','complemento']){await page.goto(base+'/#'+route+'/r1');await page.locator('#restore-record').waitFor();assert.equal(await page.locator('textarea').count(),0);}
  await page.selectOption('#role','funcionario');assert.equal(await page.locator('#restore-record').count(),0);
  await page.goto(base+'/#lixeira');await page.getByText('Disponível na visão de Editor.',{exact:true}).waitFor();assert.equal(await page.locator('[data-restore-record]').count(),0);
  await page.selectOption('#role','editor');await page.getByRole('button',{name:'Restaurar registro',exact:true}).waitFor();
  await page.fill('#trash-search','não existe');assert.equal(await page.locator('[data-restore-record]').count(),0);await page.fill('#trash-search','jardinagem');
  await page.setViewportSize({width:390,height:900});await page.screenshot({path:path.join(out,'trash-mobile.png'),fullPage:true});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.getByRole('button',{name:'Restaurar registro',exact:true}).click();await page.waitForURL(/#registro\/r1$/);
  await page.reload();await page.locator('#trash-record').waitFor();
  const restored=await page.evaluate(()=>structuredClone(state));const record=restored.records.find(r=>r.id==='r1');
  assert(!record.deletedAt);assert.equal(record.status,before.records[0].status);assert.equal(record.revision,before.records[0].revision);assert.deepEqual(record.photos,before.records[0].photos);
  assert.deepEqual(restored.editions,before.editions);assert.deepEqual(restored.publications,before.publications);
  await page.goto(base+'/#selecionar/e1');await page.locator('#select-r1').waitFor();
  assert.deepEqual(errors,[]);
  console.log('PASS: cancel, trash, reload, active filters, source preservation, edit guards, demo role visibility, search, mobile, restore with original status/photos/revision.');
 }finally{await browser.close();}
})();
