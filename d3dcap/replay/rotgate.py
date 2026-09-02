#!/usr/bin/env python3
"""rotgate.py -- per-QUAD accounting of a state-carrying frame: which engine node explains each
indexed quad Steam drew, under which placement model, and which quads nothing explains.

    python rotgate.py ordergate/frame_8980.pack [more packs]

Models tested per node:
    normal   the proven A=0 law (v3gate)                              -- every node
    rot180   SH4 rotation path with +0x148 == 0x8000, hotspot (0,0):  -- rotated nodes only
             point reflection of the A=0 layout through (floor(sx), floor(sy)), texels flipped
             both ways (bank03 loc_8c03481c + bank12 loc_8C1244B0: corners rotate rigidly about
             the pivot, so 180 deg == reflect the whole assembly through the pivot)
    unrot    the rotated node painted as if A == 0 (the alternative hypothesis)
A quad is "explained" by (node, record, model) when its tile pixels equal the predicted part bitmap
at that offset, byte for byte, under SOME flip of the page -- the flip that matched is reported, so
the winding needed by the rotated quads is observed, not assumed. The whole-frame score cannot judge
rotation (rotated nodes are also partially REVEALED at runtime); this can.
"""
import os, struct, sys
from collections import Counter, defaultdict
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blkstate as BS
import asm_ident as AI
import v3gate as V3

TX, TY = V3.TX, V3.TY


def node_parts(blk, base, slots, nd):
    """[(ri, left, top, w, h, bmp)] for the node under the A=0 law, plus (cid, ox, oy, mir)."""
    if nd['slot'] is not None:
        cid = blk[nd['off'] + V3.H_CID]
    else:
        slot = slots.get(nd['owner'])
        if slot is None:
            return None
        cid = blk[BS.H0_OFF + slot * BS.SLOT_STRIDE + V3.H_CID]
    A = V3.atlas(cid)
    if not A:
        return None
    nm, idx, parts, asms = A
    recs = asms.get(str(nd['sid'] & 0x7fff))
    if not recs:
        return None
    mir = bool(blk[nd['off'] + V3.H_FACING])
    ox, oy = np.floor(nd['sx']) * TX, np.floor(nd['sy']) * TY
    rawr = V3.rawcells(cid)
    rawr = rawr.get(nd['sid'] & 0x7fff) if isinstance(rawr, dict) else None
    out = []
    for ri, r in enumerate(recs):
        p = parts.get(str(r['part']))
        if not p:
            continue
        fl = rawr[ri]['flags'] if rawr and ri < len(rawr) else 0
        hf, vf = bool(fl & 0x8000), bool(fl & 0x4000)
        bmp = idx[p['y']:p['y'] + p['h'], p['x']:p['x'] + p['w']][::-1]
        pw, ph = p['w'], p['h']
        dm = V3.gfx1dims(cid).get(r['part'])
        if dm and '--no-logical' not in sys.argv and (nd['sid'] & 0x8000 or '--logical-all' in sys.argv):
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
        out.append((ri, left, top, pw, ph, bmp))
    return dict(nm=nm, cid=cid, ox=ox, oy=oy, mir=mir, parts=out)


def match(page, d, tk, left, top, w, h, bmp):
    """Does this quad's tile equal bmp at its offset under some page flip?  -> flip label or None"""
    if not (left - 0.6 <= d['sx'] and d['sx'] + d['tw'] <= left + w + 0.6 and
            top - 0.6 <= d['sy'] and d['sy'] + d['th'] <= top + h + 0.6):
        return None
    ox_, oy_ = int(round(d['sx'] - left)), int(round(d['sy'] - top))
    tw, th = int(round(d['tw'])), int(round(d['th']))
    if ox_ < 0 or oy_ < 0 or ox_ + tw > w or oy_ + th > h:
        return None
    want = bmp[oy_:oy_ + th, ox_:ox_ + tw]
    v0 = int(round(d['v0'] / 32.0 * tk['h'])); u0 = int(round(d['u0'] / 32.0 * tk['w']))
    raw = page[v0:v0 + th, u0:u0 + tw]
    if raw.shape != want.shape or not want.any():
        return None
    for lab, got in (('V', raw[::-1]), ('HV', raw[::-1, ::-1]), ('-', raw), ('H', raw[:, ::-1])):
        if (got == want).all():
            return (lab, ox_, oy_, tw, th, u0, v0) if os.environ.get('ROTDBG') else lab
    return None


def main():
    packs = [a for a in sys.argv[1:] if not a.startswith('--')]
    for pk in packs:
        frame = int(os.path.basename(pk).split('_')[1].split('.')[0])
        use = frame if '--paired' in sys.argv else frame + 1
        try:
            meta, blk = BS.load_frame(use)
        except SystemExit:
            print('frame %d: no state' % use); continue
        base, score, _ = BS.find_base(blk)
        if meta.get('base'): base = int(meta['base'])   # exact, from the shim (sidecar)
        if not base:
            continue
        nodes = BS.nodes(blk, base)
        slots = {base + nd['off']: nd['slot'] for nd in nodes if nd['slot'] is not None}
        man, B = AI.load_pack(pk)
        quads = AI.char_quads(man, B)
        T_ = man['textures']
        allq = []
        for k, ds in quads.items():
            tk = T_[k]
            if tk['fmt'] != 61:
                continue
            page = np.frombuffer(B(tk), np.uint8).reshape(tk['h'], tk['w'])
            for d in ds:
                allq.append((page, d, tk))
        explained = {}          # quad draw idx -> (model, node label, flip)
        per_node = []
        for nd in nodes:
            ang = struct.unpack_from('<I', blk, nd['off'] + 0x148)[0] & 0xFFFF
            hot = struct.unpack_from('<hh', blk, nd['off'] + 0x178)
            np_ = node_parts(blk, base, slots, nd)
            label = 'L%d/%d %s sel %d%s' % (nd['layer'], nd['idx'],
                                            'P%d' % nd['slot'] if nd['slot'] is not None else 'obj',
                                            nd['sid'] & 0x7fff, ' ROT %04X' % ang if ang else '')
            if not np_:
                per_node.append((label, 'no atlas/sel', Counter())); continue
            models = [('normal', np_['parts'])]
            if ang:
                if ang == 0x8000 and hot == (0, 0):
                    refl = [(ri, 2 * np_['ox'] - left - w, 2 * np_['oy'] - top - h, w, h, bmp[::-1, ::-1])
                            for (ri, left, top, w, h, bmp) in np_['parts']]
                    models = [('rot180', refl), ('unrot', np_['parts'])]
                else:
                    models = [('unrot', np_['parts'])]
            hits = Counter()
            pred = sum(int((bmp > 0).sum()) for (_, _, _, _, _, bmp) in np_['parts'])
            cov = 0
            for mname, plist in models:
                for (page, d, tk) in allq:
                    for (ri, left, top, w, h, bmp) in plist:
                        lab = match(page, d, tk, left, top, w, h, bmp)
                        if lab:
                            ox_, oy_ = int(round(d['sx'] - left)), int(round(d['sy'] - top))
                            tw, th = int(round(d['tw'])), int(round(d['th']))
                            cov += int((bmp[oy_:oy_ + th, ox_:ox_ + tw] > 0).sum())
                        if lab and isinstance(lab, tuple):
                            print('      %-26s %-6s rec %2d part %3dx%-3d tile %-2s at (%3d,%3d) %2dx%-2d page %dx%d u0 %2d v0 %2d' % (
                                label, mname, ri, w, h, lab[0], lab[1], lab[2], lab[3], lab[4], tk['w'], tk['h'], lab[5], lab[6]))
                            lab = lab[0]
                        if lab:
                            hits[(mname, lab)] += 1
                            explained.setdefault(d['i'], (mname, label, lab))
                            break
            per_node.append((label, '%s %s  px %5d covered %5d (%3d%%)' % (np_['nm'], 'MIR' if np_['mir'] else '   ', pred, cov, 100 * cov // max(1, pred)), hits))
        print('\n=== frame %d (state %d)  indexed quads %d  explained %d  UNEXPLAINED %d'
              % (frame, use, len(allq), len(explained), len(allq) - len(explained)))
        for label, nm, hits in per_node:
            if hits or 'ROT' in label or os.environ.get('ROTDBG') or '--all' in sys.argv:
                print('  %-28s %-38s %s' % (label, nm, dict(hits) if hits else 'NO QUAD MATCHED'))
        tally = Counter((m, lab) for (m, _, lab) in explained.values())
        print('  by model/flip:', dict(tally))
        un = [d for (page, d, tk) in allq if d['i'] not in explained]
        if un:
            fxfy = Counter((d['fx'], d['fy']) for d in un)
            print('  unexplained quads: %d   (fx,fy) %s   x-range %.0f..%.0f' % (
                len(un), dict(fxfy), min(d['sx'] for d in un), max(d['sx'] + d['tw'] for d in un)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
