// smoke_fx.mjs — validate the 0.3.29 sprite-class EFFECT render path against the REAL tape
// (web/tapecanvas/tape.json, a ranked match, 48,452 effect nodes). Proves the adapter detects
// the 20-byte record, decodes ÷4096 scale, classifies cat 1-4, resolves the atlas (owner-char
// primary; gfx1 bankMap for ownerless), routes own-origin + additive. Run: node web/tapecanvas/smoke_fx.mjs

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { TapeAdapter, CPSX } from './tape-adapter.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const t = JSON.parse(fs.readFileSync(path.join(here, 'tape.json'), 'utf8'));
const ad = TapeAdapter.fromJsonObject(t);
ad.effectsOn = true;

let fail = 0;
const ok = (c, m) => { console.log(`${c ? 'PASS' : 'FAIL'}  ${m}`); if (!c) fail++; };
const cidForSlot = (s) => (s % 2 === 0 ? t.p1_team[s >> 1] : t.p2_team[s >> 1]);

// find the frame index whose game frame == 8164 (the Magneto-super proof frame)
let fi = t.frames.findIndex(r => r[0] === 8164);
if (fi < 0) fi = 5329;
const sc = { slot: Array.from({ length: 6 }, () => ({})) };
const gf = ad.applyFrame(sc, fi, { now: 0, load: () => {} });

console.log(`=== REAL 0.3.29 tape — effect routing at frame idx ${fi} (game ${gf}) ===`);
console.log('objRecBytes:', ad.objRecBytes, ' diag:', JSON.stringify(ad._lastObjs));
for (const o of sc.objects.slice(0, 6))
  console.log(`  fx -> cid=${o.cid} sel=0x${o.sid.toString(16)} pos=(${o.x},${o.y}) `
    + `blend=0x${(o.blend || 0).toString(16)} add=${o.additive} scale=${o.objScale?.toFixed(3)} owner=${o.owner} gfx1=0x${(o.gfx1 >>> 0).toString(16)}`);

ok(ad.objRecBytes === 20, `20-byte 0.3.29 record detected (got ${ad.objRecBytes})`);
ok(sc.objects.length > 0, `effects ROUTE on the real tape (${sc.objects.length} at this frame)`);
ok(sc.objects.every(o => o.blend === 0x1 && o.additive === true), 'all routed effects ADDITIVE (blend=0x1 -> pipeAdd)');
ok(sc.objects.every(o => o.isEffect === 0), 'routed as part-assembly (isEffect=0 -> emitter GFX2/sel path)');
ok(sc.objects.every(o => o.cid === cidForSlot(o.owner)), 'atlas = OWNER char (owner-char resolution)');
ok(sc.objects.every(o => Math.abs(o.objScale - CPSX) < 0.02), `effect scale ÷4096 == CpsX (${sc.objects[0]?.objScale.toFixed(4)})`);

// ── whole-tape aggregate: the real-data facts the resolver is built on ──
let total = 0, gfx2nz = 0, owner255 = 0, spriteClass = 0;
const cat = {};
for (const [, arr] of ad.objsByFrame) for (const o of arr) {
  total++; cat[o.cat] = (cat[o.cat] | 0) + 1;
  if (o.gfx2) gfx2nz++;
  if (o.owner === 0xFF) owner255++;
  if (o.cat >= 1 && o.cat <= 4) spriteClass++;
}
console.log(`\nwhole tape: ${total} obj nodes, cat=${JSON.stringify(cat)}, gfx2!=0: ${gfx2nz}, owner=255: ${owner255} (${(100*owner255/total).toFixed(1)}%)`);
ok(gfx2nz === 0, 'gfx2 (H+0x1A4) is ALWAYS 0 -> resolver keys on gfx1, NOT gfx2 (corrected)');
ok(spriteClass === total, 'ALL nodes cat 1-4 (sprite-class); no 3D-class captured (expected)');
ok(owner255 / total < 0.1, `<10% ownerless (${(100*owner255/total).toFixed(1)}%) -> owner-char path covers the bulk`);

// owner-char sid COVERAGE: every owned effect's masked sel is in the caster's atlas assembly.
function asmSids(cid) {
  const hexn = (cid & 0xff).toString(16).padStart(2, '0').toUpperCase();
  try {
    const d = JSON.parse(fs.readFileSync(
      `C:/Users/trist/projects/maplecast-flycast/web/test-atlas/chars/PL${hexn}_asm.json`, 'utf8'));
    return new Set(Object.keys(d.assemblies || d).map(Number));
  } catch { return null; }
}
const asmCache = {};
let covHit = 0, covTot = 0;
for (const [, arr] of ad.objsByFrame) for (const o of arr) {
  if (o.owner >= 6) continue;
  const cid = cidForSlot(o.owner);
  const s = (asmCache[cid] ??= asmSids(cid));
  if (!s) continue;
  covTot++; if (s.has(o.sid & 0x7fff) || s.has(o.sid)) covHit++;
}
console.log(`owner-char sid coverage: ${covHit}/${covTot} = ${(100 * covHit / covTot).toFixed(1)}%`);
ok(covHit === covTot, 'EVERY owned effect sel resolves in the caster atlas (owner-char = 100%)');

// ── gfx1 bankMap for ownerless (the calibration path) ──
const ad2 = TapeAdapter.fromJsonObject({ ...t, fxBankMap: { '0x1b0e': t.p1_team[2] } });
ad2.effectsOn = true;
console.log('\nownerless gfx1-bankMap:');
ok(ad2.resolveFxAtlas({ owner: 0xFF, gfx1: 0x1b0e, gfx2: 0 }) === (t.p1_team[2] & 0xff),
  'ownerless node resolves via gfx1 bankMap (gfx1 0x1b0e -> mapped char)');
ok(ad.resolveFxAtlas({ owner: 0xFF, gfx1: 0x1b0e, gfx2: 0 }) === null,
  'ownerless node WITHOUT a bankMap entry defers (null) — not guessed');

console.log(`\n${fail ? `*** ${fail} FAILURES ***` : 'ALL EFFECT-PATH INVARIANTS PASS'}`);
process.exit(fail ? 1 : 0);
