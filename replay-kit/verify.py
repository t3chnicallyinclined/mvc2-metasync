#!/usr/bin/env python3
"""verify.py watch | rng [frames] [--exe] [--arena] | pool [secs] | cam | blk2 | reg | all

THE FALSIFICATION HARNESS. Read-only. Every command here exists to try to DISPROVE something we
have claimed, not to confirm it.

The claim under attack:
    "MvC2 ships GGPO rollback, it registers exactly one region blk[0..0x33B18), therefore that
     region is the complete deterministic simulation state, therefore anchor + inputs reproduces
     any match exactly."

The load-bearing step is the second "therefore", and it does not follow. Rollback proves the region
holds everything that CHANGES during a match — state that is set once and only READ during the
match never needs restoring, so rollback works fine without it. Rollback-sufficiency is not
replay-sufficiency. These commands go looking for exactly that gap.

The sharpest lead comes from the DC/NAOMI side of the same game code:

    DC MvC2's RNG is an LCG at 0x8C16BC2C:   s = s*0x41C64E6D + 0x3039 ;  return (s >> 16) & 0x7FFF
    with srand(1) at 0x8C11E770, and FIFTY-FOUR call sites across the character-program and
    effect banks. On DC it sits in the static data image about 1 MB BELOW the game-global block —
    i.e. nowhere near the region that became Steam's blk.

If the x86-64 recompile left that word where the SH4 build had it, it is a static that rollback
never restores and an anchor never carries, and the whole claim is false. `rng` settles it, because
an LCG is the one kind of state you can identify with certainty from two samples: only the real
generator satisfies  x1 == x0*A^k + B_k  for some plausible k.

(Why the existing evidence does not settle it: the two "bit-identical" replays ran back to back in
one process, so an out-of-blk RNG would only show up if the number of draws before each replay
differed. Damage calculation consumes zero RNG, so a short tape passes that test either way.)
"""
import struct
import sys
import time

try:
    import msvcrt
except ImportError:
    msvcrt = None

import numpy as np

from savestate import Game, BLK_PTR, BLKSZ, FC_OFF
from mvcmem import EXE, Mem

A, C, M32 = 0x41C64E6D, 0x3039, 0xFFFFFFFF        # the DC LCG, confirmed in bank11 loc_8c11e730
G = EXE + 0xAC6D40
ARENA_PTR, ASZ = G + 0x00, 0x10000000
BLK2_PTR, BLK2_SZ = G + 0x1C0, G + 0x1C8
G_SEL = G + 0x48
REG_COUNT, REG_BASE, REG_SIZE = 0x142D10950, 0x142D107D0, 0x142D108D0
SHELL_RNG = 0x142E12AB0                            # the shell xorshift128 (a DIFFERENT generator)

H0, STRIDE, MODE_OFF = 0x3DB8, 0x738, 0x3CB8
DRAW_LIST, DRAW_COUNTS = 0x2F4D0, 0x324D0
SLOT_PTRS = 0x32500


def wait_frames(g, blk, n):
    """Block until the sim frame counter has advanced n frames."""
    f0 = g.u32(blk + FC_OFF)
    while True:
        f = g.u32(blk + FC_OFF)
        if f is not None and f - f0 >= n:
            return f - f0


def lcg_scan(s0, s1, kmax, label, base_addr):
    """Every 4-aligned word that could be the LCG, and how many draws it took.

    Iterating each candidate forward would be O(words x kmax). Instead step the CLOSED FORM once
    per k — x_k = x0*A^k + B_k — and test every candidate against it at once. Words that did not
    change are dropped first: a generator nobody drew from is invisible either way, and saying so
    is the honest result.
    """
    a0 = np.frombuffer(s0, dtype="<u4")
    a1 = np.frombuffer(s1, dtype="<u4")
    n = min(len(a0), len(a1))
    a0, a1 = a0[:n], a1[:n]
    moved = np.nonzero(a0 != a1)[0]
    print(f"  {label}: {n:,} words, {len(moved):,} changed")
    if len(moved) == 0:
        return []
    x0 = a0[moved].astype(np.uint64)
    x1 = a1[moved].astype(np.uint64)
    hits, Ak, Bk = [], 1, 0
    for k in range(1, kmax + 1):
        Ak = (Ak * A) & M32
        Bk = (Bk * A + C) & M32
        eq = np.nonzero(((x0 * np.uint64(Ak) + np.uint64(Bk)) & np.uint64(M32)) == x1)[0]
        for i in eq:
            off = int(moved[i]) * 4
            hits.append((off, k))
            print(f"    ⭐ LCG MATCH at {label}+0x{off:x} (abs 0x{base_addr + off:x}) after {k} draws")
        if len(hits) > 8:
            break
    if not hits:
        print(f"    no LCG-successor relationship anywhere in {label} (kmax={kmax})")
    return hits


def cmd_rng(argv):
    frames = int(argv[0]) if argv and argv[0].isdigit() else 600
    g = Game()
    blk = g.u64(BLK_PTR)
    mode = g.read(blk + MODE_OFF, 5)[2]
    print(f"blk 0x{blk:x}  mode byte {mode} "
          f"({'CHAR SELECT' if mode == 1 else 'IN BATTLE' if mode == 2 else '?'})")
    if mode != 2:
        print("⚠ NOT IN A MATCH. Run this DURING a fight, ideally an RNG-heavy one — the DC "
              "call sites are concentrated in the character-program and effect banks (Storm, "
              "Blackheart, Sentinel; supers and projectiles on screen). A generator nobody draws "
              "from cannot be found, and its absence would prove nothing.")

    regions = [("blk", blk, BLKSZ)]
    if "--exe" in argv:
        # the exe's own image — where DC kept this word (a static in the data image)
        hdr = g.read(EXE, 0x400)
        e = struct.unpack_from("<I", hdr, 0x3C)[0]
        size_of_image = struct.unpack_from("<I", hdr, e + 24 + 56)[0]
        regions.append(("exe", EXE, size_of_image))
    if "--arena" in argv:
        regions.append(("arena", g.u64(ARENA_PTR), ASZ))

    snaps = []
    for name, base, size in regions:
        b = readable(g, base, size)
        print(f"snapshot A: {name} 0x{base:x} +0x{size:x} -> {len(b):,} B")
        snaps.append((name, base, b))
    adv = wait_frames(g, blk, frames)
    print(f"advanced {adv} sim frames")
    out = []
    for (name, base, b0) in snaps:
        b1 = readable(g, base, len(b0))
        # kmax: a generous ceiling on draws per frame. DC's consumers are per-effect, so tens per
        # frame is normal and hundreds is possible with several supers on screen.
        out += lcg_scan(b0, b1, min(frames * 64, 40000), name, base)
    print()
    if any(n == "blk" for n, _, _ in snaps) and not out:
        print("RESULT: no LCG with the DC constants found in blk.")
        print("  WHAT THAT PROVES: the DC generator, verbatim, is not sitting in the sim region.")
        print("  WHAT IT DOES NOT PROVE: that the sim has no RNG outside blk. It could be there")
        print("    (run again with --exe, then --arena), or the recompile could have swapped the")
        print("    generator entirely, which this scan cannot see because it is keyed to A/C.")
        print("  THE TEST THAT DOES NOT CARE WHICH GENERATOR IT IS: `rrtape4.py ab <tape.rr4>` —")
        print("    replay a tape twice from the same anchor with RNG-heavy play in between. Same")
        print("    end state both times => nothing outside blk survives to affect a match.")
    elif out:
        print("RESULT: the generator is located. If it is inside blk the claim survives this "
              "attack and the offset doubles as a tape-integrity checksum. If it is outside, the "
              "tape must carry it.")
    # the shell generator is a different algorithm (xorshift128) and is NOT this LCG; report it
    # only so nobody confuses the two.
    print(f"\nshell xorshift128 @0x{SHELL_RNG:x} = "
          f"{struct.unpack('<4I', g.read(SHELL_RNG, 16))}  (a DIFFERENT generator — this is the "
          f"one we write to pin the allocation, not the sim's)")


def readable(g, base, size):
    """Read a span, tolerating unreadable pages by zero-filling them (they cannot hold state)."""
    out = bytearray()
    step = 0x100000
    a = base
    while a < base + size:
        n = min(step, base + size - a)
        try:
            b = g.read(a, n)          # raises on an unreadable page; those hold no state anyway
        except Exception:
            b = None
        out += b if b else bytes(n)
        a += n
    return bytes(out)


def cmd_pool(argv):
    """Find the satellite object pool WITHOUT scanning — the draw list already points at it.

    Every projectile, cape, hit spark, super flash and assist projectile is a node from one pool.
    On DC: base 0x8C26AA54, stride 0x1D0, 256 nodes, and the node's renderable fields are laid out
    as a PREFIX of the fighter struct — same offsets for world pos, screen pos, scale, facing, the
    draw gate and sprite id. So whatever reads a fighter already reads a pool node.

    The draw list holds live handles. Six of them are the fighters (we have those exactly, from
    blk+0x32500). Everything else is a pool node, so the base and stride fall out of the handles
    themselves with no search at all.
    """
    secs = float(argv[0]) if argv else 6.0
    g = Game()
    blk = g.u64(BLK_PTR)
    fighters = {blk + H0 + i * STRIDE for i in range(6)}
    seen, layers = {}, {}
    t0 = time.time()
    while time.time() - t0 < secs:
        counts = g.read(blk + DRAW_COUNTS, 16)
        dl = g.read(blk + DRAW_LIST, 16 * 0x300)
        if not counts or not dl:
            continue
        for L in range(16):
            for i in range(min(counts[L], 96)):
                h = struct.unpack_from("<Q", dl, L * 0x300 + i * 8)[0]
                if h and h not in fighters:
                    seen[h] = seen.get(h, 0) + 1
                    layers.setdefault(h, set()).add(L)
    print(f"watched {secs:.0f}s of draw lists: {len(seen)} distinct non-fighter handles")
    if not seen:
        print("none seen — run this DURING a fight with projectiles/assists on screen.")
        return
    offs = sorted((h - blk) for h in seen)
    print(f"blk-relative range 0x{offs[0]:x} .. 0x{offs[-1]:x}")
    diffs = sorted({b - a for a, b in zip(offs, offs[1:]) if b != a})
    print(f"handle offsets: {[hex(o) for o in offs[:24]]}{' ...' if len(offs) > 24 else ''}")
    print(f"gaps between them: {[hex(d) for d in diffs[:16]]}")
    if diffs:
        from math import gcd
        stride = 0
        for d in diffs:
            stride = gcd(stride, d)
        print(f"GCD of gaps = 0x{stride:x} ({stride}) — the node stride divides this "
              f"(DC stride was 0x1d0/464; the prediction for Steam is 0x280/640)")
        if stride:
            k0 = offs[0] // stride
            print(f"implied pool base ≈ blk+0x{offs[0] - 0:x} (first live node); "
                  f"predicted base was blk+0x6e34")
    # dump one node through the FIGHTER field layout — if the prefix theory holds, these read sane
    h = max(seen, key=lambda k: seen[k])
    b = g.read(h, 0x200)
    if b:
        x, y = struct.unpack_from("<ff", b, 0x50)
        sx, sy = struct.unpack_from("<ff", b, 0x124)
        print(f"\nbusiest node 0x{h:x} (blk+0x{h - blk:x}, seen {seen[h]}x, layers "
              f"{sorted(layers[h])}) read AS A FIGHTER:")
        print(f"   world=({x:.1f},{y:.1f}) screen=({sx:.1f},{sy:.1f}) "
              f"sid={struct.unpack_from('<H', b, 0x188)[0] & 0x7FFF} "
              f"drawn={b[0x170]} facing={b[0x154]} anim={b[0x186]}")
        print("   ^ if those look like a real on-screen object, the fighter reader works verbatim "
              "on pool nodes and assists/projectiles/effects come free.")


def cmd_cam(argv):
    """Settle the camera label and the 0x10 alignment overlap with one dump.

    We call blk+0x6918 "eyeY". On DC the field at that alignment is the camera EYE DISTANCE / zoom
    divisor with a nominal value of 812.35 (loc_8c03093c divides the draw scale by cam/812.35) —
    not a Y coordinate. And the DC->Steam block alignment leaves a 0x10 discrepancy right here:
    the fighter array ends at 0x6908 by arithmetic, but the semantic anchors put the stage struct
    at 0x68F8. A float near 812 and the ground line near 433.4 pin it exactly.
    """
    g = Game()
    blk = g.u64(BLK_PTR)
    print(f"blk 0x{blk:x}  frame {g.u32(blk + FC_OFF)}  mode {list(g.read(blk + MODE_OFF, 5))}")
    b = g.read(blk + 0x68C0, 0x140)
    print(f"\nblk+0x68C0 .. +0x6A00 as f32 (fighter-array end / stage struct head):")
    for o in range(0, 0x140, 4):
        v = struct.unpack_from("<f", b, o)[0]
        u = struct.unpack_from("<I", b, o)[0]
        tag = ""
        if 700 < v < 950:
            tag = "  <<< ~812 = DC camera eye-distance / zoom divisor"
        elif 380 < v < 500:
            tag = "  <<< ~433 = the ground line"
        elif abs(v) > 1e-6 and abs(v) < 1e9:
            tag = ""
        print(f"   blk+0x{0x68C0 + o:05x}  {v:14.4f}  0x{u:08x}{tag}")
    print(f"\nfor comparison, what we currently label:")
    for name, off in (("eyeX", 0x6914), ("eyeY", 0x6918), ("ground", 0x6998)):
        print(f"   {name:6s} blk+0x{off:x} = {struct.unpack('<f', g.read(blk + off, 4))[0]:.4f}")

    # ── do these MOVE? ──────────────────────────────────────────────────────────────────────────
    # A value that reads 812.3571 forever is a CONSTANT and not worth carrying in a tape; one that
    # breathes as the fighters spread apart is the live camera and belongs there. Three seconds of
    # sampling separates the two, and nothing static can.
    watch = [("eyeX?", 0x6914), ("eyeY?", 0x6918), ("Z/zoom", 0x691C), ("pair2.y", 0x6924),
             ("pair2.z", 0x6928), ("ground", 0x6998), ("scr_lo", 0x6990), ("scr_hi", 0x6994),
             ("wld_lo", 0x69A0), ("wld_hi", 0x69A4), ("1238?", 0x69A8), ("193?", 0x69B0),
             ("pair3.z", 0x69BC)]
    lo, hi, n = {}, {}, 0
    t0 = time.time()
    while time.time() - t0 < 3.0:
        b = g.read(blk + 0x6914, 0x120)
        if not b:
            continue
        n += 1
        for k, off in watch:
            v = struct.unpack_from("<f", b, off - 0x6914)[0]
            lo[k] = v if k not in lo else min(lo[k], v)
            hi[k] = v if k not in hi else max(hi[k], v)
    print(f"\nsampled {n}x over 3s — which of these are LIVE and which are constants:")
    for k, off in watch:
        print(f"   {k:8s} blk+0x{off:x}  {lo[k]:12.4f} .. {hi[k]:12.4f}   "
              f"{'MOVES' if lo[k] != hi[k] else 'constant'}")
    print("   >>> whatever MOVES with the fighters is the live camera; constants are stage setup.")


def cmd_blk2(argv):
    """The SECOND block: blk+0x33B18, registered at G+0x1c0/0x1c8 but NOT in the rollback list.

    If it mutates during a fight it is derived output (rollback would desync otherwise, and online
    matches complete). If it is written once at match init and only read after, it is exactly the
    'set before, read during' state that rollback certifies nothing about — and an anchor taken at
    character select would not carry whatever the match later needs from it.
    """
    import zlib
    g = Game()
    blk = g.u64(BLK_PTR)
    b2, sz = g.u64(BLK2_PTR), g.u32(BLK2_SZ)
    print(f"blk  0x{blk:x} size 0x{g.u32(G + 0x1B8):x}")
    print(f"blk2 0x{b2:x} size 0x{sz:x}   (blk + 0x{b2 - blk:x})" if b2 else "blk2 pointer is NULL")
    if not b2 or not sz or sz > 0x100000:
        return
    prev, changes, samples = None, 0, 0
    t0 = time.time()
    while time.time() - t0 < 5.0:
        d = g.read(b2, sz)
        if not d:
            continue
        c = zlib.crc32(d)
        if prev is not None and c != prev:
            changes += 1
        prev = c
        samples += 1
        time.sleep(0.05)
    print(f"sampled {samples}x over 5s: {changes} changes")
    if changes:
        print("  MUTATES DURING PLAY -> derived output; rollback would desync if it mattered, so "
              "it is safe to ignore.")
    else:
        print("  STATIC during play.")

    # ── is it a COPY of blk? ────────────────────────────────────────────────────────────────────
    # blk2 is exactly sizeof(blk) + 8. That is the shape of a SAVESTATE SLOT: a small header
    # followed by the region. If its body resembles blk, it is the engine's own save buffer —
    # pure derived output, nothing to carry, and its being static offline is just "no rollback
    # has happened yet" rather than hidden input state.
    a = g.read(blk, BLKSZ)
    b = g.read(b2, sz)
    if not a or not b:
        return
    hdr = struct.unpack_from("<2I", b, 0)
    print(f"\n  blk2 header words: 0x{hdr[0]:08x} 0x{hdr[1]:08x}   "
          f"(0x{BLKSZ:x} would mean 'size', i.e. a savestate slot)")
    nz_b = sum(1 for x in b if x)
    nz_a = sum(1 for x in a if x)
    print(f"  blk  non-zero bytes: {nz_a:,}/{len(a):,} ({100.0 * nz_a / len(a):.1f}%)")
    print(f"  blk2 non-zero bytes: {nz_b:,}/{len(b):,} ({100.0 * nz_b / len(b):.1f}%)")
    if nz_b == 0:
        print("  >>> blk2 IS ENTIRELY ZERO. It holds no state at all, so it cannot be the")
        print("      'written before, read during' hazard — there is nothing in it to read.")
        print("      It is a reserved allocation (its size is exactly sizeof(blk)+8, the shape of")
        print("      a savestate slot), almost certainly the rollback save buffer, which stays")
        print("      empty until a GGPO session actually saves. ⚠ Re-check it DURING AN ONLINE")
        print("      MATCH — that is the only time it would be filled.")
        return
    # A plain byte-match against blk would be meaningless while both are mostly zero, so compare
    # only where blk actually holds something.
    for name, off in (("+0", 0), ("+4", 4), ("+8", 8)):
        n = min(len(a), len(b) - off)
        idx = [i for i in range(0, n, 64) if any(a[i:i + 8])]
        if not idx:
            continue
        same = sum(1 for i in idx if a[i:i + 8] == b[off + i:off + i + 8])
        print(f"  body at {name}: {same}/{len(idx)} of blk's NON-ZERO sampled words match "
              f"({100.0 * same / len(idx):.1f}%)")
    print("  >>> a high match means blk2 is a savestate copy of blk = derived output, safe.")
    print("  >>> non-zero but unlike blk means it is something else, and needs a two-machine diff")
    print("      before a cross-machine re-simulation is trusted.")


def cmd_reg(argv):
    """What GGPO actually registered, and which arm of the fork we are on."""
    g = Game()
    blk = g.u64(BLK_PTR)
    sel = g.u32(G_SEL)
    print(f"G+0x48 = {sel}   ->  {'SINGLE region (the native path)' if sel is not None and sel >= 3 else 'MULTI region (the emulated-CPS path)'}")
    print("   ⚠ this is a FORK. FUN_140118290 branches on it: <3 registers 10-18 regions (that is "
          "how the collection's emulated CPS titles work), >=3 registers exactly one. Everything "
          "we claim about MvC2 depends on being on the >=3 arm — assert it, never assume it.")
    print(f"G+0x1b0 (blk)  = 0x{g.u64(G + 0x1B0):x}    G+0x1b8 (size) = 0x{g.u32(G + 0x1B8):x} "
          f"(expect 0x{BLKSZ:x})")
    print(f"G+0x1c0 (blk2) = 0x{g.u64(G + 0x1C0):x}    G+0x1c8 (size) = 0x{g.u32(G + 0x1C8):x}")
    print(f"\nwhat GGPO recorded as registered:")
    print(f"   count @0x{REG_COUNT:x} = {g.u32(REG_COUNT)}")
    print(f"   base  @0x{REG_BASE:x}  = 0x{g.u64(REG_BASE):x}")
    print(f"   size  @0x{REG_SIZE:x}  = 0x{g.u32(REG_SIZE):x}")
    print("   (all zero offline = registration only happens when a GGPO session starts. Read these "
          "again DURING an online match — that is the only moment the claim is actually in force.)")
    print(f"\nrollbacks (G+0x76C) = {g.u32(EXE + 0xAC74AC)}")
    print(f"seat map  (G+0x258) = {struct.unpack('<4i', g.read(EXE + 0xAC6F98, 16))}")



SESSION_PTR = EXE + 0xACD3A8          # exe global -> the online SESSION object
SESS_KIND = 0xD0328                   # session+this: 1 = ranked, 2 = custom lobby, 4 = spectator
SESS_HOSTED = 0xD0320                 # session+this == 1 -> we are HOSTING
SESS_NET = 0x1B8                      # session+this >= 0 -> a net session is live


def cmd_watch(argv):
    """Follow the mode byte through every menu, so 'does this work in versus / arcade / training?'
    is answered by observation instead of by argument.

    Everything the replay kit does keys off ONE byte: blk+0x3CB8[2], 1 = character select, 2 = in
    battle. The anchor is taken when it reads 1, and that is the whole gate. So walk the game
    through training, versus, arcade and a lobby with this running, and whatever screens report
    mode 1 are the screens a tape can be anchored at. Nothing here writes.
    """
    g = Game()
    print("watching — walk the game through training / versus / arcade / a lobby.")
    print("a line prints whenever anything changes. press a key to stop.")
    print("")
    print(f"{'mode bytes':<20} {'screen':<14} {'frame':>9} {'teams':<26} session")
    prev = None
    while True:
        if msvcrt is not None and msvcrt.kbhit():
            msvcrt.getch(); break
        try:
            blk = g.u64(BLK_PTR)
            if not blk:
                continue
            m = g.read(blk + MODE_OFF, 5)
            if not m:
                continue
            fc = g.u32(blk + FC_OFF)
            teams = [g.read(blk + H0 + i * STRIDE + 0x6C0, 1)[0] for i in range(6)]
            sess = g.u64(SESSION_PTR)
            kind, hosted, net = None, None, None
            if sess and sess > 0x10000:
                kind = g.u32(sess + SESS_KIND)
                hosted = g.u32(sess + SESS_HOSTED)
                net = g.u32(sess + SESS_NET)
                if net >= 0x80000000:      # Game has no i32; sign it here
                    net -= 0x100000000
        except Exception:
            # menus tear these pointers down and rebuild them; a failed read just means "not now"
            time.sleep(0.1)
            continue
        screen = {1: "CHAR SELECT", 2: "IN BATTLE"}.get(m[2], "-")
        key = (tuple(m), tuple(teams), kind, hosted, net)
        if key != prev:
            prev = key
            ks = {1: "ranked", 2: "custom", 4: "spectator"}.get(kind, str(kind))
            anchor = "  <<< ANCHOR WOULD BE TAKEN HERE" if m[2] == 1 else ""
            print(f"{str(list(m)):<20} {screen:<14} {fc:>9} {str(teams):<26} "
                  f"kind={ks} hosted={hosted} net={net}{anchor}")
        time.sleep(0.05)
    print("")
    print("stopped. Every screen that reported CHAR SELECT is one a tape can be anchored at.")


CMDS = {"watch": cmd_watch, "rng": cmd_rng, "pool": cmd_pool, "cam": cmd_cam, "blk2": cmd_blk2, "reg": cmd_reg}

if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "all"
    if c == "all":
        for name in ("reg", "cam", "blk2", "pool"):
            print(f"\n{'=' * 78}\n== {name}\n{'=' * 78}")
            CMDS[name]([])
        print(f"\n{'=' * 78}\n== rng  (the decisive one — needs a busy fight)\n{'=' * 78}")
        cmd_rng([])
    elif c in CMDS:
        CMDS[c](sys.argv[2:])
    else:
        print(__doc__)
