// ============================================================================
// stage-client.mjs — VENDORED 2D-scrolled STAGE BACKDROP for the Steam tape render.
//
// The maplecast web/webgpu/stage-client.mjs renders the stage as full 3D NAOMI geometry
// (STGxxPOL/TEX) through PVR2Renderer, driven by the engine's LIVE camera matrices
// (M1@0x8C2D6B18 / M2@0x8C2D6AD8). Those matrices are NOT on a GGPO tape (the tape carries
// only camX/camY 2D pan), so the byte-exact 3D path can't run here. Instead the tape stage
// is a 2D-SCROLLED BACKDROP: a stage snapshot baked OFFLINE at a fixed fight camera
// (bake_stage_backdrop.py, projecting the POL/TEX rip's placed meshes to one flat strip),
// then scrolled at runtime by the tape's camX/camY. The fighters already place with
//   screenX = worldX - camX + 320,  screenY = (camY + 338.4) - worldY   (ground = camY+338.4;
//   camX=blk+0x6914=tape eyeX, camY=blk+0x6918=tape eyeY; CONFIRMED panel/sh4-re). So the
// backdrop scrolls the SAME way (offsetX = -camX*parallax, offsetY = +camY*parallax) and
// tracks the fighters with zero live-camera capture.
//
// FIDELITY (honest): FIRST-PASS. The snapshot is a fixed-projection flatten of the whole
// world-assembled airship (STG00 = 15 models, all placed — NOT deck-only), so it reads as
// the real Air Ship (Day) stage with sky. What it is NOT: per-frame camera-matched, and it
// has NO true multi-layer parallax (deck + sky translate together by one `parallax`). The
// fuller path is the maplecast 3D PVR2 chain with captured M1·M2 — future work.
//
// ── ASSET CONTRACT (baked by bake_stage_backdrop.py, vendored under ./stages/) ──────────
//   stages/STG<xx>_bg.png : the flat backdrop snapshot (imgW x 480). Wider than 640 so
//                           horizontal pan has margin; the bgColor backstops the edges.
//   stages/STG<xx>.json   : { stage_id, file, name, imgW, imgH, groundImgY, parallax,
//                             bgColor:[r,g,b], camRefX?, camRefY?, fidelity }
//       imgW/imgH   backdrop image size (px). groundImgY = the deck's row in the image.
//       parallax    scroll multiplier vs camX/camY (0=locked static, 1=1:1 with fighters).
//       bgColor     sky/edge fill so no black ever shows past the strip.
//       camRefX/Y   the camX/camY the snapshot was framed at (scroll is relative to these).
//
// USAGE (gpu.html):
//   const stage = new StageClient('./stages');
//   await stage.setStage(stageId);                 // lazy-load STGxx.json/_bg.png (404 = no-op)
//   every frame, BEFORE bodies:  stage.render(ctx2d, { camX, camY, ground });
// ============================================================================

const SCREEN_W = 640, SCREEN_H = 480;
const GROUND_OFFSET = 338.4;   // ground = camY + 338.4 (tape `ground` field / camera note)

// stage_id -> STGxx disc-file index. CONFIRMED (panel/sh4-re): STG_ID is a clean 0-based
// identity index into the STGxx disc files (global 0x8c26A95C; Steam blk+0x6D3C maps to it
// exactly). Valid range 0x00..0x10. Identity — no remap table.
export function resolveStageFile(stageId) { return (stageId | 0) & 0xFF; }

export const STAGE_NAMES = {
  0x00:'Airship (Day)',0x01:'Desert (Orange)',0x02:'Factory',0x03:'Carnival (Summer)',
  0x04:'Swamp',0x05:'Cave (Water)',0x06:'Clocktower (Clear)',0x07:'River on Ice',
  0x08:'Abyss',0x09:'Airship (Night)',0x0A:'Desert (Blue)',0x0B:'Training',
  0x0C:'Carnival (Winter)',0x0D:'Swamp (Asian)',0x0E:'Cave (Lava)',0x0F:'Clocktower (Snowy)',
  0x10:'River on Raft',
};

export class StageClient {
  constructor(base = './stages') {
    this.base = base.replace(/\/$/, '');
    this.stageId = -1;
    this.fileIdx = -1;
    this.img = null;         // HTMLImageElement backdrop (or null = no asset)
    this.meta = null;        // decoded STGxx.json
    this.ready = false;
    this._loading = false;
  }

  hexIdx() { return (this.fileIdx >= 0 ? this.fileIdx : 0).toString(16).toUpperCase().padStart(2, '0'); }

  // Lazy-load the backdrop for a stage_id. Safe to call every frame; only refetches on change.
  async setStage(stageId) {
    if (stageId == null || stageId < 0) return false;
    if (stageId === this.stageId) return this.ready;
    this.stageId = stageId;
    this.fileIdx = resolveStageFile(stageId);
    this.ready = false; this.img = null; this.meta = null;
    if (this._loading) return false;
    this._loading = true;
    const hx = this.hexIdx();
    const PV = 'stage2';
    try {
      const meta = await fetch(`${this.base}/STG${hx}.json?v=${PV}`)
        .then(r => r.ok ? r.json() : Promise.reject(r.status)).catch(() => ({}));
      const img = await this._loadImg(`${this.base}/STG${hx}_bg.png?v=${PV}`);
      this.img = img;
      this.meta = {
        imgW: meta.imgW || img.naturalWidth,
        imgH: meta.imgH || img.naturalHeight,
        groundImgY: (meta.groundImgY != null) ? meta.groundImgY : (img.naturalHeight * 0.72),
        parallax: (meta.parallax != null) ? meta.parallax : 0.12,
        bgColor: Array.isArray(meta.bgColor) ? meta.bgColor : [30, 34, 44],
        camRefX: meta.camRefX || 0,
        camRefY: (meta.camRefY != null) ? meta.camRefY : 0,
        name: meta.name || STAGE_NAMES[this.fileIdx] || '?',
      };
      this.ready = true;
    } catch (e) { this.ready = false; this.img = null; }
    finally { this._loading = false; }
    return this.ready;
  }
  _loadImg(u) {
    return new Promise((res, rej) => {
      const im = new Image(); im.onload = () => res(im); im.onerror = () => rej('bg 404'); im.src = u;
    });
  }

  // Draw the scrolled backdrop into a 640x480-space 2D ctx (scaled like the HUD). No-op until
  // an asset is loaded. cam = { camX (tape eyeX), camY (tape eyeY) }. The sky bgColor fills
  // the whole frame first so the strip's edges never reveal black as it pans.
  render(ctx, cam) {
    if (!ctx) return false;
    const W = ctx.canvas.width, H = ctx.canvas.height;
    ctx.save();
    ctx.scale(W / SCREEN_W, H / SCREEN_H);
    ctx.imageSmoothingEnabled = false;
    const m = this.meta;
    if (!this.ready || !this.img || !m) { ctx.restore(); return false; }

    // sky/edge backstop
    ctx.fillStyle = `rgb(${m.bgColor[0]},${m.bgColor[1]},${m.bgColor[2]})`;
    ctx.fillRect(0, 0, SCREEN_W, SCREEN_H);

    const camX = cam.camX || 0, camY = cam.camY || 0, px = m.parallax;
    // Horizontal: fighters go screenX = worldX - camX + 320, so the world (and this backdrop)
    // moves LEFT as camX grows. Center the wide strip on the screen at camRefX, then pan.
    const baseLeft = (SCREEN_W - m.imgW) / 2;                 // strip centered on screen
    const screenLeft = baseLeft - (camX - m.camRefX) * px;
    // Vertical: screenY = (camY+338.4) - worldY, so the world moves DOWN as camY grows.
    // Pin the strip's top at 0 for camRefY, then drift by +camY*parallax.
    const baseTop = (SCREEN_H - m.imgH) / 2;
    const screenTop = baseTop + (camY - m.camRefY) * px;

    ctx.drawImage(this.img, screenLeft, screenTop, m.imgW, m.imgH);
    ctx.restore();
    return true;
  }
}

// ============================================================================
// FIDELITY / FOLLOW-UP
// ----------------------------------------------------------------------------
//  FIRST-PASS (this module): a fixed-camera flatten of the full POL/TEX rip, scrolled 2D by
//  the tape camX/camY. Recognizable stage + sky behind the fighters; no per-frame camera
//  match, no true multi-layer parallax.
//  HIGHER FIDELITY (future): port the maplecast web/webgpu stage-client.mjs 3D path
//  (PVR2Renderer + STGxx POL/TEX) and either capture M1·M2 into the tape or reconstruct a
//  fixed projection and apply the camX/camY pan in-engine (STG00 is 100% placed => the
//  easiest stage to prove the 3D path on — sh4-re).
// ============================================================================
