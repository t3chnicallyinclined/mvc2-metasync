#!/usr/bin/env python3
"""blkdelta.py — how many bytes of `blk` actually change per GAME FRAME?

    python blkdelta.py [frames]        # default 600 (10 s at 60 fps)

READ-ONLY. It attaches to the running game and reads; it never writes.

WHY THIS IS THE MEASUREMENT THAT MATTERS
----------------------------------------
Path B proved that replaying Steam's own draw stream reproduces its pixels (0.011-0.018% differing,
zero missing coverage, through a 3-meter triple super). But the draw stream costs ~37-62 KB/frame, so
it can never be the delivery format.

Steam's renderer consumes a COMMAND LIST that the game builds each frame (the executor is
FUN_1402B6F30; the buffer lives at renderer+0x8678F0, double-buffered, counted at +0x867900). If that
list is a function of the simulation state in `blk`, then the smallest possible feed is **a blk delta
per frame** — no simulation to re-run, no inputs to replay, no determinism certificate needed, and
none of the cross-core float divergence that killed the flycast free-run resim, because Steam's own
code is what turns the state back into pixels.

This script measures the input side of that: the size of a per-frame blk delta, raw and compressed.

WHAT A RESULT MEANS
-------------------
  * a few hundred bytes gzipped  -> the floor is better than every other candidate we have measured
                                    (the state tape is ~136 B/frame, the draw stream ~37 KB/frame)
  * a few KB gzipped             -> still far better than the draw stream, worth building
  * tens of KB                   -> blk is not the compact representation and the command list is

WHAT IT DOES NOT ESTABLISH
--------------------------
That the command list is a function of blk at all. That is a separate hypothesis with its own
falsifier (capture blk AND the command list on two frames with identical blk, and check the lists
match). This script measures a SIZE, not a mechanism. Do not let a small number here become a claim
about MvC2.

⚠ ROLLBACK. blk+0x3CC8 mirrors GGPO's _framecount, which Sync::LoadFrame assigns BACKWARD during a
rollback. Samples where the clock does not advance by exactly +1 are counted and excluded rather than
absorbed — a rollback frame is not a frame of forward progress and averaging it in would flatter the
result. Run this in an OFFLINE match if you want a clean number.
"""
import gzip
import struct
import sys
import time
from collections import Counter

import numpy as np

from savestate import Game, BLK_PTR, BLKSZ, FC_OFF
from verify import MODE_OFF


def main():
    frames = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 600

    g = Game()
    blk = g.u64(BLK_PTR)
    mode = g.read(blk + MODE_OFF, 5)[2]
    print(f"blk 0x{blk:x}  size 0x{BLKSZ:x} ({BLKSZ:,} B)  mode {mode} "
          f"({'CHAR SELECT' if mode == 1 else 'IN BATTLE' if mode == 2 else '?'})")
    if mode != 2:
        print("⚠ NOT IN A MATCH. The delta rate of a menu says nothing about a match — get into a "
              "fight first. Numbers collected here should be discarded.")

    def clock():
        return g.u32(blk + FC_OFF)

    print(f"sampling {frames} game frames — keep fighting, and make it busy\n")

    prev = np.frombuffer(g.read(blk, BLKSZ), np.uint8).copy()
    prev_f = clock()
    raw, gz, words, runs = [], [], [], []
    hot = np.zeros(BLKSZ // 4, np.int32)
    skipped = Counter()
    t0 = time.time()

    while len(raw) < frames:
        f = clock()
        if f == prev_f:
            time.sleep(0.0005)
            continue
        step = f - prev_f
        cur = np.frombuffer(g.read(blk, BLKSZ), np.uint8).copy()
        if step != 1:
            # a rollback (negative or jumped) or a frame we were too slow to catch
            skipped["rollback / clock jumped backward" if step < 0 else
                    f"missed {step - 1} frame(s) — sampler too slow"] += 1
            prev, prev_f = cur, f
            continue

        diff = cur != prev
        nbytes = int(diff.sum())
        # word granularity, because that is what a real delta encoder would key on
        w = diff.reshape(-1, 4).any(axis=1)
        hot += w
        # contiguous runs of changed bytes -> what an (offset,len,payload) encoding would cost
        edges = np.flatnonzero(np.diff(diff.astype(np.int8)) != 0) + 1
        nruns = (len(edges) + (1 if diff[0] else 0) + 1) // 2

        payload = cur[diff].tobytes()
        raw.append(nbytes)
        words.append(int(w.sum()))
        runs.append(nruns)
        gz.append(len(gzip.compress(payload, 6)))
        prev, prev_f = cur, f

    dt = time.time() - t0
    a = lambda v: (np.percentile(v, [50, 90, 99]), np.mean(v), np.max(v))

    print(f"sampled {len(raw)} consecutive frames in {dt:.1f}s "
          f"({len(raw)/dt:.1f} samples/s)")
    if skipped:
        print("  excluded:")
        for k, v in skipped.most_common():
            print(f"    {v:5d}  {k}")
        print("  (excluded frames are NOT averaged in — a rollback is not forward progress)")

    for name, v in (("changed BYTES", raw), ("changed WORDS", words), ("contiguous RUNS", runs)):
        p, mean, mx = a(v)
        print(f"\n{name:16s} median {p[0]:9,.0f}   p90 {p[1]:9,.0f}   p99 {p[2]:9,.0f}   "
              f"mean {mean:9,.0f}   max {mx:9,.0f}")

    p, mean, mx = a(gz)
    print(f"\n{'GZIPPED payload':16s} median {p[0]:9,.0f}   p90 {p[1]:9,.0f}   p99 {p[2]:9,.0f}   "
          f"mean {mean:9,.0f}   max {mx:9,.0f}   bytes/frame")

    # what a real encoding costs: run headers + payload, then compressed
    hdr = np.array(runs) * 8            # (u32 offset, u32 length) per run
    enc = np.array(raw) + hdr
    print(f"\nwith (offset,len) run headers at 8 B each: mean {enc.mean():,.0f} B/frame raw")
    print(f"a 3-minute match at the mean gzipped rate : "
          f"{180 * 60 * np.mean(gz) / 1048576:.1f} MB")
    print(f"  for comparison — the D3D11 draw stream  : ~400 MB")
    print(f"  the agent state tape                    : ~1.5 MB")
    print(f"  confirmed GGPO inputs                   : ~0.01 MB")

    touched = int((hot > 0).sum())
    print(f"\nof {BLKSZ//4:,} words in blk, {touched:,} ({100*touched/(BLKSZ//4):.1f}%) changed at "
          f"least once; {int((hot > len(raw)*0.5).sum()):,} changed in over half the frames")
    print("  ⟹ a static hot/cold split could shrink the header cost further")

    print("\n⚠ THIS IS A SIZE, NOT A MECHANISM. It does not establish that Steam's command list is a")
    print("  function of blk — that needs its own falsifier (identical blk on two frames must give")
    print("  identical command lists). Record as record_attempt(outcome='masks_only').")


if __name__ == "__main__":
    main()
