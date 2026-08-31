#!/usr/bin/env python3
"""blk_localize.py — turn "blk CRC differs SOMEWHERE" into a CONCRETE diverging-offset list.

WHY. rrtape4.py `play` compares the live replay against the RECORDED checkpoints and reports only a
whole-blk CRC ("differs somewhere"). That comparison is contaminated by the record-vs-replay frame
phase (the restore lands ~21 frames late — the settle sleep). This tool removes that confound by
comparing TWO REPLAYS from the SAME anchor (A vs C), both of which carry the same restore phase, and
by dumping the FULL 211,736-byte blk at chosen tape-frames so we can name EXACTLY which offsets differ
and which game structure owns each.

    A==C at a post-super match frame (only frame-counter/preview differs)  => replay is deterministic;
        the record-vs-replay CRC mismatch was an alignment/frame-phase artifact, NOT nondeterminism.
    A!=C in FIGHTER-SIM or POOL(effect) fields at a match frame            => REAL nondeterminism
        (the RNG-through-super risk). That is a load-bearing negative, not a bug to paper over.

USAGE (run from replay-kit/, elevated, game running):
    python blk_localize.py cap <tape.rr4> A  --at 11640,13005
    python blk_localize.py cap <tape.rr4> C  --at 11640,13005     # same tape, second replay
    python blk_localize.py diff A C          --at 11640,13005     # concrete offset list + structure

Pick --at frames that include (1) a char-select frame (e.g. the first checkpoint) and (2) a MATCH
frame AT/AFTER the first super. `python rrtape4.py info <tape>` prints match_start; supers land in the
match window. Default --at = every checkpoint frame in the tape.

WRITES to the game (anchor + inputs), exactly like PLAY4/AB. Read the game's blk read-only for the
dumps. Reverts the input-store patch on exit.
"""
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from savestate import Game, BLK_PTR, BLKSZ, FC_OFF
from inputrec import IN0, patch, sanity
import rrtape4

HERE = os.path.dirname(os.path.abspath(__file__))
STRIDE = 0x738
H0 = 0x3DB8

# ── object pool (satellite: projectiles/assists/effects/hitsparks/super-flash AND, at char-select,
#    the rotating preview models). base≈blk+0x6dd8, stride 0x280, 256 nodes → ~blk+0x6dd8..0x2edd8.
#    KB: mvc2-dc-steam-block-map (pool INSIDE blk, carried by the anchor; preview models are pool nodes).
POOL_LO, POOL_HI = 0x6dd8, 0x2edd8
# fighter-sim sub-fields inside a 0x738 slot (Steam offsets, per rrtape4.digest / block map)
FSIM = {0x50: "worldX", 0x54: "worldY", 0x78: "velX", 0x7c: "velY", 0x124: "screenX",
        0x128: "screenY", 0x144: "sprite_id", 0x170: "draw_gate", 0x1d2: "xflip",
        0x578: "HP", 0x57c: "red_HP", 0x6c0: "CID(cursor/pick)", 0x68e: "cursor_anim"}


def classify(off):
    if 0x3CC8 <= off < 0x3CCC or 0x3CD4 <= off < 0x3CD8:
        return "FRAME COUNTER (+mirror) — excluded from CRC; BENIGN"
    if 0x3C66 <= off < 0x3CB8:
        return "input words — fed by the tape; BENIGN"
    if 0x3CB8 <= off < 0x3CC0:
        return "mode discriminator"
    if H0 <= off < H0 + 6 * STRIDE:
        i = (off - H0) // STRIDE
        fo = (off - H0) % STRIDE
        name = FSIM.get(fo)
        if name is None:
            for b, n in sorted(FSIM.items()):
                if b <= fo < b + 4:
                    name = n + "+%d" % (fo - b); break
        kind = "SIM" if fo not in (0x6c0, 0x68e) else "char-select cursor"
        return "fighter slot %d +0x%x %s [%s]" % (i, fo, name or "?", kind)
    if POOL_LO <= off < POOL_HI:
        n = (off - POOL_LO) // 0x280
        no = (off - POOL_LO) % 0x280
        return "OBJECT-POOL node ~%d +0x%x [char-select=preview model / match=effect/projectile]" % (n, no)
    if 0x2ee34 <= off < 0x2f4d0:
        return "pool head-lists"
    if 0x2f4d0 <= off < 0x324d0:
        return "draw list"
    if 0x324d0 <= off < 0x324e0:
        return "draw-list counts"
    if 0x324e0 <= off < 0x32570:
        return "battle globals (state/in_match/timer/meter/combo)"
    if 0x32500 <= off < 0x32530:
        return "slot self-pointer table (relocated pointers; BENIGN)"
    if 0x32b00 <= off < 0x32d00:
        return "render attrs"
    if 0x3CE8 <= off < 0x3D0A:
        return "unlocks/game-mode (set pre-match; BENIGN)"
    return "? UNMAPPED"


def cap(path, tag, at):
    hdr, state, inp, chk = rrtape4.load(path)
    rows = [struct.unpack_from("<III", inp, i) for i in range(0, len(inp), 12)]
    by_frame = {fc: (s0, s1) for fc, s0, s1 in rows}
    first, last_tape = rows[0][0], rows[-1][0]
    targets = sorted(set(at)) if at else sorted(
        {struct.unpack_from("<I", chk, i)[0] for i in range(0, len(chk) - hdr.get("chk_size", 0) + 1,
                                                             hdr.get("chk_size", 1))} if chk else set())
    g = Game()
    sanity(g)
    blk = rrtape4.restore_anchor(g, hdr, state, quiet=True)
    base = g.u32(blk + FC_OFF)
    drift = base - first
    print("tag %s: anchor restored, base=%d first=%d drift=%+d, targets(tape-frame)=%s"
          % (tag, base, first, drift, targets))
    grabbed = {}
    patch(g, True)
    try:
        last = None
        deadline = time.perf_counter() + (len(rows) / 60.0) * 3 + 5
        while time.perf_counter() < deadline and len(grabbed) < len(targets):
            cur = g.u32(blk + FC_OFF)
            if cur is None or cur == last:
                continue
            last = cur
            tf = cur - drift
            if tf in targets and tf not in grabbed:
                f0 = g.u32(blk + FC_OFF)
                b = g.read(blk, BLKSZ)
                if b is not None and g.u32(blk + FC_OFF) == f0:
                    open(os.path.join(HERE, "blk_%s_%d.bin" % (tag, tf)), "wb").write(b)
                    grabbed[tf] = True
                    print("  dumped tape-frame %d (game-frame %d)" % (tf, cur))
            nxt = tf + 1
            if nxt > last_tape:
                break
            v = by_frame.get(nxt)
            if v is not None:
                g.write(IN0, struct.pack("<II", *v))
    finally:
        patch(g, False)
    print("captured %d/%d target frames for tag %s" % (len(grabbed), len(targets), tag))


def diff(ta, tb, at):
    for tf in sorted(set(at)):
        pa = os.path.join(HERE, "blk_%s_%d.bin" % (ta, tf))
        pb = os.path.join(HERE, "blk_%s_%d.bin" % (tb, tf))
        if not (os.path.exists(pa) and os.path.exists(pb)):
            print("\n== tape-frame %d: MISSING dump (%s or %s) ==" % (tf, ta, tb)); continue
        A = open(pa, "rb").read(); B = open(pb, "rb").read()
        d = [i for i in range(min(len(A), len(B))) if A[i] != B[i]]
        runs = []
        for o in d:
            if runs and o <= runs[-1][1] + 8:
                runs[-1][1] = o + 1
            else:
                runs.append([o, o + 1])
        # verdict flags
        sim = [r for r in runs if "[SIM]" in classify(r[0])]
        pool = [r for r in runs if classify(r[0]).startswith("OBJECT-POOL")]
        print("\n== tape-frame %d: %d bytes differ (%s vs %s), %d runs ==" % (tf, len(d), ta, tb, len(runs)))
        for lo, hi in runs:
            print("   blk+0x%05x  %4d B   %s" % (lo, hi - lo, classify(lo)))
        if not d:
            print("   ✅ A==C byte-identical → deterministic at this frame.")
        elif sim or pool:
            print("   ❌ REAL divergence: %d fighter-SIM run(s), %d object-pool(effect) run(s). "
                  "Nondeterminism (RNG-through-super candidate)." % (len(sim), len(pool)))
        else:
            print("   ✅ only frame-counter/cursor/preview/render/pointer differ → cosmetic; "
                  "match sim is deterministic here.")


def parse_at(argv):
    for i, a in enumerate(argv):
        if a == "--at" and i + 1 < len(argv):
            return [int(x, 0) for x in argv[i + 1].split(",") if x]
    return []


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(0)
    c = sys.argv[1]
    at = parse_at(sys.argv)
    if c == "cap":
        cap(sys.argv[2], sys.argv[3], at)
    elif c == "diff":
        diff(sys.argv[2], sys.argv[3], at)
    else:
        print(__doc__)
