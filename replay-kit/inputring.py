#!/usr/bin/env python3
"""inputring.py [secs] - READ-ONLY. Verify GGPO's CONFIRMED input ring, and prove the latch lies.

*** WRITES NOTHING. Reads only. Safe to run during a real ranked match. ***

WHAT THIS SETTLES
`docs/STEAM-GGPO-INPUTQUEUE.md` located GGPO's input queues by decompiling Sync::Init. The chain down
to `stride 0xE44` was READ FROM THE BINARY. The offsets INSIDE a queue are INFERRED from upstream
GGPO's layout -- strongly supported (0xE44 is exactly upstream's sizeof(InputQueue), and
40 + 128*28 = 3624, +28 = 3652 = 0xE44 closes to the byte) but never read live. This reads them live.

THE SECOND, BIGGER THING IT PROVES
We currently record inputs by polling `G+0x218`, the post-SynchronizeInputs latch. For the REMOTE
seat that holds a PREDICTION whenever the peer's packet is late, and GGPO's predictor repeats the
last confirmed input verbatim. So this probe compares, for the same frame:

    LATCH  G+0x218          <- what every tape we have ever shipped recorded
    RING   _inputs[f % 128] <- what the frame's input ACTUALLY was, once confirmed

If those disagree on any frame, the latch is demonstrably not the authoritative record and every
existing tape carries a smeared opponent. That is the finding, and it needs no interpretation.

⚠ ONLINE ONLY. GGPO does not register a session offline -- in training the session pointer reads
null and this probe will correctly report "no session". Queue a ranked/custom match.

Usage:  PLAY a match, then run:  python inputring.py [seconds]      (default: until you press a key)
"""
import os
import struct
import sys
import time

try:
    import msvcrt
except ImportError:
    msvcrt = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from savestate import Game, BLK_PTR, FC_OFF
from mvcmem import EXE

# ── exe-relative, from docs/STEAM-GGPO-INPUTQUEUE.md ────────────────────────────────────────────
SESSION_PTR_OFF = 0x2E10B98     # *(u64*) -> the ggpo session (set by start_session AND start_spectating)
SYNC_OFF = 0x9F0                # session + this = the Sync object
QUEUES_OFF = 0x190              # Sync::_input_queues (heap array, cookie at -8)   CONFIRMED
NPLAYERS_OFF = 0x174            # Sync::_num_players                                CONFIRMED
DELAY_OFF = 0x178               # Sync::_frame_delay                                CONFIRMED
IQ_STRIDE = 0xE44               # sizeof(InputQueue) == 3652                        CONFIRMED

INPUTS_OFF = 40                 # InputQueue::_inputs[128]                          INFERRED
GI_STRIDE = 28                  # sizeof(GameInput) {i32 frame; i32 size; u8 bits[20]}  INFERRED
RING = 128                      # INPUT_QUEUE_LENGTH                                INFERRED
PREDICTION_OFF = 3624           # InputQueue::_prediction (separate member)         INFERRED
LAST_ADDED_OFF = 24             # InputQueue::_last_added_frame (header)            INFERRED

IN0 = EXE + 0xAC6F58            # G+0x218 -- the latch we currently poll

SECS = float(sys.argv[1]) if len(sys.argv) > 1 else float("inf")

g = Game()
print("inputring - READ-ONLY. Nothing is written, ever.\n")

sess = None
t0 = time.time()
while time.time() - t0 < 20:
    p = g.u64(EXE + SESSION_PTR_OFF)
    if p and 0x10000 < p < 0x7FFF_FFFF_FFFF:
        sess = p
        break
    time.sleep(0.25)

if sess is None:
    sys.exit("no GGPO session (session ptr is null).\n"
             "  -> GGPO only registers ONLINE. Start a ranked/custom match and run this again.")

sync = sess + SYNC_OFF
queues = g.u64(sync + QUEUES_OFF)
nplayers = g.u32(sync + NPLAYERS_OFF)
delay = g.u32(sync + DELAY_OFF)
print(f"session   0x{sess:x}")
print(f"sync      0x{sync:x}")
print(f"queues    0x{queues:x}   nplayers={nplayers}  frame_delay={delay}")
if not queues or not nplayers or nplayers > 8:
    sys.exit("queues/nplayers look wrong -- the chain does not hold on this build. "
             "Fall back to the scan signature in docs/STEAM-GGPO-INPUTQUEUE.md.")
cookie = g.u64(queues - 8)
print(f"array cookie (should == nplayers): {cookie}   "
      f"{'OK' if cookie == nplayers else 'MISMATCH -- queues ptr may be wrong'}\n")


def gi(qbase, slot):
    """GameInput at ring slot -> (frame, size, bits4) or None."""
    b = g.read(qbase + INPUTS_OFF + slot * GI_STRIDE, 12)
    if not b or len(b) < 12:
        return None
    fr, sz, bits = struct.unpack("<iiI", b)
    return fr, sz, bits


hits = miss = 0
sizes = {}
agree = disagree = 0
disagree_ex = []
samples = 0
last_f = None
stopped = False

print("watching... (press any key to stop)\n")
while time.time() - t0 < SECS:
    if msvcrt and msvcrt.kbhit():
        msvcrt.getch()
        stopped = True
        break
    blk = g.u64(BLK_PTR)
    if not blk or blk < 0x10000:
        time.sleep(0.2)
        continue
    f = g.u32(blk + FC_OFF)
    if f is None or f == last_f:
        time.sleep(0.002)
        continue
    last_f = f
    samples += 1

    # rule 1: does the ring slot for THIS frame actually hold THIS frame?
    e0 = gi(queues, f % RING)
    if e0 is None:
        continue
    fr, sz, ring0 = e0
    if fr == f:
        hits += 1
    else:
        miss += 1
    sizes[sz] = sizes.get(sz, 0) + 1

    # rule 2: THE COMPARISON. latch vs ring, same frame, both seats.
    latch = g.read(IN0, 8)
    if latch and len(latch) == 8 and nplayers >= 2:
        l0, l1 = struct.unpack("<II", latch)
        e1 = gi(queues + IQ_STRIDE, f % RING)
        if e1 and e1[0] == f and fr == f:
            if (ring0, e1[2]) == (l0, l1):
                agree += 1
            else:
                disagree += 1
                if len(disagree_ex) < 8:
                    disagree_ex.append((f, l0, l1, ring0, e1[2]))

el = max(1e-9, time.time() - t0)
print(f"--- {'stopped' if stopped else 'time cap'} after {el:.0f}s, {samples} frames ---\n")

tot = hits + miss
print(f"1. RING SLOT HOLDS ITS OWN FRAME : {hits}/{tot} "
      f"({100.0*hits/max(1,tot):.1f}%)")
print(f"2. GameInput.size values seen    : {dict(sorted(sizes.items()))}  (expect 4)")
lo = [g.u32(queues + k * IQ_STRIDE + LAST_ADDED_OFF) for k in range(min(nplayers, 4))]
print(f"3. _last_added_frame per queue   : {lo}   (should track the live frame)")
print(f"4. latch vs ring  agree {agree}  DISAGREE {disagree}")
for f_, l0, l1, r0, r1 in disagree_ex:
    print(f"     frame {f_}: latch=({l0:#x},{l1:#x})  ring=({r0:#x},{r1:#x})")

ok = tot and (hits / tot) > 0.9 and set(sizes) <= {4}
print("\nVERDICT: " + (
    "INFERRED OFFSETS CONFIRMED. _inputs[f%128] holds frame f with size 4.\n"
    "         The confirmed ring is readable -- stop polling the latch."
    if ok else
    "NOT CONFIRMED. The in-queue offsets do not hold as inferred. Read the numbers above,\n"
    "         then fall back to the scan signature in docs/STEAM-GGPO-INPUTQUEUE.md."))
if disagree:
    print(f"\n*** THE LATCH DISAGREED WITH THE CONFIRMED RING ON {disagree} FRAME(S). ***\n"
          "    That is the predicted-input problem, measured. Every tape recorded off G+0x218\n"
          "    carries those wrong values -- and they cluster exactly where the connection is worst.")
elif agree:
    print(f"\n    Latch matched the ring on all {agree} compared frames -- a clean connection this\n"
          "    session (few/no predictions). Re-run on a laggy match before concluding the latch is safe.")
