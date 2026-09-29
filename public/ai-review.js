'use strict';
async function reviewWithAI(handle) {
  const original=handle.value;
  const doc=new DOMParser().parseFromString(original,'text/html');
  const walker=doc.createTreeWalker(doc.body,NodeFilter.SHOW_TEXT),nodes=[];
  while(walker.nextNode())if(walker.currentNode.nodeValue.trim())nodes.push(walker.currentNode);
  const segments=nodes.map((node,id)=>({id,text:node.nodeValue}));
  if(!segments.length)return notify('Escreva um texto antes de pedir a revisão.');
  const dialog=document.createElement('dialog');dialog.className='ai-review-dialog';
  dialog.innerHTML='<h2>Revisar texto com IA</h2><p>A IA propõe correções de português, clareza e simplicidade. Você decide o que aplicar.</p><p class="help">Somente o texto deste campo será enviado à GroqCloud. Fotos, formatação e outros registros não serão enviados. Confira nomes e fatos antes de aceitar.</p><p class="ai-status" role="status">Verificando disponibilidade…</p><div class="ai-changes"></div><div class="actions"><button type="button" class="ai-cancel">Fechar sem aplicar</button><button type="button" class="ai-request primary" disabled>Enviar texto e sugerir melhorias</button><button type="button" class="ai-apply primary" hidden>Aplicar sugestões selecionadas</button></div>';
  document.body.append(dialog);dialog.showModal();
  const controller=new AbortController();let changes=[];
  const status=dialog.querySelector('.ai-status'),requestButton=dialog.querySelector('.ai-request'),applyButton=dialog.querySelector('.ai-apply');
  const close=()=>{controller.abort();dialog.close();dialog.remove();};
  dialog.querySelector('.ai-cancel').onclick=close;
  dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
  try {
    const response=await fetch('/api/ai/status',{signal:controller.signal});
    if(!response.ok)throw Error('Não foi possível consultar a IA.');
    const config=await response.json();
    if(!dialog.isConnected)return;
    if(!config.enabled){status.textContent='A integração está preparada, mas falta configurar a chave gratuita Groq no servidor. Consulte IA e autorização na página Beta.';return;}
    if(segments.length>config.maxSegments||segments.reduce((sum,s)=>sum+s.text.length,0)>config.maxChars){status.textContent='Este campo é longo demais para uma revisão. Divida-o em blocos de até 6.000 caracteres e 100 trechos.';return;}
    status.textContent='Modelo: GPT-OSS 120B · GroqCloud. O envio ocorre somente ao clicar no botão abaixo.';requestButton.disabled=false;
  } catch(error){if(error.name!=='AbortError')status.textContent=error.message;return;}
  requestButton.onclick=async()=>{
    requestButton.disabled=true;status.textContent='Preparando sugestões… O texto original continua preservado.';
    try {
      const response=await fetch('/api/ai/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({segments,consent:true}),signal:controller.signal});
      const result=await response.json();if(!response.ok)throw Error(result.error||'Não foi possível revisar.');
      if(!Array.isArray(result.changes))throw Error('Resposta inválida da IA.');
      changes=result.changes;
      if(changes.some(c=>!Number.isInteger(c.id)||!segments[c.id]||c.before!==segments[c.id].text||typeof c.after!=='string'))throw Error('As sugestões não correspondem ao texto enviado.');
      dialog.querySelector('.ai-changes').innerHTML=changes.map((change,index)=>`<section class="ai-change"><label><input type="checkbox" data-change="${index}" checked> Aceitar esta sugestão</label><div class="ai-comparison"><div><strong>Original</strong><p>${esc(change.before)}</p></div><div><strong>Sugestão</strong><p>${esc(change.after)}</p></div></div><p class="help">${esc(change.reason)}</p></section>`).join('');
      status.textContent=changes.length?`${changes.length} sugestão(ões). Desmarque as que não deseja aplicar.`:'A IA não sugeriu mudanças neste texto.';
      requestButton.hidden=true;applyButton.hidden=!changes.length;
    } catch(error){if(error.name!=='AbortError'){status.textContent=error.message;requestButton.disabled=false;}}
  };
  applyButton.onclick=()=>{
    if(!handle.instance||handle.instance.removed||handle.value!==original){status.textContent='O texto mudou desde o envio. Feche esta revisão e peça novas sugestões.';return;}
    let count=0;
    dialog.querySelectorAll('[data-change]:checked').forEach(box=>{const change=changes[Number(box.dataset.change)];nodes[change.id].nodeValue=change.after;count++;});
    if(!count){status.textContent='Selecione pelo menos uma sugestão ou feche sem aplicar.';return;}
    handle.instance.undoManager.add();
    handle.instance.undoManager.transact(()=>{handle.value=doc.body.innerHTML;});handle.instance.save();
    close();notify('Sugestões aplicadas ao editor. Confira e salve com Ctrl+S. Você pode desfazer no editor.');
  };
}
