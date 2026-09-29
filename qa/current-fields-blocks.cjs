// Authenticated field-by-field and block-by-block test on port 19001 only.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const assert=require('node:assert/strict');
const base=process.env.QA_URL,login=process.env.QA_BROWSER_LOGIN,password=process.env.QA_BROWSER_PASSWORD;
assert(base&&new URL(base).port==='19001','Use somente a instância descartável na porta 19001.');
assert(login&&password,'Credenciais sintéticas de QA ausentes.');

(async()=>{
 const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:1050}}),page=await context.newPage();
 page.setDefaultTimeout(15000);
 const checks=[];
 const check=async(name,fn)=>{try{await fn();checks.push({name,passed:true});console.log('PASS '+name);}catch(error){checks.push({name,passed:false,error:error.message});console.error('FAIL '+name+': '+error.message);throw error;}};
 const open=async route=>{await page.goto(base+'/#'+route);await page.waitForFunction(()=>authSession&&state);};
 try{
  await check('Login individual',async()=>{
   await page.goto(base);await page.locator('#login-form').waitFor();
   await page.fill('#login-form [name=login]',login);await page.fill('#login-form [name=password]',password);
   const loginResponse=page.waitForResponse(response=>response.url().endsWith('/api/auth/login')&&response.request().method()==='POST');
   await page.click('#login-form button[type=submit]');
   const response=await loginResponse;
   if(response.status()!==200)throw new Error('Login HTTP '+response.status());
   await page.waitForFunction(()=>authSession?.display_name==='QA Navegador'&&state);
   assert.match(await page.locator('.sidebar-bottom').innerText(),/QA Navegador/);
  });
  let recordId,editionId;
  await check('Campos do registro e limites',async()=>{
   await open('novo');await page.waitForFunction(()=>tinymce.get('record-text')?.initialized);
   await page.fill('[name=title]','x'.repeat(161));assert.equal((await page.inputValue('[name=title]')).length,160);
   await page.fill('[name=title]','QA: manutenção da iluminação');
   await page.fill('[name=local]','Garagem do Bloco A');await page.fill('[name=date]','2026-09-29');await page.fill('[name=who]','Equipe de manutenção');
   await page.selectOption('[name=category]','Manutenção');await page.selectOption('[name=progress]','Concluído');
   await page.evaluate(()=>{const e=tinymce.get('record-text');e.setContent('<p>Foram substituídas 18 luminárias e revisados os sensores.</p>');e.fire('change');});
   await page.click('button[value=review]');await page.waitForURL(/#registro\//);recordId=await page.evaluate(()=>location.hash.split('/')[1]);
   const item=await page.evaluate(id=>state.records.find(r=>r.id===id),recordId);
   assert.equal(item.title,'QA: manutenção da iluminação');assert.equal(item.local,'Garagem do Bloco A');assert.equal(item.who,'Equipe de manutenção');
   assert.equal(item.date,'2026-09-29');assert.equal(item.category,'Manutenção');assert.equal(item.progress,'Concluído');assert.equal(item.status,'review');
  });
  await check('Conferência pelo perfil gestor',async()=>{
   await page.click('#approve-record');await page.waitForFunction(id=>state.records.find(r=>r.id===id)?.status==='ready',recordId);
  });
  await check('Criação do informe',async()=>{
   await open('informes');await page.click('#new-edition');await page.fill('#edition-title','Informe QA autenticado');await page.fill('#edition-period','Setembro de 2026');await page.click('#create-edition');
   await page.waitForURL(/#editor\//);editionId=await page.evaluate(()=>location.hash.split('/')[1]);
  });
  await check('Inclusão da fonte conferida',async()=>{
   await page.goto(base+'/#selecionar/'+editionId);await page.locator('#select-'+recordId).waitFor();await page.check('#select-'+recordId);await page.click('#add-separate');
   await page.waitForURL(new RegExp('#editor/'+editionId));await page.waitForFunction(()=>editor?.instance?.initialized);
  });
  await check('Campos do bloco editorial',async()=>{
   await page.fill('#title-edition','Informe QA — Setembro');await page.fill('#period-edition','Setembro de 2026');
   await page.fill('#block-type','Manutenção');await page.fill('#block-title','Iluminação da garagem renovada');
   await page.evaluate(()=>{editor.value='<p>O serviço foi concluído sem interromper o acesso de veículos.</p>';});
   await page.click('#save-editor');await page.waitForFunction(()=>document.querySelector('#toast').textContent==='Edição salva no PostgreSQL.');
   const edition=await page.evaluate(id=>state.editions.find(e=>e.id===id),editionId);
   assert.equal(edition.title,'Informe QA — Setembro');assert.equal(edition.period,'Setembro de 2026');
   assert.equal(edition.blocks[0].type,'Manutenção');assert.equal(edition.blocks[0].title,'Iluminação da garagem renovada');assert.match(edition.blocks[0].body,/sem interromper/);
  });
  await check('Duplicar, remover e desfazer bloco',async()=>{
   const duplicateControl=await page.evaluate(()=>({present:!!document.querySelector('#duplicate-block'),handler:typeof document.querySelector('#duplicate-block')?.onclick,disabled:document.querySelector('#duplicate-block')?.disabled}));
   assert.deepEqual(duplicateControl,{present:true,handler:'function',disabled:false});
   await page.evaluate(()=>document.querySelector('#duplicate-block').click());await page.waitForTimeout(800);
   const afterDuplicate=await page.evaluate(id=>({blocks:state.editions.find(e=>e.id===id)?.blocks.length,toast:document.querySelector('#toast')?.textContent,recovery:document.querySelector('#storage-recovery')?.textContent||''}),editionId);
   assert.equal(afterDuplicate.blocks,2,JSON.stringify(afterDuplicate));
   await page.click('#delete-block');await page.waitForFunction(id=>state.editions.find(e=>e.id===id).blocks.length===1,editionId);
   await page.click('#undo-block');await page.waitForFunction(id=>state.editions.find(e=>e.id===id).blocks.length===2,editionId);
  });
  await check('Prévia sem publicação automática',async()=>{
   await page.click('#go-preview');await page.waitForURL(new RegExp('#previa/'+editionId));
   assert.equal(await page.locator('.publication').count(),1);assert.match(await page.locator('.publication').innerText(),/Informe QA/);
   const workspace=await (await page.request.get(base+'/api/workspace')).json();assert.equal(workspace.state.publications.length,0);
  });
  await check('Logout e novo login',async()=>{
   await page.click('#logout');await page.locator('#login-form').waitFor();
   await page.fill('#login-form [name=login]',login);await page.fill('#login-form [name=password]',password);await page.click('#login-form button[type=submit]');
   await page.waitForFunction(()=>authSession?.display_name==='QA Navegador'&&state);
  });
 }finally{
  console.log(JSON.stringify({passed:checks.every(x=>x.passed),total:checks.length,checks}));await browser.close();
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
