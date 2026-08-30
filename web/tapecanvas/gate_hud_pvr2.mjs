// gate_hud_pvr2.mjs — HEADLESS gate that renders the HUD through the REAL vendored pvr2
// rasterizer (renderer/hud-pvr2.mjs -> pvr2-renderer.mjs) under Dawn, exactly like maplecast
// render_hudq.mjs, and diffs vs the oracle _hud_cap_def/hud_0123.png. Because pvr2 is what
// PRODUCED hud_0123.png, a correct vendoring reproduces it BYTE-EXACT (~0.00/px).
//
// usage:  node gate_hud_pvr2.mjs
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const MAPLE = 'C:/Users/trist/projects/maplecast-flycast';
const CAPDIR = path.join(MAPLE, 'tools/render-replica-poc/_hud_cap_def');
const PNG = require(path.join(MAPLE, 'tools/render-replica-poc/node_modules/pngjs/lib/png.js')).PNG;

// 1) Dawn globals + device (maplecast webgpu-headless installs GPU* onto globalThis).
const { initDevice } = await import(pathToFileURL(path.join(MAPLE, 'tools/render-replica-poc/webgpu-headless.mjs')).href);
const { device, info } = await initDevice();
console.log('[gpu]', info.description || info.vendor || 'Dawn');

// 2) vendored HUD-through-pvr2 (imported AFTER globals exist).
const { HudPvr2, renderHudRGBA } = await import(pathToFileURL(path.join(HERE, 'renderer', 'hud-pvr2.mjs')).href);

// 3) parse the RAW HUDQ tail (full pcw/isp/tsp/tcw) — the same input render_hudq.mjs uses.
function parseHud(buf) {
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  if (dv.getUint32(0, true) !== 0x48554451) throw new Error('bad HUDQ magic');
  const n = dv.getUint32(4, true); const q = []; let p = 8;
  for (let i = 0; i < n; i++) {
    const x = [0, 1, 2, 3].map(k => dv.getFloat32(p + k * 4, true));
    const y = [0, 1, 2, 3].map(k => dv.getFloat32(p + 16 + k * 4, true));
    const u = [0, 1, 2, 3].map(k => dv.getFloat32(p + 32 + k * 4, true));
    const v = [0, 1, 2, 3].map(k => dv.getFloat32(p + 48 + k * 4, true));
    const col = [0, 1, 2, 3].map(k => dv.getUint32(p + 64 + k * 4, true));
    const pcw = dv.getUint32(p + 80, true), isp = dv.getUint32(p + 84, true), tsp = dv.getUint32(p + 88, true), tcw = dv.getUint32(p + 92, true);
    q.push({ x, y, u, v, col, pcw, isp, tsp, tcw }); p += 96;
  }
  return q;
}

const quads = parseHud(new Uint8Array(fs.readFileSync(path.join(CAPDIR, 'hudq_tail.bin'))));
const vram = new Uint8Array(fs.readFileSync(path.join(CAPDIR, 'vram_prefix.bin')));
const pvr = new Uint8Array(fs.readFileSync(path.join(CAPDIR, 'pvr_prefix.bin')));

const hud = new HudPvr2(device, 640, 480);
hud.setVram(vram); hud.setPalette(pvr);
const rgba = await renderHudRGBA(hud, quads, [0, 1, 2, 3]);

// oracle composites over dark gray (24,28,32) — render_hudq.mjs:104. Match it, then diff.
const W = 640, H = 480;
const mine = new Uint8Array(W * H * 4);
for (let i = 0; i < rgba.length; i += 4) { const a = rgba[i + 3] / 255; mine[i] = rgba[i] * a + 24 * (1 - a); mine[i + 1] = rgba[i + 1] * a + 28 * (1 - a); mine[i + 2] = rgba[i + 2] * a + 32 * (1 - a); mine[i + 3] = 255; }
const gt = PNG.sync.read(fs.readFileSync(path.join(CAPDIR, 'hud_0123.png')));

function region(name, x0, y0, x1, y1) {
  let s = 0, n = 0, over = 0, mx = 0;
  for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) {
    const mi = (y * W + x) * 4, gi = (y * gt.width + x) * 4;
    const d = Math.abs(mine[mi] - gt.data[gi]) + Math.abs(mine[mi + 1] - gt.data[gi + 1]) + Math.abs(mine[mi + 2] - gt.data[gi + 2]);
    s += d; n++; if (d > 30) over++; if (d > mx) mx = d;
  }
  console.log(`  ${name.padEnd(22)} mean ${(s / n).toFixed(2).padStart(7)}/px   px>30 ${String(over).padStart(5)}/${n}  max ${mx}`);
}
console.log('REAL pvr2 HUD (vendored) vs oracle hud_0123.png:');
region('WHOLE top band', 0, 44, 640, 113);
region('P1 frame+bars', 40, 44, 275, 113);
region('P2 frame+bars', 365, 44, 600, 113);
region('P2 gold reserve bar', 428, 72, 596, 86);
region('P1 portrait', 6, 45, 34, 71);
region('P2 portrait', 606, 45, 634, 71);
region('names band', 90, 60, 570, 113);

// stack ours/oracle for eyeballing
const cmp = new PNG({ width: W, height: 130 * 2 });
for (let y = 0; y < 130; y++) for (let x = 0; x < W; x++) {
  const mi = (y * W + x) * 4, o1 = (y * W + x) * 4, o2 = ((y + 130) * W + x) * 4, gi = (y * gt.width + x) * 4;
  cmp.data[o1] = mine[mi]; cmp.data[o1 + 1] = mine[mi + 1]; cmp.data[o1 + 2] = mine[mi + 2]; cmp.data[o1 + 3] = 255;
  cmp.data[o2] = gt.data[gi]; cmp.data[o2 + 1] = gt.data[gi + 1]; cmp.data[o2 + 2] = gt.data[gi + 2]; cmp.data[o2 + 3] = 255;
}
fs.writeFileSync(path.join(HERE, 'hud', '_gate_ours_vs_gt.png'), PNG.sync.write(cmp));
console.log('wrote hud/_gate_ours_vs_gt.png (top=ours via REAL pvr2, bottom=oracle)');
process.exit(0);
