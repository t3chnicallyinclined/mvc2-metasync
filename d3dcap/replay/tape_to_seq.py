#!/usr/bin/env python3
"""tape_to_seq.py -- render a RECORDED AGENT TAPE through the Path B player.

    python tape_to_seq.py ../../web/tapecanvas/tape_59601369.json --start 1800 --count 300
    python serve.py            # then http://localhost:8099/player.html?seq=tape_59601369.seq

WHAT THIS IS
------------
`player.html` replays a `.seq`, which is a recording of Steam's own DRAW CALLS -- vertex buffers,
index buffers, texture pages, pipeline state. A tape is a recording of the game's STATE -- sid, sx,
sy, facing. There are no vertices and no pixels anywhere in a tape, so the player cannot open one.

This is the bridge: it SYNTHESISES a draw list from tape state using the placement law measured
against the Path B captures, and writes it in the player's own container. Same viewer, same shaders,
same palette path -- the only thing that changes is where the draw list came from. That makes the
comparison meaningful: any difference you see is the EMITTER, not the renderer.

THE PLACEMENT LAW (measured; see docs/WORKSTREAM-MINIMAL-TAPE.md §12, and asm_ident.py)
---------------------------------------------------------------------------------------
    origin        = (sx * 3/5, sy * 7/15)        tape is 640x480; native is 384x224
    unmirrored:     part_left = origin_x - dx
    mirrored:       part_left = origin_x + dx - part_w      (the same rect, reflected about origin_x)
    both:           part_top  = origin_y + dy
    the part bitmap: the atlas rect with its 32-row TILE BANDS reversed

⭐ THE CROSS-CHECK THAT SAYS THE UNITS ARE RIGHT. A grounded character in this tape sits at
sy = 433.4, and 433.4 * 7/15 = 202.25. The ground line measured independently from three Path B
captures -- three different characters, two different frames -- was origin_y = 202.067. Two
unrelated measurements agreeing to a fifth of a native pixel is not a coincidence, and neither run
was given the other's answer.

⚠ WHAT IS ASSUMED HERE, AND HOW TO FALSIFY IT
---------------------------------------------
* `mirror = (facing == 1)`. Measured only indirectly: the RIGHT-side body of f2574 (which faces
  LEFT) was unmirrored, so the atlas is baked facing left. If every character comes out mirrored,
  this is the line to flip -- `--flip-facing` does it without editing anything.
* SLOT -> TEAM is `p1_team` on EVEN slots and `p2_team` on ODD (per mvc-live-skins-side-calibration).
  If the wrong characters appear, `--swap-teams`.
* THE TILE-BAND REVERSAL is measured on exactly TWO parts (PL32 #81 and PL2A #353, both at 1.0000).
  Applying it to every part is a generalisation, not a measurement. `--no-rowfix` turns it off; if
  some limbs look right only with it off, the rip is inconsistent and THAT is the finding.
* Effects, the HUD and the stage are NOT drawn. This is the body walker's output only, on a black
  field, because that is the only part the law has been measured against. A missing HUD here is not
  a bug -- it is scope.

⚠ ROM-derived. The .seq embeds the game's own pixels. Never commit one, never serve it publicly.
"""
import argparse
import hashlib
import json
import os
import struct
import sys
from collections import Counter, OrderedDict

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
DEF_ATLAS = r'C:\Users\trist\projects\maplecast-flycast\web\test-atlas\chars'
DEF_TEMPLATE = os.path.join(HERE, 'frame_2574.pack')

SX, SY = 192.0, 112.0            # native half-extents: 384x224
TAPE_X, TAPE_Y = 3.0 / 5.0, 7.0 / 15.0    # 640->384, 480->224
STRIDE = 40
Z0, ZSTEP = 0.98150, 1.79e-7     # Steam carries draw order in the depth value; match the shape


def sha8(b):
    return hashlib.sha256(b).hexdigest()[:16]


class Atlas:
    """One character's index pixels, packed parts and assemblies."""

    _cache = {}

    def __init__(self, base, cid):
        self.name = 'PL%02X' % cid
        self.idx = np.array(Image.open(os.path.join(base, self.name + '_idx.png')))[:, :, 0]
        a = json.load(open(os.path.join(base, self.name + '_asm.json')))
        self.parts, self.asm = a['parts'], a['assemblies']
        lut = json.load(open(os.path.join(base, self.name + '_lut.json')))
        self.banks, self.bodyBank = lut['banks'], lut.get('bodyBank', 0)

    @classmethod
    def get(cls, base, cid):
        if cid not in cls._cache:
            try:
                cls._cache[cid] = cls(base, cid)
            except FileNotFoundError:
                cls._cache[cid] = None
        return cls._cache[cid]

    def part_bitmap(self, pid, rowfix=True):
        p = self.parts[str(pid)]
        a = self.idx[p['y']:p['y'] + p['h'], p['x']:p['x'] + p['w']].copy()
        if rowfix and p['h'] >= 64:
            # The packed atlas writes a part's 32-row TILE BANDS bottom-up while writing each tile's
            # pixels top-down. Confirmed EXACT (1.0000) on PL32 part 81 and PL2A part 353.
            R = p['h'] // 32
            a = np.vstack([a[(R - 1 - i) * 32:(R - i) * 32] for i in range(R)])
        return a, p['w'], p['h']

    def palette(self, bank=None):
        b = self.banks[self.bodyBank if bank is None else bank]
        pal = np.zeros((256, 4), np.uint8)
        for i, c in enumerate(b[:256]):
            pal[i] = c
        return pal


def template(path):
    """Pipeline state, shaders, samplers and constant buffers lifted from a REAL captured draw.

    Synthesising D3D-to-WebGPU state by hand is how you get a subtly wrong picture and then blame the
    emitter for it. Copying a known-good indexed draw's state removes that whole class of error: if
    the character path renders correctly for a capture, it renders correctly here.
    """
    f = open(path, 'rb')
    assert f.read(4) == b'RRPK', path
    n = struct.unpack('<I', f.read(4))[0]
    man = json.loads(f.read(n))
    body = f.read()
    d = next((x for x in man['draws'] if x['psVariant'] == 'indexed'), None)
    if d is None:
        sys.exit('template %s has no indexed draw to copy state from' % path)
    cbs = {h: body[r['off']:r['off'] + r['len']] for h, r in man['constantBuffers'].items()}
    return man, d, cbs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('tape')
    ap.add_argument('--atlas', default=DEF_ATLAS)
    ap.add_argument('--template', default=DEF_TEMPLATE)
    ap.add_argument('-o', '--out')
    ap.add_argument('--start', type=int, default=0, help='first tape row')
    ap.add_argument('--count', type=int, default=300, help='rows to convert')
    ap.add_argument('--no-rowfix', action='store_true')
    ap.add_argument('--flip-facing', action='store_true')
    ap.add_argument('--swap-teams', action='store_true')
    a = ap.parse_args()

    tape = json.load(open(a.tape, encoding='utf-8'))
    cols = [s.strip() for s in tape['schema'].strip('[]').split(',')]
    C = {n: i for i, n in enumerate(cols)}
    for need in ('drawn[6]', 'sid[6]', 'sx[6]', 'sy[6]', 'facing[6]'):
        if need not in C:
            sys.exit('this tape has no %s column -- it predates tape v2 and cannot drive the '
                     'emitter. Record a new one with agent 0.3.23+.' % need)
    rows = tape['frames'][a.start:a.start + a.count]
    if not rows:
        sys.exit('no rows in that range (tape has %d)' % len(tape['frames']))
    p1, p2 = tape['p1_team'], tape['p2_team']
    if a.swap_teams:
        p1, p2 = p2, p1
    print('tape %s: %d frames, using %d from %d'
          % (os.path.basename(a.tape), len(tape['frames']), len(rows), a.start))
    print('  P1 %s   P2 %s' % (['PL%02X' % c for c in p1], ['PL%02X' % c for c in p2]))

    man, tdraw, tcbs = template(a.template)
    print('  state copied from %s draw %d (%s/%s)'
          % (os.path.basename(a.template), tdraw['i'], tdraw['vsVariant'], tdraw['psVariant']))

    pool, pool_index = [], {}

    def intern(b):
        h = sha8(b)
        if h not in pool_index:
            pool_index[h] = {'off': sum(len(p) for p in pool), 'len': len(b)}
            pool.append(b)
        return pool_index[h]

    textures, heads = OrderedDict(), []
    cb_recs = {h: intern(b) for h, b in tcbs.items()}
    missing, drawn_total = Counter(), 0

    for r in rows:
        verts, idxs, draws = bytearray(), [], []
        for slot in range(6):
            if not r[C['drawn[6]']][slot]:
                continue
            cid = (p1 if slot % 2 == 0 else p2)[slot // 2]
            at = Atlas.get(a.atlas, cid)
            if at is None:
                missing['PL%02X (no atlas)' % cid] += 1
                continue
            sid = int(r[C['sid[6]']][slot])
            recs = at.asm.get(str(sid))
            if not recs:
                missing['%s sel %d' % (at.name, sid)] += 1
                continue
            ox = r[C['sx[6]']][slot] * TAPE_X
            oy = r[C['sy[6]']][slot] * TAPE_Y
            mir = bool(r[C['facing[6]']][slot]) != a.flip_facing

            pal = at.palette()
            palkey = '%s_pal_%s' % (at.name, sha8(pal.tobytes()))
            if palkey not in textures:
                textures[palkey] = {'w': 256, 'h': 1, 'fmt': 28, **intern(pal.tobytes())}

            for rec in recs:
                pid = rec['part']
                if str(pid) not in at.parts:
                    continue
                bmp, pw, ph = at.part_bitmap(pid, not a.no_rowfix)
                key = '%s_p%d_%s' % (at.name, pid, sha8(bmp.tobytes()))
                if key not in textures:
                    textures[key] = {'w': pw, 'h': ph, 'fmt': 61, **intern(bmp.tobytes())}

                left = (ox + rec['dx'] - pw) if mir else (ox - rec['dx'])
                top = oy + rec['dy']
                x0, x1 = left / SX - 1.0, (left + pw) / SX - 1.0
                y0, y1 = 1.0 - top / SY, 1.0 - (top + ph) / SY
                z = Z0 - len(draws) * ZSTEP
                u0, u1 = (1.0, 0.0) if mir else (0.0, 1.0)   # the mirror lives in the UV winding
                first = len(verts) // STRIDE
                for px, py, u, v in ((x0, y0, u0, 0.0), (x0, y1, u0, 1.0),
                                     (x1, y0, u1, 0.0), (x1, y1, u1, 1.0)):
                    verts += struct.pack('<4f', px, py, z, 0.0)      # POSITION  @0
                    verts += struct.pack('<2f', 0.0, 0.0)            # NORMAL    @16 (never read)
                    verts += bytes((255, 255, 255, 255))             # color0    @24  white, opaque
                    verts += bytes((0, 0, 0, 0))                     # color1    @28  no offset
                    verts += struct.pack('<2f', u, v)                # TEXCOORD  @32
                fi = len(idxs)
                idxs += [first, first + 1, first + 2, first + 2, first + 1, first + 3]
                d = dict(tdraw)
                d.update({'i': len(draws), 'firstIndex': fi, 'indexCount': 6,
                          'stride': STRIDE, 'voff': 0, 'tex': [key, palkey]})
                draws.append(d)
        drawn_total += len(draws)
        heads.append({
            'frame': int(r[C['frame']]) if 'frame' in C else len(heads),
            'sceneRTFile': None, 'viewport': man['viewport'], 'sceneRT': man['sceneRT'],
            'clears': [{'kind': 'ClearRenderTargetView', 'colour': [0, 0, 0, 0]}],
            'vb': intern(bytes(verts)),
            'ib': intern(struct.pack('<%dI' % len(idxs), *idxs)),
            'inputLayouts': man['inputLayouts'],
            'textures': {k: textures[k] for k in {d['tex'][0] for d in draws} |
                         {d['tex'][1] for d in draws}},
            'constantBuffers': cb_recs,
            'draws': draws,
        })

    out = a.out or os.path.join(HERE, os.path.basename(a.tape).replace('.json', '') + '.seq')
    manifest = {'frames': heads, 'source': os.path.basename(a.tape),
                'note': 'SYNTHESISED from tape state by tape_to_seq.py -- not a capture'}
    hb = json.dumps(manifest).encode('utf-8')
    with open(out, 'wb') as f:
        f.write(b'RRSQ')
        f.write(struct.pack('<I', len(hb)))
        f.write(hb)
        for p in pool:
            f.write(p)
    total = 8 + len(hb) + sum(len(p) for p in pool)

    print('\n%d frames, %d draws (%.1f/frame), %d distinct textures'
          % (len(heads), drawn_total, drawn_total / max(1, len(heads)), len(textures)))
    if missing:
        print('  %d draws skipped -- no assembly record:' % sum(missing.values()))
        for k, v in missing.most_common(8):
            print('     %-24s x%d' % (k, v))
        print('  (a missing sel is a HOLE IN THE RIP, not a placement error -- do not "fix" it here)')
    if drawn_total == 0:
        sys.exit('\nnothing was drawn. Check --swap-teams and that the range covers a live round.')
    print('\nwrote %s  (%.1f MB)' % (out, total / 1048576.0))
    print('  python serve.py   then   http://localhost:8099/player.html?seq=%s'
          % os.path.basename(out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
