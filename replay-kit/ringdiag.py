#!/usr/bin/env python3
"""ringdiag.py - READ-ONLY one-shot: find GGPO's frame key and prove the ring indexes on it.

inputring.py validated the chain (array cookie == nplayers, GameInput.size == 4 on every read) but
scored 0/1501 on `_inputs[f%128].frame == f` because it keyed on blk+0x3CC8 -- the GAME's counter,
which has a different origin than GGPO's Sync::_framecount. _last_added_frame read ~5063 while blk's
counter read something else entirely.

From Sync::Init (FUN_14011c8e0):
    *(u8  *)(sync + 0x180) = 0;                  -> _rollingback
    *(u32 *)(sync + 0x188) = 0;                  -> _framecount        (zeroed at init)
    *(u32 *)(sync + 0x18c) = config[7];          -> _max_prediction_frames
matching upstream Sync::Init { _framecount = 0; _rollingback = false; _max_prediction_frames = cfg; }

This dumps the candidates and tests the ring against each, so the key is identified by evidence
rather than by my arithmetic.
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from savestate import Game, BLK_PTR, FC_OFF
from mvcmem import EXE

SESSION_PTR_OFF = 0x2E10B98
SYNC_OFF, QUEUES_OFF, NPLAYERS_OFF = 0x9F0, 0x190, 0x174
IQ_STRIDE, INPUTS_OFF, GI_STRIDE, RING = 0xE44, 40, 28, 128
LAST_ADDED_OFF = 24

g = Game()
# WAIT for a session rather than bailing: the operator starts this, THEN queues a match. Bailing
# instantly means the probe can only ever be run in a window that has already closed.
print("waiting for a GGPO session (queue an online match)... Ctrl-C to give up")
sess = None
while sess is None:
    p = g.u64(EXE + SESSION_PTR_OFF)
    if p and 0x10000 < p < 0x7FFF_FFFF_FFFF:
        sess = p
        break
    time.sleep(0.5)
print("session up - waiting 8s for the ring to fill\n")
time.sleep(8)
sync = sess + SYNC_OFF
queues = g.u64(sync + QUEUES_OFF)
n = g.u32(sync + NPLAYERS_OFF)
blk = g.u64(BLK_PTR)

print(f"session 0x{sess:x}  sync 0x{sync:x}  queues 0x{queues:x}  nplayers {n}\n")

# ── 1. what do the Sync scalars actually read? ──────────────────────────────────────────────────
print("Sync scalars (looking for a counter near _last_added_frame):")
la = [g.u32(queues + k * IQ_STRIDE + LAST_ADDED_OFF) for k in range(n)]
print(f"  _last_added_frame per queue : {la}")
print(f"  blk+0x3CC8 (game counter)   : {g.u32(blk + FC_OFF)}")
for off in (0x17c, 0x180, 0x184, 0x188, 0x18c, 0x198, 0x19c, 0x1a0):
    v = g.u32(sync + off)
    sv = struct.unpack("<i", struct.pack("<I", v))[0] if v is not None else None
    print(f"  sync+0x{off:03x} = {v:>12}  (signed {sv})")

# ── 2. what frames does the ring ACTUALLY hold right now? ───────────────────────────────────────
print("\nring contents, queue 0 (slot: frame/size) - 16 consecutive slots:")
base = la[0] if la and la[0] else 0
row = []
for s in range(16):
    slot = (base - 8 + s) % RING
    b = g.read(queues + INPUTS_OFF + slot * GI_STRIDE, 12)
    if b and len(b) >= 12:
        fr, sz, bits = struct.unpack("<iiI", b)
        row.append(f"[{slot}] {fr}/{sz}")
print("  " + "  ".join(row))

# ── 3. does slot == frame % 128 hold, using the ring's OWN frames? ───────────────────────────────
ok = bad = 0
for slot in range(RING):
    b = g.read(queues + INPUTS_OFF + slot * GI_STRIDE, 8)
    if not b or len(b) < 8:
        continue
    fr, sz = struct.unpack("<ii", b)
    if fr < 0:
        continue
    if fr % RING == slot:
        ok += 1
    else:
        bad += 1
print(f"\nSELF-CONSISTENCY: slots whose stored frame satisfies frame%128==slot : {ok} ok / {bad} bad")
print("  -> if ok is high, the ring IS indexed by frame%128 and only my frame SOURCE was wrong.")

# ── 4. track which candidate advances 1:1 with the ring ──────────────────────────────────────────
print("\nsampling 3s to see which counter tracks _last_added_frame...")
cands = {"blk+0x3CC8": None, "sync+0x184": None, "sync+0x188": None, "sync+0x18c": None}
first, last = {}, {}
t0 = time.time()
while time.time() - t0 < 3.0:
    vals = {"blk+0x3CC8": g.u32(blk + FC_OFF), "sync+0x184": g.u32(sync + 0x184),
            "sync+0x188": g.u32(sync + 0x188), "sync+0x18c": g.u32(sync + 0x18c),
            "_last_added": g.u32(queues + LAST_ADDED_OFF)}
    for k, v in vals.items():
        if v is None:
            continue
        first.setdefault(k, v)
        last[k] = v
    time.sleep(0.01)
for k in first:
    print(f"  {k:<14} {first[k]:>10} -> {last[k]:>10}   delta {last[k]-first[k]:>6}")
print("\n(the GGPO frame key is the one whose delta matches _last_added's over the same window)")
