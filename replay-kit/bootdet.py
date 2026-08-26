#!/usr/bin/env python3
"""bootdet.py snap <name> | diff <a> <b> | pin — is a cold boot reproducible?

THE QUESTION THAT DECIDES THE ARCHITECTURE.

Shipping a snapshot does not work across processes: the Steam build is a native recompile, so
blk[0..0x33B18) is full of ABSOLUTE HOST POINTERS (measured: 730 into blk, 557 into the 256 MiB
arena, 272 into the exe). Relocating them still crashes, because 557 of them point into the
DECOMPRESSED PER-CHARACTER ASSET IMAGE — relocation fixes the address but not the fact that the
bytes there belong to whichever characters that session happened to load.

Flycast Dojo's fallback is the way out (DojoSession.cpp:553-583): when no savestate exists, both
peers boot from power-on, feed blank inputs to a fixed frame, and thereby PROVABLY SHARE A STATE
without transmitting one. State is RE-DERIVED by simulation, not restored.

Applied here: if two cold boots reach character select in the same simulation state, that is our
anchor. The tape then carries INPUTS ONLY (~2 B/frame) — no pointers, no arena, no exe binding,
nothing to relocate, and it replays on any PC that owns the game.

This tool captures blk at a chosen moment and diffs two captures, CLASSIFYING every difference:
  pointer-shaped  -> expected; blk moves each launch, these relocate by a known delta
  real difference -> the anchor is not reproducible; these bytes are what a tape must carry
"""
import ctypes
import hashlib
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from savestate import Game, BLK_PTR, BLKSZ, FC_OFF
from mvcmem import EXE

HERE = os.path.dirname(os.path.abspath(__file__))
RNG_STATE = 0x142E12AB0          # xorshift128, static in the exe, WPM-able BEFORE blk is allocated
PIN = (0x11111111, 0x22222222, 0x33333333, 0x44444444)


def snap(name):
    g = Game()
    blk = g.u64(BLK_PTR)
    arena = g.u64(EXE + 0xAC6D40)
    held = g.freeze()
    try:
        f0 = g.u32(blk + FC_OFF)
        data = g.read(blk, BLKSZ)
        f1 = g.u32(blk + FC_OFF)
    finally:
        g.thaw(held)
    if f0 != f1:
        sys.exit("torn read")
    open(os.path.join(HERE, name + ".blk"), "wb").write(data)
    meta = {"blk": blk, "arena": arena, "frame": f0,
            "mode": list(data[0x3CB8:0x3CBD]),
            "md5": hashlib.md5(data).hexdigest()}
    json.dump(meta, open(os.path.join(HERE, name + ".meta.json"), "w"), indent=1)
    print(f"{name}: blk=0x{blk:x} arena=0x{arena:x} frame={f0} mode={meta['mode']}")
    print(f"   md5 {meta['md5']}")


def diff(a, b):
    ma = json.load(open(os.path.join(HERE, a + ".meta.json")))
    mb = json.load(open(os.path.join(HERE, b + ".meta.json")))
    da = open(os.path.join(HERE, a + ".blk"), "rb").read()
    db = open(os.path.join(HERE, b + ".blk"), "rb").read()
    print(f"A blk=0x{ma['blk']:x} frame={ma['frame']} mode={ma['mode']}")
    print(f"B blk=0x{mb['blk']:x} frame={mb['frame']} mode={mb['mode']}")
    if ma["md5"] == mb["md5"]:
        print("\nIDENTICAL — the anchor is reproducible byte for byte.")
        return

    d_blk = mb["blk"] - ma["blk"]
    d_arena = mb["arena"] - ma["arena"]
    asz = 0x10000000
    ptr_like = real = 0
    real_ranges = []
    run = None
    for off in range(0, min(len(da), len(db)) - 8, 8):
        wa = int.from_bytes(da[off:off + 8], "little")
        wb = int.from_bytes(db[off:off + 8], "little")
        if wa == wb:
            if run:
                real_ranges.append(run); run = None
            continue
        # does this difference look exactly like the same pointer, relocated?
        if (ma["blk"] <= wa < ma["blk"] + BLKSZ and wb - wa == d_blk) or \
           (ma["arena"] <= wa < ma["arena"] + asz and wb - wa == d_arena):
            ptr_like += 1
            if run:
                real_ranges.append(run); run = None
            continue
        real += 1
        if run and off == run[1]:
            run = (run[0], off + 8)
        else:
            if run:
                real_ranges.append(run)
            run = (off, off + 8)
    if run:
        real_ranges.append(run)

    total = len(da) // 8
    print(f"\n{ptr_like} words differ as RELOCATED POINTERS (expected)")
    print(f"{real} words differ for real  ({100.0*real/total:.3f}% of {total} words)")
    if real == 0:
        print("\nANCHOR IS REPRODUCIBLE — every difference is just a relocated pointer.")
        print("=> ship INPUTS ONLY; no snapshot, nothing to relocate.")
        return
    print(f"\n{len(real_ranges)} differing regions; largest:")
    for lo, hi in sorted(real_ranges, key=lambda r: r[1] - r[0], reverse=True)[:12]:
        tag = ""
        if 0x3DB8 <= lo < 0x3DB8 + 6 * 0x738:
            tag = f"  <- fighter slot {(lo - 0x3DB8)//0x738}"
        elif lo == FC_OFF or (lo <= FC_OFF < hi):
            tag = "  <- frame counter (expected)"
        elif 0x2f4d0 <= lo < 0x32530:
            tag = "  <- draw list / slot table"
        print(f"   blk+0x{lo:05x}..0x{hi:05x}  ({hi-lo:5d} B){tag}")


def pin():
    """Force the xorshift draw so blk lands in the same arena slot every launch.
    MUST run BEFORE MvC2's title boot allocates blk (FUN_140607b50)."""
    g = Game()
    before = [g.u32(RNG_STATE + 4 * i) for i in range(4)]
    g.write(RNG_STATE, struct.pack("<IIII", *PIN))
    after = [g.u32(RNG_STATE + 4 * i) for i in range(4)]
    print(f"rng {['%08x' % v for v in before]} -> {['%08x' % v for v in after]}")


if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "snap"
    if c == "snap":
        snap(sys.argv[2])
    elif c == "diff":
        diff(sys.argv[2], sys.argv[3])
    elif c == "pin":
        pin()
