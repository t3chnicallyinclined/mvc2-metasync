#!/usr/bin/env python3
"""rrtape3.py rec <name> <secs> | play <file.rr3> | info <file.rr3>

TAPE v3 — PORTABLE. No snapshot.

v1/v2 shipped the whole 211,736-byte deterministic state. That works perfectly IN-PROCESS (proven:
two replays gave bit-identical end states) but can never leave the process: the Steam build is a
native recompile, so the blob is full of absolute host pointers (measured: 730 into blk, 557 into
the arena, 272 into the exe) AND 557 of those point into the per-character asset image, whose
CONTENTS depend on which characters that session happened to load. Relocation fixes addresses; it
cannot fix contents. Restoring cross-process crashed the game, twice.

v3 uses Flycast Dojo's fallback instead (DojoSession.cpp:553-583): when no savestate exists, peers
boot from power-on and re-derive a shared state by simulation. Measured across three cold boots to
character select, the sim state is 99.6% identical — the only genuinely varying words are a stable
832-byte VOLATILE SET (frame counter, input words, a few animation timers, render attrs).

    tape = 832-byte volatile patch + input stream (~2 B/frame)

Nothing to relocate, nothing bound to this process. Format:
    magic b"RRTAPE30" | u32+JSON header | u32+zlib(volatile patch) | u32+zlib(inputs)
"""
import json
import os
import struct
import sys
import time
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from savestate import Game, BLK_PTR, BLKSZ, FC_OFF
from inputrec import IN0, SEATMAP, patch, sanity
from mvcmem import EXE

MAGIC = b"RRTAPE30"
HERE = os.path.dirname(os.path.abspath(__file__))


def vruns():
    p = os.path.join(HERE, "volatile_set.json")
    if not os.path.exists(p):
        sys.exit("no volatile_set.json — run: python3 volatile_set.py boot1 boot2 boot3")
    return [(r["off"], r["len"]) for r in json.load(open(p))["runs"]]


def wait_select_entry(g, blk, timeout=180):
    """Anchor on a FRESH character select, not wherever the cursor happens to be.

    A tape anchored mid-character-select is not reproducible: the cursor keeps whatever position
    the previous session left it on, so replaying the same directional inputs into a freshly
    entered select screen lands on different characters. Waiting for the TRANSITION into character
    select gives a canonical starting condition — the screen effectively starts from 0.
    """
    def mode():
        return g.read(blk + 0x3CB8, 5)[2]

    t0 = time.time()
    if mode() == 1:
        print("already at character select — leave and re-enter it for a clean anchor...")
        while mode() == 1:
            if time.time() - t0 > timeout:
                sys.exit("timed out waiting to leave character select")
            time.sleep(0.02)
    print("waiting for character select to open...")
    while mode() != 1:
        if time.time() - t0 > timeout:
            sys.exit("timed out waiting for character select")
        time.sleep(0.01)
    f = g.u32(blk + FC_OFF)
    print(f"character select entered at frame {f} — anchoring here")
    return f


def rec(name, secs, fresh=False):
    g = Game()
    blk = g.u64(BLK_PTR)
    runs = vruns()
    if fresh:
        wait_select_entry(g, blk)

    held = g.freeze()
    try:
        f0 = g.u32(blk + FC_OFF)
        state = g.read(blk, BLKSZ)
        f1 = g.u32(blk + FC_OFF)
    finally:
        g.thaw(held)
    if f0 != f1:
        sys.exit("torn read")

    vol = b"".join(state[o:o + n] for o, n in runs)
    print(f"anchor frame {f0}; volatile patch {len(vol)} B from {len(runs)} runs")

    rows, last, t0 = [], None, time.time()
    nextmsg = t0 + 1.0
    while time.time() - t0 < secs:
        fc = g.u32(blk + FC_OFF)
        if fc == last:
            continue
        last = fc
        rows.append((fc, g.u32(IN0), g.u32(IN0 + 4)))
        now = time.time()
        if now >= nextmsg:                      # a silent loop reads as a hang
            nextmsg = now + 1.0
            act = sum(1 for _, a, b in rows if a or b)
            print(f"  {now-t0:4.0f}s / {secs:.0f}s   {len(rows):5d} frames, {act} with input",
                  flush=True)
    inp = b"".join(struct.pack("<III", *r) for r in rows)
    nz = sum(1 for _, a, b in rows if a or b)
    print(f"recorded {len(rows)} frames, {nz} with input ({100.0*nz/max(1,len(rows)):.0f}%)")

    teams = [state[0x3DB8 + i * 0x738 + 0x6C0] for i in range(6)]
    hdr = json.dumps({
        "ver": 3, "start_frame": f0, "frames": len(rows), "teams": teams,
        "mode": list(state[0x3CB8:0x3CBD]), "runs": runs, "ts": int(time.time()),
        "fresh_select": bool(fresh),
        "note": "portable: volatile patch + inputs, no snapshot",
    }).encode()
    cv, ci = zlib.compress(vol, 9), zlib.compress(inp, 9)
    out = os.path.join(HERE, name + ".rr3")
    with open(out, "wb") as f:
        f.write(MAGIC)
        f.write(struct.pack("<I", len(hdr))); f.write(hdr)
        f.write(struct.pack("<I", len(cv)));  f.write(cv)
        f.write(struct.pack("<I", len(ci)));  f.write(ci)
    print(f"packed {out}  {os.path.getsize(out):,} B   "
          f"(vs {BLKSZ:,} B for a v2 snapshot tape)")


def load(path):
    d = open(path, "rb").read()
    if d[:8] != MAGIC:
        sys.exit("not an rr3 tape")
    o = 8
    hl, = struct.unpack_from("<I", d, o); o += 4
    hdr = json.loads(d[o:o + hl]); o += hl
    vl, = struct.unpack_from("<I", d, o); o += 4
    vol = zlib.decompress(d[o:o + vl]); o += vl
    il, = struct.unpack_from("<I", d, o); o += 4
    return hdr, vol, zlib.decompress(d[o:o + il])


def info(path):
    hdr, vol, inp = load(path)
    print(json.dumps({k: v for k, v in hdr.items() if k != "runs"}, indent=1))
    print(f"volatile {len(vol)} B in {len(hdr['runs'])} runs; inputs {len(inp)//12} frames; "
          f"file {os.path.getsize(path):,} B")


def play(path, apply_patch=True):
    hdr, vol, inp = load(path)
    rows = [struct.unpack_from("<III", inp, i) for i in range(0, len(inp), 12)]
    g = Game()
    sanity(g)
    blk = g.u64(BLK_PTR)
    print(f"tape v{hdr['ver']}: {hdr['frames']} frames, anchor frame {hdr['start_frame']}, "
          f"mode {hdr['mode']}")
    if hdr.get("fresh_select"):
        wait_select_entry(g, blk)          # same canonical anchor the tape was recorded on
    cur_mode = list(g.read(blk + 0x3CB8, 5))
    print(f"game mode now {cur_mode}")
    if cur_mode[2] != hdr["mode"][2]:
        where = {1: "CHARACTER SELECT", 2: "IN BATTLE"}
        want = where.get(hdr["mode"][2], hdr["mode"][2])
        have = where.get(cur_mode[2], cur_mode[2])
        sys.exit(f"REFUSING: tape was recorded on {want}, game is currently {have}."
                 "\n  Get to the same screen and run this again.")

    if apply_patch:
        held = g.freeze()
        try:
            off = 0
            for o, n in hdr["runs"]:
                g.write(blk + o, vol[off:off + n]); off += n
        finally:
            g.thaw(held)
        print(f"applied {len(vol)} B volatile patch across {len(hdr['runs'])} runs")
        time.sleep(0.05)
        print(f"frame now {g.u32(blk + FC_OFF)}")

    # FRAME-LOCKED FEED. Feeding one input per observed frame-change drifts: every missed poll
    # shifts the whole remaining stream by a frame, and a few frames of drift on a character-select
    # cursor picks a different character. Instead, key inputs by their RECORDED frame number and
    # write each one only when the game reaches that frame.
    #
    # The volatile patch includes the frame counter (blk+0x3CC8), so after patching the game's
    # frame counter already equals the tape's anchor — the two clocks start together.
    #
    # We write the input for frame F+1 the moment frame F begins, so it is in place a full frame
    # before the sim reads it, rather than racing mid-frame.
    by_frame = {fc: (s0, s1) for fc, s0, s1 in rows}
    first, last_tape = rows[0][0], rows[-1][0]
    patch(g, True)
    try:
        base = g.u32(blk + FC_OFF)
        drift = base - first
        print(f"clock aligned: game frame {base}, tape starts {first} (drift {drift:+d})")
        fed = late = 0
        seen = set()
        last = None
        deadline = time.perf_counter() + (len(rows) / 60.0) * 3 + 5
        while time.perf_counter() < deadline:
            cur = g.u32(blk + FC_OFF)
            if cur == last:
                continue
            last = cur
            nxt = cur - drift + 1                 # the tape frame about to run
            if nxt > last_tape:
                break
            v = by_frame.get(nxt)
            if v is not None and nxt not in seen:
                g.write(IN0, struct.pack("<II", *v))
                seen.add(nxt)
                fed += 1
        late = len(rows) - fed
        print(f"fed {fed}/{len(rows)} frames on their exact frame ({late} not reached) "
              f"-> frame {g.u32(blk + FC_OFF)}")
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
    if c == "rec":
        rec(sys.argv[2], float(sys.argv[3]), "--fresh" in sys.argv)
    elif c == "play":
        play(sys.argv[2], "--nopatch" not in sys.argv)
    else:
        info(sys.argv[2])
