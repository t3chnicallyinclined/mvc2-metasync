#!/usr/bin/env python3
"""merge_cursor.py <capA> <capB> — add character-select cursor state to the patch set.

The boot-diff found what varies across COLD BOOTS. It could never find the cursor: all three
boots had it at its default, so it never differed. But a tape replays into a session where the
player left the cursor somewhere else, and identical directional inputs then land on a different
character — which is exactly what we observed (tape wanted cid 44, replays produced 19, then 27).

capA/capB are two captures from the SAME process with the cursor moved between them, so every
difference is character-select state. Confirmed by inspection: blk+0x4478 == blk+0x3DB8+0x6C0 is
fighter slot 0's CID field, and it tracked Servbot(0x3a) -> Sentinel(0x34). The remaining words
are floats (0x3f800000 = 1.0f) — the rotating preview models.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from savestate import BLKSZ

HERE = os.path.dirname(os.path.abspath(__file__))
a, b = sys.argv[1], sys.argv[2]
A = open(os.path.join(HERE, a + ".blk"), "rb").read()
B = open(os.path.join(HERE, b + ".blk"), "rb").read()

vs = os.path.join(HERE, "volatile_set.json")
words = set()
for r in json.load(open(vs))["runs"]:
    for o in range(r["off"], r["off"] + r["len"], 8):
        words.add(o)
before = len(words)

for off in range(0, min(len(A), len(B)) - 8, 8):
    if A[off:off + 8] != B[off:off + 8]:
        words.add(off)

runs = []
for off in sorted(words):
    if runs and off == runs[-1][1]:
        runs[-1][1] = off + 8
    else:
        runs.append([off, off + 8])

FC = 0x3CC8
named = []
for lo, hi in runs:
    tag = ""
    if lo <= FC < hi:
        tag = "frame counter"
    elif 0x3DB8 <= lo < 0x3DB8 + 6 * 0x738:
        s = (lo - 0x3DB8) // 0x738
        f = (lo - 0x3DB8) % 0x738
        tag = f"fighter slot {s}" + (" CID (cursor)" if f == 0x6C0 else "")
    elif 0x1e000 <= lo < 0x2a000:
        tag = "char-select preview"
    named.append({"off": lo, "len": hi - lo, "tag": tag})

total = sum(r["len"] for r in named)
json.dump({"blk_size": BLKSZ, "bytes": total, "runs": named}, open(vs, "w"), indent=1)
print(f"patch set: {before} -> {len(words)} words = {total} bytes in {len(runs)} runs")
print("cursor-bearing entries:")
for r in named:
    if "CID" in r["tag"] or r["off"] in (0x3db8, 0x4478):
        print(f"   blk+0x{r['off']:05x}  {r['len']:3d} B  {r['tag']}")
