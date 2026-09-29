const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const assert=require('node:assert/strict');
const base=process.env.QA_URL;
assert(base&&new URL(base).port==='19001','Use only the isolated QA server.');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
 try{
  const page=await browser.newPage();page.setDefaultTimeout(7000);const external=[];
  page.on('request',request=>{if(!request.url().startsWith(base))external.push(request.url());});
  await page.goto(base+'/#novo');await page.waitForFunction(()=>tinymce.get('record-text')?.initialized);
  const prepared=await page.evaluate(()=>{const instance=tinymce.get('record-text');instance.setContent('<p>Texto sintético para teste.</p>');instance.fire('change');return instance.getContent({format:'text'});});
  assert.match(prepared,/Texto sintético/);
  await page.route('**/api/ai/status',route=>route.fulfill({json:{enabled:true,maxChars:6000,maxSegments:100}}));
  let posts=0;
  await page.route('**/api/ai/review',route=>{posts++;const body=route.request().postDataJSON();assert.equal(body.consent,true);assert.match(JSON.stringify(body),/Texto sintético/);assert.doesNotMatch(JSON.stringify(body),/secret|token|key/i);route.fulfill({status:503,json:{error:'IA indisponível para teste.'}});});
  await page.getByRole('button',{name:'Revisar com IA'}).click();await page.getByRole('button',{name:/Enviar texto/}).waitFor();assert.equal(posts,0,'must not send before explicit click');
  await page.getByRole('button',{name:/Enviar texto/}).click();await page.getByText('IA indisponível para teste.',{exact:true}).waitFor();assert.equal(posts,1);assert.match(await page.evaluate(()=>tinymce.get('record-text').getContent({format:'text'})),/Texto sintético/);
  await page.getByRole('button',{name:'Fechar sem aplicar'}).click();
  await page.unroute('**/api/ai/review');await page.route('**/api/ai/review',route=>route.fulfill({json:{changes:[{id:99,before:'incompatível',after:'não deve aplicar',reason:'teste'}]}}));
  await page.getByRole('button',{name:'Revisar com IA'}).click();await page.getByRole('button',{name:/Enviar texto/}).click();await page.getByText('As sugestões não correspondem ao texto enviado.',{exact:true}).waitFor();assert.match(await page.evaluate(()=>tinymce.get('record-text').getContent({format:'text'})),/Texto sintético/);
  assert.deepEqual(external,[]);console.log('PASS: IA simulada exige consentimento, mantém texto em falhas e não expõe segredo nem usa rede externa.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
