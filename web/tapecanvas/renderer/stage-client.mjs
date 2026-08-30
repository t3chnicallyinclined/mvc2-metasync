// ============================================================================
// stage-client.mjs — REAL 3D STG00 stage for the Steam tape render (OPTION B).
//
// Replaces the old 2D-flatten backdrop. This loads the maplecast POL rip
// (atlas/stages/STGxx.json — full 3D NAOMI world-space geometry + detwiddled
// texture PNGs, a port of ModNao's NaomiLib decoder) and renders it through the
// SAME vendored PVR2Renderer that draws the bodies, as the OP/TR background pass.
//
// PORTED VERBATIM from maplecast web/webgpu/stage-client.mjs (the _build POL path,
// _uploadTextures, the texMgr shim, STAGE_PVRSNAP, resolveStageFile). The ONLY
// change is the projection: the maplecast live path uses the engine's captured
// XMTRX (M1·M2), which is NOT on a GGPO tape. This file uses OPTION B — a
// perspective camera RECONSTRUCTED per-frame from the tape's camX/camY (schema idx
// 20/21) so the stage DECK plane coincides with the fighters' feet BY CONSTRUCTION.
//
// ── OPTION-B CAMERA (RE-grounded — sh4-re; do NOT retune these numbers) ─────────
// The tape carries eyeX/eyeY/ground at schema idx 20/21/22; ground = camY + 338.4.
// Per-frame view:
//   lookAt(eye = (camX, camY+98.4, DECK_Z-812.357),
//          target = (camX, camY+98.4, DECK_Z), up = +Y)   // horizontal, forward +Z
//   perspective focal 812.357 px  (tan(fovx/2)=320/812.357, tan(fovy/2)=240/812.357)
//   -> 640x480 viewport (cx=320, cy=240).
// A world point (Xw,Yw,Zw) with camera (camX,camY):
//   w  = (Zw - DECK_Z) + 812.357          // DECK plane (Zw=DECK_Z) => w = focal
//   sx = 320 + 812.357*(Xw - camX)/w
//   sy = 240 - 812.357*(Yw - (camY+98.4))/w
//   depth = 1/w                            // pvr2 z convention (bigger = nearer)
// On the deck plane (Zw=DECK_Z, w=812.357) this reduces to:
//   sx = 320 + (Xw - camX)                 // 1:1 horizontal pan (NO 8.3x parallax)
//   sy = (camY+338.4) - Yw = ground - Yw   // deck at Yw=0 -> sy=ground
// The fighters draw at their captured (sx,sy) = (worldX-camX+320, ground-worldY),
// so a grounded fighter (sy=ground) stands exactly on the deck (Yw=0,Zw=DECK_Z).
// Deeper meshes get perspScale = 812.357/(812.357 + (Zw-DECK_Z)) automatically:
// true parallax (sky/masts scroll less than the deck). NO zoom term (Option B; the
// eye distance is constant during play — byte-exact zoom needs Option A's M1·M2).
//
// DECK_Z: the stage's fighting-plane depth (worldY=0 deck surface). MEASURED from
// STG00.json geometry: the deck models (rip model 2 & 13 — flat, Y in [-165,314],
// Z in [-1056,1056]) are centered at Z=0, so the fighting plane is Zw=0.
// CONFIRMED (STG00.json per-model extent scan, 2026-08-29). Other stages: re-measure.
//
// USAGE (gpu.html):
//   import { PVR2Renderer } from './renderer/pvr2-renderer.mjs';
//   const stageR = new PVR2Renderer(); stageR.initShared(cstage, SG.dev);  // share body device
//   const STAGE = new StageClient('./stages'); STAGE.attachDevice(SG.dev);
//   await STAGE.setStage(stageId);
//   every frame, BEFORE bodies:  STAGE.setCamB(row[20], row[21]); STAGE.render(stageR);
// ============================================================================

const SCREEN_W = 640, SCREEN_H = 480;

// ── OPTION-B camera constants (sh4-re — RE-grounded) ──────────────────────────
const FOCAL   = 812.357;   // px. tan(fovx/2)=320/FOCAL, tan(fovy/2)=240/FOCAL (4:3)
const EYE_DY  = 98.4;      // eye Y = camY + 98.4  (=> ground = 240 + EYE_DY = camY+338.4)
const NEAR_W  = 1.0;       // near plane in view-w; verts nearer than this cull (behind cam)

// Per-stage fighting-plane depth (worldY=0 deck). STG00 measured = 0 (see header).
const DECK_Z_BY_FILE = { 0x00: 0 };
function deckZForFile(fileIdx) {
  return (fileIdx in DECK_Z_BY_FILE) ? DECK_Z_BY_FILE[fileIdx] : 0;
}

// WORLD-ASSEMBLED-MODEL selection (the "only render what is actually placed" fix).
// The rip is worldAssembled (ripped from assembled RAM): rip MODEL 0 is the full stage
// (deck + machinery + skydome), authored in true world space — it reaches skydome depth
// (STG00 model 0 minZ=-100436). rip models 1..14 are LOCAL sub-models (masts/props/backdrop
// quads) whose runtime placement matrix was NOT captured, so they sit at their local origin
// (Z~0) and CONTAMINATE the scene (cover the deck/sky). CONFIRMED by per-model render
// (2026-08-29): model 0 alone = the recognizable Airship Day deck+sky; +any other model = garble.
// Discriminator: keep only models whose geometry reaches deep Z (the skydome); local props
// never do. WORLD_MIN_Z threshold is well inside the gap (model0 -100436 vs next -1108).
const WORLD_MIN_Z = -10000;
// Optional explicit per-file allowlist (overrides the heuristic). STG00 = [0].
const WORLD_MODELS_BY_FILE = { 0x00: [0] };

// stage_id -> STGxx disc-file index (identity for the tape; CONFIRMED panel/sh4-re for STG00).
export function resolveStageFile(stageId) { return (stageId | 0) & 0xFF; }

export const STAGE_NAMES = {
  0x00:'Airship (Day)',0x01:'Desert (Orange)',0x02:'Factory',0x03:'Carnival (Summer)',
  0x04:'Swamp',0x05:'Cave (Water)',0x06:'Clocktower (Clear)',0x07:'River on Ice',
  0x08:'Abyss',0x09:'Airship (Night)',0x0A:'Desert (Blue)',0x0B:'Training',
  0x0C:'Carnival (Winter)',0x0D:'Swamp (Asian)',0x0E:'Cave (Lava)',0x0F:'Clocktower (Snowy)',
  0x10:'River on Raft',
};

// pvrSnap that makes _ndcMat produce a 640x480 viewport (tx=19,ty=14):
//   w=(tx+1)*32=640, h=(ty+1)*32=480  (matches pvr2-renderer.mjs _ndcMat).
export const STAGE_PVRSNAP = (() => {
  const s = new Uint32Array(16);
  s[0] = 19 | (14 << 16);
  return s;
})();

export class StageClient {
  constructor(base = './stages') {
    this.base = base.replace(/\/$/, '');
    this.stageId = -1;
    this.fileIdx = -1;
    this.wantId = -1;
    this._loading = false;
    this._data = null;          // decoded STGxx.json (POL rip)
    this._imgs = [];            // ImageBitmap per texture index
    this._parsed = null;        // PVR2Renderer parsed object (rebuilt on camera change)
    this._tm = null;            // texMgr shim
    this._dev = null;
    this._surrToTex = {};
    this.deckZ = 0;
    this.camX = 0; this.camY = 0;
    this.ready = false;
  }

  hexIdx() { return (this.fileIdx >= 0 ? this.fileIdx : 0).toString(16).toUpperCase().padStart(2, '0'); }

  // Lazy-load the POL rip for a stage_id (STGxx.json + STGxx_tNN.png). 404 => stays not-ready.
  async setStage(stageId) {
    if (stageId == null || stageId < 0) return false;
    if (stageId === this.stageId) return this.ready;
    this.stageId = stageId;
    this.fileIdx = resolveStageFile(stageId);
    this.deckZ = deckZForFile(this.fileIdx);
    this.wantId = this.fileIdx;
    this.ready = false; this._data = null; this._imgs = []; this._parsed = null;
    if (this._loading) return false;
    this._loading = true;
    const hx = this.hexIdx();
    const V = 'stage3d1';
    try {
      const data = await fetch(`${this.base}/STG${hx}.json?v=${V}`)
        .then(r => r.ok ? r.json() : Promise.reject(r.status));
      const imgs = await Promise.all((data.textures || []).map(async t => {
        try {
          const blob = await (await fetch(`${this.base}/${t.file}?v=${V}`)).blob();
          return await createImageBitmap(blob);
        } catch { return null; }
      }));
      this._data = data;
      this._imgs = imgs;
      this._worldModels = this._selectWorldModels(data);
      this._parsed = this._build(data);
      this._uploadTextures();
      this.ready = true;
      const nm = STAGE_NAMES[this.fileIdx] || '?';
      console.log(`[stage-client] loaded STG${hx} "${nm}" (POL 3D, Option-B cam): `
        + `${data.meshes.length} meshes, ${(data.textures||[]).length} textures, deckZ=${this.deckZ}, `
        + `worldModels=[${[...this._worldModels].join(',')}]`);
    } catch (e) {
      console.warn(`[stage-client] failed to load stage ${hx}`, e);
      this.ready = false;
    } finally { this._loading = false; }
    return this.ready;
  }

  // Choose which rip MODELS to render: the world-assembled stage only (see WORLD_MIN_Z note).
  // Explicit per-file allowlist wins; else keep models whose min vertex Z reaches deep (skydome).
  _selectWorldModels(data) {
    if (this.fileIdx in WORLD_MODELS_BY_FILE) return new Set(WORLD_MODELS_BY_FILE[this.fileIdx]);
    const minZ = new Map();
    for (const m of data.meshes) {
      let mz = minZ.has(m.model) ? minZ.get(m.model) : Infinity;
      for (const tri of m.tris) for (const v of tri) if (v.pos[2] < mz) mz = v.pos[2];
      minZ.set(m.model, mz);
    }
    const keep = new Set();
    for (const [model, mz] of minZ) if (mz < WORLD_MIN_Z) keep.add(model);
    if (keep.size === 0) for (const k of minZ.keys()) keep.add(k);   // fallback: keep all
    return keep;
  }

  // ── OPTION-B camera: set per-frame camX/camY (tape idx 20/21) and re-project ──
  // Returns true if a re-projection happened. No-op when camera is unchanged.
  setCamB(camX, camY) {
    camX = +camX || 0; camY = +camY || 0;
    if (camX === this.camX && camY === this.camY && this._parsed) return false;
    this.camX = camX; this.camY = camY;
    if (this._data) { this._parsed = this._build(this._data); return true; }
    return false;
  }

  // world(Xw,Yw,Zw) -> [screenX_px, screenY_px, depth=1/w]  OR null (culled: at/behind near).
  // OPTION-B pinhole (see header). deckZ pins the fighting plane to w=FOCAL.
  // FORWARD is -Z: the STG00 POL rip's Z is NEGATED vs the engine runtime Z the sh4-re camera
  // assumed (NaomiLib handedness). "Into the screen" = more-negative Zw, so the deck floor
  // (rip Z ~0..-6882) and skydome (rip Z ~-100436) recede correctly instead of being culled
  // behind a +Z eye. w = FOCAL + (deckZ - Zw); deck plane (Zw=deckZ) => w=FOCAL (unchanged).
  // The deck-pin (screenY/screenX at the plane) is independent of the Z sign — only depth flips.
  _projectB(x, y, z) {
    const w = FOCAL + (this.deckZ - z);       // forward -Z; deck plane => w = FOCAL
    if (!(w > NEAR_W)) return null;           // at/behind the near plane -> cull
    const sx = 320 + FOCAL * (x - this.camX) / w;
    const sy = 240 - FOCAL * (y - (this.camY + EYE_DY)) / w;
    return [sx, sy, 1 / w];
  }

  // Build the PVR2Renderer parsed object. POL path (ported from maplecast _build),
  // projecting every world vert through the Option-B camera; a triangle is dropped
  // atomically if any vertex culls (behind near) or lands past a sane viewport margin.
  _build(data) {
    let triTotal = 0;
    for (const m of data.meshes) triTotal += m.tris.length;
    const vcount = triTotal * 3;
    const vbuf = new ArrayBuffer(vcount * 28);
    const vf = new Float32Array(vbuf);
    const vb = new Uint8Array(vbuf);
    const opaque = [], translucent = [];
    let vi = 0;

    const surrByTex = new Map();   // texIndex -> surrogate int key (1-based)
    this._surrToTex = {};          // surrogate -> texIndex (for texMgr)

    const writeVtx = (n, x, y, z, col, u, v) => {
      const fo = n * 7, bo = n * 28;
      vf[fo] = x; vf[fo + 1] = y; vf[fo + 2] = z;
      vb[bo + 12] = col[0]; vb[bo + 13] = col[1]; vb[bo + 14] = col[2]; vb[bo + 15] = col[3];
      vb[bo + 16] = 0; vb[bo + 17] = 0; vb[bo + 18] = 0; vb[bo + 19] = 0; // spc
      vf[fo + 5] = u; vf[fo + 6] = v;
    };

    // Sanity margin: legit large off-screen tris (a ground plane's near corners can
    // project far past 640x480; the GPU rasterizer clips them). Only reject the true
    // ±millions un-projection garbage. (maplecast _buildFromTA SANITY=100000.)
    const SANITY = 100000;
    const onScreen = (p) => Number.isFinite(p[0]) && Number.isFinite(p[1])
      && Math.abs(p[0]) <= SANITY && Math.abs(p[1]) <= SANITY;

    const worldModels = this._worldModels || null;
    for (const m of data.meshes) {
      if (!m.tris.length) continue;
      if (m.placed === false) continue;                 // unplaced local prop (no world matrix) — skip
      if (worldModels && !worldModels.has(m.model)) continue;   // skip local sub-models (uncaptured runtime matrix)
      const textured = (m.texIndex < data.textures.length) ? 1 : 0;
      let surr = 0;
      if (textured) {
        surr = surrByTex.get(m.texIndex);
        if (surr === undefined) { surr = surrByTex.size + 1; surrByTex.set(m.texIndex, surr); this._surrToTex[surr] = m.texIndex; }
      }
      const alpha = (m.alpha === undefined) ? 1 : m.alpha;
      const isTrans = (!m.isOpaque) || alpha < 0.999;
      const c255 = (f) => Math.max(0, Math.min(255, Math.round((f ?? 1) * 255)));
      const meshTint = (!textured && !m.hasColor && Array.isArray(m.color))
        ? [c255(m.color[0]), c255(m.color[1]), c255(m.color[2]), 255] : null;

      // PVR control words (synthesized — same as maplecast _build):
      //   pcw: paraType=4, textured bit3, gouraud bit1
      const pcw = (4 << 29) | (textured << 3) | (1 << 1);
      let wrapBits = 0;
      if (m.wrap) {
        if (m.wrap.hFlip) wrapBits |= (1 << 18);            // FlipU
        else if (!m.wrap.hRepeat) wrapBits |= (1 << 16);    // ClampU
        if (m.wrap.vFlip) wrapBits |= (1 << 17);            // FlipV
        else if (!m.wrap.vRepeat) wrapBits |= (1 << 15);    // ClampV
      }
      const tsp = wrapBits | (isTrans
        ? ((4 << 29) | (5 << 26) | (1 << 20) | (1 << 6))    // src-a / 1-src-a, useAlpha, modulate
        : ((1 << 29) | (0 << 26) | (1 << 6)));              // ONE/ZERO, modulate
      const isp = isTrans
        ? ((6 << 29) | (0 << 27) | (1 << 26))               // dm=ge, cull none, zwrite-dis
        : ((6 << 29) | (0 << 27) | (0 << 26));              // dm=ge, cull none, zwrite on

      for (const tri of m.tris) {
        // project all 3 verts first so we can reject the tri atomically
        const fv = [];
        let ok = true;
        for (const v of tri) {
          const p = this._projectB(v.pos[0], v.pos[1], v.pos[2]);
          if (!p || !onScreen(p)) { ok = false; break; }
          let col = meshTint || v.col || [255, 255, 255, 255];
          if (alpha < 0.999) col = [col[0], col[1], col[2], Math.round((col[3] ?? 255) * alpha)];
          fv.push([p[0], p[1], p[2], col, v.uv[0], v.uv[1]]);
        }
        if (!ok) continue;
        const first = vi;
        for (const f of fv) writeVtx(vi++, f[0], f[1], f[2], f[3], f[4], f[5]);
        (isTrans ? translucent : opaque).push({ first, count: 3, isp, tsp, tcw: surr, pcw, tileclip: 0 });
      }
    }

    return { vertexData: vb.subarray(0, vi * 28), vertexCount: vi,
             opaque, punchThrough: [], translucent };
  }

  // ── texMgr shim (PVR2Renderer protocol): surrogate tcw -> GPUTexture ──────────
  attachDevice(dev) { this._dev = dev; if (this._data) this._uploadTextures(); }

  _uploadTextures() {
    const dev = this._dev;
    if (!dev || !this._data) return;
    const texByIdx = new Map();   // texIndex -> {texture, sampler, samplers:{}, w, h}
    for (let i = 0; i < this._imgs.length; i++) {
      const img = this._imgs[i];
      if (!img) continue;
      const w = img.width, h = img.height;
      const texture = dev.createTexture({ size: [w, h], format: 'rgba8unorm',
        usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST | GPUTextureUsage.RENDER_ATTACHMENT });
      dev.queue.copyExternalImageToTexture({ source: img }, { texture }, [w, h]);
      texByIdx.set(i, { texture, samplers: {}, w, h });
    }
    let fb = null;
    const surrToTex = this._surrToTex || {};
    this._tm = {
      getFallbackTexture() {
        if (fb) return fb;
        const t = dev.createTexture({ size: [1, 1], format: 'rgba8unorm',
          usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST });
        dev.queue.writeTexture({ texture: t }, new Uint8Array([255, 255, 255, 255]), { bytesPerRow: 4 }, [1, 1]);
        fb = { texture: t, sampler: dev.createSampler({ minFilter: 'nearest', magFilter: 'nearest' }) };
        return fb;
      },
      getTexture(tsp, surr) {
        if (!surr) return null;
        const ti = surrToTex[surr];
        if (ti === undefined) return null;
        const e = texByIdx.get(ti);
        if (!e) return null;
        // TSP wrap bits (core/hw/pvr/ta_structs.h; extraction identical to texture-manager.mjs).
        const cu = (tsp >> 16) & 1, cv = (tsp >> 15) & 1;
        const fu = (tsp >> 18) & 1, fv = (tsp >> 17) & 1;
        const wu = cu ? 'clamp-to-edge' : fu ? 'mirror-repeat' : 'repeat';
        const wv = cv ? 'clamp-to-edge' : fv ? 'mirror-repeat' : 'repeat';
        const key = wu + '|' + wv;
        let s = e.samplers[key];
        if (!s) s = e.samplers[key] = dev.createSampler({ minFilter: 'linear',
          magFilter: 'linear', addressModeU: wu, addressModeV: wv });
        return { texture: e.texture, sampler: s, w: e.w, h: e.h };
      },
    };
  }

  // ── render: draw the stage OP+TR layer (behind chars) via the shared pvr2 ──────
  render(renderer) {
    if (!renderer || !this._parsed || !this._tm || !this._parsed.vertexCount) return false;
    renderer.renderFrame(this._parsed, this._tm, STAGE_PVRSNAP, null,
      { singlePass: true, noSort: true, transparentClear: true,
        drawOpaque: true, drawPunch: false, drawTrans: true });
    return true;
  }

  get texMgr() { return this._tm; }
  get parsed() { return this._parsed; }
}

// ============================================================================
// STATUS (Option B, 2026-08-29):
//   • Real 3D STG00 (POL rip) rendered through the vendored pvr2 as the OP/TR bg pass.
//   • Camera reconstructed from tape camX/camY (idx 20/21): deck pinned to the fighters'
//     feet BY CONSTRUCTION (deck plane -> screenY=ground, worldX 1:1 with camX pan).
//   • True depth parallax between deck/masts/sky via perspScale=FOCAL/(FOCAL+Zw).
// FOLLOW-UP (Option A, byte-exact): persist M1@0x8C2D6B18·M2@0x8C2D6AD8 on the tape and
//   swap _projectB for the engine XMTRX (maplecast setCamera path) — removes the no-zoom
//   approximation on strong-zoom frames. Also: the far skydome (rip model 0, Z<-812 behind
//   the Option-B eye) is near-plane culled; a byte-exact XMTRX or a camera-locked sky quad
//   restores the full backdrop. Other stages: measure DECK_Z + confirm STAGE_ID.
// ============================================================================
