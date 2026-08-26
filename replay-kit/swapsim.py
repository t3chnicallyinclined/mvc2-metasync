#!/usr/bin/env python3
"""swapsim.py <tape.rr4> [frames] — run a tape's state in a SEPARATE buffer inside the same game.

THE IDEA: don't extract the simulator, redirect it. The sim reaches its state through a pointer.
Allocate another 0x33B18 buffer in the game's address space, relocate a tape's state into it, point
the engine there, run frames, then point it back. One process, one licence, N independent matches —
no extraction, no asset-loader rewrite, no packer to defeat.

POINTERS THE ENGINE HOLDS (probed live; all three must move together or it reads a torn mix):
    0x140AC6EF0  G+0x1b0       = blk           the registered/authoritative pointer
    0x142EDF560  render cache  = blk
    0x142EDF580                = blk + 0x3CB8  points INTO blk (mode/frame region)
Left alone: 0x142EF0AB0 (the arena asset table — not blk-relative) and the GGPO region base
(0x142D107D0), which is 0 offline.

The state itself is full of absolute self-pointers, so it is relocated to the NEW buffer's address
using the same delta logic and the same self-check as normal playback: blk+0x32500+8k must hold the
six fighter bases in some order.

⚠ This writes to a live process and moves the engine's state pointer. Everything is restored in a
finally block, but a crash means restarting the game.
"""
import ctypes
import ctypes.wintypes as w
import json
import struct
import sys
import time
import os
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from savestate import Game, BLK_PTR, BLKSZ, FC_OFF, k32
from rrtape4 import load, ASZ, ARENA_PTR, FRAMES_TO_RUN
from mvcmem import EXE

PTRS = [("G+0x1b0", 0x140AC6EF0, 0), ("render cache", 0x142EDF560, 0),
        ("mode ptr", 0x142EDF580, 0x3CB8)]
MEM_COMMIT_RESERVE = 0x3000
PAGE_READWRITE = 0x04

k32.VirtualAllocEx.restype = w.LPVOID
k32.VirtualAllocEx.argtypes = [w.HANDLE, w.LPVOID, ctypes.c_size_t, w.DWORD, w.DWORD]
k32.VirtualFreeEx.argtypes = [w.HANDLE, w.LPVOID, ctypes.c_size_t, w.DWORD]

tape = sys.argv[1]
run_frames = int(sys.argv[2]) if len(sys.argv) > 2 else 600

hdr, state, inp = load(os.path.join(os.path.dirname(os.path.abspath(__file__)), tape))
g = Game()
real_blk = g.u64(BLK_PTR)
arena = g.u64(ARENA_PTR)
print(f"live blk 0x{real_blk:x}   tape blk 0x{hdr['blk']:x}   frames in tape {hdr['frames']}")

buf = k32.VirtualAllocEx(g.h, None, BLKSZ, MEM_COMMIT_RESERVE, PAGE_READWRITE)
if not buf:
    sys.exit(f"VirtualAllocEx failed {ctypes.get_last_error()}")
print(f"allocated shadow state buffer at 0x{buf:x} ({BLKSZ} B)")

try:
    # relocate the tape's state to live at `buf` instead of wherever it was captured
    s = bytearray(state)
    d_blk, d_arena = buf - hdr["blk"], arena - hdr["arena"]
    nb = na = 0
    for off in range(0, len(s) - 8, 8):
        p = int.from_bytes(s[off:off + 8], "little")
        if hdr["blk"] <= p < hdr["blk"] + BLKSZ:
            s[off:off + 8] = (p + d_blk).to_bytes(8, "little"); nb += 1
        elif hdr["arena"] <= p < hdr["arena"] + ASZ:
            s[off:off + 8] = (p + d_arena).to_bytes(8, "little"); na += 1
    seen = set()
    for k in range(6):
        p = int.from_bytes(s[0x32500 + 8 * k:0x32508 + 8 * k], "little")
        rel = p - buf - 0x3DB8
        if rel < 0 or rel % 0x738 or not (0 <= rel // 0x738 < 6):
            sys.exit(f"SELF-CHECK FAILED: entry {k} = 0x{p:x}")
        seen.add(rel // 0x738)
    if seen != set(range(6)):
        sys.exit(f"SELF-CHECK FAILED: not a permutation {sorted(seen)}")
    print(f"relocated {nb} intra-blk + {na} arena pointers to the shadow buffer; self-check PASS")
    g.write(buf, bytes(s))

    saved = [(name, addr, g.u64(addr)) for name, addr, _ in PTRS]
    held = g.freeze()
    try:
        for (name, addr, delta) in PTRS:
            g.write(addr, struct.pack("<Q", buf + delta))
    finally:
        g.thaw(held)
    print("engine redirected to the shadow buffer")

    try:
        f0 = g.u32(buf + FC_OFF)
        t0 = time.perf_counter()
        deadline = t0 + 6.0
        while time.perf_counter() < deadline:
            g.write(FRAMES_TO_RUN, struct.pack("<I", 8))
            if g.u32(buf + FC_OFF) - f0 >= run_frames:
                break
        dt = time.perf_counter() - t0
        f1 = g.u32(buf + FC_OFF)
        real_now = g.u32(real_blk + FC_OFF)
        print(f"\nSHADOW state advanced {f1 - f0} frames in {dt:.2f}s "
              f"({(f1-f0)/dt:,.0f} fps)")
        print(f"  shadow frame {f0} -> {f1}")
        print(f"  the REAL match block is at frame {real_now} (untouched by this run)")
        for i in range(6):
            H = buf + 0x3DB8 + i * 0x738
            if g.read(H + 0x170, 1)[0]:
                hp = struct.unpack("<I", g.read(H + 0x578, 4))[0] & 0xFFFF
                x, y = struct.unpack("<ff", g.read(H + 0x50, 8))
                print(f"   shadow slot{i} cid={g.read(H+0x6C0,1)[0]:3d} hp={hp:3d} "
                      f"pos=({x:.1f},{y:.1f})")
    finally:
        held = g.freeze()
        try:
            for name, addr, val in saved:
                g.write(addr, struct.pack("<Q", val))
            g.write(FRAMES_TO_RUN, struct.pack("<I", 1))
        finally:
            g.thaw(held)
        print("\nengine restored to the real match block")
finally:
    k32.VirtualFreeEx(g.h, ctypes.c_void_p(buf), 0, 0x8000)   # MEM_RELEASE

time.sleep(0.4)
try:
    print(f"game still alive: frame {g.u32(g.u64(BLK_PTR) + FC_OFF)}")
except OSError as e:
    print(f"GAME DIED: {e}")
