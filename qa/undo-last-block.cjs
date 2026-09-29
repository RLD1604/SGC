const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const assert=require('node:assert/strict');
const base=process.env.QA_URL;
assert(base&&new URL(base).port==='19001','Use only the isolated QA server.');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
 try{
  const page=await browser.newPage();page.setDefaultTimeout(7000);
  await page.goto(base);await page.waitForFunction(()=>state?.editions&&typeof seed==='function');await page.evaluate(async()=>{state=seed();await persist();});await page.reload();await page.waitForFunction(()=>state?.editions?.length);
  const editionId=await page.evaluate(()=>state.editions[0].id);await page.goto(base+'/#editor/'+editionId);await page.waitForFunction(()=>editor?.instance?.initialized);
  await page.evaluate(async id=>{const e=state.editions.find(x=>x.id===id);e.blocks=[{id:'undo-full',type:'Matéria',title:'Bloco completo',body:'<p><strong>Texto formatado</strong></p>',photos:[{src:'/images/jardim.jpg',phase:'Depois',caption:'Legenda completa'}],sources:[]}];activeBlock=0;await persist();render();},editionId);
  await page.waitForFunction(()=>editor?.instance?.initialized);await page.click('#delete-block');await page.waitForFunction(id=>state.editions.find(x=>x.id===id).blocks.length===0,editionId);
  assert.equal(await page.locator('#undo-block').count(),1,'undo must stay visible without a selected block');await page.click('#undo-block');await page.waitForFunction(()=>state.editions.find(x=>x.id==='e1').blocks.length===1);
  await page.waitForFunction(id=>(undoByEdition.get(id)||[]).length===0,editionId);
  const restored=await page.evaluate(id=>state.editions.find(x=>x.id===id).blocks[0],editionId);assert.equal(restored.title,'Bloco completo');assert.equal(restored.body,'<p><strong>Texto formatado</strong></p>');assert.equal(restored.photos[0].caption,'Legenda completa');
  await page.evaluate(()=>{undoByEdition.set('other-edition',[{edition:'other-edition',index:0,block:{id:'other',title:'Outro'}}]);});assert.equal(await page.evaluate(id=>undoByEdition.get(id).length,editionId),0,'undo is isolated by edition');
  console.log('PASS: last block undo is visible, restores complete content and stays scoped to its edition.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
