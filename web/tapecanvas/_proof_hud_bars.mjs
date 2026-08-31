// _proof_hud_bars.mjs — HEADLESS proof of the two-layer life bar (bug 1).
// Drives the tape-based buildHudQuads (chip=red_hp BEHIND, fill=hp OVER) through the REAL
// pvr2 rasterizer and writes the top HUD band + a per-side yellow/red pixel census.
// usage: node _proof_hud_bars.mjs [tapeFrameIdx]
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const MAPLE = 'C:/Users/trist/projects/maplecast-flycast';
const PNG = require(path.join(MAPLE, 'tools/render-replica-poc/node_modules/pngjs/lib/png.js')).PNG;

const { initDevice } = await import(pathToFileURL(path.join(MAPLE, 'tools/render-replica-poc/webgpu-headless.mjs')).href);
const { device } = await initDevice();
const { HudPvr2, buildHudQuads, renderHudRGBA } = await import(pathToFileURL(path.join(HERE, 'renderer', 'hud-pvr2.mjs')).href);

// HUD assets (same slab hud-client loads)
const HUD = path.join(HERE, 'hud');
const baseQuads = JSON.parse(fs.readFileSync(path.join(HUD, 'hud_quads.json'), 'utf8')).quads;
const vmeta = JSON.parse(fs.readFileSync(path.join(HUD, 'hud_vram.json'), 'utf8'));
const slab = new Uint8Array(fs.readFileSync(path.join(HUD, 'hud_vram.bin')));
const pal  = new Uint8Array(fs.readFileSync(path.join(HUD, 'hud_pal.bin')));
const vram = new Uint8Array(vmeta.vramSize); vram.set(slab, vmeta.base);

// tape state: interleaved slots even=P1, odd=P2 (F.hp idx4, F.red_hp idx14)
const tape = JSON.parse(fs.readFileSync(path.join(HERE, 'tape_59601369.json'), 'utf8'));
const p1 = tape.p1_team, p2 = tape.p2_team;
const FI = +(process.argv[2] || 1500);
const row = tape.frames[FI];
const hp = row[4], red = row[14], drawn = row[17];
const cidForSlot = s => (s % 2 === 0) ? p1[s >> 1] : p2[s >> 1];
const slots = [];
for (let s = 0; s < 6; s++) slots.push({ active: drawn[s] ? 1 : 0, cid: cidForSlot(s) & 0xff, hp: hp[s] | 0, red: red[s] | 0, wins: 0, hitFlash: 0 });
const state = { inMatch: true, slots };
console.log(`frame ${FI}: hp=${JSON.stringify(hp)} red=${JSON.stringify(red)}`);

const hud = new HudPvr2(device, 640, 480);
hud.setVram(vram); hud.setPalette(pal);
const quads = buildHudQuads(baseQuads, state, {});
const rgba = await renderHudRGBA(hud, quads, [0, 1, 2, 3]);

// composite over dark gray + write the top band
const W = 640, H = 480, BAND = 120;
const out = new PNG({ width: W, height: BAND });
for (let y = 0; y < BAND; y++) for (let x = 0; x < W; x++) {
  const i = (y * W + x) * 4, a = rgba[i + 3] / 255, o = (y * W + x) * 4;
  out.data[o] = rgba[i] * a + 24 * (1 - a); out.data[o + 1] = rgba[i + 1] * a + 28 * (1 - a);
  out.data[o + 2] = rgba[i + 2] * a + 32 * (1 - a); out.data[o + 3] = 255;
}
fs.writeFileSync(path.join(HERE, `_proof_hud_bars_f${FI}.png`), PNG.sync.write(out));

// census: classify bar-band pixels (top P1 bar y 46..58, P2 bar) as YELLOW (current) vs RED (recoverable)
function census(name, x0, y0, x1, y1) {
  let yel = 0, redp = 0, tot = 0;
  for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) {
    const i = (y * W + x) * 4, r = rgba[i], g = rgba[i + 1], b = rgba[i + 2], a = rgba[i + 3];
    if (a < 40) continue; tot++;
    if (r > 150 && g < 90 && b < 90) redp++;            // solid red chip
    else if (r > 150 && g > 130 && b < 110) yel++;       // yellow/team fill
  }
  console.log(`  ${name.padEnd(16)} yellow(current)=${String(yel).padStart(4)}  red(recover)=${String(redp).padStart(4)}  of ${tot}`);
}
console.log('BAR CENSUS (both layers must be > 0 where red_hp > hp):');
census('P1 row0 bar', 46, 46, 270, 58);
census('P2 row0 bar', 370, 46, 594, 58);
console.log(`wrote _proof_hud_bars_f${FI}.png`);
process.exit(0);
