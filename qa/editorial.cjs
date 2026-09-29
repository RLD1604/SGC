const { chromium } = require(process.env.PLAYWRIGHT_MODULE);
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

(async()=>{
 const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:1100},acceptDownloads:true});
 const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try {
  const base=process.env.QA_URL;
  assert(base && new URL(base).port==='19001','Use QA_URL pointing to the isolated test server on port 19001.');
  await page.goto(base);
  await page.waitForFunction(()=>typeof state!=='undefined'&&state?.editions);
  await page.evaluate(async()=>{const publications=state.publications;state=seed();state.publications=publications;await persist();});
  await page.goto(base+'/#editor/e1');
  await page.locator('.tox-tinymce').waitFor();
  await page.click('#add-block');
  await page.fill('#custom-block-name','Prestação de contas');
  await page.click('#custom-block-form button');
  await page.waitForFunction(()=>document.querySelector('#block-type')?.value==='Prestação de contas');
  assert.equal(await page.inputValue('#block-title'),'Prestação de contas');
  await page.waitForFunction(()=>editor?.instance?.initialized);
  await page.evaluate(()=>{editor.value='<p style="text-align: center; line-height: 2; margin-bottom: 12pt"><span style="font-family: Georgia; font-size: 24pt; color: #684b91; background-color: #ffff00">Texto formatado</span></p><table><tbody><tr><td colspan="2" style="text-align: right; background-color: #e7f3eb">Célula mesclada</td></tr></tbody></table>';});
  await page.click('#save-editor');
  await page.waitForFunction(()=>document.querySelector('#toast')?.textContent==='Edição salva no PostgreSQL.');
  await page.reload();
  await page.locator('.tox-tinymce').waitFor();
  await page.getByRole('button',{name:'2. Prestação de contas',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#block-type')?.value==='Prestação de contas');
  await page.waitForFunction(()=>typeof editor!=='undefined'&&editor?.instance?.initialized&&editor.value.includes('Texto formatado'));
  const formatting=await page.evaluate(()=>{
    const p=editor.editor.querySelector('p'),s=editor.editor.querySelector('span');
    return {align:p.style.textAlign,line:p.style.lineHeight,space:p.style.marginBottom,font:s.style.fontFamily,size:s.style.fontSize,color:s.style.color,colspan:editor.editor.querySelector('td').getAttribute('colspan')};
  });
  assert.equal(formatting.align,'center');assert.equal(formatting.line,'2');assert.equal(formatting.space,'12pt');assert.equal(formatting.font,'Georgia');assert.equal(formatting.size,'24pt');assert.equal(formatting.colspan,'2');
  const safety=await page.evaluate(()=>sanitizeEditorialHTML('<p onclick="alert(1)" style="position:fixed;background-image:url(https://example.com/x);text-align:center">Seguro<script>alert(1)</script><a href="javascript:alert(1)">Link</a></p>'));
  assert(!/onclick|javascript:|<script|position:|background-image/.test(safety));assert(safety.includes('text-align: center'));
  await page.evaluate(async()=>{
    const canvas=document.createElement('canvas');canvas.width=200;canvas.height=400;canvas.getContext('2d').fillRect(0,0,200,400);
    const src=canvas.toDataURL();editorialImageSizes.set(src,{width:200,height:400});
    state.editions[0].blocks[1].photos=[{src:'/images/jardim.jpg',phase:'Antes',caption:'Horizontal',orientation:'landscape'},{src,phase:'Depois',caption:'Vertical',width:200,height:400}];await persist();render();
  });
  await page.click('#go-preview');await page.locator('.public-photos img').first().waitFor();
  const dimensions=async()=>page.locator('.public-photos img').evaluateAll(imgs=>imgs.map(img=>({width:Math.round(img.getBoundingClientRect().width),height:Math.round(img.getBoundingClientRect().height),fit:getComputedStyle(img).objectFit})));
  assert.deepEqual(await dimensions(),[{width:355,height:200,fit:'contain'},{width:200,height:355,fit:'contain'}]);
  await page.emulateMedia({media:'print'});assert.deepEqual(await dimensions(),[{width:355,height:200,fit:'contain'},{width:200,height:355,fit:'contain'}]);await page.emulateMedia({media:'screen'});
  await page.setViewportSize({width:390,height:900});
  const mobile=await dimensions();assert(mobile.every(p=>p.width<=355&&p.fit==='contain'));assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true);
  await page.setViewportSize({width:1440,height:1100});
  await page.click('#finalize');await page.check('#confirm');await page.click('#confirm-publish');await page.locator('#download').waitFor();
  const downloadPromise=page.waitForEvent('download');await page.click('#download');const download=await downloadPromise;
  const out=process.env.QA_RESULTS_DIR||path.join(__dirname,'results');await fs.mkdir(out,{recursive:true});await download.saveAs(path.join(out,'informe-teste.html'));
  const exported=await fs.readFile(path.join(out,'informe-teste.html'),'utf8');assert(exported.includes('standard-photo portrait'));assert(exported.includes('font-size: 24pt'));assert(!/src="\//.test(exported));
  const exportPage=await context.newPage();await exportPage.goto('file:///'+path.join(out,'informe-teste.html').replaceAll('\\','/'));
  const exportedSizes=await exportPage.locator('.public-photos img').evaluateAll(imgs=>imgs.map(img=>({w:Math.round(img.width),h:Math.round(img.height),fit:getComputedStyle(img).objectFit})));
  assert.deepEqual(exportedSizes,[{w:355,h:200,fit:'contain'},{w:200,h:355,fit:'contain'}]);
  await page.goto(base+'/#editor/e1');await page.locator('.tox-tinymce').waitFor();await page.screenshot({path:path.join(out,'editor-desktop.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({passed:true,checks:['custom block creation','formatted content survives reload','table colspan preserved','unsafe markup removed','landscape 355x200','portrait 200x355','print dimensions','mobile reflow','standalone export dimensions'],formatting},null,2));
 } finally {await context.close();await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
