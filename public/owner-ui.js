'use strict';
let role='editor',activeDraft=null,state=null,ownerTimer=null;
function esc(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
const main=document.querySelector('#main'),message=document.querySelector('#owner-message');
function note(text){message.textContent=text;}
async function ownerStart(){
 if(!await ensureAuth())return;
 try{const status=await authRequest('/api/owner/status');await ownerDashboard().catch(error=>{if(error.status===403)unlockForm(status.enrolled);else{main.innerHTML='<section><h1>Painel temporariamente indisponível</h1><p>Tente novamente em alguns instantes.</p></section>';note(error.message);}});}
 catch(error){main.innerHTML='<section><h1>Acesso restrito</h1><p>Esta área é exclusiva do dono da plataforma.</p></section>';note(error.message);}
}
function unlockForm(enrolled){
 clearTimeout(ownerTimer);
 main.innerHTML=`<section><h1>Confirmar acesso do dono</h1><p>O acesso é liberado por 15 minutos após confirmar sua senha e o código do autenticador.</p><form id="owner-unlock"><label>Sua senha<input name="password" type="password" autocomplete="current-password" required maxlength="1024"></label><label>Código de seis dígitos<input name="code" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" ${enrolled?'required':''}></label><button class="primary" type="submit">Confirmar acesso</button>${!enrolled?'<button type="button" id="owner-setup">Configurar autenticador</button><div id="setup-area" hidden><p>No Google Authenticator: + → Ler código QR. No Microsoft Authenticator: Adicionar conta → Outra conta → Escanear código QR.</p><img id="setup-qr" alt="QR Code para configurar seu autenticador"><details><summary>Não consigo escanear</summary><p>Cadastre a chave abaixo manualmente, usando código baseado em tempo.</p><p id="setup-key"></p></details><p>Nome da conta: SGC · rodrigo. Não compartilhe nem fotografe o QR Code ou a chave. Depois informe o código de seis dígitos acima.</p></div>':''}</form></section>`;
 const form=document.querySelector('#owner-unlock');
 document.querySelector('#owner-setup')?.addEventListener('click',async()=>{
  try{const result=await authRequest('/api/owner/enroll',{method:'POST',body:JSON.stringify({password:form.elements.password.value})});document.querySelector('#setup-key').textContent=result.setupKey;document.querySelector('#setup-qr').src=result.setupQr;document.querySelector('#setup-area').hidden=false;note('Configure o autenticador e confirme o código.');}
  catch(error){note(error.message);}
 });
 form.onsubmit=async event=>{event.preventDefault();const button=form.querySelector('[type="submit"]');button.disabled=true;
  try{await authRequest('/api/owner/verify',{method:'POST',body:JSON.stringify({password:form.elements.password.value,code:form.elements.code.value})});form.reset();document.querySelector('#setup-key')?.replaceChildren();document.querySelector('#setup-qr')?.removeAttribute('src');await ownerDashboard();note('Acesso confirmado.');}
  catch(error){note(error.message);}finally{if(button.isConnected)button.disabled=false;}
 };
}
async function ownerDashboard(){
 const overview=await authRequest('/api/owner/overview');
 clearTimeout(ownerTimer);ownerTimer=setTimeout(()=>{unlockForm(true);note('O período de acesso terminou. Confirme novamente.');},Math.max(0,new Date(overview.accessExpiresAt).getTime()-Date.now()));
 const backup=overview.backup||{};
 const backupLabel=({success:'Verificado',pending:'Envio em andamento',stale:'Atrasado: verifique o backup',schedule_error:'Agendamento requer atenção',unavailable:'Sem confirmação disponível'})[backup.status]||'Sem confirmação disponível';
 main.innerHTML=`<section><h1>Operação da plataforma</h1><p class="help">Este painel mostra metadados operacionais. Não abre documentos ou fotos dos clientes. Relatos do navegador não são comprovação de sucesso.</p><div class="stats"><p>App: ${esc(overview.status)}<br>Banco: ${esc(overview.database)}</p><p>Últimas 24 horas<br>Sucessos: ${esc(overview.last24Hours.success||0)} · Erros: ${esc(overview.last24Hours.error||0)} · Bloqueios: ${esc(overview.last24Hours.denied||0)}</p><p>Backup: ${esc(backupLabel)}<br>${esc(backup.runId||'')}</p></div><button id="owner-lock">Bloquear painel</button></section><section><h2>Ações e erros</h2><form class="filters" id="event-filters"><label>Condomínio<select name="condominiumId"><option value="">Todos</option>${overview.condominiums.map(c=>`<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('')}</select></label><label>Usuário<select name="userId"><option value="">Todos</option>${overview.users.map(u=>`<option value="${esc(u.id)}">${esc(u.name)}</option>`).join('')}</select></label><label>Resultado<select name="result"><option value="">Todos</option><option value="success">Sucesso confirmado</option><option value="error">Erro</option><option value="denied">Bloqueio</option><option value="reported">Relato do navegador</option></select></label><label>Ação<input name="action" maxlength="160" placeholder="Ex.: owner_verify"></label><label>Código de atendimento<input name="requestId" maxlength="42"></label><button type="submit">Consultar</button></form><div class="table-scroll"><table><thead><tr><th>Horário</th><th>Condomínio / usuário</th><th>Ação</th><th>Resultado</th><th>Código</th></tr></thead><tbody id="events"></tbody></table></div><button id="more-events" hidden>Mais antigos</button></section>`;
 const dateFields=document.createElement('div');dateFields.innerHTML='<label>Desde<input name="from" type="datetime-local"></label><label>Até<input name="until" type="datetime-local"></label>';document.querySelector('#event-filters').append(dateFields);
 let next=null,nextId=null,filters='';
 const userNames=new Map(overview.users.map(u=>[u.id,u.name]));const condoNames=new Map(overview.condominiums.map(c=>[c.id,c.name]));
 const labels={success:'Sucesso confirmado',error:'Erro',denied:'Bloqueio',reported:'Relato'};
 async function load(more=false){
  try{const query=filters+(more&&next?'&before='+encodeURIComponent(next)+'&beforeId='+encodeURIComponent(nextId):'');const result=await authRequest('/api/owner/events?'+query);const rows=result.events.map(e=>`<tr><td>${esc(new Date(e.at).toLocaleString())}</td><td>${esc(condoNames.get(e.condominiumId)||e.condominiumId||'—')}<br><code>${esc(userNames.get(e.userId)||e.userId||'Não identificado')}</code></td><td>${esc(e.action)}<br>${esc(e.source)}${e.httpStatus?' · HTTP '+esc(e.httpStatus):''}</td><td>${esc(labels[e.result]||e.result)}</td><td><code>${esc(e.requestId)}</code>${e.metadata?.clientIncidentId?'<br><code>LOCAL-'+esc(e.metadata.clientIncidentId)+'</code>':''}</td></tr>`).join('');if(more)document.querySelector('#events').insertAdjacentHTML('beforeend',rows);else document.querySelector('#events').innerHTML=rows||'<tr><td colspan="5">Nenhum evento encontrado.</td></tr>';next=result.nextBefore;nextId=result.nextId;document.querySelector('#more-events').hidden=!next;}
  catch(error){note(error.message);if(error.status===403){await authRequest('/api/owner/lock',{method:'POST',body:'{}'}).catch(()=>{});unlockForm(true);}}
 }
 document.querySelector('#event-filters').onsubmit=event=>{event.preventDefault();const fields=[...new FormData(event.target)].filter(([,v])=>v).map(([k,v])=>[k,(k==='from'||k==='until')?new Date(v).toISOString():v]);filters=new URLSearchParams(fields).toString();load();};
 document.querySelector('#more-events').onclick=()=>load(true);
 document.querySelector('#owner-lock').onclick=async()=>{try{await authRequest('/api/owner/lock',{method:'POST',body:'{}'});unlockForm(true);note('Painel bloqueado.');}catch(error){note(error.message);}};
 await load();
}
document.querySelector('#owner-logout').onclick=logout;
ownerStart();
