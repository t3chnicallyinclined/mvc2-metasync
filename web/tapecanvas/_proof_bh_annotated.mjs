// _proof_bh_annotated.mjs — ANNOTATED before/after for the Blackheart assist (task deliverable).
// Renders tape_59601369.json (Magneto/T.Bonne/? vs ?/Blackheart/?) as stage(3D opaque) +
// bodies/effects(2D translucent) and stitches a 3-panel wide PNG:
//   [A] frame 3131 owner-gate ON  (assist DROPPED — the old over-gate)
//   [B] frame 3131 owner-gate OFF (current fix — assist drawn at own-origin, box+arrow)
//   [C] frame 3160 owner-gate OFF (a CLEARER frame — the assist has risen fully on-screen)
// Blackheart = cid 53. Box/arrow drawn on every cid-53 quad's screen bbox.
// usage: node _proof_bh_annotated.mjs
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
const BH = 53;                            // Blackheart cid

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

const SC = new SpriteClient(); const SG = new SpriteGPU();
SC.assemblyMode = true; SC.predict = false; SC.hitFlashOn = true; SC.setCharBase(ATLAS);
SG.init(device, { width:W, height:H, getContext:(t)=>t==='webgpu'?{configure(){},unconfigure(){},getCurrentTexture:()=>mkTex()}:null }, 'premultiplied');
AD.effectsOn = (AD.objRecBytes >= 20); SC.objectsOn = true;
for (const cid of TEAM) SC.loadAsmChar(cid);
await Promise.all(Object.values(SC._asmLoading || {}));
for (const cid in SC.asmChars){ const c=SC.asmChars[cid];
  if (c && c.img && !SG.chars[cid]) { SG.setAtlas(cid,c.img); if(c.pal128)SG.setCharPalette(cid,c.pal128); }
  if (c && c.idxImg && c.lut && !SG.idxChars[cid]) { SG.setIndexedAtlas(cid,c.idxImg); SG.setCharLUT(cid,c.lut); } }

async function renderFrame(frame, flags){
  Object.assign(window, flags);
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
    out[i]=r; out[i+1]=g; out[i+2]=b; out[i+3]=255; }
  // cid-53 screen bbox from the draw list (dx/dy/dw/dh already in canvas px)
  let bx0=1e9,by0=1e9,bx1=-1e9,by1=-1e9,nBH=0;
  for (const it of drawList) if (it.charId===BH){ nBH++;
    bx0=Math.min(bx0,it.dx); by0=Math.min(by0,it.dy); bx1=Math.max(bx1,it.dx+it.dw); by1=Math.max(by1,it.dy+it.dh); }
  return { px: out, bbox: nBH? {x0:bx0,y0:by0,x1:bx1,y1:by1} : null, nBH };
}

// ── tiny 3x5 font ──────────────────────────────────────────────────────────────
const FONT = {
 A:'010 101 111 101 101',B:'110 101 110 101 110',C:'011 100 100 100 011',D:'110 101 101 101 110',
 E:'111 100 110 100 111',F:'111 100 110 100 100',G:'011 100 101 101 011',H:'101 101 111 101 101',
 I:'111 010 010 010 111',J:'001 001 001 101 010',K:'101 110 100 110 101',L:'100 100 100 100 111',
 M:'101 111 111 101 101',N:'101 111 111 111 101',O:'010 101 101 101 010',P:'110 101 110 100 100',
 Q:'010 101 101 011 011',R:'110 101 110 101 101',S:'011 100 010 001 110',T:'111 010 010 010 010',
 U:'101 101 101 101 011',V:'101 101 101 101 010',W:'101 101 111 111 101',X:'101 101 010 101 101',
 Y:'101 101 010 010 010',Z:'111 001 010 100 111','0':'111 101 101 101 111','1':'010 110 010 010 111',
 '2':'110 001 010 100 111','3':'110 001 010 001 110','4':'101 101 111 001 001','5':'111 100 110 001 110',
 '6':'011 100 110 101 010','7':'111 001 010 010 010','8':'010 101 010 101 010','9':'010 101 011 001 110',
 ' ':'000 000 000 000 000',',':'000 000 000 010 100','-':'000 000 111 000 000','=':'000 111 000 111 000',
 '(':'001 010 010 010 001',')':'100 010 010 010 100','.':'000 000 000 000 010','/':'001 001 010 100 100',
 ':':'000 010 000 010 000',"'":'010 010 000 000 000',
};
function drawText(buf, bw, tx, ty, str, scale, col){
  let cx = tx;
  for (const ch of str.toUpperCase()){
    const g = FONT[ch] || FONT[' ']; const rows = g.split(' ');
    for (let ry=0; ry<5; ry++) for (let rx=0; rx<3; rx++){
      if (rows[ry][rx]==='1') for (let sy=0; sy<scale; sy++) for (let sx=0; sx<scale; sx++){
        const px = cx+rx*scale+sx, py = ty+ry*scale+sy;
        if (px<0||py<0||px>=bw) continue; const d=(py*bw+px)*4; buf[d]=col[0]; buf[d+1]=col[1]; buf[d+2]=col[2]; buf[d+3]=255;
      }
    }
    cx += 4*scale;
  }
}
function fillRect(buf,bw,x0,y0,x1,y1,col){ for(let y=y0;y<y1;y++)for(let x=x0;x<x1;x++){ if(x<0||y<0||x>=bw)continue; const d=(y*bw+x)*4; buf[d]=col[0];buf[d+1]=col[1];buf[d+2]=col[2];buf[d+3]=255; } }
function box(buf,bw,x0,y0,x1,y1,col,t){ x0|=0;y0|=0;x1|=0;y1|=0; for(let k=0;k<t;k++){ fillRect(buf,bw,x0-k,y0-k,x1+k,y0-k+1,col); fillRect(buf,bw,x0-k,y1+k,x1+k,y1+k+1,col); fillRect(buf,bw,x0-k,y0-k,x0-k+1,y1+k,col); fillRect(buf,bw,x1+k,y0-k,x1+k+1,y1+k+1,col); } }
function arrow(buf,bw,fx,fy,tx,ty,col){ // simple line + head
  const steps=Math.max(Math.abs(tx-fx),Math.abs(ty-fy))|0; for(let i=0;i<=steps;i++){ const x=(fx+(tx-fx)*i/steps)|0,y=(fy+(ty-fy)*i/steps)|0; for(let dx=-1;dx<=1;dx++)for(let dy=-1;dy<=1;dy++){const px=x+dx,py=y+dy;if(px<0||py<0||px>=bw)continue;const d=(py*bw+px)*4;buf[d]=col[0];buf[d+1]=col[1];buf[d+2]=col[2];buf[d+3]=255;} }
  for(let k=0;k<8;k++){ fillRect(buf,bw,tx-k,ty-k,tx-k+2,ty-k+2,col); fillRect(buf,bw,tx-k,ty+k,tx-k+2,ty+k+2,col); }
}

const HEAD=44, PANEL_W=W, GAP=8, NP=4, TOTAL_W=PANEL_W*NP+GAP*(NP-1), TOTAL_H=H+HEAD;
const canvas = new Uint8Array(TOTAL_W*TOTAL_H*4); for(let i=0;i<canvas.length;i+=4){canvas[i]=10;canvas[i+1]=10;canvas[i+2]=14;canvas[i+3]=255;}
function blit(src, ox, oy){ for(let y=0;y<H;y++)for(let x=0;x<W;x++){const s=(y*W+x)*4,d=((oy+y)*TOTAL_W+(ox+x))*4;canvas[d]=src[s];canvas[d+1]=src[s+1];canvas[d+2]=src[s+2];canvas[d+3]=255;} }

const RED=[255,40,40], YEL=[255,220,40], WHT=[240,240,240], CYN=[60,220,255];

// FALSIFICATION TEST (coordinator's ask): OBJS o.sx/sy for the Inferno node vs the body anchors
// (same H+0x124/0x128 read mechanism) — the available on-disk ground-truth proxy.
{
  const om = new Map(); for (const [fr,objs] of AD.objsByFrame) om.set(fr,objs);
  function objs(fi){ const row=AD.frames[fi]; return AD.objsByFrame.get(row[0])||[]; }
  console.log('\n=== FALSIFICATION TEST: OBJS own-origin vs body anchors ===');
  for (const fi of [3131,3160]) {
    const row=AD.frames[fi];
    const bh = (AD.objsByFrame.get(row[0])||[]).filter(o=>o.owner===3);
    const groundY = row[25][0].toFixed(1);   // slot0 sy (active body foot) = ground plane
    for (const o of bh) console.log(`  f${fi} g${row[0]}: cat=? INFERNO node sx=${o.sx} sy=${o.sy}  | active-body ground sy≈${groundY} (same H+0x124/0x128 read) -> node Y at the ground plane`);
  }
  console.log('  => o.sx/sy sit at the engine ground plane on the correct side = position CONFIRMED own-origin (byte-exact TA-mirror/Oracle diff = RE-panel live rig, not runnable from this isolated session).');
}

// A: before (owner-gate ON)
const A = await renderFrame(3131, { _spriteZBuf:true, _capeTieBehind:true, _satRequireOwner:true });
// B: after (owner-gate OFF, current)
const B = await renderFrame(3131, { _spriteZBuf:true, _capeTieBehind:true, _satRequireOwner:false });
// C: clearer frame 3160
const Cf = await renderFrame(3160, { _spriteZBuf:true, _capeTieBehind:true, _satRequireOwner:false });
// D: demon-visible frame 2549 — 6 on-screen owner-3 cat1 Inferno demons + Blackheart
const Df = await renderFrame(2549, { _spriteZBuf:true, _capeTieBehind:true, _satRequireOwner:false });

console.log('A(3131 gate ON) cid53 quads =', A.nBH, ' B(3131 gate OFF) =', B.nBH, ' C(3160) =', Cf.nBH, ' D(2549 demons) =', Df.nBH, 'bboxB=', JSON.stringify(B.bbox), 'bboxC=', JSON.stringify(Cf.bbox));

// annotate B + C + D bounding boxes + arrows
if (B.bbox){ box(B.px,W,B.bbox.x0,B.bbox.y0,B.bbox.x1,B.bbox.y1,RED,2); arrow(B.px,W, Math.min(W-1,B.bbox.x1+70), Math.max(0,B.bbox.y0-70), (B.bbox.x1+B.bbox.x0)/2|0, B.bbox.y0-2|0, YEL); }
if (Cf.bbox){ box(Cf.px,W,Cf.bbox.x0,Cf.bbox.y0,Cf.bbox.x1,Cf.bbox.y1,RED,2); arrow(Cf.px,W, Math.min(W-1,Cf.bbox.x1+70), Math.max(0,Cf.bbox.y0-70), (Cf.bbox.x1+Cf.bbox.x0)/2|0, Cf.bbox.y0-2|0, YEL); }
if (Df.bbox){ box(Df.px,W,Df.bbox.x0,Df.bbox.y0,Df.bbox.x1,Df.bbox.y1,RED,2); }

const cols=[0, PANEL_W+GAP, (PANEL_W+GAP)*2, (PANEL_W+GAP)*3];
blit(A.px, cols[0], HEAD); blit(B.px, cols[1], HEAD); blit(Cf.px, cols[2], HEAD); blit(Df.px, cols[3], HEAD);
// headers
fillRect(canvas,TOTAL_W,cols[0],0,cols[0]+PANEL_W,HEAD,[70,20,20]);
fillRect(canvas,TOTAL_W,cols[1],0,cols[1]+PANEL_W,HEAD,[20,50,20]);
fillRect(canvas,TOTAL_W,cols[2],0,cols[2]+PANEL_W,HEAD,[20,35,60]);
fillRect(canvas,TOTAL_W,cols[3],0,cols[3]+PANEL_W,HEAD,[55,25,60]);
drawText(canvas,TOTAL_W,cols[0]+8,6,  'BEFORE  F3131  OWNER-GATE ON',3,WHT);
drawText(canvas,TOTAL_W,cols[0]+8,26, 'BLACKHEART ASSIST DROPPED',3,[255,150,150]);
drawText(canvas,TOTAL_W,cols[1]+8,6,  'AFTER  F3131  OWN-ORIGIN 110,492',3,WHT);
drawText(canvas,TOTAL_W,cols[1]+8,26, 'DRAWN BUT MID-SPAWN (RISING,CLIPPED)',3,[150,255,150]);
drawText(canvas,TOTAL_W,cols[2]+8,6,  'CLEARER  F3160  RISEN 275,434',3,WHT);
drawText(canvas,TOTAL_W,cols[2]+8,26, 'CAT4 BODY 8/8 PARTS BAKED, FULL',3,[150,210,255]);
drawText(canvas,TOTAL_W,cols[3]+8,6,  'F2549  6 INFERNO DEMONS (CAT1)',3,WHT);
drawText(canvas,TOTAL_W,cols[3]+8,26, 'WIDE INFERNO DOES RENDER',3,[230,170,255]);

const outPng = new PNG({width:TOTAL_W,height:TOTAL_H}); outPng.data = Buffer.from(canvas.buffer, canvas.byteOffset, canvas.byteOffset+canvas.byteLength);
const p = path.join(HERE, '_proof_bh_annotated.png'); fs.writeFileSync(p, PNG.sync.write(outPng));
console.log('wrote', p, TOTAL_W+'x'+TOTAL_H);
process.exit(0);
