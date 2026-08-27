#!/usr/bin/env python3
"""inputring.py [secs] - READ-ONLY. Does the latch we record actually match GGPO's confirmed inputs?

*** WRITES NOTHING. Reads only. Safe during a real ranked match. ***

BACKGROUND (all CONFIRMED live 2026-08-27, see docs/STEAM-GGPO-INPUTQUEUE.md)
  session = *(u64*)0x142E10B98 ; sync = session+0x9F0 ; queues = *(u64*)(sync+0x190)
  InputQueue stride 0xE44 ; _inputs at +40 ; GameInput stride 28 ; 128 slots ; keyed frame % 128
  sync+0x184 = _last_confirmed_frame   sync+0x188 = _framecount (== blk+0x3CC8, same number)
  sync+0x18c = _max_prediction_frames = 8   sync+0x178 = _frame_delay

⚠ THE RING LAGS THE LIVE FRAME. _last_added_frame trailed _framecount by 3 when measured. Asking the
ring for the CURRENT frame returns a stale entry from 128 frames ago -- that is what produced an
earlier 0/6875 result, and it was the READER's bug. Harvest the ring continuously and join afterwards.

WHAT THIS MEASURES
The agent records inputs by polling G+0x218, the post-SynchronizeInputs latch. For the REMOTE seat
that holds a PREDICTION whenever the peer's packet is late (GGPO's predictor repeats the last
confirmed input verbatim). So for every frame we hold BOTH:

    LATCH  G+0x218 sampled at frame N   <- what every shipped tape recorded
    RING   the confirmed input for N    <- what frame N's input actually was

Disagreements are direct evidence that existing tapes carry a fabricated opponent.

SELF-CALIBRATING ON FRAME DELAY. Upstream AdvanceQueueHead stores at `frame + _frame_delay` (live: 4),
so a stored .frame may not mean "consumed on frame N". Rather than assume, this tries every shift in
[-12,+12] and reports which one maximises agreement. The winning shift IS the delay semantic,
measured. (The GGPO source is still the authority; this is corroboration, not a substitute.)
"""
import os
import struct
import sys
import time
from collections import Counter

try:
    import msvcrt
except ImportError:
    msvcrt = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from savestate import Game, BLK_PTR, FC_OFF
from mvcmem import EXE

SESSION_PTR_OFF = 0x2E10B98
SYNC_OFF = 0x9F0
# ⚠ sync+0x178 is _config.INPUT_SIZE (== 4), NOT frame delay. Sync::CreateQueues calls
# InputQueue::Init(i, _config.input_size) -- there is no frame-delay arg, and Init zeroes it.
# The REAL _frame_delay is per-queue at queue+36, and it is a WRITE-side shift only: never index with it.
NPLAYERS_OFF, INPUT_SIZE_OFF = 0x174, 0x178
LAST_CONF_OFF, FRAMECOUNT_OFF, MAXPRED_OFF, QUEUES_OFF = 0x184, 0x188, 0x18c, 0x190
IQ_STRIDE, INPUTS_OFF, GI_STRIDE, RING = 0xE44, 40, 28, 128
Q_ID_OFF, Q_LAST_ADDED_OFF, Q_FRAME_DELAY_OFF = 0, 24, 36
ROLLINGBACK_OFF = 0x180
# ⚠⚠ TWO CONFOUNDS, both read out of the latch-fill routine at 0x140118950. Without these the
# comparison below manufactures disagreements that have NOTHING to do with prediction:
#   and ecx, 0xffffff                    -> the latch keeps only the LOW 24 BITS
#   mov [rdx + rax*4 + 0x218], ecx       -> where rax = *(i32*)(G + 0x258 + i*4), a RUNTIME
#                                           seat->slot PERMUTATION (negative = seat not present)
LATCH_MASK = 0xFFFFFF
SEATMAP = EXE + 0xAC6F98        # G+0x258
IN0 = EXE + 0xAC6F58            # G+0x218 -- the latch the agent polls

SECS = float(sys.argv[1]) if len(sys.argv) > 1 else float("inf")

g = Game()
print("inputring - READ-ONLY. Nothing is written, ever.")
print("waiting for a GGPO session (queue an ONLINE match)... Ctrl-C to give up")
sess = None
while sess is None:
    p = g.u64(EXE + SESSION_PTR_OFF)
    if p and 0x10000 < p < 0x7FFF_FFFF_FFFF:
        sess = p
    else:
        time.sleep(0.5)

sync = sess + SYNC_OFF
queues = g.u64(sync + QUEUES_OFF)
n = g.u32(sync + NPLAYERS_OFF) or 0
input_size = g.u32(sync + INPUT_SIZE_OFF)
maxpred = g.u32(sync + MAXPRED_OFF)
print(f"\nsession 0x{sess:x}  sync 0x{sync:x}  queues 0x{queues:x}")
print(f"nplayers {n}  input_size {input_size}  max_prediction_frames {maxpred}")
if not queues or n < 2:
    sys.exit("need >=2 queues -- is this really an online match?")
# Self-validating attach checks (Sync::CreateQueues sets _id = i; MSVC new[] cookie holds the count).
cookie = g.u64(queues - 8)
ids = [g.u32(queues + k * IQ_STRIDE + Q_ID_OFF) for k in range(n)]
fdel = [g.u32(queues + k * IQ_STRIDE + Q_FRAME_DELAY_OFF) for k in range(n)]
print(f"array cookie {cookie} {'OK' if cookie == n else 'MISMATCH'}   "
      f"_id per queue {ids} {'OK' if ids == list(range(n)) else 'MISMATCH -- layout wrong, STOP'}")
print(f"_frame_delay per queue (the REAL one, queue+36): {fdel}   "
      f"[write-side shift only - never used to index]")
# The game's counter vs GGPO's. Measured EQUAL once (both 416, both +179/3s); the expert expects a
# possible origin offset. Report it rather than assume either way.
blk = g.u64(BLK_PTR)
print(f"_framecount {g.u32(sync + FRAMECOUNT_OFF)}   blk+0x3CC8 {g.u32(blk + FC_OFF) if blk else None}   "
      f"_last_confirmed {g.u32(sync + LAST_CONF_OFF)}")
print("\nplay the set; press any key here when done.\n")

latch = {}            # frame -> (l0, l1)   sampled live
ring = [dict() for _ in range(n)]   # per queue: frame -> bits
lag = Counter()
last_f = None
t0 = time.time()
last_harvest = 0.0
stopped = False


nonzero_bits = [0] * n     # G8-style liveness: a dead (Init-only) ring is all-zero bits


def harvest():
    """Pull every confirmed entry out of each ring. 3584 B/queue, ~1/s is ample (128 frames = 2.13s).
    Mask to 24 bits so ring values compare against the 24-bit latch. G2 self-consistency (frame%128==slot)
    is the gate for accepting a slot -- it, not sz==4, is what proves the slot was actually written."""
    for k in range(n):
        buf = g.read(queues + k * IQ_STRIDE + INPUTS_OFF, RING * GI_STRIDE)
        if not buf or len(buf) < RING * GI_STRIDE:
            continue
        for s in range(RING):
            fr, sz, bits = struct.unpack_from("<iiI", buf, s * GI_STRIDE)
            if fr >= 0 and sz == 4 and fr % RING == s:
                ring[k][fr] = bits & LATCH_MASK
                if bits & LATCH_MASK:
                    nonzero_bits[k] += 1


while time.time() - t0 < SECS:
    if msvcrt and msvcrt.kbhit():
        msvcrt.getch()
        stopped = True
        break
    fc = g.u32(sync + FRAMECOUNT_OFF)
    if fc is None:
        break
    if fc != last_f:
        last_f = fc
        # skip frames sampled mid-rollback: the latch is being rewritten under us
        if g.u8(sync + ROLLINGBACK_OFF) == 0:
            b = g.read(IN0, 16)     # 4 seat words, not 2 -- the permutation can target any of them
            if b and len(b) == 16:
                words = struct.unpack("<IIII", b)
                # queue k's value lands at word seatmap[k]; negative means the seat is absent
                slots = [g.i32(SEATMAP + 4 * k) for k in range(n)]
                if all(s is not None and 0 <= s < 4 for s in slots):
                    latch[fc] = tuple(words[s] & LATCH_MASK for s in slots)
        lc = g.u32(sync + LAST_CONF_OFF)
        if lc is not None:
            lag[fc - lc] += 1
    now = time.time() - t0
    if now - last_harvest >= 1.0:
        last_harvest = now
        harvest()
    time.sleep(0.002)

harvest()   # final sweep so the tail of the match is not lost
el = max(1e-9, time.time() - t0)
print(f"--- {'stopped' if stopped else 'time cap'} after {el:.0f}s ---")
print(f"latch samples {len(latch)}   ring entries {[len(r) for r in ring]}   "
      f"sim {(max(latch)-min(latch))/el:.1f} Hz" if latch else "no samples")
if lag:
    print(f"_framecount - _last_confirmed_frame: {sorted(lag.items())[:8]}  (how far the ring trails)")

# ── G8 NEGATIVE CONTROL: a dead, Init-only ring reads frame%128==slot on stale slots too, so the
#    self-consistency gate alone is NOT liveness. A live ring MUST carry nonzero input bits. ──
print(f"\nliveness: nonzero-input entries per queue {nonzero_bits}")
if not latch or not any(ring) or not any(nonzero_bits):
    sys.exit("DEAD or EMPTY ring -- no queue carried a nonzero input. Not a running fight, or the\n"
             "layout is wrong. (This is the negative control: at a menu this is the CORRECT result.)")

# ── which shift aligns the latch with the ring? key by _framecount; the shift should come out 0 ──
print("\nshift  compared  agree   disagree   agreement")
best = None
for sh in range(-12, 13):
    comp = ag = 0
    for f, lw in latch.items():
        rw = [ring[k].get(f + sh) for k in range(n)]
        if any(v is None for v in rw):
            continue
        comp += 1
        if tuple(rw) == lw:
            ag += 1
    if comp >= 30:
        pct = 100.0 * ag / comp
        if best is None or pct > best[1]:
            best = (sh, pct, comp, ag)
        print(f"{sh:>+5}  {comp:>8}  {ag:>5}  {comp-ag:>8}   {pct:>7.1f}%")

if best is None:
    sys.exit("\nno shift had enough overlap to compare -- run a longer match.")

sh, pct, comp, ag = best
print(f"\nBEST ALIGNMENT: shift {sh:+d}  ->  {pct:.1f}% agreement over {comp} frames")
if sh == 0:
    print("  => a stored .frame N IS the input the sim consumed on frame N. No delay adjustment.")
else:
    print(f"  => the ring is offset by {sh:+d} from the latch. A recorder MUST apply this shift,")
    print(f"     or every input lands {abs(sh)} frames from where it belongs (looks plausible, replays wrong).")

dis = comp - ag
print(f"\nLATCH vs CONFIRMED RING (at shift {sh}, both masked to 24 bits, seat-permuted, "
      f"rollback frames skipped):")
print(f"  {dis} disagreement(s) in {comp} compared frames ({100.0*dis/comp:.2f}%)")
if dis:
    print("  -> On these frames the value we sampled from the latch differed from GGPO's confirmed")
    print("     record. NOTE: the latch SELF-CORRECTS on the rollback re-sim path, so this is a")
    print("     SAMPLING-RACE measurement (we caught a pre-correction value), not proof the latch is")
    print("     permanently wrong. It is the magnitude the confirmed-ring read would eliminate.")
    shown = 0
    for f, lw in sorted(latch.items()):
        rw = tuple(ring[k].get(f + sh) for k in range(n))
        if all(v is not None for v in rw) and rw != lw:
            print(f"      frame {f}: latch={tuple(hex(x) for x in lw)}  confirmed={tuple(hex(x) for x in rw)}")
            shown += 1
            if shown >= 10:
                break
else:
    print("  Latch matched the ring on every compared frame. That is NOT proof the latch is safe --")
    print("  it most likely means a clean connection with few predictions this session. Re-run on a")
    print("  laggy match before concluding anything.")
