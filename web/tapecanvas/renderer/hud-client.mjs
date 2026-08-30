// ============================================================================
// hud-client.mjs — tape-driven MVC2 HUD, rendered through the REAL pvr2 rasterizer.
//
// This is a THIN ORCHESTRATOR over renderer/hud-pvr2.mjs (the vendored pvr2-renderer.mjs — the
// exact TA rasterizer that produced the ground-truth _hud_cap_def/hud_0123.png; a Dawn gate
// reproduces it BYTE-EXACT, 0.00/px). We do NOT software-rasterize the HUD anymore — the prior
// rasterQuadList was a wheel-reinvention and is deleted.
//
// PER FRAME:
//   1. buildHudQuads(state)  — clone the baked HUDQ quads (hud/hud_quads.json, raw pvr words),
//      RESHAPE bar x by live hp, RECOLOR the fill by team, hit-flash brighten (hud-pvr2.mjs).
//   2. injectPortraits(vram,state) — write the tape's DM01 faces into the HUD VRAM (on roster
//      change) so the CORRECT per-char face renders through pvr2 (not the capture roster).
//   3. pvr2 render -> RGBA -> the HUD canvas.
//   4. digits (TIME / combo / LEVEL) + super meters as a 2D overlay from the REAL FONT.BIN atlas
//      (hud/font/font.png) — these are NOT in the top-band HUDQ capture; positions flagged (§7).
//
// STATIC HUD VRAM/palette (hud/hud_vram.bin + hud/hud_pal.bin) are baked by rip_hud_quads.py
// from the capture (ROM-derived -> gitignore/scp-only). The tape carries no HUD VRAM, so the
// frame/bars/names come from this match-independent slab; portraits are injected per tape char.
// ============================================================================

import { HudPvr2, buildHudQuads, injectPortraits, renderHudRGBA } from './hud-pvr2.mjs';

const P1_SLOTS = [0, 2, 4], P2_SLOTS = [1, 3, 5];
const TEAM_HEX = ['#fe3ffe', '#00fe00', '#00bffe'];   // C1/C2/C3 for the meter tint
const clamp01 = v => v < 0 ? 0 : (v > 1 ? 1 : v);

export const NAMES = {
  0x00:'RYU',0x01:'ZANGIEF',0x02:'GUILE',0x03:'MORRIGAN',0x04:'ANAKARIS',0x05:'STRIDER',
  0x06:'CYCLOPS',0x07:'WOLVERINE',0x08:'PSYLOCKE',0x09:'ICEMAN',0x0A:'ROGUE',
  0x0B:'CAPT.AMERICA',0x0C:'SPIDER-MAN',0x0D:'HULK',0x0E:'VENOM',0x0F:'DR.DOOM',
  0x10:'TRON',0x11:'JILL',0x12:'HAYATO',0x13:'RUBY HEART',0x14:'SONSON',0x15:'AMINGO',
  0x16:'MARROW',0x17:'CABLE',0x18:'ABYSS',0x19:'ABYSS',0x1A:'ABYSS',0x1B:'CHUN-LI',
  0x1C:'MEGA MAN',0x1D:'ROLL',0x1E:'AKUMA',0x1F:'B.B.HOOD',0x20:'FELICIA',0x21:'CHARLIE',
  0x22:'SAKURA',0x23:'DAN',0x24:'CAMMY',0x25:'DHALSIM',0x26:'M.BISON',0x27:'KEN',
  0x28:'GAMBIT',0x29:'JUGGERNAUT',0x2A:'STORM',0x2B:'SABRETOOTH',0x2C:'MAGNETO',
  0x2D:'SHUMA',0x2E:'WAR MACHINE',0x2F:'SILVER SAMURAI',0x30:'OMEGA RED',0x31:'SPIRAL',
  0x32:'COLOSSUS',0x33:'IRON MAN',0x34:'SENTINEL',0x35:'BLACKHEART',0x36:'THANOS',
  0x37:'JIN',0x38:'CAPT.COMMANDO',0x39:'WOLVERINE',0x3A:'SERVBOT',
};

export class HudClient {
  constructor(base) {
    this.base = base;
    this.ready = false;
    this.baseQuads = null;      // hud_quads.json quads (raw pvr words + cls/side/row/sub)
    this.vram = null;           // sparse 8 MiB HUD VRAM (frame/bars/names + injected portraits)
    this.pal = null;            // palette RAM (pvr_regs prefix)
    this.portByCid = {};        // char_id -> {w,h,data} DM01 face (for injection)
    this.font = null;           // {img, rects} FONT.BIN digit atlas
    this.hud = null;            // HudPvr2 (needs a GPUDevice — set via initGpu)
    this._rosterKey = null;     // re-inject portraits only when the visible roster changes
    this._off = null;           // offscreen 640x480 canvas for the pvr2 RGBA + overlays
  }
  resetAnim() { this._rosterKey = null; }   // force a portrait re-inject on the next frame

  async load() {
    const V = 'pvr2hud1';
    this.baseQuads = (await fetch(new URL(`hud_quads.json?v=${V}`, this.base)).then(r => r.json())).quads;
    // static HUD VRAM slab + palette -> reconstruct the sparse 8 MiB vram array
    const vmeta = await fetch(new URL(`hud_vram.json?v=${V}`, this.base)).then(r => r.json());
    const [slabBuf, palBuf] = await Promise.all([
      fetch(new URL(`hud_vram.bin?v=${V}`, this.base)).then(r => r.arrayBuffer()),
      fetch(new URL(`hud_pal.bin?v=${V}`, this.base)).then(r => r.arrayBuffer()),
    ]);
    this.vram = new Uint8Array(vmeta.vramSize);
    this.vram.set(new Uint8Array(slabBuf), vmeta.base);
    this.pal = new Uint8Array(palBuf);
    // DM01 portraits (47 real; 9 blank — CONFIRMED no unique static cell, never a monogram)
    try {
      const [pm, pi] = await Promise.all([
        fetch(new URL(`portraits/portraits.json?v=${V}`, this.base)).then(r => r.json()),
        this._img(new URL(`portraits/portraits.png?v=${V}`, this.base)),
      ]);
      const pd = this._imgData(pi);
      for (const k in pm.rects) this.portByCid[parseInt(k, 10)] = this._subTex(pd, pm.rects[k]);
    } catch (e) { /* portraits absent -> capture-roster faces from VRAM */ }
    // real FONT.BIN digits
    try {
      const [fm, fi] = await Promise.all([
        fetch(new URL(`font/font.json?v=${V}`, this.base)).then(r => r.json()),
        this._img(new URL(`font/font.png?v=${V}`, this.base)),
      ]);
      this.font = { img: fi, rects: fm.rects };
    } catch (e) { this.font = null; }
    this.ready = true;
    return this.ready;
  }

  // Give the HUD a GPUDevice (share the body renderer's device). Call after load() + device create.
  initGpu(device) {
    this.hud = new HudPvr2(device, 640, 480);
    this.hud.setVram(this.vram);
    this.hud.setPalette(this.pal);
  }

  _img(u) { return new Promise((res, rej) => { const im = new Image(); im.onload = () => res(im); im.onerror = () => rej('img'); im.src = u.href || u; }); }
  _imgData(img) { const c = document.createElement('canvas'); c.width = img.width; c.height = img.height; const x = c.getContext('2d'); x.imageSmoothingEnabled = false; x.drawImage(img, 0, 0); return { w: img.width, h: img.height, data: x.getImageData(0, 0, img.width, img.height).data }; }
  _subTex(atlas, r) { const w = r.w, h = r.h, data = new Uint8Array(w * h * 4); for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { const si = ((r.y + y) * atlas.w + (r.x + x)) * 4, di = (y * w + x) * 4; for (let k = 0; k < 4; k++) data[di + k] = atlas.data[si + k]; } return { w, h, data }; }

  // ── TAPE-DRIVEN FRAME (async — pvr2 render + readback). Draws the HUD onto `ctx` (2D). ──
  async renderState(ctx, state) {
    if (!ctx) return;
    const W = ctx.canvas.width, H = ctx.canvas.height;
    if (!state || !state.inMatch || !this.ready || !this.hud) { ctx.clearRect(0, 0, W, H); return; }
    // pvr2 render + GPU readback is async; the tape loop calls this fire-and-forget. Drop overlapping
    // frames (the HUD shows the last completed frame) so bursts never queue up multiple readbacks.
    if (this._busy) return; this._busy = true;
    try { await this._renderInner(ctx, state, W, H); } finally { this._busy = false; }
  }
  async _renderInner(ctx, state, W, H) {
    // re-inject DM01 faces only when the visible roster changes (cheap; avoids per-frame VRAM churn)
    const rk = (state.slots || []).map(s => `${s.active ? 1 : 0}:${s.cid & 0xff}`).join(',');
    if (rk !== this._rosterKey) {
      injectPortraits(this.vram, state, this.portByCid);
      this.hud.setVram(this.vram);            // re-dirty -> pvr2 re-decodes the portrait textures
      this._rosterKey = rk;
    }
    const quads = buildHudQuads(this.baseQuads, state, {});
    const rgba = await renderHudRGBA(this.hud, quads);   // real pvr2 render, straight-alpha RGBA
    // blit onto a 640x480 offscreen (so a non-640 ctx still scales via drawImage), then overlays
    if (!this._off) { this._off = document.createElement('canvas'); this._off.width = 640; this._off.height = 480; }
    const ox = this._off.getContext('2d');
    ox.putImageData(new ImageData(new Uint8ClampedArray(rgba.buffer, rgba.byteOffset, rgba.byteLength), 640, 480), 0, 0);
    this._overlays(ox, state);
    ctx.clearRect(0, 0, W, H);
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(this._off, 0, 0, W, H);
  }

  // Digits (TIME / combo / LEVEL) + super meters — REAL FONT.BIN glyphs + gouraud meter quads.
  // FLAG (§7): positions are the re_kb/27 estimates; the timer/combo/meter are NOT in the y<=112
  // HUDQ capture band. DERIVABLE now: timer x-center ~320 (the gap between the P1/P2 bar assemblies).
  // Needs one full-band (BAND_H=480) HUDQ capture with a running timer + built meter + active combo.
  _overlays(ctx, state) {
    const tv = Math.max(0, Math.min(99, state.timer | 0));
    this._digits(ctx, String(tv).padStart(2, '0'), 320, 8, 20, 'center');
    const MT_OY = 460, MT_H = 8, MT_LEN = 232, MT_SKEW = 9;
    const ci1 = this._pointIdx(state, P1_SLOTS), ci2 = this._pointIdx(state, P2_SLOTS);
    const m1 = state.p1 || {}, m2 = state.p2 || {};
    this._meter(ctx, 20, MT_OY, MT_LEN, MT_H, MT_SKEW, false, clamp01((m1.lvl || 0) / 5), TEAM_HEX[ci1]);
    this._meter(ctx, 620, MT_OY, MT_LEN, MT_H, MT_SKEW, true, clamp01((m2.lvl || 0) / 5), TEAM_HEX[ci2]);
    this._digits(ctx, String(Math.max(0, Math.min(8, m1.lvl | 0))), 8, MT_OY - 10, 11, 'left');
    this._digits(ctx, String(Math.max(0, Math.min(8, m2.lvl | 0))), 632, MT_OY - 10, 11, 'right');
    if ((m1.combo | 0) > 1) this._digits(ctx, String(m1.combo | 0), 20, 44, 16, 'left');
    if ((m2.combo | 0) > 1) this._digits(ctx, String(m2.combo | 0), 620, 44, 16, 'right');
  }
  _pointIdx(state, sideSlots) { for (let i = 0; i < sideSlots.length; i++) { const e = (state.slots || [])[sideSlots[i]]; if (e && e.active) return i; } return 0; }
  _digits(ctx, str, x, y, dh, align) {
    if (!this.font) return 0;
    const adv = Math.round(dh * 0.72), total = str.length * adv;
    let cx = align === 'right' ? x - total : (align === 'center' ? Math.round(x - total / 2) : x);
    for (const ch of str) { const r = this.font.rects['digit_' + ch]; if (r) { ctx.imageSmoothingEnabled = false; ctx.drawImage(this.font.img, r.x, r.y, r.w, r.h, cx, y, adv - 1, dh); } cx += adv; }
    return total;
  }
  _meter(ctx, ox, oy, len, h, skew, mirror, fillFrac, teamHex) {
    const dir = mirror ? -1 : 1;
    const quad = (l0, l1, style) => { ctx.beginPath(); ctx.moveTo(ox + dir * l0, oy); ctx.lineTo(ox + dir * l1, oy); ctx.lineTo(ox + dir * (l1 + skew), oy + h); ctx.lineTo(ox + dir * (l0 + skew), oy + h); ctx.closePath(); ctx.fillStyle = style; ctx.fill(); };
    quad(0, len, '#15181e');
    const f = clamp01(fillFrac);
    if (f > 0) { const g = ctx.createLinearGradient(ox, 0, ox + dir * len * f, 0); g.addColorStop(0, teamHex); g.addColorStop(1, '#ffff00'); quad(0, len * f, g); }
  }
}
