#!/usr/bin/env python3
"""blk_delta.py -- SUPERGUN SERVER ARCH lane (Q2): measure the REAL per-frame WRITE SET of the MvC2 tick.

Q2 asks whether a central authoritative server could stream STATE deltas instead of inputs. That is only
viable if the per-frame delta is small. docs/FRAME-READSET.md (iii) measured 120 changed blk bytes on ONE
IDLE tick by p-code emulation; the combat-frame write set was never measured. This script measures it
directly from the receipt runner's per-tick blk dumps (rr_runner --dump-every 1), which already exist for
a 300-tick real-input run.

  python blk_delta.py --dir <dir with blk_tNNN.bin> [--json out.json] [--csv out.csv]

Reports, per frame: differing bytes, contiguous runs, a run-length delta encoding size (u32 off + u16 len),
a 16 B block encoding size, and zlib-compressed sizes of both. Plus the region attribution of the changed
bytes (blk field groups from docs/FRAME-READSET.md 3.1) and the distribution over the run.

BYOR: reads game-derived dumps from %TEMP%; writes only aggregate numbers.
"""
import argparse, glob, json, os, re, zlib, statistics as st

# blk region map -- docs/FRAME-READSET.md s3.1 + docs/RE-METHOD.md block map
REGIONS = [
    (0x00000, 0x01000, "matrix stack"),
    (0x01000, 0x03C66, "render-list records (0x38 stride)"),
    (0x03C66, 0x03CB8, "input array"),
    (0x03CB8, 0x03DB8, "G (frame clock / globals)"),
    (0x03DB8, 0x06908, "fighters 6 x 0x738"),
    (0x06908, 0x06DD8, "stage/camera"),
    (0x06DD8, 0x2EDF0, "object pool nodes (0x280 stride)"),
    (0x2EDF0, 0x324D0, "pool bookkeeping / draw lists"),
    (0x324D0, 0x32500, "draw counts"),
    (0x32500, 0x33B18, "battle state"),
]

def region_of(off):
    for lo, hi, name in REGIONS:
        if lo <= off < hi:
            return name
    return "beyond"

def runs_of(a, b):
    """contiguous differing byte runs between two equal-length buffers"""
    out = []
    n = len(a)
    i = 0
    while i < n:
        if a[i] != b[i]:
            j = i + 1
            while j < n and a[j] != b[j]:
                j += 1
            out.append((i, j - i))
            i = j
        else:
            i += 1
    return out

def coalesce(runs, gap):
    """merge runs separated by < gap identical bytes (a real encoder would)"""
    if not runs:
        return []
    out = [list(runs[0])]
    for off, ln in runs[1:]:
        if off - (out[-1][0] + out[-1][1]) < gap:
            out[-1][1] = off + ln - out[-1][0]
        else:
            out.append([off, ln])
    return [tuple(x) for x in out]

def blocks_of(a, b, bs):
    out = []
    for off in range(0, len(a), bs):
        if a[off:off+bs] != b[off:off+bs]:
            out.append(off)
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--json')
    ap.add_argument('--csv')
    ap.add_argument('--gap', type=int, default=8, help='coalesce runs separated by fewer than N same bytes')
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(a.dir, 'blk_t*.bin')))
    if len(files) < 2:
        raise SystemExit('need >= 2 blk_tNNN.bin dumps in %s' % a.dir)
    prev = open(files[0], 'rb').read()
    rows = []
    reg_bytes = {}
    reg_frames = {}
    for f in files[1:]:
        cur = open(f, 'rb').read()
        k = int(re.search(r'blk_t(\d+)', os.path.basename(f)).group(1))
        r = runs_of(prev, cur)
        rc = coalesce(r, a.gap)
        diff = sum(l for _, l in r)
        # run-length delta record: u32 offset + u16 len + payload
        enc = sum(6 + l for _, l in rc)
        payload = b''.join(cur[o:o+l] for o, l in rc)
        b16 = blocks_of(prev, cur, 16)
        b64 = blocks_of(prev, cur, 64)
        pay16 = b''.join(cur[o:o+16] for o in b16)
        seen = set()
        for o, l in r:
            for name in {region_of(o), region_of(o + l - 1)}:
                seen.add(name)
            reg_bytes[region_of(o)] = reg_bytes.get(region_of(o), 0) + l
        for name in seen:
            reg_frames[name] = reg_frames.get(name, 0) + 1
        rows.append(dict(tick=k, diff=diff, runs=len(r), cruns=len(rc), enc=enc,
                         enc_z=len(zlib.compress(payload, 6)) + 6 * len(rc),
                         b16=len(b16) * 16, b16_idx=len(b16),
                         b16_z=len(zlib.compress(pay16, 6)) + 4 * len(b16),
                         b64=len(b64) * 64,
                         whole_z=len(zlib.compress(bytes(x ^ y for x, y in zip(prev, cur)), 6)))) 
        prev = cur
    def stats(key):
        v = sorted(x[key] for x in rows)
        n = len(v)
        return dict(min=v[0], p50=v[n//2], p90=v[int(n*0.9)], p99=v[min(n-1,int(n*0.99))], max=v[-1],
                    mean=round(sum(v)/n, 1))
    summary = {k: stats(k) for k in ('diff','runs','cruns','enc','enc_z','b16','b16_idx','b16_z','b64','whole_z')}
    summary['frames'] = len(rows)
    summary['region_bytes_total'] = dict(sorted(reg_bytes.items(), key=lambda x: -x[1]))
    summary['region_frames'] = dict(sorted(reg_frames.items(), key=lambda x: -x[1]))
    summary['worst_frames_by_enc'] = sorted(rows, key=lambda r: -r['enc'])[:12]
    print(json.dumps(summary, indent=1))
    for k in ('diff','enc','enc_z','b16','b16_z','whole_z'):
        s = summary[k]
        print('%-8s min %7d  p50 %7d  p90 %7d  p99 %7d  max %7d  mean %9.1f  |  at 60 Hz p50 %8.1f KB/s  max %8.1f KB/s'
              % (k, s['min'], s['p50'], s['p90'], s['p99'], s['max'], s['mean'], s['p50']*60/1000.0, s['max']*60/1000.0))
    if a.json:
        json.dump(dict(summary=summary, rows=rows), open(a.json, 'w'), indent=1)
    if a.csv:
        with open(a.csv, 'w') as fh:
            fh.write(','.join(rows[0].keys()) + '\n')
            for r in rows:
                fh.write(','.join(str(v) for v in r.values()) + '\n')

if __name__ == '__main__':
    main()
