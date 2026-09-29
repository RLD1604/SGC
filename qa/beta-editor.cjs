const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const assert=require('node:assert/strict');
const path=require('node:path');
const out=process.env.QA_RESULTS_DIR||path.join(__dirname,'results');
(async()=>{
  const base=process.env.QA_URL;
  assert(base&&new URL(base).port==='19001','Use the isolated test server.');
  const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:1100}});
  const errors=[],external=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(/^https?:/.test(r.url())&&new URL(r.url()).origin!==new URL(base).origin)external.push(r.url());});
  try {
    await page.goto(base+'/#nota');
    await page.waitForFunction(()=>tinymce.get('record-text')?.initialized);
    assert.equal(await page.inputValue('[name="category"]'),'Nota solta');
    await page.getByRole('button',{name:'Mais ferramentas',exact:true}).click();
    await page.getByRole('menubar').getByRole('menuitem',{name:'Editar',exact:true}).waitFor();
    await page.fill('[name="title"]','Nota solta Beta: comunicação à equipe');
    await page.evaluate(()=>tinymce.get('record-text').setContent('<p><br></p>'));
    await page.click('button[value="review"]');
    assert.match(await page.locator('#toast').innerText(),/Preencha o assunto/);
    await page.evaluate(()=>{
      const ed=tinymce.get('record-text');
      ed.setContent('<p style="text-align: center; line-height: 2; margin-bottom: 12pt"><span style="font-family: Georgia; font-size: 18pt; color: #684b91">Aviso da administração</span></p><table><tbody><tr><td colspan="2">Serviço concluído</td></tr></tbody></table>');
      ed.selection.select(ed.getBody().querySelector('span'));ed.execCommand('Bold');
    });
    await page.evaluate(()=>tinymce.get('record-text').focus());
    await page.keyboard.press('Escape');
    await page.keyboard.press('Control+s');
    await page.waitForURL(/#registro\//);
    const recordId=page.url().split('/').at(-1);
    await page.reload();await page.locator('.rich-content table').first().waitFor();
    let saved=await page.evaluate(id=>state.records.find(r=>r.id===id),recordId);
    assert(saved.textHtml.includes('font-size: 18pt'));
    assert(/<(strong|b)[ >]/.test(saved.textHtml));
    assert(!saved.text.includes('<p>'));assert(saved.text.includes('Aviso da administração'));
    await page.click('#approve-record');
    await page.waitForFunction(id=>state.records.find(r=>r.id===id)?.status==='ready',recordId);
    await page.waitForFunction(()=>document.querySelector('#toast')?.textContent==='Registro conferido.');
    const editionId=await page.evaluate(()=>state.editions[0].id);
    await page.goto(base+'/#selecionar/'+editionId);
    try{await page.check('#select-'+recordId);}catch(error){
      console.error('Selection diagnostic',await page.evaluate(id=>({url:location.href,ids:state.records.map(r=>({id:r.id,status:r.status,title:r.title})),html:document.querySelector('#main')?.innerText.slice(0,500)}),recordId));
      throw error;
    }
    await page.click('#add-separate');
    await page.waitForFunction(()=>editor?.instance?.initialized);
    assert.match(await page.inputValue('#block-title'),/Nota solta Beta/);
    assert(await page.evaluate(()=>editor.value.includes('font-size: 18pt')&&editor.value.includes('colspan="2"')));
    await page.click('#save-editor');
    await page.waitForFunction(()=>document.querySelector('#toast').textContent==='Edição salva no PostgreSQL.');
    await page.goto(base+'/#registro/'+recordId);await page.click('#request-fix');
    await page.waitForFunction(()=>tinymce.get('feedback')?.initialized);
    await page.evaluate(()=>tinymce.get('feedback').setContent('<p><strong>Completar:</strong></p><ol><li>Confirmar data.</li><li>Informar prestador.</li></ol>'));
    await page.click('#save-feedback');await page.waitForURL(/#registro\//);
    await page.reload();await page.locator('.rich-content ol').waitFor();
    saved=await page.evaluate(id=>state.records.find(r=>r.id===id),recordId);
    assert.equal(saved.status,'fix');assert(saved.feedbackHtml.includes('<ol>'));
    await page.goto(base+'/#novo/'+recordId);await page.waitForFunction(()=>tinymce.get('record-text')?.initialized);
    assert(await page.evaluate(()=>tinymce.get('record-text').getContent().includes('font-size: 18pt')));
    await page.screenshot({path:path.join(out,'beta-nota-desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:900});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    assert((await page.locator('#record-text_ifr').boundingBox()).height>=220,'Mobile must keep the writing area visible.');
    await page.screenshot({path:path.join(out,'beta-nota-mobile.png'),fullPage:true});
    for(let i=0;i<3;i++) {
      await page.evaluate(()=>location.hash='#registros');await page.locator('#record-grid').waitFor();
      await page.evaluate(()=>location.hash='#nota');await page.locator('#record-form').waitFor();
    }
    await page.waitForFunction(()=>tinymce.get('record-text')?.initialized);
    assert.equal(await page.locator('.tox-tinymce').count(),1,'Navigation must not leave duplicate editors.');
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    console.log('PASS: Portuguese UI; note editor; empty rich-text validation; bold; Ctrl+S; persisted formatting; formatted source to newsletter; rich feedback; reopening; mobile; no external editor requests.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
