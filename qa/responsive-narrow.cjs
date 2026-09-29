const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const assert=require('node:assert/strict');
const base=process.env.QA_URL;
assert(base&&new URL(base).port==='19001','Use only the isolated QA server.');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
 try{
  const page=await browser.newPage();page.setDefaultTimeout(7000);
  const assertFits=async label=>assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),label+' causes horizontal page scroll');
  await page.goto(base);await page.waitForFunction(()=>state?.editions&&typeof seed==='function');await page.evaluate(async()=>{state=seed();await persist();});await page.reload();await page.waitForFunction(()=>state?.records?.length&&state?.editions?.length);
  const ids=await page.evaluate(()=>({record:state.records[0].id,edition:state.editions[0].id}));
  for(const width of [320,360,390]){
   await page.setViewportSize({width,height:900});
   for(const route of ['inicio','registros','novo','complemento/'+ids.record,'editor/'+ids.edition,'previa/'+ids.edition]){await page.goto(base+'/#'+route);await page.waitForFunction(()=>state?.editions);await page.waitForTimeout(120);await assertFits(width+' '+route);}
   await page.goto(base+'/#informes');await page.click('#new-edition');await assertFits(width+' new-edition modal');await page.locator('#dialog .close').click();
   await page.goto(base+'/#editor/'+ids.edition);await page.waitForFunction(()=>editor?.instance?.initialized);await page.evaluate(id=>{const e=state.editions.find(x=>x.id===id);e.blocks[0].body='<table><tr><th>Coluna muito longa</th><th>Outra coluna</th></tr><tr><td>Conteúdo</td><td>Conteúdo</td></tr></table>';render();},ids.edition);await page.waitForTimeout(120);await assertFits(width+' rich table');
  }
  console.log('PASS: main flows, modal, editor and tables fit 320/360/390px.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
