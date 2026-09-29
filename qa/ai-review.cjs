const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const assert=require('node:assert/strict');
(async()=>{
 const base=process.env.QA_URL;assert(base&&new URL(base).port==='19001','Use isolated QA server.');
 const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1050}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 try {
  await page.goto(base+'/#nota');await page.waitForFunction(()=>tinymce.get('record-text')?.initialized);
  const initial='<p style="color: #684b91;"><strong>Os serviço foi feito em 10/09.</strong></p><p>A equipe realizaram a limpeza.</p>';
  await page.evaluate(html=>tinymce.get('record-text').setContent(html),initial);
  await page.getByRole('button',{name:'Revisar com IA',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.ai-status').textContent.includes('falta configurar'));
  await page.click('.ai-cancel');
  let calls=0;
  await page.route('**/api/ai/status',route=>route.fulfill({json:{enabled:true,maxChars:6000,maxSegments:100}}));
  await page.route('**/api/ai/review',route=>{
   calls++;const body=route.request().postDataJSON();assert.equal(body.consent,true);assert(!JSON.stringify(body).includes('<strong>'));
   route.fulfill({json:{changes:body.segments.map(s=>({id:s.id,before:s.text,after:s.id===0?'Os serviços foram feitos em 10/09.':'A equipe realizou a limpeza.',reason:'Correção de concordância.'}))}});
  });
  await page.getByRole('button',{name:'Revisar com IA',exact:true}).click();
  await page.locator('.ai-request:not([disabled])').waitFor();assert.equal(calls,0);
  await page.click('.ai-request');await page.locator('.ai-apply:not([hidden])').waitFor();
  assert(await page.evaluate(()=>tinymce.get('record-text').getContent({format:'text'}).includes('Os serviço')));
  await page.uncheck('[data-change="1"]');await page.click('.ai-apply');
  const applied=await page.evaluate(()=>({html:tinymce.get('record-text').getContent(),text:tinymce.get('record-text').getContent({format:'text'})}));
  assert(applied.text.includes('Os serviços foram feitos em 10/09.'));assert(applied.text.includes('A equipe realizaram'));assert(applied.html.includes('<strong>'));assert(applied.html.includes('#684b91'));
  await page.evaluate(()=>tinymce.get('record-text').undoManager.undo());
  assert(await page.evaluate(()=>tinymce.get('record-text').getContent({format:'text'}).includes('Os serviço')));
  await page.getByRole('button',{name:'Revisar com IA',exact:true}).click();await page.click('.ai-request');await page.locator('.ai-apply:not([hidden])').waitFor();
  await page.evaluate(()=>tinymce.get('record-text').setContent('<p>Texto alterado durante a revisão.</p>'));
  await page.click('.ai-apply');assert.match(await page.locator('.ai-status').innerText(),/texto mudou/);
  await page.click('.ai-cancel');assert(await page.evaluate(()=>tinymce.get('record-text').getContent().includes('Texto alterado')));
  assert.deepEqual(errors,[]);console.log('PASS: missing key; explicit send; mocked suggestions; selective apply; original formatting; undo; stale-text rejection; no automatic save. No real cloud request.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
