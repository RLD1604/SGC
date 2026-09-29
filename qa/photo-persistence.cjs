const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const assert=require('node:assert/strict');
const path=require('node:path');
(async()=>{
 const base=process.env.QA_URL;assert(base&&new URL(base).port==='19001');
 const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1050}});
 try{
  await page.goto(base);await page.waitForFunction(()=>Array.isArray(state?.records));
  if(!await page.evaluate(()=>state.records.some(r=>r.title==='Teste de foto otimizada'))){
   await page.goto(base+'/#novo');await page.waitForFunction(()=>tinymce.get('record-text')?.initialized);
   await page.locator('#photos-input').setInputFiles(path.join(__dirname,'../public/images/jardim.jpg'));
   await page.waitForFunction(()=>workingPhotos.length===1&&!document.querySelector('#photos-input').disabled);
   await page.fill('[name="title"]','Teste de foto otimizada');
   await page.evaluate(()=>tinymce.get('record-text').setContent('<p>Registro de teste isolado.</p>'));
   await page.locator('button[value="draft"]').click();await page.waitForURL(/#registro/);
  }
  const before=await page.evaluate(async()=>{
   const record=state.records.find(r=>r.title==='Teste de foto otimizada');
   if(!record)throw Error('Run photo-optimizer.cjs first.');
   const photo=record.photos[0];let edition=state.editions.find(e=>e.id==='e1');
   if(!edition){edition={id:'e1',title:'Informe de teste',period:'Etapa 5',status:'draft',blocks:[],cover:'/images/jardim.jpg',version:1};state.editions.push(edition);}
   edition.blocks=[{id:'photo-qa',type:'Matéria',title:'Foto em destaque',body:'<p>Texto preservado</p>',photos:[structuredClone(photo)],sources:[]}];
   await persist();return {recordId:record.id,photo:structuredClone(photo)};
  });
  assert(before.photo.masterSrc.startsWith('/api/media/'));assert.equal(before.photo.masterSrc,before.photo.originalSrc);
  await page.goto(base+'/#editor/e1');await page.waitForFunction(()=>editor?.instance?.initialized);
  await page.fill('#block-title','Título não salvo ainda');
  await page.getByRole('button',{name:'Foto em destaque',exact:true}).click();
  await page.getByRole('button',{name:'Usar tamanho padrão',exact:true}).waitFor();
  assert.equal(await page.inputValue('#block-title'),'Título não salvo ainda');
  await page.getByRole('button',{name:'Ajustar foto',exact:true}).click();
  await page.getByText('Enquadramento',{exact:true}).click();await page.getByText('Girar',{exact:true}).click();await page.getByText('+90°',{exact:true}).click();
  await page.getByRole('button',{name:'Aplicar ajustes',exact:true}).click();await page.locator('.photo-editor-dialog').waitFor({state:'detached'});
  await page.click('#save-editor');await page.waitForFunction(()=>document.querySelector('#toast').textContent==='Edição salva no PostgreSQL.');
  await page.reload();await page.waitForFunction(()=>editor?.instance?.initialized);
  const after=await page.evaluate(id=>({record:state.records.find(r=>r.id===id).photos[0],block:state.editions.find(e=>e.id==='e1').blocks[0]}),before.recordId);
  assert.deepEqual(after.record,before.photo);assert.equal(after.block.title,'Título não salvo ainda');
  const photo=after.block.photos[0];assert(photo.featured);assert(photo.width>photo.height);assert(photo.masterSrc.startsWith('/api/media/'));assert.notEqual(photo.masterSrc,before.photo.masterSrc);assert.equal(photo.originalSrc,before.photo.originalSrc);
  await page.goto(base+'/#previa/e1');await page.locator('.featured-photo img').waitFor();
  assert((await page.locator('.public-photos .featured-photo').boundingBox()).width>355);
  const exportInfo=await page.evaluate(async()=>{const compact=await optimizedEditionCopy(state.editions.find(e=>e.id==='e1'));return {html:publicationHTML(compact),photo:compact.blocks[0].photos[0]};});
  assert(!exportInfo.photo.masterSrc&&!exportInfo.photo.originalSrc);assert(exportInfo.html.includes('featured-photo'));assert(exportInfo.photo.src.startsWith('data:'));
  console.log('PASS: real DB master references, edited photo persists, source record unchanged, unsaved text retained, featured preview and compact export.');
 }finally{await browser.close();}
})();
