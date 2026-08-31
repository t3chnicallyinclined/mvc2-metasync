// _proof_objs.mjs — HEADLESS proof: stage + bodies + OBJECTS (effectsOn) for bugs 3 & 4.
// Renders tape_59601369.json (Storm/Magneto/Colossus vs Spiral/Blackheart/SonSon) with the
// object/effect pass ON, reports the render census, and writes a composite PNG.
// usage: node _proof_objs.mjs [replayFrameIdx] [capeTieBehind=1|0]
import fs from 'node:fs'; import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url'; import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const MAPLE = 'C:/Users/trist/projects/maplecast-flycast';
const POC = path.join(MAPLE, 'tools/render-replica-poc');
const PNG = require(path.join(POC, 'node_modules/pngjs/lib/png.js')).PNG;
const ATLAS = path.join(MAPLE, 'web/test-atlas/chars');
const STAGES = path.join(HERE, 'stages');
const FRAME = +(process.argv[2] || 41);
const CAPE = process.argv[3] === undefined ? true : process.argv[3] !== '0';
const W = 640, H = 480;

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
window._capeTieBehind = CAPE;

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
const row = AD.frames[FRAME];

const stageTex = mkTex();
const stageCanvas = { width:W, height:H, getContext:(t)=>t==='webgpu'?{configure(){},getCurrentTexture:()=>stageTex}:null };
const STAGE = new StageClient(STAGES); STAGE.attachDevice(device); await STAGE.setStage(AD.stage_id ?? 0);
STAGE.setCamB(row[20], row[21]);
const stageR = new PVR2Renderer(); stageR.initShared(stageCanvas, device); STAGE.render(stageR);
await device.queue.onSubmittedWorkDone?.();
const stagePx = await readTex(stageTex);

const bodyTex = mkTex();
const bodyCanvas = { width:W, height:H, getContext:(t)=>t==='webgpu'?{configure(){},unconfigure(){},getCurrentTexture:()=>bodyTex}:null };
const SC = new SpriteClient(); const SG = new SpriteGPU();
SC.assemblyMode = true; SC.predict = false; SC.hitFlashOn = true; SC.setCharBase(ATLAS);
SG.init(device, bodyCanvas, 'premultiplied');
AD.effectsOn = (AD.objRecBytes >= 20); SC.objectsOn = true;
// apply twice so lazily-loaded atlases are present for the emit
AD.applyFrame(SC, FRAME, { load:(sc,cid)=>sc.loadAsmChar(cid) });
await Promise.all(Object.values(SC._asmLoading || {}));
AD.applyFrame(SC, FRAME, { load:(sc,cid)=>sc.loadAsmChar(cid) });
await Promise.all(Object.values(SC._asmLoading || {}));
for (const cid in SC.asmChars){ const c=SC.asmChars[cid];
  if (c && c.img && !SG.chars[cid]) { SG.setAtlas(cid,c.img); if(c.pal128)SG.setCharPalette(cid,c.pal128); }
  if (c && c.idxImg && c.lut && !SG.idxChars[cid]) { SG.setIndexedAtlas(cid,c.idxImg); SG.setCharLUT(cid,c.lut); } }
const drawList = SC.buildAssemblyDrawList(W,H);
SG.render(drawList, {}, null, [], null);
await device.queue.onSubmittedWorkDone?.();
const bodyPx = await readTex(SG.PP && SG.PP.offscreenTex ? SG.PP.offscreenTex : bodyTex);

const out = new Uint8Array(W*H*4);
for (let i=0;i<W*H*4;i+=4){ let r=0x18,g=0x1a,b=0x20;
  const sa=stagePx[i+3]/255; r=stagePx[i]*sa+r*(1-sa); g=stagePx[i+1]*sa+g*(1-sa); b=stagePx[i+2]*sa+b*(1-sa);
  const ba=bodyPx[i+3]/255;  r=bodyPx[i]*ba+r*(1-ba); g=bodyPx[i+1]*ba+g*(1-ba); b=bodyPx[i+2]*ba+b*(1-ba);
  out[i]=r; out[i+1]=g; out[i+2]=b; out[i+3]=255; }
const png = new PNG({width:W,height:H}); png.data = Buffer.from(out.buffer, out.byteOffset, out.byteLength);
const tag = CAPE ? 'capefix' : 'capeoff';
const p = path.join(HERE, `_proof_objs_f${FRAME}_${tag}.png`); fs.writeFileSync(p, PNG.sync.write(png));

// Z-BUCKET census for Storm (cid 42): how her body parts vs her attached effect parts
// distribute across the layer buckets (floor(z/1e5)). With the fix, the tied effect drops
// from bucket 5 (interleaved with the body) into bucket 4 (strictly behind the whole body).
{
  const buck = {};
  for (const it of drawList) { if (it.charId !== 42) continue; const b = Math.floor((it.z || 0) / 1e5);
    buck[b] = (buck[b] || 0) + 1; }
  console.log(`  cid42 z-buckets floor(z/1e5): ${JSON.stringify(buck)}  (bodyLayer=${row[30][0]}; tied effect should sit one bucket BELOW when fixed)`);
}
const d = AD._lastObjs || {};
console.log(`frame idx ${FRAME} (game ${row[0]}) capeTieBehind=${CAPE}`);
console.log(`  OBJS diag: total=${d.total} effect=${d.effect} satellite=${d.satellite} drawn=${d.drawn} gated=${d.gated} 3D=${d.threeD} ownerless=${d.ownerless}`);
console.log(`  emitter: drawList quads=${drawList.length}  asmDrawn=${SC._asmDrawn} skipSel=${SC._asmSkipSel} note="${SC._asmNote}"`);
console.log(`  wrote ${path.basename(p)}`);
process.exit(0);
