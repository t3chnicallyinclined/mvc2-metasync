#!/usr/bin/env python3
"""inputrec.py rec <name> <secs> | play <name> | probe — record and replay a match from inputs.

THE ARCHIVAL FORMAT under test:
    <name>.state  = blk[0..0x33B18)   the complete deterministic state at the start frame
    <name>.inp    = per frame: [u32 frame][u32 seat0][u32 seat1]   (12 B/frame on disk)

REPLAY = restore the snapshot, then feed the recorded inputs one frame at a time. If MvC2 is
deterministic from (state, inputs) — which its own GGPO rollback proves, since that is exactly
what a rollback re-simulation does — the match reproduces exactly.

THE PATCH. In offline/training the GGPO tick never runs; FUN_140039de0 reads the pad and stores
it over G+0x218 every frame, so external writes are clobbered ~0x74 bytes before the sim reads
them. We NOP the two 6-byte stores (seats 0 and 1) so OUR writes are authoritative, then restore
the original bytes afterwards. Only 12 bytes of code change, and it is always reverted.
    0x14003A33B: 89 81 18 02 00 00   MOV [RCX+0x218], EAX   (seat 0)
    0x14003A35F: 89 81 1C 02 00 00   MOV [RCX+0x21C], EAX   (seat 1)

We do NOT touch the `prev = cur` shuffle that precedes each store — the engine still maintains
just-pressed/just-released correctly from whatever we write.
"""
import ctypes
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from savestate import Game, BLK_PTR, BLKSZ, FC_OFF, k32
from mvcmem import EXE

HERE = os.path.dirname(os.path.abspath(__file__))
IN0 = EXE + 0xAC6F58                  # G+0x218, seat 0 current input (u32, 24-bit)
SEATMAP = EXE + 0xAC6F98              # G+0x258
STORES = [(0x14003A33B, bytes.fromhex("898118020000")),
          (0x14003A35F, bytes.fromhex("89811c020000"))]
PAGE_EXECUTE_READWRITE = 0x40


def patch(g, enable):
    """NOP (or restore) the two input stores. Returns the original bytes for safety."""
    old = ctypes.c_ulong(0)
    for addr, orig in STORES:
        k32.VirtualProtectEx(g.h, ctypes.c_void_p(addr), len(orig),
                             PAGE_EXECUTE_READWRITE, ctypes.byref(old))
        cur = g.read(addr, len(orig))
        want = b"\x90" * len(orig) if enable else orig
        if cur != want:
            g.write(addr, want)
        k32.VirtualProtectEx(g.h, ctypes.c_void_p(addr), len(orig), old.value,
                             ctypes.byref(ctypes.c_ulong(0)))


def sanity(g):
    """Refuse to patch if the bytes are not what we expect — a patched/updated build must not
    be blindly overwritten."""
    for addr, orig in STORES:
        cur = g.read(addr, len(orig))
        if cur not in (orig, b"\x90" * len(orig)):
            sys.exit(f"UNEXPECTED CODE at 0x{addr:x}: {cur.hex()} — refusing to patch")


def rec(name, secs):
    g = Game()
    blk = g.u64(BLK_PTR)
    held = g.freeze()
    try:
        f0 = g.u32(blk + FC_OFF)
        snap = g.read(blk, BLKSZ)
        f1 = g.u32(blk + FC_OFF)
    finally:
        g.thaw(held)
    if f0 != f1:
        sys.exit("torn snapshot")
    open(os.path.join(HERE, name + ".state"), "wb").write(snap)
    print(f"snapshot @ frame {f0} ({len(snap)} B)")

    rows, last, t0 = [], None, time.time()
    while time.time() - t0 < secs:
        fc = g.u32(blk + FC_OFF)
        if fc == last:
            continue
        last = fc
        s0 = g.u32(IN0)
        s1 = g.u32(IN0 + 4)
        rows.append((fc, s0, s1))
    with open(os.path.join(HERE, name + ".inp"), "wb") as f:
        for r in rows:
            f.write(struct.pack("<III", *r))
    nz = sum(1 for _, a, b in rows if a or b)
    print(f"recorded {len(rows)} frames, {nz} with input "
          f"({100.0 * nz / max(1, len(rows)):.0f}%) -> {name}.inp")
    if nz == 0:
        print("  ⚠ ZERO input frames captured — G+0x218 is not the live input in this mode")


def play(name):
    g = Game()
    sanity(g)
    blk = g.u64(BLK_PTR)
    snap = open(os.path.join(HERE, name + ".state"), "rb").read()
    raw = open(os.path.join(HERE, name + ".inp"), "rb").read()
    rows = [struct.unpack_from("<III", raw, i) for i in range(0, len(raw), 12)]
    print(f"restoring frame {int.from_bytes(snap[FC_OFF:FC_OFF+4], 'little')}, "
          f"{len(rows)} input frames")

    held = g.freeze()
    try:
        g.write(blk, snap)
    finally:
        g.thaw(held)
    time.sleep(0.05)

    patch(g, True)
    try:
        fed = miss = 0
        last = None
        base = g.u32(blk + FC_OFF)
        for i, (fc, s0, s1) in enumerate(rows):
            deadline = time.perf_counter() + 0.05
            while True:                       # wait for the sim to reach the next frame
                cur = g.u32(blk + FC_OFF)
                if cur != last:
                    break
                if time.perf_counter() > deadline:
                    miss += 1
                    break
            last = cur
            g.write(IN0, struct.pack("<II", s0, s1))
            fed += 1
        # Capture the outcome HERE — still frozen out of live input. Once we un-patch, the pad is
        # authoritative again and the sim runs on, so any state read after that is polluted by
        # however many frames elapsed plus whatever the player pressed. Comparing those is what
        # made an earlier determinism check meaningless.
        end_fc = g.u32(blk + FC_OFF)
        out = []
        for i in range(6):
            H = blk + 0x3DB8 + i * 0x738
            out.append((g.read(H + 0x170, 1)[0], g.read(H + 0x6C0, 1)[0],
                        struct.unpack("<I", g.read(H + 0x578, 4))[0] & 0xFFFF,
                        round(struct.unpack("<f", g.read(H + 0x50, 4))[0], 3),
                        round(struct.unpack("<f", g.read(H + 0x54, 4))[0], 3),
                        int.from_bytes(g.read(H + 0x188, 2), "little") & 0x7FFF))
        print(f"fed {fed} frames ({miss} timing misses); frame {base} -> {end_fc}")
        import json
        json.dump({"fc": end_fc, "slots": out},
                  open(os.path.join(HERE, name + ".out.json"), "w"))
        for i, v in enumerate(out):
            if v[0]:
                print(f"   slot{i} cid={v[1]:3d} hp={v[2]:3d} pos=({v[3]},{v[4]}) sid={v[5]}")
    finally:
        patch(g, False)
        print("code un-patched")


def probe():
    g = Game()
    blk = g.u64(BLK_PTR)
    print("watching inputs for 6s — press/hold things now")
    seen = {}
    t0 = time.time()
    while time.time() - t0 < 6:
        for label, addr in (("G+0x218 seat0", IN0), ("G+0x21c seat1", IN0 + 4)):
            v = g.u32(addr)
            if v:
                seen.setdefault(label, set()).add(v)
        v = int.from_bytes(g.read(blk + 0x3C66, 2), "little")
        if v:
            seen.setdefault("blk+0x3C66 sim", set()).add(v)
        v = int.from_bytes(g.read(blk + 0x3C66 + 0x14, 2), "little")
        if v:
            seen.setdefault("blk+0x3C7A sim p2", set()).add(v)
    if not seen:
        print("  NOTHING — no input observed at any of the candidate addresses")
    for k, vals in seen.items():
        print(f"  {k}: {len(vals)} distinct, e.g. " +
              " ".join("0x%x" % x for x in sorted(vals)[:8]))
    print("seat map:", [int.from_bytes(g.read(SEATMAP + 4 * k, 4), "little", signed=True)
                        for k in range(4)])


if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "probe"
    if c == "rec":
        rec(sys.argv[2], float(sys.argv[3]))
    elif c == "play":
        play(sys.argv[2])
    else:
        probe()
