// _fxverify.mjs — headless render of the REAL 0.3.32 wire, A/B: raw reader blend byte (flat) vs
// the allowlist-additive override (bright). usage: node _fxverify.mjs <tapeRel> <fi> <label>
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const HERE  = path.dirname(fileURLToPath(import.meta.url));
const MAPLE = path.resolve(HERE, '../../../maplecast-flycast');
const POC   = path.join(MAPLE, 'tools/render-replica-poc');
const PNG   = require(path.join(POC, 'node_modules/pngjs/lib/png.js')).PNG;
const ATLAS_DIR = path.join(MAPLE, 'web/test-atlas/chars');
const TAPE  = path.join(HERE, process.argv[2] || 'tape.json');
const FRAME = +(process.argv[3] || 2205);
const LABEL = process.argv[4] || 'fx';
const W = 640, H = 480;

function localPath(url){let p=String(url).split('?')[0];if(p.startsWith('file://'))p=fileURLToPath(p);return p;}
globalThis.fetch = async (url) => { const p=localPath(url);
  if(!fs.existsSync(p)){const miss=async()=>{throw new Error('404 '+p);};return{ok:false,status:404,json:miss,blob:miss,text:miss,arrayBuffer:miss};}
  const buf=fs.readFileSync(p);
  return{ok:true,status:200,json:async()=>JSON.parse(buf.toString('utf8')),text:async()=>buf.toString('utf8'),
    blob:async()=>({_png:buf}),arrayBuffer:async()=>buf.buffer.slice(buf.byteOffset,buf.byteOffset+buf.byteLength)};};
globalThis.createImageBitmap = async (b)=>{const png=PNG.sync.read(b._png);return{width:png.width,height:png.height,_rgba:new Uint8Array(png.data)};};
globalThis.document={createElement:()=>({width:0,height:0,getContext:()=>({getImageData:()=>({data:new Uint8ClampedArray(0)}),putImageData(){},drawImage(){}})})};
globalThis.window=globalThis; window._emitterPort=true; window._emitZByLayer=true; window._fxGarbleGuard=true;

const { initDevice } = await import(pathToFileURL(path.join(POC,'webgpu-headless.mjs')).href);
const { device } = await initDevice();
let fmtForced='rgba8unorm'; try{navigator.gpu.getPreferredCanvasFormat=()=>'rgba8unorm';}catch(_){}
device.queue.copyExternalImageToTexture=(src,dst,size)=>{const bm=src.source;const[w,h]=size;device.queue.writeTexture({texture:dst.texture},bm._rgba,{bytesPerRow:w*4,rowsPerImage:h},[w,h,1]);};
const canvasTex=device.createTexture({size:[W,H],format:fmtForced,usage:GPUTextureUsage.RENDER_ATTACHMENT|GPUTextureUsage.COPY_SRC|GPUTextureUsage.TEXTURE_BINDING});
const fakeCanvas={width:W,height:H,getContext:(t)=>(t==='webgpu'?{configure(){},unconfigure(){},getCurrentTexture:()=>canvasTex}:null)};

const { SpriteClient } = await import(pathToFileURL(path.join(HERE,'renderer','sprite-client.mjs')).href);
const { SpriteGPU }    = await import(pathToFileURL(path.join(HERE,'renderer','sprite-gpu.mjs')).href);
const { loadTapeJson } = await import(pathToFileURL(path.join(HERE,'tape-adapter.mjs')).href);
const SC=new SpriteClient(); const SG=new SpriteGPU();
SC.assemblyMode=true; SC.predict=false; SC.setCharBase(ATLAS_DIR); SG.init(device,fakeCanvas,'premultiplied');
const AD=await loadTapeJson(TAPE); AD.effectsOn=AD.objRecBytes>=20; SC.objectsOn=AD.effectsOn;
console.log(`tape recBytes=${AD.objRecBytes} frames=${AD.frameCount} p1=${JSON.stringify(AD.p1_team)} p2=${JSON.stringify(AD.p2_team)}`);

async function readTex(tex){const bpr=Math.ceil(W*4/256)*256;const rb=device.createBuffer({size:bpr*H,usage:GPUBufferUsage.COPY_DST|GPUBufferUsage.MAP_READ});
  const enc=device.createCommandEncoder();enc.copyTextureToBuffer({texture:tex},{buffer:rb,bytesPerRow:bpr,rowsPerImage:H},[W,H,1]);device.queue.submit([enc.finish()]);
  await rb.mapAsync(GPUMapMode.READ);const m=new Uint8Array(rb.getMappedRange()).slice();rb.unmap();
  const out=new Uint8Array(W*H*4);for(let y=0;y<H;y++)for(let x=0;x<W;x++){const s=y*bpr+x*4,d=(y*W+x)*4;out[d]=m[s];out[d+1]=m[s+1];out[d+2]=m[s+2];out[d+3]=m[s+3];}return out;}
function writePng(name,px){for(let i=0;i<px.length;i+=4){const a=px[i+3]/255;px[i]=px[i]*a+0x18*(1-a);px[i+1]=px[i+1]*a+0x1a*(1-a);px[i+2]=px[i+2]*a+0x20*(1-a);px[i+3]=255;}
  const png=new PNG({width:W,height:H});png.data=Buffer.from(px.buffer,px.byteOffset,px.byteLength);const p=path.join(HERE,name);fs.writeFileSync(p,PNG.sync.write(png));return p;}
function bright(px){let n=0,sum=0;for(let i=0;i<px.length;i+=4){const b=Math.max(px[i],px[i+1],px[i+2]);if(b>40){n++;sum+=b;}}return{n,avg:n?(sum/n)|0:0};}

async function pass(tag,realOnly){
  if(realOnly)window._fxRealBlendOnly=true; else delete window._fxRealBlendOnly;
  const gframe=AD.applyFrame(SC,FRAME,{load:(sc,cid)=>sc.loadAsmChar(cid)});
  await Promise.all(Object.values(SC._asmLoading||{}));
  for(const cid in SC.asmChars){const c=SC.asmChars[cid];if(c&&c.img&&!SG.chars[cid]){SG.setAtlas(cid,c.img);if(c.pal128)SG.setCharPalette(cid,c.pal128);}if(c&&c.idxImg&&c.lut&&!SG.idxChars[cid]){SG.setIndexedAtlas(cid,c.idxImg);SG.setCharLUT(cid,c.lut);}}
  const dl=SC.buildAssemblyDrawList(W,H);
  const nAdd=dl.filter(s=>s.blend!=null&&(s.blend&0xf)===1).length;
  const d=AD._lastObjs||{};
  try{SG.render(dl,{},null,[],null);}catch(e){console.log('render threw',e.message);}
  await device.queue.onSubmittedWorkDone?.();
  const can=await readTex(canvasTex); const br=bright(can.slice());
  const png=writePng(`_fx_${LABEL}_f${FRAME}_${tag}.png`,can.slice());
  console.log(`[${tag}] gf=${gframe} drawList=${dl.length} additiveItems=${nAdd} diag=${JSON.stringify(d)} brightPx=${br.n} avg=${br.avg}`);
  console.log(`        -> ${png}`);
}
await pass('realblend', true);    // raw reader computeObjectBlend byte (0% additive -> flat/opaque)
await pass('allowlist', false);   // allowlist-additive override (the fix)
console.log('done');
