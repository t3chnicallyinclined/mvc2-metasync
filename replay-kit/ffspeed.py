#!/usr/bin/env python3
"""ffspeed.py [rate] — how fast can the sim actually run? This is the tape-throughput number.

FUN_140039de0 is the offline frame driver:
    G[0x798] = 1;                          // frames to run this tick
    while (G[0x798] >= 1 && !G[0x780]) {
        G[0x770] = (G[0x798] > 1);         // SKIP RENDER on catch-up frames
        ...
        (*(code**)(G + 0x10))();           // one sim frame
        G[0x768]++;  G[0x798]--;
    }
So writing a larger value into G+0x798 makes the engine run that many sim frames per tick, and it
suppresses rendering for all but the last — the engine's own fast-forward, not a hack we added.

Measures the baseline rate, then the rate while we keep topping up frames-to-run, and reports the
multiplier plus what it implies for re-simulating tapes.
"""
import struct
import sys
import time
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from savestate import Game, BLK_PTR, FC_OFF
from mvcmem import EXE

FRAMES_TO_RUN = EXE + 0xAC74D8      # G+0x798
SKIP_RENDER = EXE + 0xAC74B0        # G+0x770
RATE = int(sys.argv[1]) if len(sys.argv) > 1 else 8

g = Game()
blk = g.u64(BLK_PTR)


def fps(seconds, drive=None):
    f0 = g.u32(blk + FC_OFF)
    t0 = time.perf_counter()
    n = 0
    while time.perf_counter() - t0 < seconds:
        if drive:
            g.write(FRAMES_TO_RUN, struct.pack("<I", drive))
            n += 1
    dt = time.perf_counter() - t0
    return (g.u32(blk + FC_OFF) - f0) / dt, n


base, _ = fps(2.0)
print(f"baseline           : {base:7.1f} sim frames/sec")

fast, writes = fps(3.0, RATE)
print(f"frames-to-run={RATE:<4}  : {fast:7.1f} sim frames/sec  ({writes} writes)")

g.write(FRAMES_TO_RUN, struct.pack("<I", 1))
time.sleep(0.3)
after, _ = fps(1.0)
print(f"after restoring 1  : {after:7.1f} sim frames/sec")

mult = fast / base if base else 0
print(f"\nspeedup: {mult:.1f}x realtime")
for mins in (3, 5):
    frames = mins * 60 * 60
    print(f"  a {mins}-minute match ({frames:,} frames) re-simulates in "
          f"{frames/fast:6.1f}s  ->  {3600*fast/frames:6.1f} tapes/hour/instance")
