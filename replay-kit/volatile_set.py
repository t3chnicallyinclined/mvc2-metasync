#!/usr/bin/env python3
"""volatile_set.py <boot1> <boot2> ... — the exact bytes a tape must carry.

Two cold boots reach character select in ~99.6% identical simulation state. Of the words that do
differ, most are just the SAME POINTER RELOCATED (blk moves every launch; the 256 MiB arena does
not). What remains is the VOLATILE SET: the handful of words that genuinely vary run to run.

This computes the union of that set across every pair of captures, so the replay format is:

    tape = inputs (~2 B/frame)  +  volatile-set patch (a few hundred bytes)

and needs NO snapshot — which is what makes it portable to any PC that owns the game, instead of
being bound to the process, arena and exe image that recorded it.
"""
import itertools
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from savestate import BLKSZ

HERE = os.path.dirname(os.path.abspath(__file__))
ASZ = 0x10000000


def load(name):
    meta = json.load(open(os.path.join(HERE, name + ".meta.json")))
    return meta, open(os.path.join(HERE, name + ".blk"), "rb").read()


names = sys.argv[1:]
caps = [load(n) for n in names]
print(f"{len(caps)} captures: " + ", ".join(
    f"{n}(blk=0x{m['blk']:x},f={m['frame']})" for n, (m, _) in zip(names, caps)))

volatile = set()
for (na, (ma, da)), (nb, (mb, db)) in itertools.combinations(zip(names, caps), 2):
    d_blk = mb["blk"] - ma["blk"]
    d_arena = mb["arena"] - ma["arena"]
    n = 0
    for off in range(0, min(len(da), len(db)) - 8, 8):
        wa = int.from_bytes(da[off:off + 8], "little")
        wb = int.from_bytes(db[off:off + 8], "little")
        if wa == wb:
            continue
        if (ma["blk"] <= wa < ma["blk"] + BLKSZ and wb - wa == d_blk) or \
           (ma["arena"] <= wa < ma["arena"] + ASZ and wb - wa == d_arena):
            continue                       # just a relocated pointer
        volatile.add(off)
        n += 1
    print(f"  {na} vs {nb}: {n} volatile words")

# merge adjacent words into runs so the patch is compact
runs = []
for off in sorted(volatile):
    if runs and off == runs[-1][1]:
        runs[-1][1] = off + 8
    else:
        runs.append([off, off + 8])

total = sum(hi - lo for lo, hi in runs)
print(f"\nVOLATILE SET: {len(volatile)} words in {len(runs)} runs = {total} bytes "
      f"({100.0*total/BLKSZ:.3f}% of the {BLKSZ}-byte state)")

FC_OFF = 0x3CC8
named = []
for lo, hi in runs:
    tag = ""
    if lo <= FC_OFF < hi:
        tag = "frame counter"
    elif 0x3DB8 <= lo < 0x3DB8 + 6 * 0x738:
        tag = f"fighter slot {(lo - 0x3DB8) // 0x738}"
    elif 0x3C66 <= lo < 0x3CB8:
        tag = "input words"
    elif 0x2f4d0 <= lo < 0x32530:
        tag = "draw list / slot table"
    elif 0x32be0 <= lo < 0x32c00:
        tag = "render attrs"
    named.append({"off": lo, "len": hi - lo, "tag": tag})

print("\nlargest runs:")
for r in sorted(named, key=lambda r: -r["len"])[:15]:
    print(f"   blk+0x{r['off']:05x}  {r['len']:4d} B   {r['tag']}")

out = os.path.join(HERE, "volatile_set.json")
json.dump({"blk_size": BLKSZ, "bytes": total, "runs": named}, open(out, "w"), indent=1)
print(f"\nwrote {out}")
print("=> a tape carries these bytes + the input stream. No snapshot. Nothing to relocate.")
