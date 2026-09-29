const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const assert=require('node:assert/strict');
const path=require('node:path');
const out=process.env.QA_RESULTS_DIR||path.join(__dirname,'results');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1050}}),errors=[],external=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(r.url().startsWith('http')&&!r.url().startsWith('http://127.0.0.1:19001'))external.push(r.url());});
 let state={records:[],editions:[{id:'e1',title:'Teste',period:'Setembro',version:1,blocks:[]}],publications:[]};
 await page.route('**/api/**',route=>{if(route.request().method()==='PUT')state=route.request().postDataJSON().state;return route.fulfill({json:{revision:1,state}});});
 try{
  await page.goto('http://127.0.0.1:19001/#nota');await page.waitForFunction(()=>tinymce.get('record-text')?.initialized);
  const data=await page.evaluate(async()=>{
   const canvas=document.createElement('canvas');canvas.width=2400;canvas.height=1600;
   const ctx=canvas.getContext('2d');ctx.fillStyle='#3a6a9a';ctx.fillRect(0,0,2400,1600);ctx.fillStyle='white';ctx.font='100px Arial';ctx.fillText('Registro de manutenção',100,300);ctx.fillRect(100,500,1000,400);
   const blob=await new Promise(r=>canvas.toBlob(r,'image/png'));const p=await preparePhoto(blob);
   workingPhotos.push({...p,phase:'Antes',caption:'Foto de teste'});photoList();
   const bitmap=await createImageBitmap(await (await fetch(p.masterSrc)).blob());
   return {width:p.width,height:p.height,masterWidth:bitmap.width,masterHeight:bitmap.height,src:p.src};
  });
  assert.equal(data.width,900);assert.equal(data.height,600);assert.equal(data.masterWidth,2048);
  await page.getByRole('button',{name:'Ajustar foto',exact:true}).click();
  await page.getByText('Luz e cores',{exact:true}).waitFor();
  await page.locator('.photo-editor-host canvas').first().waitFor();
  await page.screenshot({path:path.join(out,'photo-editor-desktop.png'),fullPage:true});
  await page.getByRole('button',{name:'Cancelar',exact:true}).click();
  assert.equal(await page.evaluate(()=>workingPhotos[0].src),data.src);
  await page.getByRole('button',{name:'Ajustar foto',exact:true}).click();
  await page.getByText('Enquadramento',{exact:true}).click();
  await page.getByText('Girar',{exact:true}).click();
  await page.getByText('+90°',{exact:true}).click();
  await page.getByRole('button',{name:'Aplicar ajustes',exact:true}).click();
  await page.locator('.photo-editor-dialog').waitFor({state:'detached'});
  const updated=await page.evaluate(()=>({width:workingPhotos[0].width,height:workingPhotos[0].height,original:workingPhotos[0].originalSrc,master:workingPhotos[0].masterSrc}));
  console.log('Saved dimensions',updated.width,updated.height);
  assert.equal(updated.width,600);assert.equal(updated.height,900);
  await page.getByRole('button',{name:'Ajustar foto',exact:true}).click();
  await page.getByRole('button',{name:'Restaurar cópia guardada'}).click();await page.locator('.photo-editor-dialog').waitFor({state:'detached'});
  const restored=await page.evaluate(()=>workingPhotos[0]);assert.equal(restored.width,900);assert.equal(restored.height,600);assert.equal(restored.originalSrc,updated.original);
  const compact=await page.evaluate(async()=>{const copy=await optimizedEditionCopy({blocks:[{photos:workingPhotos}]});return {keys:Object.keys(copy.blocks[0].photos[0]),width:copy.blocks[0].photos[0].width};});
  assert(!compact.keys.includes('masterSrc'));assert(!compact.keys.includes('originalSrc'));assert.equal(compact.width,900);
  await page.setViewportSize({width:390,height:900});await page.getByRole('button',{name:'Ajustar foto',exact:true}).click();await page.getByRole('button',{name:'Aplicar ajustes',exact:true}).waitFor();
  await page.screenshot({path:path.join(out,'photo-editor-mobile.png'),fullPage:true});
  assert((await page.locator('.photo-editor-dialog').boundingBox()).width<=390);
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
  console.log('PASS: 3x derivative, 2048px master, local editor, cancel, apply, restore, export excludes masters, desktop and mobile.');
 }finally{await browser.close();}
})();


