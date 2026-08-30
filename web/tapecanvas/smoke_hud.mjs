// smoke_hud.mjs — Node verification of TapeAdapter.buildHudState() (the full-HUD state the
// vendored hud-client.mjs renders). Run: node web/tapecanvas/smoke_hud.mjs [frameIdx]
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { TapeAdapter } from './tape-adapter.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const t = JSON.parse(fs.readFileSync(path.join(here, 'tape.json'), 'utf8'));
const ad = TapeAdapter.fromJsonObject(t);
const fi = parseInt(process.argv[2] || '7729', 10);
const st = ad.buildHudState(fi);

let fail = 0;
const ok = (c, m) => { console.log(`${c ? 'PASS' : 'FAIL'}  ${m}`); if (!c) fail++; };

console.log(`\n=== buildHudState(${fi}) ===`);
console.log(JSON.stringify(st, null, 1));

ok(st.inMatch === true, 'inMatch');
ok(st.slots.length === 6, '6 slots');
ok(st.slots[0].cid === (t.p1_team[0] & 0xff), 'slot0 cid = p1_team[0]');
ok(st.slots[5].cid === (t.p2_team[2] & 0xff), 'slot5 cid = p2_team[2]');
ok(st.timer >= 0 && st.timer <= 99, `timer ${st.timer} in [0,99]`);
ok(st.p1.lvl >= 0 && st.p1.lvl <= 5, `p1 lvl ${st.p1.lvl} in [0,5]`);
ok(st.p2.lvl >= 0 && st.p2.lvl <= 5, `p2 lvl ${st.p2.lvl} in [0,5]`);
ok(st.p1.fill !== st.p2.fill || st.p1.fill === 0, 'p1/p2 fill are independent columns');
ok(st.slots.every(s => s.wins === 0), 'wins=0 (no fabricated stars; round_no is a global counter)');

console.log(`\n${fail ? `*** ${fail} FAILURES ***` : 'ALL HUD-STATE CHECKS PASS'}`);
process.exit(fail ? 1 : 0);
