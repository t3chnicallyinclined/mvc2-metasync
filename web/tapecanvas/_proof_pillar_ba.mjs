// _proof_pillar_ba.mjs — BEFORE/AFTER for the Blackheart Inferno effect-wire (blend) fix.
// Renders tape_59601369.json at the Inferno frames as stage(3D opaque) + bodies/effects(2D)
// and stitches a wide PNG:
//   [A] frame idx 721  window._fxAdditive=false  (BEFORE — effects render dim MODE-2 alpha)
//   [B] frame idx 721  window._fxAdditive=true   (AFTER  — effects render bright additive)
//   [C] frame idx 716  BEFORE
//   [D] frame idx 716  AFTER
// The fix: tape-adapter effectBlendByte() + the sprite-client additive-branch pipe (0x1->0x11).
// usage: node _proof_pillar_ba.mjs [outfile]
import fs from 'node:fs'; import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url'; import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const MAPLE = 'C:/Users/trist/projects/maplecast-flycast';
const POC = path.join(MAPLE, 'tools/render-replica-poc');
const PNG = require(path.join(POC, 'node_modules/pngjs/lib/png.js')).PNG;
const ATLAS = path.join(MAPLE, 'web/test-atlas/chars');
const STAGES = path.join(HERE, 'stages');
const OUT = process.argv[2] || path.join(HERE, '_proof_pillar_ba.png');
const W = 640, H = 480;
const FRAMES = process.argv[3] ? process.argv[3].split(',').map(Number) : [721, 716];

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
const TEAM = [AD.p1_team[0],AD.p2_team[0],AD.p1_team[1],AD.p2_team[1],AD.p1_team[2],AD.p2_team[2]];

const SC = new SpriteClient(); const SG = new SpriteGPU();
SC.assemblyMode = true; SC.predict = false; SC.hitFlashOn = true; SC.setCharBase(ATLAS);
SG.init(device, { width:W, height:H, getContext:(t)=>t==='webgpu'?{configure(){},unconfigure(){},getCurrentTexture:()=>mkTex()}:null }, 'premultiplied');
AD.effectsOn = (AD.objRecBytes >= 20); SC.objectsOn = true;
for (const cid of TEAM) SC.loadAsmChar(cid);
await Promise.all(Object.values(SC._asmLoading || {}));
for (const cid in SC.asmChars){ const c=SC.asmChars[cid];
  if (c && c.img && !SG.chars[cid]) { SG.setAtlas(cid,c.img); if(c.pal128)SG.setCharPalette(cid,c.pal128); }
  if (c && c.idxImg && c.lut && !SG.idxChars[cid]) { SG.setIndexedAtlas(cid,c.idxImg); SG.setCharLUT(cid,c.lut); } }

async function renderFrame(frame, additive, ownerlessTo){
  window._fxAdditive = additive;
  window._fxOwnerlessTo = (ownerlessTo != null) ? ownerlessTo : null;
  const row = AD.frames[frame];
  const stageTex = mkTex();
  const stageCanvas = { width:W, height:H, getContext:(t)=>t==='webgpu'?{configure(){},getCurrentTexture:()=>stageTex}:null };
  const STAGE = new StageClient(STAGES); STAGE.attachDevice(device); await STAGE.setStage(AD.stage_id ?? 0);
  STAGE.setCamB(row[20], row[21]);
  const stageR = new PVR2Renderer(); stageR.initShared(stageCanvas, device); STAGE.render(stageR);
  await device.queue.onSubmittedWorkDone?.();
  const stagePx = await readTex(stageTex);
  AD.applyFrame(SC, frame, { load:(sc,cid)=>sc.loadAsmChar(cid) });
  await Promise.all(Object.values(SC._asmLoading || {}));
  const drawList = SC.buildAssemblyDrawList(W,H);
  SG.render(drawList, {}, null, [], null);
  await device.queue.onSubmittedWorkDone?.();
  const bodyPx = await readTex(SG.PP.offscreenTex);
  const out = new Uint8Array(W*H*4);
  for (let i=0;i<W*H*4;i+=4){ let r=0x18,g=0x1a,b=0x20;
    const sa=stagePx[i+3]/255; r=stagePx[i]*sa+r*(1-sa); g=stagePx[i+1]*sa+g*(1-sa); b=stagePx[i+2]*sa+b*(1-sa);
    const ba=bodyPx[i+3]/255;  r=bodyPx[i]*ba+r*(1-ba); g=bodyPx[i+1]*ba+g*(1-ba); b=bodyPx[i+2]*ba+b*(1-ba);
    out[i]=Math.min(255,r); out[i+1]=Math.min(255,g); out[i+2]=Math.min(255,b); out[i+3]=255; }
  const diag = AD._lastObjs;
  return { px: out, diag };
}

// tiny font for labels
const FONT={A:'010 101 111 101 101',B:'110 101 110 101 110',C:'011 100 100 100 011',D:'110 101 101 101 110',E:'111 100 110 100 111',F:'111 100 110 100 100',G:'011 100 101 101 011',H:'101 101 111 101 101',I:'111 010 010 010 111',L:'100 100 100 100 111',N:'101 111 111 111 101',O:'010 101 101 101 010',P:'110 101 110 100 100',R:'110 101 110 101 101',S:'011 100 010 001 110',T:'111 010 010 010 010',U:'101 101 101 101 011',V:'101 101 101 101 010',W:'101 101 111 111 101',X:'101 101 010 101 101',Y:'101 101 010 010 010',' ':'000 000 000 000 000','0':'111 101 101 101 111','1':'010 110 010 010 111','2':'110 001 010 100 111','3':'110 001 010 001 110','4':'101 101 111 001 001','5':'111 100 110 001 110','6':'011 100 110 101 010','7':'111 001 010 010 010','8':'010 101 010 101 010','9':'010 101 011 001 110',':':'000 010 000 010 000','=':'000 111 000 111 000','(':'001 010 010 010 001',')':'100 010 010 010 100','-':'000 000 111 000 000','.':'000 000 000 000 010'};
function drawText(buf,bw,tx,ty,str,scale,col){ let cx=tx; for(const ch of str.toUpperCase()){ const g=FONT[ch]||FONT[' ']; const rows=g.split(' '); for(let ry=0;ry<5;ry++)for(let rx=0;rx<3;rx++){ if(rows[ry][rx]==='1')for(let sy=0;sy<scale;sy++)for(let sx=0;sx<scale;sx++){ const px=cx+rx*scale+sx,py=ty+ry*scale+sy; if(px<0||py<0||px>=bw)continue; const d=(py*bw+px)*4; buf[d]=col[0];buf[d+1]=col[1];buf[d+2]=col[2];buf[d+3]=255; } } cx+=4*scale; } }

const HEAD=40, NP=4, TOTAL_W=W*NP+8*(NP-1), TOTAL_H=H+HEAD;
const canvas=new Uint8Array(TOTAL_W*TOTAL_H*4); for(let i=0;i<canvas.length;i+=4){canvas[i]=10;canvas[i+1]=10;canvas[i+2]=14;canvas[i+3]=255;}
function blit(src,ox,oy){ for(let y=0;y<H;y++)for(let x=0;x<W;x++){const s=(y*W+x)*4,d=((oy+y)*TOTAL_W+(ox+x))*4;canvas[d]=src[s];canvas[d+1]=src[s+1];canvas[d+2]=src[s+2];canvas[d+3]=255;} }

// BH cid for the ownerless-attribution proof panel (the AFTER column previews the demon nodes
// the reader-shipped owner will render). Detect Blackheart (53) in the roster; else no attr.
const OWNTO = TEAM.includes(53) ? 53 : null;
const panels=[];
for(const fr of FRAMES){
  panels.push({ fr, tag:'BEFORE ALPHA',    add:false, ...(await renderFrame(fr,false,null)) });
  panels.push({ fr, tag:'AFTER ADDITIVE',  add:true,  ...(await renderFrame(fr,true, OWNTO)) });
}
const RED=[255,90,90],GRN=[120,255,120];
panels.forEach((p,i)=>{ const ox=i*(W+8);
  blit(p.px, ox, HEAD);
  drawText(canvas,TOTAL_W, ox+8, 6, `IDX ${p.fr} ${p.tag}`, 3, p.add?GRN:RED);
  drawText(canvas,TOTAL_W, ox+8, 24, `FX ${p.diag.drawn} ADD ${p.diag.additive} DEFER ${p.diag.ownerless}`, 2, [200,200,210]);
});
const png=new PNG({width:TOTAL_W,height:TOTAL_H}); png.data=Buffer.from(canvas.buffer); fs.writeFileSync(OUT, PNG.sync.write(png));
console.log('wrote', OUT, `(${TOTAL_W}x${TOTAL_H})`);
for(const p of panels) console.log(`  idx ${p.fr} additive=${p.add}: drawn=${p.diag.drawn} additive=${p.diag.additive} deferred=${p.diag.ownerless}`);
process.exit(0);
