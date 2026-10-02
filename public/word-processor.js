'use strict';
// One editor lifecycle and one HTML contract for every narrative field.
const wordProcessors=new Map();

function plainToRich(value='') {
  return String(value).split(/\r?\n/).map(line=>`<p>${esc(line)||'<br>'}</p>`).join('');
}
function recordHTML(record) {
  return sanitizeEditorialHTML(record.textHtml ?? plainToRich(record.text));
}
function richPlainText(html) {
  const doc=new DOMParser().parseFromString(sanitizeEditorialHTML(html),'text/html');
  doc.querySelectorAll('br').forEach(node=>node.replaceWith('\n'));
  doc.querySelectorAll('p,div,li,h1,h2,h3,h4,h5,h6,tr').forEach(node=>node.append('\n'));
  return doc.body.textContent.replace(/\u00a0/g,' ').replace(/\n{3,}/g,'\n\n').trim();
}
function hasMeaningfulRichText(html) { return richPlainText(html).length>0; }
function saveCurrentText() {
  syncWordProcessors();
  const button=document.querySelector('#save-editor, #save-feedback, #record-form button[value="draft"]');
  button?.click();
}

function createWordProcessor(selector,documentContext=null) {
  const target=typeof selector==='string'?document.querySelector(selector):selector;
  if(wordProcessors.has(target))return wordProcessors.get(target);
  let instance=null,removed=false;
  const handle={
    get value(){return sanitizeEditorialHTML(instance?.initialized?instance.getContent():target.value);},
    set value(html){target.value=sanitizeEditorialHTML(html);if(instance?.initialized)instance.setContent(target.value);},
    get editor(){return instance?.getBody();},
    get instance(){return instance;},
    documentContext(){
      const routeId=location.hash.split('/')[1];
      const record=target.id==='record-text'?currentRecord:target.id==='feedback'?state?.records?.find(item=>item.id===routeId):null;
      const inferred=record?{documentType:'record',documentId:record.id,expectedRevision:record.revision}:null;
      const context=documentContext||inferred;
      const type=context?.documentType||target.dataset.documentType;
      const id=context?.documentId||target.dataset.documentId;
      const revision=Number(context?.expectedRevision??target.dataset.documentRevision);
      return type&&id&&Number.isInteger(revision)?{documentType:type,documentId:id,expectedRevision:revision}:null;
    },
    sync(){if(instance?.initialized)target.value=handle.value;},
    destruct(){removed=true;if(instance)instance.remove();wordProcessors.delete(target);}
  };
  wordProcessors.set(target,handle);
  handle.ready=tinymce.init({
    target,base_url:sqaUrl('/vendor/tinymce'),suffix:'.min',license_key:'gpl',
    language:'pt-BR',language_url:sqaUrl('/vendor/tinymce/langs/pt-BR.js'),
    promotion:false,branding:true,height:target.id==='rich-editor'?680:520,min_height:360,
    menubar:'edit view insert format tools table help',
    plugins:'advlist autolink lists link charmap preview searchreplace visualblocks visualchars fullscreen insertdatetime table wordcount nonbreaking help',
    toolbar:[
      'undo redo | blocks | aireview fullscreen',
      'bold italic underline strikethrough | fontfamily fontsize | forecolor backcolor removeformat',
      'alignleft aligncenter alignright alignjustify | bullist numlist outdent indent | lineheight paragraphspace | table link charmap | searchreplace'
    ],
    toolbar_mode:'sliding',toolbar_sticky:false,resize:true,contextmenu:'link table',
    font_family_formats:'Arial=arial,sans-serif;Georgia=georgia,serif;Times New Roman=times new roman,serif;Verdana=verdana,sans-serif;Courier New=courier new,monospace',
    font_size_formats:'10pt 11pt 12pt 14pt 16pt 18pt 20pt 24pt 28pt 32pt 36pt',
    block_formats:'Parágrafo=p;Título 1=h1;Título 2=h2;Título 3=h3;Citação=blockquote',
    line_height_formats:'1 1.15 1.5 2',
    browser_spellcheck:true,content_css:sqaUrl('/word-processor-content.css'),
    paste_data_images:false,automatic_uploads:false,images_upload_handler:undefined,
    invalid_elements:'script,style,iframe,object,embed,svg,math,img,form,input,button,link,meta,video,audio',
    convert_urls:false,relative_urls:false,object_resizing:'table',
    table_default_attributes:{border:'1'},table_default_styles:{'border-collapse':'collapse',width:'100%'},
    setup(ed) {
      instance=ed;
      ed.ui.registry.addContextToolbar('textselection',{
        predicate:()=>!ed.selection.isCollapsed(),
        items:'bold italic underline | forecolor link',position:'selection',scope:'editor'
      });
      ed.ui.registry.addButton('aireview',{text:'Revisar com IA',tooltip:'Revisar com IA',onAction:()=>reviewWithAI(handle)});
      ed.ui.registry.addMenuButton('paragraphspace',{
        text:'Espaço ¶',tooltip:'Espaçamento após o parágrafo',
        fetch(callback){callback([0,6,12,18,24].map(space=>({type:'menuitem',text:space+' pt',onAction:()=>{ed.undoManager.transact(()=>{for(const block of ed.selection.getSelectedBlocks())ed.dom.setStyle(block,'margin-bottom',space+'pt');});ed.nodeChanged();ed.save();}})));}
      });
      ed.addShortcut('meta+s','Salvar texto',()=>{saveCurrentText();return false;});
      ed.on('init',()=>{
        if(removed||!target.isConnected){ed.remove();return;}
        instance=ed;ed.setContent(sanitizeEditorialHTML(target.value));
        const container=ed.getContainer(),controls=document.createElement('div');
        controls.className='processor-controls';
        const toggle=document.createElement('button');
        toggle.type='button';toggle.className='processor-toggle';
        const header=container.querySelector('.tox-editor-header');
        header.id=ed.id+'-formatting';toggle.setAttribute('aria-controls',header.id);
        const hint=document.createElement('span');hint.textContent='Selecione um trecho para formatar. Tela cheia: Ctrl + Shift + F.';
        controls.append(toggle,hint);container.prepend(controls);
        let expanded=false;
        try{expanded=localStorage.getItem('sqa-editor-tools')==='expanded';}catch{}
        const update=()=>{
          container.classList.toggle('processor-compact',!expanded);
          toggle.textContent=expanded?'Recolher ferramentas':'Mais ferramentas';
          toggle.setAttribute('aria-expanded',String(expanded));
          ed.dispatch('ResizeEditor');
        };
        toggle.onclick=()=>{expanded=!expanded;try{localStorage.setItem('sqa-editor-tools',expanded?'expanded':'compact');}catch{}update();};
        update();
      });
      ed.on('change input undo redo',()=>{if(instance)ed.save();document.dispatchEvent(new CustomEvent('editor-dirty'));});
      ed.on('BeforeSetContent',event=>{if(event.content)event.content=sanitizeEditorialHTML(event.content);});
    }
  }).catch(()=>{if(!removed)notify('Não foi possível abrir o editor. O campo de texto continua disponível.');});
  return handle;
}
function mountWordProcessors(root) {
  root.querySelectorAll('textarea').forEach(target=>createWordProcessor(target));
}
function syncWordProcessors(root=document) {
  for(const [target,handle] of wordProcessors)if(root.contains(target))handle.sync();
}
function destroyWordProcessors(root=document) {
  for(const [target,handle] of [...wordProcessors])if(root.contains(target)||!target.isConnected)handle.destruct();
}

function feedbackForm(recordId) {
  const record=state.records.find(item=>item.id===recordId);
  if(!record){location.hash='#registros';return;}
  if(record.deletedAt){trashedRecordDetail(record);return;}
  $('#main').innerHTML=heading('O que precisa ser completado?',esc(record.title),`<a class="button" href="#registro/${record.id}">Voltar ao registro</a>`)+`<section class="panel"><form id="feedback-form"><label for="feedback">Orientação para o funcionário</label><textarea id="feedback">${esc(record.feedbackHtml??plainToRich(record.feedback||''))}</textarea><p class="processor-help">Explique o que precisa ser acrescentado. Você pode organizar o pedido em tópicos ou tabelas.</p><div class="actions"><button type="submit" id="save-feedback" class="primary">Solicitar complemento</button></div></form></section>`;
  $('#feedback-form').onsubmit=async event=>{
    event.preventDefault();syncWordProcessors(event.target);
    const html=sanitizeEditorialHTML($('#feedback').value),text=richPlainText(html);
    if(!hasMeaningfulRichText(html))return notify('Escreva uma orientação para o funcionário.');
    record.feedback=text;record.feedbackHtml=html;record.status='fix';
    if(await save('Pedido de complemento salvo.'))location.hash='#registro/'+record.id;
  };
}
