const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const assert=require('node:assert/strict');
(async()=>{
  const base=process.env.QA_URL;
  assert(base&&new URL(base).port==='19001','Use only the isolated QA server.');
  const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
  try {
    const a=await browser.newPage(),b=await browser.newPage();
    await a.goto(base);await b.goto(base);
    await Promise.all([a,b].map(p=>p.waitForFunction(()=>typeof state!=='undefined'&&state?.editions)));
    await a.evaluate(async()=>{state.records.push({id:crypto.randomUUID(),title:'Registro compartilhado QA',text:'Teste',photos:[],status:'draft',revision:1});await persist();});
    await b.reload();await b.waitForFunction(()=>typeof state!=='undefined'&&state?.records.some(r=>r.title==='Registro compartilhado QA'));
    await a.evaluate(async()=>{state.records[0].text='Mudança de A';await persist();});
    await b.evaluate(async()=>{state.records[0].text='Mudança de B';await save();});
    await b.locator('#storage-recovery').waitFor();
    assert.match(await b.locator('#storage-recovery').innerText(),/Outra sessão/);
    await a.reload();await a.waitForFunction(()=>typeof state!=='undefined'&&state?.records.some(r=>r.text==='Mudança de A'));
    await b.reload();await b.waitForFunction(()=>typeof db!=='undefined'&&db);
    const count=await b.evaluate(()=>state.records.length);
    await b.evaluate(async()=>{await new Promise((resolve,reject)=>{const t=db.transaction('app','readwrite');t.objectStore('app').put(seed(),'state');t.oncomplete=resolve;t.onerror=reject;});});
    await b.reload();await b.getByRole('button',{name:/Importar deste navegador/}).click();
    await b.waitForFunction(n=>state.records.length===n+4,count);
    await b.reload();await b.waitForFunction(()=>typeof state!=='undefined'&&state?.records);
    assert.equal(await b.getByRole('button',{name:/Importar deste navegador/}).count(),0);
    assert.equal(await b.evaluate(()=>state.records.length),count+4);
    const legacy=await b.evaluate(()=>load());assert.equal(legacy.records.length,4);
    console.log('PASS: independent sessions share records; stale write blocked; browser import retains local originals and does not repeat.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
