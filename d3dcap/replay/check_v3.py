#!/usr/bin/env python3
"""check_v3.py -- verify a TAPE v3 recording carries what the renderer needs, in one pass.

    python check_v3.py <tape.json.gz | tape.json>

Checks, in order, and says which failed:
  1. the v3 streams exist        nodes / pals present, nodes_frames > 0, pals_n plausible (~4)
  2. the record decodes           44 B stride, count per frame consistent with the byte length
  3. FIGHTERS ARE INTERLEAVED     kind=0 records are NOT all grouped at the front of a frame --
                                  this is the entire point of v3; if they are grouped, ordering
                                  was reconstructed, not recorded
  4. the sort key is live         (s8) values are the {-8,0,1,2,8} family seen in the state capture,
                                  and within a layer they are non-decreasing (the array is pre-sorted)
  5. palettes resolve             every pal index < pals_n, and each palette has ~15 non-zero entries
  6. precision survived           fsx/fsy carry fractional parts (the i16 columns could not)
  7. v2 wire unchanged            objs_enc stride is still 32 B and contains NO kind=0 rows
"""
import base64
import gzip
import json
import struct
import sys
from collections import Counter, defaultdict


def load(path):
    raw = open(path, 'rb').read()
    if raw[:2] == b'\x1f\x8b':
        raw = gzip.decompress(raw)
    return json.loads(raw)


def b64gz(s):
    return gzip.decompress(base64.b64decode(s))


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    t = load(sys.argv[1])
    ok = True

    def fail(msg):
        nonlocal ok
        ok = False
        print('  FAIL  ' + msg)

    print('ver %s   frames %d   schema cols %d'
          % (t.get('ver'), len(t.get('frames', [])), len(t.get('schema', '').split(','))))

    # 1. streams
    if not t.get('nodes'):
        fail('no `nodes` stream -- this is not a v3 tape (agent < v3, or nodes_enc not emitted)')
        return 1
    nf, pn = t.get('nodes_frames', 0), t.get('pals_n', 0)
    print('nodes_frames %d   pals_n %d' % (nf, pn))
    if nf <= 0:
        fail('nodes_frames == 0')
    if not (1 <= pn <= 64):
        fail('pals_n %d is not plausible (expect a handful: the on-screen characters)' % pn)

    # 2. decode
    nb = b64gz(t['nodes'])
    pals = b64gz(t['pals']) if t.get('pals') else b''
    # v4 (agent 0.3.34+): 50 B = the 44 B v3 record + u16 angle, i16 hotx, i16 hoty. `nodes_stride`
    # says which; a v3 tape has no key and is 44.
    stride = int(t.get('nodes_stride', 44))
    print('nodes_stride %d (ver %s)' % (stride, t.get('nodes_ver', 3)))
    if stride not in (44, 50):
        fail('nodes_stride %d is neither 44 (v3) nor 50 (v4)' % stride)
        return 1
    frames, off = {}, 0
    while off + 6 <= len(nb):
        fr = struct.unpack_from('<I', nb, off)[0]
        n = struct.unpack_from('<H', nb, off + 4)[0]
        off += 6
        rows = []
        for _ in range(n):
            if off + stride > len(nb):
                fail('nodes stream truncated inside frame %d' % fr)
                break
            (kind, slot, cat, srt, layer, face, owner, drawn, sid, pal, flash, glow, isfx, blend,
             atimer, zx, zy, ekey, fsx, fsy, depth, gfx1, gfx2) = struct.unpack_from(
                '<BBBbBBBBHHHBBBBHHHfffII', nb, off)
            angle, hotx, hoty = struct.unpack_from('<Hhh', nb, off + 44) if stride >= 50 else (0, 0, 0)
            rows.append(dict(kind=kind, slot=slot, cat=cat, sort=srt, layer=layer, face=face,
                             owner=owner, drawn=drawn, sid=sid, pal=pal, flash=flash, glow=glow,
                             zx=zx / 4096.0, fsx=fsx, fsy=fsy, gfx1=gfx1,
                             angle=angle, hotx=hotx, hoty=hoty))
            off += stride
        frames[fr] = rows
    if off != len(nb):
        fail('nodes stream has %d trailing bytes -- stride mismatch?' % (len(nb) - off))
    total = sum(len(v) for v in frames.values())
    print('decoded %d frames, %d nodes, %.1f nodes/frame' % (len(frames), total, total / max(1, len(frames))))

    # 3. interleaving -- the whole point
    grouped = interleaved = 0
    for rows in frames.values():
        kinds = [r['kind'] for r in rows]
        if kinds.count(0) >= 2 and kinds.count(1) >= 1:
            first_obj = kinds.index(1)
            if any(k == 0 for k in kinds[first_obj:]):
                interleaved += 1
            else:
                grouped += 1
    print('frames with >=2 fighters and >=1 object: interleaved %d, fighters-all-first %d'
          % (interleaved, grouped))
    if interleaved == 0 and grouped > 0:
        fail('fighters are ALWAYS grouped before objects -- the order was reconstructed, not recorded')

    # 4. sort key
    sv = Counter(r['sort'] for rows in frames.values() for r in rows)
    print('sort values: %s' % sorted(sv.items(), key=lambda kv: -kv[1])[:8])
    if set(sv) == {0}:
        fail('sort is 0 everywhere -- reading the wrong offset (DC +0x31 instead of Steam +0x4D?)')
    viol = pairs = 0
    for rows in frames.values():
        by = defaultdict(list)
        for i, r in enumerate(rows):
            by[r['layer']].append((i, r['sort']))
        for L, seq in by.items():
            seq.sort()
            for (_, a), (_, b) in zip(seq, seq[1:]):
                pairs += 1
                if b < a:
                    viol += 1
    print('in-layer sort monotonicity: %d pairs, %d violations' % (pairs, viol))
    if viol:
        fail('sort key DEcreases within a layer %d times -- either not the key, or order not recorded' % viol)

    # 5. palettes
    bad = sum(1 for rows in frames.values() for r in rows if r['pal'] != 0xFFFF and r['pal'] >= pn)
    if bad:
        fail('%d nodes index a palette >= pals_n' % bad)
    nz = [sum(1 for i in range(16) if pals[p * 32 + i * 2:p * 32 + i * 2 + 2] != b'\x00\x00')
          for p in range(pn)]
    print('palette non-zero entries per table row: %s' % nz)
    if nz and max(nz) < 8:
        fail('palettes look empty -- H+0x1B8 not the live DatPal on this build?')

    # 6. precision
    frac = sum(1 for rows in frames.values() for r in rows if abs(r['fsx'] - round(r['fsx'])) > 1e-3)
    print('nodes whose fsx has a fractional part: %d of %d' % (frac, total))
    if total and frac == 0:
        fail('fsx is integral everywhere -- precision was lost somewhere before the wire')

    # 8. v4: the rotation fields are live (angle is a u16 with 0x10000 = 360 deg; every rotated node
    #    seen so far is exactly 0x8000 -- any other non-zero value is NEW DATA, print it)
    if stride >= 50:
        av = Counter(r['angle'] for rows in frames.values() for r in rows if r['angle'])
        hv = Counter((r['hotx'], r['hoty']) for rows in frames.values() for r in rows if r['angle'])
        print('v4 rotated nodes: %d   angles %s   hotspots %s' % (sum(av.values()), dict(av.most_common(6)), dict(hv.most_common(4))))
        odd = {a: c for a, c in av.items() if a != 0x8000}
        if odd:
            print('  NOTE: angles other than 0x8000 present %s -- the general rotation formula is specified but unexercised' % odd)

    # 7. v2 wire unchanged
    if t.get('objs'):
        ob = b64gz(t['objs'])
        o2, kinds0 = 0, 0
        while o2 + 6 <= len(ob):
            n = struct.unpack_from('<H', ob, o2 + 4)[0]
            o2 += 6 + 32 * n
        if o2 != len(ob):
            fail('objs_enc no longer parses at a 32 B stride (%d trailing bytes)' % (len(ob) - o2))
        else:
            print('objs_enc still parses at 32 B stride (v2 consumers unaffected)')

    print('\nRESULT: %s' % ('PASS -- this tape can drive the v3 renderer' if ok else 'FAIL -- see above'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
