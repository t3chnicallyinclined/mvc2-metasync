// gate_bodies_headless.mjs — REAL headless Dawn render of SpriteGPU on a FROZEN tape frame.
//
// This is the gate the stubbed draw-order smoke test could NOT be. The stub only checked
// draw-call ORDER against a fake WebGPU — it never produced a pixel, so it passed while the
// live render was blank. This renders the EMITTER body draw list (sprite-client
// buildEmitterDrawList -> sprite-gpu.mjs SpriteGPU.render, VERBATIM, the code under test)
// under Dawn, reads back the ACTUAL framebuffer, and asserts non-empty character-body pixels.
//
// Reuses the HUD gate's Dawn init (maplecast render-replica-poc/webgpu-headless.mjs) and the
// proven headless PNG->texture pattern from shot_stage_headless.mjs (fetch/createImageBitmap
// shims + copyExternalImageToTexture monkeypatch). It drives SpriteClient + tape-adapter +
// SpriteGPU EXACTLY as web/tapecanvas/gpu.html does (same window flags, same alphaMode, T=null).
//
//   usage:  node gate_bodies_headless.mjs [tapeIndex]        (default 200)
//
// PASS  = character region shows bodies (offscreen alpha pixels > BODY_MIN).
// FAIL  = 0 (blank) — proves the run-based-draw regression that HudClient masks.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const HERE  = path.dirname(fileURLToPath(import.meta.url));
const MAPLE = 'C:/Users/trist/projects/maplecast-flycast';
const POC   = path.join(MAPLE, 'tools/render-replica-poc');
const PNG   = require(path.join(POC, 'node_modules/pngjs/lib/png.js')).PNG;
const ATLAS_DIR = process.env.ATLAS_DIR ? path.resolve(process.env.ATLAS_DIR) : path.join(MAPLE, 'web/test-atlas/chars');
// BASE = which tapecanvas copy to test (its renderer/ + tape-adapter + tape.json). Default = this dir.
const BASE  = process.argv[3] ? path.resolve(process.argv[3]) : HERE;
const TAPE  = path.join(BASE, 'tape.json');
const FRAME = +(process.argv[2] || 200);
const W = 640, H = 480;
const BODY_MIN = 1500;          // two point-char bodies at CPS scale are ~30k alpha px; 1500 = generous floor

// ── browser-platform shims: local-file fetch + pngjs createImageBitmap (shot_stage_headless) ──
function localPath(url) {
  let p = String(url).split('?')[0];                       // strip cache-bust query
  if (p.startsWith('file://')) p = fileURLToPath(p);
  return p;
}
globalThis.fetch = async (url) => {
  const p = localPath(url);
  if (!fs.existsSync(p)) {
    const miss = async () => { throw new Error('404 ' + p); };
    return { ok: false, status: 404, json: miss, blob: miss, text: miss, arrayBuffer: miss };
  }
  const buf = fs.readFileSync(p);
  return {
    ok: true, status: 200,
    json: async () => JSON.parse(buf.toString('utf8')),
    text: async () => buf.toString('utf8'),
    blob: async () => ({ _png: buf }),
    arrayBuffer: async () => buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength),
  };
};
globalThis.createImageBitmap = async (blob) => {
  const png = PNG.sync.read(blob._png);
  return { width: png.width, height: png.height, _rgba: new Uint8Array(png.data) };
};
// document shim — onTXTR / buildDrawList use createElement('canvas'); NOT on the emitter path,
// but shim defensively so no code path throws in Node.
globalThis.document = { createElement: () => ({ width: 0, height: 0,
  getContext: () => ({ getImageData: () => ({ data: new Uint8ClampedArray(0) }), putImageData() {}, drawImage() {} }) }) };
// window flags EXACTLY as gpu.html sets them (faithful reproduction of the live harness).
globalThis.window = globalThis;
window._emitterPort  = true;    // faithful loc_8c033e90 emitter port
window._emitZByLayer = true;    // draw_layer group sort (spec §4)
window._fxGarbleGuard = true;   // suppress offline-decode banded effect cells

// ── Dawn device (same init as gate_hud_pvr2.mjs) ──
const { initDevice } = await import(pathToFileURL(path.join(POC, 'webgpu-headless.mjs')).href);
const { device, info } = await initDevice();
console.log('[gpu]', info.description || info.vendor || 'Dawn');

// Force rgba8unorm canvas format so the fake-canvas texture + offscreen readback are 1:1 RGBA.
let fmtForced = 'rgba8unorm';
try { navigator.gpu.getPreferredCanvasFormat = () => 'rgba8unorm'; } catch (_) {}
try { fmtForced = navigator.gpu.getPreferredCanvasFormat(); } catch (_) {}
console.log('[gpu] canvas format =', fmtForced);

// Dawn node has no ImageBitmap upload path — monkeypatch copyExternalImageToTexture -> writeTexture.
device.queue.copyExternalImageToTexture = (src, dst, size) => {
  const bm = src.source; const [w, h] = size;
  device.queue.writeTexture({ texture: dst.texture }, bm._rgba, { bytesPerRow: w * 4, rowsPerImage: h }, [w, h, 1]);
};

// ── device-error / lost hooks (deliverable item 4) ──
const errors = [];
let deviceLost = null;
try { device.lost?.then?.((d) => { deviceLost = d; }); } catch (_) {}
try { device.addEventListener?.('uncapturederror', (e) => errors.push('uncaptured: ' + (e.error && e.error.message || e.error))); } catch (_) {}

// ── fake canvas + webgpu context (headless has no swap-chain) ──
const canvasTex = device.createTexture({ size: [W, H], format: fmtForced,
  usage: GPUTextureUsage.RENDER_ATTACHMENT | GPUTextureUsage.COPY_SRC | GPUTextureUsage.TEXTURE_BINDING });
const fakeCtx = { configure() {}, unconfigure() {}, getCurrentTexture: () => canvasTex };
const fakeCanvas = { width: W, height: H, getContext: (t) => (t === 'webgpu' ? fakeCtx : null) };

// ── modules UNDER TEST (imported after globals exist) ──
console.log('[base]', BASE);
const SG_FILE = process.env.SG_FILE ? path.resolve(process.env.SG_FILE) : path.join(BASE, 'renderer', 'sprite-gpu.mjs');
console.log('[sprite-gpu]', SG_FILE);
const { SpriteClient } = await import(pathToFileURL(path.join(BASE, 'renderer', 'sprite-client.mjs')).href);
const { SpriteGPU }    = await import(pathToFileURL(SG_FILE).href);
const { loadTapeJson } = await import(pathToFileURL(path.join(BASE, 'tape-adapter.mjs')).href);

// ── drive it EXACTLY as gpu.html does ──
const SC = new SpriteClient();
const SG = new SpriteGPU();
SC.assemblyMode = true;   // EMITTER (parts) path — the validated body renderer
SC.predict = false;       // frozen tape frame — no extrapolation
SC.hitFlashOn = true;
SC.setCharBase(ATLAS_DIR);           // fetch shim reads local PLxx files

device.pushErrorScope('out-of-memory');
device.pushErrorScope('validation');
const ok = SG.init(device, fakeCanvas, 'premultiplied');
console.log('SG.init ->', ok, '(ctx via fake canvas, alphaMode premultiplied — same as gpu.html)');

const AD = await loadTapeJson(TAPE);
console.log(`tape: ${AD.frameCount} frames · p1=${JSON.stringify(AD.p1_team)} p2=${JSON.stringify(AD.p2_team)} · objRecBytes=${AD.objRecBytes} · costume=${JSON.stringify(AD.costume)}`);

// effects gate — mirror gpu.html renderFrame(): fx checkbox default checked + 20-byte objs
AD.effectsOn  = AD.objRecBytes >= 20;
SC.objectsOn  = AD.effectsOn;

const gframe = AD.applyFrame(SC, FRAME, { load: (sc, cid) => sc.loadAsmChar(cid) });
console.log(`applyFrame idx=${FRAME} -> game frame ${gframe}`);
for (let s = 0; s < 6; s++) { const sl = SC.slot[s]; if (sl.active)
  console.log(`  active slot ${s}: cid=${sl.char_id}(0x${(sl.char_id & 0xff).toString(16)}) sid=${sl.sprite_id} costume=${sl.costume} sx=${sl.screen_x.toFixed(1)} sy=${sl.screen_y.toFixed(1)} hp=${sl.health} layer=${sl.draw_layer}`); }

// AWAIT the lazy atlas loads (headless: no rAF re-render loop to catch late loads)
await Promise.all(Object.values(SC._asmLoading || {}));

// register loaded atlases into the GPU — gpu.html syncAtlases(), VERBATIM logic
for (const cid in SC.asmChars) {
  const c = SC.asmChars[cid];
  if (c && c.img && !SG.chars[cid]) { SG.setAtlas(cid, c.img); if (c.pal128) SG.setCharPalette(cid, c.pal128); }
  if (c && c.idxImg && c.lut && !SG.idxChars[cid]) { SG.setIndexedAtlas(cid, c.idxImg); SG.setCharLUT(cid, c.lut); }
}

// build the emitter draw list (buildEmitterDrawList) + report route census
const drawList = SC.buildAssemblyDrawList(W, H);
console.log(`drawList: ${drawList.length} sprites · asmDrawn=${SC._asmDrawn} · note="${SC._asmNote}"`);
let nRGB = 0, nLUT = 0, nNull = 0;
for (const s of drawList) {
  const ic = SG.idxChars[s.charId], lut = SG.charLUT[s.charId];
  if (s.costume != null && ic && ic.bg && lut) nLUT++;
  else if (SG.chars[s.charId] && SG.chars[s.charId].bg) nRGB++;
  else nNull++;
}
console.log(`route census (mirror sprite-gpu routeOf): lut=${nLUT} rgb=${nRGB} null(no-atlas,skipped)=${nNull}`);

// ── RENDER — the code under test, VERBATIM (same args gpu.html passes) ──
let renderThrow = null;
try { SG.render(drawList, {}, null /* no live PVR palette on a tape */, [], null); }
catch (e) { renderThrow = e; }
console.log(`SG._skippedEmpty = ${SG._skippedEmpty | 0} (persist-on-empty bail count; nonzero => render bailed before drawing)`);
if (renderThrow) { errors.push('SG.render THREW: ' + renderThrow.message); console.log('SG.render THREW:', renderThrow.stack || renderThrow.message); }

// pop error scopes (validation first, then oom)
const valErr = await device.popErrorScope();
const oomErr = await device.popErrorScope();
if (valErr) errors.push('validation: ' + valErr.message);
if (oomErr) errors.push('out-of-memory: ' + oomErr.message);
try { await device.queue.onSubmittedWorkDone?.(); } catch (_) {}
if (deviceLost) errors.push('device.lost: ' + (deviceLost.message || deviceLost.reason));

// ── readback both surfaces ──
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
    if (bgra) { out[d] = m[s + 2]; out[d + 1] = m[s + 1]; out[d + 2] = m[s]; out[d + 3] = m[s + 3]; }
    else { out[d] = m[s]; out[d + 1] = m[s + 1]; out[d + 2] = m[s + 2]; out[d + 3] = m[s + 3]; }
  }
  return out;
}
const off = SG.ok && SG.PP && SG.PP.offscreenTex ? await readTex(SG.PP.offscreenTex) : new Uint8Array(W * H * 4);
const can = await readTex(canvasTex);

// ── measure ──
const countAlpha = (px, x0, y0, x1, y1) => { let n = 0; for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) if (px[(y * W + x) * 4 + 3] > 0) n++; return n; };
const countNonBlack = (px, x0, y0, x1, y1) => { let n = 0; for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) { const i = (y * W + x) * 4; if (px[i] > 8 || px[i + 1] > 8 || px[i + 2] > 8) n++; } return n; };
const bbox = (px) => { let x0 = W, y0 = H, x1 = -1, y1 = -1; for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) if (px[(y * W + x) * 4 + 3] > 0) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; } return x1 < 0 ? null : { x0, y0, x1, y1 }; };

const REGION = [0, 96, W, H];    // character region (below the HUD top band, which SG never draws anyway)
const bodyOffAll = countAlpha(off, 0, 0, W, H);
const bodyOffReg = countAlpha(off, ...REGION);
const bodyCanReg = countNonBlack(can, ...REGION);
const bb = bbox(off);

// ── write proof PNGs ──
function writePng(name, px, overBg) {
  const png = new PNG({ width: W, height: H });
  if (overBg) for (let i = 0; i < px.length; i += 4) { const a = px[i + 3] / 255; px[i] = px[i] * a + 0x18 * (1 - a); px[i + 1] = px[i + 1] * a + 0x1a * (1 - a); px[i + 2] = px[i + 2] * a + 0x20 * (1 - a); px[i + 3] = 255; }
  png.data = Buffer.from(px.buffer, px.byteOffset, px.byteLength);
  const p = path.join(HERE, name); fs.writeFileSync(p, PNG.sync.write(png)); return p;
}
const pOff = writePng(`_gate_bodies_f${FRAME}_offscreen.png`, off.slice(), true);
const pCan = writePng(`_gate_bodies_f${FRAME}_canvas.png`, can.slice(), false);

// ── report ──
console.log('\n================= GATE: SpriteGPU bodies (REAL pixels) =================');
console.log(`frozen frame        : tape idx ${FRAME}  (game frame ${gframe})`);
console.log(`offscreen body px   : ${bodyOffAll} whole-frame · ${bodyOffReg} in char region ${JSON.stringify(REGION)}`);
console.log(`canvas non-black px : ${bodyCanReg} in char region (post-blit; what the user sees)`);
console.log(`body bbox (alpha>0) : ${bb ? `x[${bb.x0}..${bb.x1}] y[${bb.y0}..${bb.y1}]` : 'NONE — fully blank'}`);
console.log(`WebGPU errors       : ${errors.length ? '\n  - ' + errors.join('\n  - ') : '(none)'}`);
console.log(`proof PNGs          : ${pOff}\n                      ${pCan}`);
const pass = bodyOffReg >= BODY_MIN;
console.log(`\nRESULT: ${pass ? 'PASS — bodies render' : 'FAIL — BLANK (0/low body pixels); SpriteGPU draws no characters'} (threshold ${BODY_MIN})`);
console.log('=======================================================================');
process.exit(pass ? 0 : 1);
