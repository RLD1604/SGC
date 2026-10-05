const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const listeners={},calls=[],ctx={Date,Set,JSON,location:{hash:'#editor/PRIVATE'},authSession:{user_id:'u'},csrfToken:'test',document:{addEventListener(){}},window:{fetch:async(...args)=>{calls.push(args);return {}},addEventListener:(event,fn)=>listeners[event]=fn}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../public/diagnostics.js'),'utf8'),ctx);
(async()=>{
 listeners.error({message:'SECRET',filename:'PRIVATE',error:new Error('SECRET')});
 await Promise.resolve();
 assert.equal(JSON.parse(calls[0][1].body).page,'editor');
 assert.equal(JSON.parse(calls[0][1].body).kind,'script_error');
 assert.ok(!calls[0][1].body.includes('SECRET'));
 assert.ok(!calls[0][1].body.includes('PRIVATE'));
 for(let i=0;i<40;i++)await ctx.window.SgcDiagnostics.report('script_error');
 assert.equal(calls.length,20);
 ctx.authSession=null;
 await ctx.window.SgcDiagnostics.report('script_error');
 assert.equal(calls.length,20);
 console.log('PASS: browser privacy, volume limit and anonymous silence');
})().catch(error=>{console.error(error);process.exitCode=1});
