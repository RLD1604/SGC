const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
 const context=await browser.newContext();const page=await context.newPage();
 try {
  const base=process.env.QA_URL;
  assert(base&&new URL(base).port==='19001','Use only the isolated QA server.');
  await page.goto(base+'/#novo');await page.locator('#record-form').waitFor();
  const result=await page.evaluate(async()=>{
   const cases=[];
   for(const [width,height] of [[1920,1080],[1080,1920],[1200,1200],[80,40]]){
    const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;
    const ctx=canvas.getContext('2d');
    for(let x=0;x<width;x+=8){ctx.fillStyle=`rgb(${x%256},${(x*7)%256},${(x*13)%256})`;ctx.fillRect(x,0,8,height)}
    const input=await new Promise(r=>canvas.toBlob(r,'image/png'));
    const optimized=await optimizePhotoBlob(input);
    const decoded=await createImageBitmap(await(await fetch(optimized.src)).blob());
    cases.push({input:[width,height],actual:[decoded.width,decoded.height],before:input.size,after:optimized.bytes,mime:optimized.mime});decoded.close();
   }
   const original=structuredClone(seed().editions[0]);
   original.blocks[0].photos=[{src:'/images/jardim.jpg',phase:'Antes',caption:'Manter legenda'}];
   const serialized=JSON.stringify(original),compact=await optimizedEditionCopy(original),again=await optimizedEditionCopy(compact);
   const photo=compact.blocks[0].photos[0];
   return {cases,sourceUnchanged:JSON.stringify(original)===serialized,idempotent:photo.src===again.blocks[0].photos[0].src,caption:photo.caption,photoBytes:photo.bytes,originalBytes:photo.originalBytes,coverEmbedded:compact.cover.startsWith('data:')};
  });
  assert.deepEqual(result.cases[0].actual,[1065,599]);
  assert.deepEqual(result.cases[1].actual,[599,1065]);
  assert.deepEqual(result.cases[2].actual,[600,600]);
  assert.deepEqual(result.cases[3].actual,[80,40]);
  assert(result.cases.slice(0,3).every(x=>x.after<x.before));
  assert(result.sourceUnchanged&&result.idempotent&&result.coverEmbedded);
  assert.equal(result.caption,'Manter legenda');assert(result.photoBytes<result.originalBytes);
  await page.locator('#photos-input').setInputFiles('prototipo-condominio/public/images/jardim.jpg');
  await page.waitForFunction(()=>workingPhotos.length===1&&document.querySelector('#photos-input').disabled===false);
  await page.fill('[name="title"]','Teste de foto otimizada');await page.waitForFunction(()=>tinymce.get('record-text')?.initialized);await page.evaluate(()=>tinymce.get('record-text').setContent('<p>Registro de teste isolado.</p>'));
  await page.locator('button[value="draft"]').click();await page.waitForURL(/#registro/);
  await page.reload();await page.locator('.photos-detail img').waitFor();
  const persisted=await page.evaluate(()=>{const p=state.records.at(-1).photos[0];return {width:p.width,height:p.height,bytes:p.bytes,version:p.optimizationVersion,mime:p.mime}});
  assert.equal(persisted.version,2);assert(persisted.width<=600&&persisted.height<=1065);
  console.log(JSON.stringify({passed:true,...result,persisted},null,2));
 } finally {await context.close();await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});

