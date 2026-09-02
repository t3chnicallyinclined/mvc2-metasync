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
    the part bitmap: the atlas rect FLIPPED VERTICALLY -- every part is packed upside down

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
* THE PALETTE BANK. `costume` is in the tape but the costume -> bank mapping is NOT known, so this
  uses the atlas `bodyBank` and colours may be wrong even when the pose is exact. It cannot be
  derived from the captures either: those are a DIFFERENT match, so their costumes do not apply.
  `--bank N` overrides. Wrong colours here are an open question, not a placement error.
* LAYER DIRECTION. Bodies and objects are ordered by the tape's `layer`, descending. Which end of
  that range is "back" is NOT measured: the captures carry no game state, so layer cannot be
  correlated against Steam's draw index there. `--layer-asc` flips it.
* OBJECTS use the OWNER slot's character atlas with `sid & 0x7fff`. If object sids do not resolve,
  the run reports them and they are probably indexed against an effects bank instead -- `gfx1` in
  the row is the content key that would say which.
* The HUD and the stage are NOT drawn, on a black field. Not a bug -- scope.

⚠ ROM-derived. The .seq embeds the game's own pixels. Never commit one, never serve it publicly.
"""
import argparse
import base64
import gzip
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

    def part_bitmap(self, pid, vflip=True):
        p = self.parts[str(pid)]
        a = self.idx[p['y']:p['y'] + p['h'], p['x']:p['x'] + p['w']]
        # ⭐ EVERY PART IS STORED UPSIDE DOWN. Verified against Steam's OWN rendered frame
        # (scene_5630): PL32 sel 13 assembled with a full vertical flip is Colossus in exactly the
        # captured pose; without it, or with a 32-row band reversal, it is scrambled.
        # ⚠ An earlier reading of "the tile BANDS are reversed" scored 1.0000 and was still WRONG as
        # a drawing rule. That test compared atlas blocks against captured 32x32 pages -- and BOTH
        # are stored flipped the same way, so the within-tile half of the flip cancelled and only the
        # band-order half showed up. It is a true statement about atlas-vs-capture LAYOUT and a false
        # one about how to draw. Comparing two representations that share a defect cannot reveal it.
        return (a[::-1].copy() if vflip else a.copy()), p['w'], p['h']

    def palette(self, bank=None, costume=0):
        # ⭐ costume c -> ROM palette row block 8*c. Established from the palette DATA, not guessed:
        # grouping identical rows in PLxx_lut.json, rows repeat at +8 and NEVER at +4 (checked on
        # PL00/PL17/PL2A/PL32/PL0A: 25-35 of 40 rows equal at +8, 0 of 44 equal at +4). Rows 0..47
        # are 6 costume blocks of 8. This matches CLAUDE.md's PVR formula 16*(pair+1) + 8*side --
        # eight PAL4 banks per fighter slot.
        # ⚠ The SUB-ROW within the block (0..7) is a documented GAP. A capture's PL32 body needed
        # sub-row 2, and that assembly's records all carry FLAGS 0x0000, so the record's 0x0070
        # field cannot be the whole story -- node+0x12d/+0x12e are the missing terms. Sub-row 0 is
        # the default here; --bank overrides absolutely.
        if bank is None:
            bank = 8 * int(costume)
        b = self.banks[bank % len(self.banks)]
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
    ap.add_argument('--no-vflip', action='store_true',
                    help='draw parts as packed. They come out upside down -- diagnostic only.')
    ap.add_argument('--bank', type=int, default=None,
                    help='palette bank override. Default is the atlas bodyBank; the costume->bank '
                         'rule is NOT yet known (see the note in the header).')
    ap.add_argument('--forward-records', action='store_true',
                    help='draw assembly records in list order. Measured WRONG -- capes and limbs '
                         'punch through bodies. Diagnostic only.')
    ap.add_argument('--no-objs', action='store_true',
                    help='bodies only. Capes and projectiles that are their own pool node vanish.')
    ap.add_argument('--objs-under', action='store_true',
                    help="on a layer TIE draw objects BEHIND their body. Approximates the missing "
                         "node+0x31 sort key; the engine's real tie-break is fighters-first.")
    ap.add_argument('--layer-desc', action='store_true',
                    help='walk layers 15->0. The engine walks 0->15 (loc_8c0308c2); diagnostic only.')
    ap.add_argument('--flip-facing', action='store_true')
    ap.add_argument('--swap-teams', action='store_true')
    a = ap.parse_args()

    raw = open(a.tape, 'rb').read()
    if raw[:2] == bytes([0x1F, 0x8B]):
        raw = gzip.decompress(raw)
    tape = json.loads(raw)
    # ⭐ TAPE v3. `nodes` is the engine's own draw list -- fighters and pool objects interleaved,
    # in paint order. When present it REPLACES the per-slot columns and the objs stream: the record
    # index is the z-order, so the sort/layer/registration model below is bypassed entirely.
    # `pals` is the palette each node's `pal` indexes: 32 B ARGB4444 (u16 LE, A15-12 R11-8 G7-4
    # B3-0, nibble*17). Verified: all 5 resolved rows of tape 59612530 match an atlas LUT row
    # byte-for-byte.
    v3nodes, v3pals = {}, []
    if tape.get('nodes'):
        nb = gzip.decompress(base64.b64decode(tape['nodes']))
        off = 0
        while off + 6 <= len(nb):
            fr = struct.unpack_from('<I', nb, off)[0]
            n = struct.unpack_from('<H', nb, off + 4)[0]
            off += 6
            rows = []
            for _ in range(n):
                v = struct.unpack_from('<BBBbBBBBHHHBBBBHHHfffII', nb, off)
                off += 44
                rows.append(dict(kind=v[0], slot=v[1], cat=v[2], sort=v[3], layer=v[4], face=v[5],
                                 owner=v[6], drawn=v[7], sid=v[8], pal=v[9], zx=v[15] / 4096.0,
                                 fsx=v[18], fsy=v[19], depth=v[20], gfx1=v[21]))
            v3nodes[fr] = rows
        pb = gzip.decompress(base64.b64decode(tape.get('pals', '')))
        for i in range(len(pb) // 32):
            pal = np.zeros((256, 4), np.uint8)
            for j in range(16):
                w = struct.unpack_from('<H', pb, i * 32 + j * 2)[0]
                pal[j] = ((w >> 8) & 15) * 17, ((w >> 4) & 15) * 17, (w & 15) * 17, ((w >> 12) & 15) * 17
            v3pals.append(pal)
        print('  TAPE v3: %d frames of ordered nodes, %d palettes' % (len(v3nodes), len(v3pals)))
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
    costume = tape.get('costume') or [0] * 6
    if a.swap_teams:
        p1, p2 = p2, p1
    print('tape %s: %d frames, using %d from %d'
          % (os.path.basename(a.tape), len(tape['frames']), len(rows), a.start))
    print('  P1 %s   P2 %s' % (['PL%02X' % c for c in p1], ['PL%02X' % c for c in p2]))

    objs = {}
    # v2 only: the local test tapes carry `objs` pre-decoded as [frame, rows] pairs; a server tape
    # carries it as a base64 gz string. On a v3 tape the node stream supersedes it, so skip both.
    if not a.no_objs and not v3nodes and isinstance(tape.get('objs'), list):
        for fr, lst in tape['objs']:
            objs[int(fr)] = lst
    print('  objs stream: %d frames carry objects (%d rows total)'
          % (len(objs), sum(len(v) for v in objs.values())))

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

        # ── ONE ordered list of bodies AND objects ───────────────────────────────────────────────
        # ⭐ `layer` is the ordering field, and it is carried on BOTH: the six fighter slots have
        # layer[6] (255 = not drawn) and every object row has its own. They share one space, 3..11.
        # Tris asked "there has to be a pointer or function telling that object what order to draw
        # in" -- this is it, and it is already in every tape we have recorded.
        items = []
        fr_clock = int(r[C['frame']])
        if v3nodes:
            # v3: the order IS the payload. No sort below is applied; `kind` picks the atlas lookup.
            for nd in v3nodes.get(fr_clock, ()):
                if nd['kind'] == 0:
                    cid = (p1 if nd['slot'] % 2 == 0 else p2)[nd['slot'] // 2]
                    mir = bool(nd['face'])
                else:
                    if nd['owner'] > 5:
                        missing['object with owner %d (unowned)' % nd['owner']] += 1
                        continue
                    cid = (p1 if nd['owner'] % 2 == 0 else p2)[nd['owner'] // 2]
                    mir = bool(nd['face']) != bool(nd['sid'] & 0x8000)
                items.append((0, Atlas.get(a.atlas, cid), nd['sid'] & 0x7FFF, nd['fsx'], nd['fsy'],
                              mir, 'body' if nd['kind'] == 0 else 'obj', nd['pal']))
        for slot in range(6 if not v3nodes else 0):
            if not r[C['drawn[6]']][slot]:
                continue
            lay = r[C['layer[6]']][slot] if 'layer[6]' in C else 8
            items.append((lay, Atlas.get(a.atlas, (p1 if slot % 2 == 0 else p2)[slot // 2]),
                          int(r[C['sid[6]']][slot]),
                          r[C['sx[6]']][slot], r[C['sy[6]']][slot],
                          bool(r[C['facing[6]']][slot]), 'body', costume[slot]))
        # OBJECTS -- capes, projectiles, satellites. Not drawing these is why a cape can simply
        # VANISH on one animation and be fine on another: in some poses it is part of the body
        # sprite, in others it is its own pool node.
        # Row layout, from the tape's own objs_enc header:
        #   [sid(|0x8000 = the object's OWN hflip), sx, sy, zx(scale x4096), face, cat, owner, layer,
        #    gfx1, _]
        # zx is 6826 in every row of this tape = 5/3 exactly, i.e. the same 640->384 factor the
        # origins use, so the native scale is 1 and no scaling is applied here. A tape where zx
        # VARIES would need it -- that is the DC walker's scaled branch, and it is not exercised yet.
        for ob in (() if v3nodes else objs.get(int(r[C['frame']]), ())):
            sid_raw, osx, osy, zx, face, cat, owner, lay = ob[0], ob[1], ob[2], ob[3], ob[4], ob[5], ob[6], ob[7]
            if owner > 5:
                missing['object with owner %d (unowned)' % owner] += 1
                continue
            items.append((lay, Atlas.get(a.atlas, (p1 if owner % 2 == 0 else p2)[owner // 2]),
                          sid_raw & 0x7FFF, osx, osy,
                          bool(face) != bool(sid_raw & 0x8000), 'obj', costume[owner]))

        # ⭐⭐ THE DRAW ORDER, CONFIRMED FROM THE DISASSEMBLY (mvc2-sh4-re-expert, bank03/bank04).
        # Battle sprites do NOT use the linked-list buckets I first read. There are TWO render
        # systems and the fighters are in the other one:
        #   System A  3D/backdrop props: doubly-linked lists, head 0x8C287A5C, walked by
        #             loc_8c0301ce (+ a real SECOND pass loc_8c030410 for nodes with a model at
        #             +0x84). In battle these run AFTER the sprites, buckets 5,6,7,8,0x0B.
        #   System B  THE FIGHTERS AND EVERY POOL OBJECT: 16 FLAT ARRAYS at
        #             0x8C287DE0 + L*0x180, counts at 0x8C2895E0, cleared every frame, cap 96 per
        #             layer (over-cap nodes are SILENTLY DROPPED). Walked by loc_8c0308c2 as
        #             L = 0..15 ASCENDING, then i = 0..count-1.
        # So: layer ASCENDING, not descending -- my previous default was backwards.
        #
        # Registration (bank04 loc_8c04515e) appends at the tail, then insertion-sorts backwards,
        # ASCENDING and STABLY, on key (s8)node+0x31. Registration order is:
        #     the six fighters first -- P1C1, P2C1, P1C2, P2C2, P1C3, P2C3, i.e. our slots 0..5
        #     with even = P1 (this CONFIRMS the slot->team assumption), then the pool lists in
        #     order 3, 4, 1, 2.
        #
        # ⚠⚠ WE DO NOT RECORD node+0x31, AND IT IS THE ACTUAL TIE-BREAK. Registration order only
        # decides ties, and on ties the fighter registers FIRST, so a same-layer object draws ON
        # TOP of its body. A cape that belongs behind must therefore carry a SMALLER +0x31 -- which
        # is exactly the field the tape drops. That is why some frames still show the cape through
        # the body, and it is now a precisely specified one-byte tape addition rather than a
        # mystery. --objs-under approximates it meanwhile.
        KIND = {'body': 0, 'obj': 1}                 # registration order: fighters, then the pool
        if a.objs_under:
            KIND = {'body': 1, 'obj': 0}
        if not v3nodes:
            items.sort(key=lambda t: ((-t[0] if a.layer_desc else t[0]), KIND[t[6]]))

        for lay, at, sid, tsx, tsy, mir, kind, cos in items:
            if at is None:
                missing['no atlas'] += 1
                continue
            recs = at.asm.get(str(sid))
            if not recs:
                missing['%s %s sel %d' % (at.name, kind, sid)] += 1
                continue
            ox, oy = tsx * TAPE_X, tsy * TAPE_Y
            if a.flip_facing:
                mir = not mir

            if v3nodes and a.bank is None and 0 <= cos < len(v3pals):
                pal = v3pals[cos]                      # v3: `cos` is the resolved palette index
            else:
                pal = at.palette(a.bank, cos)
            palkey = '%s_pal_%s' % (at.name, sha8(pal.tobytes()))
            if palkey not in textures:
                textures[palkey] = {'w': 256, 'h': 1, 'fmt': 28, **intern(pal.tobytes())}

            # ⭐ DRAW ORDER WITHIN AN ASSEMBLY IS THE REVERSE OF THE RECORD LIST. Recovered from the
            # captures, where submission order is known exactly: match each body's tiles back to
            # their part, then compare Steam's first draw index per part against that part's index
            # in the assembly.
            #     f5630 PL32 sel 13   record indices [17, 7]   descending
            #     f2574 PL17 sel 189  [7, 6]   sel 197 [10, 7]   sel 201 [10, 7]
            #     f5630 PL2A sel 83   [4, 1]
            # Three characters, four sels, no exceptions. Steam gives each draw a DECREASING z, so
            # submission order IS back-to-front: get it wrong and a cape draws through the body.
            # ⚠ The ROM walker itself counts UP (bank03 loc_8c03489e: index+1, record ptr +8), so
            # the reversal is in OUR rip, not the game. Worth chasing in rip_gfx2_assembly.py -- but
            # what the renderer must do is measured either way.
            for rec in (recs if a.forward_records else reversed(recs)):
                pid = rec['part']
                if str(pid) not in at.parts:
                    continue
                bmp, pw, ph = at.part_bitmap(pid, not a.no_vflip)
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
