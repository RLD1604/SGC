const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const assert=require('node:assert/strict');
const path=require('node:path');
const out=process.env.QA_RESULTS_DIR||path.join(__dirname,'results');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 // Static preview, all API traffic mocked: no changes to the condominium database.
 await page.route('**/api/**',route=>route.fulfill({json:{revision:1,state:{records:[],editions:[],publications:[]}}}));
 try{
  await page.goto('http://127.0.0.1:19001/#nota');
  await page.waitForFunction(()=>tinymce.get('record-text')?.initialized);
  const toggle=page.getByRole('button',{name:'Mais ferramentas',exact:true});
  await toggle.waitFor();assert.equal(await toggle.getAttribute('aria-expanded'),'false');
  assert.equal(await page.getByRole('menubar').isVisible(),false);
  assert.equal(await page.locator('.tox-toolbar-overlord>.tox-toolbar').nth(1).isVisible(),false);
  await page.evaluate(()=>tinymce.get('record-text').setContent('<p>Texto original de teste.</p>'));
  const before=await page.evaluate(()=>tinymce.get('record-text').getContent());
  await toggle.click();assert(await page.getByRole('menubar').isVisible());
  await page.getByRole('button',{name:'Recolher ferramentas',exact:true}).click();
  assert.equal(await page.evaluate(()=>tinymce.get('record-text').getContent()),before);
  await page.evaluate(()=>{const ed=tinymce.get('record-text');ed.focus();ed.selection.select(ed.getBody().querySelector('p'));ed.nodeChanged();});
  await page.locator('.tox-pop .tox-tbtn').first().waitFor();
  await page.evaluate(()=>tinymce.get('record-text').execCommand('mceFullScreen'));
  assert(await page.locator('.tox-fullscreen .processor-toggle').isVisible());
  await page.evaluate(()=>tinymce.get('record-text').execCommand('mceFullScreen'));
  await page.setViewportSize({width:390,height:900});
  assert((await page.locator('#record-text_ifr').boundingBox()).height>=220);
  await page.waitForTimeout(300); assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:path.join(out,'compact-editor-mobile.png'),fullPage:true});
  await page.getByRole('button',{name:'Mais ferramentas',exact:true}).click();
  await page.reload();await page.getByRole('button',{name:'Recolher ferramentas',exact:true}).waitFor();
  assert.deepEqual(errors,[]);
  console.log('PASS: toggle, preserved content, contextual toolbar, fullscreen, mobile and remembered preference.');
 }finally{await browser.close();}
})();


