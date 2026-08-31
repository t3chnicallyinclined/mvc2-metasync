// _proof_render_model.mjs — HEADLESS before/after proof for the AUTHORITATIVE RENDER-COMPOSITE
// MODEL (docs/RENDER-ACCURACY-PROGRAM.md 2026-08-31). Renders tape_59601369.json (Storm/Magneto/
// Colossus vs Spiral/Blackheart/SonSon) as stage(3D opaque) + bodies/effects(2D translucent) and
// writes composite PNGs for two cases:
//   • CAPE-TIE frame (41): the depth buffer OFF (painter / last-wins) vs ON (z-buffer).
//   • BLACKHEART-ASSIST frame (3131): owner-gate ON (old drop) vs OFF (step-4 fix, assist draws).
// usage: node _proof_render_model.mjs
import fs from 'node:fs'; import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url'; import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const MAPLE = 'C:/Users/trist/projects/maplecast-flycast';
const POC = path.join(MAPLE, 'tools/render-replica-poc');
const PNG = require(path.join(POC, 'node_modules/pngjs/lib/png.js')).PNG;
const ATLAS = path.join(MAPLE, 'web/test-atlas/chars');
const STAGES = path.join(HERE, 'stages');
const W = 640, H = 480;
const TEAM = [42, 49, 44, 53, 50, 20];   // interleaved slot cids for tape_59601369

function localPath(url){ let p=String(url).split('?')[0]; if(p.startsWith('file://'))p=fileURLToPath(p); return p; }
globalThis.fetch = async (url) => { const p = localPath(url);
  if (!fs.existsSync(p)) { const m=async()=>{throw new Error('404 '+p)}; return {ok:false,status:404,json:m,blob:m,text:m,arrayBuffer:m}; }
  const buf = fs.readFileSync(p);
  return { ok:true, status:200, json:async()=>JSON.parse(buf.toString('utf8')), text:async()=>buf.toString('utf8'),
    blob:async()=>({_png:buf}), arrayBuffer:async()=>buf.buffer.slice(buf.byteOffset, buf.byteOffset+buf.byteLength) }; };
globalThis.createImageBitmap = async (blob) => { const png = PNG.sync.read(blob._png); return { width:png.width, height:png.height, _rgba:new Uint8Array(png.data) }; };
globalThis.document = { createElement: () => ({ width:0,height:0, getContext: () => ({ getImageData:()=>({data:new Uint8ClampedArray(0)}), putImageData(){}, drawImage(){} }) }) };
globalThis.window = globalThis;
window._emitterPort = true; window._emitZByLayer = true; window._fxGarbleGuard = false; window._bodyGarbleGuard = false;

const { initDevice } = await import(pathToFileURL(path.join(POC,'webgpu-headless.mjs')).href);
const { device } = await initDevice();
try { navigator.gpu.getPreferredCanvasFormat = () => 'rgba8unorm'; } catch(_) {}
device.queue.copyExternalImageToTexture = (src,dst,size) => { const [w,h]=size; device.queue.writeTexture({texture:dst.texture}, src.source._rgba, {bytesPerRow:w*4,rowsPerImage:h}, [w,h,1]); };
function mkTex(){ return device.createTexture({size:[W,H],format:'rgba8unorm',usage:GPUTextureUsage.RENDER_ATTACHMENT|GPUTextureUsage.COPY_SRC|GPUTextureUsage.TEXTURE_BINDING}); }
async function readTex(tex){ const bpr=Math.ceil(W*4/256)*256; const rb=device.createBuffer({size:bpr*H,usage:GPUBufferUsage.COPY_DST|GPUBufferUsage.MAP_READ});
  const e=device.createCommandEncoder(); e.copyTextureToBuffer({texture:tex},{buffer:rb,bytesPerRow:bpr,rowsPerImage:H},[W,H,1]); device.queue.submit([e.finish()]);
  await rb.mapAsync(GPUMapMode.READ); const m=new Uint8Array(rb.getMappedRange()).slice(); rb.unmap();
  const o=new Uint8Array(W*H*4); for(let y=0;y<H;y++)for(let x=0;x<W;x++){const s=y*bpr+x*4,d=(y*W+x)*4;o[d]=m[s];o[d+1]=m[s+1];o[d+2]=m[s+2];o[d+3]=m[s+3];} return o; }

const { StageClient }  = await import(pathToFileURL(path.join(HERE,'renderer','stage-client.mjs')).href);
const { PVR2Renderer } = await import(pathToFileURL(path.join(HERE,'renderer','pvr2-renderer.mjs')).href);
const { SpriteClient } = await import(pathToFileURL(path.join(HERE,'renderer','sprite-client.mjs')).href);
const { SpriteGPU }    = await import(pathToFileURL(path.join(HERE,'renderer','sprite-gpu.mjs')).href);
const { loadTapeJson } = await import(pathToFileURL(path.join(HERE,'tape-adapter.mjs')).href);

const AD = await loadTapeJson(path.join(HERE,'tape_59601369.json'));

// one SpriteClient/SpriteGPU, reused; preload BOTH teams so a detached assist has its atlas.
const SC = new SpriteClient(); const SG = new SpriteGPU();
SC.assemblyMode = true; SC.predict = false; SC.hitFlashOn = true; SC.setCharBase(ATLAS);
SG.init(device, { width:W, height:H, getContext:(t)=>t==='webgpu'?{configure(){},unconfigure(){},getCurrentTexture:()=>mkTex()}:null }, 'premultiplied');
AD.effectsOn = (AD.objRecBytes >= 20); SC.objectsOn = true;
for (const cid of TEAM) SC.loadAsmChar(cid);
await Promise.all(Object.values(SC._asmLoading || {}));
for (const cid in SC.asmChars){ const c=SC.asmChars[cid];
  if (c && c.img && !SG.chars[cid]) { SG.setAtlas(cid,c.img); if(c.pal128)SG.setCharPalette(cid,c.pal128); }
  if (c && c.idxImg && c.lut && !SG.idxChars[cid]) { SG.setIndexedAtlas(cid,c.idxImg); SG.setCharLUT(cid,c.lut); } }

async function renderCase(frame, tag, flags){
  Object.assign(window, flags);
  const row = AD.frames[frame];
  // stage
  const stageTex = mkTex();
  const stageCanvas = { width:W, height:H, getContext:(t)=>t==='webgpu'?{configure(){},getCurrentTexture:()=>stageTex}:null };
  const STAGE = new StageClient(STAGES); STAGE.attachDevice(device); await STAGE.setStage(AD.stage_id ?? 0);
  STAGE.setCamB(row[20], row[21]);
  const stageR = new PVR2Renderer(); stageR.initShared(stageCanvas, device); STAGE.render(stageR);
  await device.queue.onSubmittedWorkDone?.();
  const stagePx = await readTex(stageTex);
  // bodies + effects
  AD.applyFrame(SC, frame, { load:(sc,cid)=>sc.loadAsmChar(cid) });
  await Promise.all(Object.values(SC._asmLoading || {}));
  const drawList = SC.buildAssemblyDrawList(W,H);
  SG.render(drawList, {}, null, [], null);
  await device.queue.onSubmittedWorkDone?.();
  const bodyPx = await readTex(SG.PP.offscreenTex);
  // composite over a neutral BG
  const out = new Uint8Array(W*H*4);
  for (let i=0;i<W*H*4;i+=4){ let r=0x18,g=0x1a,b=0x20;
    const sa=stagePx[i+3]/255; r=stagePx[i]*sa+r*(1-sa); g=stagePx[i+1]*sa+g*(1-sa); b=stagePx[i+2]*sa+b*(1-sa);
    const ba=bodyPx[i+3]/255;  r=bodyPx[i]*ba+r*(1-ba); g=bodyPx[i+1]*ba+g*(1-ba); b=bodyPx[i+2]*ba+b*(1-ba);
    out[i]=r; out[i+1]=g; out[i+2]=b; out[i+3]=255; }
  const png = new PNG({width:W,height:H}); png.data = Buffer.from(out.buffer, out.byteOffset, out.byteOffset+out.byteLength);
  const p = path.join(HERE, `_proof_model_${tag}.png`); fs.writeFileSync(p, PNG.sync.write(png));
  const byCid={}; for(const it of drawList) byCid[it.charId]=(byCid[it.charId]||0)+1;
  console.log(`  ${tag}: quads=${drawList.length} skipSel=${SC._asmSkipSel} perCid=${JSON.stringify(byCid)} -> ${path.basename(p)}`);
  return { drawList, byCid };
}

console.log('CAPE-TIE frame 41 (Storm cid42):');
await renderCase(41, 'cape_f41_zbufOFF', { _spriteZBuf:false, _capeTieBehind:true, _satRequireOwner:false });
await renderCase(41, 'cape_f41_zbufON',  { _spriteZBuf:true,  _capeTieBehind:true, _satRequireOwner:false });
// cid42 z-bucket census (cape should sit one bucket BEHIND the body)
{ const dl = SC.buildAssemblyDrawList(W,H); const buck={};
  for(const it of dl){ if(it.charId!==42) continue; const bk=Math.floor((it.z||0)/1e5); buck[bk]=(buck[bk]||0)+1; }
  console.log(`  cid42 z-buckets floor(z/1e5): ${JSON.stringify(buck)} (bodyLayer=${AD.frames[41][30][0]}; tied cape one bucket below)`); }

console.log('BLACKHEART-ASSIST frame 3131 (Blackheart cid53, body INACTIVE):');
const before = await renderCase(3131, 'bh_f3131_ownerGATE', { _spriteZBuf:true, _capeTieBehind:true, _satRequireOwner:true });
const after  = await renderCase(3131, 'bh_f3131_FIXED',      { _spriteZBuf:true, _capeTieBehind:true, _satRequireOwner:false });
console.log(`  Blackheart (cid53) parts: owner-gate=${before.byCid[53]||0}  fixed=${after.byCid[53]||0}  (0 -> >0 = step-4 fix)`);
process.exit(0);
