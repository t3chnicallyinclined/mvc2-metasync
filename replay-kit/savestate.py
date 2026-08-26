#!/usr/bin/env python3
"""savestate.py snap|restore|info [slot] — save/restore MvC2's complete deterministic state.

THE CLAIM UNDER TEST: `blk[0 .. 0x33B18)` is the ENTIRE deterministic simulation state, because
that is the single region MvC2 registers with GGPO for rollback. If that is true, copying those
211,736 bytes out and back in is a perfect save state — the match should snap back exactly.

Atomicity: the sim advances on the game's own thread, so a copy taken while it runs can tear.
We suspend every thread in the process for the duration of the copy, then resume. The frame
counter (blk+0x3CC8) is read before and after and must match, which catches a torn read.

⚠ RESTORE WRITES 211,736 BYTES INTO THE LIVE GAME. If the state is inconsistent the game can
crash — recoverable by restarting it, but it IS a write to a running process.

We deliberately do NOT call the game's own save_game_state/load_game_state: they operate on
globals with no locking and would race GGPO and the sim. External RPM/WPM + suspend is safer.
"""
import ctypes
import ctypes.wintypes as w
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mvcmem import EXE, find_pid

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

PROCESS_VM_READ, PROCESS_VM_WRITE, PROCESS_VM_OPERATION = 0x0010, 0x0020, 0x0008
PROCESS_QUERY_INFORMATION = 0x0400
THREAD_SUSPEND_RESUME = 0x0002
TH32CS_SNAPTHREAD = 0x00000004

BLK_PTR, BLKSZ, FC_OFF = EXE + 0xAC6EF0, 0x33B18, 0x3CC8
HERE = os.path.dirname(os.path.abspath(__file__))


class THREADENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ThreadID", w.DWORD),
                ("th32OwnerProcessID", w.DWORD), ("tpBasePri", ctypes.c_long),
                ("tpDeltaPri", ctypes.c_long), ("dwFlags", w.DWORD)]


k32.OpenProcess.restype = w.HANDLE
k32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
k32.OpenThread.restype = w.HANDLE
k32.OpenThread.argtypes = [w.DWORD, w.BOOL, w.DWORD]
k32.ReadProcessMemory.argtypes = [w.HANDLE, w.LPCVOID, w.LPVOID, ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_size_t)]
k32.WriteProcessMemory.argtypes = [w.HANDLE, w.LPVOID, w.LPCVOID, ctypes.c_size_t,
                                   ctypes.POINTER(ctypes.c_size_t)]
k32.CreateToolhelp32Snapshot.restype = w.HANDLE


def threads_of(pid):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    te = THREADENTRY32()
    te.dwSize = ctypes.sizeof(te)
    out = []
    if k32.Thread32First(snap, ctypes.byref(te)):
        while True:
            if te.th32OwnerProcessID == pid:
                out.append(te.th32ThreadID)
            if not k32.Thread32Next(snap, ctypes.byref(te)):
                break
    k32.CloseHandle(snap)
    return out


class Game:
    def __init__(self):
        self.pid = find_pid()
        self.h = k32.OpenProcess(
            PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION | PROCESS_QUERY_INFORMATION,
            False, self.pid)
        if not self.h:
            raise OSError(f"OpenProcess failed {ctypes.get_last_error()} (need admin?)")

    def read(self, addr, n):
        buf = (ctypes.c_char * n)()
        got = ctypes.c_size_t(0)
        if not k32.ReadProcessMemory(self.h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got)):
            raise OSError(f"RPM failed at 0x{addr:x}: {ctypes.get_last_error()}")
        return bytes(buf[:got.value])

    def write(self, addr, data):
        put = ctypes.c_size_t(0)
        if not k32.WriteProcessMemory(self.h, ctypes.c_void_p(addr), data, len(data),
                                      ctypes.byref(put)):
            raise OSError(f"WPM failed at 0x{addr:x}: {ctypes.get_last_error()}")
        return put.value

    def u64(self, a):
        return int.from_bytes(self.read(a, 8), "little")

    def u32(self, a):
        return int.from_bytes(self.read(a, 4), "little")

    def freeze(self):
        held = []
        for tid in threads_of(self.pid):
            th = k32.OpenThread(THREAD_SUSPEND_RESUME, False, tid)
            if th and k32.SuspendThread(th) != 0xFFFFFFFF:
                held.append(th)
            elif th:
                k32.CloseHandle(th)
        return held

    def thaw(self, held):
        for th in held:
            k32.ResumeThread(th)
            k32.CloseHandle(th)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "info"
    slot = sys.argv[2] if len(sys.argv) > 2 else "0"
    path = os.path.join(HERE, f"state{slot}.bin")

    g = Game()
    blk = g.u64(BLK_PTR)
    if not blk:
        sys.exit("no match block (game not in a match?)")

    if cmd == "info":
        print(f"pid {g.pid}  blk 0x{blk:x}  frame {g.u32(blk + FC_OFF)}  "
              f"threads {len(threads_of(g.pid))}")
        return

    if cmd == "snap":
        held = g.freeze()
        try:
            f0 = g.u32(blk + FC_OFF)
            t = time.perf_counter()
            data = g.read(blk, BLKSZ)
            ms = (time.perf_counter() - t) * 1000
            f1 = g.u32(blk + FC_OFF)
        finally:
            g.thaw(held)
        if f0 != f1:
            sys.exit(f"TORN READ: frame moved {f0} -> {f1} while frozen")
        open(path, "wb").write(data)
        print(f"SNAP  frame={f0}  {len(data)} B in {ms:.1f} ms  (froze {len(held)} threads) -> {path}")
        return

    if cmd == "restore":
        if not os.path.exists(path):
            sys.exit(f"no snapshot at {path}")
        data = open(path, "rb").read()
        if len(data) != BLKSZ:
            sys.exit(f"snapshot is {len(data)} B, expected {BLKSZ}")
        want = int.from_bytes(data[FC_OFF:FC_OFF + 4], "little")
        held = g.freeze()
        try:
            before = g.u32(blk + FC_OFF)
            t = time.perf_counter()
            n = g.write(blk, data)
            ms = (time.perf_counter() - t) * 1000
        finally:
            g.thaw(held)
        time.sleep(0.15)
        after = g.u32(blk + FC_OFF)
        print(f"RESTORE  wrote {n} B in {ms:.1f} ms  (froze {len(held)} threads)")
        print(f"  frame was {before}, snapshot held {want}, now {after}")
        print(f"  -> the sim {'JUMPED BACK and is running from the snapshot' if after < before else 'did NOT jump back'}")
        return

    sys.exit("usage: savestate.py snap|restore|info [slot]")


if __name__ == "__main__":
    main()
