const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const assert=require('node:assert/strict');
const base='http://localhost:9001';
(async()=>{
 const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1280,height:900}}),page=await context.newPage();
  page.on('request',request=>{assert.equal(request.method(),'GET','A verificação pós-publicação deve ser somente leitura.');});
  const health=await (await context.request.get(base+'/api/health')).json();assert.equal(health.status,'ok');assert.equal(health.schema,4);
  const payload=await (await context.request.get(base+'/api/state')).json();assert.equal(payload.revision,7);assert.equal(payload.state.records.length,5);assert.equal(payload.state.editions.length,3);
  const photo=payload.state.records.flatMap(record=>record.photos||[]).find(item=>item.src?.startsWith('/api/media/'));assert(photo,'Uma foto persistida deve existir.');
  const media=await context.request.get(base+photo.src);assert.equal(media.status(),200);assert.match(media.headers()['content-type']||'',/^image\//);
  const edition=payload.state.editions.find(item=>item.blocks?.length);assert(edition,'Um informe com conteúdo deve existir.');
  await page.goto(base+'/#previa/'+edition.id);await page.locator('.publication').waitFor();assert(await page.locator('.publication h1').count());
  console.log(JSON.stringify({passed:true,version:health.application.version,schema:health.schema,revision:payload.revision,records:payload.state.records.length,editions:payload.state.editions.length,photos:payload.state.records.flatMap(record=>record.photos||[]).length,preview:edition.id}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
