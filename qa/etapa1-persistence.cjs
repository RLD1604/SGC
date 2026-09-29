// Etapa 1 regression checks. Run only against the disposable QA instance.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

const base=process.env.QA_URL;
assert(base&&new URL(base).port==='19001','QA_URL must point to the isolated port 19001.');
const out=process.env.QA_RESULTS_DIR||path.join(__dirname,'results','intensive');
fs.mkdirSync(out,{recursive:true});

(async()=>{
  const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  const page=await context.newPage();
  page.setDefaultTimeout(10000);
  const checks=[];
  const check=async(name,fn)=>{try{await fn();checks.push({name,passed:true});}catch(error){checks.push({name,passed:false,error:error.message});}console.log((checks.at(-1).passed?'PASS ':'FAIL ')+name);};
  const open=async(route='inicio')=>{await page.goto(base+'/#'+route);await page.waitForFunction(()=>typeof state!=='undefined'&&state?.editions);};
  const readyRecord=()=>page.waitForFunction(()=>window.tinymce?.get('record-text')?.initialized);
  const record=(title)=>({id:crypto.randomUUID(),title,text:'Registro de QA',photos:[],status:'draft',revision:1,history:[]});

  try{
    await check('P1-02: requestSubmit, Enter e Ctrl+S concorrentes criam somente um registro',async()=>{
      const title='P1-02 concorrente '+Date.now();
      await open('novo');await readyRecord();
      await page.fill('[name=title]',title);
      const puts=[];
      await page.route('**/api/state',async route=>{
        if(route.request().method()==='PUT')puts.push({key:route.request().headers()['idempotency-key'],body:route.request().postDataJSON()});
        await route.continue();
      });
      await page.evaluate(()=>{
        const form=document.querySelector('#record-form');
        const draft=form.querySelector('button[value="draft"]');
        form.requestSubmit(draft);
        form.dispatchEvent(new SubmitEvent('submit',{bubbles:true,cancelable:true,submitter:draft}));
        document.dispatchEvent(new KeyboardEvent('keydown',{bubbles:true,cancelable:true,ctrlKey:true,key:'s'}));
      });
      await page.waitForURL(/#registro\//);await page.evaluate(()=>saving);await page.unroute('**/api/state');
      const response=await (await page.request.get(base+'/api/state')).json();
      assert.equal(response.state.records.filter(row=>row.title===title).length,1);
      assert.equal(puts.length,1,'A operação deve gerar um único PUT');
      assert.match(puts[0].key||'',/^[\w-]{1,100}$/,'PUT sem Idempotency-Key válida');
    });

    await check('P1-02: duas criações deliberadas com o mesmo conteúdo continuam distintas',async()=>{
      const title='P1-02 criação deliberada '+Date.now();
      for(let i=0;i<2;i++){
        await open('novo');await readyRecord();await page.fill('[name=title]',title);
        await page.click('button[value="draft"]');await page.waitForURL(/#registro\//);await page.evaluate(()=>saving);
      }
      const response=await (await page.request.get(base+'/api/state')).json();
      const rows=response.state.records.filter(row=>row.title===title);
      assert.equal(rows.length,2);
      assert.notEqual(rows[0].id,rows[1].id);
    });

    await check('P1-02: conflito 409 preserva recuperação sem oferecer Retry',async()=>{
      const other=await context.newPage();
      try{
        await other.goto(base+'/#inicio');await other.waitForFunction(()=>typeof state!=='undefined'&&state?.editions);
        const first='P1-02 vencedor '+Date.now(),second='P1-02 conflito '+Date.now();
        await page.evaluate(async title=>{state.records.push({id:crypto.randomUUID(),title,text:'A',photos:[],status:'draft',revision:1,history:[]});await persist();},first);
        await other.evaluate(async title=>{state.records.push({id:crypto.randomUUID(),title,text:'B',photos:[],status:'draft',revision:1,history:[]});await save();},second);
        await other.locator('#storage-recovery').waitFor();
        assert.equal(await other.locator('#retry-draft').count(),0,'409 não pode oferecer retry com revisão obsoleta');
        assert.equal(await other.locator('#download-draft').count(),1);
        assert.equal(await other.locator('#reload-state').count(),1);
      }finally{await other.close();}
    });

    await check('P1-04: informe inexistente não abre editor, prévia nem publicação substitutos',async()=>{
      for(const route of ['editor/inexistente-etapa1','previa/inexistente-etapa1','publicado/inexistente-etapa1']){
        await open(route);await page.waitForURL(/#informes$/);
        assert.equal(await page.locator('#title-edition,#save-editor,#publication').count(),0,route);
      }
    });
  }finally{
    fs.writeFileSync(path.join(out,'etapa1-persistence.json'),JSON.stringify({at:new Date().toISOString(),checks},null,2));
    await browser.close();
  }
  console.log(JSON.stringify({passed:checks.filter(check=>check.passed).length,total:checks.length}));
  process.exitCode=checks.every(check=>check.passed)?0:1;
})().catch(error=>{console.error(error);process.exitCode=1;});
