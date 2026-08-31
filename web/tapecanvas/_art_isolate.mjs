// _art_isolate.mjs — isolate the pink/magenta blocky artifact: render STAGE-only and
// BODY/EFFECT-only layers to SEPARATE pngs (transparent shown on a neutral gray) so we can
// see which layer carries the artifact. Also dumps OBJDIAG (each effect/sat object's anchor).
//   usage: node _art_isolate.mjs <tape.json> <frameIdx> [tag]
import fs from 'node:fs'; import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url'; import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const HERE  = path.dirname(fileURLToPath(import.meta.url));
const MAPLE = 'C:/Users/trist/projects/maplecast-flycast';
const POC   = path.join(MAPLE, 'tools/render-replica-poc');
const PNG   = require(path.join(POC, 'node_modules/pngjs/lib/png.js')).PNG;
const ATLAS = path.join(MAPLE, 'web/test-atlas/chars');
const STAGES = path.join(HERE, 'stages');
const TAPE  = path.resolve(process.argv[2] || path.join(HERE, 'tape_59601369.json'));
const FRAME = +(process.argv[3] || 870);
const TAG   = process.argv[4] || `f${FRAME}`;
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
window._objDiag = true;   // dump OBJDIAG anchor lines

const { initDevice } = await import(pathToFileURL(path.join(POC,'webgpu-headless.mjs')).href);
const { device } = await initDevice();
try { navigator.gpu.getPreferredCanvasFormat = () => 'rgba8unorm'; } catch(_) {}
device.queue.copyExternalImageToTexture = (src,dst,size) => { const [w,h]=size; device.queue.writeTexture({texture:dst.texture}, src.source._rgba, {bytesPerRow:w*4,rowsPerImage:h}, [w,h,1]); };

function mkTex(){ return device.createTexture({size:[W,H],format:'rgba8unorm',usage:GPUTextureUsage.RENDER_ATTACHMENT|GPUTextureUsage.COPY_SRC|GPUTextureUsage.TEXTURE_BINDING}); }
async function readTex(tex){ const bpr=Math.ceil(W*4/256)*256; const rb=device.createBuffer({size:bpr*H,usage:GPUBufferUsage.COPY_DST|GPUBufferUsage.MAP_READ});
  const e=device.createCommandEncoder(); e.copyTextureToBuffer({texture:tex},{buffer:rb,bytesPerRow:bpr,rowsPerImage:H},[W,H,1]); device.queue.submit([e.finish()]);
  await rb.mapAsync(GPUMapMode.READ); const m=new Uint8Array(rb.getMappedRange()).slice(); rb.unmap();
  const o=new Uint8Array(W*H*4); for(let y=0;y<H;y++)for(let x=0;x<W;x++){const s=y*bpr+x*4,d=(y*W+x)*4;o[d]=m[s];o[d+1]=m[s+1];o[d+2]=m[s+2];o[d+3]=m[s+3];} return o; }
function writeLayer(px, name){ // transparent -> gray #303030 so drawn pixels stand out
  const out=new Uint8Array(W*H*4);
  for(let i=0;i<W*H*4;i+=4){ const a=px[i+3]/255; out[i]=px[i]*a+0x30*(1-a); out[i+1]=px[i+1]*a+0x30*(1-a); out[i+2]=px[i+2]*a+0x30*(1-a); out[i+3]=255; }
  const png=new PNG({width:W,height:H}); png.data=Buffer.from(out.buffer,out.byteOffset,out.byteLength);
  const p=path.join(HERE,name); fs.writeFileSync(p,PNG.sync.write(png)); return p;
}

const { StageClient }  = await import(pathToFileURL(path.join(HERE,'renderer','stage-client.mjs')).href);
const { PVR2Renderer } = await import(pathToFileURL(path.join(HERE,'renderer','pvr2-renderer.mjs')).href);
const { SpriteClient } = await import(pathToFileURL(path.join(HERE,'renderer','sprite-client.mjs')).href);
const { SpriteGPU }    = await import(pathToFileURL(path.join(HERE,'renderer','sprite-gpu.mjs')).href);
const { loadTapeJson } = await import(pathToFileURL(path.join(HERE,'tape-adapter.mjs')).href);

const AD = await loadTapeJson(TAPE);
const row = AD.frames[FRAME];

// STAGE only
const stageTex = mkTex();
const stageCanvas = { width:W, height:H, getContext:(t)=>t==='webgpu'?{configure(){},getCurrentTexture:()=>stageTex}:null };
const STAGE = new StageClient(STAGES); STAGE.attachDevice(device);
const stageOk = await STAGE.setStage(AD.stage_id ?? 0);
const stageR = new PVR2Renderer(); stageR.initShared(stageCanvas, device);
if (stageOk && STAGE.ready) { STAGE.setCamB(row[20], row[21]); STAGE.render(stageR); }
await device.queue.onSubmittedWorkDone?.();
const stagePx = await readTex(stageTex);
writeLayer(stagePx, `_art_${TAG}_stage.png`);

// BODIES + EFFECTS only
const bodyCanvasTex = mkTex();
const bodyCanvas = { width:W, height:H, getContext:(t)=>t==='webgpu'?{configure(){},unconfigure(){},getCurrentTexture:()=>bodyCanvasTex}:null };
const SC = new SpriteClient(); const SG = new SpriteGPU();
SC.assemblyMode = true; SC.predict = false; SC.hitFlashOn = true; SC.setCharBase(ATLAS);
SG.init(device, bodyCanvas, 'premultiplied');
AD.effectsOn = AD.objRecBytes >= 20; SC.objectsOn = AD.effectsOn;
AD.applyFrame(SC, FRAME, { load:(sc,cid)=>sc.loadAsmChar(cid) });
await Promise.all(Object.values(SC._asmLoading || {}));
AD.applyFrame(SC, FRAME, { load:(sc,cid)=>sc.loadAsmChar(cid) });
await Promise.all(Object.values(SC._asmLoading || {}));
for (const cid in SC.asmChars){ const c=SC.asmChars[cid];
  if (c && c.img && !SG.chars[cid]) { SG.setAtlas(cid,c.img); if(c.pal128)SG.setCharPalette(cid,c.pal128); }
  if (c && c.idxImg && c.lut && !SG.idxChars[cid]) { SG.setIndexedAtlas(cid,c.idxImg); SG.setCharLUT(cid,c.lut); } }
const drawList = SC.buildAssemblyDrawList(W,H);
console.log('=== OBJECTS (sc.objects) ===');
for(const o of SC.objects) console.log(`  cid=${o.cid} PL${(o.cid).toString(16).padStart(2,'0').toUpperCase()} sid=0x${(o.sid&0xffff).toString(16)} type=${o.type} scr=(${o.x|0},${o.y|0}) xflip=${o.xflip} add=${!!o.additive} gfx1=0x${(o.gfx1>>>0).toString(16)} owner=${o.owner}`);
SG.render(drawList, {}, null, [], null);
await device.queue.onSubmittedWorkDone?.();
const bodyPx = await readTex(SG.PP && SG.PP.offscreenTex ? SG.PP.offscreenTex : bodyCanvasTex);
writeLayer(bodyPx, `_art_${TAG}_body.png`);

console.log(`tape=${path.basename(TAPE)} frame=${FRAME} gf=${row[0]} cam=(${row[20].toFixed(1)},${row[21].toFixed(1)})`);
console.log(`wrote _art_${TAG}_stage.png + _art_${TAG}_body.png`);
process.exit(0);
