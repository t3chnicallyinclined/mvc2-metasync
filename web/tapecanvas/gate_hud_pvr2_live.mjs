// gate_hud_pvr2_live.mjs — render the LIVE tape HUD through the REAL vendored pvr2 rasterizer
// under Dawn: reshape bars by tape HP + inject the tape's DM01 portraits into the HUD VRAM, then
// pvr2-render. Proves the live path runs on the gold-standard renderer (not the software raster)
// and that faces are the TAPE's chars (portrait injection working), bars track HP.
//
// usage:  node gate_hud_pvr2_live.mjs [frame]
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const MAPLE = 'C:/Users/trist/projects/maplecast-flycast';
const PNG = require(path.join(MAPLE, 'tools/render-replica-poc/node_modules/pngjs/lib/png.js')).PNG;
const FRAME = +(process.argv[2] || 600);

const { initDevice } = await import(pathToFileURL(path.join(MAPLE, 'tools/render-replica-poc/webgpu-headless.mjs')).href);
const { device } = await initDevice();
const { HudPvr2, renderHudRGBA, buildHudQuads, injectPortraits } = await import(pathToFileURL(path.join(HERE, 'renderer', 'hud-pvr2.mjs')).href);
const { TapeAdapter } = await import(pathToFileURL(path.join(HERE, 'tape-adapter.mjs')).href);

const rd = p => { const d = PNG.sync.read(fs.readFileSync(p)); return { w: d.width, h: d.height, data: d.data }; };
const sub = (a, r) => { const w = r.w, h = r.h, data = new Uint8Array(w * h * 4); for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { const si = ((r.y + y) * a.w + (r.x + x)) * 4, di = (y * w + x) * 4; for (let k = 0; k < 4; k++) data[di + k] = a.data[si + k]; } return { w, h, data }; };

const baseQuads = JSON.parse(fs.readFileSync(path.join(HERE, 'hud/hud_quads.json'))).quads;
const vmeta = JSON.parse(fs.readFileSync(path.join(HERE, 'hud/hud_vram.json')));
const slab = new Uint8Array(fs.readFileSync(path.join(HERE, 'hud/hud_vram.bin')));
const pal = new Uint8Array(fs.readFileSync(path.join(HERE, 'hud/hud_pal.bin')));
const vram = new Uint8Array(vmeta.vramSize); vram.set(slab, vmeta.base);   // splat HUD region into sparse 8 MiB

const pmeta = JSON.parse(fs.readFileSync(path.join(HERE, 'hud/portraits/portraits.json')));
const pimg = rd(path.join(HERE, 'hud/portraits/portraits.png'));
const portByCid = {}; for (const k in pmeta.rects) portByCid[parseInt(k, 10)] = sub(pimg, pmeta.rects[k]);

const tape = JSON.parse(fs.readFileSync(path.join(HERE, 'tape.json')));
const ad = TapeAdapter.fromJsonObject(tape);
const state = ad.buildHudState(FRAME);
console.log('tape teams p1', tape.p1_team, 'p2', tape.p2_team, '| frame', FRAME);
console.log('slots:', state.slots.map(s => ({ a: s.active, cid: (s.cid & 0xff).toString(16), hp: s.hp })));

injectPortraits(vram, state, portByCid);
const hud = new HudPvr2(device, 640, 480);
hud.setVram(vram); hud.setPalette(pal);
const quads = buildHudQuads(baseQuads, state, {});
const rgba = await renderHudRGBA(hud, quads);

const W = 640, H = 120, out = new PNG({ width: W, height: H });
for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) { const i = (y * 640 + x) * 4; const a = rgba[i + 3] / 255; const o = (y * W + x) * 4;
  out.data[o] = rgba[i] * a; out.data[o + 1] = rgba[i + 1] * a; out.data[o + 2] = rgba[i + 2] * a; out.data[o + 3] = 255; }
fs.writeFileSync(path.join(HERE, 'hud/_live_tape_hud.png'), PNG.sync.write(out));
// measure P1 point bar fill width (hp -> reshape sanity)
let last = 46; for (let x = 46; x < 270; x++) { const i = (52 * 640 + x) * 4; if (rgba[i] + rgba[i + 1] + rgba[i + 2] > 40 && rgba[i + 3] > 0) last = x; }
console.log('rendered live HUD via pvr2. P1 point bar fill reaches x=' + last + ' (hp=' + state.slots[0].hp + '/144)');
console.log('wrote hud/_live_tape_hud.png');
process.exit(0);
