// render_replica_mcrr.mjs — HEADLESS render of the RESIM's LIVE render-replica wire
// (MCRR prefix + FRMx state frames, taSize=0) on the TAPECANVAS WebGPU renderer.
//
// This is the RANK-3 transpiled-reconstruction path (the resim shipped STATE, not TA):
//   compressed live wire ([u32 len][ZCST-zstd(inner)]...)
//     -> decompress (renderer/fzstd.mjs)                              [vendored]
//     -> seed 16MB RAM + 8MB VRAM + PVR from the MCRR static prefix
//     -> per FRMx: apply 24 dynamic state regions + GFX/palette tails
//     -> render_frame_node.wasm  (_render_frame_ta)   [maplecast transpile, in place]
//     -> body_decoder.ensureBodyTextures -> body part pixels into VRAM  [maplecast]
//     -> renderer/ta-parser.mjs (TAParser.parse)                       [vendored]
//     -> renderer/pvr2-renderer.mjs (PVR2Renderer.renderFrame)         [vendored]
//     -> offscreen WebGPU target -> readback -> PNG
//
// Reuses the proven pipeline from tools/render-replica-poc/render_strategy.mjs +
// _audit_livecap.mjs (parse/seed/render_frame/ensureBodyTextures) and points the
// FINAL raster at the tapecanvas vendored pvr2. NO new renderer.
//
// usage: node render_replica_mcrr.mjs --in <file.mcrr> --frames a,b,c --outdir DIR

import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const RDIR = path.join(HERE, 'renderer');
const MAPLE = 'C:/Users/trist/projects/maplecast-flycast';
const POC = path.join(MAPLE, 'tools/render-replica-poc');
const GFX_DIR = path.join(MAPLE, 'web/render-replica/gfx') + '/';

const require = createRequire(import.meta.url);
const PNG = require(path.join(POC, 'node_modules/pngjs/lib/png.js')).PNG;

// Dawn globals + vendored fzstd/renderer + maplecast transpile front-end.
const { initDevice } = await import(pathToFileURL(path.join(POC, 'webgpu-headless.mjs')).href);
const { decompress } = await import(pathToFileURL(path.join(RDIR, 'fzstd.mjs')).href);
const { PVR2Renderer }   = await import(pathToFileURL(path.join(RDIR, 'pvr2-renderer.mjs')).href);
const { TAParser }       = await import(pathToFileURL(path.join(RDIR, 'ta-parser.mjs')).href);
const { TextureManager } = await import(pathToFileURL(path.join(RDIR, 'texture-manager.mjs')).href);
const createRenderFrame  = (await import(pathToFileURL(path.join(POC, 'render_frame_node.mjs')).href)).default;
const { decodeA, ensureBodyTextures } = await import(pathToFileURL(path.join(MAPLE, 'web/render-replica/body_decoder.mjs')).href);

const ZCST = 0x5453435A, MCRR = 0x5252434D, FRMX = 0x784D5246, HUDQ = 0x48554451;
const G = a => (a >>> 0) & 0xFFFFFF;

function parseArgs(argv) {
  const a = { frames: [0], outdir: '.' };
  for (let i = 2; i < argv.length; i++) { const k = argv[i], nx = () => argv[++i];
    if (k === '--in') a.in = nx(); else if (k === '--frames') a.frames = nx().split(',').map(s => +s);
    else if (k === '--outdir') a.outdir = nx(); else { console.error('unknown', k); process.exit(2); } }
  return a;
}
function decomp(u8) { const v = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
  return (u8.length >= 8 && v.getUint32(0, true) === ZCST) ? decompress(u8.subarray(8)) : u8; }

// Split compressed live wire into decompressed inner messages.
function loadMcrr(file) {
  const dv = new DataView(file.buffer, file.byteOffset, file.byteLength);
  const inners = []; let off = 0;
  while (off + 4 <= file.length) { const len = dv.getUint32(off, true); off += 4;
    if (len === 0 || off + len > file.length) break;
    inners.push(decomp(file.subarray(off, off + len))); off += len; }
  return inners;
}

// Parse the MCRR static prefix -> region tables + seeded RAM/VRAM/PVR.
function parsePrefix(pre) {
  const pv = new DataView(pre.buffer, pre.byteOffset, pre.byteLength);
  let p = 0; const u32 = () => { const v = pv.getUint32(p, true); p += 4; return v >>> 0; };
  if (u32() !== MCRR) throw new Error('bad MCRR prefix');
  const ver = u32(), nS = u32(), nD = u32(), nF = u32(), vB = u32(), pB = u32(); u32();
  const reg = () => { const a = u32(), l = u32(); let t = ''; for (let i = 0; i < 8; i++) { const c = pre[p + i]; if (c) t += String.fromCharCode(c); } p += 8; return { addr: a >>> 0, len: l, tag: t }; };
  const S = Array.from({ length: nS }, reg), D = Array.from({ length: nD }, reg);
  const vram = pre.subarray(p, p + vB).slice(); p += vB;
  const pvr = pre.subarray(p, p + pB).slice(); p += pB;
  const ram = new Uint8Array(16 * 1024 * 1024);
  for (const r of S) { const b = pre.subarray(p, p + r.len); p += r.len;
    if (r.tag === 'ram16') ram.set(b.subarray(0, Math.min(b.length, ram.length)), 0);
    else ram.set(b, G(r.addr)); }
  return { S, D, vram, pvr, ram, dynTotal: D.reduce((s, r) => s + r.len, 0) };
}

// Apply an FRMx inner's GFX tail (cumulative) into RAM, palette tail into pvr.
// Returns whether this is a valid FRMx.
function applyFrame(inner, P, ram, pvr, applyDyn) {
  const iv = new DataView(inner.buffer, inner.byteOffset, inner.byteLength);
  if (iv.getUint32(0, true) !== FRMX) return false;
  let q = 12; // FRMx + vframe + taSize(0)
  if (applyDyn) { for (const r of P.D) { ram.set(inner.subarray(q, q + r.len), G(r.addr)); q += r.len; } }
  else q += P.dynTotal;
  // GFX tail (on-change): nGfx + [base,len,bytes]
  const nGfx = iv.getUint32(q, true); q += 4;
  if (nGfx <= 64) for (let g = 0; g < nGfx; g++) { const base = iv.getUint32(q, true), len = iv.getUint32(q + 4, true); q += 8; ram.set(inner.subarray(q, q + len), G(base)); q += len; }
  // palette tail
  const palLen = iv.getUint32(q, true); q += 4; if (palLen) { pvr.set(inner.subarray(q, q + Math.min(palLen, pvr.length))); q += palLen; }
  return true;
}

const SLOTS = [0x8C268340, 0x8C2688E4, 0x8C268E88, 0x8C26942C, 0x8C2699D0, 0x8C269F74];

async function main() {
  const a = parseArgs(process.argv);
  if (!a.in) { console.error('need --in <file.mcrr>'); process.exit(2); }
  const { device, info } = await initDevice();
  console.log('[gpu]', info.vendor || info.description || 'Dawn');
  console.log('[vendored raster] =', RDIR);

  const inners = loadMcrr(new Uint8Array(readFileSync(a.in).buffer));
  const P = parsePrefix(inners[0]);
  const frameInners = inners.slice(1).filter(m => { const v = new DataView(m.buffer, m.byteOffset, m.byteLength); return m.length >= 12 && v.getUint32(0, true) === FRMX; });
  console.log(`[mcrr] ${inners.length} msgs; ${frameInners.length} FRMx frames; ${P.S.length} static + ${P.D.length} dyn regions; dynTotal=0x${P.dynTotal.toString(16)}`);

  const M = await createRenderFrame({ locateFile: (x) => path.join(POC, x) });

  const R = new PVR2Renderer(); R.dev = device; R.fmt = 'rgba8unorm';
  device.addEventListener?.('uncapturederror', e => console.error('[wgpu]', e.error?.message || e));
  R._init(640, 480);
  const color = device.createTexture({ size: [640, 480], format: R.fmt, usage: GPUTextureUsage.RENDER_ATTACHMENT | GPUTextureUsage.COPY_SRC | GPUTextureUsage.TEXTURE_BINDING });
  const depth = device.createTexture({ size: [640, 480], format: 'depth32float', usage: GPUTextureUsage.RENDER_ATTACHMENT });
  const rt = { color, depth, colorView: color.createView(), depthView: depth.createView(), width: 640, height: 480 };
  const snap = new Uint32Array(16); snap[0] = ((Math.round(640 / 32) - 1) & 0x3F) | (((Math.round(480 / 32) - 1) & 0x3F) << 16);

  mkdirSync(a.outdir, { recursive: true });
  const u8r = (ram, x) => ram[G(x)];
  const u32r = (ram, x) => (ram[G(x)] | (ram[G(x) + 1] << 8) | (ram[G(x) + 2] << 16) | (ram[G(x) + 3] << 24)) >>> 0;

  for (const fi of a.frames) {
    if (fi < 0 || fi >= frameInners.length) { console.warn(`frame ${fi} out of range 0..${frameInners.length - 1}`); continue; }
    // Fresh RAM/pvr from static; replay GFX/palette tails 0..fi (on-change), dyn only at fi.
    const ram = P.ram.slice(); const pvr = P.pvr.slice();
    let vframe = 0;
    for (let f = 0; f <= fi; f++) { applyFrame(frameInners[f], P, ram, pvr, f === fi);
      if (f === fi) { const iv = new DataView(frameInners[f].buffer, frameInners[f].byteOffset, frameInners[f].byteLength); vframe = iv.getUint32(4, true); } }

    // Local GFX fallback for any resident char whose GFX1 isn't in RAM (belt).
    { const done = new Set(); for (const b of SLOTS) { if (u8r(ram, b) === 0) continue; const cid = u8r(ram, b + 1); const g1b = u32r(ram, b + 0x15C); if (!((g1b & 0x0C000000) || (g1b & 0x8C000000))) continue; if (done.has(cid)) continue; done.add(cid); const hex = 'PL' + cid.toString(16).toUpperCase().padStart(2, '0'); try { const g1 = new Uint8Array(readFileSync(GFX_DIR + hex + '_gfx1.bin')); const g2 = new Uint8Array(readFileSync(GFX_DIR + hex + '_gfx2.bin')); const g1d = G(g1b), g2d = G(u32r(ram, b + 0x160)); if (!ram[g1d] && g1d + g1.length <= ram.length) ram.set(g1, g1d); if (!ram[g2d] && g2d + g2.length <= ram.length) ram.set(g2, g2d); } catch {} } }

    // render_frame transpile -> TA + per-quad attrs
    const rp = M._malloc(ram.length); M.HEAPU8.set(ram, rp);
    const cap = 512 * 1024, op = M._malloc(cap);
    const len = M._render_frame_ta(rp, op, cap);
    const quads = M._render_frame_quad_count();
    const ta = M.HEAPU8.slice(op, op + len);
    const sp = M._malloc(quads * 2 || 2), gp = M._malloc(quads * 4 || 4), crp = M._malloc(quads * 8 || 8), mp = M._malloc(quads || 1);
    M._render_frame_quad_sels(sp, quads); M._render_frame_quad_gfx1s(gp, quads); M._render_frame_quad_colrow(crp, quads); M._render_frame_quad_mirror(mp, quads);
    const sels = new Uint16Array(M.HEAPU8.buffer.slice(sp, sp + quads * 2));
    const gfxs = new Uint32Array(M.HEAPU8.buffer.slice(gp, gp + quads * 4));
    const cr = new Int32Array(M.HEAPU8.buffer.slice(crp, crp + quads * 8));
    const mir = new Uint8Array(M.HEAPU8.buffer.slice(mp, mp + quads));

    // Body part textures into VRAM (the fixed decoder). Seed VRAM from static prefix,
    // then overwrite animated body bands with this pose's parts.
    const vram = P.vram.slice();
    ensureBodyTextures(ram, vram, ta, quads, {}, sels, gfxs, cr, {}, mir);

    // Raster on the tapecanvas vendored pvr2.
    const T = new TextureManager(device); T.setDirtyPages(null, true); T.updatePalette(pvr);
    const parsed = new TAParser().parse(ta, len);
    R.renderFrame(parsed, T, snap, vram, {}, rt);
    device.queue.submit([R._lastEncoder.finish()]);

    const bpr = Math.ceil(640 * 4 / 256) * 256;
    const rb = device.createBuffer({ size: bpr * 480, usage: GPUBufferUsage.COPY_DST | GPUBufferUsage.MAP_READ });
    const enc = device.createCommandEncoder();
    enc.copyTextureToBuffer({ texture: color }, { buffer: rb, bytesPerRow: bpr, rowsPerImage: 480 }, [640, 480, 1]);
    device.queue.submit([enc.finish()]);
    await rb.mapAsync(GPUMapMode.READ);
    const mapped = new Uint8Array(rb.getMappedRange()).slice(); rb.unmap(); rb.destroy();
    const out = new Uint8Array(640 * 480 * 4);
    for (let y = 0; y < 480; y++) for (let x = 0; x < 640; x++) { const s = y * bpr + x * 4, d = (y * 640 + x) * 4; out[d] = mapped[s]; out[d + 1] = mapped[s + 1]; out[d + 2] = mapped[s + 2]; out[d + 3] = mapped[s + 3]; }
    const png = new PNG({ width: 640, height: 480 }); png.data = Buffer.from(out.buffer);
    const outPath = path.join(a.outdir, `replica_f${fi}_vf${vframe}.png`);
    writeFileSync(outPath, PNG.sync.write(png));
    let nz = 0; for (let i = 0; i < out.length; i += 4) if (out[i] | out[i + 1] | out[i + 2]) nz++;
    console.log(`[frame ${fi}] vframe=${vframe} taLen=${len} quads=${quads} op=${parsed.opaque.length} tr=${parsed.translucent.length} | ${nz}/307200 non-black -> ${outPath}`);
    M._free(rp); M._free(op); M._free(sp); M._free(gp); M._free(crp); M._free(mp);
  }
}
main().catch(e => { console.error(e); process.exit(1); });
