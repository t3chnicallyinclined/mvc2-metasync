#!/usr/bin/env python3
"""v3gate.py -- the v3 render path, end to end, against Steam's own pixels. Same frame, no tape needed.

    python v3gate.py ordergate/frame_*.pack [--png DIR]

For a state-carrying capture frame this builds EXACTLY what a v3 tape would carry -- the engine's
draw list read out of blk, fighters and pool objects interleaved in walk order -- then runs it
through the emitter's placement law and paints it BY INDEX, the way the player now does. The result
is diffed per pixel, at palette-INDEX level, against a raster of every character quad Steam actually
drew (in Steam's own draw order). No palette is involved on purpose: this isolates ORDER and
PLACEMENT from colour.

What a failure looks like:
   red    Steam drew it, we did not          -> a node we skipped / a sid we cannot resolve
   blue   we drew it, Steam did not          -> a phantom (e.g. a node whose +0x170 flipped)
   yellow both drew, different index         -> WRONG ORDER at that pixel (a cape in front of a body
                                                shows up here), or wrong placement/mirror

Fighter atlas = its own cid (blk+slot*0x738+0x6C0). Object atlas = its OWNER's cid; owner is the
u64 at H+0x28 (the owning fighter's H base). Object mirror = face XOR sid bit 15, as in the tape
adapter. Records inside a body paint in REVERSE list order (ordergate: 59 bodies, 0 violations).
"""
import glob, json, os, struct, sys
from collections import Counter
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blkstate as BS
import asm_ident as AI
import emitter_gate as EG

ATL = AI.DEF_ATLAS
H_CID, H_FACING = 0x6c0, 0x154
TX, TY = 3.0 / 5.0, 7.0 / 15.0

sys.path.insert(0, 'C:/Users/trist/projects/maplecast-flycast/tools')
import rip_gfx2_assembly as RIP
_rawc = {}
def rawcells(cid):
    if cid not in _rawc:
        g = glob.glob('C:/Users/trist/projects/maplecast-flycast/dasm_PLDAT/Output/PL%02X_DAT/*GFX_DATA_01.BIN' % cid)
        _rawc[cid] = RIP.read_cells(open(g[0], 'rb').read())[0] if g else {}
    return _rawc[cid]

_atlas = {}
_dims = {}
def gfx1dims(cid):
    """per part: (sw, sh, lw, lh) in 8 px units from the GFX1 header [lw][lh][sw][sh] (GFX_DATA_00).
    ⭐ THE PART'S DRAWN SIZE IS lw*8 x lh*8 (LOGICAL), NOT sw*8 x sh*8 (STORAGE). SH4 scale walker
    bank03 loc_8c0348c8 (10971-11008): Uspan = lw/sw, Vspan = lh/sh, quad = lw*8 x lh*8 * scale,
    sampling the top-left logical sub-rect of the storage texture. Seen in the captures before it
    was understood: bolt part 156 [4,11,4,16] drawn 32x88 of 32x128; P4 cell-0 rec 1 [14,4,16,4]
    drawn 112x32 of 128x32. The deployed atlas json carries STORAGE dims (the --realparts branch
    of the rip), so the clip is applied here from the ROM header."""
    if cid not in _dims:
        g = glob.glob('C:/Users/trist/projects/maplecast-flycast/dasm_PLDAT/Output/PL%02X_DAT/*GFX_DATA_00.BIN' % cid)
        d = {}
        if g:
            b = open(g[0], 'rb').read()
            n = struct.unpack_from('<I', b, 0)[0] >> 2
            for sel in range(n):
                o = struct.unpack_from('<I', b, sel * 4)[0]
                if o + 4 <= len(b):
                    lw, lh, sw, sh = b[o:o + 4]
                    d[sel] = (sw, sh, lw, lh)
        _dims[cid] = d
    return _dims[cid]


def atlas(cid):
    if cid not in _atlas:
        nm = 'PL%02X' % cid
        try:
            A = np.array(Image.open(os.path.join(ATL, nm + '_idx.png')))[:, :, 0]
            asm = json.load(open(os.path.join(ATL, nm + '_asm.json')))
            _atlas[cid] = (nm, A, asm['parts'], asm['assemblies'])
        except FileNotFoundError:
            _atlas[cid] = None
    return _atlas[cid]


def emit_frame(blk, base, shape, x0, y0):
    """Paint the engine draw list (from blk) into an index raster the size of the truth raster."""
    H, W = shape
    img = np.zeros((H, W), np.uint8)
    nodes = BS.nodes(blk, base)
    slots = {}
    for nd in nodes:
        if nd['slot'] is not None:
            slots[base + nd['off']] = nd['slot']
    skipped = Counter()
    drawn = 0
    # ⭐⭐ PAINT ORDER IS DEPTH ORDER, NOT WALK ORDER. Steam's walker (FUN_1406129f0) submits each
    # quad with z = base + 0.001*(k+1), the sink qsorts the whole pass by z DESCENDING with FIFO ties
    # (comparator @0x1408434d0), and the D3D stream is that sorted list. Measured on the captures:
    #   * within a body z FALLS along draw order (-2e-7/quad): record 0 is nearest -> drawn last;
    #   * within a layer the LATER-registered node has the larger base (layerAcc += 0.001*parts per
    #     node) -> it is BEHIND -> drawn before the earlier one;
    #   * across layers the base is linear in the LAYER INDEX (0.979379 + 0.000359*L, residuals
    #     ~5e-6 over layers 3..6; layer 0 sits below layer 3): lower layer = NEARER.
    # So the painter order is: layers far->near, then REVERSE registration order within a layer,
    # then reverse record order within a node. The DC table LayerZ (bank13 loc_8c1355dc) agrees
    # with the measured index order on 0..7; it is the only evidence for 8..15 (8..11 nearest) --
    # used here for those and FLAGGED, not measured.
    LAYERZ = [15, 17, 19, 21, 23, 25, 27, 29, 10, 11, 12, 13, 30, 31, 32, 33]
    order = sorted(range(len(nodes)), key=lambda i: (-LAYERZ[nodes[i]['layer']], -nodes[i]['idx']))
    for nd in (nodes[i] for i in order):
        # ⭐ +0x148 bit 15 (DC node+0x104, the walker's ROTATION path): across 30 frames and 394
        # nodes, bit set <=> absent from the axis-aligned indexed stream, 370/0/0/24, zero exceptions.
        # These nodes are not drawn as tiles; painting them here invents pixels. --draw-rotated keeps
        # them for A/B.
        # SH4 verdict (bank03:10665, loc_8c03481c): +0x148 is a plain u16 ANGLE (0x10000 = 360 deg),
        # gate is `!= 0`, pivot = hotspot (+0x178/+0x17A), facing negates the angle, and every quad
        # corner is rotated rigidly about the pivot AFTER placement. Surveyed: all 31 rotated nodes in
        # these captures hold exactly 0x8000 with hotspot (0,0) -> a point reflection of the A=0
        # layout through (floor(sx), floor(sy)), texels flipped both ways. --rot180 paints that;
        # any other angle is still skipped (not exercised by this data).
        ang = struct.unpack_from('<I', blk, nd['off'] + 0x148)[0] & 0xFFFF
        rot180 = False
        if ang:
            hot = struct.unpack_from('<hh', blk, nd['off'] + 0x178)
            if '--rot180' in sys.argv and ang == 0x8000 and hot == (0, 0):
                rot180 = True
            elif '--draw-rotated' not in sys.argv:
                skipped['rotation-path node (angle 0x%04X hot %s)' % (ang, hot)] += 1
                continue
        if nd['slot'] is not None:
            cid = blk[nd['off'] + H_CID]
            mir = bool(blk[nd['off'] + H_FACING])
        else:
            slot = slots.get(nd['owner'])
            if slot is None:
                skipped['unowned object'] += 1
                continue
            cid = blk[base - base + BS.H0_OFF + slot * BS.SLOT_STRIDE + H_CID]
            # Ghidra (FUN_1406129f0): sid bit 15 selects the RECORD FORMAT (tiled vs assembly), it is
            # not a flip. The tape adapter XORs it into the mirror; --bit15-flip keeps that for A/B.
            mir = bool(blk[nd['off'] + H_FACING]) != (bool(nd['sid'] & 0x8000) if '--bit15-flip' in sys.argv else False)
        A = atlas(cid)
        if not A:
            skipped['no atlas PL%02X' % cid] += 1
            continue
        nm, idx, parts, asms = A
        recs = asms.get(str(nd['sid'] & 0x7fff))
        if not recs:
            skipped['%s sel %d' % (nm, nd['sid'] & 0x7fff)] += 1
            continue
        # ⭐ THE ENGINE TRUNCATES THE 640x480 SCREEN COORD TO AN INTEGER BEFORE PLACING THE SPRITE.
        # Measured: tile-solved origins are exactly 398, 511, 444, 433, 422, 446, 424 in 640-space
        # while blk holds 398.2, 444.1, 433.6, 422.5, 446.25 -- 433.6->433 and 422.5->422, so it is
        # truncation, not rounding. Using the float put every part up to 0.6 native px off, which
        # showed up as 1-3k wrong-index pixels per frame with nothing missed or invented.
        # floor() here; floor vs trunc differ only for NEGATIVE coords, which this data has not
        # exercised -- flag, do not assume.
        ox, oy = np.floor(nd['sx']) * TX, np.floor(nd['sy']) * TY
        # PER-RECORD MIRROR BITS, from the RAW record FLAGS (the deployed json labels them flip/flipy
        # with the rip's assignment 0x4000=X, 0x8000=Y). Steam's walker (Ghidra, chunk 0x140612f70):
        # `TEST [rec+4],0x4000` -> V swap (vflip); `CMP [rec+4],0 / JL` = sign bit 0x8000 -> U swap
        # (hflip), sense XORed with node+0x154. The one single-bit record captured so far agrees with
        # Steam (0x8000 -> hflip). --flags-rip uses the rip's assignment for A/B.
        rawr = rawcells(cid)
        rawr = rawr.get(nd['sid'] & 0x7fff) if isinstance(rawr, dict) else None
        for ri in range(len(recs) - 1, -1, -1):
            r = recs[ri]
            p = parts.get(str(r['part']))
            if not p:
                continue
            fl = rawr[ri]['flags'] if rawr and ri < len(rawr) else 0
            if '--flags-rip' in sys.argv:
                hf, vf = bool(fl & 0x4000), bool(fl & 0x8000)
            else:
                hf, vf = bool(fl & 0x8000), bool(fl & 0x4000)
            bmp = idx[p['y']:p['y'] + p['h'], p['x']:p['x'] + p['w']][::-1]
            pw, ph = p['w'], p['h']
            # logical clip (see gfx1dims): top-left lw*8 x lh*8 of the DC-oriented image, applied
            # BEFORE any flip; the placement then uses the logical size. SCALE-WALKER RECORDS ONLY
            # (sid bit 15): the tiled builder (bit 15 clear) uses STORAGE dims -- clipping tiled
            # bodies LOST 11 matched tiles on f8940. --no-logical / --logical-all for A/B.
            dm = gfx1dims(cid).get(r['part'])
            if dm and '--no-logical' not in sys.argv and                     (nd['sid'] & 0x8000 or '--logical-all' in sys.argv):
                sw, sh, lw, lh = dm
                cw = lw * 8 if 0 < lw <= sw else pw
                ch = lh * 8 if 0 < lh <= sh else ph
                if (cw, ch) != (pw, ph):
                    bmp = bmp[:ch, :cw]
                    pw, ph = cw, ch
            if vf:
                bmp = bmp[::-1]
            if mir != hf:
                bmp = bmp[:, ::-1]
            left = (ox + r['dx'] - pw) if mir else (ox - r['dx'])
            top = oy + r['dy']
            if rot180:
                left, top = 2 * ox - left - pw, 2 * oy - top - ph
                bmp = bmp[::-1, ::-1]
            r0 = int(round(top - y0)); c0 = int(round(left - x0))
            rs, re = max(0, r0), min(H, r0 + ph)
            cs, ce = max(0, c0), min(W, c0 + pw)
            if re <= rs or ce <= cs:
                continue
            sub = bmp[rs - r0:re - r0, cs - c0:ce - c0]
            m = sub > 0
            img[rs:re, cs:ce][m] = sub[m]
        drawn += 1
    return img, drawn, skipped


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    png = None
    if '--png' in sys.argv:
        png = sys.argv[sys.argv.index('--png') + 1]
        args = [a for a in args if a != png]
        os.makedirs(png, exist_ok=True)
    tot = Counter()
    for pk in args:
        frame = int(os.path.basename(pk).split('_')[1].split('.')[0])
        # ⭐ PAIR frame N's DRAWS WITH blk(N+1). The walker (FUN_140620F10) WRITES node+0x124/+0x128
        # during frame N's render, and the shim's first build dumped blk at openFrame(N) -- i.e. before
        # that walk -- so the snapshot named N carries frame N-1's placement. Measured on every failing
        # frame: the tile-solved origin equals floor(blk(N+1).sy) exactly (446/422/437) while blk(N)
        # holds the previous value (444.11/420.54/439.83); the frames that passed were the ones where
        # nobody moved. Captures made after the shim dumps at Present pair 1:1 instead (`--paired`).
        use = frame if '--paired' in sys.argv else frame + 1
        try:
            meta, blk = BS.load_frame(use)
        except SystemExit:
            continue
        base, score, _ = BS.find_base(blk)
        if not base:
            continue
        man, B = EG.load_pack(pk)
        quads = EG.indexed_quads(man, B)
        if not quads:
            continue
        truth, x0, y0 = EG.raster_truth(man, B, quads)
        ours, drawn, skipped = emit_frame(blk, base, truth.shape, x0, y0)
        both = (truth > 0) | (ours > 0)
        missed = int(((truth > 0) & (ours == 0)).sum())
        invented = int(((truth == 0) & (ours > 0)).sum())
        wrong = int(((truth > 0) & (ours > 0) & (truth != ours)).sum())
        same = int(((truth > 0) & (ours > 0) & (truth == ours)).sum())
        union = int(both.sum())
        tot.update(dict(missed=missed, invented=invented, wrong=wrong, same=same, union=union))
        print('frame %d  nodes drawn %2d  exact %6.2f%%   missed %5d  invented %5d  WRONG-INDEX %5d   %s'
              % (frame, drawn, 100.0 * same / max(1, union), missed, invented, wrong,
                 dict(skipped) if skipped else ''))
        if png:
            pal = np.zeros((256, 4), np.uint8); pal[1:16] = [200, 200, 200, 255]; pal[0] = [30, 30, 40, 255]
            d = np.zeros(truth.shape + (4,), np.uint8); d[..., 3] = 255; d[..., :3] = 30
            d[(truth > 0) & (ours == 0)] = (255, 60, 60, 255)
            d[(truth == 0) & (ours > 0)] = (60, 160, 255, 255)
            d[(truth > 0) & (ours > 0) & (truth != ours)] = (255, 220, 0, 255)
            d[(truth > 0) & (ours > 0) & (truth == ours)] = (70, 70, 70, 255)
            row = [Image.fromarray(pal[truth]), Image.fromarray(pal[ours]), Image.fromarray(d)]
            Wt = sum(i.width for i in row) + 32; Ht = max(i.height for i in row)
            out = Image.new('RGBA', (Wt, Ht), (30, 30, 40, 255)); x = 0
            for i in row:
                out.paste(i, (x, 0), i); x += i.width + 16
            out.resize((Wt * 2, Ht * 2), Image.NEAREST).save(os.path.join(png, 'v3gate_%d.png' % frame))
    if tot['union']:
        print('\nTOTAL  exact %.3f%% of the union   missed %d  invented %d  WRONG-INDEX %d'
              % (100.0 * tot['same'] / tot['union'], tot['missed'], tot['invented'], tot['wrong']))


if __name__ == '__main__':
    main()
