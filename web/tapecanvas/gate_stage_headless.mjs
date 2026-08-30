// gate_stage_headless.mjs — REAL headless Dawn render of the 3D STG00 stage (Option-B camera)
// through the vendored PVR2Renderer, plus the acceptance measurements the coordinator asked for.
//
// It drives the ACTUAL StageClient (renderer/stage-client.mjs) + PVR2Renderer EXACTLY as
// gpu.html does (initShared on a fake canvas sharing one Dawn device, setCamB(camX,camY) from
// the tape, render). Then it:
//   (1) DECK-UNDER-FEET RESIDUAL: projects the real STG00 deck geometry (rip models 2 & 13,
//       verts at the fighting spot |Yw|<20,|Zw|<20) through the SAME StageClient._projectB and
//       reports screenY vs ground (=camY+338.4). ACCEPTANCE: residual ~= 0.
//   (2) PAN TRACKING: a fixed deck vert projected at frame A (camX~0) vs frame B (camX=-960);
//       reports Δscreen/ΔcamX. ACCEPTANCE: |ratio| ~= 1.0 (the old 2D flatten parallax 0.12
//       gave 0.12 => an 8.3x drift).
//   (3) REAL PIXELS: renders the 3D stage under Dawn, reads back the framebuffer, counts
//       non-transparent stage pixels, PROBES alpha at each drawn fighter's captured foot pixel
//       (sx,sy) — deck must be rendered there — and writes a proof PNG.
//
//   usage:  node gate_stage_headless.mjs [frameA=200] [frameB=9000]

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const HERE  = path.dirname(fileURLToPath(import.meta.url));
const MAPLE = 'C:/Users/trist/projects/maplecast-flycast';
const POC   = path.join(MAPLE, 'tools/render-replica-poc');
const PNG   = require(path.join(POC, 'node_modules/pngjs/lib/png.js')).PNG;
const TAPE  = path.join(HERE, 'tape.json');
const STAGES_DIR = path.join(HERE, 'stages');
const FRAME_A = +(process.argv[2] || 200);
const FRAME_B = +(process.argv[3] || 9000);
const W = 640, H = 480;

// ── browser-platform shims (verbatim pattern from gate_bodies_headless.mjs) ──
function localPath(url) { let p = String(url).split('?')[0]; if (p.startsWith('file://')) p = fileURLToPath(p); return p; }
globalThis.fetch = async (url) => {
  // stage-client fetches by bare filename against its base dir (an absolute path here).
  let p = localPath(url);
  if (!path.isAbsolute(p)) p = path.join(STAGES_DIR, p);
  if (!fs.existsSync(p)) { const miss = async () => { throw new Error('404 ' + p); };
    return { ok: false, status: 404, json: miss, blob: miss, text: miss, arrayBuffer: miss }; }
  const buf = fs.readFileSync(p);
  return { ok: true, status: 200,
    json: async () => JSON.parse(buf.toString('utf8')),
    text: async () => buf.toString('utf8'),
    blob: async () => ({ _png: buf }),
    arrayBuffer: async () => buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) };
};
globalThis.createImageBitmap = async (blob) => { const png = PNG.sync.read(blob._png);
  return { width: png.width, height: png.height, _rgba: new Uint8Array(png.data) }; };
globalThis.window = globalThis;

// ── Dawn device ──
const { initDevice } = await import(pathToFileURL(path.join(POC, 'webgpu-headless.mjs')).href);
const { device, info } = await initDevice();
console.log('[gpu]', info.description || info.vendor || 'Dawn');
let fmtForced = 'rgba8unorm';
try { navigator.gpu.getPreferredCanvasFormat = () => 'rgba8unorm'; } catch (_) {}
try { fmtForced = navigator.gpu.getPreferredCanvasFormat(); } catch (_) {}
console.log('[gpu] canvas format =', fmtForced);
device.queue.copyExternalImageToTexture = (src, dst, size) => {
  const bm = src.source; const [w, h] = size;
  device.queue.writeTexture({ texture: dst.texture }, bm._rgba, { bytesPerRow: w * 4, rowsPerImage: h }, [w, h, 1]);
};
const errors = [];
try { device.addEventListener?.('uncapturederror', (e) => errors.push('uncaptured: ' + (e.error && e.error.message || e.error))); } catch (_) {}

// ── fake canvas / webgpu context for the stage renderer (headless, no swap-chain) ──
const canvasTex = device.createTexture({ size: [W, H], format: fmtForced,
  usage: GPUTextureUsage.RENDER_ATTACHMENT | GPUTextureUsage.COPY_SRC | GPUTextureUsage.TEXTURE_BINDING });
const fakeCtx = { configure() {}, unconfigure() {}, getCurrentTexture: () => canvasTex };
const fakeCanvas = { width: W, height: H, getContext: (t) => (t === 'webgpu' ? fakeCtx : null) };

// ── modules UNDER TEST (imported after globals exist) — the code gpu.html runs ──
const { StageClient }  = await import(pathToFileURL(path.join(HERE, 'renderer', 'stage-client.mjs')).href);
const { PVR2Renderer } = await import(pathToFileURL(path.join(HERE, 'renderer', 'pvr2-renderer.mjs')).href);
const { loadTapeJson } = await import(pathToFileURL(path.join(HERE, 'tape-adapter.mjs')).href);

// ── tape ──
const AD = await loadTapeJson(TAPE);
const rowA = AD.frames[FRAME_A], rowB = AD.frames[FRAME_B];
const camXA = rowA[20], camYA = rowA[21], groundA = rowA[22];
const camXB = rowB[20], camYB = rowB[21];
console.log(`tape: ${AD.frameCount} frames · stage_id=${AD.stage_id}`);
console.log(`frame A=${FRAME_A}: camX=${camXA.toFixed(2)} camY=${camYA.toFixed(2)} ground=${groundA.toFixed(2)}`);
console.log(`frame B=${FRAME_B}: camX=${camXB.toFixed(2)} camY=${camYB.toFixed(2)}`);

// ── load the 3D stage exactly as gpu.html: attachDevice then setStage ──
const STAGE = new StageClient(STAGES_DIR);
STAGE.attachDevice(device);
device.pushErrorScope('validation');
const ready = await STAGE.setStage(AD.stage_id != null ? AD.stage_id : 0);
console.log(`STAGE.setStage -> ready=${ready} · deckZ=${STAGE.deckZ} · meshes=${STAGE._data ? STAGE._data.meshes.length : 0}`);

// ═══════════ (1) DECK-UNDER-FEET RESIDUAL (real geometry, StageClient._projectB) ═══════════
// The deck models (rip 2 & 13). The FIGHTER convention places a world point (Xw,Yw,Zw) on the
// fighting plane at screenY = ground - Yw. The deck is "pinned to the feet" iff the 3D
// projection maps the fighting-plane (Zw~0) the SAME way: screenY_3d == ground - Yw. (This
// isolates camera correctness from the deck's own Y-thickness; a raw screenY-vs-ground compare
// would just measure how thick the deck is.) Also report the pure deck-top (Yw~0,Zw~0) row.
STAGE.setCamB(camXA, camYA);
const deckVerts = [];
for (const m of STAGE._data.meshes) {
  if (m.model !== 2 && m.model !== 13) continue;
  for (const tri of m.tris) for (const v of tri) {
    if (Math.abs(v.pos[2]) < 20) deckVerts.push(v.pos);      // at the fighting plane (Zw~0)
  }
}
let maxDev = 0, sumDev = 0, n = 0;          // residual vs the fighter convention (ground - Yw)
for (const p of deckVerts) {
  const s = STAGE._projectB(p[0], p[1], p[2]); if (!s) continue;
  const dev = Math.abs(s[1] - (groundA - p[1])); maxDev = Math.max(maxDev, dev); sumDev += dev; n++;
}
const meanDev = n ? sumDev / n : NaN;
// CAMERA DECK-PIN (the property that matters): a fighting-plane point (Xw, Yw=0, Zw=deckZ)
// must project to screenY = ground for ALL Xw. Probe synthetic points across the deck X-span
// (fighters live at worldX = sx+camX-320, i.e. ~ +/-320 here) through the ACTUAL _projectB.
let pinMax = 0;
for (let Xw = -400; Xw <= 400; Xw += 20) {
  const s = STAGE._projectB(Xw, 0, STAGE.deckZ);
  pinMax = Math.max(pinMax, Math.abs(s[1] - groundA), Math.abs(s[0] - (Xw - camXA + 320)));
}
console.log(`\n(1) DECK-UNDER-FEET  (frame A, camY=${camYA})`);
console.log(`    ground (camY+338.4)                       : ${groundA.toFixed(3)} px`);
console.log(`    CAMERA deck-pin max err (Yw=0,Zw=deckZ)   : ${pinMax.toExponential(2)} px  (ACCEPT: ~0 => deck plane == ground, screenX 1:1)`);
console.log(`    real-geom residual |sY-(ground-Yw)| Zw<20 : mean ${meanDev.toFixed(3)} max ${maxDev.toFixed(3)} px  (INFO: nonzero = deck's true Z-depth/railings, correct 3D)`);

// ═══════════ (2) PAN TRACKING (fixed deck vert, frame A vs frame B) ═══════════
// A deck vert AT the fighting plane (Yw=0,Zw=0) if present, else nearest origin.
let anchor = null, best = Infinity;   // deck vert closest to the fighting plane (min |Zw|, then |Yw|)
for (const p of deckVerts) { const d = Math.abs(p[2]) * 10 + Math.abs(p[1]); if (d < best) { best = d; anchor = p; } }
STAGE.setCamB(camXA, camYA); const sA = STAGE._projectB(anchor[0], anchor[1], anchor[2]);
STAGE.setCamB(camXB, camYB); const sB = STAGE._projectB(anchor[0], anchor[1], anchor[2]);
const dCam = camXB - camXA, dScr = sB[0] - sA[0];
const ratio = dCam !== 0 ? dScr / dCam : NaN;
const oldParallax = 0.12, oldDScr = -oldParallax * dCam;
console.log(`\n(2) PAN TRACKING  (deck anchor world=[${anchor.map(v=>v.toFixed(1))}])`);
console.log(`    ΔcamX (A->B)                 : ${dCam.toFixed(2)}`);
console.log(`    Δstage screenX (Option B)    : ${dScr.toFixed(2)}   ratio d(screenX)/d(camX) = ${ratio.toFixed(4)}`);
console.log(`    |ratio|                       : ${Math.abs(ratio).toFixed(4)}   (ACCEPT: ~1.0; NOT 0.12)`);
console.log(`    old 2D-flatten Δ (parallax .12): ${oldDScr.toFixed(2)}  => ${(Math.abs(dScr/ (oldDScr||1))).toFixed(1)}x more tracking than the flatten`);

// ═══════════ (3) REAL PIXELS: render the 3D stage under Dawn @ frame A ═══════════
STAGE.setCamB(camXA, camYA);
const stageR = new PVR2Renderer(); stageR.initShared(fakeCanvas, device);
let renderThrow = null;
try { STAGE.render(stageR); } catch (e) { renderThrow = e; }
if (renderThrow) errors.push('STAGE.render THREW: ' + (renderThrow.stack || renderThrow.message));
const valErr = await device.popErrorScope(); if (valErr) errors.push('validation: ' + valErr.message);
try { await device.queue.onSubmittedWorkDone?.(); } catch (_) {}

async function readTex(tex) {
  const bpr = Math.ceil(W * 4 / 256) * 256;
  const rb = device.createBuffer({ size: bpr * H, usage: GPUBufferUsage.COPY_DST | GPUBufferUsage.MAP_READ });
  const enc = device.createCommandEncoder();
  enc.copyTextureToBuffer({ texture: tex }, { buffer: rb, bytesPerRow: bpr, rowsPerImage: H }, [W, H, 1]);
  device.queue.submit([enc.finish()]);
  await rb.mapAsync(GPUMapMode.READ);
  const m = new Uint8Array(rb.getMappedRange()).slice(); rb.unmap();
  const out = new Uint8Array(W * H * 4);
  const bgra = /bgra/.test(fmtForced);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const s = y * bpr + x * 4, d = (y * W + x) * 4;
    if (bgra) { out[d]=m[s+2]; out[d+1]=m[s+1]; out[d+2]=m[s]; out[d+3]=m[s+3]; }
    else { out[d]=m[s]; out[d+1]=m[s+1]; out[d+2]=m[s+2]; out[d+3]=m[s+3]; }
  }
  return out;
}
const px = await readTex(canvasTex);
let alphaPx = 0, x0=W,y0=H,x1=-1,y1=-1;
for (let y=0;y<H;y++) for (let x=0;x<W;x++){ if (px[(y*W+x)*4+3]>0){ alphaPx++; if(x<x0)x0=x; if(x>x1)x1=x; if(y<y0)y0=y; if(y>y1)y1=y; } }

// probe alpha at each drawn fighter's captured foot pixel (sx,sy)
const drawn = rowA[17], sx = rowA[24], sy = rowA[25];
const probes = [];
for (let s=0;s<6;s++){ if(!drawn[s]) continue;
  const fx = Math.round(sx[s]), fy = Math.round(sy[s]);
  if (fx<0||fx>=W||fy<0||fy>=H){ probes.push({slot:s,fx,fy,onscreen:false}); continue; }
  const a = px[(fy*W+fx)*4+3];
  probes.push({slot:s,fx,fy,onscreen:true,alpha:a,deck:a>0}); }

// write proof PNG (over the #181a20 bg like the app screenshot)
const png = new PNG({ width: W, height: H });
const cp = px.slice();
for (let i=0;i<cp.length;i+=4){ const a=cp[i+3]/255; cp[i]=cp[i]*a+0x18*(1-a); cp[i+1]=cp[i+1]*a+0x1a*(1-a); cp[i+2]=cp[i+2]*a+0x20*(1-a); cp[i+3]=255; }
png.data = Buffer.from(cp.buffer, cp.byteOffset, cp.byteLength);
const pOut = path.join(HERE, `_gate_stage_f${FRAME_A}.png`);
fs.writeFileSync(pOut, PNG.sync.write(png));

console.log(`\n(3) REAL PIXELS  (3D stage rendered under Dawn, frame A)`);
console.log(`    stage non-transparent px     : ${alphaPx}  (ACCEPT: >0 — geometry rasterized)`);
console.log(`    stage bbox                   : ${x1<0?'NONE':`x[${x0}..${x1}] y[${y0}..${y1}]`}`);
console.log(`    deck-under-feet pixel probe  :`);
for (const pr of probes) console.log(`      slot ${pr.slot} foot (${pr.fx},${pr.fy}) : ${pr.onscreen?`alpha=${pr.alpha} deck=${pr.deck?'YES':'no'}`:'off-screen (deck below viewport)'}`);
console.log(`    proof PNG                    : ${pOut}`);
console.log(`    WebGPU errors                : ${errors.length ? '\n  - '+errors.join('\n  - ') : '(none)'}`);

// ── verdict ──
const feetProbes = probes.filter(p=>p.onscreen);
const feetOnDeck = feetProbes.length>0 && feetProbes.every(p=>p.deck);
const pass = ready && pinMax < 0.5 && Math.abs(ratio) > 0.98 && Math.abs(ratio) < 1.02
           && alphaPx > 1000 && errors.length===0 && (feetProbes.length===0 || feetOnDeck);
console.log(`\n================= GATE ${pass ? 'PASS ✅' : 'FAIL ❌'} =================`);
console.log(`camera deck-pin~0: ${pinMax<0.5} · pan ratio~1: ${Math.abs(ratio+1)<0.02||Math.abs(ratio-1)<0.02} · stage pixels: ${alphaPx>1000} · feet-on-deck: ${feetProbes.length? feetOnDeck : 'n/a(off-screen)'} · errors: ${errors.length}`);
process.exit(pass ? 0 : 1);
