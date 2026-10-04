// Transparently authenticates legacy browser suites against disposable SGC instances.
// The wrapper is enabled only by executar-final.ps1 and refuses non-QA port 19001.
const assert=require('node:assert/strict');
const real=require(process.env.REAL_PLAYWRIGHT_MODULE);
const base=process.env.QA_URL;
const login=process.env.QA_BROWSER_LOGIN;
const password=process.env.QA_BROWSER_PASSWORD;
assert(base&&new URL(base).port==='19001','Autenticação automática restrita à porta descartável 19001.');
assert(login&&password,'Credenciais sintéticas de QA ausentes.');

const authenticated=new WeakSet();
async function authenticate(page){
  const context=page.context();
  if(authenticated.has(context))return page;
  await page.goto(base);
  await page.locator('#login-form').waitFor();
  await page.fill('#login-form [name=login]',login);
  await page.fill('#login-form [name=password]',password);
  const responsePromise=page.waitForResponse(r=>r.url().endsWith('/api/auth/login')&&r.request().method()==='POST');
  await page.click('#login-form button[type=submit]');
  const response=await responsePromise;
  assert.equal(response.status(),200,'Login sintético falhou');
  await page.waitForFunction(()=>typeof authSession!=='undefined'&&authSession&&typeof state!=='undefined'&&state);
  authenticated.add(context);
  return page;
}

function wrapContext(context){
  return new Proxy(context,{get(target,property){
    if(property==='newPage')return async()=>authenticate(await target.newPage());
    const value=Reflect.get(target,property,target);
    return typeof value==='function'?value.bind(target):value;
  }});
}

const chromium=new Proxy(real.chromium,{get(target,property){
  if(property!=='launch'){
    const value=Reflect.get(target,property,target);
    return typeof value==='function'?value.bind(target):value;
  }
  return async(...args)=>{
    const browser=await target.launch(...args);
    return new Proxy(browser,{get(browserTarget,browserProperty){
      if(browserProperty==='newPage')return async options=>authenticate(await browserTarget.newPage(options));
      if(browserProperty==='newContext')return async options=>wrapContext(await browserTarget.newContext(options));
      const value=Reflect.get(browserTarget,browserProperty,browserTarget);
      return typeof value==='function'?value.bind(browserTarget):value;
    }});
  };
}});

module.exports={...real,chromium};
