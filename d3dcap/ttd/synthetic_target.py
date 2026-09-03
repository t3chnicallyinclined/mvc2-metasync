#!/usr/bin/env python3
"""synthetic_target.py -- a stand-in for the game so the TTD pipeline can be proven without MvC2.

Mimics the memory shape extract.js relies on:
  blk    = 0x4000-byte buffer; u32 "frame clock" at blk+0x3CC8 incremented once per 16 ms tick (like blk+0x3CC8)
  dcram  = 0x10000-byte buffer read every tick (like the DC-RAM host image)
  ctx    = 0x1000-byte buffer
Each tick also calls into ntdll (time.sleep -> NtCreateTimer2/NtSetTimerEx/NtWaitForMultipleObjects on 3.13) so the Calls stage has a symbol target.
Writes <out>/synthetic_cfg.json for `extract.py --synthetic`.

  python synthetic_target.py --out <dir> [--ticks 400]
"""
import argparse
import ctypes
import json
import os
import sys
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--ticks", type=int, default=600)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    blk = ctypes.create_string_buffer(0x4000)
    dcram = ctypes.create_string_buffer(0x10000)
    ctx = ctypes.create_string_buffer(0x1000)
    for i in range(0, 0x10000, 4):
        ctypes.memmove(ctypes.addressof(dcram) + i, (i & 0xFF).to_bytes(4, "little"), 4)
    clock = ctypes.c_uint32.from_buffer(blk, 0x3CC8)
    other = ctypes.c_uint32.from_buffer(blk, 0x100)
    rd = ctypes.c_uint32.from_buffer(dcram, 0x200)
    cfg = {
        "module": "python",
        "clock_addr": hex(ctypes.addressof(blk) + 0x3CC8), "clock_size": 4, "boundary": "clock",
        "blk": hex(ctypes.addressof(blk)), "blk_size": hex(0x4000),
        "dcram": hex(ctypes.addressof(dcram)), "dcram_size": hex(0x10000),
        "ctx": hex(ctypes.addressof(ctx)), "ctx_size": hex(0x1000), "game_state": None,
        "funcs_rva": [], "funcs_sym": ["ntdll!NtWaitForMultipleObjects", "ntdll!NtSetTimerEx", "ntdll!NtCreateTimer2", "ntdll!NtClose", "ntdll!NtWriteFile", "ntdll!NtDelayExecution"],   # Python 3.13 time.sleep = NtCreateTimer2/NtSetTimerEx/NtWaitForMultipleObjects (measured on the trace)
        "probe_call_target": "ntdll!NtWaitForMultipleObjects", "probe_call_target_is_rva": False,
        "pid": os.getpid(), "live_base": "0x0",
    }
    json.dump(cfg, open(os.path.join(a.out, "synthetic_cfg.json"), "w"), indent=1)
    print("[synthetic] pid %d clock %s blk %s; cfg %s" % (os.getpid(), cfg["clock_addr"], cfg["blk"], os.path.join(a.out, "synthetic_cfg.json")), flush=True)
    for t in range(a.ticks):
        clock.value += 1                 # the "frame boundary" write
        other.value = rd.value + t       # a blk write fed by a dcram read
        ctypes.memmove(ctypes.addressof(ctx), ctypes.addressof(dcram) + (t % 64) * 16, 16)   # dcram reads at varying pages
        time.sleep(0.016)
    print("[synthetic] done %d ticks, clock=%d" % (a.ticks, clock.value), flush=True)


if __name__ == "__main__":
    main()
