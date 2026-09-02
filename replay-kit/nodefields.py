#!/usr/bin/env python3
"""nodefields.py — what ARE the volatile columns of a pool node? Read them, don't guess.

    python nodefields.py            # classify every hot column of every live list-0x0B node

READ-ONLY.

WHY
---
The volatility histogram found 69 hot columns per 0x280 node, and `poolphase.py` fixed the phase at
0x258 from a live pointer walk. Twelve of those columns land on known fighter-struct fields. The rest
are unnamed, and the biggest unnamed feature is a run at 8-BYTE spacing from +0x1A0 to +0x228.

Eight-byte spacing in a 64-bit recompile is the signature of POINTERS — and it explains a detail the
histogram alone could not: `+0x1A0 gfx1` is hot but `+0x1A4 gfx2` is not. If the DC's two adjacent
32-bit pointers became two 64-bit pointers, then +0x1A4 is not a field at all, it is the HIGH half of
+0x1A0, and it stays constant because everything it points at lives in one region.

That is a hypothesis with an obvious test: read the values and see whether they are pointers.

This classifies each hot column by what it actually holds across every live node:
    ptr:blk     dereferences inside blk
    ptr:near    a plausible pointer, outside blk (the arena, the exe image, elsewhere)
    float       finite, sane magnitude, non-integral
    small int   fits in a byte or two
    other
"""
import struct
import sys
from collections import Counter, defaultdict

from savestate import Game, BLK_PTR, BLKSZ
from verify import MODE_OFF

LIST_HEAD, NEXT_OFF, NODE = 0x2EEB0, 0x08, 0x280
NAMES = {0x50: 'px', 0x54: 'py', 0x58: 'vx', 0x5c: 'vy', 0x124: 'screenX', 0x128: 'screenY',
         0x12c: 'depth', 0x130: 'zx', 0x134: 'zy', 0x144: 'sprite_id', 0x154: 'facing',
         0x168: 'anim_ptr', 0x170: 'drawn', 0x188: 'sid', 0x1a0: 'gfx1', 0x1a4: 'gfx2',
         0x1d0: 'anim_state'}


def classify(qw, dw, blk):
    if blk <= qw < blk + BLKSZ:
        return 'ptr:blk'
    if 0x10000 < qw < 0x7FFFFFFFFFFF and (qw & 3) == 0:
        return 'ptr:near'
    if dw == 0:
        return 'zero'
    f = struct.unpack('<f', struct.pack('<I', dw))[0]
    if f == f and abs(f) not in (float('inf'),) and 1e-6 < abs(f) < 1e9 and f != int(f):
        return 'float'
    if dw < 0x10000:
        return 'small int'
    return 'other'


def main():
    g = Game()
    blk = g.u64(BLK_PTR)
    if g.read(blk + MODE_OFF, 5)[2] != 2:
        print("⚠ NOT IN A MATCH — the pool is empty and this will find nothing.")

    head, seen, nodes = g.u64(blk + LIST_HEAD), set(), []
    cur = head
    while cur and cur not in seen and blk <= cur < blk + BLKSZ and len(nodes) < 512:
        seen.add(cur)
        nodes.append(g.read(cur, NODE))
        cur = g.u64(cur + NEXT_OFF)
    print(f"blk 0x{blk:x}   walked {len(nodes)} live nodes from *(blk+0x{LIST_HEAD:X})\n")
    if not nodes:
        return

    HOT = [0x000,0x004,0x008,0x010,0x018,0x028,0x030,0x034,0x038,0x04C,0x050,0x054,0x06C,0x070,
           0x074,0x094,0x098,0x09C,0x0A0,0x0A8,0x0B0,0x0B8,0x0BC,0x0C0,0x0C8,0x0D0,0x0D8,0x0DC,
           0x0E0,0x0E4,0x0E8,0x0F0,0x120,0x124,0x128,0x12C,0x130,0x134,0x14C,0x154,0x170,0x174,
           0x180,0x184,0x188,0x18C,0x194,0x198,0x1A0,0x1A8,0x1B0,0x1B8,0x1C0,0x1C8,0x1D0,0x1D8,
           0x1E0,0x1E8,0x1F0,0x1F8,0x200,0x208,0x210,0x218,0x220,0x228,0x22C,0x230,0x260]

    print(f"{'off':>6} {'name':<11} {'dominant kind':<10} {'distinct':>9}   sample")
    ptr_run = []
    for off in HOT:
        kinds, vals = Counter(), set()
        for nd in nodes:
            if off + 8 > NODE:
                continue
            dw = struct.unpack_from('<I', nd, off)[0]
            qw = struct.unpack_from('<Q', nd, off)[0]
            kinds[classify(qw, dw, blk)] += 1
            vals.add(dw)
        if not kinds:
            continue
        kind, n = kinds.most_common(1)[0]
        if kind.startswith('ptr'):
            ptr_run.append(off)
        s = struct.unpack_from('<Q', nodes[0], off)[0]
        print(f"  +0x{off:03X} {NAMES.get(off,''):<11} {kind:<10} {len(vals):>9}   "
              f"0x{s:016X}" + ("  <- unanimous" if n == len(nodes) else f"  ({n}/{len(nodes)})"))

    print(f"\ncolumns whose dominant value is a POINTER: {len(ptr_run)}")
    if ptr_run:
        runs, cur_run = [], [ptr_run[0]]
        for a, b in zip(ptr_run, ptr_run[1:]):
            (cur_run.append(b) if b - a == 8 else (runs.append(cur_run), cur_run.clear(),
                                                   cur_run.append(b)))
        runs.append(cur_run)
        for r in runs:
            if len(r) > 2:
                print(f"  ⭐ contiguous 8-byte pointer array: +0x{r[0]:03X} .. +0x{r[-1]:03X} "
                      f"({len(r)} entries)")
        print("\n  ⟹ if a run covers +0x1A0, the DC's adjacent 32-bit gfx1/gfx2 became 64-bit "
              "pointers,\n     and +0x1A4 was never a field — it is the high half of +0x1A0.")
    print("\n⚠ This reads VALUES from one moment. It classifies a layout; it is not a claim about "
          "what any field MEANS.")


if __name__ == "__main__":
    main()
