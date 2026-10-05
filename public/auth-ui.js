'use strict';
let authSession=null,csrfToken='';
function currentRoleGrants(){const condo=authSession?.memberships?.[0];return (authSession?.grants||[]).filter(item=>item.condominium_id===condo);}
function hasRole(...roles){return currentRoleGrants().some(item=>roles.includes(item.role));}
function canReviewRecords(){return hasRole('administrador','gestor','sindico');}
function canApproveEditions(){return hasRole('administrador','gestor','sindico');}

async function authRequest(path,options={}){
 const headers={...(options.headers||{})};
 if(options.body&&!headers['Content-Type'])headers['Content-Type']='application/json';
 if(options.method&&options.method!=='GET'&&csrfToken)headers['X-CSRF-Token']=csrfToken;
 let response;
 try{response=await fetch(path,{...options,headers,credentials:'same-origin',cache:'no-store'});}
 catch(cause){const code='LOCAL-'+crypto.randomUUID();window.SgcDiagnostics?.report('network_error',code);const error=new Error('Não foi possível confirmar a operação. Código de atendimento: '+code);error.requestId=code;throw error;}
 const result=await response.json().catch(()=>({error:'O servidor não respondeu.'}));
 if(!response.ok){const code=response.headers.get('X-Request-ID');const error=new Error((result.error||'Não foi possível concluir.')+(code?' Código de atendimento: '+code:''));error.status=response.status;error.requestId=code;throw error;}
 return result;
}

function renderLogin(message=''){
 document.body.classList.add('auth-required');
 const main=document.querySelector('#main');
 main.innerHTML=`<section class="panel auth-panel"><h1>Entrar no espaço de trabalho</h1><p>Use sua conta individual do condomínio.</p>${message?`<p class="error">${esc(message)}</p>`:''}<form id="login-form"><label>Identificador<input name="login" autocomplete="username" required></label><label>Senha<input name="password" type="password" autocomplete="current-password" required></label><button class="primary" type="submit">Entrar</button></form><details><summary>Ativar convite ou recuperar acesso</summary><form id="activate-form"><label>Token de ativação<input name="token" autocomplete="off" required></label><label>Nova senha: mínimo de 8 caracteres, com número, maiúscula e caractere especial<input name="password" type="password" minlength="8" autocomplete="new-password" required></label><button type="submit">Ativar conta</button></form><form id="recovery-form"><label>Identificador<input name="login" required></label><button type="submit">Solicitar recuperação</button></form><form id="complete-recovery-form"><label>Token de recuperação<input name="token" required></label><label>Nova senha: mínimo de 8 caracteres, com número, maiúscula e caractere especial<input name="password" type="password" minlength="8" autocomplete="new-password" required></label><button type="submit">Concluir recuperação</button></form></details></section>`;
 main.querySelector('#login-form').onsubmit=async event=>{event.preventDefault();const data=Object.fromEntries(new FormData(event.target));try{const result=await authRequest('/api/auth/login',{method:'POST',body:JSON.stringify(data)});authSession=result.principal;csrfToken=result.csrf_token;location.reload();}catch(error){renderLogin(error.message)}};
 main.querySelector('#activate-form').onsubmit=async event=>{event.preventDefault();try{await authRequest('/api/auth/activate',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(event.target)))});renderLogin('Conta ativada. Entre com sua nova senha.')}catch(error){renderLogin(error.message)}};
 main.querySelector('#recovery-form').onsubmit=async event=>{event.preventDefault();await authRequest('/api/auth/recovery/request',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(event.target)))}).catch(()=>{});renderLogin('Se a conta puder ser recuperada, o responsável entregará as instruções.');};
 main.querySelector('#complete-recovery-form').onsubmit=async event=>{event.preventDefault();try{await authRequest('/api/auth/recovery/complete',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(event.target)))});renderLogin('Senha alterada. Entre novamente.')}catch(error){renderLogin(error.message)}};
}

async function ensureAuth(){
 try{const result=await authRequest('/api/auth/session');authSession=result.principal;csrfToken=result.csrf_token;document.body.classList.remove('auth-required');applyIdentity();return true;}
 catch(error){renderLogin(error.message);return false;}
}

function applyIdentity(){
 const roles=new Set(currentRoleGrants().map(item=>item.role));
 role=(roles.has('administrador')||roles.has('operador')||roles.has('gestor')||roles.has('sindico')||roles.has('editor'))?'editor':'funcionario';
 document.querySelector('.view-switch')?.remove();
 const profile=roles.has('administrador')?'Administrador':roles.has('operador')?'Operador':'Conta individual';
 const reviewLink=document.querySelector('[data-nav="revisao"]');if(reviewLink)reviewLink.hidden=!canReviewRecords();
 const identity=document.querySelector('.sidebar-bottom div');if(identity)identity.innerHTML=`${esc(authSession.display_name)}<small>${profile}</small>`;
 const avatar=document.querySelector('.avatar');if(avatar)avatar.textContent=authSession.display_name.split(/\s+/).slice(0,2).map(x=>x[0]).join('').toUpperCase();
 if(!document.querySelector('#logout')){const button=document.createElement('button');button.id='logout';button.textContent='Sair';button.onclick=logout;document.querySelector('.sidebar-bottom')?.append(button);}
}

async function logout(){
 if(activeDraft?.dirty&&!confirm('Há alterações não salvas. O rascunho continuará isolado nesta conta. Sair?'))return;
 try{await authRequest('/api/auth/logout',{method:'POST',body:'{}'});authSession=null;csrfToken='';state=null;location.reload();}catch(error){notify('A saída não foi confirmada: '+error.message);}
}
