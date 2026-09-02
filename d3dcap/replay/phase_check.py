#!/usr/bin/env python3
"""phase_check.py -- measure the tape's READ PHASE against the render walk, from the tape alone.

    python phase_check.py <tape.json.gz>

The walker writes a node's screen X (+0x124, shipped as fsx) DURING the render; the sim writes
its world X (px) during the update. A row labelled N carries px(N) always, but fsx is either the
placement computed from px(N) (read AFTER the walk) or from px(N-1) (read BEFORE it). The camera
map is `sx = 320 + (px - eyeX)` (agent 0.3.23 note, sub-pixel exact on drawn objects), so for a
MOVING fighter the residual  fsx - (320 + px(N) - eyeX(N))  is ~0 in one case and ~ -vx in the
other. Histogram both hypotheses per row; a v3 (random-phase) tape shows a MIX, an edge-synced v4
tape shows ONE population -- and which one it is tells the renderer how to pair frames.
"""
import base64, gzip, json, struct, sys
from collections import Counter


def load(path):
    raw = open(path, 'rb').read()
    if raw[:2] == b'\x1f\x8b':
        raw = gzip.decompress(raw)
    return json.loads(raw)


def main():
    t = load(sys.argv[1])
    cols = [c.strip() for c in t['schema'].strip('[]').split(',')]
    C = {n: i for i, n in enumerate(cols)}
    rows = {int(r[C['frame']]): r for r in t['frames']}
    stride = int(t.get('nodes_stride', 44))
    nb = gzip.decompress(base64.b64decode(t['nodes']))
    fsx = {}                      # frame -> {slot: fsx}
    off = 0
    while off + 6 <= len(nb):
        fr, n = struct.unpack_from('<IH', nb, off); off += 6
        d = {}
        for _ in range(n):
            kind, slot = nb[off], nb[off + 1]
            if kind == 0:
                d[slot] = struct.unpack_from('<f', nb, off + 24)[0]
            off += stride
        fsx[fr] = d
    same = prev = neither = 0
    res_same, res_prev = Counter(), Counter()
    for fr, d in fsx.items():
        r, rp = rows.get(fr), rows.get(fr - 1)
        if not r or not rp:
            continue
        for slot, sx in d.items():
            px, pxp = r[C['px[6]']][slot], rp[C['px[6]']][slot]
            ex, exp = r[C['eyeX']], rp[C['eyeX']]
            if abs(px - pxp) < 0.5:
                continue                              # not moving: the two hypotheses coincide
            a = sx - (320 + px - ex)
            b = sx - (320 + pxp - exp)
            res_same[round(a, 1)] += 1; res_prev[round(b, 1)] += 1
            if abs(a) < 0.51 and abs(b) >= 0.51: same += 1
            elif abs(b) < 0.51 and abs(a) >= 0.51: prev += 1
            else: neither += 1
    tot = same + prev + neither
    print('moving-fighter rows: %d   fsx matches px(N): %d (%.1f%%)   matches px(N-1): %d (%.1f%%)   neither: %d'
          % (tot, same, 100.0 * same / max(1, tot), prev, 100.0 * prev / max(1, tot), neither))
    print('residual vs px(N)  :', res_same.most_common(6))
    print('residual vs px(N-1):', res_prev.most_common(6))
    if tot and same and prev and min(same, prev) > 0.05 * tot:
        print('VERDICT: MIXED phase -- reads land before AND after the walk (random-phase sampling)')
    elif tot:
        print('VERDICT: single phase -- fsx is the placement of %s' % ('THIS frame' if same >= prev else 'the PREVIOUS frame'))


if __name__ == '__main__':
    sys.exit(main())
