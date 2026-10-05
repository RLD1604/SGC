const {chromium}=require('C:/Users/roddr/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),crypto=require('node:crypto'),assert=require('node:assert/strict'),path=require('node:path');
const base='http://127.0.0.1:19101/SGC',root=path.resolve(__dirname,'..');
const password=fs.readFileSync(path.join(root,'.secrets/qa_owner_password'),'utf8').trim();
const key=fs.readFileSync(path.join(root,'.secrets/qa_owner_totp'),'utf8').trim();
function code(){let bits=0,value=0,bytes=[];for(const c of key){value=(value<<5)|'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'.indexOf(c);bits+=5;if(bits>=8){bits-=8;bytes.push((value>>bits)&255);}}const counter=Buffer.alloc(8);counter.writeBigUInt64BE(BigInt(Math.floor(Date.now()/30000)));const digest=crypto.createHmac('sha1',Buffer.from(bytes)).update(counter).digest(),offset=digest[19]&15;return String((digest.readUInt32BE(offset)&0x7fffffff)%1000000).padStart(6,'0');}
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1365,height:900}}),page=await context.newPage();
  const errors=[];page.on('pageerror',error=>errors.push(error.name));
  await page.goto(base+'/owner.html');
  await page.locator('#login-form').waitFor();
  await page.fill('#login-form [name=login]','rodrigo');await page.fill('#login-form [name=password]',password);await page.click('#login-form button');
  await page.locator('#owner-unlock').waitFor();
  await page.fill('#owner-unlock [name=password]',password);await page.click('#owner-setup');await page.locator('#setup-area:not([hidden])').waitFor();
  assert.equal(await page.locator('#setup-key').textContent(),key);
  await page.fill('#owner-unlock [name=code]',code());await page.click('#owner-unlock [type=submit]');
  await page.locator('#event-filters').waitFor();await page.locator('#events tr').first().waitFor();
  assert.equal(await page.locator('#setup-key').count(),0);
  assert.equal(await page.locator('[type=password]').count(),0);
  await page.screenshot({path:path.join(root,'qa/results/owner-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:path.join(root,'qa/results/owner-mobile.png'),fullPage:true});
  await page.click('#owner-lock');await page.locator('#owner-unlock').waitFor();
  assert.equal(await page.locator('#event-filters').count(),0);
  const tenant=await browser.newContext(),tenantPage=await tenant.newPage();
  await tenantPage.goto(base+'/owner.html');await tenantPage.fill('#login-form [name=login]','qa.operator');await tenantPage.fill('#login-form [name=password]',password);await tenantPage.click('#login-form button');
  await tenantPage.getByRole('heading',{name:'Acesso restrito'}).waitFor();
  assert.deepEqual(errors,[]);
  console.log('PASS: owner login, enrollment, MFA, metadata dashboard, responsive layout, panel lock and operator denial; no page errors');
 }finally{await browser.close();}
})().catch(error=>{console.error(error.name+': '+error.message.replaceAll(password,'[redacted]').replaceAll(key,'[redacted]'));process.exitCode=1;});
