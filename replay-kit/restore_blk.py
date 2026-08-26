#!/usr/bin/env python3
"""restore_blk.py <capture> — restore a .blk snapshot into THIS process, with relocation.

THE QUESTION: is a CHARACTER-SELECT savestate portable across processes?

We only ever tried restoring BATTLE states cross-process, and they crashed. A battle state holds
557 pointers into the decompressed per-character asset image — relocation fixes their addresses but
not the fact that the bytes there belong to whichever characters that session loaded.

At character select no characters are loaded yet, so those pointers should be absent or inert.
If a char-select state restores cleanly, then the replay format is the normal one every emulator
uses — LOAD A STATE, THEN FEED INPUTS — instead of the snapshot-free workaround.

Relocation: blk moves each launch, the 256 MiB arena does not (measured across four launches).
    p in [old_blk, old_blk+0x33B18)  -> += (new_blk - old_blk)
    p in [old_arena, old_arena+256M) -> += (new_arena - old_arena)
Self-check before writing: blk+0x32500+8k must be the six fighter bases, in ANY order (that table
is the live team/tag order, not a fixed permutation).
"""
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from savestate import Game, BLK_PTR, BLKSZ, FC_OFF
from mvcmem import EXE

HERE = os.path.dirname(os.path.abspath(__file__))
ASZ = 0x10000000

name = sys.argv[1]
meta = json.load(open(os.path.join(HERE, name + ".meta.json")))
state = bytearray(open(os.path.join(HERE, name + ".blk"), "rb").read())
if len(state) != BLKSZ:
    sys.exit(f"{name}: {len(state)} B, expected {BLKSZ}")

g = Game()
new_blk = g.u64(BLK_PTR)
new_arena = g.u64(EXE + 0xAC6D40)
old_blk, old_arena = meta["blk"], meta["arena"]
cur_mode = list(g.read(new_blk + 0x3CB8, 5))

print(f"tape mode {meta['mode']}   game mode {cur_mode}")
print(f"blk 0x{old_blk:x} -> 0x{new_blk:x}   arena 0x{old_arena:x} -> 0x{new_arena:x}")
if cur_mode[2] != meta["mode"][2]:
    sys.exit("REFUSING: different screen — get to the screen the capture was taken on")

d_blk, d_arena = new_blk - old_blk, new_arena - old_arena
n_blk = n_arena = 0
for off in range(0, len(state) - 8, 8):
    p = int.from_bytes(state[off:off + 8], "little")
    if old_blk <= p < old_blk + BLKSZ:
        state[off:off + 8] = (p + d_blk).to_bytes(8, "little"); n_blk += 1
    elif old_arena <= p < old_arena + ASZ:
        state[off:off + 8] = (p + d_arena).to_bytes(8, "little"); n_arena += 1
print(f"relocated {n_blk} intra-blk + {n_arena} arena pointers")

seen = set()
for k in range(6):
    p = int.from_bytes(state[0x32500 + 8 * k:0x32508 + 8 * k], "little")
    rel = p - new_blk - 0x3DB8
    if rel < 0 or rel % 0x738 or not (0 <= rel // 0x738 < 6):
        sys.exit(f"SELF-CHECK FAILED: slot entry {k} = 0x{p:x}")
    seen.add(rel // 0x738)
if seen != set(range(6)):
    sys.exit(f"SELF-CHECK FAILED: not a permutation ({sorted(seen)})")
print("self-check PASS")

held = g.freeze()
try:
    g.write(new_blk, bytes(state))
finally:
    g.thaw(held)
time.sleep(0.4)

try:
    fc = g.u32(new_blk + FC_OFF)
    mode = list(g.read(new_blk + 0x3CB8, 5))
    print(f"\nAFTER RESTORE: frame {fc}, mode {mode}")
    time.sleep(0.6)
    fc2 = g.u32(new_blk + FC_OFF)
    print(f"still running: frame {fc2} (+{fc2-fc})")
    print("\nCHARACTER-SELECT STATE IS PORTABLE — a savestate-based tape will work.")
except OSError as e:
    print(f"\nGAME DIED: {e}")
    print("=> char-select state is NOT portable either; stay with the patch approach.")
