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
import glob
import gzip
import hashlib
import json
import os
import math
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


sys.path.insert(0, 'C:/Users/trist/projects/maplecast-flycast/tools')
try:
    import rip_gfx2_assembly as RIP
except Exception:
    RIP = None

# ══ TAPE v5: THE WORLD-SPACE CLASS (System A) ═══════════════════════════════════════════════════
# Shadows, 1P/2P markers, super glows, hail chunks, the HUD and the stage props are not sprites:
# the game's second render system draws them as textured polygon lists placed by a 4x4 matrix and
# projected by a scene constant block built from the camera. Everything below is taken from the
# capture, byte for byte (see mvc-system-a-world-nodes): the node's 4x4 at +0xA8 transposed IS
# Steam's CBWorld; the polygon list at +0xA0 IS Steam's vertex buffer; the scene block is a fitted
# function of the render camera blk+0x6914 (exact to 2e-5 on every walker-time frame).
WORLD_TEMPLATE = os.path.join(HERE, 'capgate', 'frame_4445.pack')
import copy
import tsp_state as TS      # PCW/ISP/TSP -> D3D state, read from Steam's FUN_1408482a0 (gate: tsp_gate.py)
import bg_rule as BG        # frame background colour, read from FUN_1406101b0 / FUN_140843eb0 (gate: bg_gate.py)

CAMERA_BLOCK = os.path.join(HERE, 'camera_block.json')
TCW_PAGES = os.path.join(HERE, 'tcw_pages')
STAGE_DIR = 'C:/Users/trist/projects/maplecast-flycast/atlas/stages'   # ModNao-port rips: STGxx.json + STGxx_tNN.png


def nl_triangles(pay, has_colored=False):
    """Flat TRIANGLE LIST of every group of a NaomiLib mesh payload (see nl_groups)."""
    return [v for _flags, vs in nl_groups(pay, has_colored) for v in vs]


def nl_groups(pay, has_colored=False):
    """Expand a NaomiLib mesh payload (polygon groups) into [(group flags, TRIANGLE LIST of
    (x, y, z, nx, ny, nz, u, v) vertices)], one entry per group, in the winding Steam draws them.
    Group header 8 B: u32 flags (bits 0-1 = the D3D cull word Steam sends as ring command 9 --
    1 NONE, 2 FRONT, 3 BACK, tsp_state.codes; bit3 = 'triple' = independent triangles; bit 6 =
    submit as a strip, not expanded), u32 count (x3 for triple). Vertex: 0x20 direct (pos@0,
    normal@0xC, colour BGRA@0x10 when coloured, uv@0x18) or 0x08 reference ((u32@0 >> 16) in
    0x5FF0..0x5FFF; i32 @+4 = byte offset from the reference to the referenced vertex, +8). A zero
    u32 ends the mesh.
    WINDING is Steam's own CPU strip expansion in FUN_1408482a0 (strip loop after the vertex copy):
    even i -> (v[i], v[i+1], v[i+2]), odd i -> (v[i+2], v[i+1], v[i]); triple groups verbatim.
    Measured (tsp_gate.py, stage-11 tape vs 4 capgate packs): 442 of 454 matched draws reproduce
    the captured triangles with this rule (the old bit0-dependent rule: 133). The 12 others are
    bit-6 (0x72/0xF2) 5-vertex strips whose captured VB order is (0,2,1,4,3); their consumer is
    not identified and they are left in record order. One group = one D3D draw (its cull word)."""
    out = []
    n = len(pay)
    sa = 0
    while sa + 8 <= n:
        flags, vcount = struct.unpack_from('<II', pay, sa)
        if flags == 0 and vcount == 0:
            break
        triple = bool((flags >> 3) & 1)
        sa += 8
        vs = []
        ended = False
        for _ in range(vcount * (3 if triple else 1)):
            if sa + 8 > n:
                ended = True
                break
            head = struct.unpack_from('<I', pay, sa)[0]
            if head == 0:
                ended = True
                sa += 8
                break
            if 0x5FF0 <= (head >> 16) <= 0x5FFF:
                voff = struct.unpack_from('<i', pay, sa + 4)[0]
                ca = sa + voff + 8
                sa += 8
            else:
                ca = sa
                sa += 0x20
            if 0 <= ca and ca + 0x20 <= n:
                vs.append(struct.unpack_from('<8f', pay, ca))
            else:
                vs.append((0.0,) * 8)
        tris = []
        if triple:
            for i in range(2, len(vs), 3):
                tris += [vs[i - 2], vs[i - 1], vs[i]]                    # FUN_1408482a0: lists copied verbatim
        else:
            for i in range(max(0, len(vs) - 2)):
                if i % 2 == 0:
                    tris += [vs[i], vs[i + 1], vs[i + 2]]                # even: in order
                else:
                    tris += [vs[i + 2], vs[i + 1], vs[i]]                # odd: reversed (0x1408485xx)
        out.append((flags, tris))
        if ended:
            break
    return out


def complete_prop(recs, arc_models, cache, oi):
    """Stage props are ARC MODELS placed by list-5 nodes (STAGE-DRAW-GHIDRA.md); agents <= 0.3.40 cut every
    object at 4 KB / 8 records (stage 16: 9..18-mesh models shipped 5..7 records = part of the background
    missing). If the object's FIRST record is an arc model's first mesh (vertex identity, the 99.6% gate),
    keep the tape's own records (exact bytes) and append the arc model's remaining meshes as records:
    key = 0xC10 + texIndex, PCW/ISP/TSP from the mesh header (falling back to the object's own words),
    colour = (alpha, R, G, B), one triple group per mesh, centre/radius for the sort key."""
    if oi in cache:
        return cache[oi]
    out = recs
    if recs and recs[0].get('verts') and arc_models:
        v0 = {tuple(round(c, 2) for c in v[:3]) for v in recs[0]['verts']}
        for mi, meshes in arc_models.items():
            m0 = meshes[0]
            s0 = {tuple(round(c, 2) for c in v['pos']) for tri in m0['tris'] for v in tri}
            if not v0 or not s0 or len(v0 & s0) / len(v0) < 0.9:
                continue
            if len(meshes) > len(recs):
                r0 = recs[0]
                extra = []
                for m in meshes[len(recs):]:
                    verts = [(v['pos'][0], v['pos'][1], v['pos'][2], 0.0, 0.0, 0.0, v['uv'][0], v['uv'][1])
                             for tri in m['tris'] for v in tri]
                    if not verts:
                        continue
                    col = m.get('color') or [1.0, 1.0, 1.0]
                    ctr = m.get('center'); rad = m.get('radius')
                    if ctr is None:
                        xs = [v[0] for v in verts]; ys = [v[1] for v in verts]; zs = [v[2] for v in verts]
                        ctr = (sum(xs) / len(xs), sum(ys) / len(ys), sum(zs) / len(zs))
                        rad = max(((v[0] - ctr[0]) ** 2 + (v[1] - ctr[1]) ** 2 + (v[2] - ctr[2]) ** 2) ** 0.5 for v in verts)
                    ti = int(m.get('texIndex', 255))
                    extra.append(dict(tcw=0xC10 + ti, key='%08X' % (0xC10 + ti),
                                      pcw=int(m.get('baseParams', r0['pcw'])), isp=int(m.get('texInstr', r0['isp'])),
                                      tsp=int(m.get('tsp', r0['tsp'])), texnum=ti,
                                      colour=(float(m.get('alpha', 1.0)), float(col[0]), float(col[1]), float(col[2])),
                                      verts=verts, groups=[(0x8, verts)], centre=tuple(ctr), radius=float(rad), arc=True))
                out = list(recs) + extra
                complete_prop.stats[mi] = (len(recs), len(meshes))
            break
    cache[oi] = out
    return out
complete_prop.stats = {}


def decode_anodes(tape):
    """frame -> [node dict]; and the interned objects as [(header bytes, [records])]."""
    if not tape.get('anodes'):
        return {}, []
    ab = gzip.decompress(base64.b64decode(tape['anodes']))
    stride = int(tape.get('anodes_stride', 96))
    frames, off = {}, 0
    while off + 6 <= len(ab):
        fr, n = struct.unpack_from('<IH', ab, off)
        off += 6
        rows = []
        for _ in range(n):
            if off + stride > len(ab):
                break
            rows.append(dict(list=ab[off], flags=struct.unpack_from('<I', ab, off + 4)[0],
                             matrix=struct.unpack_from('<16f', ab, off + 8),
                             colour=struct.unpack_from('<3f', ab, off + 72),
                             obj=struct.unpack_from('<H', ab, off + 84)[0],
                             model=struct.unpack_from('<Q', ab, off + 88)[0],
                             # 0.3.39 (stride 100): node+0x90 alpha multiplier, applied on flag-bit-5
                             # nodes (FUN_140849c30/be0); < 1.0 forces the normal-blend preset 0x45
                             alpha=struct.unpack_from('<f', ab, off + 96)[0] if stride >= 100 else 1.0))
            off += stride
        frames[fr] = rows
    ob = gzip.decompress(base64.b64decode(tape.get('aobjs', ''))) if tape.get('aobjs') else b''
    objs = []
    if len(ob) >= 2:
        n = struct.unpack_from('<H', ob, 0)[0]
        o = 2
        for _ in range(n):
            if o + 4 > len(ob):
                break
            ln = struct.unpack_from('<I', ob, o)[0]
            body = ob[o + 4:o + 4 + ln]
            o += 4 + ln
            recs = []
            q = 0x18
            while q + 0x50 <= len(body):
                pcw = struct.unpack_from('<i', body, q)[0]
                if pcw >= 0:
                    break
                size = struct.unpack_from('<i', body, q + 0x4C)[0]
                hdr = body[q:q + 0x50]
                pay = body[q + 0x50:q + 0x50 + max(0, size)]
                # The record is a NaomiLib MESH (0x50 header: texCtrl/TCW @0x0C, texNum @0x20,
                # vertexColorMode @0x24 (-3 = coloured verts), alpha @0x2C, RGB @0x30, polyDataLen @0x4C)
                # followed by POLYGON GROUPS, not a flat vertex array. Steam's FUN_140848ee0 walks the
                # same records and its D3D draws are indexed TRIANGLE LISTS (gold: indexCount 6/9/42 =
                # 4/5/16-vertex strips expanded). nl_triangles() does that expansion (format facts:
                # rip_stage.py scan_model, ModNao scanModel.ts / getVertexAddressingMode.ts).
                groups = nl_groups(pay, struct.unpack_from('<i', hdr, 0x24)[0] == -3)
                verts = [v for _f, vs in groups for v in vs]
                # PCW/ISP/TSP @0/4/8 verbatim: Steam derives blend, sampler, depth preset and the
                # pixel-shader variant from them (tsp_state.codes, docs/TSP-RENDER-STATE-GHIDRA.md)
                pcw_w, isp_w, tsp_w = struct.unpack_from('<3I', hdr, 0)
                tcw = struct.unpack_from('<I', hdr, 0x0C)[0]
                # a SYNTHETIC tape (states_to_tape) stashes its page key in the header's spare words;
                # a real object has floats there -- accept only a clean 'sha_<16 hex>' or 8-hex key
                stash = hdr[0x10:0x30].rstrip(b'\x00')
                ok = stash.isascii() and ((stash.startswith(b'sha_') and len(stash) == 20 and stash[4:].isalnum())
                                          or (len(stash) == 8 and stash.isalnum()))
                key = stash.decode('ascii') if ok else '%08X' % tcw
                recs.append(dict(tcw=tcw, key=key, pcw=pcw_w, isp=isp_w, tsp=tsp_w, groups=groups,
                                 texnum=struct.unpack_from('<i', hdr, 0x20)[0],
                                 colour=struct.unpack_from('<4f', hdr, 0x2C), verts=verts,
                                 # NaomiLib bounding sphere @0x10..0x1C: the translucent sort key input
                                 # (FUN_140843320); a synthetic tape stashes its page key there (ok above)
                                 centre=None if ok else struct.unpack_from('<3f', hdr, 0x10),
                                 radius=None if ok else struct.unpack_from('<f', hdr, 0x1C)[0]))
                q += 0x50 + max(0, size)
            objs.append(recs)
    return frames, objs


PORTRAIT_DIR = os.path.join(HERE, 'portraits')
PORTRAIT_SLOT_K = (0, 3, 1, 4, 2, 5)     # DAT_140a6aac8: fighter slot -> HUD texHdr record offset k
PORTRAIT_ASSIST_PAGE = (1, 0, 3, 0)      # DAT_140a6aac4: fighter+0x655 (assist type) -> DAT page index
PORTRAIT_NAME_PAGE = 2                   # DC 0x0CE61000 - 0x0CE60000
PORTRAIT_TCW, PORTRAIT_NAME_TCW = 0xC9A, 0xCA0


def hud_portrait_pages(tape, base=None):
    """{'00000C9A': page, ...} for this tape's roster -- the twelve runtime-patched HUD slots.

    FUN_14060d560 (CONFIRMED, docs/PORTRAIT-PAGES-GHIDRA.md) rewrites HUD texHdr records 10+k (portrait) and
    16+k (name plate) for every fighter slot s, k = DAT_140a6aac8[s], from that fighter's own character DAT
    (AFS 3+cid, 16-bit LZSS, 0x800-B 32x32 RGB565 twiddled pages). The portrait page is
    DAT_140a6aac4[*(fighter+0x655)] and +0x655 is the ASSIST TYPE the tape already carries as `assist[slot]`;
    the name page is page 2 always. Empty when the rip is absent (the caller then keeps the old library page)."""
    base = base or PORTRAIT_DIR
    idxf = os.path.join(base, 'index.json')
    if not os.path.exists(idxf):
        return {}
    chars = (json.load(open(idxf)) or {}).get('chars') or {}
    p1, p2 = tape.get('p1_team') or [], tape.get('p2_team') or []
    assist = tape.get('assist') or [0] * 6
    out = {}
    for s in range(6):
        team, i = (p1, s // 2) if s % 2 == 0 else (p2, s // 2)
        if i >= len(team):
            continue
        ent = chars.get(str(int(team[i])))
        if not ent:
            continue
        k = PORTRAIT_SLOT_K[s]
        a = int(assist[s]) if s < len(assist) else 0
        for tcw, page in ((PORTRAIT_TCW + k, PORTRAIT_ASSIST_PAGE[a & 3]), (PORTRAIT_NAME_TCW + k, PORTRAIT_NAME_PAGE)):
            pv = (ent.get('pages') or [None] * 4)[page]
            fn = os.path.join(base, pv['file']) if pv else None
            if not fn or not os.path.exists(fn):
                continue
            im = Image.open(fn).convert('RGBA')
            out['%08X' % tcw] = dict(w=im.width, h=im.height, fmt=28, data=np.array(im).tobytes())
    return out


def scene_block(cam, variant):
    """The 432-byte scene constant block for camera (cx, cy, cz) and list variant 'list6'|'list7'."""
    m = scene_block.model[variant]
    sc = m['scale']
    cx, cy = cam[0] * sc, cam[1] * sc
    out = []
    for i in range(108):
        kind = m['model'][str(i)]
        if kind[0] == 'const':
            out.append(kind[1])
        else:
            a, b, c = kind[1]
            out.append(a * cx + b * cy + c)
    return struct.pack('<108f', *out)
scene_block.model = json.load(open(CAMERA_BLOCK)) if os.path.exists(CAMERA_BLOCK) else None


# ── THE TRANSLUCENT SORT (Ghidra, docs/TRANSLUCENT-SORT-GHIDRA.md; gate d3dcap/replay/sort_gate.py) ──
# Steam queues every draw with a category (FUN_1408436a0: PCW list type 0 -> 0, 1 -> 1, translucent -> 3;
# a flag-bit-5 node with alpha < 1 -> 3) and flushes (FUN_140843eb0 -> FUN_140842e30) categories 0, 1, 2 in
# SUBMISSION order and category 3 qsort'ed (MSVC CRT) by LAB_1408434d0: f32 key DESCENDING, ties by the
# submission sequence number ASCENDING. The key of a world record = w of [centre(rec+0x10) 1] x W x V x P
# (FUN_140843320; the Screen matrix's 4th column is (0,0,0,1)); radius(rec+0x1C) < 0 forces key = -radius.
# HUD lists (kind 0) skip V. A sprite record's key is the walker depth node+0x12C plus 0.001 per record
# (FUN_1406129f0), and FUN_1408432e0 turns THAT into the quad's vertex z = max(0, (P32 - D*P22)/D).
def scene_VP(scb):
    """(V, P) 4x4 row-vector matrices from a 432-B scene block (rows 7-10 = V, 15-18 = P; WORLD-CAMERA doc 3.1)."""
    V = np.array(struct.unpack_from('<16f', scb, 7 * 16), dtype=np.float32).reshape(4, 4)
    P = np.array(struct.unpack_from('<16f', scb, 15 * 16), dtype=np.float32).reshape(4, 4)
    return V, P


def sort_key_record(centre, radius, W16, V, P, hud=False):
    """FUN_140843320 for a record drawn with world matrix W16 (the node's +0xA8, row-vector order)."""
    if centre is None:
        return None
    if radius is not None and radius < 0:
        return float(-radius)
    W = np.array(W16, dtype=np.float32).reshape(4, 4)
    v = np.array([centre[0], centre[1], centre[2], 1.0], dtype=np.float32)
    return float((v @ ((W @ P) if hud else (W @ V @ P)))[3])


def sprite_vertex_z(D, P):
    """FUN_1408432e0: the sprite quad's vertex z from its depth key D under projection P (slot 3)."""
    D = np.float32(D)
    if D == 0:
        return 0.0
    z = (np.float32(P[3, 2]) - D * np.float32(P[2, 2])) / D
    return float(max(np.float32(0), z))


def order_draws(draws, legacy=False):
    """Two phases: categories 0/1 (Z-write) in submission order, then category 3 by (-key, submission).
    Draws without a key (no centre available) keep their submission slot among the cat-3 draws by taking
    the key of the previous keyed draw. Bit-13 draws inherit the cull state of the draw flushed before
    them (ring state, FUN_140849ac0 path)."""
    if legacy:
        for d in draws:
            for k in ('_cat', '_key', '_sub', '_inherit_cull'):
                d.pop(k, None)
        return draws
    stats = Counter()
    phase1 = [d for d in draws if d.get('_cat', 0) in (0, 1)]
    phase1.sort(key=lambda d: (d.get('_cat', 0), d.get('_sub', (9,))))
    phase3 = [d for d in draws if d.get('_cat', 0) not in (0, 1)]
    phase3.sort(key=lambda d: d.get('_sub', (9,)))
    last = 0.0
    for d in phase3:
        if d.get('_key') is None:
            d['_key'] = last
            stats['cat3 draw without a key (kept in submission slot)'] += 1
        last = d['_key']
    phase3.sort(key=lambda d: (-d['_key'], d.get('_sub', (9,))))
    out = phase1 + phase3
    prev = None
    for i, d in enumerate(out):
        if d.pop('_inherit_cull', False) and prev is not None and 'raster' in prev:
            d['raster'] = prev['raster']
        d['i'] = i
        prev = d
        stats['cat %d' % d.get('_cat', 0)] += 1
        for k in ('_cat', '_key', '_sub'):
            d.pop(k, None)
    order_draws.stats.update(stats)
    return out
order_draws.stats = Counter()


class WorldTemplate:
    """Pipeline state + PS constants lifted from real world-space draws of a captured frame."""
    KEYS = ('vs', 'ps', 'il', 'vsVariant', 'psVariant', 'psFog', 'samp', 'blend',
            'bfactor', 'smask', 'depth', 'raster', 'vp', 'scissor', 'stride')

    def __init__(self, path):
        man, B = load_pack_rrpk(path)
        self.inputLayouts = man['inputLayouts']
        self.draw = {}
        self.pscb = {}
        for d in man['draws']:
            if d.get('vsVariant') != 'vs_world':
                continue
            v = d.get('psVariant')
            if v in self.draw:
                continue
            self.draw[v] = {k: d[k] for k in self.KEYS}
            cbs = man['constantBuffers']
            self.pscb[v] = [bytes(B(cbs[h])) if (h and cbs.get(h) and cbs[h]['len'] != 432 and cbs[h]['len'] != 48) else None
                            for h in (d.get('pscbHash') or [])]
        # every distinct captured (ps, sampler, blend, depth, cull) of the world draws, so a state
        # PREDICTED from a record's TA header (tsp_state.predict) is served with the capture's own
        # D3D state objects -- stencil ops, ms flags and all -- never a hand-made desc
        self.by_state = {}
        for d in man['draws']:
            if d.get('vsVariant') == 'vs_world':
                self.by_state.setdefault(TS.state_key(TS.captured(d)), {k: d[k] for k in self.KEYS})
        # ── THE FRAME PREAMBLE (docs/FRAME-BACKGROUND-GHIDRA.md, gate bg_gate.py 3/3 packs byte-exact).
        # The scene RT is never cleared by ClearRenderTargetView: every captured frame starts with three
        # full-screen quads at z = 1 -- (i) the host's clear quad (FUN_14033c5c0(dev, 0x3f, black) at the
        # ring executor's entry: stride 28, blend off, DepthFunc ALWAYS, depth write, stencil REPLACE 0),
        # (ii) the engine's background quad (FUN_140843eb0, format 0x4000 -> the executor's 40-B layout,
        # texId 0xffff = the 1x1 white page, colour = bg_rule from blk+0x6CB4.. via FUN_1406101b0),
        # (iii) the depth+stencil clear at the first pass begin (FUN_14033c5c0(dev, 0x30): ps null, colour
        # mask 0). Their D3D state is copied from the capture; the vertices are synthesised (bg_gate.py
        # shows the executor's bytes are reproduced exactly).
        self.preamble, self.preamble_cb = [], []
        pre = man['draws'][:3]
        if (len(pre) == 3 and pre[0]['stride'] == 28 and pre[1]['stride'] == 40 and pre[2]['stride'] == 28
                and pre[2].get('ps') is None and pre[1]['tex'][0]
                and man['textures'][pre[1]['tex'][0]]['w'] == 1 and man['textures'][pre[1]['tex'][0]]['h'] == 1):
            for d in pre:
                self.preamble.append({k: d.get(k) for k in self.KEYS + ('vscbHash', 'pscbHash')})
                cbs = man['constantBuffers']
                self.preamble_cb.append({h: bytes(B(cbs[h])) for h in (d.get('vscbHash') or []) + (d.get('pscbHash') or [])
                                         if h and h in cbs})
        self.pages = {}
        idx = os.path.join(TCW_PAGES, 'index.json')
        if os.path.exists(idx):
            for k, v in json.load(open(idx)).items():
                self.pages[k] = v

    def select(self, pred, stats):
        """Template draw dict for a predicted state (tsp_state.predict): the captured draw whose
        state equals it exactly; else the ps-variant fallback with the predicted fields patched in
        (a None field = unknown/unmapped code = keep the fallback's value). `stats` counts which."""
        ps = pred.get('ps') if pred.get('ps') in self.draw else next(iter(self.draw))
        full = all(pred.get(f) is not None for f in TS.FIELDS)
        hit = self.by_state.get(TS.state_key(dict(pred, ps=ps))) if full else None
        if hit is not None:
            stats['exact captured state'] += 1
            return dict(hit), ps
        d = copy.deepcopy(self.draw[ps])
        if pred.get('samp') and d.get('samp') and d['samp'][0]:
            d['samp'][0].update(filter=pred['samp'][0], u=pred['samp'][1], v=pred['samp'][2], w=pred['samp'][2])
        if pred.get('blend') and d.get('blend'):
            d['blend'].update(src=pred['blend'][0], dst=pred['blend'][1])
        if pred.get('depth') and d.get('depth'):
            d['depth'].update(write=pred['depth'][0], sten=pred['depth'][1])
        if pred.get('cull') and d.get('raster'):
            d['raster']['cull'] = pred['cull']
        stats['patched fallback' if full else 'partial (unmapped code or no group)'] += 1
        return d, ps


def load_pack_rrpk(path):
    b = open(path, 'rb').read()
    n = struct.unpack_from('<I', b, 4)[0]
    man = json.loads(b[8:8 + n].decode('utf-8'))
    body = b[8 + n:]
    return man, (lambda r: body[r['off']:r['off'] + r['len']])


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
        # ⭐ PER-RECORD PALETTE ROW. The deployed _asm.json drops the record FLAGS word; bits 4-6 of
        # it are the palette row (SH4 expert: body cells row 0, Storm's lightning row 2, her
        # satellites row 1; roster histogram {0:7462, 0x10:1708, 0x20:747, 0x30:26}). On Steam the
        # row is applied by WHICH 256x1 palette the draw binds (the index pages are plain 1..15
        # under every palette -- measured, 0 texels > 15 in 130k). This is the "PL32 needs sub-row
        # 2" gap, closed: the sub-row is per RECORD, from the ROM, not per costume.
        self.rows, self.flags = {}, {}
        g = glob.glob('C:/Users/trist/projects/maplecast-flycast/dasm_PLDAT/Output/%s_DAT/*GFX_DATA_01.BIN' % self.name)
        if RIP and g:
            cells = RIP.read_cells(open(g[0], 'rb').read())[0]
            for sel, recs in (cells.items() if isinstance(cells, dict) else enumerate(cells)):
                self.rows[int(sel)] = [((r['flags'] >> 4) & 7) for r in (recs or [])]
                # per-record FLAGS: 0x8000 = hflip (XOR the node's facing), 0x4000 = vflip
                # (Steam walker, Ghidra chunk 0x140612f70; v3gate 100% with this mapping)
                self.flags[int(sel)] = [r['flags'] for r in (recs or [])]
        # GFX1 LOGICAL DIMS. Header [lw][lh][sw][sh] in 8 px units: a scale-walker record (sid
        # bit 15) draws lw*8 x lh*8 -- the top-left of the storage block -- and is PLACED by that
        # width (SH4 bank03 loc_8c0348c8). The deployed json carries STORAGE dims. Tiled bodies keep
        # storage dims. v3gate: 98.5% -> 100% on the super frames.
        self.dims = {}
        g0 = glob.glob('C:/Users/trist/projects/maplecast-flycast/dasm_PLDAT/Output/%s_DAT/*GFX_DATA_00.BIN' % self.name)
        if g0:
            b = open(g0[0], 'rb').read()
            n = struct.unpack_from('<I', b, 0)[0] >> 2
            for sel in range(n):
                o = struct.unpack_from('<I', b, sel * 4)[0]
                if o + 4 <= len(b):
                    lw, lh, sw, sh = b[o:o + 4]
                    self.dims[sel] = (sw, sh, lw, lh)

    def row_of(self, sel, ri):
        rows = self.rows.get(int(sel))
        return rows[ri] if rows and ri < len(rows) else 0

    def flag_of(self, sel, ri):
        fl = self.flags.get(int(sel))
        return fl[ri] if fl and ri < len(fl) else 0

    @classmethod
    def get(cls, base, cid):
        if cid not in cls._cache:
            try:
                cls._cache[cid] = cls(base, cid)
            except FileNotFoundError:
                cls._cache[cid] = None
        return cls._cache[cid]

    def part_bitmap(self, pid, vflip=True, logical=False):
        p = self.parts[str(pid)]
        a = self.idx[p['y']:p['y'] + p['h'], p['x']:p['x'] + p['w']]
        if logical and int(pid) in self.dims:
            sw, sh, lw, lh = self.dims[int(pid)]
            cw = lw * 8 if 0 < lw <= sw else p['w']
            ch = lh * 8 if 0 < lh <= sh else p['h']
            if (cw, ch) != (p['w'], p['h']):
                b = a[::-1][:ch, :cw]            # top-left in DC (top-down) orientation
                return (b.copy() if vflip else b[::-1].copy()), cw, ch
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
    ap.add_argument('--pal-lag', type=int, default=0,
                    help='TAPE v5 palrows: use the rows of frame-N (the bound LUT lags a mid-frame palette '
                         'change by >= 1 frame; exact lag not yet gated). Default 0 = same frame.')
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
    ap.add_argument('--no-world', action='store_true', help='ignore the v5 world-space stream')
    ap.add_argument('--legacy-order', action='store_true',
                    help='emit draws in the old dispatcher order (world 5/6, sprites, 7/8, HUD) instead of '
                         "Steam's two phases (Z-write categories in submission order, then category 3 sorted "
                         'by the FUN_140843320 key; docs/TRANSLUCENT-SORT-GHIDRA.md)')
    ap.add_argument('--world-template', default=WORLD_TEMPLATE)
    ap.add_argument('--legacy-torn-guard', action='store_true',
                    help='restore the ABSOLUTE torn draw-list test (n < 2); see the guard below')
    ap.add_argument('--no-preamble', action='store_true',
                    help='skip the three frame-preamble quads (host clear, FUN_140843eb0 background quad, '
                         'depth-only clear) and rely on the ClearRenderTargetView -- diagnostic only; the '
                         'background is then black on every frame (docs/FRAME-BACKGROUND-GHIDRA.md)')
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
    v3palrows = {}                        # frame -> (48 x pal index, 48 x flag); TAPE v5 `palrows`
    bank_slot, unknown_slots = {}, []     # filled after the nodes decode
    if tape.get('nodes'):
        nb = gzip.decompress(base64.b64decode(tape['nodes']))
        # v4 (agent 0.3.34+): 50 B = the 44 B v3 record + u16 angle (H+0x148, 0x10000 = 360 deg),
        # i16 hotx, i16 hoty (H+0x178, the rotation pivot). `nodes_stride` says which.
        stride = int(tape.get('nodes_stride', 44))
        off = 0
        while off + 6 <= len(nb):
            fr = struct.unpack_from('<I', nb, off)[0]
            n = struct.unpack_from('<H', nb, off + 4)[0]
            off += 6
            rows = []
            for _ in range(n):
                v = struct.unpack_from('<BBBbBBBBHHHBBBBHHHfffII', nb, off)
                angle, hotx, hoty = struct.unpack_from('<Hhh', nb, off + 44) if stride >= 50 else (0, 0, 0)
                # 0.3.38 (stride 54): u32 blk-relative offset of *(H+0x28) = the owning fighter's
                # H base (blk+0x3DB8+slot*0x738), or 0. Resolves the slot with no bank guess.
                owner_off = struct.unpack_from('<I', nb, off + 50)[0] if stride >= 54 else 0
                off += stride
                oslot = (owner_off - 0x3DB8) // 0x738 if owner_off >= 0x3DB8 and (owner_off - 0x3DB8) % 0x738 == 0 else -1
                rows.append(dict(kind=v[0], slot=v[1], cat=v[2], sort=v[3], layer=v[4], face=v[5],
                                 owner=v[6], drawn=v[7], sid=v[8], pal=v[9], zx=v[15] / 4096.0,
                                 fsx=v[18], fsy=v[19], depth=v[20], gfx1=v[21],
                                 angle=angle, hot=(hotx, hoty), oslot=oslot if 0 <= oslot < 6 else -1))
            v3nodes[fr] = rows
        pb = gzip.decompress(base64.b64decode(tape.get('pals', '')))
        for i in range(len(pb) // 32):
            pal = np.zeros((256, 4), np.uint8)
            for j in range(16):
                w = struct.unpack_from('<H', pb, i * 32 + j * 2)[0]
                pal[j] = ((w >> 8) & 15) * 17, ((w >> 4) & 15) * 17, (w & 15) * 17, ((w >> 12) & 15) * 17
            v3pals.append(pal)
        # TAPE v5 `palrows` (docs/PALETTE-SOURCE-GHIDRA.md s4): the ENGINE-RESOLVED palette rows, per
        # frame per fighter slot -- the 8 staging lines blk+0x1040+(0x10+8*slot+row)*0x38 that the
        # engine uploads to PALETTE_RAM and the draw binds as its 256x1 LUT (capgate 494/518 draws
        # byte-exact). `pal` above is DatPal+0 = costume 0 row 0 and is WRONG for any non-default
        # colour (5/5 fighters on the TTD gate) -- it is kept only for tapes without this key.
        # Record: [u32 frame][48 x u16 index into `pals` (slot*8+row)][48 x u8 flag (1 raw / 2 dim
        # pending, 0 uploaded)], stride from `palrows_stride` (148).
        if tape.get('palrows'):
            prb = gzip.decompress(base64.b64decode(tape['palrows']))
            pstride = int(tape.get('palrows_stride', 148))
            off = 0
            while off + pstride <= len(prb):
                pfr = struct.unpack_from('<I', prb, off)[0]
                idx = struct.unpack_from('<48H', prb, off + 4)
                flg = prb[off + 100:off + 148]
                v3palrows[pfr] = (idx, flg)
                off += pstride
            print('  TAPE v5 palrows: %d frames of 6x8 engine-resolved palette rows' % len(v3palrows))
        for _fr, _rows in v3nodes.items():
            for _n in _rows:
                if _n['kind'] == 0 and _n['gfx1']:
                    # the tape's gfx1 is the fighter's GFX1 TABLE POINTER (u32): unique per fighter, but its
                    # low 16 bits are 0x1020 for EVERY fighter (page-aligned tables), so the old `& 0xFFFF`
                    # key collapsed all six fighters onto one slot -> every bank-resolved object (hit sparks,
                    # cat 3: sids 1002..1006 in the OWNER's own sprite set) drew with the wrong character's rip.
                    bank_slot[_n['gfx1']] = _n['slot']
        unknown_slots = [s_ for s_ in range(6) if s_ not in set(bank_slot.values())]
        print('  TAPE v%d: %d frames of ordered nodes, %d palettes, stride %d' % (
            4 if stride >= 50 else 3, len(v3nodes), len(v3pals), stride))
    cols = [s.strip() for s in tape['schema'].strip('[]').split(',')]
    C = {n: i for i, n in enumerate(cols)}
    # 0.3.39 array columns carry their arity in the name (look[3], deck[3]); expose the bare name too
    for _n, _i in list(C.items()):
        if _n.endswith(']') and '[' in _n:
            C.setdefault(_n[:_n.index('[')], _i)
    # ── v5 world-space stream ──
    v5nodes, v5objs = decode_anodes(tape)
    wt = None
    if v5nodes and not a.no_world:
        if scene_block.model is None or not os.path.exists(a.world_template):
            print('  ⚠ world-space stream present but no camera_block.json / template pack -- skipping it')
        else:
            wt = WorldTemplate(a.world_template)
            stage_rip = None
            stage_preload = {}
            stage_geo = []
            arc_models, prop_cache = {}, {}          # arc deck geometry for the current frame (see emit_stage)
            stage_announced = []
            sid_ = tape.get('stage_id')
            if sid_ is not None and os.path.exists(os.path.join(STAGE_DIR, 'STG%02X.json' % int(sid_))):
                stage_rip = json.load(open(os.path.join(STAGE_DIR, 'STG%02X.json' % int(sid_))))
                print('  stage %02X: %d arc textures available (TCW 0xC10 + index)' % (int(sid_), len(stage_rip['textures'])))
                for _m in stage_rip['meshes']:
                    if _m.get('model', 0) != 0 and _m.get('tris'):
                        arc_models.setdefault(int(_m['model']), []).append(_m)
                # Prefer pages ripped with the HOST decode (rip_texbank.py --bank stage --stage XX --out
                # tcw_pages/stage_XX): rip_stage.py's PNGs use a transposed twiddle + wrong 565/1555
                # expansion (docs/TEXTURE-BANKS-GHIDRA.md, falsification arm 0/13). Same TCW keys.
                sdir = os.path.join(TCW_PAGES, 'stage_%02X' % int(sid_))
                sidx = os.path.join(sdir, 'index.json')
                if os.path.exists(sidx):
                    npre = 0
                    stage_preload = {}
                    sj = json.load(open(sidx))
                    for skey, sv in (sj.get('pages') or {k: v for k, v in sj.items() if k != 'meta'}).items():
                        if not isinstance(sv, dict) or 'file' not in sv:
                            continue
                        fn = os.path.join(sdir, sv['file'])
                        if os.path.exists(fn):
                            im = Image.open(fn).convert('RGBA')
                            stage_preload[skey] = dict(w=im.width, h=im.height, fmt=28, data=np.array(im).tobytes())
                            npre += 1
                    print('  stage %02X: %d host-decoded pages from %s' % (int(sid_), npre, sdir))
            elif sid_ is not None:
                print('  stage %s: no arc rip found in %s' % (sid_, STAGE_DIR))
            # pages shipped inside a synthetic tape (offline test) take precedence over the TCW library
            tape_pages = {}
            for _k, _v in (stage_preload or {}).items():   # host-decoded stage pages take precedence
                tape_pages.setdefault(_k, _v)
            for k, v in (tape.get('pages') or {}).items():
                tape_pages[k] = dict(w=v['w'], h=v['h'], fmt=v['fmt'], data=gzip.decompress(base64.b64decode(v['data'])))
            # RUNTIME-PATCHED HUD PORTRAIT / NAME PAGES (TCW 0xC9A..0xCA5).  The engine rewrites those twelve
            # texture slots at every match load from the SIX FIGHTERS' OWN character DATs (FUN_14060d560,
            # docs/PORTRAIT-PAGES-GHIDRA.md), so they are roster-dependent and the capture-derived TCW library's
            # copies belong to whatever roster was captured -- the bug that put Sentinel's portrait and name on a
            # Mag/Storm/Colossus tape.  Resolve them per tape from the character DATs instead:
            #     slot s -> k = DAT_140a6aac8[s] = {0,3,1,4,2,5}[s]      (exe, CONFIRMED)
            #     portrait TCW 0xC9A + k  <- DAT page DAT_140a6aac4[assist[s]] = {1,0,3,0}[assist[s]]
            #     name     TCW 0xCA0 + k  <- DAT page 2
            #     slot s is P1 team s/2 when s is even, P2 team s/2 when odd (select code + web.rs)
            for _k, _v in hud_portrait_pages(tape).items():
                tape_pages[_k] = _v
            print('  TAPE v5: %d frames of world-space nodes, %d objects, %d pages in tape, %d in library'
                  % (len(v5nodes), len(v5objs), len(tape_pages), len(wt.pages)))
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
    held, last_nodes = Counter(), None   # rows whose draw list was HELD from the previous row
    rotated_general = Counter()   # angle -> parts drawn through the general (ungated) rotation path
    world_state_total = Counter() # world draws by how WorldTemplate.select served their D3D state (tsp_state)
    bg_stats = Counter()          # frame preamble: where the background colour came from (bg_rule.from_row)

    # torn draw-list guard (see the block below): counts of the PRISTINE node lists, taken before the guard is
    # ever allowed to substitute into v3nodes, and the clock of every tape row (not just this slice, so the
    # forward scan can see past the end of the requested window exactly as rr-render does).
    TORN_FACTOR, TORN_SCAN = 2, 8
    node_counts = {k: len(v) for k, v in v3nodes.items()}
    all_clocks = [int(x[C['frame']]) for x in tape['frames']]
    row_i = a.start - 1
    for r in rows:
        row_i += 1
        verts, idxs, draws = bytearray(), [], []

        # ── FRAME PREAMBLE: the frame is cleared by DRAWS, not by a clear (review-re M2). Three full-screen
        # quads at z = 1 open every captured frame; the middle one carries the engine's background colour
        # (FUN_1406101b0: stage words blk+0x6CB8.. x the deck multiplier, or the fade/blackout colour). The
        # tape (0.3.42) ships the 24 input bytes; older tapes fall back to the per-stage table in bg_rule.
        # Vertex bytes and state are the executor's own layout, gated byte-exact on 3 packs (bg_gate.py).
        if wt is not None and wt.preamble and not a.no_preamble:
            bg = BG.from_row(r, C, tape.get('stage_id'), bg_stats)
            if bg is None:
                bg_stats['no colour (mode outside 0..3 / no table entry) -> black'] += 1
                bg = (0, 0, 0)
            bcols = BG.vertex_colours(bg)
            q28 = b''.join(struct.pack('<4f', x, y, 1.0, 0.0) + bytes(12) for x, y in ((-1, 1), (1, 1), (-1, -1), (1, -1)))
            q40 = b''.join(struct.pack('<4f', x, y, 1.0, 0.0) + struct.pack('<2f', 0.0, 1.0) + bytes(c) + bytes(4)
                           + struct.pack('<2f', 0.0, 0.0)
                           for (x, y), c in zip(((-1, 1), (-1, -1), (1, 1), (1, -1)), bcols))
            if 'bg_white' not in textures:            # texId 0xffff = the executor's 1x1 white placeholder page
                textures['bg_white'] = {'w': 1, 'h': 1, 'fmt': 28, **intern(bytes([255, 255, 255, 255]))}
            voffs = (0, len(q28), len(q28) + len(q40))
            verts.extend(q28); verts.extend(q40); verts.extend(q28)
            verts.extend(bytes((-len(verts)) % STRIDE))   # keep len(verts)//STRIDE exact for every later draw
            for k, (d0, vo) in enumerate(zip(wt.preamble, voffs)):
                for h, b in wt.preamble_cb[k].items():
                    cb_recs.setdefault(h, {**intern(b)})
                fi = len(idxs)
                idxs.extend((0, 1, 2, 2, 1, 3))           # the capture's index order for all three quads
                d = dict(d0)
                d.update({'i': len(draws), 'firstIndex': fi, 'indexCount': 6, 'stride': d0['stride'], 'voff': vo,
                          'tex': ['bg_white' if k >= 1 else None, None]})
                d['_cat'], d['_key'], d['_sub'] = 0, None, (-1, k)    # Z-write phase, ahead of every scene draw
                draws.append(d)

        # ── ONE ordered list of bodies AND objects ───────────────────────────────────────────────
        # ⭐ `layer` is the ordering field, and it is carried on BOTH: the six fighter slots have
        # layer[6] (255 = not drawn) and every object row has its own. They share one space, 3..11.
        # Tris asked "there has to be a pointer or function telling that object what order to draw
        # in" -- this is it, and it is already in every tape we have recorded.
        items = []
        fr_clock = int(r[C['frame']])
        # ⚠ DATA GAPS ARE HELD, NOT DRAWN EMPTY. A row whose clock has no nodes entry (the agent
        # got no draw list for it) or a torn partial list (1 node where the neighbours have many --
        # the engine clears and rebuilds the list every frame, a read mid-rebuild sees a stub) used
        # to become a frame with zero draws: the player's per-draw uniform buffer is then size 0 and
        # WebGPU refuses the bind group ("Binding size (160) is larger than the size (0)"). Playback
        # now HOLDS the previous frame's draw list for those rows and reports how many; the tape
        # data itself is untouched. The fix at the source is the agent's read timing (v4c).
        # The torn test is RELATIVE and ADDITIVE (2026-09-04, mirrored in rr-render sprites.rs emit_row).
        # The old test was ABSOLUTE -- len(cur) < 2 -- so it caught only a total collapse; on prod tape
        # ..._59618234 row 851 the list goes 24 -> 2 -> 24 and was DRAWN, popping every effect and one
        # fighter out for a single frame. A row is now also torn when it holds less than 1/TORN_FACTOR of
        # what BOTH neighbours agree on. RECOVERY is the discriminator: nothing in the engine removes draws
        # and restores them within one 1/60 s frame, while a legitimate shrink (a super ending, a KO)
        # persists into the next row and is therefore never held. The forward scan steps over a run of
        # consecutive torn rows to find that recovery. TORN_FACTOR = 2 is a stated margin, not a fit;
        # TORN_SCAN = 8 is the engine's own GGPO rollback horizon. Every row the old test held is still
        # held -- the change only ADDS rows. --legacy-torn-guard restores the old test exactly.
        if v3nodes:
            cur = v3nodes.get(fr_clock)
            torn = False
            if cur is not None and last_nodes is not None:
                torn = len(cur) < 2 and len(last_nodes) >= 3
                if not torn and not a.legacy_torn_guard:
                    prev, nxt = len(last_nodes), None
                    for k in range(1, TORN_SCAN + 1):
                        if row_i + k >= len(all_clocks):
                            break
                        m = node_counts.get(all_clocks[row_i + k])
                        if m is not None and m * TORN_FACTOR >= prev:
                            nxt = m
                            break
                    if nxt is not None:
                        torn = len(cur) * TORN_FACTOR < min(prev, nxt)
            if cur is None or torn:
                if cur is None:
                    key = 'no nodes'
                elif len(cur) < 2 and len(last_nodes) >= 3:
                    key = 'torn (%d node)' % len(cur)
                else:
                    key = 'torn (%d of %d nodes)' % (len(cur), len(last_nodes))
                held[key] += 1
                if last_nodes is not None:
                    v3nodes[fr_clock] = last_nodes
            else:
                last_nodes = cur
        if v3nodes:
            # v3: the order IS the payload. No sort below is applied; `kind` picks the atlas lookup.
            # ⭐ PAINT ORDER IS DEPTH ORDER, NOT WALK ORDER (v3gate.py, 3 frames at 100.00%). Steam
            # z-sorts every submitted quad, far to near: layers by LayerZ (lower index nearer for
            # 0..7; 8..11 nearest per the DC table, flagged), then REVERSE registration order within
            # a layer, then reverse record order within a node. The stream index is the registration
            # order within its layer, so the key is (-LayerZ[layer], -index).
            LAYERZ = [15, 17, 19, 21, 23, 25, 27, 29, 10, 11, 12, 13, 30, 31, 32, 33]
            ordered = sorted(enumerate(v3nodes.get(fr_clock, ())),
                             key=lambda t: (-LAYERZ[t[1]['layer'] & 15], -t[0]))
            for _si, nd in ordered:
                if nd['kind'] == 0:
                    cid = (p1 if nd['slot'] % 2 == 0 else p2)[nd['slot'] // 2]
                else:
                    owner = nd['owner']
                    if owner > 5:
                        # an OWNERLESS pool object (owner 0xFF: spawned by another object, assist
                        # attacks, global supers) still carries its GFX1 bank, and every effect inherits
                        # its character's bank by struct copy -- the bank names the character. Bank
                        # identity is the low 16 bits (0x381714 == 0x1714 + a flag byte). Resolve
                        # through the slot->bank map of the whole tape, and when the bank is seen on no
                        # fighter node (a parked fighter carries gfx1 == 0) by ELIMINATION if exactly one
                        # slot has no known bank. First v5 tape: 13% of objects were this class.
                        b = nd['gfx1']           # full pointer (see bank_slot)
                        if nd.get('oslot', -1) >= 0:
                            owner = nd['oslot']          # 0.3.38 raw owner link
                        elif b in bank_slot:
                            owner = bank_slot[b]
                        elif len(unknown_slots) == 1:
                            owner = unknown_slots[0]
                    if owner > 5:
                        missing['object with owner %d (unowned, gfx1 %08X unmatched)' % (nd['owner'], nd['gfx1'])] += 1
                        continue
                    cid = (p1 if owner % 2 == 0 else p2)[owner // 2]
                # mirror = the node's facing ONLY. sid bit 15 selects the record FORMAT (the
                # scale walker), it is not a flip (Ghidra FUN_1406129f0; v3gate 100% with this).
                mir = bool(nd['face'])
                items.append((0, Atlas.get(a.atlas, cid), nd['sid'] & 0x7FFF, nd['fsx'], nd['fsy'],
                              mir, 'body' if nd['kind'] == 0 else 'obj', nd['pal'],
                              dict(bit15=bool(nd['sid'] & 0x8000), angle=nd.get('angle', 0), hot=nd.get('hot', (0, 0)),
                                   walk=_si, depth=nd.get('depth'),
                                   pslot=(nd['slot'] if nd['kind'] == 0 else owner), pframe=fr_clock)))
        for slot in range(6 if not v3nodes else 0):
            if not r[C['drawn[6]']][slot]:
                continue
            lay = r[C['layer[6]']][slot] if 'layer[6]' in C else 8
            sid_raw = int(r[C['sid[6]']][slot])
            items.append((lay, Atlas.get(a.atlas, (p1 if slot % 2 == 0 else p2)[slot // 2]),
                          sid_raw & 0x7FFF,
                          r[C['sx[6]']][slot], r[C['sy[6]']][slot],
                          bool(r[C['facing[6]']][slot]), 'body', costume[slot],
                          dict(bit15=bool(sid_raw & 0x8000), angle=0, hot=(0, 0))))
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
                          bool(face), 'obj', costume[owner],       # facing only; bit 15 is not a flip
                          dict(bit15=bool(sid_raw & 0x8000), angle=0, hot=(0, 0))))

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

        world_missing = Counter()
        world_state = Counter()             # how each world draw's D3D state was served (WorldTemplate.select)
        sub_seq = [0]                       # submission sequence within the frame (the qsort tie-break)
        def next_sub():
            sub_seq[0] += 1
            return sub_seq[0]
        # slot 3 during the sprite walk = the world camera P (FUN_14061d7e0 is called per sprite node)
        Vs, Ps = (None, None)
        if scene_block.model is not None:
            Vs, Ps = scene_VP(scene_block((float(r[C['eyeX']]) if 'eyeX' in C else 0.0,
                                           float(r[C['eyeY']]) if 'eyeY' in C else 0.0), 'list6'))
        last_cull = [None]                  # ring cull state carried across draws (FUN_140849ac0 path)
        def emit_stage(cam, deck_col=(1.0, 1.0, 1.0)):
            """The loaded stage's 3D deck from the ARC RIP (STGxx.json model 0), not from a capture.
            Model 0 of every stage is the world-placed deck+skydome at an IDENTITY world matrix
            (rip_stage.py, re_kb 26; the STG00 tape renderer drew it that way with real pixels).
            Its vertices are in the same units as the tape's list-5/6 stage objects (the stage-5
            tape's objects match the STG05 meshes vertex-for-vertex), so they go through the same
            vs_world path with CBWorld = identity and the list-6 scene block from the tape camera.
            Props (models 1..N) have runtime matrices the rip does not carry; only the ones that
            arrive as tape nodes are drawn (by emit_world). Geometry is appended ONCE per seq."""
            if not wt or stage_rip is None:
                return
            # vertex/index buffers are PER FRAME ('vb' is interned per frame), so the deck geometry is
            # appended into every frame's buffers; only the mesh->page prep is cached across frames.
            if stage_geo:
                stage_geo.clear()
            if True:
                for mi, mesh in enumerate(stage_rip['meshes']):
                    if mesh.get('model', 0) != 0 or not mesh.get('placed', True) or not mesh['tris']:
                        continue
                    ti = int(mesh['texIndex'])
                    key = '%08X' % (0xC10 + ti)
                    page = tape_pages.get(key)
                    if page is None and 0 <= ti < len(stage_rip['textures']):
                        fn = os.path.join(STAGE_DIR, stage_rip['textures'][ti]['file'])
                        if os.path.exists(fn):
                            im = Image.open(fn).convert('RGBA')
                            page = tape_pages[key] = dict(w=im.width, h=im.height, fmt=28, data=np.array(im).tobytes())
                    if page is None and ti == 255:
                        # UNTEXTURED mesh (NL texIndex 255): drawn with vertex colour only. STG10 mesh 0 is the
                        # SKY -- a 6-tri box x +-53k, z -103k..-42k with a blue-grey -> pink gradient in the
                        # vertex colours; skipping it left the sky black. A 1x1 white page through the same
                        # modulate shader == vertex colour, so no new pipeline variant is needed.
                        key = 'FLAT_WHITE'
                        page = tape_pages.get(key) or tape_pages.setdefault(key, dict(w=1, h=1, fmt=28, data=bytes([255, 255, 255, 255])))
                    if page is None:
                        world_missing['stage mesh %d: no texture %d' % (mi, ti)] += 1
                        continue
                    tkey = 'world_%s' % key
                    if tkey not in textures:
                        textures[tkey] = {'w': page['w'], 'h': page['h'], 'fmt': page['fmt'], **intern(page['data'])}
                    first = len(verts) // STRIDE
                    nv = 0
                    for tri in mesh['tris']:
                        for vtx in tri:
                            x, y, z = vtx['pos']
                            u, v = vtx['uv']
                            c = vtx.get('col') or (255, 255, 255, 255)
                            c = (min(255, int(c[0] * deck_col[0])), min(255, int(c[1] * deck_col[1])),
                                 min(255, int(c[2] * deck_col[2])), c[3])
                            verts.extend(struct.pack('<4f', x, y, z, 0.0))
                            verts.extend(struct.pack('<2f', 0.0, 0.0))
                            verts.extend(bytes((int(c[0]), int(c[1]), int(c[2]), int(c[3]))))   # R,G,B,A (see world pass)
                            verts.extend(bytes((0, 0, 0, 0)))
                            verts.extend(struct.pack('<2f', u, v))
                            nv += 1
                    fi = len(idxs)
                    idxs.extend(range(first, first + nv))
                    if mesh.get('center') is not None:
                        centre, radius = tuple(mesh['center']), mesh.get('radius')
                    else:
                        # old rip without the header sphere: vertex centroid stands in (counted)
                        pts = [vtx['pos'] for tri in mesh['tris'] for vtx in tri]
                        centre = tuple(sum(p[k] for p in pts) / len(pts) for k in range(3)); radius = None
                        world_missing['deck mesh %d: sort centre from the vertex centroid (rip lacks the header sphere)' % mi] += 1
                    stage_geo.append(dict(fi=fi, nv=nv, tkey=tkey, opaque=bool(mesh.get('isOpaque', True)),
                                          centre=centre, radius=radius,
                                          # the mesh's own TA header words, when the rip carries them
                                          # (rip_stage.py: baseParams = PCW @0, texInstr = ISP @4, tsp @8)
                                          hdr=(mesh.get('baseParams'), mesh.get('texInstr'), mesh.get('tsp'))))
                if not stage_announced:
                    stage_announced.append(1)
                    print('  stage %02X: %d model-0 meshes from the arc, %d vertices (per frame)' % (
                        int(stage_rip['stageId']), len(stage_geo), sum(g['nv'] for g in stage_geo)))
            ident = struct.pack('<12f', 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0)
            scb = scene_block(cam, 'list6')
            hw = sha8(ident); hs = sha8(scb)
            cb_recs.setdefault(hw, {**intern(ident)})
            cb_recs.setdefault(hs, {**intern(scb)})
            Vd, Pd = scene_VP(scb)
            IDENT16 = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
            for g in stage_geo:
                if g['hdr'][2] is not None:
                    # state from the mesh's PCW/ISP/TSP exactly as for a tape record (kind 2 =
                    # FUN_140849c10 deck draw). The rip flattens the polygon groups, so the per-group
                    # cull word is unavailable here: cull = None keeps the template's raster (fallback).
                    pred = TS.predict(g['hdr'][0], g['hdr'][1], g['hdr'][2], 0, kind=2)
                    pred['cull'] = None
                    d, ps_variant = wt.select(pred, world_state)
                else:
                    ps_variant = 'opaque' if g['opaque'] else 'texalpha'     # old rip: ModNao isOpaque rule
                    if ps_variant not in wt.draw:
                        ps_variant = next(iter(wt.draw))
                    d = dict(wt.draw[ps_variant])
                pscb = [(sha8(b) if b else None) for b in wt.pscb.get(ps_variant, [])]
                for b in wt.pscb.get(ps_variant, []):
                    if b:
                        cb_recs.setdefault(sha8(b), {**intern(b)})
                pscb = [(pscb[0] if pscb else None), hs, (pscb[2] if len(pscb) > 2 else None), None]
                d.update({'i': len(draws), 'firstIndex': g['fi'], 'indexCount': g['nv'], 'stride': STRIDE, 'voff': 0,
                          'tex': [g['tkey'], None], 'vscbHash': [hw, hs, None, None], 'pscbHash': pscb})
                # category from the PCW list type (kind 2 deck draw, FUN_1408436a0); old rips: isOpaque
                ltype = ((g['hdr'][0] >> 24) & 7) if g['hdr'][0] is not None else (0 if g['opaque'] else 2)
                d['_cat'] = 0 if ltype == 0 else (1 if ltype == 1 else 3)
                d['_key'] = sort_key_record(g['centre'], g['radius'], IDENT16, Vd, Pd) if d['_cat'] == 3 else None
                d['_sub'] = (1, next_sub())
                draws.append(d)

        def emit_world(lists):
            """Append vs_world draws for this frame's nodes in `lists`, in list order."""
            if not wt:
                return
            rows_w = v5nodes.get(fr_clock, ())
            cam = (float(r[C['eyeX']]) if 'eyeX' in C else 0.0, float(r[C['eyeY']]) if 'eyeY' in C else 0.0,
                   float(r[C['zoom']]) if 'zoom' in C else 812.357)
            if lists[0] == 5:
                # 0.3.39 rows: blackout gate blk+0x3D50 (!= 0 -> no deck draw, FUN_140620960) and the
                # deck colour multiplier blk+0x6CA8 (FUN_140849b00 before the model-0 walk)
                blackout = int(float(r[C['blackout']])) if 'blackout' in C else 0
                cam_state = (int(float(r[C['cam_state']])) & 0xFF) if 'cam_state' in C else 0   # byte at blk+0x6908; 1 = scripted camera (not yet rendered: closed form needs look/fov/yoff/roll)
                deck_col = tuple(float(x) for x in r[C['deck']]) if 'deck' in C and isinstance(r[C['deck']], (list, tuple)) else (1.0, 1.0, 1.0)
                if not blackout:
                    emit_stage(cam, deck_col)
            # FUN_140620960 (docs/STAGE-DRAW-GHIDRA.md s3): while G+0x98 (blk+0x3D50) != 0 the deck AND list 5
            # (stage props) are skipped; list 6 and everything after still draw. Drawing the props over a
            # missing deck was the "half the background is gone" super-blackout look.
            if 'blackout' in C and int(float(r[C['blackout']])) and 5 in lists:
                lists = tuple(L for L in lists if L != 5)
            for nd in rows_w:
                if nd['list'] not in lists or nd['obj'] >= len(v5objs):
                    if nd['list'] in lists and nd['model']:
                        world_missing['3D model node (list %d)' % nd['list']] += 1
                    continue
                # scene CB per list (Ghidra, docs/STAGE-DRAW-GHIDRA.md + WORLD-CAMERA-GHIDRA.md): deck/5/6/12 =
                # world camera FUN_14061d7e0; 7/8/9 = x0.1 camera FUN_14061d6a0; HUD 0xB/0xD = FUN_14061d5b0
                # (angle 0x4000, V = I -> the camera-independent block 04E19F4C). Gold frame 4445: 171/177
                # list-11 draws bind 04E19F4C -- the old 'list6' choice projected the HUD with the world camera.
                variant = 'hud' if nd['list'] in (11, 13) else ('list6' if nd['list'] in (5, 6, 12) else 'list7')
                m = nd['matrix']
                cbw = struct.pack('<12f', m[0], m[4], m[8], m[12], m[1], m[5], m[9], m[13], m[2], m[6], m[10], m[14])
                scb = scene_block(cam, variant)
                Vn, Pn = scene_VP(scb)
                rank = {5: 2, 6: 3, 7: 4, 8: 5, 9: 5, 11: 6, 12: 7, 13: 6}.get(nd['list'], 8)   # FUN_140620960 submission order
                hw = sha8(cbw); hs = sha8(scb)
                cb_recs.setdefault(hw, {**intern(cbw)})
                cb_recs.setdefault(hs, {**intern(scb)})
                objrecs = v5objs[nd['obj']]
                if nd['list'] == 5 and stage_rip is not None:
                    objrecs = complete_prop(objrecs, arc_models, prop_cache, nd['obj'])
                for rec in objrecs:
                    key = rec['key']
                    page = tape_pages.get(key)
                    if page is None and key in wt.pages:
                        pv = wt.pages[key]
                        fn = os.path.join(TCW_PAGES, pv.get('file', 'tcw_%s_%dx%d_f%d.png' % (key, pv['w'], pv['h'], pv['fmt'])))
                        if os.path.exists(fn):
                            im = Image.open(fn)
                            data = np.array(im.convert('RGBA')).tobytes() if pv['fmt'] != 61 else np.array(im)[:, :, 0].tobytes()
                            page = tape_pages[key] = dict(w=pv['w'], h=pv['h'], fmt=pv['fmt'], data=data)
                    if page is None and stage_rip is not None and key.isalnum() and len(key) == 8:
                        # STAGE TEXTURES COME FROM THE ARC RIP: TCW = 0xC10 + texture index of the
                        # loaded stage's TEX list (learned on the stage-5 tape 59613255: its list-6
                        # objects' vertices match the STG05 meshes exactly and 0xC11..0xC1A map to
                        # texIndex 1..10). stage_id from the tape (blk+0x6D04, agent >= 0.3.36).
                        ti = int(key, 16) - 0xC10
                        if 0 <= ti < len(stage_rip['textures']):
                            tx = stage_rip['textures'][ti]
                            fn = os.path.join(STAGE_DIR, tx['file'])
                            if os.path.exists(fn):
                                im = Image.open(fn).convert('RGBA')
                                page = tape_pages[key] = dict(w=im.width, h=im.height, fmt=28, data=np.array(im).tobytes())
                    if page is None:
                        world_missing['no page for %s' % key] += 1
                        continue
                    tkey = 'world_%s' % key
                    if tkey not in textures:
                        textures[tkey] = {'w': page['w'], 'h': page['h'], 'fmt': page['fmt'], **intern(page['data'])}
                    # ── render state from the record's OWN TA header, not a flag heuristic. Steam's
                    # consumer FUN_1408482a0 reads PCW/ISP/TSP (blend = TSP src/dst alpha instr,
                    # sampler = TSP filter/clamp/flip bits, depth preset = PCW list type + ISP bit 26,
                    # ps variant = TSP bit 19 ignore-tex-alpha); the node flags pick the draw KIND in
                    # FUN_140620cd0 (docs/TSP-RENDER-STATE-GHIDRA.md; tsp_state.codes). Gate on 4
                    # capgate packs vs the stage-11 tape: sampler/depth/cull/ps 776/776, blend 772/776.
                    #   bit 5  -> FUN_140849c30/be0(obj, node+0x90): kind 3 with an ALPHA MULTIPLIER
                    #             the tape does not carry (1.0 assumed; when it is < 1.0 Steam forces
                    #             normal blending via ctx+0x1f8274 = 0x45 -- the 4 gate misses)
                    #   bit 13 -> FUN_140849ac0: kind 2 with param 2 = no cull command (ring state
                    #             keeps the previous draw's cull)
                    #   lists 0xB/0xD -> FUN_1408499e0: kind 0 (HUD perspective), same state rules
                    kind = 3 if (nd['flags'] & 0x20) else (0 if nd['list'] in (11, 13) else 2)
                    # ── vertex colour0 = record colour (alpha @0x2C, RGB @0x30) x node colour: bits
                    # 10/11 of the flags select 1.0 / node+0x94 / blk+0x6CA8 / the product
                    # (FUN_140620cd0 -> FUN_140849b00 -> ctx+0x1f825c..64), then FUN_1408482a0 packs
                    # (int)(c * 255 * mult) clamped to 255 as ARGB (bytes B,G,R,A). blk+0x6CA8.. is
                    # not in the tape (1.0 assumed). Gate: 647/776 exact with all multipliers 1.0; the
                    # rest are node multipliers (127 = 0.5 etc.).
                    col = rec['colour']
                    cm = tuple(nd['colour']) if (nd['flags'] & 0x400) else (1.0, 1.0, 1.0)
                    # 0.3.39: bit-5 nodes multiply the record alpha by node+0x90 (tape 'alpha'; 1.0 on
                    # older tapes) -- the render-state gate's only blend residual (4/824)
                    amult = min(1.0, float(nd.get('alpha', 1.0))) if (nd['flags'] & 0x20) else 1.0
                    # VB colour is R8G8B8A8 in R,G,B,A byte order: gold HUD-block draws carry ff0000ff (red
                    # damage) and ffff00ff (yellow bar) -- under B,G,R,A those would be blue/cyan, which is
                    # exactly what the first stage-13 render showed. Record floats: alpha @0x2C, R,G,B @0x30.
                    cbytes = bytes((min(255, max(0, int(col[1] * 255 * cm[0]))),
                                    min(255, max(0, int(col[2] * 255 * cm[1]))),
                                    min(255, max(0, int(col[3] * 255 * cm[2]))),
                                    min(255, max(0, int(col[0] * 255 * amult)))))
                    for gflags, gverts in rec['groups']:          # one polygon GROUP = one D3D draw
                        if not gverts:
                            continue
                        pred = TS.predict(rec['pcw'], rec['isp'], rec['tsp'], gflags, kind=kind, alpha_mult=amult)
                        if nd['flags'] & 0x2000:
                            pred['cull'] = last_cull[0]           # kind-2/param-2 path sends no cull word
                        elif pred['cull'] is not None:
                            last_cull[0] = pred['cull']
                        tdraw_w, ps_variant = wt.select(pred, world_state)
                        # queue category (FUN_1408436a0): list type 0 -> cat 0 (kind 3 with alpha < 1 -> cat 3),
                        # 1 -> cat 1, 2/3/4 -> cat 3 with the record-centre key
                        ltype = (rec['pcw'] >> 24) & 7
                        cat = 0 if ltype == 0 else (1 if ltype == 1 else 3)
                        if ltype == 0 and kind == 3 and amult < 1.0:
                            cat = 3
                        skey = sort_key_record(rec.get('centre'), rec.get('radius'), m, Vn, Pn, hud=(kind == 0)) if cat == 3 else None
                        if cat == 3 and skey is None:
                            world_missing['record without a sort centre (synthetic tape)'] += 1
                        first = len(verts) // STRIDE
                        for (x, y, z, nx, ny, nz, u, v) in gverts:
                            verts.extend(struct.pack('<4f', x, y, z, 0.0))
                            verts.extend(struct.pack('<2f', nx, ny))
                            verts.extend(cbytes)
                            verts.extend(bytes((0, 0, 0, 0)))
                            verts.extend(struct.pack('<2f', u, v))
                        nv = len(gverts)
                        fi = len(idxs)
                        idxs.extend(range(first, first + nv))
                        pscb = [(sha8(b) if b else None) for b in wt.pscb.get(ps_variant, [])]
                        for b in wt.pscb.get(ps_variant, []):
                            if b:
                                cb_recs.setdefault(sha8(b), {**intern(b)})
                        pscb = [(pscb[0] if pscb else None), hs, (pscb[2] if len(pscb) > 2 else None), None]
                        d = dict(tdraw_w)
                        d.update({'i': len(draws), 'firstIndex': fi, 'indexCount': nv, 'stride': STRIDE, 'voff': 0,
                                  'tex': [tkey, None], 'vscbHash': [hw, hs, None, None], 'pscbHash': pscb})
                        d['_cat'], d['_key'], d['_sub'] = cat, skey, (rank, next_sub())
                        if nd['flags'] & 0x2000:
                            d['_inherit_cull'] = True
                        draws.append(d)
        emit_world((5, 6, 12, 13))          # stage: behind the sprites
        for lay, at, sid, tsx, tsy, mir, kind, cos, extra in items:
            if at is None:
                missing['no atlas'] += 1
                continue
            recs = at.asm.get(str(sid))
            if not recs:
                missing['%s %s sel %d' % (at.name, kind, sid)] += 1
                continue
            # engine truncates the 640x480 coord to an integer before placement (see v3gate.py);
            # floor vs trunc for negatives is unmeasured -- flag
            ox, oy = np.floor(tsx) * TAPE_X, np.floor(tsy) * TAPE_Y
            if a.flip_facing:
                mir = not mir

            # TAPE v5: the engine's own staged rows for this fighter slot (slot*8 + row) -- no LUT
            # locate, no costume rule; row = the record's palette sub-row (rec.flags >> 4, `row_of`),
            # exactly the bank the slot table carries (FUN_140612180). --pal-lag N reads the rows of
            # an earlier frame (the bound LUT lags a mid-frame palette change by >= 1 frame, INFERRED).
            prow = None
            if v3palrows and a.bank is None and 0 <= extra.get('pslot', -1) < 6:
                pf = extra.get('pframe')
                for _lag in range(a.pal_lag, -1, -1):
                    if (pf - _lag) in v3palrows:
                        prow = v3palrows[pf - _lag]; break
            if prow is not None:
                _ps = extra['pslot'] * 8
                base_pal = v3pals[prow[0][_ps]] if prow[0][_ps] < len(v3pals) else v3pals[cos]
                blk_base = None
            elif v3nodes and a.bank is None and 0 <= cos < len(v3pals):
                base_pal = v3pals[cos]                 # v3: `cos` is the resolved palette index
                blk_base = None                        # locate its row-0 in the LUT for sibling rows
                for bi, bk in enumerate(at.banks):
                    if all(list(bk[i]) == base_pal[i].tolist() for i in range(16)):
                        blk_base = bi - (bi % 8); break
            else:
                base_pal = at.palette(a.bank, cos); blk_base = None
            pal_cache = {}
            def pal_for_row(row):
                if prow is not None:
                    if row == 0:
                        return base_pal
                    _pi = prow[0][extra['pslot'] * 8 + (row & 7)]
                    return v3pals[_pi] if _pi < len(v3pals) else base_pal
                if row == 0 or blk_base is None or blk_base + row >= len(at.banks):
                    return base_pal
                if row not in pal_cache:
                    pal_cache[row] = at.palette(blk_base + row, 0)
                return pal_cache[row]

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
            for ri, rec in (enumerate(recs) if a.forward_records else reversed(list(enumerate(recs)))):
                pid = rec['part']
                if str(pid) not in at.parts:
                    continue
                pal = pal_for_row(at.row_of(sid, ri))
                palkey = '%s_pal_%s' % (at.name, sha8(pal.tobytes()))
                if palkey not in textures:
                    textures[palkey] = {'w': 256, 'h': 1, 'fmt': 28, **intern(pal.tobytes())}
                fl = at.flag_of(sid, ri)
                hf, vf = bool(fl & 0x8000), bool(fl & 0x4000)
                # scale-walker records (sid bit 15) sample only the logical rect; tiled records draw
                # the FULL storage block (see the placement below for how a flip is anchored).
                bmp, pw, ph = at.part_bitmap(pid, not a.no_vflip, logical=extra['bit15'])
                sw, sh, lw, lh = at.dims.get(int(pid), (0, 0, 0, 0))
                Lw = lw * 8 if 0 < lw <= sw else pw
                Lh = lh * 8 if 0 < lh <= sh else ph
                # per-record flags: vflip in the bitmap; hflip in the bitmap too -- the node's mirror
                # is applied by the UV winding below, so the net is (mir XOR hf), as on Steam.
                if vf:
                    bmp = bmp[::-1]
                if hf:
                    bmp = bmp[:, ::-1]
                # ROTATION (SH4 bank03 loc_8c03481c; v3gate 24/24): +0x148 is an angle, 0x8000 =
                # 180 deg. With a zero hotspot that is a point reflection of the whole assembly
                # through (floor(sx), floor(sy)) with the texels flipped both ways. Other angles are
                # specified (rigid rotation about the hotspot) but unexercised -- drawn unrotated
                # and counted, so a tape that carries one is noticed.
                rot180 = extra['angle'] == 0x8000 and tuple(extra['hot']) == (0, 0)
                # GENERAL ROTATION (SH4 bank03 loc_8c03481c / loc_8c034b66 + bank12 loc_8C1244B0,
                # mvc2-sh4-re-expert, CONFIRMED in the disassembly; first seen in DATA on tape
                # 59612784: angle 0x1400 = 28.125 deg with hotspots like (-48,-104)):
                #   pivot P = origin + (facing ? -hotX : hotX, hotY)      [native px; E0/E4 + s*hot]
                #   theta   = ((facing ? -A : A) & 0xFFFF) * 2pi / 65536   [+A = CCW on the y-down screen]
                #   corner' = P + R(corner - P),  R(x, y) = (x*c + y*s, -x*s + y*c)
                # The A=0 layout is the proven placement law; the rotation is RIGID about P, applied
                # to the four corners of each part AFTER placement (post-scale). ⚠ Pixel-exactness of
                # this path is NOT gated: no capture holds a non-0x8000 angle yet. 0x8000 with a zero
                # hotspot is the exact special case (reflection with texel flips, gated 24/24).
                rot_gen = bool(extra['angle']) and not rot180
                if rot180:
                    bmp = bmp[::-1, ::-1]
                key = '%s_p%d_%s' % (at.name, pid, sha8(bmp.tobytes()))
                if key not in textures:
                    textures[key] = {'w': pw, 'h': ph, 'fmt': 61, **intern(bmp.tobytes())}

                if extra['bit15']:
                    left = (ox + rec['dx'] - pw) if mir else (ox - rec['dx'])
                    top = oy + rec['dy']
                else:
                    # TILED flip anchoring, SH4-confirmed (v3gate has the citations): the full
                    # storage block is drawn, reflected about the LOGICAL box; padding hangs outside
                    # on the mirrored side. Reduces to the proven law for flags 0.
                    mirX = (mir != hf)
                    X0 = (ox + rec['dx'] - Lw) if mir else (ox - rec['dx'])
                    left = X0 + (Lw - pw) if mirX else X0
                    top = oy + rec['dy'] + ((Lh - ph) if vf else 0)
                if rot180:
                    left, top = 2 * ox - left - pw, 2 * oy - top - ph
                # corners in native px: TL, BL, TR, BR (index order the IB below expects)
                corners = [(left, top), (left, top + ph), (left + pw, top), (left + pw, top + ph)]
                if rot_gen:
                    # ⚠ THE ROTATION IS IN 640x480 SPACE, NOT NATIVE. The walker rotates L = pen*sX
                    # (bank03 loc_8c03481c: fr14/fr12 = float*+0xEC) -- i.e. in the E0/E4 screen
                    # space where pixels are square -- and the pivot is floor(E0) + sX*hot. Native
                    # (384x224) is anisotropic (3/5, 7/15), so rotating there bends the angle: on
                    # tape 59612784 f4485 the rocket-punch trail origins run at 28 deg in 640-space
                    # (= 0x1400 exactly) and the native-space rotation drew the pieces off-line.
                    sgn = -1.0 if mir else 1.0
                    hx, hy = extra['hot']
                    Px, Py = np.floor(tsx) + sgn * hx / TAPE_X, np.floor(tsy) + hy / TAPE_Y   # 640-space pivot
                    th = (((-extra['angle']) if mir else extra['angle']) & 0xFFFF) * (2.0 * math.pi / 65536.0)
                    c, sn = math.cos(th), math.sin(th)
                    rot = []
                    for cx, cy in corners:
                        X, Y = cx / TAPE_X - Px, cy / TAPE_Y - Py                   # native -> 640, about P
                        rot.append(((Px + X * c + Y * sn) * TAPE_X, (Py - X * sn + Y * c) * TAPE_Y))
                    corners = rot
                    rotated_general[extra['angle']] += 1
                # sort key = walker depth (+0x12C, tape 'depth') + 0.001 per record in submission order
                # (FUN_1406129f0), the vertex z = FUN_1408432e0(key) under the world P (slot 3 at the walk)
                D = None
                if extra.get('depth') is not None and Ps is not None and not a.legacy_order:
                    D = float(np.float32(extra['depth']) + np.float32(0.001) * ri)
                    z = sprite_vertex_z(D, Ps)
                else:
                    z = Z0 - len(draws) * ZSTEP
                u0, u1 = (1.0, 0.0) if mir else (0.0, 1.0)   # the mirror lives in the UV winding
                first = len(verts) // STRIDE
                for (cx, cy), u, v in zip(corners, (u0, u0, u1, u1), (0.0, 1.0, 0.0, 1.0)):
                    px, py = cx / SX - 1.0, 1.0 - cy / SY
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
                d['_cat'], d['_key'], d['_sub'] = 3, D, (0, extra.get('walk', 0), ri)
                draws.append(d)
        emit_world((7, 8, 9))               # effects, shadows, markers: after the sprites
        emit_world((11,))                   # the HUD last
        # Steam's flush order: Z-write categories (submission order), then category 3 sorted by the key
        draws = order_draws(draws, legacy=a.legacy_order)
        for k, v in world_missing.items():
            missing['world: ' + k] += v
        for k, v in world_state.items():
            world_state_total[k] += v
        drawn_total += len(draws)
        heads.append({
            'frame': int(r[C['frame']]) if 'frame' in C else len(heads),
            'sceneRTFile': None, 'viewport': man['viewport'], 'sceneRT': man['sceneRT'],
            'clears': [{'kind': 'ClearRenderTargetView', 'colour': [0, 0, 0, 0]}],
            'vb': intern(bytes(verts)),
            'ib': intern(struct.pack('<%dI' % len(idxs), *idxs)),
            'inputLayouts': {**man['inputLayouts'], **(wt.inputLayouts if wt else {})},
            'textures': {k: textures[k] for k in ({d['tex'][0] for d in draws if d['tex'][0]} |
                                                  {d['tex'][1] for d in draws if d['tex'][1]})},
            'constantBuffers': cb_recs,
            'draws': draws,
        })

    out = a.out or os.path.join(HERE, os.path.basename(a.tape).replace('.json', '') + '.seq')
    manifest = {'frames': heads, 'source': os.path.basename(a.tape),
                'first': heads[0]['frame'] if heads else 0, 'count': len(heads),   # the player's range label
                'note': 'SYNTHESISED from tape state by tape_to_seq.py -- not a capture'}
    hb = json.dumps(manifest).encode('utf-8')
    with open(out, 'wb') as f:
        f.write(b'RRSQ')
        f.write(struct.pack('<I', len(hb)))
        f.write(hb)
        for p in pool:
            f.write(p)
    total = 8 + len(hb) + sum(len(p) for p in pool)

    if held:
        print('  rows HELD from the previous frame (no/torn node data in the tape): %s' % dict(held))
    if rotated_general:
        print('  general-rotation parts (disassembly formula, NOT pixel-gated): %s'
              % {('0x%04X' % k): v for k, v in rotated_general.items()})
    if complete_prop.stats:
        print('  stage props completed from the arc (tape records -> arc meshes): %s' % dict(sorted(complete_prop.stats.items())))
    if bg_stats:
        print('  frame preamble / background colour (bg_rule, FUN_1406101b0): %s' % dict(bg_stats))
    elif wt is not None and not a.no_preamble:
        print('  ⚠ no frame preamble: the world template pack does not start with the three clear quads')
    print('\n%d frames, %d draws (%.1f/frame), %d distinct textures'
          % (len(heads), drawn_total, drawn_total / max(1, len(heads)), len(textures)))
    if world_state_total:
        print('  world draws, D3D state from the record header (tsp_state): %s' % dict(world_state_total))
    if order_draws.stats:
        print('  draw order (FUN_140842e30 flush; --legacy-order for the old dispatcher order): %s' % dict(order_draws.stats))
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
