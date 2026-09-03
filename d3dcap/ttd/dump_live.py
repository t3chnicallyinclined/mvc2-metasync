#!/usr/bin/env python3
"""dump_live.py -- read-only snapshot of the live Steam MvC2 process memory (no injection, no elevation).

Why this exists: a TTD trace only knows the bytes the RECORDED instructions touched; untouched pages replay
as unknown. The offline p-code harness needs whole images, so we snapshot them live right before (and after)
the recording and let extract.py merge the trace's known pages on top.

Addresses (RVA against the Ghidra image base 0x140000000; resolved against the live module base):
  game_state ptr  *(exe+0xACD3A0)        docs/STEAM-CODE-MAP.md "game_state"      (CONFIRMED)
  blk             *(exe+0x2EDF560)       == *(game_state+0x1B0), size *(game_state+0x1B8)=0x33B18 (CONFIRMED)
  blk2            *(exe+0x2EDF568)       2nd block, size 0x33B20 (STEAM-CODE-MAP.md +0x1c0/+0x1c8)
  ctx             *(exe+0x2EF0AB0)       = base+0x8000000 (docs/STAGE-DRAW-GHIDRA.md s2, CONFIRMED)
  dcram           *(ctx+8)               = ctx[1] = base+0x8400000, DC 0x0C000000.. host copy (CONFIRMED)
  frame clock     blk+0x3CC8 u32         docs/TAPE-V3-SPEC.md:43 (CONFIRMED)

Usage:  python dump_live.py --out <dir> [--pid N | --proc MarvelVsCapcomFightingCollection] [--dcram-mb 32]
Writes: meta.json exe_image.bin blk.bin blk2.bin game_state.bin ctx.bin dcram.bin (+ *.unreadable.json)
All outputs are game-derived: keep them under d3dcap/ttd/runs/ (gitignored).
"""
import argparse
import ctypes
import ctypes.wintypes as w
import json
import os
import struct
import subprocess
import time

k32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi
k32.OpenProcess.restype = w.HANDLE
k32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
k32.ReadProcessMemory.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.ReadProcessMemory.restype = w.BOOL
psapi.EnumProcessModules.argtypes = [w.HANDLE, ctypes.POINTER(ctypes.c_void_p), w.DWORD, w.LPDWORD]
PROCESS_VM_READ = 0x10
PROCESS_QUERY_INFORMATION = 0x400
GHIDRA_BASE = 0x140000000
RVA_GAME_STATE_PTR = 0xACD3A0
RVA_BLK_PTR = 0x2EDF560
RVA_BLK2_PTR = 0x2EDF568
RVA_CTX_PTR = 0x2EF0AB0
RVA_GGPO_SESSION = 0x2E10B98
BLK_SIZE = 0x33B18
BLK2_SIZE = 0x33B20
CLOCK_OFF = 0x3CC8
CTX_SIZE = 0x400000          # [base+0x8000000, base+0x8400000): ctx table + ctx[3]
PAGE = 0x1000


class MODULEINFO(ctypes.Structure):
    _fields_ = [("lpBaseOfDll", ctypes.c_void_p), ("SizeOfImage", w.DWORD), ("EntryPoint", ctypes.c_void_p)]


psapi.GetModuleInformation.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.POINTER(MODULEINFO), w.DWORD]
psapi.GetModuleFileNameExW.argtypes = [w.HANDLE, ctypes.c_void_p, w.LPWSTR, w.DWORD]


def find_pid(name):
    out = subprocess.check_output(["tasklist", "/FI", "IMAGENAME eq %s.exe" % name, "/FO", "CSV", "/NH"]).decode(errors="replace")
    for line in out.splitlines():
        if line.startswith('"'):
            return int(line.split('","')[1])
    return None


class Proc:
    def __init__(self, pid):
        self.pid = pid
        self.h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
        if not self.h:
            raise SystemExit("OpenProcess(%d) failed: %d" % (pid, ctypes.get_last_error()))
        mods = (ctypes.c_void_p * 1)()
        needed = w.DWORD()
        psapi.EnumProcessModules(self.h, mods, ctypes.sizeof(mods), ctypes.byref(needed))
        mi = MODULEINFO()
        psapi.GetModuleInformation(self.h, mods[0], ctypes.byref(mi), ctypes.sizeof(mi))
        self.base = mi.lpBaseOfDll
        self.size = mi.SizeOfImage
        buf = ctypes.create_unicode_buffer(1024)
        psapi.GetModuleFileNameExW(self.h, mods[0], buf, 1024)
        self.path = buf.value

    def read(self, addr, n):
        buf = ctypes.create_string_buffer(n)
        got = ctypes.c_size_t()
        ok = k32.ReadProcessMemory(self.h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got))
        return buf.raw[: got.value] if ok else None

    def q(self, addr):
        b = self.read(addr, 8)
        return struct.unpack("<Q", b)[0] if b else None

    def d(self, addr):
        b = self.read(addr, 4)
        return struct.unpack("<I", b)[0] if b else None

    def dump_pages(self, addr, n, path):
        """page-wise read; unreadable pages -> zero-filled + listed in <path>.unreadable.json"""
        bad = []
        with open(path, "wb") as f:
            off = 0
            while off < n:
                ln = min(PAGE, n - off)
                b = self.read(addr + off, ln)
                if b is None or len(b) != ln:
                    bad.append(hex(addr + off))
                    b = b"\0" * ln
                f.write(b)
                off += ln
        if bad:
            with open(path + ".unreadable.json", "w") as f:
                json.dump(bad, f)
        return len(bad)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--proc", default="MarvelVsCapcomFightingCollection")
    ap.add_argument("--dcram-mb", type=int, default=32, help="DC work-RAM image size to snapshot (doc: 32 MB image; DC RAM proper is 16 MB)")
    ap.add_argument("--no-exe-image", action="store_true")
    a = ap.parse_args()
    pid = a.pid or find_pid(a.proc)
    if not pid:
        raise SystemExit("process %s.exe not running" % a.proc)
    p = Proc(pid)
    os.makedirs(a.out, exist_ok=True)
    rv = lambda rva: p.base + rva
    gs = p.q(rv(RVA_GAME_STATE_PTR))
    blk = p.q(rv(RVA_BLK_PTR))
    blk2 = p.q(rv(RVA_BLK2_PTR))
    ctx = p.q(rv(RVA_CTX_PTR))
    dcram = p.q(ctx + 8) if ctx else None
    hx = lambda v: hex(v) if v else None
    meta = {
        "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "pid": pid, "exe": p.path, "module": os.path.splitext(os.path.basename(p.path))[0],
        "exe_base": hex(p.base), "exe_size": hex(p.size), "ghidra_base": hex(GHIDRA_BASE),
        "aslr_delta": hex(p.base - GHIDRA_BASE),
        "game_state": hx(gs),
        "blk": hx(blk), "blk_size": hex(BLK_SIZE),
        "blk_via_game_state": hx(p.q(gs + 0x1B0)) if gs else None,
        "blk_size_via_game_state": hx(p.d(gs + 0x1B8)) if gs else None,
        "blk2": hx(blk2), "blk2_size": hex(BLK2_SIZE),
        "ctx": hx(ctx), "ctx_size": hex(CTX_SIZE),
        "dcram": hx(dcram), "dcram_size": hex(a.dcram_mb << 20),
        "dc_base": "0x0C000000",
        "clock_addr": hx(blk + CLOCK_OFF) if blk else None,
        "clock_value": p.d(blk + CLOCK_OFF) if blk else None,
        "ggpo_session": hex(p.q(rv(RVA_GGPO_SESSION)) or 0),
        "scene_id": p.d(gs + 8) if gs else None,
        "rvas": {"game_state_ptr": hex(RVA_GAME_STATE_PTR), "blk_ptr": hex(RVA_BLK_PTR), "ctx_ptr": hex(RVA_CTX_PTR),
                 "render_dispatcher": "0x620960", "sprite_walker": "0x620F10", "ggpo_advance_frame_cb": "0x118F00",
                 "sim_tick": "0x118950"},
        "unreadable_pages": {},
    }
    print(json.dumps(meta, indent=1))
    if not blk or not dcram:
        raise SystemExit("blk / dcram pointers not resolvable (is the game past boot?)")
    t0 = time.time()
    meta["unreadable_pages"]["blk.bin"] = p.dump_pages(blk, BLK_SIZE, os.path.join(a.out, "blk.bin"))
    meta["unreadable_pages"]["blk2.bin"] = p.dump_pages(blk2, BLK2_SIZE, os.path.join(a.out, "blk2.bin")) if blk2 else None
    meta["unreadable_pages"]["game_state.bin"] = p.dump_pages(gs, 0x1000, os.path.join(a.out, "game_state.bin"))
    meta["unreadable_pages"]["ctx.bin"] = p.dump_pages(ctx, CTX_SIZE, os.path.join(a.out, "ctx.bin"))
    meta["unreadable_pages"]["dcram.bin"] = p.dump_pages(dcram, a.dcram_mb << 20, os.path.join(a.out, "dcram.bin"))
    if not a.no_exe_image:
        meta["unreadable_pages"]["exe_image.bin"] = p.dump_pages(p.base, p.size, os.path.join(a.out, "exe_image.bin"))
    meta["clock_value_after"] = p.d(blk + CLOCK_OFF)
    meta["dump_seconds"] = round(time.time() - t0, 2)
    with open(os.path.join(a.out, "meta.json"), "w") as f:
        json.dump(meta, f, indent=1)
    print("[dump_live] wrote %s in %s s; clock %s -> %s" % (a.out, meta["dump_seconds"], meta["clock_value"], meta["clock_value_after"]))


if __name__ == "__main__":
    main()
