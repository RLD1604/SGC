// Etapa 4 acceptance for P3-09.  It checks responsive behaviour only on the
// disposable QA service, never against the workstation service on port 9001.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const assert=require('node:assert/strict');

const base=process.env.QA_URL;
assert(base&&new URL(base).port==='19001','Use somente a porta isolada 19001.');

(async()=>{
 const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
 const page=await browser.newPage({viewport:{width:390,height:900}});
 page.setDefaultTimeout(15000);let template;const checks=[];
 const check=async(name,fn)=>{try{await fn();checks.push({name,passed:true});console.log('PASS '+name);}catch(error){checks.push({name,passed:false,error:error.message});console.log('FAIL '+name);}};
 const clone=value=>structuredClone(value);
 const get=async()=>await (await page.request.get(base+'/api/state')).json();
 const reset=async()=>{const before=await get(),state=clone(template);const edition=state.editions.find(e=>e.id==='e1');
   edition.blocks[0].body='<table><thead><tr><th>Item</th><th>Detalhe</th></tr></thead><tbody><tr><td>Manutenção</td><td>Conteúdo rico com uma descrição suficientemente longa para testar a quebra de linha sem ampliar a página.</td></tr></tbody></table><p><strong>Texto formatado</strong> após a tabela.</p>';
   edition.blocks[0].photos=[{src:'/images/jardim.jpg',phase:'Depois',caption:'Foto da galeria responsiva'}];
   const response=await page.request.put(base+'/api/state',{data:{revision:before.revision,state}});assert.equal(response.status(),200);await page.reload();await page.waitForFunction(()=>state?.editions);};
 const open=async route=>{await page.goto(base+'/#'+route);await page.waitForFunction(()=>state?.editions&&document.querySelector('#main'));};
 const noOverflow=async(label)=>assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,label+' tem rolagem horizontal');
 const accessible=async(selector,label)=>{const node=page.locator(selector).first();await node.waitFor({state:'visible'});const box=await node.boundingBox();assert(box,label+' sem caixa visível');const width=await page.evaluate(()=>innerWidth);assert(box.x>=-1&&box.x+box.width<=width+1,label+' está fora da largura visível');};
 try{
  await page.goto(base);await page.waitForFunction(()=>state?.editions&&typeof seed==='function');template=await page.evaluate(()=>seed());
  await reset();
  for(const width of [320,360,390,768,1440]) await check('P3-09: largura '+width+' mantém conteúdo e controles acessíveis',async()=>{
   await page.setViewportSize({width,height:900});

   await open('registros');await noOverflow('Registros');
   await accessible('nav','navegação');await accessible('#search','pesquisa');await accessible('#filter-status','filtro de situação');await accessible('#filter-category','filtro de categoria');await accessible('.record-card','card de registro');

   await open('novo');await page.waitForFunction(()=>tinymce.get('record-text')?.initialized);await noOverflow('Novo registro');
   await accessible('[name=title]','assunto');await accessible('.tox-tinymce','editor TinyMCE');await accessible('#photos-input','envio de foto');await accessible('button[value=draft]','salvar registro');await accessible('button[value=review]','enviar registro');
   // This is a real navigation-guard modal, rather than merely testing an
   // empty dialog element hidden in the page template.
   await page.fill('[name=title]','Modal responsivo '+width);await page.click('nav a[href="#registros"]');await page.locator('#draft-navigation').waitFor();await noOverflow('Modal de rascunho');
   for(const id of ['#draft-save','#draft-stay','#draft-discard'])await accessible(id,'ação do modal '+id);
   await page.click('#draft-discard');await page.waitForURL(/#registros$/);

   await open('informes');await page.click('#new-edition');await page.locator('#dialog[open]').waitFor();await noOverflow('Modal de novo informe');
   await accessible('#edition-title','título no modal');await accessible('#edition-period','período no modal');await accessible('#create-edition','criar informe');await page.locator('#dialog .close').click();

   await open('editor/e1');await page.waitForFunction(()=>editor?.instance?.initialized);await noOverflow('Editor de informe');
   await accessible('#title-edition','título do informe');await accessible('#period-edition','período do informe');await accessible('.tox-tinymce','TinyMCE editorial');await accessible('#save-editor','salvar informe');await accessible('#go-preview','ir para prévia');

   await open('previa/e1');await noOverflow('Prévia com tabela e foto');await accessible('#finalize','finalizar informe');await accessible('.publication table','tabela rica');await accessible('.public-photos img','foto na prévia');
  });
 }finally{await browser.close();}
 console.log(JSON.stringify({passed:checks.filter(c=>c.passed).length,total:checks.length,checks}));
 process.exitCode=checks.every(c=>c.passed)?0:1;
})().catch(error=>{console.error(error);process.exitCode=1;});
