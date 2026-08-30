// smoke.mjs — Node verification of tape-adapter.mjs against the real render_59598061 tape.
// Run: node web/tapecanvas/smoke.mjs [frameIdx]
// Proves the adapter maps a decoded 0.3.28 frame into correct SpriteClient state, with NO
// browser/WebGPU. Asserts the load-bearing invariants (interleave, scale, layer, mask, gating).

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { TapeAdapter, CPSX, CPSY } from './tape-adapter.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const t = JSON.parse(fs.readFileSync(path.join(here, 'tape.json'), 'utf8'));
const ad = TapeAdapter.fromJsonObject(t);   // detects 16 vs 20-byte record + gfx1/gfx2
const byFrame = ad.objsByFrame;

// SpriteClient-shaped mock: slot[6] of plain objects + fields the adapter writes.
const sc = { slot: Array.from({ length: 6 }, () => ({})), _loads: [] };
const opts = { now: 0, load: (s, cid) => s._loads.push(cid) };

const fi = parseInt(process.argv[2] || '600', 10);
const gframe = ad.applyFrame(sc, fi, opts);

let fail = 0;
const ok = (cond, msg) => { console.log(`${cond ? 'PASS' : 'FAIL'}  ${msg}`); if (!cond) fail++; };

console.log(`\n=== tape-adapter smoke — frame index ${fi} (game frame ${gframe}) ===`);
console.log(`p1_team=${JSON.stringify(t.p1_team)} p2_team=${JSON.stringify(t.p2_team)} costume=${JSON.stringify(t.costume)}\n`);
const LAB = ['P1a', 'P2a', 'P1b', 'P2b', 'P1c', 'P2c'];
for (let s = 0; s < 6; s++) {
  const sl = sc.slot[s];
  console.log(`slot${s} ${LAB[s]}  cid=${sl.char_id} active=${sl.active} sid=0x${(sl.sprite_id).toString(16)} `
    + `xf=${sl.sid_xform} face=${sl.facing} screen=(${sl.screen_x?.toFixed(1)},${sl.screen_y?.toFixed(1)}) `
    + `scale=(${sl.scaleX?.toFixed(3)},${sl.scaleY?.toFixed(3)}) layer=${sl.draw_layer} hp=${sl.health}/${sl._maxhp} `
    + `red=${sl.red_health} costume=${sl.costume}`);
}
console.log('\nHUD:', JSON.stringify(sc.hud));
console.log('obj gating:', JSON.stringify(ad._lastObjs), '  objects[] len =', sc.objects.length);
console.log('lazy loads (char_ids):', JSON.stringify(sc._loads));

// ── invariants ──
console.log('\n=== invariants ===');
// interleave: even slots' char_id come from p1_team, odd from p2_team
ok(sc.slot[0].char_id === t.p1_team[0] && sc.slot[2].char_id === t.p1_team[1] && sc.slot[4].char_id === t.p1_team[2],
  'even slots (0,2,4) = P1 team');
ok(sc.slot[1].char_id === t.p2_team[0] && sc.slot[3].char_id === t.p2_team[1] && sc.slot[5].char_id === t.p2_team[2],
  'odd slots (1,3,5) = P2 team');
// scale recovery: a normally-scaled char (zx≈CpsX) yields scaleX≈1.0 (no double-apply)
const anyActive = sc.slot.find(s => s.active);
ok(anyActive && Math.abs(anyActive.scaleX - 1.0) < 0.02,
  `active char scaleX≈1.0 (got ${anyActive?.scaleX?.toFixed(4)}) — zx/CpsX, no double-apply`);
// sprite_id masking: high bit stripped, sid_xform set when present
const xf = sc.slot.find(s => s.active && s.sid_xform);
ok(sc.slot.every(s => s.sprite_id < 0x8000), 'all sprite_id masked to 15 bits');
// layer feed: active drawn slots carry a real layer (3..6) or 0xFF benched
ok(sc.slot.filter(s => s.active).every(s => s.draw_layer !== undefined),
  'every active slot has a draw_layer');
// hud life fraction sanity
ok(sc.hud.timer >= 0 && sc.hud.timer <= 99, `timer in [0,99] (=${sc.hud.timer})`);
// EFFECTS default DARK in the BODY harness (effectsOn=false), even on a 0.3.29 tape: the body
// pass renders bodies + HUD only. (smoke_fx.mjs lights + validates the effect path.)
ok(sc.objects.length === 0 && ad._lastObjs.gated === ad._lastObjs.effect,
  `effects gated in body pass: all ${ad._lastObjs.effect} sprite-class objs gated, objects[] empty`);

// whole-tape record shape.
let totalObjs = 0, ownerReal = 0;
for (const [, objs] of byFrame) for (const o of objs) { totalObjs++; if (o.owner < 6) ownerReal++; }
console.log(`\nwhole-tape obj scan: ${totalObjs} objs, recBytes=${ad.objRecBytes}, ${ownerReal} with owner<6`);
ok(ad.objRecBytes === 20, `0.3.29 tape detected as 20-byte objs record (got ${ad.objRecBytes})`);
ok(ownerReal / totalObjs > 0.8, `owner populated on ${(100*ownerReal/totalObjs).toFixed(1)}% of objs (H+0x28 captured)`);
// ÷4096 scale decode sanity: raw zx_q=6826 -> 1.6665 (=CpsX); the 0.3.28 ÷16 read gave 426.6.
const anyObj = [...byFrame.values()].flat().find(o => o.zx > 0);
ok(anyObj && Math.abs(anyObj.zx / 4096 - CPSX) < 0.01,
  `obj scale ÷4096: raw zx_q=${anyObj?.zx} -> ${(anyObj ? (anyObj.zx/4096).toFixed(4) : '?')} == CpsX`);

console.log(`\n${fail ? `*** ${fail} FAILURES ***` : 'ALL INVARIANTS PASS'}`);
process.exit(fail ? 1 : 0);
