#!/usr/bin/env python3
"""bg_gate.py -- the FRAME PREAMBLE gate (review-re M2, docs/FRAME-BACKGROUND-GHIDRA.md).

    python bg_gate.py 4445 4505 7279

For each capgate frame with a state dump AND a pack: derive the three background words from the dump's blk
bytes with bg_rule.background_words (FUN_1406101b0), build the three preamble quads exactly as the executor
lays them out, and compare BYTE-EXACT against the pack's first three scene draws (vertex bytes, index order,
state). Then sample the captured scene RT: the most common colour in the viewport must be the background
colour when the background is visible.

The gate is deterministic (frozen dump + frozen pack) and numeric (bytes equal / total).
"""
import collections
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bg_rule as BG
import blkstate as BS
import emitter_gate as E
import emu_gate as G

HERE = os.path.dirname(os.path.abspath(__file__))


def quads(cols):
    """(q28 host clear quad, q40 engine background quad) as the executor writes them."""
    q28 = b''.join(struct.pack('<4f', x, y, 1.0, 0.0) + bytes(12) for x, y in ((-1, 1), (1, 1), (-1, -1), (1, -1)))
    q40 = b''.join(struct.pack('<4f', x, y, 1.0, 0.0) + struct.pack('<2f', 0.0, 1.0) + bytes(c) + bytes(4)
                   + struct.pack('<2f', 0.0, 0.0)
                   for (x, y), c in zip(((-1, 1), (-1, -1), (1, 1), (1, -1)), cols))
    return q28, q40


def inputs_from_blk(blk):
    mode = struct.unpack_from('<I', blk, 0x6CB4)[0]
    words = list(struct.unpack_from('<3I', blk, 0x6CB8))
    deck = struct.unpack_from('<3f', blk, 0x6CA8)
    fade = struct.unpack_from('<I', blk, 0x6CE4)[0]
    fade_col = struct.unpack_from('<I', blk, 0x6CF0)[0]
    g = 0x3CB8
    in_fight = (blk[g], blk[g + 1], blk[g + 2]) == (2, 1, 2) and (blk[g + 0x2E] & 1) == 0
    blackout = blk[0x3D50]          # G+0x98 = per-frame copy of entity+0x96 (FUN_14061f030)
    return dict(mode=mode, words=words, deck=deck, fade=fade, fade_col=fade_col, blackout=blackout, ent6=1, in_fight=in_fight)


def main(frames):
    tot = collections.Counter()
    for fr in frames:
        try:
            meta, blk, base = G.frame_state(fr, BS.CAP)
        except SystemExit as e:
            print('frame %d: no state dump (%s)' % (fr, e)); continue
        pack = os.path.join(HERE, 'capgate', 'frame_%d.pack' % fr)
        if not os.path.exists(pack):
            print('frame %d: no pack' % fr); continue
        inp = inputs_from_blk(blk)
        c012 = BG.background_words(**inp)
        cols = BG.vertex_colours(c012) if c012 else None
        print('frame %d (stage %02X): mode %d words %s deck %s fade %d/%06x blackout %d fight %s -> words %s colours %s'
              % (fr, blk[0x6D04], inp['mode'], ['%06x' % w for w in inp['words']], tuple(round(float(x), 3) for x in inp['deck']),
                 inp['fade'], inp['fade_col'], inp['blackout'], inp['in_fight'],
                 ['%06x' % w for w in c012] if c012 else None, cols))
        man, B = E.load_pack(pack)
        vb, ib = B(man['vb']), B(man['ib'])
        d0, d1, d2 = man['draws'][:3]
        q28, q40 = quads(cols or [(0, 0, 0, 255)] * 4)
        got = [vb[d['voff']:d['voff'] + 4 * d['stride']] for d in (d0, d1, d2)]
        exp = [q28, q40, q28]
        names = ['host clear quad (28 B x 4)', 'FUN_140843eb0 background quad (40 B x 4)', 'depth-only quad (28 B x 4)']
        for n, g_, e_, d in zip(names, got, exp, (d0, d1, d2)):
            ok = g_ == e_
            tot['quad bytes exact'] += ok; tot['quad bytes total'] += 1
            idx = struct.unpack_from('<6I', ib, d['firstIndex'] * 4)
            iok = idx == (0, 1, 2, 2, 1, 3)
            tot['index order exact'] += iok; tot['index order total'] += 1
            print('   %-42s bytes %s  indices %s' % (n, 'EXACT' if ok else 'DIFF ' + g_.hex() + ' vs ' + e_.hex(), 'EXACT' if iok else str(idx)))
        # state facts the emitter copies verbatim (recorded, not derived)
        st = lambda d: (d['blend']['en'], d['blend'].get('mask'), d['depth']['func'], d['depth']['write'], d['depth']['sten'], d['depth']['fpass'], d['raster']['cull'], d['raster']['ccw'], d['ps'] is None)
        print('   state (blend en, mask, zfunc, zwrite, sten, spass, cull, ccw, ps null): %s | %s | %s' % (st(d0), st(d1), st(d2)))
        # the 1x1 page bound by the background quad must be white
        t = man['textures'][d1['tex'][0]]
        white = (t['w'], t['h'], B(t)) == (1, 1, b'\xff\xff\xff\xff')
        tot['1x1 page white'] += white; tot['1x1 page total'] += 1
        print('   1x1 page %s' % ('ffffffff EXACT' if white else 'DIFF %s' % B(t).hex()))
        # pixel check on the captured scene RT
        bmp = os.path.join(HERE, 'capgate', 'scene_%d_2048x1024_f87.bmp' % fr)
        if os.path.exists(bmp) and cols:
            from PIL import Image
            im = np.array(Image.open(bmp).convert('RGBA'))
            x0, y0, w, h = man['viewport'][:4]
            vp = im[int(y0):int(y0 + h), int(x0):int(x0 + w)]
            cnt = collections.Counter(map(tuple, vp.reshape(-1, 4)))
            top = cnt.most_common(1)[0]
            bgc = tuple(cols[0])
            n_bg = cnt.get(bgc, 0)
            print('   scene RT: most common viewport colour %s x%d; background colour %s covers %d px (%.1f%%)'
                  % (top[0], top[1], bgc, n_bg, 100.0 * n_bg / vp.shape[0] / vp.shape[1]))
            tot['scene RT most-common == background'] += (tuple(int(v) for v in top[0]) == bgc)
            tot['scene RT total'] += 1
        else:
            print('   scene RT: no bmp for this frame')
    print('\nGATE: quad bytes %d/%d, index order %d/%d, 1x1 page %d/%d, scene RT %d/%d'
          % (tot['quad bytes exact'], tot['quad bytes total'], tot['index order exact'], tot['index order total'],
             tot['1x1 page white'], tot['1x1 page total'], tot['scene RT most-common == background'], tot['scene RT total']))
    return 0


if __name__ == '__main__':
    sys.exit(main([int(x) for x in sys.argv[1:]] or [4445, 4505, 7279]))
