#!/usr/bin/env python3
"""poolphase.py — settle the object pool's BASE and NODE PHASE from the live game.

    python poolphase.py

READ-ONLY. Attaches to the running game and reads.

WHY THIS EXISTS
---------------
A volatility histogram proved the dominant region of `blk` is a 0x280-stride array (85% of columns
separate decisively at 0x280 vs ~16% at every other stride — a 5x margin). It CANNOT fix the phase:
a random 69-of-160 hot set hits ~7.8 of 18 known fighter-struct fields by chance, and a full phase
sweep ties four different bases at 12/18. So a field mapping derived from the histogram was retracted.

The phase is not a guess we have to live with. The game exposes a real node pointer:
`mvc-hud-list0b-live-re` records a live list whose HEAD is at `*(blk + 0x2eeb0)`, walked via `+0x08`,
with a category byte at `+0x03`. One dereference gives a genuine node ADDRESS, and
`(node - blk) mod 0x280` is the phase — measured, not inferred.

Cross-checks, because one pointer could be a coincidence:
  * every node on the walk must share the same residue mod 0x280
  * the residues must be consistent with the six fighter structs at blk+0x3DB8 stride 0x738
  * the derived base must sit at or after the end of the fighter slots
"""
import struct
import sys
from collections import Counter

from savestate import Game, BLK_PTR, BLKSZ, FC_OFF
from verify import MODE_OFF, H0, STRIDE

LIST_HEAD = 0x2EEB0        # mvc-hud-list0b-live-re: head pointer of the list-0x0B pool
NEXT_OFF = 0x08            # walk link
CAT_OFF = 0x03             # category byte
NODE = 0x280               # stride, from the periodicity scan


def main():
    g = Game()
    blk = g.u64(BLK_PTR)
    mode = g.read(blk + MODE_OFF, 5)[2]
    print(f"blk 0x{blk:x}  mode {mode} "
          f"({'CHAR SELECT' if mode == 1 else 'IN BATTLE' if mode == 2 else '?'})")
    if mode != 2:
        print("⚠ NOT IN A MATCH — the pool is empty outside a fight and this will find nothing.")

    head = g.u64(blk + LIST_HEAD)
    print(f"list head *(blk+0x{LIST_HEAD:X}) = 0x{head:x}")
    if not head:
        print("  head is NULL. Either the offset is wrong for this build, or nothing is in the list "
              "right now. Try again mid-combo with effects on screen.")
        return

    nodes, seen, cur = [], set(), head
    while cur and cur not in seen and len(nodes) < 512:
        seen.add(cur)
        inside = blk <= cur < blk + BLKSZ
        nodes.append((cur, cur - blk if inside else None, g.read(cur + CAT_OFF, 1)[0] if inside else None))
        if not inside:
            break
        cur = g.u64(cur + NEXT_OFF)

    inblk = [n for n in nodes if n[1] is not None]
    print(f"\nwalked {len(nodes)} nodes, {len(inblk)} of them inside blk")
    if not inblk:
        print("  ⚠ the list does not live inside blk on this build. The pool this histogram found is")
        print("    something else, and the phase question stands. Report this — it is informative.")
        return

    res = Counter(off % NODE for _, off, _ in inblk)
    print(f"\nresidue of (node - blk) mod 0x{NODE:X}:")
    for r, n in res.most_common(6):
        print(f"    0x{r:03X}  x{n}")

    if len(res) == 1:
        phase = next(iter(res))
        lowest = min(off for _, off, _ in inblk)
        base = lowest - ((lowest - phase) // NODE) * NODE
        fighters_end = H0 + 6 * STRIDE
        print(f"\n⭐ SETTLED: every node shares residue 0x{phase:03X}.")
        print(f"   lowest node at blk+0x{lowest:X}; the array's base is blk+0x{phase:X} + k*0x{NODE:X}")
        print(f"   first node at or after the fighter slots (which end at blk+0x{fighters_end:X}): "
              f"blk+0x{phase + ((fighters_end - phase + NODE - 1)//NODE)*NODE:X}")
        print(f"\n   ⟹ a node offset +0xNNN in the histogram is really node offset "
              f"+0x{{(0xNNN - 0x{phase:03X}) mod 0x{NODE:X}}}")
        print(f"   ⚠ the previously-guessed bases were 0x6908 (residue 0x{0x6908 % NODE:03X}) and "
              f"0x6DD8 (residue 0x{0x6DD8 % NODE:03X})")
    else:
        print("\n⚠ NOT SETTLED: the nodes do NOT share one residue, so this list is not an array of")
        print("  0x280-stride cells — or it interleaves two pools. Do not force a phase onto it.")

    cats = Counter(c for _, _, c in inblk if c is not None)
    print(f"\ncategory byte at +0x{CAT_OFF:02X}: {dict(cats.most_common(8))}")
    print("\n⚠ This settles a LAYOUT, not a mechanism. It says nothing about whether Steam's command")
    print("  list is a function of blk.")


if __name__ == "__main__":
    main()
