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
CAMERA_BLOCK = os.path.join(HERE, 'camera_block.json')
TCW_PAGES = os.path.join(HERE, 'tcw_pages')


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
                             model=struct.unpack_from('<Q', ab, off + 88)[0]))
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
                verts = [struct.unpack_from('<8f', pay, v) for v in range(8, len(pay) - 31, 32)]
                tcw = struct.unpack_from('<I', hdr, 0x0C)[0]
                # a SYNTHETIC tape (states_to_tape) stashes its page key in the header's spare words;
                # a real object has floats there -- accept only a clean 'sha_<16 hex>' or 8-hex key
                stash = hdr[0x10:0x30].rstrip(b'\x00')
                ok = stash.isascii() and ((stash.startswith(b'sha_') and len(stash) == 20 and stash[4:].isalnum())
                                          or (len(stash) == 8 and stash.isalnum()))
                key = stash.decode('ascii') if ok else '%08X' % tcw
                recs.append(dict(tcw=tcw, key=key,
                                 colour=struct.unpack_from('<4f', hdr, 0x2C), verts=verts))
                q += 0x50 + max(0, size)
            objs.append(recs)
    return frames, objs


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


class WorldTemplate:
    """Pipeline state + PS constants lifted from real world-space draws of a captured frame."""
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
            self.draw[v] = {k: d[k] for k in ('vs', 'ps', 'il', 'vsVariant', 'psVariant', 'psFog', 'samp', 'blend',
                                              'bfactor', 'smask', 'depth', 'raster', 'vp', 'scissor', 'stride')}
            cbs = man['constantBuffers']
            self.pscb[v] = [bytes(B(cbs[h])) if (h and cbs.get(h) and cbs[h]['len'] != 432 and cbs[h]['len'] != 48) else None
                            for h in (d.get('pscbHash') or [])]
        self.pages = {}
        idx = os.path.join(TCW_PAGES, 'index.json')
        if os.path.exists(idx):
            for k, v in json.load(open(idx)).items():
                self.pages[k] = v


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
    ap.add_argument('--world-template', default=WORLD_TEMPLATE)
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
                off += stride
                rows.append(dict(kind=v[0], slot=v[1], cat=v[2], sort=v[3], layer=v[4], face=v[5],
                                 owner=v[6], drawn=v[7], sid=v[8], pal=v[9], zx=v[15] / 4096.0,
                                 fsx=v[18], fsy=v[19], depth=v[20], gfx1=v[21],
                                 angle=angle, hot=(hotx, hoty)))
            v3nodes[fr] = rows
        pb = gzip.decompress(base64.b64decode(tape.get('pals', '')))
        for i in range(len(pb) // 32):
            pal = np.zeros((256, 4), np.uint8)
            for j in range(16):
                w = struct.unpack_from('<H', pb, i * 32 + j * 2)[0]
                pal[j] = ((w >> 8) & 15) * 17, ((w >> 4) & 15) * 17, (w & 15) * 17, ((w >> 12) & 15) * 17
            v3pals.append(pal)
        print('  TAPE v%d: %d frames of ordered nodes, %d palettes, stride %d' % (
            4 if stride >= 50 else 3, len(v3nodes), len(v3pals), stride))
    cols = [s.strip() for s in tape['schema'].strip('[]').split(',')]
    C = {n: i for i, n in enumerate(cols)}
    # ── v5 world-space stream ──
    v5nodes, v5objs = decode_anodes(tape)
    wt = None
    if v5nodes and not a.no_world:
        if scene_block.model is None or not os.path.exists(a.world_template):
            print('  ⚠ world-space stream present but no camera_block.json / template pack -- skipping it')
        else:
            wt = WorldTemplate(a.world_template)
            # pages shipped inside a synthetic tape (offline test) take precedence over the TCW library
            tape_pages = {}
            for k, v in (tape.get('pages') or {}).items():
                tape_pages[k] = dict(w=v['w'], h=v['h'], fmt=v['fmt'], data=gzip.decompress(base64.b64decode(v['data'])))
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

    for r in rows:
        verts, idxs, draws = bytearray(), [], []

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
        if v3nodes:
            cur = v3nodes.get(fr_clock)
            if cur is None or (len(cur) < 2 and last_nodes is not None and len(last_nodes) >= 3):
                held['no nodes' if cur is None else 'torn (%d node)' % len(cur)] += 1
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
                        # an OWNERLESS pool object (owner 0xFF: global supers, some projectiles) still
                        # carries its GFX1 bank pointer, and every effect inherits its character's
                        # GFX1 by struct copy -- so the bank names the character. Resolve through the
                        # fighters of this frame (kind 0 nodes carry theirs).
                        for f in v3nodes.get(fr_clock, ()):
                            if f['kind'] == 0 and f['gfx1'] and f['gfx1'] == nd['gfx1']:
                                owner = f['slot']
                                break
                    if owner > 5:
                        missing['object with owner %d (unowned, gfx1 %08X unmatched)' % (nd['owner'], nd['gfx1'])] += 1
                        continue
                    cid = (p1 if owner % 2 == 0 else p2)[owner // 2]
                # mirror = the node's facing ONLY. sid bit 15 selects the record FORMAT (the
                # scale walker), it is not a flip (Ghidra FUN_1406129f0; v3gate 100% with this).
                mir = bool(nd['face'])
                items.append((0, Atlas.get(a.atlas, cid), nd['sid'] & 0x7FFF, nd['fsx'], nd['fsy'],
                              mir, 'body' if nd['kind'] == 0 else 'obj', nd['pal'],
                              dict(bit15=bool(nd['sid'] & 0x8000), angle=nd.get('angle', 0), hot=nd.get('hot', (0, 0)))))
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
        def emit_world(lists):
            """Append vs_world draws for this frame's nodes in `lists`, in list order."""
            if not wt:
                return
            rows_w = v5nodes.get(fr_clock, ())
            cam = (float(r[C['eyeX']]) if 'eyeX' in C else 0.0, float(r[C['eyeY']]) if 'eyeY' in C else 0.0,
                   float(r[C['zoom']]) if 'zoom' in C else 812.357)
            for nd in rows_w:
                if nd['list'] not in lists or nd['obj'] >= len(v5objs):
                    if nd['list'] in lists and nd['model']:
                        world_missing['3D model node (list %d)' % nd['list']] += 1
                    continue
                variant = 'list6' if nd['list'] in (5, 6, 11, 12, 13) else 'list7'
                m = nd['matrix']
                cbw = struct.pack('<12f', m[0], m[4], m[8], m[12], m[1], m[5], m[9], m[13], m[2], m[6], m[10], m[14])
                scb = scene_block(cam, variant)
                hw = sha8(cbw); hs = sha8(scb)
                cb_recs.setdefault(hw, {**intern(cbw)})
                cb_recs.setdefault(hs, {**intern(scb)})
                for rec in v5objs[nd['obj']]:
                    key = rec['key']
                    page = tape_pages.get(key)
                    if page is None and key in wt.pages:
                        pv = wt.pages[key]
                        fn = os.path.join(TCW_PAGES, pv.get('file', 'tcw_%s_%dx%d_f%d.png' % (key, pv['w'], pv['h'], pv['fmt'])))
                        if os.path.exists(fn):
                            im = Image.open(fn)
                            data = np.array(im.convert('RGBA')).tobytes() if pv['fmt'] != 61 else np.array(im)[:, :, 0].tobytes()
                            page = tape_pages[key] = dict(w=pv['w'], h=pv['h'], fmt=pv['fmt'], data=data)
                    if page is None:
                        world_missing['no page for %s' % key] += 1
                        continue
                    tkey = 'world_%s' % key
                    if tkey not in textures:
                        textures[tkey] = {'w': page['w'], 'h': page['h'], 'fmt': page['fmt'], **intern(page['data'])}
                    ps_variant = 'texalpha' if (nd['flags'] & 0x20) or nd['list'] in (7, 8, 9) else 'opaque'
                    if ps_variant not in wt.draw:
                        ps_variant = next(iter(wt.draw))
                    tdraw_w = wt.draw[ps_variant]
                    col = rec['colour']
                    cbytes = bytes((int(max(0, min(1, col[2])) * 255), int(max(0, min(1, col[1])) * 255),
                                    int(max(0, min(1, col[0])) * 255), int(max(0, min(1, col[3])) * 255)))
                    first = len(verts) // STRIDE
                    for (x, y, z, nx, ny, nz, u, v) in rec['verts']:
                        verts.extend(struct.pack('<4f', x, y, z, 0.0))
                        verts.extend(struct.pack('<2f', nx, ny))
                        verts.extend(cbytes)
                        verts.extend(bytes((0, 0, 0, 0)))
                        verts.extend(struct.pack('<2f', u, v))
                    nv = len(rec['verts'])
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

            if v3nodes and a.bank is None and 0 <= cos < len(v3pals):
                base_pal = v3pals[cos]                 # v3: `cos` is the resolved palette index
                blk_base = None                        # locate its row-0 in the LUT for sibling rows
                for bi, bk in enumerate(at.banks):
                    if all(list(bk[i]) == base_pal[i].tolist() for i in range(16)):
                        blk_base = bi - (bi % 8); break
            else:
                base_pal = at.palette(a.bank, cos); blk_base = None
            pal_cache = {}
            def pal_for_row(row):
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
                draws.append(d)
        emit_world((7, 8, 9))               # effects, shadows, markers: after the sprites
        emit_world((11,))                   # the HUD last
        for k, v in world_missing.items():
            missing['world: ' + k] += v
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
