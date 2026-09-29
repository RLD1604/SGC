// Run against an isolated Docker instance only. Never point at port 9001.
const {spawnSync}=require('node:child_process');
const fs=require('node:fs');const path=require('node:path');
if(!process.env.QA_URL||new URL(process.env.QA_URL).port!=='19001')throw Error('QA_URL must use isolated port 19001.');
const scripts=['record-trash','editorial','beta-editor','photo-optimizer','photo-persistence','shared-storage','ai-review','compact-editor','photo-editor','intensive-fields','intensive-edge'];
const folder=path.join(__dirname,'results','intensive');fs.mkdirSync(folder,{recursive:true});
const results=[];
for(const name of scripts){
 console.log('RUN '+name);const start=Date.now();
 const r=spawnSync(process.execPath,[path.join(__dirname,name+'.cjs')],{env:process.env,encoding:'utf8',timeout:180000,maxBuffer:8*1024*1024});
 fs.writeFileSync(path.join(folder,name+'.log'),(r.stdout||'')+'\n'+(r.stderr||'')+(r.error?'\n'+r.error:''));
 results.push({name,passed:r.status===0,seconds:Math.round((Date.now()-start)/1000),exitCode:r.status});
 console.log((r.status===0?'PASS ':'FAIL ')+name);
}
fs.writeFileSync(path.join(folder,'suite.json'),JSON.stringify({at:new Date().toISOString(),results},null,2));
console.log(JSON.stringify(results));
process.exitCode=results.every(r=>r.passed)?0:1;
