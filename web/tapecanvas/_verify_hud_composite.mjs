// _verify_hud_composite.mjs — HEADLESS PROOF for the Path-A HUD overlay.
// Renders the SAME three layers play_state.html now composites — REAL 3D stage, REAL bodies
// (emitter), and the REAL pvr2 HUD as a TRANSPARENT overlay — and writes one composited PNG.
// Also asserts the HUD is a genuine overlay: it must be MOSTLY transparent (bars/frame only),
// not an opaque black sheet (the old bug), AND the bodies must survive under it.
//   usage: node _verify_hud_composite.mjs <tape.json> <frameIdx> [outName]
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
const OUT   = process.argv[4] || `_hud_composite_f${FRAME}.png`;
const W = 640, H = 480;

function localPath(url){ let p=String(url).split('?')[0]; if(p.startsWith('file://'))p=fileURLToPath(p); return p; }
globalThis.fetch = async (url) => { const p = localPath(url);
  if (!fs.existsSync(p)) { const m=async()=>{throw new Error('404 '+p)}; return {ok:false,status:404,json:m,blob:m,text:m,arrayBuffer:m}; }
  const buf = fs.readFileSync(p);
  return { ok:true, status:200, json:async()=>JSON.parse(buf.toString('utf8')), text:async()=>buf.toString('utf8'),
    blob:async()=>({_png:buf}), arrayBuffer:async()=>buf.buffer.slice(buf.byteOffset, buf.byteOffset+buf.byteLength) }; };
globalThis.createImageBitmap = async (blob) => { const png = PNG.sync.read(blob._png); return { width:png.width, height:png.height, _rgba:new Uint8Array(png.data) }; };
// DOM shim: HudClient uses document.createElement('canvas')+2D ctx for portrait/font atlases.
function mkCanvas(){ let W2=0,H2=0; const ctx={ imageSmoothingEnabled:false,
  drawImage(img,sx,sy,sw,sh,dx,dy,dw,dh){ this._last=img; },
  getImageData(x,y,w,h){ const im=this._srcImg; const data=new Uint8ClampedArray(w*h*4);
    if(im&&im._rgba){ for(let j=0;j<h;j++)for(let i=0;i<w;i++){const si=((y+j)*im.width+(x+i))*4,di=(j*w+i)*4; for(let k=0;k<4;k++)data[di+k]=im._rgba[si+k]||0; } }
    return { data, width:w, height:h }; },
  putImageData(){}, clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){}, closePath(){}, fill(){}, createLinearGradient(){return{addColorStop(){}}} };
  return { get width(){return W2;}, set width(v){W2=v;}, get height(){return H2;}, set height(v){H2=v;}, getContext:()=>ctx, _ctx:ctx }; }
globalThis.document = { createElement: () => mkCanvas() };
globalThis.Image = class { set src(u){ (async()=>{ try{ const p=localPath(u); const png=PNG.sync.read(fs.readFileSync(p)); this.width=png.width; this.height=png.height; this._rgba=new Uint8Array(png.data); this.onload&&this.onload(); }catch(e){ this.onerror&&this.onerror(e);} })(); } };
globalThis.ImageData = class { constructor(d,w,h){ this.data=d; this.width=w; this.height=h; } };
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
const { HudPvr2, renderHudRGBA, buildHudQuads, injectPortraits } = await import(pathToFileURL(path.join(HERE,'renderer','hud-pvr2.mjs')).href);
const { loadTapeJson } = await import(pathToFileURL(path.join(HERE,'tape-adapter.mjs')).href);

const AD = await loadTapeJson(TAPE);
const row = AD.frames[FRAME];

// ── STAGE ──
const stageTex = mkTex();
const stageCanvas = { width:W, height:H, getContext:(t)=>t==='webgpu'?{configure(){},getCurrentTexture:()=>stageTex}:null };
const STAGE = new StageClient(STAGES); STAGE.attachDevice(device);
const stageOk = await STAGE.setStage(AD.stage_id ?? 0);
const stageR = new PVR2Renderer(); stageR.initShared(stageCanvas, device);
if (stageOk && STAGE.ready) { STAGE.setCamB(row[20], row[21]); STAGE.render(stageR); }
await device.queue.onSubmittedWorkDone?.();
const stagePx = await readTex(stageTex);

// ── BODIES + EFFECTS ──
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
SG.render(drawList, {}, null, [], null);
await device.queue.onSubmittedWorkDone?.();
const bodyPx = await readTex(SG.PP && SG.PP.offscreenTex ? SG.PP.offscreenTex : bodyCanvasTex);

// ── HUD (transparent overlay via the real pvr2) ──
const baseQuads = JSON.parse(fs.readFileSync(path.join(HERE,'hud/hud_quads.json'))).quads;
const vmeta = JSON.parse(fs.readFileSync(path.join(HERE,'hud/hud_vram.json')));
const slab = new Uint8Array(fs.readFileSync(path.join(HERE,'hud/hud_vram.bin')));
const pal = new Uint8Array(fs.readFileSync(path.join(HERE,'hud/hud_pal.bin')));
const vram = new Uint8Array(vmeta.vramSize); vram.set(slab, vmeta.base);
const pmeta = JSON.parse(fs.readFileSync(path.join(HERE,'hud/portraits/portraits.json')));
const pimgPng = PNG.sync.read(fs.readFileSync(path.join(HERE,'hud/portraits/portraits.png')));
const pimg = { w:pimgPng.width, h:pimgPng.height, data:pimgPng.data };
const subP=(a,r)=>{const w=r.w,h=r.h,data=new Uint8Array(w*h*4);for(let y=0;y<h;y++)for(let x=0;x<w;x++){const si=((r.y+y)*a.w+(r.x+x))*4,di=(y*w+x)*4;for(let k=0;k<4;k++)data[di+k]=a.data[si+k];}return{w,h,data};};
const portByCid={}; for(const k in pmeta.rects) portByCid[parseInt(k,10)]=subP(pimg,pmeta.rects[k]);
const hstate = AD.buildHudState(FRAME);
injectPortraits(vram, hstate, portByCid);
const hud = new HudPvr2(device, W, H); hud.setVram(vram); hud.setPalette(pal);
const hudQuads = buildHudQuads(baseQuads, hstate, {});
const hudPx = await renderHudRGBA(hud, hudQuads);   // straight-alpha RGBA (un-premultiplied)

// ── composite: bg -> stage -> bodies -> HUD (all straight-alpha over) ──
const out = new Uint8Array(W*H*4);
for (let i=0;i<W*H*4;i+=4){
  let r=0x18,g=0x1a,b=0x20;
  const sa=stagePx[i+3]/255; r=stagePx[i]*sa+r*(1-sa); g=stagePx[i+1]*sa+g*(1-sa); b=stagePx[i+2]*sa+b*(1-sa);
  const ba=bodyPx[i+3]/255;  r=bodyPx[i]*ba +r*(1-ba); g=bodyPx[i+1]*ba +g*(1-ba); b=bodyPx[i+2]*ba +b*(1-ba);
  const ha=hudPx[i+3]/255;   r=hudPx[i]*ha  +r*(1-ha); g=hudPx[i+1]*ha  +g*(1-ha); b=hudPx[i+2]*ha  +b*(1-ha);
  out[i]=r; out[i+1]=g; out[i+2]=b; out[i+3]=255;
}
const png = new PNG({width:W,height:H}); png.data = Buffer.from(out.buffer, out.byteOffset, out.byteLength);
fs.writeFileSync(path.join(HERE, OUT), PNG.sync.write(png));
// HUD layer alone over neutral gray — visual proof it is a sparse transparent overlay (bars/
// frame/portraits only), not the old opaque black sheet.
{ const g=new Uint8Array(W*H*4);
  for(let i=0;i<W*H*4;i+=4){ const a=hudPx[i+3]/255; g[i]=hudPx[i]*a+0x30*(1-a); g[i+1]=hudPx[i+1]*a+0x30*(1-a); g[i+2]=hudPx[i+2]*a+0x30*(1-a); g[i+3]=255; }
  const gp=new PNG({width:W,height:H}); gp.data=Buffer.from(g.buffer,g.byteOffset,g.byteLength);
  fs.writeFileSync(path.join(HERE, OUT.replace(/\.png$/, '_hudlayer.png')), PNG.sync.write(gp)); }

// ── ASSERTIONS: HUD is an overlay, not an opaque sheet; bodies survive under it ──
let hudOpaque=0, hudTrans=0, hudDrawn=0;
for(let i=0;i<W*H*4;i+=4){ const a=hudPx[i+3]; if(a>=250)hudOpaque++; else if(a<=5)hudTrans++; if(a>10)hudDrawn++; }
let bodyN=0; for(let i=0;i<bodyPx.length;i+=4) if(bodyPx[i+3]>0) bodyN++;
// count body pixels that survive into the final composite (not fully overpainted by an opaque HUD)
let bodyVisible=0; for(let i=0;i<W*H*4;i+=4){ if(bodyPx[i+3]>40 && hudPx[i+3]<200) bodyVisible++; }
const tot=W*H;
console.log(`tape=${path.basename(TAPE)} frame=${FRAME} gf=${row[0]} teams p1=${JSON.stringify(AD.p1_team)} p2=${JSON.stringify(AD.p2_team)}`);
console.log(`HUD overlay: drawn=${hudDrawn} (${(100*hudDrawn/tot).toFixed(1)}%) opaque=${hudOpaque} transparent=${hudTrans} (${(100*hudTrans/tot).toFixed(1)}%)`);
console.log(`bodies: total=${bodyN}px · survive-under-HUD=${bodyVisible}px`);
const PASS = hudDrawn>2000 && hudTrans > tot*0.55 && bodyVisible > bodyN*0.9;
console.log(`HUD overlay assertion: ${PASS ? 'PASS' : 'FAIL'} (need HUD drawn>2000, transparent>55%, bodies survive>90%)`);
console.log(`-> ${path.join(HERE, OUT)}`);
process.exit(PASS ? 0 : 1);
