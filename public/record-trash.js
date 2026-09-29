'use strict';
function activeRecords(){return state.records.filter(record=>!record.deletedAt);}
function trashLink(){return role==='editor'?`<a class="button" href="#lixeira">Lixeira (${state.records.filter(r=>r.deletedAt).length})</a>`:'';}
function sourceNotice(source){
 const record=state.records.find(r=>r.id===source.id);
 return record?.deletedAt?' · <strong>Registro na lixeira · cópia preservada</strong>':record?.revision!==source.revision?' · <strong>Fonte atualizada</strong>':'';
}
function confirmTrash(recordId){
 const record=state.records.find(r=>r.id===recordId);
 if(role!=='editor'||!record||record.deletedAt)return;
 const used=[...state.editions,...state.publications].filter(e=>e.blocks.some(b=>b.sources?.some(s=>s.id===recordId))).length;
 modal(`<h2>Mover registro para a lixeira?</h2><p><strong>${esc(record.title)}</strong></p><p>O registro sairá do acervo e da seleção de matérias. Você poderá restaurá-lo pela lixeira.</p>${used?`<p>Este registro é fonte de ${used} informe(s). Os textos e as fotos já incluídos serão preservados.</p>`:''}<div class="actions"><button type="button" id="cancel-trash">Cancelar</button><button type="button" class="danger" id="confirm-trash">Mover para a lixeira</button></div>`,()=>{
  $('#cancel-trash').onclick=()=>$('#dialog').close();
  $('#confirm-trash').onclick=async()=>{
   if(role!=='editor'||record.deletedAt){$('#dialog').close();return;}
   $('#confirm-trash').disabled=true;
   record.deletedAt=new Date().toISOString();
   record.history=[...(record.history||[]),{at:record.deletedAt,text:'Movido para a lixeira'}];
   $('#dialog').close();
   if(await save('Registro movido para a lixeira. Você pode restaurá-lo.'))location.hash='#registros';
  };
 });
}
async function restoreRecord(recordId){
 const record=state.records.find(r=>r.id===recordId);
 if(role!=='editor'||!record?.deletedAt)return;
 delete record.deletedAt;
 record.history=[...(record.history||[]),{at:new Date().toISOString(),text:'Restaurado da lixeira'}];
 if(await save('Registro restaurado ao acervo.'))location.hash='#registro/'+record.id;
}
function trashView(){
 if(role!=='editor'){$('#main').innerHTML=heading('Lixeira','Disponível na visão de Editor.','<a class="button" href="#registros">Voltar aos registros</a>');return;}
 $('#main').innerHTML=heading('Lixeira','Os registros ficam guardados até você restaurá-los. Não há exclusão automática.','<a class="button" href="#registros">Voltar aos registros</a>')+'<div class="filters"><input id="trash-search" type="search" aria-label="Buscar na lixeira" placeholder="Buscar por assunto ou local"></div><div id="trash-list"></div>';
 const update=()=>{
  const query=$('#trash-search').value.toLocaleLowerCase('pt-BR');
  const rows=state.records.filter(r=>r.deletedAt&&(r.title+' '+(r.local||'')).toLocaleLowerCase('pt-BR').includes(query)).sort((a,b)=>b.deletedAt.localeCompare(a.deletedAt));
  $('#trash-list').innerHTML=rows.map(r=>`<article class="panel"><h2><a href="#registro/${r.id}">${esc(r.title)}</a></h2><p>${esc(r.local||'Local não informado')} · Na lixeira desde ${esc(new Date(r.deletedAt).toLocaleString('pt-BR'))}</p><p>Situação anterior: ${esc(labels[r.status]||r.status)} · ${r.photos.length} foto(s)</p><div class="actions"><a class="button" href="#registro/${r.id}">Ver registro</a><button type="button" class="primary" data-restore-record="${r.id}">Restaurar registro</button></div></article>`).join('')||'<div class="empty">Nenhum registro na lixeira para esta busca.</div>';
  document.querySelectorAll('[data-restore-record]').forEach(button=>button.onclick=()=>{button.disabled=true;restoreRecord(button.dataset.restoreRecord);});
 };
 $('#trash-search').oninput=update;update();
}
function trashedRecordDetail(record){
 if(role!=='editor'){$('#main').innerHTML=heading('Registro fora do acervo','Este registro está na lixeira.','<a class="button" href="#registros">Voltar aos registros</a>');return;}
 $('#main').innerHTML=heading(esc(record.title),'Este registro está na lixeira. Restaure-o para editar ou incluí-lo em um novo informe.','<a class="button" href="#lixeira">Voltar à lixeira</a>')+`<section class="panel"><p>Situação anterior: ${esc(labels[record.status]||record.status)}</p><div class="rich-content">${recordHTML(record)}</div><div class="public-photos">${record.photos.map(p=>editorialPhoto(p)).join('')}</div><div class="actions"><button type="button" id="restore-record" class="primary">Restaurar registro</button></div></section>`;
 $('#restore-record').onclick=()=>{$('#restore-record').disabled=true;restoreRecord(record.id);};
}
