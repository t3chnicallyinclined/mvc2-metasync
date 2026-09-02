#!/usr/bin/env python3
"""asm_ident.py -- identify the CHARACTER and validate the ASSEMBLY TABLE from a capture alone.

    python asm_ident.py frame_2574.pack [--atlas DIR] [--char PL17] [--minx 200]

Runs entirely on files already on disk. No live session, no game state, no new capture.

WHY THIS EXISTS
---------------
The union-of-tiles / IoU test that preceded this one "found no convergence, best 0.685", and that was
read as evidence that our offline `_asm.json` geometry might not describe the engine's real quads.
That reading was wrong, and the reason is worth keeping: **silhouette IoU between two CONSERVATIVE
COVERS of a humanoid has no discriminating power.** Steam's tiles and the assembly's part rects are
both over-approximations of the same sprite at different granularities, so two DIFFERENT characters
also score 0.7-0.8. The test could not have failed for the right reason, so it could not have passed
for the right reason either. Re-run here, it tops out at IoU 0.802 on an unrelated character.

WHAT STEAM ACTUALLY DRAWS (measured, frame 2574, 84 indexed draws)
-----------------------------------------------------------------
Every character draw is ONE QUAD, and:
  * quads are exactly 8x8, 16x16 or 32x32 in native units -- integer, square, power of two;
  * the UV span in TEXELS equals the size in native units EXACTLY. Scale is 1:1. There is no zoom;
  * every quad samples a 32x32 R8_UNORM index page + a 256x1 RGBA palette (POINT on both);
  * index values are 0..15 ONLY -- 4bpp is preserved, and index 0 is the transparent entry;
  * each quad gets its OWN z, stepping by a constant ~1.79e-7 per draw -- draw order is carried in
    the depth value, i.e. the registration counter, exactly as the composite render model says.
So Steam's character path is a plain 2D tile blit with no transform: the sprite is split into 8/16/32
tiles cut from 32x32 pages. The DC assembly record (dx, dy, part) sits ONE LEVEL ABOVE this, which is
why comparing them directly needs a union, not a per-quad match.

THE TESTS, in increasing strength
---------------------------------
1. IDENTIFY. Take each captured 32x32 index page and look for a byte-exact copy in every offline
   `PLxx_idx.png`. A 4bpp bitmap match across 60 characters with zero free parameters.
   RESULT on frame 2574: 7 tiles match at EXACTLY 1.000, all to PL17, no ambiguity.
   => the ROM-extracted index pixels ARE the bytes Steam draws, and the character is recoverable from
      a capture that carries no game state at all.

2. PLACE. For each matched tile we know its position in the atlas AND on screen. Resolve which packed
   part contains it and derive that part's top-left on screen. RESULT: 7 independent tiles collapse
   onto 2 part placements, each confirmed redundantly (5 tiles and 2 tiles), with no disagreement.

3. THE FALSIFIER. Does one assembly record set place ALL observed parts at ONE origin?
   RESULT: yes, exactly -- origin (319.8, 202.1), zero residual, under the model below.

THE PLACEMENT MODEL (confirmed, no fitted constants)
----------------------------------------------------
    screen_x = origin_x - dx        # facing LEFT (mirrored). +dx when facing right.
    screen_y = origin_y + dy
    within a part, for a tile at atlas offset (offx, offy):
        x += offx
        y += (part_h - tile_h - offy)          <-- the part bitmap rows are stored BOTTOM-UP

TWO THINGS TO CARRY FORWARD
---------------------------
  * THE X SIGN IS THE FACING FLIP, and forgetting it is what made sound data look broken. The
    observed part-to-part delta was dx=+32, dy=-48; the table says dx=-32, dy=-48. One axis exactly
    negated and the other exactly equal is the signature of a MIRROR, not of bad geometry. This is
    the DC walker's neg-X control (`0x10`, bank03) surfacing in Steam pixels. A near-miss in one axis
    only is a transform you have not modelled -- it is almost never corrupt data.
  * THE WITHIN-PART VERTICAL INVERSION IS MEASURED BUT NOT EXPLAINED. Five tiles of part 1158 are
    consistent ONLY with bottom-up part rows, while the record says flipy=0. The likely cause is the
    row order the rip writes into `_parts.png`, NOT the engine. It is exactly the shape of defect
    that turns a limb into a column or a blob, so check it before blaming placement for one.

WHAT THIS DOES **NOT** ESTABLISH
--------------------------------
The `sel` narrows to 10 of PL17's 681 assemblies, not to one: those 10 all share the observed parts.
Only 2 parts were observed, on one body of one frame, so the placement law is confirmed on 2 points,
not over a pose. This says THE TABLE AND THE PIXELS ARE SOUND and gives the exact placement law; it
does not certify every record. Widen it with more frames, or by capturing game state alongside.
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

DEF_ATLAS = r'C:\Users\trist\projects\maplecast-flycast\web\test-atlas\chars'
SX, SY = 192.0, 112.0          # native units: NDC-per-texel is exactly 2/384 and 2/224


def load_pack(path):
    f = open(path, 'rb')
    if f.read(4) != b'RRPK':
        sys.exit('not a pack: %s' % path)
    n = struct.unpack('<I', f.read(4))[0]
    man = json.loads(f.read(n))
    body = f.read()
    return man, (lambda b: body[b['off']:b['off'] + b['len']])


def char_quads(man, B):
    """One entry per indexed draw: its screen rect, and where in its 32x32 page it samples."""
    vb, ib = B(man['vb']), B(man['ib'])
    IDX = struct.unpack('<%dI' % (len(ib) // 4), ib)
    out = defaultdict(list)
    for d in man['draws']:
        if d['psVariant'] != 'indexed' or not d['tex'][0]:
            continue
        st, vo = d['stride'], d['voff']
        ii = sorted(set(IDX[d['firstIndex']:d['firstIndex'] + d['indexCount']]))
        P, U = [], []
        for i in ii:
            x, y = struct.unpack_from('<2f', vb, vo + i * st)
            u, v = struct.unpack_from('<2f', vb, vo + i * st + 32)
            P.append(((x + 1) * SX, (1 - y) * SY))
            U.append((u, v))
        z = struct.unpack_from('<f', vb, vo + ii[0] * st + 8)[0]
        out[d['tex'][0]].append(dict(
            i=d['i'], z=z, sx=min(p[0] for p in P), sy=min(p[1] for p in P),
            tw=max(p[0] for p in P) - min(p[0] for p in P),
            th=max(p[1] for p in P) - min(p[1] for p in P),
            u0=min(u for u, v in U) * 32, v0=min(v for u, v in U) * 32))
    return out


def match_tiles(man, B, quads, atlas_dir, only=None):
    """Byte-exact 32x32 search of each captured index page across every offline atlas."""
    T = man['textures']
    pages = {k: np.frombuffer(B(T[k]), np.uint8).reshape(32, 32) for k in quads
             if T[k]['w'] == 32 and T[k]['h'] == 32 and T[k]['fmt'] == 61}
    probes = {}
    for k, a in pages.items():
        # search on the most distinctive row; 4bpp means most rows are too plain to be a key
        nz, r = max((len(set(a[r].tolist())), r) for r in range(32))
        if nz >= 6:
            probes[k] = (a, r)
    files = sorted(glob.glob(os.path.join(atlas_dir, '*_idx.png')))
    if only:
        files = [f for f in files if os.path.basename(f).startswith(only + '_')]
    hits = {}
    for fp in files:
        name = os.path.basename(fp).replace('_idx.png', '')
        A = np.array(Image.open(fp))[:, :, 0]
        flat, W = A.tobytes(), A.shape[1]
        for k, (a, r) in probes.items():
            if k in hits:
                continue
            row, s = a[r].tobytes(), 0
            while True:
                p = flat.find(row, s)
                if p < 0:
                    break
                s = p + 1
                y, x = divmod(p, W)
                y -= r
                if x + 32 > W or y < 0 or y + 32 > A.shape[0]:
                    continue
                if (A[y:y + 32, x:x + 32] == a).all():
                    hits[k] = (name, y, x)
                    break
    return len(pages), len(probes), hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pack')
    ap.add_argument('--atlas', default=DEF_ATLAS)
    ap.add_argument('--char')
    ap.add_argument('--minx', type=float, default=None,
                    help='only consider draws at screen x >= this, to isolate ONE body')
    a = ap.parse_args()

    man, B = load_pack(a.pack)
    quads = char_quads(man, B)
    npg, nprobe, hits = match_tiles(man, B, quads, a.atlas, a.char)
    print('index pages %d, probed %d, matched byte-exact %d' % (npg, nprobe, len(hits)))
    if not hits:
        sys.exit('no captured tile occurs in any offline atlas -- the pixel banks DISAGREE')
    per = Counter(v[0] for v in hits.values())
    for nm, c in per.most_common():
        print('   %-8s  %d tiles' % (nm, c))
    ch = per.most_common(1)[0][0]
    print('\nCHARACTER = %s   (%d of %d matched tiles; %d other candidates rejected outright)'
          % (ch, per[ch], len(hits), len(per) - 1))

    asm = json.load(open(os.path.join(a.atlas, ch + '_asm.json')))
    parts = asm['parts']

    def part_of(ax, ay):
        for pid, pt in parts.items():
            if pt['x'] <= ax and pt['y'] <= ay and ax + 32 <= pt['x'] + pt['w'] \
                    and ay + 32 <= pt['y'] + pt['h']:
                return int(pid), pt
        return None, None

    place, votes = {}, defaultdict(Counter)
    for k, (nm, ay, ax) in hits.items():
        if nm != ch:
            continue
        pid, pt = part_of(ax, ay)
        if pid is None:
            continue
        for q in quads[k]:
            if a.minx is not None and q['sx'] < a.minx:
                continue
            offx = ax + q['u0'] - pt['x']
            offy = ay + q['v0'] - pt['y']
            px = q['sx'] - offx
            py = q['sy'] - (pt['h'] - q['th'] - offy)     # part bitmap rows are bottom-up
            votes[pid][(round(px, 3), round(py, 3))] += 1
    print()
    for pid, c in votes.items():
        (px, py), n = c.most_common(1)[0]
        place[pid] = (px, py)
        print('   part %-5d %3dx%-3d  top-left %8.1f,%7.1f   confirmed by %d tiles%s'
              % (pid, parts[str(pid)]['w'], parts[str(pid)]['h'], px, py, n,
                 '' if len(c) == 1 else '   *** %d DISAGREEING placements' % (len(c) - 1)))
    if len(place) < 2:
        sys.exit('\nonly %d part placed -- with a single part the origin is always solvable, so this '
                 'cannot test the table. Use a frame where more tiles match.' % len(place))

    print('\nsearching %d %s assemblies for one origin that places all %d parts...'
          % (len(asm['assemblies']), ch, len(place)))
    best = []
    for facing, sgn in (('LEFT (mirrored)', -1), ('RIGHT', +1)):
        for sel, recs in asm['assemblies'].items():
            have = {r['part']: r for r in recs}
            if not set(place) <= set(have):
                continue
            os_ = {(round(px - sgn * have[p]['dx'], 3), round(py - have[p]['dy'], 3))
                   for p, (px, py) in place.items()}
            if len(os_) == 1:
                best.append((facing, sel, len(recs), os_.pop()))
    if not best:
        print('   FAILED: no assembly places these parts consistently under either facing.')
        print('   THAT would be a real defect in the table -- but first rule out that the parts')
        print('   belong to two DIFFERENT pool nodes that happen to be drawn side by side.')
        return 1
    print('   EXACT -- zero residual, facing %s' % best[0][0])
    print('   origin = %s' % (best[0][3],))
    print('   sel narrowed to %d of %d: %s'
          % (len(best), len(asm['assemblies']), ', '.join(b[1] for b in best[:16])))
    print('\n   The table and the pixels are SOUND. The sel is not unique from geometry alone --')
    print('   these assemblies all share the observed parts. Game state at capture would pin it.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
