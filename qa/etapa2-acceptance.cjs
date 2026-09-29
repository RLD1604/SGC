// Etapa 2 acceptance: document validation, atomic imports and legacy migration.
// It writes only to the disposable service exposed as QA_URL:19001.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const assert=require('node:assert/strict');

const base=process.env.QA_URL;
assert(base&&new URL(base).port==='19001','Use somente a porta isolada 19001.');

(async()=>{
 const browser=await chromium.launch({executablePath:'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',headless:true});
 const page=await browser.newPage({viewport:{width:1280,height:900}});
 page.setDefaultTimeout(15000);
 const checks=[];
 const check=async(name,fn)=>{try{await fn();checks.push({name,passed:true});console.log('PASS '+name);}catch(error){checks.push({name,passed:false,error:error.message});console.log('FAIL '+name);}};
 const get=async()=>await (await page.request.get(base+'/api/state')).json();
 const put=async state=>{const current=await get();return page.request.put(base+'/api/state',{data:{revision:current.revision,state}});};
 const clone=value=>structuredClone(value);
 const assertUnchanged=async before=>assert.deepEqual(await get(),before,'A operação inválida alterou o acervo.');
 let template;
 const baseState=()=>clone(template);
 const reset=async()=>{const response=await put(baseState());assert.equal(response.status(),200);};
 const rejectedPut=async(mutator,message)=>{
   const before=await get(),candidate=clone(before.state);mutator(candidate);
   const response=await page.request.put(base+'/api/state',{data:{revision:before.revision,state:candidate}});
   assert.equal(response.status(),400,message);await assertUnchanged(before);
 };
 const rejectedImport=async(mutator,message)=>{
   const before=await get(),candidate=baseState();mutator(candidate);
   const response=await page.request.post(base+'/api/import',{data:{importId:'etapa2-reject-'+crypto.randomUUID(),state:candidate}});
   assert.equal(response.status(),400,message);await assertUnchanged(before);
 };
 try{
  await page.goto(base);await page.waitForFunction(()=>state?.editions&&typeof seed==='function');
  template=await page.evaluate(()=>seed());
  await reset();

  await check('Tipos obrigatórios e opcionais inválidos são rejeitados atomicamente',async()=>{
   for(const [label,mutate] of [
    ['id ausente',s=>delete s.records[0].id],
    ['id duplicado',s=>s.records.push(clone(s.records[0]))],
    ['título numérico',s=>s.records[0].title=3],
    ['texto opcional nulo',s=>s.records[0].who=null],
    ['fotos opcionais não-lista',s=>s.records[0].photos={}],
    ['capa não textual',s=>s.editions[0].cover=[]],
    ['revisão não numérica',s=>s.records[0].revision={}],
    ['histórico não-lista',s=>s.records[0].history={}]
   ]) await rejectedPut(mutate,label);
  });

  await check('Datas reais, enums e limites de título são validados',async()=>{
   for(const [label,mutate] of [
    ['data impossível',s=>s.records[0].date='2026-02-30'],
    ['data sem formato ISO',s=>s.records[0].date='30/02/2026'],
    ['categoria fora do catálogo',s=>s.records[0].category='Qualquer coisa'],
    ['andamento fora do catálogo',s=>s.records[0].progress='Talvez'],
    ['título com 161 caracteres',s=>s.records[0].title='x'.repeat(161)],
    ['bloco com tipo não textual',s=>s.editions[0].blocks[0].type=[]],
    ['bloco com título não textual',s=>s.editions[0].blocks[0].title=[]]
   ]) await rejectedPut(mutate,label);
   const valid=baseState();valid.records[0].title='x'.repeat(160);
   assert.equal((await put(valid)).status(),200,'O limite válido de 160 caracteres foi rejeitado.');
  });

  await check('Referências de bloco e revisões de fonte são consistentes',async()=>{
   await reset();
   await rejectedPut(s=>s.editions[0].blocks[0].sources=[{id:'registro-ausente',revision:1,title:'Ausente'}],'Fonte inexistente');
   await rejectedPut(s=>s.editions[0].blocks[0].sources=[{id:'r1',revision:'1',title:'Fonte'}],'Revisão de fonte textual');
   await rejectedPut(s=>s.editions[0].blocks[0].sources=[{id:'r1',revision:999,title:'Fonte'}],'Revisão de fonte divergente');
  });

  await check('Texto rico vazio e espaços não permitem estados editoriais completos',async()=>{
   await reset();
   await rejectedPut(s=>{s.records[0].status='review';s.records[0].title='Registro';s.records[0].text='   ';s.records[0].textHtml='<p>&nbsp; <br></p>';},'Revisão com texto rico vazio');
   await rejectedPut(s=>{s.records[0].status='ready';s.records[0].title='Registro';s.records[0].text='\n\t';s.records[0].textHtml='<div> </div>';},'Conferência com texto rico vazio');
   await rejectedPut(s=>{s.editions[0].title='   ';s.editions[0].period='\t';},'Informe identificado somente por espaços');
   await rejectedPut(s=>{s.editions[0].blocks[0].type='  ';s.editions[0].blocks[0].title='\n';},'Bloco identificado somente por espaços');
  });

  await check('Importação inválida é atômica e usa as mesmas regras do salvamento',async()=>{
   await reset();
   await rejectedImport(s=>{s.records.push({id:'deveria-nao-entrar',title:'Válido',status:'draft',text:'Texto',photos:[],revision:1,history:[]});s.records[0].date='2026-99-99';},'Importação com data inválida');
   await rejectedImport(s=>s.editions[0].period=[],'Importação com período inválido');
  });

  await check('Importação válida é repetível sem duplicar e preserva referências',async()=>{
   await reset();
   const imported={records:[{id:'legacy-source',title:'Registro importado Etapa 2',status:'draft',text:'Texto legado válido',photos:[],revision:2,history:[{at:'2026-09-23T12:00:00.000Z',text:'Criado'}]}],editions:[{id:'legacy-edition',title:'Informe importado Etapa 2',period:'Outubro de 2026',status:'draft',version:1,cover:'/images/jardim.jpg',blocks:[{id:'legacy-block',type:'Matéria',title:'Bloco importado',body:'<p>Conteúdo válido</p>',photos:[],sources:[{id:'legacy-source',revision:2,title:'Registro importado Etapa 2'}]}]}],publications:[]};
   const importId='etapa2-repeat-'+crypto.randomUUID();
   const first=await page.request.post(base+'/api/import',{data:{importId,state:clone(imported)}});
   assert.equal(first.status(),200);const second=await page.request.post(base+'/api/import',{data:{importId,state:clone(imported)}});
   assert.equal(second.status(),200);assert.equal((await second.json()).alreadyImported,true);
   const current=await get();
   assert.equal(current.state.records.filter(r=>r.title==='Registro importado Etapa 2').length,1);
   const record=current.state.records.find(r=>r.title==='Registro importado Etapa 2');
   const edition=current.state.editions.find(e=>e.title==='Informe importado Etapa 2');
   assert.equal(edition.blocks[0].sources[0].id,record.id);
   assert.equal(edition.blocks[0].sources[0].revision,2);
  });

  await check('Histórico válido permanece editável e formato legado reconhecido é migrado',async()=>{
   await reset();
   const legacy={records:[
    {id:'old-history',title:'Histórico válido editável Etapa 2',status:'draft',text:'Texto antigo',photos:[],revision:1,history:[{at:'2026-09-23T12:00:00.000Z',text:'Importado'}]},
    // A recognized older record omitted history; migration must normalize it,
    // rather than crashing the editor or accepting an ambiguous object.
    {id:'old-no-history',title:'Sem histórico legado Etapa 2',status:'draft',text:'Texto antigo',photos:[],revision:1}
   ],editions:[{id:'old-edition',title:'Informe legado Etapa 2',period:'Setembro de 2026',status:'draft',version:1,cover:'/images/jardim.jpg',blocks:[]}],publications:[]};
   const response=await page.request.post(base+'/api/import',{data:{importId:'etapa2-legacy-'+crypto.randomUUID(),state:legacy}});
   assert.equal(response.status(),200);
   const current=await get(),record=current.state.records.find(r=>r.title==='Histórico válido editável Etapa 2'),noHistory=current.state.records.find(r=>r.title==='Sem histórico legado Etapa 2');
   assert(Array.isArray(record.history)&&record.history.length===1);
   assert.deepEqual(noHistory.history,[],'Migração não normalizou o histórico legado ausente.');
   await page.reload();await page.waitForFunction(()=>state?.editions);
   await page.goto(base+'/#novo/'+record.id);await page.waitForFunction(()=>tinymce.get('record-text')?.initialized);
   await page.fill('[name=title]','Histórico editado Etapa 2');await page.click('button[value=draft]');
   try{await page.waitForURL(new RegExp('#registro/'+record.id+'$'));}catch(error){console.error('Diagnóstico edição histórica',await page.evaluate(()=>({url:location.href,toast:document.querySelector('#toast')?.textContent,recovery:document.querySelector('#storage-recovery')?.querySelector('p')?.textContent,submitting:document.querySelector('#record-form')?.dataset.submitting,status:document.querySelector('#draft-status')?.textContent})));throw error;}
   const after=await get();assert(after.state.records.some(r=>r.id===record.id&&r.title==='Histórico editado Etapa 2'));
  });
 }finally{await browser.close();}
 console.log(JSON.stringify({passed:checks.filter(c=>c.passed).length,total:checks.length,checks}));
 process.exitCode=checks.every(c=>c.passed)?0:1;
})().catch(error=>{console.error(error);process.exitCode=1;});
