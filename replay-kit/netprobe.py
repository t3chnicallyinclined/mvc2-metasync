#!/usr/bin/env python3
"""netprobe.py [secs] - READ-ONLY observer for a REAL ONLINE MATCH. Writes nothing, ever.

Three things are unobservable offline and have been open all session. A ranked match answers all
three, and none of it can be faked in training mode:

1. **GGPO REGISTRATION.** `DAT_142d10950 / 142d107d0 / 142d108d0` are what GGPO actually recorded as
   the registered save/restore region. Offline they read 0 - registration only happens when a
   session starts. In a live match they should show ONE region == blk, size 0x33B18. That turns the
   central claim of the whole replay design from "read from the registration code" into "observed
   in the live netcode".
   ! `FUN_140118290` FORKS on `G+0x48`: <3 registers 10-18 regions (the emulated-CPS path), >=3
   registers the single pair. MvC2 reads 11. We assert it rather than assume it.

2. **THE SEAT MAP.** `G+0x258 + k*4` maps GGPO player k -> seat index (-1 = unmapped). It reads all
   zeros offline, so we have never seen it populated. It is the fix for the documented side-swap,
   and 0.3.24 records it - but nobody has confirmed what it looks like when it is real.

3. **ROLLBACKS.** `G+0x76C` counts load_game_state calls. Offline it is 0 forever. Online it should
   climb. That matters two ways: it proves the sim really is being rewound and re-simulated (which
   is the entire basis for "blk holds everything that changes"), and it is the tape-quality signal -
   a snapshot taken on a frame that got rolled back is not the frame the tape thinks it is.

Also samples both seats' raw input words so we can confirm P2's seat carries real data online (it is
always zero offline, so the two-seat path has never actually been exercised).
"""
import os
import struct
import sys
import time

try:                  # Windows: lets ENTER stop the probe cleanly. Ctrl-C also hits the .cmd
    import msvcrt     # wrapper and pops "Terminate batch job (Y/N)?" mid-summary.
except ImportError:
    msvcrt = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from savestate import Game, BLK_PTR, FC_OFF
from mvcmem import EXE

IN0 = EXE + 0xAC6F58          # G+0x218
SEATMAP = EXE + 0xAC6F98      # G+0x258
ROLLBACKS = EXE + 0xAC74AC    # G+0x76C
G_SEL = EXE + 0xAC6D40 + 0x48 # the registration fork
REG_COUNT, REG_BASE, REG_SIZE = 0x142D10950, 0x142D107D0, 0x142D108D0
# Runs until you press ENTER. Pass a number of seconds for a hard cap instead.
SECS = float(sys.argv[1]) if len(sys.argv) > 1 else float("inf")

g = Game()
print("netprobe - READ-ONLY. Play your ranked match; I will not touch anything.\n")

seen_reg = None
seen_seats = None
max_rb = 0
modes = {}
p2_seen = 0
samples = 0
t0 = time.time()
last_line = 0.0
last_fc = None

stopped = False
while time.time() - t0 < SECS:
    if msvcrt and msvcrt.kbhit():
        msvcrt.getch()          # any key stops it - no need to remember which
        stopped = True
        break
    try:
        blk = g.u64(BLK_PTR)
        if not blk or blk < 0x10000:
            time.sleep(0.2)
            continue
        fc = g.u32(blk + FC_OFF)
        if fc == last_fc:
            continue
        last_fc = fc
        samples += 1

        mode = g.read(blk + 0x3CB8, 5)[2]
        modes[mode] = modes.get(mode, 0) + 1

        rb = g.u32(ROLLBACKS) or 0
        max_rb = max(max_rb, rb)

        seats = tuple(int.from_bytes(g.read(SEATMAP + 4 * k, 4), "little", signed=True)
                      for k in range(4))
        if seats != (0, 0, 0, 0) and seats != seen_seats:
            seen_seats = seats
            print(f"  [{time.time()-t0:5.0f}s] SEAT MAP populated: {list(seats)}")

        n = g.u32(REG_COUNT) or 0
        if n and seen_reg != n:
            seen_reg = n
            base = g.u64(REG_BASE) or 0
            size = g.u32(REG_SIZE) or 0
            print(f"  [{time.time()-t0:5.0f}s] GGPO REGISTERED {n} region(s): "
                  f"base=0x{base:x} size=0x{size:x}   "
                  f"{'== blk, 0x33B18 OK' if base == blk and size == 0x33B18 else '! NOT blk/0x33B18'}")
            print(f"            G+0x48 = {g.u32(G_SEL)} "
                  f"({'single-region arm (>=3) OK' if (g.u32(G_SEL) or 0) >= 3 else '! multi-region arm (<3)'})")

        if g.u32(IN0 + 4):
            p2_seen += 1

        now = time.time() - t0
        if now - last_line >= 15.0:
            last_line = now
            print(f"  [{now:5.0f}s] frame {fc}  mode {mode}  rollbacks {rb}  "
                  f"p2-input frames {p2_seen}")
    except OSError:
        time.sleep(0.3)

print(f"\n--- {'stopped by you' if stopped else 'time cap reached'} "
      f"after {time.time()-t0:.0f}s, {samples} frames sampled ---")
print(f"GGPO region count      : {seen_reg if seen_reg is not None else 'NEVER REGISTERED (no session seen)'}")
print(f"seat map               : {list(seen_seats) if seen_seats else 'never populated (all zeros)'}")
print(f"max rollback count     : {max_rb}   "
      f"{'<- the sim WAS rewound and re-simulated' if max_rb else '<- never rolled back'}")
print(f"frames with P2 input   : {p2_seen}")
print(f"modes seen             : {dict(sorted(modes.items()))}  (1 = char select, 2 = battle)")
