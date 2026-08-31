// hud-pvr2.mjs — render the MVC2 HUD through the REAL pvr2 rasterizer (the exact TA renderer
// that produced the ground-truth _hud_cap_def/hud_0123.png), NOT a software re-implementation.
//
// This is a straight reuse of maplecast tools/render-replica-poc/render_hudq.mjs's proven path:
//   HUDQ quads -> buildHudTA (para4 poly + 4 verts) -> TAParser -> PVR2Renderer.renderFrame
//   with the shipped VRAM + palette. render_hudq.mjs under Dawn reproduces hud_0123.png
//   BYTE-EXACT (0.00/px, verified) — so routing the tape HUD through it is pixel-faithful by
//   construction, and the P2 para5 gold bar renders correctly (pvr2 made the truth).
//
// buildHudTA is copied VERBATIM from render_hudq.mjs (per feedback-port-proven-code-asis).
// The vendored deps are the same modules: pvr2-renderer.mjs / ta-parser.mjs / texture-manager.mjs
// / shaders.mjs (copied into ./ alongside sprite-gpu.mjs).
//
// Runs in BOTH environments off one code path:
//   • Node/Dawn (gate): caller supplies a Dawn device; render() records, caller submits + reads back.
//   • Browser (gpu.html): caller supplies a navigator.gpu device + a WebGPU-context canvas; render()
//     draws into an offscreen RENDER_ATTACHMENT texture which the caller blits/presents.

import { PVR2Renderer } from './pvr2-renderer.mjs';
import { TAParser } from './ta-parser.mjs';
import { TextureManager } from './texture-manager.mjs';

// EXACT copy of render_hudq.mjs buildHudTA (order = the replay.html strip-order, default 0,1,2,3).
export function buildHudTA(quads, order = [0, 1, 2, 3]) {
  const buf = new Uint8Array(quads.length * 160 + 32);
  const dv = new DataView(buf.buffer); let o = 0; const Z = 1.0;
  for (const q of quads) {
    const textured = (q.pcw >> 3) & 1;
    let pcw = (4 << 29) | (2 << 24) | (q.pcw & 0x00FFFFFF);
    pcw = (pcw & ~(3 << 4)) | (0 << 4);
    pcw = (pcw & ~1) | 0;
    dv.setUint32(o, pcw, true);
    dv.setUint32(o + 4, q.isp, true);
    dv.setUint32(o + 8, q.tsp, true);
    dv.setUint32(o + 12, textured ? q.tcw : 0, true);
    dv.setUint32(o + 16, 0, true); dv.setUint32(o + 20, 0, true); dv.setUint32(o + 24, 0, true); dv.setUint32(o + 28, 0, true);
    o += 32;
    for (let k = 0; k < 4; k++) {
      const i = order[k], eos = (k === 3) ? 1 : 0;
      dv.setUint32(o, (7 << 29) | (eos << 28), true);
      dv.setFloat32(o + 4, q.x[i], true);
      dv.setFloat32(o + 8, q.y[i], true);
      dv.setFloat32(o + 12, Z, true);
      dv.setFloat32(o + 16, textured ? q.u[i] : 0, true);
      dv.setFloat32(o + 20, textured ? q.v[i] : 0, true);
      dv.setUint32(o + 24, q.col[i] >>> 0, true);
      dv.setUint32(o + 28, 0, true);
      o += 32;
    }
  }
  dv.setUint32(o, 0, true); o += 32;
  return buf.subarray(0, o);
}

// synthSnap / makeRT — verbatim from render_hudq.mjs.
function synthSnap(w, h) { const s = new Uint32Array(16); const tx = (Math.round(w / 32) - 1) & 0x3F, ty = (Math.round(h / 32) - 1) & 0x3F; s[0] = tx | (ty << 16); return s; }

export class HudPvr2 {
  // device = a GPUDevice (Dawn in Node, navigator.gpu device in browser). W/H = HUD canvas size.
  constructor(device, W = 640, H = 480) {
    this.dev = device; this.W = W; this.H = H;
    this.R = new PVR2Renderer(); this.R.dev = device; this.R.fmt = 'rgba8unorm'; this.R._init(W, H);
    this.T = new TextureManager(device);
    this.rt = this._makeRT(W, H);
    this._paletteKey = null;
  }
  _makeRT(w, h) {
    const c = this.dev.createTexture({ size: [w, h], format: this.R.fmt, usage: GPUTextureUsage.RENDER_ATTACHMENT | GPUTextureUsage.COPY_SRC | GPUTextureUsage.TEXTURE_BINDING });
    const z = this.dev.createTexture({ size: [w, h], format: 'depth32float', usage: GPUTextureUsage.RENDER_ATTACHMENT });
    return { color: c, depth: z, colorView: c.createView(), depthView: z.createView(), width: w, height: h };
  }
  // Upload the HUD's static VRAM once (frame/name/portrait textures). vram = Uint8Array (<=8MB).
  setVram(vram) { this.vram = vram; this.T.setDirtyPages(null, true); }
  // Upload the palette RAM (pvr_regs prefix) — call when it changes.
  setPalette(pvr) { this.T.updatePalette(pvr); }

  // Record the HUD render into a command encoder. Returns the encoder (caller submits).
  // quads = [{x,y,u,v,col,pcw,isp,tsp,tcw}] (HUDQ shape). Renders the TRANSLUCENT HUD pass only.
  render(quads, order = [0, 1, 2, 3]) {
    const ta = buildHudTA(quads, order);
    const parsed = new TAParser().parse(ta, ta.length);
    const snap = synthSnap(this.W, this.H);
    // transparentClear: the offscreen RT clears to (0,0,0,a=0) so every pixel the HUD does
    // NOT draw stays fully transparent. Without this the RT clears to OPAQUE black (a=1) and
    // the readback paints black over the whole 640x480 — the "HUD covers the fighters" bug
    // that forced play_state.html/gpu.html to hide the HUD canvas. With it, the readback is a
    // clean straight-alpha HUD sprite that alpha-composites OVER the bodies (renderHudRGBA
    // un-premultiplies so putImageData/drawImage and manual composites are both correct).
    this.R.renderFrame(parsed, this.T, snap, this.vram,
      { singlePass: true, noSort: true, transparentClear: true,
        drawOpaque: false, drawPunch: false, drawTrans: true }, this.rt);
    return this.R._lastEncoder;
  }
  get colorTexture() { return this.rt.color; }
}

// ============================================================================
// LIVE tape -> HUDQ quads. Clones the baked quads (hud_quads.json, which carries the RAW pvr
// words) and PERTURBS only the dynamic bits, then feeds buildHudTA -> pvr2 (byte-exact renderer):
//   • bar quads (cls='bar'): RESHAPE the inner x by live hp (gstaBuildHudTA inner-edge move) and
//     RECOLOR the fill's team corners by the point char's team-slot color; hit-flash brightens col.
//   • portraits/names: stay in VRAM (see injectPortraits — DM01 faces are written into the HUD VRAM
//     so the correct per-tape face renders through pvr2, not the capture roster).
// opts.verbatim -> no perturbation (reproduce the capture; used by the gate).
const HP_MAX = 144, P1_SLOTS = [0, 2, 4], P2_SLOTS = [1, 3, 5];
// team inner-stop ARGB (loc_8c15FFB0 oracle stops): C1 magenta / C2 green / C3 cyan.
const TEAM_INNER = [0xfefe3ffe, 0xfe00fe00, 0xfe00bffe];
// portrait VRAM byte-addrs by [side][visual row] (CONFIRMED HUDQ quads [3][15][27]=P1, [9][21][33]=P2).
export const PORTRAIT_ADDR = [[0x4ef000, 0x4ef800, 0x4f0000], [0x4f2000, 0x4f2800, 0x4f3000]];

function orderSide(slots, sideSlots) { const on = [], off = []; for (const s of sideSlots) ((slots[s] && slots[s].active) ? on : off).push(s); return on.concat(off); }

export function buildHudQuads(baseQuads, state, opts = {}) {
  const slots = state.slots || [];
  const p1 = orderSide(slots, P1_SLOTS), p2 = orderSide(slots, P2_SLOTS);
  const pointCol = (ss) => { for (let i = 0; i < ss.length; i++) if (slots[ss[i]] && slots[ss[i]].active) return i; return 0; };
  const sideTeam = [TEAM_INNER[pointCol(P1_SLOTS)], TEAM_INNER[pointCol(P2_SLOTS)]];
  const out = [];
  const barPos = {};   // `${side}_${row}` -> { fill: outIdx, chip: outIdx }  (for the draw-order swap)
  for (const bq of baseQuads) {
    const q = { x: bq.x.slice(), y: bq.y.slice(), u: bq.u.slice(), v: bq.v.slice(),
                col: bq.col.map(c => parseInt(c, 16) >>> 0),
                pcw: parseInt(bq.pcw, 16) >>> 0, isp: parseInt(bq.isp, 16) >>> 0,
                tsp: parseInt(bq.tsp, 16) >>> 0, tcw: parseInt(bq.tcw, 16) >>> 0 };
    if (opts.verbatim) { out.push(q); continue; }
    if (bq.cls === 'bar') {
      const slot = bq.side === 0 ? p1[Math.min(2, bq.row)] : p2[Math.min(2, bq.row)];
      const e = slots[slot];
      if (e) {
        // TWO-LAYER LIFE BAR (real capture, hud_quads.json): the yellow→team gradient
        // 'fill' quad (col 0xfefefe00 outer / 0xfefe3ffe team inner) = CURRENT health;
        // the solid-red 'chip' quad (col 0xfffe0000) = the RECOVERABLE / recently-lost
        // health BEHIND it. Tape-confirmed red_hp >= hp always (8086 red>hp, 0 red<hp over
        // this tape), so the red 'chip' is the WIDER background and the yellow 'fill' the
        // narrower foreground. Size each by its OWN quantity (chip=red_hp, fill=hp) — the
        // old code sized BOTH by hp so red covered yellow 1:1 = the "only red shows" bug.
        const hpFrac  = Math.max(0, Math.min(1, (e.hp  | 0) / HP_MAX));
        const redFrac = Math.max(0, Math.min(1, (e.red | 0) / HP_MAX));
        const frac = (bq.sub === 'chip') ? redFrac : hpFrac;
        let minx = q.x[0], maxx = q.x[0]; for (let k = 1; k < 4; k++) { if (q.x[k] < minx) minx = q.x[k]; if (q.x[k] > maxx) maxx = q.x[k]; }
        if (bq.side === 0) { const inner = minx + (maxx - minx) * frac; for (let k = 0; k < 4; k++) if (q.x[k] > minx + 0.5) q.x[k] = inner; }
        else { const inner = maxx - (maxx - minx) * frac; for (let k = 0; k < 4; k++) if (q.x[k] < maxx - 0.5) q.x[k] = inner; }
        if (bq.sub === 'fill') {
          const tc = sideTeam[bq.side] & 0x00ffffff;
          for (let k = 0; k < 4; k++) { const c = q.col[k], r = (c >> 16) & 255, g = (c >> 8) & 255, b = c & 255;
            const isWarm = b < 40 && r > 200 && g > 200; if (!isWarm) q.col[k] = ((c & 0xff000000) | tc) >>> 0; }
        }
        const fl = e.hitFlash || 0;
        if (fl > 0) for (let k = 0; k < 4; k++) { const c = q.col[k]; let r = (c >> 16) & 255, g = (c >> 8) & 255, b = c & 255;
          r += (255 - r) * fl; g += (255 - g) * fl; b += (255 - b) * fl;
          q.col[k] = (((c & 0xff000000) >>> 0) | ((r & 255) << 16) | ((g & 255) << 8) | (b & 255)) >>> 0; }
      }
      const key = `${bq.side}_${bq.row}`;
      (barPos[key] || (barPos[key] = {}))[bq.sub] = out.length;
    }
    out.push(q);
  }
  // DRAW ORDER: the yellow 'fill' (current hp) must composite OVER the red 'chip'
  // (recoverable loss). In the baked capture 'fill' precedes 'chip' in the quad list, so the
  // translucent painter's pass draws chip LAST = on top = the all-red bug. Swap the two array
  // slots per (side,row) so 'chip' draws first and 'fill' lands over it — leaves every
  // frame/portrait/name quad untouched (out index == baseQuads index; only the pair swaps).
  for (const k in barPos) {
    const b = barPos[k];
    if (b.fill != null && b.chip != null && b.fill < b.chip) {
      const t = out[b.fill]; out[b.fill] = out[b.chip]; out[b.chip] = t;
    }
  }
  return out;
}

// ── DM01 portrait injection into the HUD VRAM (32x32 RGB565 twiddled @ PORTRAIT_ADDR). Writes the
// correct per-tape face so pvr2 renders it (not the baked capture roster). `portByCid[cid]` =
// {w,h,data:RGBA}.
//
// ORIENTATION (CONFIRMED, NOT guessed): the game stores ONE portrait blob per char and produces the
// per-side inward-facing look ENTIRELY in the quad UVs — P1 quads [3][15][27] carry DESCENDING u
// (0.984->0.016 => H-flip), P2 quads [9][21][33] ASCENDING u (no flip) [hud_quads.json]. Proven
// against the oracle: the capture's stored P1/P2 point textures are identical (mirror match) and
// hud_0123.png shows P1 = H-flip(stored), P2 = stored (red edge on opposite sides — scratchpad
// facing.png). Therefore injection must write the canonical face with NO per-side mirror; the UV
// asymmetry does the flip. (A per-side inject mirror double-flips P1 -> both sides face the same
// way = the "portraits look flipped" bug.) Match-independent VRAM (frame/bars/names) is untouched. ──
const _T5 = []; // twiddle LUT for 32x32
(function () { for (let y = 0; y < 32; y++) for (let x = 0; x < 32; x++) { let r = 0, s = 0, xx = x, yy = y; for (let b = 0; b < 5; b++) { r |= (yy & 1) << s++; yy >>= 1; r |= (xx & 1) << s++; xx >>= 1; } _T5[y * 32 + x] = r; } })();
function _down64to32(src, mirror) { // src {w:64,h:64,data} -> 32x32 [r,g,b][] box-avg, optional H-mirror
  const o = new Array(32 * 32);
  for (let y = 0; y < 32; y++) for (let x = 0; x < 32; x++) {
    const sx = (mirror ? (31 - x) : x) * 2, sy = y * 2; let r = 0, g = 0, b = 0;
    for (let j = 0; j < 2; j++) for (let i = 0; i < 2; i++) { const si = ((sy + j) * src.w + (sx + i)) * 4; r += src.data[si]; g += src.data[si + 1]; b += src.data[si + 2]; }
    o[y * 32 + x] = [r >> 2, g >> 2, b >> 2];
  }
  return o;
}
export function injectPortraits(vram, state, portByCid) {
  const slots = state.slots || [];
  for (let side = 0; side < 2; side++) {
    const order = orderSide(slots, side === 0 ? P1_SLOTS : P2_SLOTS);
    for (let row = 0; row < 3; row++) {
      const e = slots[order[row]]; if (!e) continue;
      const pim = portByCid[e.cid & 0xff]; if (!pim || pim.w < 64) continue;
      const cell = _down64to32(pim, false);   // NO per-side mirror — the quad UVs flip P1 (see header)
      const base = PORTRAIT_ADDR[side][row];
      for (let i = 0; i < 32 * 32; i++) {
        const [r, g, b] = cell[i]; const px = (i % 32), py = (i / 32) | 0;
        const val = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3);
        const off = base + _T5[py * 32 + px] * 2;
        if (off + 1 < vram.length) { vram[off] = val & 0xff; vram[off + 1] = (val >> 8) & 0xff; }
      }
    }
  }
}

// Node/Dawn helper: render + read back straight-alpha RGBA (Uint8Array W*H*4). Verbatim readback
// from render_hudq.mjs (handles bpr padding + bgra/rgba).
export async function renderHudRGBA(hud, quads, order = [0, 1, 2, 3]) {
  const d = hud.dev, w = hud.W, h = hud.H, fmt = hud.R.fmt;
  const enc = hud.render(quads, order);
  d.queue.submit([enc.finish()]);
  const bpr = Math.ceil(w * 4 / 256) * 256;
  const rb = d.createBuffer({ size: bpr * h, usage: GPUBufferUsage.COPY_DST | GPUBufferUsage.MAP_READ });
  const e = d.createCommandEncoder();
  e.copyTextureToBuffer({ texture: hud.rt.color }, { buffer: rb, bytesPerRow: bpr, rowsPerImage: h }, [w, h, 1]);
  d.queue.submit([e.finish()]);
  await rb.mapAsync(GPUMapMode.READ);
  const m = new Uint8Array(rb.getMappedRange()).slice(); rb.unmap(); rb.destroy();
  const out = new Uint8Array(w * h * 4); const bgra = fmt.startsWith('bgra');
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const s = y * bpr + x * 4, dd = (y * w + x) * 4;
    let r, g, b, a;
    if (bgra) { r = m[s + 2]; g = m[s + 1]; b = m[s]; a = m[s + 3]; }
    else { r = m[s]; g = m[s + 1]; b = m[s + 2]; a = m[s + 3]; }
    // UN-PREMULTIPLY: the transparent-clear translucent pass leaves rgb PREMULTIPLIED by the
    // accumulated coverage (rgb = color*a). Divide back out so `out` is TRUE straight alpha —
    // the shape putImageData()/drawImage() and the manual gate composite both assume. Opaque
    // HUD pixels (a=255) are unchanged; only fractional-alpha edges are corrected. a=0 stays 0.
    if (a > 0 && a < 255) { const inv = 255 / a; r = Math.min(255, r * inv); g = Math.min(255, g * inv); b = Math.min(255, b * inv); }
    out[dd] = r; out[dd + 1] = g; out[dd + 2] = b; out[dd + 3] = a;
  }
  return out;
}
