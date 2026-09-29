const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const assert=require('node:assert/strict');
const base=process.env.QA_URL;
assert(base&&new URL(base).port==='19001','Use only the isolated QA server.');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
 try{
  const page=await browser.newPage();page.setDefaultTimeout(7000);
  const go=async route=>{await page.goto(base+'/#'+route);await page.waitForFunction(()=>state?.editions);};
  const ready=()=>page.waitForFunction(()=>tinymce.get('record-text')?.initialized);
  await go('inicio');await page.evaluate(async()=>{state=seed();await persist();});await page.reload();await page.waitForFunction(()=>state?.records?.length&&state?.editions?.length);
  const ids=await page.evaluate(()=>({record:state.records[0].id,edition:state.editions[0].id}));
  await go('novo');await ready();
  await page.fill('[name=title]','   ');await page.evaluate(()=>tinymce.get('record-text').setContent('<p>&nbsp; <br></p>'));
  await page.click('button[value=review]');await page.getByText('Preencha o assunto e conte o que aconteceu antes de enviar.',{exact:true}).waitFor();assert(page.url().endsWith('#novo'));
  await page.fill('[name=title]','x'.repeat(161));assert.equal((await page.inputValue('[name=title]')).length,160);
  await page.click('nav a[href="#registros"]');await page.click('#draft-discard');await page.waitForURL(/#registros$/);
  await go('complemento/'+ids.record);await page.waitForFunction(()=>tinymce.get('feedback')?.initialized);await page.evaluate(()=>tinymce.get('feedback').setContent('<div> &nbsp; </div>'));await page.click('#save-feedback');await page.getByText('Escreva uma orientação para o funcionário.',{exact:true}).waitFor();assert(page.url().includes('#complemento/'+ids.record));
  await go('informes');await page.click('#new-edition');await page.fill('#edition-title','  ');await page.fill('#edition-period','\t ');await page.click('#create-edition');assert(await page.locator('#dialog').isVisible());await page.getByText('Informe o título e o período.',{exact:true}).waitFor();
  await page.locator('#dialog .close').click();await go('editor/'+ids.edition);await page.waitForFunction(()=>editor?.instance?.initialized);await page.fill('#title-edition',' ');await page.fill('#period-edition','\n');await page.click('#save-editor');await page.getByText('Informe título e período antes de salvar a edição.',{exact:true}).waitFor();assert.equal((await page.inputValue('#title-edition')).trim(),'');
  console.log('PASS: frontend validation rejects whitespace-only required fields and keeps entered content.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
