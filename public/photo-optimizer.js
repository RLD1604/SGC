'use strict';

// Resize image pixels, not merely the CSS box. Preserve the full scene and aspect ratio.
const PHOTO_OPTIMIZATION_VERSION = 2;
const PHOTO_QUALITY = 0.88;

function photoByteLabel(bytes) {
  return bytes < 1024 ? `${bytes} B` : bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function optimizePhotoBlob(blob, master=false) {
  const bitmap = await createImageBitmap(blob, {imageOrientation:'from-image'});
  try {
    const portrait = bitmap.height > bitmap.width;
    if(bitmap.width*bitmap.height>25000000)throw new Error('Foto acima de 25 megapixels.');
    const box = master ? {width:2048,height:2048} : portrait ? {width:600,height:1065} : {width:1065,height:600};
    const scale = Math.min(1,box.width/bitmap.width,box.height/bitmap.height);
    const width = Math.max(1,Math.round(bitmap.width*scale));
    const height = Math.max(1,Math.round(bitmap.height*scale));
    const canvas = document.createElement('canvas');
    canvas.width = width; canvas.height = height;
    const ctx = canvas.getContext('2d');
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(bitmap,0,0,width,height);
    const encode = (type,quality)=>new Promise((resolve,reject)=>canvas.toBlob(result=>result?resolve(result):reject(new Error('Falha ao comprimir foto')),type,quality));
    let encoded = await encode('image/webp',PHOTO_QUALITY);
    // Tiny graphics may compress better without loss; do not force WebP in that case.
    if (encoded.size > blob.size) {
      const png = await encode('image/png');
      if (png.size < encoded.size) encoded = png;
    }
    const src = await new Promise((resolve,reject)=>{
      const reader = new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(reader.error);reader.readAsDataURL(encoded);
    });
    const result = {src,width,height,bytes:encoded.size,originalBytes:blob.size,mime:encoded.type,optimizationVersion:PHOTO_OPTIMIZATION_VERSION};
    editorialImageSizes.set(src,{width,height});
    return result;
  } finally {bitmap.close()}
}

async function preparePhoto(blob) {
  const master=await optimizePhotoBlob(blob,true);
  const display=await optimizePhotoBlob(blob);
  return {...display,masterSrc:master.src,originalSrc:master.src,masterBytes:master.bytes};
}

async function optimizePhotoSource(src) {
  const response = await fetch(src);
  if (!response.ok) throw new Error('Não foi possível carregar uma foto');
  if (/^\/api\/media\/[a-f0-9]{64}$/.test(src)) {
    const blob=await response.blob();
    const bitmap=await createImageBitmap(blob);
    const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(reader.error);reader.readAsDataURL(blob);});
    const result={src:data,width:bitmap.width,height:bitmap.height,bytes:blob.size,mime:blob.type,optimizationVersion:PHOTO_OPTIMIZATION_VERSION};
    bitmap.close();return result;
  }
  return optimizePhotoBlob(await response.blob());
}

// Operates on a copy: older publications remain untouched, even when exported again.
async function optimizedEditionCopy(edition) {
  const copy = structuredClone(edition);
  const cache = new Map();
  const process = async photo=>{
    delete photo.masterSrc;delete photo.originalSrc;delete photo.masterBytes;
    if (photo.optimizationVersion === PHOTO_OPTIMIZATION_VERSION && photo.src.startsWith('data:')) {
      editorialImageSizes.set(photo.src,{width:photo.width,height:photo.height});
      if (!cache.has(photo.src)) cache.set(photo.src,photo);
      return photo;
    }
    if (!cache.has(photo.src)) cache.set(photo.src,await optimizePhotoSource(photo.src));
    const result={...photo,...cache.get(photo.src)};
    delete result.masterSrc;delete result.originalSrc;delete result.masterBytes;
    return result;
  };
  for (const block of copy.blocks) {
    for (let i=0;i<(block.photos||[]).length;i++) block.photos[i]=await process(block.photos[i]);
  }
  if(copy.cover) copy.cover=(await process({src:copy.cover})).src;
  return copy;
}
