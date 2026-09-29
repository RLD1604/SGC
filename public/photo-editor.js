'use strict';
let photoEditorLoader;
function loadPhotoEditor(){
  if(window.FilerobotImageEditor)return Promise.resolve();
  return photoEditorLoader??=new Promise((resolve,reject)=>{
    const script=document.createElement('script');script.src=sqaUrl('/vendor/filerobot/filerobot-image-editor.min.js');
    script.onload=resolve;script.onerror=()=>{photoEditorLoader=null;script.remove();reject(new Error('Editor indisponível.'));};document.head.append(script);
  });
}
const photoTranslations={
 name:'Nome',save:'Aplicar ajustes',saveAs:'Salvar como',back:'Voltar',loading:'Carregando…',
 resetOperations:'Desfazer todos os ajustes',changesLoseWarningHint:'Deseja descartar os ajustes desta sessão?',discardChangesWarningHint:'Os ajustes não aplicados serão descartados.',
 cancel:'Cancelar',apply:'Aplicar',warning:'Atenção',confirm:'Confirmar',discardChanges:'Descartar ajustes',
 undoTitle:'Desfazer',redoTitle:'Refazer',showImageTitle:'Comparar com a foto inicial',zoomInTitle:'Ampliar',zoomOutTitle:'Reduzir',toggleZoomMenuTitle:'Opções de ampliação',
 adjustTab:'Enquadramento',finetuneTab:'Luz e cores',filtersTab:'Filtros',watermarkTab:'Marca d’água',annotateTabLabel:'Marcações',resize:'Redimensionar',resizeTab:'Tamanho',imageName:'Nome da foto',
 invalidImageError:'Não foi possível abrir a foto.',uploadImageError:'Não foi possível carregar a foto.',
 cropTool:'Recortar',original:'Original',custom:'Livre',square:'Quadrado',landscape:'Horizontal',portrait:'Vertical',ellipse:'Elipse',classicTv:'4:3',cinemascope:'Panorâmico',
 arrowTool:'Seta',blurTool:'Desfoque',brightnessTool:'Luminosidade',contrastTool:'Contraste',ellipseTool:'Elipse',unFlipX:'Desfazer espelhamento horizontal',flipX:'Espelhar horizontalmente',unFlipY:'Desfazer espelhamento vertical',flipY:'Espelhar verticalmente',
 hsvTool:'Cores',hue:'Matiz',brightness:'Luminosidade',saturation:'Saturação',value:'Intensidade',imageTool:'Imagem',importing:'Carregando…',addImage:'Adicionar imagem',uploadImage:'Enviar imagem',fromGallery:'Da galeria',
 lineTool:'Linha',penTool:'Desenhar',polygonTool:'Polígono',sides:'Lados',rectangleTool:'Retângulo',cornerRadius:'Cantos arredondados',resizeWidthTitle:'Largura em pixels',resizeHeightTitle:'Altura em pixels',toggleRatioLockTitle:'Manter proporção',resetSize:'Restaurar tamanho',rotateTool:'Girar',textTool:'Texto',
 textSpacings:'Espaçamento',textAlignment:'Alinhamento',fontFamily:'Fonte',size:'Tamanho',letterSpacing:'Entre letras',lineHeight:'Entre linhas',warmthTool:'Temperatura',padding:'Margem',paddings:'Margens',shadow:'Sombra',horizontal:'Horizontal',vertical:'Vertical',blur:'Desfoque',opacity:'Opacidade',transparency:'Transparência',position:'Posição',stroke:'Contorno',
 saveAsModalTitle:'Salvar foto',extension:'Extensão',format:'Formato',nameIsRequired:'Informe um nome.',quality:'Qualidade',imageDimensionsHoverTitle:'Resolução da foto',cropSizeLowerThanResizedWarning:'Este recorte pode reduzir a qualidade.',actualSize:'Tamanho real',fitSize:'Ajustar à tela',addImageTitle:'Escolher imagem',mutualizedFailedToLoadImg:'Não foi possível carregar a foto.',tabsMenu:'Ferramentas',download:'Baixar',width:'Largura',height:'Altura',cropItemNoEffect:'Prévia indisponível'
};
async function editPhoto(photo,onApplied){
  const route=location.hash,opener=document.activeElement;
  try{await loadPhotoEditor();}catch{notify('Não foi possível abrir o editor de fotos. Tente novamente.');return;}
  if(location.hash!==route)return;
  const dialog=document.createElement('dialog');dialog.className='photo-editor-dialog';dialog.setAttribute('aria-label','Ajustar foto');
  dialog.innerHTML='<header><h2>Ajustar foto</h2><button type="button" data-cancel-photo>Cancelar</button><button type="button" data-restore-photo>Restaurar cópia guardada</button></header><p class="help">Os ajustes serão aplicados ao rascunho. Depois, salve o registro ou a edição.</p><div class="photo-editor-host"></div><p class="photo-editor-status" role="status"></p>';
  document.body.append(dialog);dialog.showModal();
  const host=dialog.querySelector('.photo-editor-host'),status=dialog.querySelector('[role="status"]');
  let instance,busy=false,closed=false;
  const close=()=>{if(closed)return;closed=true;instance?.terminate();dialog.close();dialog.remove();window.removeEventListener('hashchange',close);opener?.focus();};
  window.addEventListener('hashchange',close);
  dialog.addEventListener('cancel',event=>{event.preventDefault();if(!busy)close();});
  dialog.querySelector('[data-cancel-photo]').onclick=()=>{if(!busy)close();};
  const apply=async(blob,restoring=false)=>{
    if(busy||closed)return;busy=true;status.textContent='Preparando foto com qualidade…';
    dialog.querySelectorAll('header button').forEach(b=>b.disabled=true);
    try{
      const prepared=await preparePhoto(blob);
      if(closed)return;
      const originalSrc=photo.originalSrc||photo.masterSrc||photo.src;
      Object.assign(photo,prepared,{originalSrc,orientation:'auto'});
      await onApplied();close();notify(restoring?'Cópia guardada restaurada. Salve para gravar.':'Ajustes aplicados. Salve para gravar.');
    }catch{status.textContent='Não foi possível aplicar a foto. Tente novamente.';}
    finally{busy=false;dialog.querySelectorAll('header button').forEach(b=>b.disabled=false);}
  };
  const restore=dialog.querySelector('[data-restore-photo]');
  restore.disabled=!photo.originalSrc;
  restore.onclick=async()=>{try{const response=await fetch(photo.originalSrc);if(!response.ok)throw new Error();await apply(await response.blob(),true);}catch{status.textContent='Não foi possível carregar a cópia guardada.';}};
  if(!photo.masterSrc)status.textContent='Foto antiga: os detalhes já reduzidos não podem ser recuperados. Reenvie a foto para melhorar a qualidade.';
  instance=new FilerobotImageEditor(host,{
    source:sqaUrl(photo.masterSrc||photo.src),translations:photoTranslations,useBackendTranslations:false,
    theme:{typography:{fontFamily:'Arial, sans-serif'}},
    tabsIds:['Adjust','Finetune','Annotate'],defaultTabId:'Finetune',
    savingPixelRatio:1,previewPixelRatio:1,defaultSavedImageType:'png',
    annotationsCommon:{fill:'#e23333'},Text:{text:'Observação',fonts:['Arial','Georgia','Verdana']},
    Crop:{presetsItems:[]},Rotate:{angle:90,componentType:'buttons'},onBeforeSave:()=>false,
    onSave:async result=>{
      const blob=await new Promise(resolve=>result.imageCanvas.toBlob(resolve,'image/png'));
      if(blob)await apply(blob);
    }
  });
  instance.render();
}
