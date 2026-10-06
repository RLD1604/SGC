const {chromium}=require('C:/Users/roddr/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const root=path.resolve(__dirname,'..'),out=path.join(root,'docs/manuais/telas');fs.mkdirSync(out,{recursive:true});
const base='http://127.0.0.1:19103/SGC/';
function totp(key){let b=0,v=0,a=[];for(const c of key){v=(v<<5)|'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'.indexOf(c);b+=5;if(b>=8){b-=8;a.push((v>>b)&255)}}const n=Buffer.alloc(8);n.writeBigUInt64BE(BigInt(Math.floor(Date.now()/30000)));const d=crypto.createHmac('sha1',Buffer.from(a)).update(n).digest(),i=d[19]&15;return String((d.readUInt32BE(i)&0x7fffffff)%1000000).padStart(6,'0')}
(async()=>{const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});try{
const page=await browser.newPage({viewport:{width:1280,height:960}});await page.goto(base);await page.locator('#login-form').waitFor();await page.screenshot({path:path.join(out,'01-acesso.png'),fullPage:true});
const people=JSON.parse(fs.readFileSync(path.join(root,'.secrets/qa_preentrega_finalcredentials.json'))),saved=JSON.parse(fs.readFileSync(path.join(root,'.secrets/qa_preentrega_finalsessions.json')));
const p=people.find(x=>x.login==='maverick');await page.fill('#login-form [name=login]',p.login);await page.fill('#login-form [name=password]',p.password);await page.click('#login-form button');await page.locator('#user-mfa-form').waitFor();await page.screenshot({path:path.join(out,'02-autenticador.png'),fullPage:true});await page.fill('#user-mfa-form [name=code]',totp(saved.maverick.key));await page.click('#user-mfa-form button');await page.locator('#logout').waitFor();
const ids=JSON.parse(fs.readFileSync(path.join(root,'qa/results/pre-entrega-20261006/final-jornada/ids.json')));
for(const [name,route] of [['03-visao-geral','inicio'],['04-novo-registro','novo'],['05-informes','informes'],['06-editor','editor/'+ids.edition]]){await page.goto(base+'#'+route);await page.locator('#main h1').first().waitFor();await page.waitForTimeout(700);await page.screenshot({path:path.join(out,name+'.png'),fullPage:false});console.log('Captured '+name)}
}finally{await browser.close()}})().catch(()=>{console.error('Falha na captura QA; nenhuma credencial exibida.');process.exitCode=1});
