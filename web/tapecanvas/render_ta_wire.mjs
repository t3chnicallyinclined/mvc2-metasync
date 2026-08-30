// render_ta_wire.mjs — HEADLESS full-match render of the REAL TA display-list wire
// through the TAPECANVAS VENDORED renderer (renderer/*.mjs), NOT maplecast's copies.
//
//   captured serverPublish TA-wire (.mirror.zcst)
//        -> renderer/frame-decoder.mjs (FrameDecoder.applyFrame)   [vendored]
//        -> renderer/ta-parser.mjs     (TAParser.parse + fillBGP)  [vendored]
//        -> renderer/texture-manager.mjs (TextureManager)          [vendored]
//        -> renderer/pvr2-renderer.mjs (PVR2Renderer.renderFrame)  [vendored]
//        -> offscreen WebGPU target -> readback -> PNG
//
// This is the EXACT path web/webgpu-test.html runs live (FrameDecoder.applyFrame
// -> P.parse -> R.renderFrame), and the same offline path maplecast's
// tools/render-replica-poc/render_ta.mjs runs — but pointed at OUR vendored
// renderer, proving the tapecanvas renderer draws the full match TA (bodies +
// effects + palette + blend + stage + HUD) from the resim's serverPublish stream.
//
// Bootstrap (Dawn + pngjs) is borrowed from maplecast render-replica-poc exactly
// like tapecanvas/gate_hud_pvr2.mjs does.
//
// usage:
//   node render_ta_wire.mjs --mirror <file.zcst> [--frame N | --frame last] [--out f.png]
//   node render_ta_wire.mjs --mirror <file.zcst> --frames a,b,c --outdir DIR

import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const RDIR = path.join(HERE, 'renderer');
const MAPLE = 'C:/Users/trist/projects/maplecast-flycast';
const POC = path.join(MAPLE, 'tools/render-replica-poc');

const require = createRequire(import.meta.url);
const PNG = require(path.join(POC, 'node_modules/pngjs/lib/png.js')).PNG;

// Dawn globals + device (installs GPU* onto globalThis, provides navigator.gpu).
const { initDevice } = await import(pathToFileURL(path.join(POC, 'webgpu-headless.mjs')).href);

// VENDORED renderer modules (imported AFTER GPU globals exist).
const { PVR2Renderer }   = await import(pathToFileURL(path.join(RDIR, 'pvr2-renderer.mjs')).href);
const { TAParser }       = await import(pathToFileURL(path.join(RDIR, 'ta-parser.mjs')).href);
const { TextureManager } = await import(pathToFileURL(path.join(RDIR, 'texture-manager.mjs')).href);
const { FrameDecoder }   = await import(pathToFileURL(path.join(RDIR, 'frame-decoder.mjs')).href);

const VRAM_SIZE = 8 * 1024 * 1024;

function parseArgs(argv) {
  const a = { out: 'ta_wire.png', width: 640, height: 480, frame: -1, frames: null, outdir: null };
  for (let i = 2; i < argv.length; i++) {
    const k = argv[i], next = () => argv[++i];
    if (k === '--mirror') a.mirror = next();
    else if (k === '--out') a.out = next();
    else if (k === '--outdir') a.outdir = next();
    else if (k === '--width') a.width = +next();
    else if (k === '--height') a.height = +next();
    else if (k === '--frame') { const v = next(); a.frame = v === 'last' ? -1 : +v; }
    else if (k === '--frames') a.frames = next().split(',').map(s => +s);
    else { console.error('unknown arg', k); process.exit(2); }
  }
  return a;
}

function makeRenderTarget(device, fmt, w, h) {
  const color = device.createTexture({ size: [w, h], format: fmt,
    usage: GPUTextureUsage.RENDER_ATTACHMENT | GPUTextureUsage.COPY_SRC | GPUTextureUsage.TEXTURE_BINDING });
  const depth = device.createTexture({ size: [w, h], format: 'depth32float',
    usage: GPUTextureUsage.RENDER_ATTACHMENT });
  return { color, depth, colorView: color.createView(), depthView: depth.createView(), width: w, height: h };
}

async function readbackRGBA(device, texture, w, h, fmt) {
  const bytesPerRow = Math.ceil(w * 4 / 256) * 256;
  const buf = device.createBuffer({ size: bytesPerRow * h, usage: GPUBufferUsage.COPY_DST | GPUBufferUsage.MAP_READ });
  const enc = device.createCommandEncoder();
  enc.copyTextureToBuffer({ texture }, { buffer: buf, bytesPerRow, rowsPerImage: h }, [w, h, 1]);
  device.queue.submit([enc.finish()]);
  await buf.mapAsync(GPUMapMode.READ);
  const mapped = new Uint8Array(buf.getMappedRange()).slice();
  buf.unmap(); buf.destroy();
  const out = new Uint8Array(w * h * 4);
  const bgra = fmt.startsWith('bgra');
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const s = y * bytesPerRow + x * 4, d = (y * w + x) * 4;
    if (bgra) { out[d] = mapped[s + 2]; out[d + 1] = mapped[s + 1]; out[d + 2] = mapped[s]; out[d + 3] = mapped[s + 3]; }
    else { out[d] = mapped[s]; out[d + 1] = mapped[s + 1]; out[d + 2] = mapped[s + 2]; out[d + 3] = mapped[s + 3]; }
  }
  return out;
}

function writePNG(p, rgba, w, h) {
  const png = new PNG({ width: w, height: h });
  png.data = Buffer.from(rgba.buffer, rgba.byteOffset, rgba.byteLength);
  writeFileSync(p, PNG.sync.write(png));
}

// Split a captured serverPublish TA-wire into its length-prefixed messages
// ([u32 len][msg]...). Same auto-framing render_ta.mjs uses.
function splitMsgs(file) {
  const dv = new DataView(file.buffer, file.byteOffset, file.byteLength);
  const looksFramed = file.length >= 4 && dv.getUint32(0, true) + 4 <= file.length && dv.getUint32(0, true) > 8;
  const msgs = [];
  if (looksFramed) {
    let off = 0;
    while (off + 4 <= file.length) {
      const len = dv.getUint32(off, true); off += 4;
      if (len === 0) continue;                 // capture_mirror.mjs records empty control frames — SKIP, don't stop
      if (off + len > file.length) break;       // genuine truncation: stop
      msgs.push(file.subarray(off, off + len)); off += len;
    }
  } else msgs.push(file);
  return msgs;
}

async function main() {
  const a = parseArgs(process.argv);
  if (!a.mirror) { console.error('need --mirror <file.zcst>'); process.exit(2); }
  const { device, info } = await initDevice();
  console.log('[gpu]', info.vendor || info.description || 'Dawn');
  console.log('[vendored] renderer =', RDIR);

  const R = new PVR2Renderer();
  R.dev = device; R.fmt = 'rgba8unorm';
  device.addEventListener?.('uncapturederror', (e) => console.error('[wgpu]', e.error?.message || e));
  R._init(a.width, a.height);
  const rt = makeRenderTarget(device, R.fmt, a.width, a.height);

  const file = new Uint8Array(readFileSync(a.mirror).buffer);
  const msgs = splitMsgs(file);

  // FIRST PASS (decode only, no VRAM snapshot): count TA frames + map TA-frame
  // index -> message index, so a negative "last" resolves and targets are known.
  const D0 = new FrameDecoder();
  const taMsgOfFrame = [];
  let skipped = 0;
  for (let mi = 0; mi < msgs.length; mi++) {
    let fr = null;
    try { fr = D0.applyFrame(msgs[mi]); } catch (e) { skipped++; continue; }
    if (D0.syncPending) D0.syncPending = false;
    if (fr) taMsgOfFrame.push(mi);
  }
  const nFrames = taMsgOfFrame.length;
  if (!nFrames) throw new Error(`no renderable TA frame in ${msgs.length} messages`);
  console.log(`[mirror] ${msgs.length} messages (${skipped} non-TA side-channel skipped); ${nFrames} TA frames`);

  const idxs = (a.frames ? a.frames : [a.frame])
    .map(v => v < 0 ? nFrames - 1 : Math.min(v, nFrames - 1))
    .sort((x, y) => x - y);
  if (a.outdir) mkdirSync(a.outdir, { recursive: true });

  // SECOND PASS: decode sequentially again; render-on-hit while VRAM/pvrRegs are
  // current in the decoder (no per-frame 8MB snapshot -> constant memory).
  const targetMsgs = new Map(idxs.map(fi => [taMsgOfFrame[fi], fi]));
  const D = new FrameDecoder();
  let taIdx = -1;
  for (let mi = 0; mi < msgs.length; mi++) {
    let fr = null;
    try { fr = D.applyFrame(msgs[mi]); } catch (e) { continue; }
    if (D.syncPending) D.syncPending = false;
    if (!fr) continue;
    taIdx++;
    const fi = targetMsgs.get(mi);
    if (fi === undefined) continue;
    const P = new TAParser();
    const T = new TextureManager(device);
    T.setDirtyPages(null, true);      // headless single frame: decode all textures
    T.updatePalette(D.pvrRegs);
    const parsed = P.parse(fr.taBuffer, fr.taSize);
    try { P.fillBGP(parsed, D.pvrRegs, D.vram); } catch (e) { console.warn('[fillBGP]', e.message); }
    R.renderFrame(parsed, T, fr.pvrSnapshot, D.vram, {}, rt);
    device.queue.submit([R._lastEncoder.finish()]);
    const rgba = await readbackRGBA(device, rt.color, a.width, a.height, R.fmt);
    let nz = 0; for (let k = 0; k < rgba.length; k += 4) if (rgba[k] | rgba[k + 1] | rgba[k + 2]) nz++;
    const outPath = a.outdir ? path.join(a.outdir, `ta_wire_f${fi}.png`) : a.out;
    writePNG(outPath, rgba, a.width, a.height);
    console.log(`[frame ${fi}] #${fr.frameNum} verts=${parsed.vertexCount} op=${parsed.opaque.length} pt=${parsed.punchThrough.length} tr=${parsed.translucent.length} | ${nz}/${a.width * a.height} non-black -> ${outPath}`);
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
