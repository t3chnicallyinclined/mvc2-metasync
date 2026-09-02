#!/usr/bin/env python3
"""ordergate.py -- test the INTRA-ASSEMBLY draw-order rule against Steam, with the sid KNOWN.

    python ordergate.py ordergate/frame_*.pack

For a state-carrying capture we know, per frame, every fighter's cid + sid + facing (blkstate) AND
Steam's draw index per quad (the pack). So instead of solving the sel from geometry, predict every
part's screen rect from the placement law and read which record each captured tile belongs to.
Then: within one body, is Steam's draw order the REVERSE of the record list (the rule the emitter
applies), or not? Every violation is printed with (char, sel, record idx, draw idx).
"""
import glob, json, os, struct, sys
from collections import defaultdict, Counter
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blkstate as BS
import asm_ident as AI

ATL = AI.DEF_ATLAS
H_CID, H_FACING = 0x6c0, 0x154
TX, TY = 3.0 / 5.0, 7.0 / 15.0

atlas_cache = {}
def atlas(cid):
    if cid not in atlas_cache:
        nm = 'PL%02X' % cid
        try:
            A = np.array(Image.open(os.path.join(ATL, nm + '_idx.png')))[:, :, 0]
            asm = json.load(open(os.path.join(ATL, nm + '_asm.json')))
            atlas_cache[cid] = (nm, A, asm['parts'], asm['assemblies'])
        except FileNotFoundError:
            atlas_cache[cid] = None
    return atlas_cache[cid]

RAW = '--raw' in sys.argv
sys.argv = [a for a in sys.argv if a != '--raw']
sys.path.insert(0, 'C:/Users/trist/projects/maplecast-flycast/tools')
import rip_gfx2_assembly as RIP
_raw = {}
def rawcells(cid):
    """the rip's per-record view, WITH the raw FLAGS and sel words the deployed json drops"""
    if cid not in _raw:
        g = glob.glob('C:/Users/trist/projects/maplecast-flycast/dasm_PLDAT/Output/PL%02X_DAT/*GFX_DATA_01.BIN' % cid)
        _raw[cid] = RIP.read_cells(open(g[0], 'rb').read())[0] if g else {}
    return _raw[cid]
ok = viol = 0
detail = Counter()
for pk in sys.argv[1:]:
    frame = int(os.path.basename(pk).split('_')[1].split('.')[0])
    try:
        meta, blk = BS.load_frame(frame)
    except SystemExit:
        continue
    base, score, _ = BS.find_base(blk)
    if not base:
        continue
    bodies = []
    for nd in BS.nodes(blk, base):
        if nd['slot'] is None:
            continue
        cid = blk[nd['off'] + H_CID]
        A = atlas(cid)
        if not A:
            continue
        nm, idx, parts, asms = A
        recs = asms.get(str(nd['sid'] & 0x7fff))
        if not recs:
            continue
        mir = bool(blk[nd['off'] + H_FACING])
        ox, oy = nd['sx'] * TX, nd['sy'] * TY
        rects = []
        for ri, r in enumerate(recs):
            p = parts.get(str(r['part']))
            if not p:
                continue
            left = (ox + r['dx'] - p['w']) if mir else (ox - r['dx'])
            rects.append((ri, r['part'], left, oy + r['dy'], p['w'], p['h']))
        bodies.append(dict(cid=cid, nm=nm, sid=nd['sid'] & 0x7fff, mir=mir, rects=rects))
    if not bodies:
        continue
    man, B = AI.load_pack(pk)
    quads = AI.char_quads(man, B)
    # which body + record does each captured quad fall inside?  (tile rect inside part rect)
    per_body = defaultdict(list)     # (body i) -> [(record idx, draw idx)]
    T_ = man['textures']
    rejected = 0
    for k, ds in quads.items():
        tk = T_[k]
        # pages are 32x32 mostly, but 64x32 / 8x8 / 16x16 pages exist too: reshape by the record
        page = np.frombuffer(B(tk), np.uint8).reshape(tk['h'], tk['w']) if tk['fmt'] == 61 else None
        for d in ds:
            hits = []
            for bi, b in enumerate(bodies):
                nm, idx, parts, asms = atlas(b['cid'])
                for (ri, part, L, T, w, h) in b['rects']:
                    if not (L - 0.6 <= d['sx'] and d['sx'] + d['tw'] <= L + w + 0.6 and
                            T - 0.6 <= d['sy'] and d['sy'] + d['th'] <= T + h + 0.6):
                        continue
                    # GEOMETRY IS NOT ENOUGH. A tile of some OTHER node (a cape object drawn behind)
                    # can sit inside this part's rect and be mis-read as one of its records. Require
                    # the tile's pixels to BE this part at that offset: pages are stored bottom-up
                    # and mirrored bodies reverse columns, exactly as emitter_gate reproduces them.
                    if page is None:
                        continue
                    p = parts[str(part)]
                    bmp = idx[p['y']:p['y'] + p['h'], p['x']:p['x'] + p['w']][::-1]
                    if b['mir']:
                        bmp = bmp[:, ::-1]
                    ox_ = int(round(d['sx'] - L)); oy_ = int(round(d['sy'] - T))
                    tw, th = int(round(d['tw'])), int(round(d['th']))
                    if ox_ < 0 or oy_ < 0 or ox_ + tw > p['w'] or oy_ + th > p['h']:
                        continue
                    want = bmp[oy_:oy_ + th, ox_:ox_ + tw]
                    # the quad samples page[v0:v0+th, u0:u0+tw] with V inverted (see emitter_gate)
                    # char_quads scales u/v by 32; rescale to THIS page's real size
                    v0 = int(round(d['v0'] / 32.0 * tk['h'])); u0 = int(round(d['u0'] / 32.0 * tk['w']))
                    got = page[v0:v0 + th, u0:u0 + tw][::-1]
                    if d['fx']:
                        got = got[:, ::-1]
                    if got.shape == want.shape and (got == want).all():
                        hits.append((bi, ri))
            if len(hits) == 1:
                bi, ri = hits[0]
                per_body[bi].append((ri, d['i']))
            elif not hits:
                rejected += 1
    for bi, pairs in per_body.items():
        b = bodies[bi]
        first = {}
        for ri, di in pairs:
            first[ri] = min(first.get(ri, 1 << 30), di)
        order = sorted(first.items(), key=lambda t: t[1])      # by Steam draw index
        ris = [ri for ri, _ in order]
        if len(ris) < 2:
            continue
        if ris == sorted(ris, reverse=True):
            ok += 1
        else:
            viol += 1
            detail[(b['nm'], b['sid'])] += 1
            print('frame %d %s sel %-4d %s  draw order by record idx: %s   (%d parts)' % (
                frame, b['nm'], b['sid'], 'MIR' if b['mir'] else '   ', ris, len(first)))
            if RAW:
                # the pulled-out set = records drawn before the longest strictly-descending tail
                tail = 1
                while tail < len(ris) and ris[-tail - 1] > ris[-tail]:
                    tail += 1
                pulled = set(ris[:len(ris) - tail])
                cells = rawcells(b['cid'])
                recs = cells.get(b['sid']) if isinstance(cells, dict) else \
                    (cells[b['sid']] if b['sid'] < len(cells) else None)
                nm, idx, parts, asms = atlas(b['cid'])
                for ri, r in enumerate(recs or []):
                    if ri not in first:
                        continue
                    p = parts.get(str(r['sel']), {})
                    print('     %s rec %2d draw %4d  part %5d %3dx%-3d  dx %+4d dy %+4d  ddx %+4d ddy %+4d  FLAGS %04X' % (
                        'PULLED' if ri in pulled else '      ', ri, first[ri], r['sel'],
                        p.get('w', 0), p.get('h', 0), r['dx'], r['dy'], r.get('ddx', 0), r.get('ddy', 0), r['flags']))
print('\nbodies with >=2 parts attributed: reversed-order HOLDS %d, VIOLATED %d' % (ok, viol))
if detail:
    print('violating sels:', detail.most_common(12))
