'use strict';

// Shared by the editing surface, preview and standalone HTML export.
function sanitizeEditorialHTML(html) {
  const doc = new DOMParser().parseFromString(html || '', 'text/html');
  doc.querySelectorAll('script,style,iframe,object,embed,svg,math,img,form,input,button,link,meta').forEach(el => el.remove());
  const tags = new Set(['P','BR','STRONG','B','I','EM','U','S','STRIKE','SUB','SUP','UL','OL','LI','H1','H2','H3','H4','H5','H6','BLOCKQUOTE','TABLE','CAPTION','COLGROUP','COL','THEAD','TBODY','TFOOT','TR','TH','TD','A','SPAN','DIV','HR','PRE']);
  const styles = new Set(['color','background-color','font-family','font-size','font-weight','font-style','text-decoration','text-align','line-height','margin-left','margin-right','margin-top','margin-bottom','text-indent','padding','padding-left','padding-right','padding-top','padding-bottom','border','border-width','border-style','border-color','border-collapse','width','height','vertical-align','list-style-type']);
  const fonts = new Set(['arial','georgia','times new roman','verdana','tahoma','trebuchet ms','segoe ui','courier new','sans-serif','serif','monospace']);
  for (const el of [...doc.body.querySelectorAll('*')]) {
    if (!tags.has(el.tagName)) { el.replaceWith(...el.childNodes); continue; }
    const clean = document.createElement('span');
    for (const prop of styles) {
      let value = el.style.getPropertyValue(prop);
      if (!value || /url\s*\(|expression|var\s*\(|[<>\\]/i.test(value)) continue;
      if (prop === 'font-family' && !value.split(',').every(f => fonts.has(f.trim().replace(/["']/g,'').toLowerCase()))) continue;
      if (prop === 'font-size' && (!/^[\d.]+(px|pt|em|rem|%)$/.test(value) || parseFloat(value) > 96)) continue;
      if ((prop === 'width' || prop === 'height') && !['TABLE','TD','TH','COL'].includes(el.tagName)) continue;
      if (prop.startsWith('margin') || prop === 'text-indent') {
        if (!/^[\d.]+(px|pt|em|rem|%)?$/.test(value) || parseFloat(value)>200) continue;
      }
      clean.style.setProperty(prop,value);
    }
    for (const a of [...el.attributes]) {
      if (el.tagName === 'A' && a.name === 'href' && /^(https?:\/\/|mailto:|tel:)/i.test(a.value)) continue;
      if (['TD','TH'].includes(el.tagName) && ['colspan','rowspan'].includes(a.name) && /^(?:[1-9]|[1-9][0-9])$/.test(a.value)) continue;
      if (el.tagName === 'OL' && a.name === 'start' && /^\d{1,4}$/.test(a.value)) continue;
      el.removeAttribute(a.name);
    }
    if (clean.style.cssText) el.setAttribute('style',clean.style.cssText);
  }
  return doc.body.innerHTML;
}

const editorialImageSizes = new Map();
async function measureEditorialPhotos(data) {
  const photos=[...data.records.flatMap(r=>r.photos||[]),...data.editions.flatMap(e=>e.blocks.flatMap(b=>b.photos||[])),...data.publications.flatMap(e=>e.blocks.flatMap(b=>b.photos||[]))];
  const sources=[...new Set([...photos.map(p=>p.src),...data.editions.map(e=>e.cover),...data.publications.map(e=>e.cover)].filter(Boolean))];
  await Promise.all(sources.map(src=>new Promise(resolve=>{
    const img=new Image();
    const timer=setTimeout(resolve,5000);
    img.onload=()=>{clearTimeout(timer);editorialImageSizes.set(src,{width:img.naturalWidth,height:img.naturalHeight});resolve()};
    img.onerror=()=>{clearTimeout(timer);resolve()};
    img.src=sqaUrl(src);
  })));
}
function photoFrame(photo) {
  const size=editorialImageSizes.get(photo.src)||photo;
  const vertical=photo.orientation==='portrait'||(photo.orientation!=='landscape'&&size.height>size.width);
  return {width:vertical?200:355,height:vertical?355:200,kind:vertical?'portrait':'landscape'};
}
function editorialPhoto(photo,caption=true) {
  const frame=photoFrame(photo);
  return `<figure class="standard-photo ${frame.kind}${photo.featured?' featured-photo':''}"><img src="${esc(sqaUrl(photo.src))}" width="${frame.width}" height="${frame.height}" alt="${esc(photo.caption||photo.phase||'Foto do condomínio')}" loading="eager">${caption?`<figcaption><strong>${esc(photo.phase||'Registro geral')}</strong>${photo.caption?' · '+esc(photo.caption):''}</figcaption>`:''}</figure>`;
}

function showBlockPicker(edition,capture) {
  capture();
  const presets=['Palavra do Síndico','Informações gerais','Atenção especial','Regras dos espaços','Convivência','Grade esportiva','Contatos','Matéria'];
  const customTypes=[...new Set(state.editions.flatMap(e=>e.blocks.map(b=>b.type)))].filter(t=>!presets.includes(t));
  modal(`<h2>Adicionar um bloco</h2><p class="help">Use um modelo ou crie uma seção com o nome que desejar.</p><div class="form-grid">${[...presets,...customTypes].map(t=>`<button type="button" data-type="${esc(t)}">${esc(t)}</button>`).join('')}</div><hr><h3>Criar outro bloco</h3><form id="custom-block-form"><label>Nome da seção<input id="custom-block-name" maxlength="100" placeholder="Ex.: Prestação de contas, Achados e perdidos…" required></label><div class="actions"><button type="submit" class="primary">Criar bloco personalizado</button></div></form>`,()=>{
    const create=async type=>{
      edition.blocks.push({id:id(),type,title:type,body:type==='Grade esportiva'?'<table><thead><tr><th>Atividade</th><th>Dia</th><th>Horário</th><th>Local</th></tr></thead><tbody><tr><td></td><td></td><td></td><td></td></tr></tbody></table>':'<p><br></p>',photos:[],sources:[]});
      edition.version++;activeBlock=edition.blocks.length-1;
      if(await save('Bloco criado. Escreva o conteúdo e salve a edição.')) {$('#dialog').close();render();}
    };
    document.querySelectorAll('[data-type]').forEach(button=>button.onclick=()=>create(button.dataset.type));
    $('#custom-block-form').onsubmit=event=>{event.preventDefault();const name=$('#custom-block-name').value.trim();if(!name)return notify('Dê um nome à seção.');create(name)};
  });
}
