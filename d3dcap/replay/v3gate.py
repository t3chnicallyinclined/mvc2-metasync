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
import glob, json, os, sys
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

_atlas = {}
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
    for nd in nodes:                                   # ⭐ walk order IS paint order
        if nd['slot'] is not None:
            cid = blk[nd['off'] + H_CID]
            mir = bool(blk[nd['off'] + H_FACING])
        else:
            slot = slots.get(nd['owner'])
            if slot is None:
                skipped['unowned object'] += 1
                continue
            cid = blk[base - base + BS.H0_OFF + slot * BS.SLOT_STRIDE + H_CID]
            mir = bool(blk[nd['off'] + H_FACING]) != bool(nd['sid'] & 0x8000)
        A = atlas(cid)
        if not A:
            skipped['no atlas PL%02X' % cid] += 1
            continue
        nm, idx, parts, asms = A
        recs = asms.get(str(nd['sid'] & 0x7fff))
        if not recs:
            skipped['%s sel %d' % (nm, nd['sid'] & 0x7fff)] += 1
            continue
        ox, oy = nd['sx'] * TX, nd['sy'] * TY
        for r in reversed(recs):
            p = parts.get(str(r['part']))
            if not p:
                continue
            bmp = idx[p['y']:p['y'] + p['h'], p['x']:p['x'] + p['w']][::-1]
            if mir:
                bmp = bmp[:, ::-1]
            left = (ox + r['dx'] - p['w']) if mir else (ox - r['dx'])
            top = oy + r['dy']
            r0 = int(round(top - y0)); c0 = int(round(left - x0))
            rs, re = max(0, r0), min(H, r0 + p['h'])
            cs, ce = max(0, c0), min(W, c0 + p['w'])
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
        try:
            meta, blk = BS.load_frame(frame)
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
