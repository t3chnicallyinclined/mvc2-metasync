#!/usr/bin/env python3
"""ptrcensus.py <state.rr4 | name.blk> [...] — classify EVERY pointer-shaped word in a blk snapshot.

WHY THIS EXISTS. The relocation in `restore_blk.py` / `rrtape4.py` sorts words into exactly two
buckets and silently ignores everything else:

    p in [blk, blk+0x33B18)          -> += d_blk
    p in [arena, arena+256MiB)       -> += d_arena
    <anything else>                  -> LEFT ALONE, no count, no warning

The published census ("~804 intra-blk, ~243-557 arena, ~272 exe") never reported the RESIDUAL:
pointer-shaped words that are in NONE of those regions. Those are the ones that would be a wild
address in another process. Until that number is known, "the battle state crashed because of stale
asset CONTENTS" is a hypothesis with no measurement behind it — a dangling ADDRESS is a strictly
more parsimonious explanation for an access violation than valid-address-wrong-bytes.

This tool is READ-ONLY and OFFLINE. It touches no running process.

Arena carve map, CONFIRMED from FUN_140607b50 / FUN_140608690 in the runtime dump:
    arena+0x00000000  region 0            (dir[0])
    arena+0x08000000  allocator directory, memset 0, 0x1F8600 B   (DAT_142ef0ab0; dir[2] = blk)
    arena+0x08200000  dir[3]
    arena+0x08400000  ASSET IMAGE, memset 0xCD, 0x2000000 B (32 MiB)   <- the hypothesis' suspect
    arena+0x0A400000  G+0x208
    arena+((rng&0x3F)+0xC0)*0x100000 = blk   (192..255 MiB in)
    blk+0x33B18       blk2, 0x33B20 B, registered at G+0x1c0/0x1c8, NOT rollback-saved
"""
import json
import os
import struct
import sys
import zlib

BLKSZ = 0x33B18
ASZ = 0x10000000
EXE = 0x140000000
EXE_END = 0x1440E8000            # from the runtime dump: 0x140000000..0x1440E7FFF

ASSET_OFF, ASSET_SZ = 0x8400000, 0x2000000
DIR_OFF, DIR_SZ = 0x8000000, 0x1F8600


def load_any(path):
    """-> (blk_base, arena_base, state_bytes, label)"""
    if path.endswith(".rr4") or path.endswith(".rrtape"):
        d = open(path, "rb").read()
        o = 8
        hl, = struct.unpack_from("<I", d, o); o += 4
        hdr = json.loads(d[o:o + hl]); o += hl
        sl, = struct.unpack_from("<I", d, o); o += 4
        state = zlib.decompress(d[o:o + sl])
        return hdr["blk"], hdr["arena"], state, f"{os.path.basename(path)} mode={hdr.get('mode')}"
    base = path[:-4] if path.endswith(".blk") else path
    meta = json.load(open(base + ".meta.json"))
    state = open(base + ".blk", "rb").read()
    return meta["blk"], meta["arena"], state, f"{os.path.basename(base)} mode={meta.get('mode')}"


# Per-slot windows in the asset image, in DC/NAOMI addresses. CONFIRMED by reading the static
# tables FUN_14060d100 indexes (DAT_140a6d708/728/748/768/788/7a8/7c8/7e8/808/828/848) out of the
# runtime dump. steam_addr = arena + 0x8400000 + (dc_addr - 0xC000000)  <=> the asset image IS
# NAOMI main RAM 0x0C000000..0x0DFFFFFF.
SLOT_MAIN = [0xC420000, 0xC810000, 0xC570000, 0xC960000, 0xC6C0000, 0xCAB0000, 0xCC00000]
SLOT_AUX0 = [0xC550000, 0xC940000, 0xC6A0000, 0xCA90000, 0xC7F0000, 0xCBE0000, 0xCD30000]
# slot 6 is NOT a fighter: FUN_14060c370 case 5 loads a FIXED entry (0x95) into 0xCC00000, so its
# contents are identical in every process at the same phase. That is why a character-select state
# -- whose only asset pointers land in slot 6 and the common 0xD?????? banks -- is portable.


def dc_window(dc):
    for i in range(7):
        if SLOT_MAIN[i] <= dc < SLOT_MAIN[i] + 0x130000:
            return f"slot{i}.main"
        if SLOT_AUX0[i] <= dc < SLOT_AUX0[i] + 0x20000:
            return f"slot{i}.aux"
    if dc >= 0xD000000:
        return "common/stage bank (boot- or phase-loaded, fixed entry ids)"
    return "asset:unmapped-window"


def classify(p, blk, arena):
    if p == 0:
        return None
    # canonical user-mode range, and reject obvious small ints / floats-as-u64
    if p < 0x10000 or p >= 0x7FFFFFFFFFFF:
        return None
    if blk <= p < blk + BLKSZ:
        return "blk"
    if blk + BLKSZ <= p < blk + BLKSZ + 0x33B20:
        return "blk2 !!"                       # arena-classified today -> moved by d_arena, WRONG
    if arena <= p < arena + ASZ:
        r = p - arena
        if ASSET_OFF <= r < ASSET_OFF + ASSET_SZ:
            return "arena:ASSET " + dc_window(r - ASSET_OFF + 0xC000000)
        if DIR_OFF <= r < DIR_OFF + DIR_SZ:
            return "arena:dir"
        if r >= 0xC0 * 0x100000:
            return "arena:blkslots"            # the 192..255MiB window blk is drawn from
        return "arena:other"
    if EXE <= p < EXE_END:
        return "exe"
    return "UNCLASSIFIED !!"                   # <- left unrelocated by the shipping code


def census(path):
    blk, arena, state, label = load_any(path)
    print(f"\n=== {label}")
    print(f"    blk 0x{blk:x}  arena 0x{arena:x}  blk-arena 0x{blk-arena:x} "
          f"({(blk-arena)>>20} MiB)  len {len(state)}")
    if len(state) != BLKSZ:
        print(f"    !! expected {BLKSZ} bytes")
    buckets, examples = {}, {}
    for off in range(0, len(state) - 7, 8):
        p = int.from_bytes(state[off:off + 8], "little")
        k = classify(p, blk, arena)
        if k is None:
            continue
        buckets[k] = buckets.get(k, 0) + 1
        examples.setdefault(k, []).append((off, p))
    tot = len(state) // 8
    for k in sorted(buckets, key=lambda k: -buckets[k]):
        if k == "UNCLASSIFIED !!":
            continue
        print(f"    {buckets[k]:6d}  {k}")
        vals = {}
        for off, p in examples[k]:
            vals[p] = vals.get(p, 0) + 1
        print(f"              {len(vals)} distinct targets; "
              f"top {[('0x%x' % v, n) for v, n in sorted(vals.items(), key=lambda x: -x[1])[:4]]}")
        for off, p in examples[k][:4]:
            print(f"              blk+0x{off:05x} -> 0x{p:012x}")
    # the UNCLASSIFIED bucket is mostly float pairs (0x3f800000 = 1.0f) and small counters.
    # Histogram by the high 24 bits so a REAL foreign pointer (heap ~0x1xx.., DLL ~0x7ffx..)
    # cannot hide inside the noise.
    unk = examples.get("UNCLASSIFIED !!", [])
    hi = {}
    for off, p in unk:
        hi[p >> 32] = hi.get(p >> 32, 0) + 1
    print(f"    {len(unk):6d}  UNCLASSIFIED, by high 32 bits:")
    for h, n in sorted(hi.items(), key=lambda x: -x[1]):
        ex = next(p for o, p in unk if p >> 32 == h)
        note = ""
        if h == 0:
            note = "  (< 4 GiB: float pairs / counters, NOT Win64 pointers)"
        elif 0x10 <= h <= 0x7FFF:
            note = "  <<< PLAUSIBLE FOREIGN POINTER (heap/DLL) — the relocator ignores these"
        print(f"              hi=0x{h:x}  n={n:5d}  e.g. 0x{ex:012x}{note}")
    print(f"    ({tot} 8-aligned words total)")
    foreign = sum(n for h, n in hi.items() if 0x10 <= h <= 0x7FFF) + buckets.get("blk2 !!", 0)
    print(f"    >>> FOREIGN/UNRELOCATED pointer-shaped words: {foreign}")
    return buckets


def live():
    """Census the RUNNING game. Read-only. Run it IN A BATTLE — that is the state nobody has
    measured. Also dumps the per-fighter pointer fields FUN_14060d100 installs, and the two
    fields the two logged crashes actually faulted on."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from mvcmem import Mem, EXE as E
    m = Mem()
    blk = m.u64(E + 0xAC6EF0)
    arena = m.u64(E + 0xAC6D40)
    state = m.read(blk, BLKSZ)
    mode = list(state[0x3CB8:0x3CBD])
    print(f"pid {m.pid} blk 0x{blk:x} arena 0x{arena:x} mode {mode} "
          f"({'CHAR SELECT' if mode[2] == 1 else 'IN BATTLE' if mode[2] == 2 else '?'})")
    tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_live.blk")
    open(tmp, "wb").write(state)
    json.dump({"blk": blk, "arena": arena, "mode": mode},
              open(tmp[:-4] + ".meta.json", "w"))
    census(tmp)
    print("\n  per-fighter pointer fields (the ones FUN_14060d100 installs):")
    H0, ST = 0x3DB8, 0x738
    fields = (0x1a8, 0x1b0, 0x1b8, 0x1c0, 0x1c8, 0x1d0, 0x1d8, 0x1e0, 0x1e8, 0x1f0,
              0x200, 0x208, 0x210, 0x218, 0x220, 0x2c0, 0x558, 0x560, 0x6b8)
    for i in range(6):
        H = H0 + i * ST
        print(f"   slot{i} cid={state[H+0x6c0]:3d} pal={state[H+0x6c1]:3d} "
              f"drawn={state[H+0x170]} loaded={state[H+0x171]} "
              f"sid=0x{struct.unpack_from('<H', state, H+0x188)[0]:04x}")
        for o in fields:
            p = struct.unpack_from("<Q", state, H + o)[0]
            k = classify(p, blk, arena) or ("NULL" if p == 0 else f"raw 0x{p:x}")
            note = ""
            if o == 0x1b0:
                note = "   <-- crash #2 faulted walking this table (FUN_140612430+0x88)"
            if o == 0x2c0:
                note = "   <-- crash #1 faulted dereferencing this (FUN_14063e4a0+0x0F)"
            print(f"        H+0x{o:03x} = {k}{note}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "live":
        live()
        sys.exit(0)
    args = sys.argv[1:]
    if not args:
        here = os.path.dirname(os.path.abspath(__file__))
        args = [os.path.join(here, f) for f in sorted(os.listdir(here))
                if f.endswith(".rr4") or f.endswith(".blk")]
    for a in args:
        try:
            census(a)
        except Exception as e:
            print(f"\n=== {a}: {type(e).__name__}: {e}")
