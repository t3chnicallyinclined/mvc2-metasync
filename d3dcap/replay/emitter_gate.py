#!/usr/bin/env python3
"""emitter_gate.py -- diff the EMITTER's output against Steam's own pixels, on the same frame.

    python emitter_gate.py frame_5630.pack
    python emitter_gate.py frame_5630.pack --png gate_5630.png

Runs on packs already on disk. No live session, no tape, no game state.

WHY THIS IS THE GATE THAT MATTERS
---------------------------------
Every emitter bug so far was found by looking at a picture and saying "that's wrong". That works
until it doesn't: a cape drawing through a body is obvious, a part 8 px too low is not, and "looks
right" has already been wrong three times in this program (the 0.685 IoU null, the band-reversal
1.0000, the "content is never mirrored" retraction).

This closes the loop with a number. It reconstructs, for one captured frame:
  * TRUTH   -- what Steam actually drew, straight from its own indexed draw calls and texture pages;
  * EMITTER -- the same body rebuilt from the offline atlas through the placement law.
Both land in the same native-pixel raster, and the diff is per-pixel.

⭐ It needs NO game state. The character comes from byte-exact tile matching and the sel from the
origin solve (asm_ident), so every capture ever taken is usable as an oracle.

⚠⚠ THE V AXIS IS INVERTED, AND GETTING THIS WRONG COSTS A DAY
--------------------------------------------------------------
Read straight off a captured quad's vertices:

    screen y 119.07  ->  texel v 8.0
    screen y 127.07  ->  texel v 0.0

V DECREASES as screen y increases. The index pages are stored BOTTOM-UP and Steam samples them with
inverted V, so the two cancel and the rendered frame is upright. Three separate confusions all
reduce to this one fact:
  * a captured page matches the offline atlas block BYTE-EXACT -- because both are stored flipped;
  * assembling a part from the atlas needs a FULL VERTICAL FLIP to look right;
  * an earlier "the 32-row tile BANDS are reversed" result scored 1.0000 and was still the wrong
    DRAWING rule -- it compared two representations that share the flip, so the within-tile half
    cancelled and only the band-order half survived.
**Comparing two representations that share a defect cannot reveal that defect.** The only reference
that settled it was Steam's rendered framebuffer, which nothing of ours had touched.
"""
import argparse
import glob
import json
import os
import struct
import sys
from collections import Counter, defaultdict

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
DEF_ATLAS = r'C:\Users\trist\projects\maplecast-flycast\web\test-atlas\chars'
SX, SY = 192.0, 112.0


def load_pack(path):
    f = open(path, 'rb')
    if f.read(4) != b'RRPK':
        sys.exit('not a pack: %s' % path)
    n = struct.unpack('<I', f.read(4))[0]
    man = json.loads(f.read(n))
    body = f.read()
    return man, (lambda b: body[b['off']:b['off'] + b['len']])


def indexed_quads(man, B):
    """Every character quad: screen rect, the texel rect it samples, and its mirror flag."""
    vb, ib = B(man['vb']), B(man['ib'])
    IDX = struct.unpack('<%dI' % (len(ib) // 4), ib)
    out = []
    for d in man['draws']:
        if d['psVariant'] != 'indexed' or not d['tex'][0]:
            continue
        st, vo = d['stride'], d['voff']
        ii = sorted(set(IDX[d['firstIndex']:d['firstIndex'] + d['indexCount']]))
        # ⚠ TEXEL COORDS SCALE BY THE PAGE'S OWN SIZE. Character bodies are all 32x32 pages, so
        # `* 32` was right on every frame that scored 100%; the scale-walker records (bolts, drones,
        # the sid-0x8000 poses) sit on 64x32 / 128x16 / 32x256 / 8x8 pages and the reference
        # itself was sliced wrong there -- HALF the super-frame residual was the TRUTH, not us.
        tw, th = man['textures'][d['tex'][0]]['w'], man['textures'][d['tex'][0]]['h']
        P, U = [], []
        for i in ii:
            x, y = struct.unpack_from('<2f', vb, vo + i * st)
            u, v = struct.unpack_from('<2f', vb, vo + i * st + 32)
            P.append(((x + 1) * SX, (1 - y) * SY))
            U.append((u * tw, v * th))
        z = struct.unpack_from('<f', vb, vo + ii[0] * st + 8)[0]
        gx = [p[0] for p in P]
        # mirror: does u DECREASE as screen x increases?  vflip: does v INCREASE with screen y?
        # (normal winding has the screen TOP at the HIGHER v; a 180-degree rotated quad -- SH4
        # rotation path, +0x148 == 0x8000 -- reverses BOTH windings)
        lo = min(range(len(P)), key=lambda j: P[j][0])
        hi = max(range(len(P)), key=lambda j: P[j][0])
        ylo = min(range(len(P)), key=lambda j: P[j][1])
        yhi = max(range(len(P)), key=lambda j: P[j][1])
        out.append(dict(
            i=d['i'], z=z, page=d['tex'][0], pal=d['tex'][1],
            sx=min(gx), sy=min(p[1] for p in P),
            w=max(gx) - min(gx), h=max(p[1] for p in P) - min(p[1] for p in P),
            u0=min(u for u, v in U), u1=max(u for u, v in U),
            v0=min(v for u, v in U), v1=max(v for u, v in U),
            mir=U[hi][0] < U[lo][0], vflip=U[yhi][1] > U[ylo][1],
            P=P, UV=[(u / tw, v / th) for u, v in U]))
    out.sort(key=lambda q: -q['z'])          # decreasing z == later == on top; paint back first
    return out


def raster_truth(man, B, quads):
    """What Steam drew, from its own pages. The ONE reference nothing of ours has touched.

    ⚠ EVERY QUAD IS RASTERISED FROM ITS OWN FOUR VERTICES. The first version pasted the page
    sub-rect into the quad's axis-aligned BOUNDING BOX -- exact for the axis-aligned quads that
    bodies are made of, and WRONG for a rotated quad: the arm of a 28-degree rocket punch came out
    as unrotated tiles smeared over their bounding boxes, and the gate then blamed the renderer
    (76-94% on frames whose rotated tile CENTRES our placement matched to 0.1 px). Here the
    screen->UV map of each quad is solved from its vertices (a rotated/mirrored rectangle is an
    affine map) and every pixel centre in the bounding box is inverse-mapped and point-sampled --
    the same thing the GPU does with point sampling, up to its edge coverage rule. Axis-aligned
    quads reduce to exactly the old paste."""
    T = man['textures']
    x0 = min(q['sx'] for q in quads)
    y0 = min(q['sy'] for q in quads)
    W = int(round(max(q['sx'] + q['w'] for q in quads) - x0))
    H = int(round(max(q['sy'] + q['h'] for q in quads) - y0))
    img = np.zeros((H, W), np.uint8)
    for q in quads:
        t = T[q['page']]
        page = np.frombuffer(B(t), np.uint8).reshape(t['h'], t['w'])
        P, UV = q['P'], q['UV']
        if len(P) < 3:
            continue
        # affine screen->uv from three non-collinear vertices (least squares over all four)
        A = np.array([[px, py, 1.0] for px, py in P])
        try:
            M, *_ = np.linalg.lstsq(A, np.array(UV), rcond=None)      # (3,2): [u v] = [x y 1] @ M
        except np.linalg.LinAlgError:
            continue
        xs = [px for px, _ in P]; ys = [py for _, py in P]
        r0, r1 = max(0, int(np.floor(min(ys) - y0))), min(H, int(np.ceil(max(ys) - y0)) + 1)
        c0, c1 = max(0, int(np.floor(min(xs) - x0))), min(W, int(np.ceil(max(xs) - x0)) + 1)
        if r1 <= r0 or c1 <= c0:
            continue
        yy, xx = np.mgrid[r0:r1, c0:c1]
        X = xx + 0.5 + x0; Y = yy + 0.5 + y0                            # pixel centres, native
        u = X * M[0, 0] + Y * M[1, 0] + M[2, 0]
        v = X * M[0, 1] + Y * M[1, 1] + M[2, 1]
        # inside the quad == inside the quad's own UV rectangle
        ulo, uhi = min(a for a, _ in UV), max(a for a, _ in UV)
        vlo, vhi = min(b for _, b in UV), max(b for _, b in UV)
        eps = 1e-6
        inside = (u >= ulo - eps) & (u < uhi - eps) & (v >= vlo - eps) & (v < vhi - eps)
        tu = np.clip(np.floor(u * t['w']).astype(np.int64), 0, t['w'] - 1)
        tv = np.clip(np.floor(v * t['h']).astype(np.int64), 0, t['h'] - 1)
        vals = np.zeros_like(tu, dtype=np.uint8)
        vals[inside] = page[tv[inside], tu[inside]]
        m = vals > 0                                                  # index 0 is the transparent entry
        img[r0:r1, c0:c1][m] = vals[m]
    return img, x0, y0


def raster_emitter(atlas_dir, ch, sel, ox, oy, mir, ref_shape, x0, y0, forward=False):
    """The same body rebuilt from the offline atlas through the placement law."""
    A = np.array(Image.open(os.path.join(atlas_dir, ch + '_idx.png')))[:, :, 0]
    asm = json.load(open(os.path.join(atlas_dir, ch + '_asm.json')))
    parts, recs = asm['parts'], asm['assemblies'].get(str(sel))
    if not recs:
        return None
    H, W = ref_shape
    img = np.zeros((H, W), np.uint8)
    for rec in (recs if forward else reversed(recs)):
        p = parts.get(str(rec['part']))
        if not p:
            continue
        bmp = A[p['y']:p['y'] + p['h'], p['x']:p['x'] + p['w']][::-1]   # pages are bottom-up
        left = (ox + rec['dx'] - p['w']) if mir else (ox - rec['dx'])
        top = oy + rec['dy']
        if mir:
            bmp = bmp[:, ::-1]
        r0 = int(round(top - y0))
        c0 = int(round(left - x0))
        rs, re = max(0, r0), min(H, r0 + p['h'])
        cs, ce = max(0, c0), min(W, c0 + p['w'])
        if re <= rs or ce <= cs:
            continue
        sub = bmp[rs - r0:re - r0, cs - c0:ce - c0]
        m = sub > 0
        img[rs:re, cs:ce][m] = sub[m]
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pack')
    ap.add_argument('--atlas', default=DEF_ATLAS)
    ap.add_argument('--png', default=None, help='write a side-by-side truth|emitter|diff image')
    ap.add_argument('--forward-records', action='store_true')
    a = ap.parse_args()

    man, B = load_pack(a.pack)
    quads = indexed_quads(man, B)
    if not quads:
        sys.exit('no indexed (character) draws in %s' % a.pack)
    print('%s: %d character quads' % (os.path.basename(a.pack), len(quads)))

    truth, x0, y0 = raster_truth(man, B, quads)
    cov = (truth > 0).sum()
    print('truth raster %dx%d, %d non-transparent pixels' % (truth.shape[1], truth.shape[0], cov))

    # identity + sel come from asm_ident, which needs no game state
    sys.path.insert(0, HERE)
    import asm_ident as AI
    q2 = AI.char_quads(man, B)
    _, _, hits = AI.match_tiles(man, B, q2, a.atlas)
    if not hits:
        sys.exit('no captured tile matches any atlas -- cannot identify the character')
    per = Counter(v[0] for v in hits.values())
    print('characters identified: %s' % dict(per))

    T = man['textures']
    pal_key = max((k for k in {q['pal'] for q in quads} if k),
                  key=lambda k: (np.frombuffer(B(T[k]), np.uint8).reshape(256, 4)[:, 3] > 0).sum())
    pal = np.frombuffer(B(T[pal_key]), np.uint8).reshape(256, 4)

    # ── solve (char, sel, origin, mirror) per body, exactly as asm_ident does ────────────────────
    bodies = []
    for ch in per:
        atlas = json.load(open(os.path.join(a.atlas, ch + '_asm.json')))
        parts = atlas['parts']

        def part_of(ax, ay):
            for pid, p in parts.items():
                if p['x'] <= ax and p['y'] <= ay and ax + 32 <= p['x'] + p['w']                         and ay + 32 <= p['y'] + p['h']:
                    return int(pid), p
            return None, None

        votes, mirrored = defaultdict(Counter), {}
        for k, (nm, ay, ax) in hits.items():
            if nm != ch:
                continue
            pid, pt = part_of(ax, ay)
            if pid is None:
                continue
            for q in q2[k]:
                offx = ax + q['u0'] - pt['x']
                offy = ay + q['v0'] - pt['y']
                sxo = (pt['w'] - q['tw'] - offx) if q['fx'] else offx
                votes[pid][(round(q['sx'] - sxo, 3),
                            round(q['sy'] - (pt['h'] - q['th'] - offy), 3))] += 1
                mirrored[pid] = q['fx']
        place = {pid: c.most_common(1)[0][0] for pid, c in votes.items()}
        if len(place) < 2:
            print('  %s: only %d part placed -- the origin is always solvable from one, so this '
                  'body cannot be gated' % (ch, len(place)))
            continue
        sols = []
        for sel, recs in atlas['assemblies'].items():
            have = {r['part']: r for r in recs}
            if not set(place) <= set(have):
                continue
            os_ = set()
            for pid, (px, py) in place.items():
                r = have[pid]
                ox = (px - r['dx'] + parts[str(pid)]['w']) if mirrored[pid] else (px + r['dx'])
                os_.add((round(ox, 3), round(py - r['dy'], 3)))
            if len(os_) == 1:
                sols.append((sel, os_.pop()))
        if not sols:
            print('  %s: no assembly places its parts consistently -- not gated' % ch)
            continue
        sel, (ox, oy) = sols[0]
        bodies.append((ch, sel, ox, oy, any(mirrored.values()), len(sols)))
        print('  %s sel %s (1 of %d candidates)  origin (%.1f, %.1f)  %s'
              % (ch, sel, len(sols), ox, oy, 'MIRRORED' if any(mirrored.values()) else 'upright'))

    if not bodies:
        sys.exit('no body could be pinned -- nothing to gate on this pack')

    ims = [Image.fromarray(pal[truth])]
    labels = ['STEAM TRUTH']
    print()
    for ch, sel, ox, oy, mir, _n in bodies:
        em = raster_emitter(a.atlas, ch, sel, ox, oy, mir, truth.shape, x0, y0,
                            a.forward_records)
        if em is None:
            continue
        # ⚠ SCORE ONE BODY, NOT THE FRAME. The truth raster holds EVERY body in the frame while
        # each emitter raster holds one, so scoring the whole plane counts the OTHER fighter as
        # "missed" and buries the real signal: the first run read 0.407/0.593 for exactly that
        # reason. Restrict to this body's own bounding box, padded, and score there.
        ys, xs = np.nonzero(em)
        if not len(ys):
            print('%s sel %s: emitter drew nothing' % (ch, sel))
            continue
        PAD = 8
        r0, r1 = max(0, ys.min() - PAD), min(em.shape[0], ys.max() + 1 + PAD)
        c0, c1 = max(0, xs.min() - PAD), min(em.shape[1], xs.max() + 1 + PAD)
        tt, ee = truth[r0:r1, c0:c1], em[r0:r1, c0:c1]
        both = (tt > 0) | (ee > 0)
        inter = ((tt > 0) & (ee > 0)).sum()
        union = both.sum()
        same = ((tt > 0) & (ee > 0) & (tt == ee)).sum()
        print('%s sel %-5s  bbox %dx%d   coverage IoU %.4f   index-exact %.4f of the overlap   '
              '(missed %d, invented %d, wrong index %d)'
              % (ch, sel, c1 - c0, r1 - r0, inter / max(1, union), same / max(1, inter),
                 int(((tt > 0) & (ee == 0)).sum()), int(((tt == 0) & (ee > 0)).sum()),
                 int(inter - same)))
        ims.append(Image.fromarray(pal[em]))
        labels.append('%s sel %s' % (ch, sel))
        d = np.zeros(truth.shape + (4,), np.uint8)
        d[..., 3] = 255
        d[(truth > 0) & (em == 0)] = (255, 60, 60, 255)     # truth only  -> we MISSED it
        d[(truth == 0) & (em > 0)] = (60, 160, 255, 255)    # emitter only -> we INVENTED it
        d[(truth > 0) & (em > 0) & (truth == em)] = (40, 40, 40, 255)
        d[(truth > 0) & (em > 0) & (truth != em)] = (255, 220, 0, 255)   # both, wrong index
        ims.append(Image.fromarray(d))
        labels.append('diff (red=missed, blue=invented, yellow=wrong index)')

    if a.png:
        W = sum(i.width for i in ims) + 16 * (len(ims) - 1)
        H = max(i.height for i in ims)
        out = Image.new('RGBA', (max(W, 1), H), (30, 30, 40, 255))
        x = 0
        for i in ims:
            out.paste(i, (x, 0), i)
            x += i.width + 16
        out.resize((out.width * 2, out.height * 2), Image.NEAREST).save(a.png)
        print('wrote %s  (%s)' % (a.png, ' | '.join(labels)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
