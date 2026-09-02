#!/usr/bin/env python3
"""tcw_logger.py -- while the shim captures, log (node matrix -> TCW/TSP/PCW/object hash) for every
drawn System-A node, live, so the capture's world-space draws can be keyed by TEXTURE IDENTITY.

    python tcw_logger.py --out %TEMP%\\rrcap\\tcw_log.json      (Ctrl+C or --seconds N to stop)

Why: a world-space draw in a capture carries the page PIXELS and the node's matrix (CBWorld), but
not which asset the page is. The node's polygon-list object (+0xA0) carries the TCW -- the DC VRAM
address of the texture, a stable identity across sessions -- but that object lives outside the
state block, so a dump cannot have it. Reading it live beside the capture and joining on the
matrix (byte-exact in both) gives TCW -> page. Transient effects (hail, glows, markers) exist for
a few dozen frames, so poll fast and keep every distinct matrix.
"""
import argparse, ctypes, ctypes.wintypes as w, hashlib, json, os, struct, subprocess, sys, time

PROC = 'MarvelVsCapcomFightingCollection'
BLK_PTR_RVA = 0x2EDF560          # DAT_142edf560 - 0x140000000
ALIST_HEADS = 0x2EDE8


def open_game():
    out = subprocess.run(['powershell', '-NoProfile', '-Command', '(Get-Process %s).Id' % PROC],
                         capture_output=True, text=True).stdout.strip().splitlines()
    if not out or not out[0].isdigit():
        return None, None, None
    pid = int(out[0])
    k32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    h = k32.OpenProcess(0x410, False, pid)
    mods = (ctypes.c_void_p * 4)()
    need = w.DWORD()
    psapi.EnumProcessModulesEx(h, mods, ctypes.sizeof(mods), ctypes.byref(need), 3)
    return pid, h, mods[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(os.environ.get('TEMP', '.'), 'rrcap', 'tcw_log.json'))
    ap.add_argument('--seconds', type=float, default=0, help='stop after N seconds (0 = until Ctrl+C)')
    ap.add_argument('--hz', type=float, default=60.0)
    a = ap.parse_args()
    k32 = ctypes.windll.kernel32
    pid, h, base = open_game()
    while not pid:
        time.sleep(1.0)
        pid, h, base = open_game()
    print('[tcw] attached to pid %d, base 0x%X' % (pid, base))

    def rd(addr, n):
        buf = ctypes.create_string_buffer(n)
        got = ctypes.c_size_t()
        return buf.raw if k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got)) else None

    log = {}                 # matrix64 hex -> record
    objs = {}                # object content sha -> {tcw, tsp, pcw, records hex}
    t0 = time.time()
    last_save = t0
    polls = 0
    while True:
        if a.seconds and time.time() - t0 > a.seconds:
            break
        b = rd(base + BLK_PTR_RVA, 8)
        if not b:
            time.sleep(0.5)
            pid, h, base = open_game()
            if not pid:
                continue
            continue
        blk = struct.unpack('<Q', b)[0]
        if not blk:
            time.sleep(0.2)
            continue
        heads = rd(blk + ALIST_HEADS, 16 * 8)
        if not heads:
            time.sleep(0.2)
            continue
        for L in range(5, 14):
            p = struct.unpack_from('<Q', heads, L * 8)[0]
            n = 0
            while p and n < 200:
                nd = rd(p, 0x180)
                if not nd:
                    break
                obj = struct.unpack_from('<Q', nd, 0xA0)[0]
                if nd[0x170] and obj:
                    key = nd[0xA8:0xA8 + 64].hex()
                    if key not in log:
                        hdr = rd(obj + 0x18, 0x50)
                        if hdr:
                            pcw, isp, tsp, tcw = struct.unpack_from('<4I', hdr, 0)
                            size = struct.unpack_from('<i', hdr, 0x4C)[0]
                            pay = rd(obj + 0x18 + 0x50, max(0, min(size, 4096))) if size > 0 else b''
                            sha = hashlib.sha256(hdr + (pay or b'')).hexdigest()[:16]
                            if sha not in objs:
                                objs[sha] = dict(tcw='%08X' % tcw, tsp='%08X' % tsp, pcw='%08X' % pcw, isp='%08X' % isp,
                                                 hdr=hdr.hex(), payload=(pay or b'').hex())
                            log[key] = dict(list=L, tcw='%08X' % tcw, obj=sha, flags=struct.unpack_from('<I', nd, 0xF0)[0],
                                            colour=list(struct.unpack_from('<fff', nd, 0x94)), model=struct.unpack_from('<Q', nd, 0xE8)[0] != 0)
                n += 1
                p = struct.unpack_from('<Q', nd, 0x10)[0]
        polls += 1
        if time.time() - last_save > 5:
            json.dump(dict(matrices=log, objects=objs, polls=polls), open(a.out, 'w'))
            last_save = time.time()
        time.sleep(1.0 / a.hz)
    json.dump(dict(matrices=log, objects=objs, polls=polls), open(a.out, 'w'))
    print('[tcw] %d distinct matrices, %d objects, %d polls -> %s' % (len(log), len(objs), polls, a.out))


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass
