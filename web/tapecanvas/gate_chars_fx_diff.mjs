// gate_chars_fx_diff.mjs — REGION-MASKED characters+effects PIXEL gate.
//
// THE GATE (mission 2026-08-29): no render fix is real until the LIVE/engine framebuffer's
// pixels match the tape renderer's on the SAME frozen frame. This is the FALSIFIABLE gate for
// the characters + effects pixel-perfect effort. Offline geometry (X-spans) is a pre-filter,
// NOT a pass. This measures REAL pixels: renders the tape's bodies+effects through the code
// under test (SpriteClient buildEmitterDrawList -> SpriteGPU.render, VERBATIM, same as gpu.html),
// reads back the ACTUAL Dawn framebuffer, and diffs it against an ENGINE ground-truth PNG
// (MAPLECAST_GSTA_SHOT from the flycast oracle in plain-mirror mode = the engine's real TA).
//
// It reports, EXCLUDING stage/background (chars+effects only):
//   - per-pixel mean |Δ| (masked), windowed SSIM, and the diff bounding box, PER FIGHTER
//   - the EFFECT layer separately (fx-added pixels, isolated by bodies+fx MINUS bodies-only)
//   - coverage delta (pixels we drew but engine didn't / engine drew but we didn't)
//   - a RANKED list: which fighter / body-region / effects carry the biggest residual
//
// Ground-truth is the ENGINE framebuffer, never an offline replica. gl_row/row harness_shots
// are replica-vs-replica (byte-identical bodies) — DO NOT use them as GT (confirmed 2026-08-29).
//
// MODES
//   node gate_chars_fx_diff.mjs --frame 200 --gt <engine.png> [--gt-bg black|<stageonly.png>]
//        -> the real gate: masked chars+fx diff of ours(frame) vs engine GT.
//   node gate_chars_fx_diff.mjs --frame 200 --selftest
//        -> SENSITIVITY: proves the gate PASSES ours-vs-ours (Δ≈0) and FAILS a deliberately
//           wrong render (6px shift + palette corruption). A low score is only a real pass if
//           this test shows the gate can fail. No engine GT needed.
//   node gate_chars_fx_diff.mjs --pair <a.png> <b.png> [--hud-top N] [--hud-bot N]
//        -> run the SAME region-diff metric on two existing framebuffers (e.g. engine mirror vs
//           a recon), excluding HUD bands. For metric validation on real engine captures.
//
// Exit 0 = PASS (masked mean |Δ| <= --tol, default 6 ; and coverage <= --cov-tol, default 4%).
// Exit 1 = FAIL. Exit 2 = could not render / bad args.

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
const W = 640, H = 480;

// ── args ──
function argVal(name, def) { const i = process.argv.indexOf(name); return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : def; }
function argFlag(name) { return process.argv.includes(name); }
const FRAME    = +(argVal('--frame', 200));
const GT_PATH  = argVal('--gt', null);
const GT_BG    = argVal('--gt-bg', 'black');     // 'black' => gt foreground = non-black; else a stage-only PNG to subtract
const TOL      = +(argVal('--tol', 6));          // masked mean |Δ| per channel px pass ceiling
const COV_TOL  = +(argVal('--cov-tol', 4));      // coverage-mismatch % pass ceiling
const SELFTEST = argFlag('--selftest');
const PAIR     = argFlag('--pair');
const HUD_TOP  = +(argVal('--hud-top', 130));    // rows [0..HUD_TOP) excluded (top HUD band)
const HUD_BOT  = +(argVal('--hud-bot', 40));     // rows [H-HUD_BOT..H) excluded (bottom level meters)
const DIFF_THR = +(argVal('--diff-thr', 30));    // per-px sum-abs-delta counted as a "diff pixel" / bbox
const COV_LUM  = +(argVal('--cov-lum', 24));     // luminance-over-black foreground threshold (coverage; same rule both sides)

// ═══════════════════════ shared pixel helpers ═══════════════════════
function readPNG(p) { const d = PNG.sync.read(fs.readFileSync(p)); return { w: d.width, h: d.height, data: new Uint8Array(d.data) }; }
function writePNG(p, rgba, w = W, h = H) { const png = new PNG({ width: w, height: h }); png.data = Buffer.from(rgba.buffer, rgba.byteOffset, rgba.byteLength); fs.writeFileSync(p, PNG.sync.write(png)); return p; }
// composite premultiplied-alpha rgba over a solid bg -> opaque rgb-in-rgba
function overBg(px, bg = [0x18, 0x1a, 0x20]) {
  const out = new Uint8Array(px.length);
  for (let i = 0; i < px.length; i += 4) { const a = px[i + 3] / 255;
    out[i] = px[i] * a + bg[0] * (1 - a); out[i + 1] = px[i + 1] * a + bg[1] * (1 - a);
    out[i + 2] = px[i + 2] * a + bg[2] * (1 - a); out[i + 3] = 255; }
  return out;
}
const lum = (r, g, b) => 0.299 * r + 0.587 * g + 0.114 * b;

// masked mean |Δ| per channel + diff-pixel count + diff bbox, over a boolean mask
function maskedDiff(a, b, mask, w = W, h = H) {
  let sum = 0, n = 0, over = 0, mx = 0, x0 = w, y0 = h, x1 = -1, y1 = -1;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    if (!mask[y * w + x]) continue;
    const i = (y * w + x) * 4;
    const d = Math.abs(a[i] - b[i]) + Math.abs(a[i + 1] - b[i + 1]) + Math.abs(a[i + 2] - b[i + 2]);
    sum += d; n++; if (d > mx) mx = d;
    if (d > DIFF_THR) { over++; if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
  }
  return { meanPerCh: n ? sum / (n * 3) : 0, n, over, overPct: n ? 100 * over / n : 0, max: mx,
           bbox: x1 < 0 ? null : { x0, y0, x1, y1 } };
}

// windowed SSIM over a mask: 8x8 blocks, averaged over blocks with >=25% mask coverage.
function maskedSSIM(a, b, mask, w = W, h = H) {
  const C1 = (0.01 * 255) ** 2, C2 = (0.03 * 255) ** 2, B = 8;
  let acc = 0, nb = 0;
  for (let by = 0; by < h; by += B) for (let bx = 0; bx < w; bx += B) {
    let sa = 0, sb = 0, saa = 0, sbb = 0, sab = 0, cnt = 0, tot = 0;
    for (let y = by; y < Math.min(by + B, h); y++) for (let x = bx; x < Math.min(bx + B, w); x++) {
      tot++; if (!mask[y * w + x]) continue; cnt++;
      const i = (y * w + x) * 4; const la = lum(a[i], a[i + 1], a[i + 2]), lb = lum(b[i], b[i + 1], b[i + 2]);
      sa += la; sb += lb; saa += la * la; sbb += lb * lb; sab += la * lb;
    }
    if (cnt < tot * 0.25 || cnt < 4) continue;
    const ma = sa / cnt, mb = sb / cnt, va = saa / cnt - ma * ma, vb = sbb / cnt - mb * mb, cov = sab / cnt - ma * mb;
    const s = ((2 * ma * mb + C1) * (2 * cov + C2)) / ((ma * ma + mb * mb + C1) * (va + vb + C2));
    acc += s; nb++;
  }
  return nb ? acc / nb : 1;
}

// coverage: foreground of a vs foreground of b within a region -> % of union pixels that disagree
function coverageDelta(fgA, fgB, region, w = W) {
  let onlyA = 0, onlyB = 0, both = 0;
  for (const idx of region) { const a = fgA[idx], b = fgB[idx]; if (a && b) both++; else if (a) onlyA++; else if (b) onlyB++; }
  const union = onlyA + onlyB + both;
  return { onlyA, onlyB, both, union, pct: union ? 100 * (onlyA + onlyB) / union : 0 };
}

// ═══════════════════════ --pair mode (metric on two existing framebuffers) ═══════════════════════
if (PAIR) {
  const ai = process.argv.indexOf('--pair');
  const A = readPNG(process.argv[ai + 1]), Bp = readPNG(process.argv[ai + 2]);
  const a = A.data, b = Bp.data;
  // mask = play area minus HUD bands, AND at least one side has foreground (non-near-black).
  const mask = new Uint8Array(W * H);
  const fgA = new Uint8Array(W * H), fgB = new Uint8Array(W * H);
  const region = [];
  for (let y = HUD_TOP; y < H - HUD_BOT; y++) for (let x = 0; x < W; x++) {
    const idx = y * W + x, i = idx * 4;
    fgA[idx] = (a[i] > 16 || a[i + 1] > 16 || a[i + 2] > 16) ? 1 : 0;
    fgB[idx] = (b[i] > 16 || b[i + 1] > 16 || b[i + 2] > 16) ? 1 : 0;
    mask[idx] = 1; region.push(idx);        // stage cancels (identical in both), so diff whole play area
  }
  const d = maskedDiff(a, b, mask);
  const ss = maskedSSIM(a, b, mask);
  const cov = coverageDelta(fgA, fgB, region);
  console.log('\n===== PAIR region-diff (play area, HUD bands excluded) =====');
  console.log(`A: ${process.argv[ai + 1]}`);
  console.log(`B: ${process.argv[ai + 2]}`);
  console.log(`region rows [${HUD_TOP}..${H - HUD_BOT})  pixels ${d.n}`);
  console.log(`mean |Δ|/ch : ${d.meanPerCh.toFixed(3)}   diff px>${DIFF_THR}: ${d.over} (${d.overPct.toFixed(2)}%)   max ${d.max}`);
  console.log(`SSIM        : ${ss.toFixed(4)}`);
  console.log(`coverage    : onlyA ${cov.onlyA}  onlyB ${cov.onlyB}  both ${cov.both}  mismatch ${cov.pct.toFixed(2)}%`);
  console.log(`diff bbox   : ${d.bbox ? `x[${d.bbox.x0}..${d.bbox.x1}] y[${d.bbox.y0}..${d.bbox.y1}]` : 'none'}`);
  // ranked columns: split play area into vertical thirds (left fighter / center / right fighter)
  const thirds = [[0, 213, 'LEFT (P1 side)'], [213, 426, 'CENTER'], [426, 640, 'RIGHT (P2 side)']];
  console.log('ranked by column band:');
  const ranked = thirds.map(([xa, xb, name]) => {
    const m = new Uint8Array(W * H); for (let y = HUD_TOP; y < H - HUD_BOT; y++) for (let x = xa; x < xb; x++) m[y * W + x] = 1;
    const dd = maskedDiff(a, b, m); return { name, over: dd.over, mean: dd.meanPerCh, bbox: dd.bbox };
  }).sort((p, q) => q.over - p.over);
  for (const r of ranked) console.log(`  ${r.name.padEnd(16)} diff px ${String(r.over).padStart(6)}  mean ${r.mean.toFixed(3)}  bbox ${r.bbox ? `x[${r.bbox.x0}..${r.bbox.x1}] y[${r.bbox.y0}..${r.bbox.y1}]` : '-'}`);
  // heatmap
  const hm = new Uint8Array(W * H * 4);
  for (let idx = 0; idx < W * H; idx++) { const i = idx * 4; const dd = Math.abs(a[i] - b[i]) + Math.abs(a[i + 1] - b[i + 1]) + Math.abs(a[i + 2] - b[i + 2]);
    const v = Math.min(255, dd); hm[i] = v; hm[i + 1] = mask[idx] ? (dd > DIFF_THR ? 0 : 40) : 0; hm[i + 2] = mask[idx] ? 40 : 0; hm[i + 3] = 255; }
  const hp = writePNG(path.join(HERE, `_gate_pair_heat.png`), hm);
  console.log(`heatmap     : ${hp}`);
  const pass = d.meanPerCh <= TOL && cov.pct <= COV_TOL;
  console.log(`\nRESULT: ${pass ? 'PASS' : 'FAIL'}  (mean |Δ|/ch ${d.meanPerCh.toFixed(3)} vs tol ${TOL}; coverage ${cov.pct.toFixed(2)}% vs ${COV_TOL}%)`);
  console.log('===========================================================');
  process.exit(pass ? 0 : 1);
}

// ═══════════════════════ headless Dawn render of the tape (bodies / bodies+fx) ═══════════════════════
// browser-platform shims (verbatim from gate_bodies_headless.mjs — the proven rig).
function localPath(url) { let p = String(url).split('?')[0]; if (p.startsWith('file://')) p = fileURLToPath(p); return p; }
globalThis.fetch = async (url) => { const p = localPath(url);
  if (!fs.existsSync(p)) { const miss = async () => { throw new Error('404 ' + p); }; return { ok: false, status: 404, json: miss, blob: miss, text: miss, arrayBuffer: miss }; }
  const buf = fs.readFileSync(p);
  return { ok: true, status: 200, json: async () => JSON.parse(buf.toString('utf8')), text: async () => buf.toString('utf8'),
    blob: async () => ({ _png: buf }), arrayBuffer: async () => buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) }; };
globalThis.createImageBitmap = async (blob) => { const png = PNG.sync.read(blob._png); return { width: png.width, height: png.height, _rgba: new Uint8Array(png.data) }; };
globalThis.document = { createElement: () => ({ width: 0, height: 0, getContext: () => ({ getImageData: () => ({ data: new Uint8ClampedArray(0) }), putImageData() {}, drawImage() {} }) }) };
globalThis.window = globalThis;
window._emitterPort = true; window._emitZByLayer = true; window._fxGarbleGuard = true;

const LOG = (m) => process.stderr.write(`[gate ${((Date.now() - _t0) / 1000).toFixed(1)}s] ${m}\n`);
const _t0 = Date.now();
LOG('init Dawn device...');
const { initDevice } = await import(pathToFileURL(path.join(POC, 'webgpu-headless.mjs')).href);
const { device } = await initDevice();
LOG('device ready');
try { navigator.gpu.getPreferredCanvasFormat = () => 'rgba8unorm'; } catch (_) {}
device.queue.copyExternalImageToTexture = (src, dst, size) => { const [w, h] = size; device.queue.writeTexture({ texture: dst.texture }, src.source._rgba, { bytesPerRow: w * 4, rowsPerImage: h }, [w, h, 1]); };

function mkTex() { return device.createTexture({ size: [W, H], format: 'rgba8unorm', usage: GPUTextureUsage.RENDER_ATTACHMENT | GPUTextureUsage.COPY_SRC | GPUTextureUsage.TEXTURE_BINDING }); }
async function readTex(tex) { const bpr = Math.ceil(W * 4 / 256) * 256; const rb = device.createBuffer({ size: bpr * H, usage: GPUBufferUsage.COPY_DST | GPUBufferUsage.MAP_READ });
  const e = device.createCommandEncoder(); e.copyTextureToBuffer({ texture: tex }, { buffer: rb, bytesPerRow: bpr, rowsPerImage: H }, [W, H, 1]); device.queue.submit([e.finish()]);
  await rb.mapAsync(GPUMapMode.READ); const m = new Uint8Array(rb.getMappedRange()).slice(); rb.unmap();
  const o = new Uint8Array(W * H * 4); for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) { const s = y * bpr + x * 4, d = (y * W + x) * 4; o[d] = m[s]; o[d + 1] = m[s + 1]; o[d + 2] = m[s + 2]; o[d + 3] = m[s + 3]; } return o; }

const { SpriteClient } = await import(pathToFileURL(path.join(HERE, 'renderer', 'sprite-client.mjs')).href);
const { SpriteGPU }    = await import(pathToFileURL(path.join(HERE, 'renderer', 'sprite-gpu.mjs')).href);
const { loadTapeJson } = await import(pathToFileURL(path.join(HERE, 'tape-adapter.mjs')).href);

const AD = await loadTapeJson(path.join(HERE, 'tape.json'));

// Render the tape at FRAME with effects on/off. Returns { px (premultiplied rgba), slots }.
async function renderTape(frame, { effects }) {
  const canvasTex = mkTex();
  const canvas = { width: W, height: H, getContext: (t) => t === 'webgpu' ? { configure() {}, unconfigure() {}, getCurrentTexture: () => canvasTex } : null };
  const SC = new SpriteClient(); const SG = new SpriteGPU();
  SC.assemblyMode = true; SC.predict = false; SC.hitFlashOn = true; SC.setCharBase(ATLAS_DIR);
  SG.init(device, canvas, 'premultiplied');
  AD.effectsOn = !!effects && AD.objRecBytes >= 20; SC.objectsOn = AD.effectsOn;
  const gframe = AD.applyFrame(SC, frame, { load: (sc, cid) => sc.loadAsmChar(cid) });
  await Promise.all(Object.values(SC._asmLoading || {}));
  for (const cid in SC.asmChars) { const c = SC.asmChars[cid];
    if (c && c.img && !SG.chars[cid]) { SG.setAtlas(cid, c.img); if (c.pal128) SG.setCharPalette(cid, c.pal128); }
    if (c && c.idxImg && c.lut && !SG.idxChars[cid]) { SG.setIndexedAtlas(cid, c.idxImg); SG.setCharLUT(cid, c.lut); } }
  const drawList = SC.buildAssemblyDrawList(W, H);
  SG.render(drawList, {}, null, [], null);
  await device.queue.onSubmittedWorkDone?.();
  const px = await readTex(SG.PP && SG.PP.offscreenTex ? SG.PP.offscreenTex : canvasTex);
  // per-drawn-slot foot-anchor screen X (tape schema idx 24 = sx[6], 17 = drawn[6])
  const row = AD.frames[frame];
  const drawn = row[17], sx = row[24], sy = row[25];
  const slots = []; for (let s = 0; s < 6; s++) if (drawn[s] === 1) slots.push({ s, side: s < 3 ? 1 : 2, sx: sx[s], sy: sy[s] });
  return { px, slots, gframe, drawList };
}

// build boolean masks from ours: fighterMask (bodies alpha), effectMask (fx-added alpha), per-fighter split.
function buildMasks(bodiesFx, bodiesOnly, slots) {
  const fighter = new Uint8Array(W * H), effect = new Uint8Array(W * H), fg = new Uint8Array(W * H);
  for (let idx = 0; idx < W * H; idx++) {
    const bodyA = bodiesOnly[idx * 4 + 3] > 8, allA = bodiesFx[idx * 4 + 3] > 8;
    if (bodyA) fighter[idx] = 1;
    if (allA && !bodyA) effect[idx] = 1;      // effects added pixels where the body had none
    if (allA) fg[idx] = 1;
  }
  // per-fighter: assign each fighter pixel to the nearest drawn-slot foot-anchor X (fighters are H-separated)
  const perSlot = {}; for (const sl of slots) perSlot[sl.s] = new Uint8Array(W * H);
  if (slots.length) for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) { const idx = y * W + x; if (!fighter[idx]) continue;
    let best = slots[0], bd = 1e9; for (const sl of slots) { const d = Math.abs(x - sl.sx); if (d < bd) { bd = d; best = sl; } } perSlot[best.s][idx] = 1; }
  return { fighter, effect, fg, perSlot };
}
function dilate(mask, r = 3) { const out = new Uint8Array(mask.length); for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) { if (!mask[y * W + x]) continue;
  for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++) { const ny = y + dy, nx = x + dx; if (ny >= 0 && ny < H && nx >= 0 && nx < W) out[ny * W + nx] = 1; } } return out; }
function bboxOf(mask) { let x0 = W, y0 = H, x1 = -1, y1 = -1; for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) if (mask[y * W + x]) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; } return x1 < 0 ? null : { x0, y0, x1, y1 }; }

const CHARMAP = { 0x2a: 'STORM', 0x2c: 'MAGNETO', 0x32: 'COLOSSUS', 0x34: 'SENTINEL', 0x0f: '0x0F', 0x17: 'CABLE' };
const nameOf = (cid) => CHARMAP[cid & 0xff] || ('cid0x' + (cid & 0xff).toString(16));

// ── render ours at FRAME ──
LOG(`render bodies+fx  f${FRAME}...`);
const oursFx   = await renderTape(FRAME, { effects: true });
LOG(`render bodies-only f${FRAME}...`);
const oursBody = await renderTape(FRAME, { effects: false });
LOG('masks + diff...');
const masks = buildMasks(oursFx.px, oursBody.px, oursFx.slots);
const oursFxRGB = overBg(oursFx.px);
writePNG(path.join(HERE, `_gate_cfx_f${FRAME}_ours.png`), oursFxRGB);
// effect-only proof (fx pixels over black)
const fxOnly = new Uint8Array(W * H * 4); for (let idx = 0; idx < W * H; idx++) if (masks.effect[idx]) { const i = idx * 4; fxOnly[i] = oursFx.px[i]; fxOnly[i + 1] = oursFx.px[i + 1]; fxOnly[i + 2] = oursFx.px[i + 2]; fxOnly[i + 3] = 255; }
writePNG(path.join(HERE, `_gate_cfx_f${FRAME}_fxonly.png`), fxOnly);

const nFighter = masks.fighter.reduce((a, v) => a + v, 0);
const nEffect  = masks.effect.reduce((a, v) => a + v, 0);
console.log(`\nFROZEN FRAME: tape idx ${FRAME}  (game frame ${oursFx.gframe})`);
console.log(`roster: p1=[${AD.p1_team.map(nameOf).join(',')}]  p2=[${AD.p2_team.map(nameOf).join(',')}]  stage_id=${AD.stage_id}`);
console.log(`drawn slots: ${oursFx.slots.map(s => `s${s.s}(${nameOf(AD['p' + s.side + '_team'][s.s % 3])}) x=${s.sx|0} y=${s.sy|0}`).join('  ')}`);
console.log(`ours pixels: fighter ${nFighter}  effect ${nEffect}  (objRecBytes=${AD.objRecBytes}, ${oursFx.slots.length} slots drawn; effect px come from fx objs at this game frame)`);

// ═══════════════════════ SELFTEST — sensitivity (no GT needed) ═══════════════════════
if (SELFTEST || !GT_PATH) {
  if (!GT_PATH && !SELFTEST) console.log('\n[no --gt supplied] running SENSITIVITY selftest so a future low score is a proven pass.');
  const region = masks.fighter;                       // gate on the fighter mask
  // 1) ours vs ours (identity) => must be ~0
  const idn = maskedDiff(oursFxRGB, oursFxRGB, region);
  const idnSSIM = maskedSSIM(oursFxRGB, oursFxRGB, region);
  // 2) ours vs deliberately-WRONG: shift +6px X and corrupt palette (swap R/B, scale G)
  const wrong = new Uint8Array(oursFxRGB.length);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) { const sx = Math.max(0, x - 6); const si = (y * W + sx) * 4, di = (y * W + x) * 4;
    wrong[di] = oursFxRGB[si + 2]; wrong[di + 1] = Math.min(255, oursFxRGB[si + 1] * 1.4); wrong[di + 2] = oursFxRGB[si]; wrong[di + 3] = 255; }
  const wr = maskedDiff(oursFxRGB, wrong, region);
  const wrSSIM = maskedSSIM(oursFxRGB, wrong, region);
  // coverage of wrong: recompute fg of shifted
  const wrongFg = new Uint8Array(W * H); for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) { const idx = y * W + x; wrongFg[idx] = masks.fg[y * W + Math.max(0, x - 6)]; }
  const fighterD6 = dilate(masks.fighter, 6);
  const regionIdx = []; for (let idx = 0; idx < W * H; idx++) if (fighterD6[idx]) regionIdx.push(idx);
  const wrCov = coverageDelta(masks.fg, wrongFg, regionIdx);
  writePNG(path.join(HERE, `_gate_cfx_f${FRAME}_selftest_wrong.png`), wrong);
  console.log('\n===== SENSITIVITY SELFTEST (fighter mask) =====');
  console.log(`identity  (ours vs ours)   : mean |Δ|/ch ${idn.meanPerCh.toFixed(3)}  SSIM ${idnSSIM.toFixed(4)}  diff px>${DIFF_THR} ${idn.over}`);
  console.log(`corrupted (6px + pal swap) : mean |Δ|/ch ${wr.meanPerCh.toFixed(3)}  SSIM ${wrSSIM.toFixed(4)}  diff px>${DIFF_THR} ${wr.over}  coverage ${wrCov.pct.toFixed(2)}%`);
  const idnPass = idn.meanPerCh <= TOL && idn.over === 0;
  const wrFails = wr.meanPerCh > TOL;                 // the gate MUST flag the wrong render
  console.log(`\ngate discriminates: identity PASS=${idnPass}  corrupted FAILS-gate=${wrFails}`);
  console.log(`RESULT: ${idnPass && wrFails ? 'PASS — gate is falsifiable (0 on identity, fails on wrong)' : 'FAIL — gate does not discriminate'}`);
  console.log('================================================');
  process.exit(idnPass && wrFails ? 0 : 1);
}

// ═══════════════════════ REAL GATE — ours vs ENGINE GT ═══════════════════════
// --gt SELF : feed ours(over black) as its own GT — exercises EVERY report branch; must yield ~0.
//             (code-path smoke test for the real-GT path when no engine capture exists yet.)
const oursBlackSelf = overBg(oursFx.px, [0, 0, 0]);
const gt = (GT_PATH === 'SELF') ? { w: W, h: H, data: oursBlackSelf } : readPNG(GT_PATH);
if (gt.w !== W || gt.h !== H) { console.log(`GT is ${gt.w}x${gt.h}, expected ${W}x${H}`); process.exit(2); }
// compare ours (over black, so bg matches GT's black char-pass bg) vs GT
const oursBlack = overBg(oursFx.px, [0, 0, 0]);
// COVERAGE foreground uses the SAME color-over-black luminance rule on BOTH sides (so a
// semi-transparent effect/edge pixel that composites dark is treated identically). GT with a
// stage keeps the stage-subtraction path. HUD bands excluded on both.
const gtFg = new Uint8Array(W * H), oursFgAll = new Uint8Array(W * H);
let stageOnly = null; if (GT_BG !== 'black') stageOnly = readPNG(GT_BG);
for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) { const idx = y * W + x, i = idx * 4;
  if (y < HUD_TOP || y >= H - HUD_BOT) continue;
  oursFgAll[idx] = lum(oursBlack[i], oursBlack[i + 1], oursBlack[i + 2]) > COV_LUM ? 1 : 0;
  if (stageOnly) { const d = Math.abs(gt.data[i] - stageOnly.data[i]) + Math.abs(gt.data[i + 1] - stageOnly.data[i + 1]) + Math.abs(gt.data[i + 2] - stageOnly.data[i + 2]); gtFg[idx] = d > 24 ? 1 : 0; }
  else gtFg[idx] = lum(gt.data[i], gt.data[i + 1], gt.data[i + 2]) > COV_LUM ? 1 : 0;
}
// gate mask = (ours fighter+effect alpha) UNION (gt foreground), dilated 2px to tolerate ±1px placement.
const oursAlphaFg = new Uint8Array(W * H); for (let idx = 0; idx < W * H; idx++) oursAlphaFg[idx] = (masks.fighter[idx] || masks.effect[idx]) ? 1 : 0;
const gateMask = new Uint8Array(W * H); for (let idx = 0; idx < W * H; idx++) gateMask[idx] = (oursAlphaFg[idx] || gtFg[idx]) ? 1 : 0;
const gateMaskD = dilate(gateMask, 2);

function report(name, mask) {
  const d = maskedDiff(oursBlack, gt.data, mask);
  const ss = maskedSSIM(oursBlack, gt.data, mask);
  const region = []; for (let idx = 0; idx < W * H; idx++) if (mask[idx]) region.push(idx);
  const cov = coverageDelta(oursFgAll, gtFg, region);
  console.log(`  ${name.padEnd(22)} mean|Δ|/ch ${d.meanPerCh.toFixed(3).padStart(7)}  SSIM ${ss.toFixed(4)}  diff px>${DIFF_THR} ${String(d.over).padStart(6)}/${d.n}  cov-miss ${cov.pct.toFixed(1)}%  bbox ${d.bbox ? `x[${d.bbox.x0}..${d.bbox.x1}] y[${d.bbox.y0}..${d.bbox.y1}]` : '-'}`);
  return { name, ...d, ssim: ss, cov: cov.pct };
}
console.log(`\n===== CHARS+FX GATE — ours(f${FRAME}) vs ENGINE GT =====`);
console.log(`GT: ${GT_PATH}  (bg=${GT_BG})`);
const whole = report('WHOLE chars+fx', gateMaskD);
const fRep = report('FIGHTERS (bodies)', dilate(masks.fighter, 2));
const eRep = masks.effect.reduce((a, v) => a + v, 0) ? report('EFFECTS only', dilate(masks.effect, 2)) : null;
// per-fighter
const perRep = [];
for (const sl of oursFx.slots) { const nm = `${nameOf(AD['p' + sl.side + '_team'][sl.s % 3])} (s${sl.s})`;
  perRep.push(report('  ' + nm, dilate(masks.perSlot[sl.s], 2))); }
// RANK
console.log('\nRANKED residual (biggest first — what the sprite-render expert fixes first):');
const ranked = [...perRep, ...(eRep ? [eRep] : [])].sort((a, b) => b.over - a.over);
for (const r of ranked) console.log(`  ${r.name.trim().padEnd(20)} diff px>${DIFF_THR} ${String(r.over).padStart(6)}  mean|Δ|/ch ${r.meanPerCh.toFixed(3)}  SSIM ${r.ssim.toFixed(4)}  cov-miss ${r.cov.toFixed(1)}%`);
// heatmap
const hm = new Uint8Array(W * H * 4);
for (let idx = 0; idx < W * H; idx++) { const i = idx * 4; if (!gateMaskD[idx]) { hm[i + 3] = 255; continue; }
  const dd = Math.abs(oursBlack[i] - gt.data[i]) + Math.abs(oursBlack[i + 1] - gt.data[i + 1]) + Math.abs(oursBlack[i + 2] - gt.data[i + 2]);
  hm[i] = Math.min(255, dd); hm[i + 1] = dd > DIFF_THR ? 0 : 60; hm[i + 2] = 40; hm[i + 3] = 255; }
const hp = writePNG(path.join(HERE, `_gate_cfx_f${FRAME}_heat.png`), hm);
console.log(`\nheatmap  : ${hp}`);
console.log(`proof    : _gate_cfx_f${FRAME}_ours.png  _gate_cfx_f${FRAME}_fxonly.png`);
const pass = whole.meanPerCh <= TOL && whole.cov <= COV_TOL;
console.log(`\nRESULT: ${pass ? 'PASS' : 'FAIL'}  (WHOLE mean|Δ|/ch ${whole.meanPerCh.toFixed(3)} vs tol ${TOL}; cov-miss ${whole.cov.toFixed(1)}% vs ${COV_TOL}%)`);
console.log('=========================================================');
process.exit(pass ? 0 : 1);
