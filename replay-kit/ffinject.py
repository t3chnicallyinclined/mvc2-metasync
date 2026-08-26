#!/usr/bin/env python3
"""ffinject.py [rates...] — does input injection still land on the right frame under fast-forward?

THE UNVERIFIED CLAIM. `ffspeed.py` measured 22,403 sim frames/sec at frames-to-run=8 (373x) and
that number is quoted for host-node throughput. But it measured PURE SIMULATION with no inputs. A
replay must also put the correct input word on each frame, and at 22k fps that is ~22,000 polls plus
~22,000 writes per second. The arithmetic says it fits (~2.5 us per RPM/WPM => ~110 ms of a second).
Arithmetic is not a measurement, and this session has been wrong twice while confident.

THE TEST. Write a UNIQUE, FRAME-DERIVED value as the input on each frame, then read the engine's own
PREVIOUS-input register (G+0x228 = IN0+0x10) on the following frame. The engine copies cur -> prev
itself each tick, so prev tells us what the sim ACTUALLY consumed for that frame — not what we
believe we wrote. Any frame where prev does not match what we wrote for it is a real miss.

Uses a directions-free, harmless bit (START is excluded) so a stray press cannot do anything odd in
training mode; only the low byte varies.

Read/writes only the input words and frames-to-run — never the sim state.
"""
import struct
import sys
import time
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from savestate import Game, BLK_PTR, FC_OFF
from inputrec import IN0, patch, sanity
from mvcmem import EXE

FRAMES_TO_RUN = EXE + 0xAC74D8      # G+0x798
PREV = IN0 + 0x10                   # G+0x228 — engine writes prev = cur each tick
TEST_FRAMES = 600

rates = [int(a) for a in sys.argv[1:]] or [1, 2, 4, 8]


def stamp(fc):
    """A value unique per frame, inside the 24-bit input mask, with no meaningful buttons set."""
    return 0x010000 | (fc & 0xFF)


def run(g, blk, rate):
    written = {}          # frame -> value we wrote FOR that frame
    seen = {}             # frame -> value the engine reported consuming
    last = None
    f0 = g.u32(blk + FC_OFF)
    t0 = time.perf_counter()
    deadline = t0 + 20.0
    while time.perf_counter() < deadline:
        cur = g.u32(blk + FC_OFF)
        if cur == last:
            continue
        # the engine has just started frame `cur`; prev holds what it consumed for cur-1
        if last is not None and last in written:
            seen[last] = g.u32(PREV)
        last = cur
        if cur - f0 >= TEST_FRAMES:
            break
        v = stamp(cur + 1)
        g.write(IN0, struct.pack("<I", v))
        written[cur + 1] = v
        if rate > 1:
            g.write(FRAMES_TO_RUN, struct.pack("<I", rate))
    dt = time.perf_counter() - t0
    advanced = g.u32(blk + FC_OFF) - f0

    checked = [(f, written[f]) for f in written if f in seen]
    hits = sum(1 for f, v in checked if seen[f] == v)
    return advanced, dt, len(written), len(checked), hits


g = Game()
sanity(g)
blk = g.u64(BLK_PTR)
print(f"frames-to-run   sim fps    frames    written   verified   correct   fidelity")
patch(g, True)
try:
    for rate in rates:
        adv, dt, wrote, checked, hits = run(g, blk, rate)
        fid = (100.0 * hits / checked) if checked else 0.0
        print(f"{rate:>13}  {adv/dt:9,.0f}  {adv:8,}  {wrote:9,}  {checked:9,}  {hits:8,}  "
              f"{fid:6.1f}%")
        g.write(FRAMES_TO_RUN, struct.pack("<I", 1))
        time.sleep(0.5)
finally:
    patch(g, False)
    g.write(FRAMES_TO_RUN, struct.pack("<I", 1))
    print("\ncode un-patched, frames-to-run restored to 1")

print("\n'verified' = frames where we could read back what the engine consumed.")
print("'fidelity' < 100% at a given rate means a replay CANNOT be trusted at that speed.")
