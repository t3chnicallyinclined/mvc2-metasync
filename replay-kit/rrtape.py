#!/usr/bin/env python3
"""rrtape.py pack <name> <out.rrtape> | play <file.rrtape> | info <file.rrtape>

ONE FILE that opens MvC2 at a saved moment and replays a match.

FORMAT  (all little-endian)
    magic   b"RRTAPE01"
    u32     header length
    bytes   header, JSON: {ver, build, exe_base, blk, arena, start_frame, frames,
                           teams, seat_map, ts, note}
    u32     compressed snapshot length
    bytes   zlib(blk[0..0x33B18))          the complete deterministic state
    u32     compressed input length
    bytes   zlib(per frame: u32 frame, u32 seat0, u32 seat1)

WHY THIS IS THE WHOLE MATCH: MvC2 registers exactly one rollback region with GGPO —
blk[0..0x33B18) — so that region IS the complete deterministic simulation state. Restore it and
feed the recorded inputs and the match reproduces. Verified: two replays from one tape produced
bit-identical end states (frame, hp, position to 3dp, sprite id).

A 10-second capture is ~15 KB. A five-minute match is well under 100 KB.
"""
import ctypes
import json
import os
import struct
import sys
import time
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from savestate import Game, BLK_PTR, BLKSZ, FC_OFF
from inputrec import IN0, SEATMAP, STORES, patch, sanity
from mvcmem import EXE

MAGIC = b"RRTAPE01"
HERE = os.path.dirname(os.path.abspath(__file__))


def pack(name, out):
    state = open(os.path.join(HERE, name + ".state"), "rb").read()
    inp = open(os.path.join(HERE, name + ".inp"), "rb").read()
    if len(state) != BLKSZ:
        sys.exit(f"state is {len(state)} B, expected {BLKSZ}")
    rows = len(inp) // 12
    start = int.from_bytes(state[FC_OFF:FC_OFF + 4], "little")

    # character ids come out of the snapshot itself — no separate metadata needed
    teams = []
    for i in range(6):
        H = 0x3DB8 + i * 0x738
        teams.append(state[H + 0x6C0])

    # Record WHERE this state lived. The blob is full of absolute pointers (FUN_140628020 writes
    # six self-pointers at blk+0x32500), and both `blk` and the 256 MiB arena move every launch.
    # Without these three addresses a tape cannot be relocated into another process — restoring it
    # raw crashes the game the moment it dereferences a stale pointer. (Observed: blk 0x16be1000 ->
    # 0x16de1000 on relaunch, ERROR_PARTIAL_COPY, process gone.)
    g = Game()
    hdr = json.dumps({
        "ver": 2, "start_frame": start, "frames": rows, "teams": teams,
        "blk": g.u64(BLK_PTR), "arena": g.u64(EXE + 0xAC6D40), "exe": EXE,
        "arena_size": 0x10000000,
        "ts": int(time.time()), "note": "MvC2 GGPO deterministic-state tape",
    }).encode()
    cs, ci = zlib.compress(state, 9), zlib.compress(inp, 9)
    with open(out, "wb") as f:
        f.write(MAGIC)
        f.write(struct.pack("<I", len(hdr))); f.write(hdr)
        f.write(struct.pack("<I", len(cs)));  f.write(cs)
        f.write(struct.pack("<I", len(ci)));  f.write(ci)
    n = os.path.getsize(out)
    print(f"packed {out}  {n:,} B  ({rows} frames, {rows/60.0:.1f}s)")
    print(f"   state {len(state):,} -> {len(cs):,}   inputs {len(inp):,} -> {len(ci):,}")


def load(path):
    d = open(path, "rb").read()
    if d[:8] != MAGIC:
        sys.exit("not an rrtape")
    o = 8
    hl, = struct.unpack_from("<I", d, o); o += 4
    hdr = json.loads(d[o:o + hl]); o += hl
    sl, = struct.unpack_from("<I", d, o); o += 4
    state = zlib.decompress(d[o:o + sl]); o += sl
    il, = struct.unpack_from("<I", d, o); o += 4
    inp = zlib.decompress(d[o:o + il])
    return hdr, state, inp


def info(path):
    hdr, state, inp = load(path)
    print(json.dumps(hdr, indent=2))
    print(f"state {len(state):,} B, inputs {len(inp)//12} frames, file {os.path.getsize(path):,} B")


def relocate(state, hdr, new_blk, new_arena):
    """Rewrite the blob's absolute pointers for THIS process, or refuse.

    Both `blk` and the 256 MiB arena move every launch, and the blob stores absolute 64-bit
    pointers into both. Two deltas are needed because the RNG that picks blk's slot inside the
    arena can differ between runs:
        p inside the old blk     -> p += (new_blk   - old_blk)
        p elsewhere in the arena -> p += (new_arena - old_arena)   (e.g. the 32 MiB asset image)
    Only 8-ALIGNED words are considered, which is what the compiler emits for pointers.

    SELF-CHECK (free, and catches a bad rewrite instantly): blk+0x32500+8k must hold the six
    fighter bases blk+0x3DB8+n*0x738 — the ORDER is the live team/tag order and changes during a
    match, so we require a PERMUTATION of n=0..5, not a fixed sequence.
    """
    if hdr.get("ver", 1) < 2 or "blk" not in hdr:
        sys.exit("REFUSING: this tape predates address recording and cannot be relocated.\n"
                 "  Restoring it into another process crashes the game. Re-record with ver 2.")
    old_blk, old_arena = hdr["blk"], hdr["arena"]
    asz = hdr.get("arena_size", 0x10000000)
    d_blk, d_arena = new_blk - old_blk, new_arena - old_arena
    # FUN_140607b50 carves a SECOND block immediately after ours: blk+0x33B18, size 0x33B20.
    # It moves with blk, but it is outside the snapshot — so pointers into it were falling through
    # to the arena bucket and getting delta 0, i.e. left dangling at the old address. That is
    # consistent with the observed failure: the sim ran (a hit was audible) then died.
    BLK_SPAN = BLKSZ + 0x33B20
    if d_blk == 0 and d_arena == 0:
        print("same process layout — no relocation needed")
        return state

    print(f"relocating: blk 0x{old_blk:x} -> 0x{new_blk:x} (delta {d_blk:+#x}), "
          f"arena delta {d_arena:+#x}")
    buf = bytearray(state)
    n_blk = n_second = n_arena = 0
    for off in range(0, len(buf) - 8, 8):
        p = int.from_bytes(buf[off:off + 8], "little")
        if old_blk <= p < old_blk + BLKSZ:
            buf[off:off + 8] = (p + d_blk).to_bytes(8, "little"); n_blk += 1
        elif old_blk + BLKSZ <= p < old_blk + BLK_SPAN:      # the sibling block, moves with blk
            buf[off:off + 8] = (p + d_blk).to_bytes(8, "little"); n_second += 1
        elif old_arena <= p < old_arena + asz:
            buf[off:off + 8] = (p + d_arena).to_bytes(8, "little"); n_arena += 1
    print(f"  rewrote {n_blk} intra-blk + {n_second} sibling-block + {n_arena} arena pointers")

    seen = set()
    for k in range(6):
        p = int.from_bytes(buf[0x32500 + 8 * k:0x32508 + 8 * k], "little")
        rel = p - new_blk - 0x3DB8
        if rel < 0 or rel % 0x738 or not (0 <= rel // 0x738 < 6):
            sys.exit(f"SELF-CHECK FAILED: slot table entry {k} = 0x{p:x} is not a fighter base")
        seen.add(rel // 0x738)
    if seen != set(range(6)):
        sys.exit(f"SELF-CHECK FAILED: slot table is not a permutation of 0..5 ({sorted(seen)})")
    print("  self-check PASS: slot table is a valid permutation of the six fighter bases")
    return bytes(buf)


def play(path, speed=1):
    hdr, state, inp = load(path)
    rows = [struct.unpack_from("<III", inp, i) for i in range(0, len(inp), 12)]
    print(f"tape: {hdr['frames']} frames ({hdr['frames']/60.0:.1f}s) from frame {hdr['start_frame']}")

    g = Game()
    sanity(g)
    blk = g.u64(BLK_PTR)
    arena = g.u64(EXE + 0xAC6D40)

    state = relocate(state, hdr, blk, arena)

    held = g.freeze()
    try:
        g.write(blk, state)
    finally:
        g.thaw(held)
    time.sleep(0.05)
    print(f"restored to frame {g.u32(blk + FC_OFF)}")

    patch(g, True)
    try:
        last, fed, miss = None, 0, 0
        for fc, s0, s1 in rows:
            deadline = time.perf_counter() + 0.05
            while True:
                cur = g.u32(blk + FC_OFF)
                if cur != last:
                    break
                if time.perf_counter() > deadline:
                    miss += 1
                    break
            last = cur
            g.write(IN0, struct.pack("<II", s0, s1))
            fed += 1
        end = g.u32(blk + FC_OFF)
        print(f"played {fed} frames ({miss} misses) -> frame {end}")
        for i in range(6):
            H = blk + 0x3DB8 + i * 0x738
            if g.read(H + 0x170, 1)[0]:
                hp = struct.unpack("<I", g.read(H + 0x578, 4))[0] & 0xFFFF
                x, y = struct.unpack("<ff", g.read(H + 0x50, 8))
                print(f"   slot{i} cid={g.read(H+0x6C0,1)[0]:3d} hp={hp:3d} pos=({x:.1f},{y:.1f})")
    finally:
        patch(g, False)


if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "info"
    if c == "pack":
        pack(sys.argv[2], sys.argv[3])
    elif c == "play":
        play(sys.argv[2])
    else:
        info(sys.argv[2])
