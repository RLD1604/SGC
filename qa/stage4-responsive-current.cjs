const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const assert=require('node:assert/strict');
const base=process.env.QA_URL,login=process.env.QA_BROWSER_LOGIN,password=process.env.QA_BROWSER_PASSWORD;
assert(base&&new URL(base).port==='19001'&&login&&password);
let browser;
(async()=>{
 browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
 const page=await browser.newPage();page.setDefaultTimeout(12000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base);await page.fill('#login-form [name=login]',login);await page.fill('#login-form [name=password]',password);await page.click('#login-form button[type=submit]');await page.waitForFunction(()=>authSession&&state);
 const checks=[];
 for(const width of [320,390,768,1440]){
  await page.setViewportSize({width,height:900});
  for(const route of ['inicio','registros','novo','informes']){
   await page.goto(base+'/#'+route);await page.waitForFunction(()=>authSession&&state);await page.waitForTimeout(150);
   if(route==='novo')await page.waitForFunction(()=>tinymce.get('record-text')?.initialized);
   const layout=await page.evaluate(()=>({
    viewport:innerWidth,
    scroll:document.documentElement.scrollWidth,
    dialogs:[...document.querySelectorAll('[role=dialog]')].filter(x=>!x.hidden).length,
    offenders:[...document.querySelectorAll('body *')].map(element=>{
     const rect=element.getBoundingClientRect();
     return {tag:element.tagName.toLowerCase(),id:element.id,className:String(element.className||''),left:Math.round(rect.left),right:Math.round(rect.right),width:Math.round(rect.width)};
    }).filter(rect=>rect.right>innerWidth+2||rect.left< -2).slice(0,12)
   }));
   assert(layout.scroll<=layout.viewport+2,`${width}px ${route}: largura ${layout.scroll}; elementos ${JSON.stringify(layout.offenders)}`);checks.push(`${width}:${route}`);
  }
 }
 assert.equal(errors.length,0,errors.join('\n'));
 console.log(JSON.stringify({passed:true,checks:checks.length,widths:4,routes:4}));
})().catch(e=>{console.error(e);process.exitCode=1}).finally(async()=>{if(browser)await browser.close()});
