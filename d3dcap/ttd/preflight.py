#!/usr/bin/env python3
"""preflight.py -- can Microsoft TTD attach to this process?  Read-only checks, no elevation, exit 0 = go.

Why: TTD's recorder (TTDRecordCPU.dll) validates the ntdll syscall stubs it needs (GetNtdllAPIAddresses). When an
export such as ntdll!NtResumeThread starts with a JMP (E9 rel32) instead of the stub bytes (4C 8B D1 B8 imm32 ...),
initialization fails with 'ErrorGettingNtdllApiAddresses ... failed for NtResumeThread' / 'Injection by thread was
incomplete. Status: 2156436999' (seen 2026-09-03, runs 20260903-000941 and 001536). Owner of the Nt* hooks (CONFIRMED by
following the JMP -> push-ret stubs): the game exe's own runtime/protection layer (handlers exe+0x311ddf0..+0x3124720 in
the RWX section at VA 0x03092000). The Steam overlay (gameoverlayrenderer64.dll) owns only the LdrLoadDll hook. Hence
-attach is impossible on this title; record.ps1 -Launch (TTD starts the exe) is the path. See docs/TTD-FRAME-TRACE.md s0.

Checks: (1) overlay / injector modules loaded, (2) ntdll exports TTD needs are unhooked (live bytes == this process'
bytes; ntdll shares one base per boot), (3) no leftover TTD DLLs (a failed attach can leave the process 'under tracing
control'), (4) no debugger attached, (5) mitigation policies TTD cannot record under (DynamicCode prohibit).

  python preflight.py [--pid N | --proc NAME] [--json out.json]
"""
import argparse
import ctypes
import ctypes.wintypes as w
import json
import subprocess
import sys

k = ctypes.windll.kernel32
psapi = ctypes.windll.psapi
nt = ctypes.windll.ntdll
k.OpenProcess.restype = w.HANDLE
k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
k.ReadProcessMemory.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k.GetProcessMitigationPolicy.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t]
psapi.EnumProcessModulesEx.argtypes = [w.HANDLE, ctypes.POINTER(ctypes.c_void_p), w.DWORD, w.LPDWORD, w.DWORD]
psapi.GetModuleFileNameExW.argtypes = [w.HANDLE, ctypes.c_void_p, w.LPWSTR, w.DWORD]

# ntdll exports the TTD recorder resolves/uses (NtResumeThread is the one it reports first)
NT_EXPORTS = ("NtResumeThread NtSuspendThread NtGetContextThread NtSetContextThread NtCreateThreadEx NtCreateThread "
              "NtProtectVirtualMemory NtAllocateVirtualMemory NtFreeVirtualMemory NtQueryInformationThread "
              "NtQueryInformationProcess NtWriteVirtualMemory NtReadVirtualMemory NtMapViewOfSection NtUnmapViewOfSection "
              "NtOpenThread NtTerminateThread NtContinue NtQueueApcThread NtSetInformationThread NtClose NtWaitForSingleObject "
              "NtDelayExecution NtCreateSection NtQueryVirtualMemory NtFlushInstructionCache NtRaiseException NtSetEvent "
              "NtCreateEvent NtCreateFile NtOpenFile NtDuplicateObject NtWaitForMultipleObjects NtDeviceIoControlFile "
              "LdrLoadDll LdrGetProcedureAddress KiUserApcDispatcher KiUserExceptionDispatcher").split()
INJECTORS = ("gameoverlayrenderer64.dll", "gameoverlayrenderer.dll", "easyanticheat", "battleye", "beclient", "rtsshooks", "rivatuner",
             "discordhook", "reshade", "d3dcap.dll", "ttdrecordcpu.dll", "ttdloader.dll", "ttdliverecorder.dll")
SEP = chr(92)


def find_pid(name):
    out = subprocess.check_output(["tasklist", "/FI", "IMAGENAME eq %s.exe" % name, "/FO", "CSV", "/NH"]).decode(errors="replace")
    for line in out.splitlines():
        if line.startswith('"'):
            return int(line.split('","')[1])
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--proc", default="MarvelVsCapcomFightingCollection")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    pid = a.pid or find_pid(a.proc)
    if not pid:
        print("[preflight] process %s.exe not running" % a.proc)
        return 2
    h = k.OpenProcess(0x10 | 0x400, False, pid)
    if not h:
        print("[preflight] OpenProcess(%d) failed" % pid)
        return 2

    def rd(addr, n):
        b = ctypes.create_string_buffer(n)
        g = ctypes.c_size_t()
        return b.raw[: g.value] if k.ReadProcessMemory(h, ctypes.c_void_p(addr), b, n, ctypes.byref(g)) else None

    mods = (ctypes.c_void_p * 2048)()
    need = w.DWORD()
    psapi.EnumProcessModulesEx(h, mods, ctypes.sizeof(mods), ctypes.byref(need), 3)
    names = []
    for i in range(need.value // 8):
        b = ctypes.create_unicode_buffer(1024)
        psapi.GetModuleFileNameExW(h, mods[i], b, 1024)
        names.append(b.value)
    res = {"pid": pid, "modules": len(names), "blockers": [], "warnings": [], "injectors": [], "hooked": [], "ttd_loaded": []}
    for p in names:
        low = p.lower().rsplit(SEP, 1)[-1]
        if any(x in low for x in INJECTORS):
            (res["ttd_loaded"] if low.startswith("ttd") else res["injectors"]).append(p)
    for f in NT_EXPORTS:
        try:
            addr = ctypes.cast(getattr(nt, f), ctypes.c_void_p).value
        except AttributeError:
            continue
        me = ctypes.string_at(addr, 16)          # 16 bytes: the syscall stub 4C 8B D1 B8 imm32 F6 04 25 ... vs E9 rel32
        live = rd(addr, 16)
        if live is not None and live != me:
            res["hooked"].append({"export": "ntdll!" + f, "live": live.hex(), "expected": me.hex(), "jmp": live[0] == 0xE9})
    dbg = w.BOOL()
    k.CheckRemoteDebuggerPresent(h, ctypes.byref(dbg))
    res["debugger"] = bool(dbg.value)
    v = ctypes.c_uint64(0)
    k.GetProcessMitigationPolicy(h, 2, ctypes.byref(v), 8)
    res["dynamic_code_policy"] = v.value
    v = ctypes.c_uint64(0)
    k.GetProcessMitigationPolicy(h, 7, ctypes.byref(v), 8)
    res["cfg_policy"] = v.value

    nrt = [x for x in res["hooked"] if x["export"] == "ntdll!NtResumeThread"]
    if nrt and nrt[0]["jmp"]:
        res["blockers"].append("ntdll!NtResumeThread starts with E9 (JMP) in the target: live %s vs stub %s -- this is exactly what TTD's GetNtdllAPIAddresses() rejects (run 20260903-000941 / 001536)" % (nrt[0]["live"], nrt[0]["expected"]))
    if res["hooked"]:
        res["blockers"].append("%d ntdll export(s) are hooked (JMP patched): %s -- TTD's GetNtdllAPIAddresses() will fail"
                               % (len(res["hooked"]), ", ".join(x["export"] for x in res["hooked"][:6])))
    ov = [p for p in res["injectors"] if "overlay" in p.lower()]
    if ov:
        res["blockers"].append("Steam in-game overlay is loaded (%s) -- it installs the ntdll hooks" % ov[0])
    for p in res["injectors"]:
        if "overlay" not in p.lower():
            res["warnings"].append("injector/hook DLL loaded: %s" % p)
    if res["ttd_loaded"]:
        res["blockers"].append("TTD DLLs already in the process (%s) -- a previous attach left it 'under tracing control'; restart the game"
                               % ", ".join(res["ttd_loaded"]))
    if res["debugger"]:
        res["blockers"].append("a debugger is attached")
    if res["dynamic_code_policy"] & 1:
        res["blockers"].append("ProcessDynamicCodePolicy.ProhibitDynamicCode is set (ACG) -- TTD cannot emulate under it")

    for b in res["blockers"]:
        print("[preflight] BLOCKER: " + b)
    for wv in res["warnings"]:
        print("[preflight] warning: " + wv)
    print("[preflight] pid %d: %d modules, %d hooked exports, injectors=%s, ttd=%s, debugger=%s"
          % (pid, len(names), len(res["hooked"]), res["injectors"] or "none", res["ttd_loaded"] or "none", res["debugger"]))
    if res["blockers"]:
        print("[preflight] REMEDY (primary): the Nt* hooks belong to the exe's own runtime layer (handlers at exe+0x311ddf0.., RWX section")
        print("            0x03092000) so -attach cannot work on this title. Quit the game and let TTD start it:")
        print("              powershell -NoProfile -ExecutionPolicy Bypass -File C:/Users/trist/projects/mvc-live-skins-quarters/d3dcap/ttd/record.ps1 -Launch")
        print("            Also advisable: Steam > Library > game > Properties > General > untick 'Enable the Steam Overlay while in-game'")
        print("            (removes the LdrLoadDll hook only; global switch: Steam > Settings > In Game).")
        print("            If TTD DLLs are listed: restart the game. If another injector is listed: close it (RTSS/Discord/ReShade) and relaunch.")
        print("            VERIFY after relaunch (must print nothing for the overlay and exit 0):")
        print("              powershell -NoProfile -Command \"(Get-Process MarvelVsCapcomFightingCollection).Modules | Where-Object { $_.ModuleName -match 'overlay' } | Select-Object ModuleName,FileName\"")
        print("              python C:/Users/trist/projects/mvc-live-skins-quarters/d3dcap/ttd/preflight.py")
    if a.json:
        json.dump(res, open(a.json, "w"), indent=1)
    return 1 if res["blockers"] else 0


if __name__ == "__main__":
    sys.exit(main())
