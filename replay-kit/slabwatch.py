#!/usr/bin/env python3
"""slabwatch.py [secs] — T1(a): do the per-character DAT slabs MUTATE during a fight?

THE ONE MEASUREMENT THAT DECIDES THE BATTLE-ANCHOR ARCHITECTURE. Read-only, zero risk.

Two expert audits agree a battle snapshot's problem is CONTENT, not addresses: the per-character
asset slabs in the NAOMI guest-RAM image hold whichever characters that session loaded. They differ
on the fix, and the difference hinges on one unmeasured fact:

  * If the slabs are STATIC during play (pure ROM data), a battle anchor is portable to any target
    that loaded the same team in the same slot order. You warm the assets by replaying the
    character-select confirm frames, then jump to the battle state. ~17 KB extra per tape.
  * If any slab MUTATES, it holds live match state OUTSIDE blk — the anchor can never carry it, and
    a tape would have to ship 8.25 MB of guest RAM.

There is a DOCUMENTED CONFLICT to settle here:
    `mvc2-dc-steam-block-map` flags a per-anim-sub-frame self-modify in this image as UNKNOWN.
    `STEAM-REPLAY-PLAN.md:38` says the slab is byte-identical to the pristine ROM blob except
    Dat_Pal+2, which is our own skin painter writing.
Both cannot be right. This settles it by reading.

ADDRESS MODEL (CONFIRMED by both audits, independently, on two different launches):
    host(dc) = (dc & 0x1FFFFFFF) + arena - 0x3C00000
    arena + 0x8400000 == host(0x0C000000)          <- the 32 MiB NAOMI guest-RAM image
Per-slot DAT slabs are FIXED and character-independent (pl_mem.asm pl_A..pl_F_datfile):
"""
import hashlib
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from savestate import Game, BLK_PTR, FC_OFF
from mvcmem import EXE

ARENA_PTR = EXE + 0xAC6D40
DC_DAT = [0x0C420000, 0x0C810000, 0x0C570000, 0x0C960000, 0x0C6C0000, 0x0CAB0000]
SLAB = 0x150000
DAT_PAL_OFF = 0x1B8            # H+0x1B8 — our skin painter writes here; expected to differ
H0, STRIDE = 0x3DB8, 0x738
SECS = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0

g = Game()
blk = g.u64(BLK_PTR)
arena = g.u64(ARENA_PTR)
D = arena - 0x3C00000
mode = list(g.read(blk + 0x3CB8, 5))
cids = [g.read(blk + H0 + i * STRIDE + 0x6C0, 1)[0] for i in range(6)]
print(f"blk 0x{blk:x}  arena 0x{arena:x}  D 0x{D:x}  mode {mode}  cids {cids}")
if mode[2] != 2:
    sys.exit("REFUSING: not in a battle (mode[2] != 2). Get into a fight and run again.")

# sanity: the engine's own DAT base for each slot must equal host(DC_DAT[i])
ok = True
for i in range(6):
    live = g.u64(blk + H0 + i * STRIDE + 0x6B8)
    want = (DC_DAT[i] & 0x1FFFFFFF) + D
    tag = "ok" if live == want else "MISMATCH"
    if live != want:
        ok = False
    print(f"  slot{i} cid={cids[i]:3d}  H+0x6B8=0x{live:x}  host(dc 0x{DC_DAT[i]:08x})=0x{want:x}  {tag}")
if not ok:
    sys.exit("address model does not hold on this launch — stop and re-derive D")

print(f"\nhashing the six {SLAB//1024} KiB slabs for {SECS:.0f}s...")
first, changes, samples = {}, {i: 0 for i in range(6)}, 0
t0 = time.perf_counter()
last_fc = None
while time.perf_counter() - t0 < SECS:
    fc = g.u32(blk + FC_OFF)
    if fc == last_fc:
        continue
    last_fc = fc
    samples += 1
    for i in range(6):
        b = g.read((DC_DAT[i] & 0x1FFFFFFF) + D, SLAB)
        if b is None:
            continue
        h = hashlib.blake2b(b, digest_size=16).digest()
        if i not in first:
            first[i] = (h, b)
        elif h != first[i][0]:
            changes[i] += 1

print(f"sampled {samples} frames\n")
print(f"{'slot':>4} {'cid':>4}  {'changed':>8}   verdict")
mut = False
for i in range(6):
    c = changes[i]
    mut |= c > 0
    print(f"{i:>4} {cids[i]:>4}  {c:>8}   {'STATIC' if c == 0 else 'MUTATES'}")

if not mut:
    print("\nT1(a) RESULT: all six slabs STATIC during play.")
    print("=> a battle anchor IS portable to a target with the same team in the same slot order.")
    print("=> Option A (warm assets via char-select confirm frames, then jump) is sound.")
    print("   STEAM-REPLAY-PLAN.md:38 is right; the block-map's self-modify flag does not apply here.")
else:
    print("\nT1(a) RESULT: at least one slab MUTATES.")
    print("=> the DAT image holds live match state OUTSIDE blk.")
    print("=> a battle anchor CANNOT be carried by blk alone; Option B (ship 8.25 MB of guest RAM)")
    print("   or char-select-only anchoring. Locate the mutating bytes before deciding.")
