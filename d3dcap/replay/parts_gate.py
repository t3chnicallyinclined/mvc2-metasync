#!/usr/bin/env python3
"""parts_gate.py -- deterministic gate for the LIST-0xC part draws (combo counter / rating text).

    python parts_gate.py 4445                 # derive the list-12 draws from the frame's blk + the exe's static
                                              # part lists + the HUD-bank POL, and compare with frame_4445.pack
    python parts_gate.py 4445 4447 4474 7441  # several frames

THE RULE BEING GATED (docs/PARTS-LIST0C-GHIDRA.md, FUN_140653a70, CONFIRMED by decompile; SH4 loc_8C0F215E):
  for each list-12 node with +0x170 != 0 and +0x110 != 0:
      cur = T(node+0x50)                                     (stored to node+0xA8)
      camera = FUN_14061d5b0 (P(0x4000, 4/3, 1, 12000), V = I)
      for pass in 0, 1:
          cur = T(node+0x50)                                 (FUN_140846c30(node+0xA8))
          if pass == 1: list = node+0x118 (stop if 0); cur = T(node+0x80, -6, 0) x cur
          k = 0
          for entry {i8 count, i8 flags, i8 scaleIdx, i8 modelIdx, f32 xoff} while count >= 0:
              cur = T(xoff, 0, 0) x cur
              if scaleIdx: cur = S(SCALE[scaleIdx & 7]) x cur          (PTR_DAT_140a7a2b0)
              colour = (1, 1, 1); alpha 1.0; ctx+0x1f855c = 1 (records copied to the frame arena)
              if flags < 0: model = modelIdx
              else:         model = node[0x228 + k]; k += 1; skip the draw if model < 0
              if count > 0: model records PCW/ISP/TSP/TCW := HEADER[count-1] (DAT_142eed370 =
                            first-record header of HUD models 0..3 -> TCW 0xC92 + count - 1)
              draw PTR_DAT_142edf598[model] via FUN_1408499e0 (kind 0 -> W = cur, V = I, P = HUD)
  Matrices are row-vector 4x4; FUN_140846ee0 pre-multiplies (cur = M x cur).

GATE: every derived draw must find a captured draw (scene CB with V = I) whose 48-B CBWorld equals the
derived W bit-for-bit, whose unique vertex positions and uvs equal the ripped model group bit-for-bit,
and whose bound texture page equals the bank page the patched TCW names byte-for-byte. The exe-static
tables are read from the dump at run time (never copied into the repo).
"""
import argparse
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import blkstate as S                        # noqa: E402
import emitter_gate as E                    # noqa: E402
import rip_parts as RP                      # noqa: E402
import rip_texbank as R                     # noqa: E402

DUMP = os.environ.get('MVC_DUMP', r'C:\Users\trist\ghidra_projects\mvc_dump.bin')
IMAGE_BASE = 0x140000000
SCALE_TABLE = 0x140a7a2b0          # PTR_DAT_140a7a2b0: 8 pointers to (sx, sy, sz)
LINE2_Y = -6.0                     # DAT_14097f1b0
HDR_TABLE_MODELS = 4               # DAT_142eed370[k] = header of HUD model k (FUN_14060c370 case 4)

_dump = None


def dump(addr, n):
    global _dump
    if _dump is None:
        _dump = open(DUMP, 'rb').read()
    return _dump[addr - IMAGE_BASE:addr - IMAGE_BASE + n]


def part_list(addr):
    out = []
    for k in range(64):
        c, f, s, m, x = struct.unpack('<bbbbf', dump(addr + 8 * k, 8))
        if c < 0:
            break
        out.append((c, f, s, m, x))
    return out


def scale_table():
    return [struct.unpack('<3f', dump(struct.unpack('<Q', dump(SCALE_TABLE + 8 * i, 8))[0], 12)) for i in range(8)]


# -- float32 matrix ops exactly as NaomiLib does them (row-vector, pre-multiply) ------------------------
def ident():
    return np.eye(4, dtype=np.float32)


def translate(x, y, z):
    m = ident()
    m[3, 0] = np.float32(x)
    m[3, 1] = np.float32(y)
    m[3, 2] = np.float32(z)
    return m


def scale(sx, sy, sz):
    m = ident()
    m[0, 0] = np.float32(sx)
    m[1, 1] = np.float32(sy)
    m[2, 2] = np.float32(sz)
    return m


def premul(M, cur):
    """cur = M x cur in float32, element by element (FUN_140846ee0)."""
    out = np.zeros((4, 4), dtype=np.float32)
    for i in range(4):
        for j in range(4):
            acc = np.float32(0.0)
            for k in range(4):
                acc = np.float32(acc + np.float32(M[i, k] * cur[k, j]))
            out[i, j] = acc
    return out


def cbworld(m):
    """Steam binds the 4x4 row-vector matrix as a row-major 3x4: rows = columns 0..2 of m."""
    return struct.pack('<12f', m[0, 0], m[1, 0], m[2, 0], m[3, 0], m[0, 1], m[1, 1], m[2, 1], m[3, 1],
                       m[0, 2], m[1, 2], m[2, 2], m[3, 2])


def derive(node, scales, hdr_tcw):
    """The draws FUN_140653a70 emits for one node: [dict(model, tcw, W bytes, pass, entry)]."""
    draws = []
    for pas in (0, 1):
        lst = node['list1'] if pas == 0 else node['list2']
        if not lst:
            break
        cur = translate(*node['pos'])
        if pas == 1:
            cur = premul(translate(node['x2'], LINE2_Y, 0.0), cur)
        k = 0
        for ei, (count, flags, sidx, midx, xoff) in enumerate(part_list(lst)):
            cur = premul(translate(xoff, 0.0, 0.0), cur)
            if sidx:
                cur = premul(scale(*scales[sidx & 7]), cur)
            if flags < 0:
                model = midx
            else:
                model = node['digits'][k]
                k += 1
                if model < 0:
                    continue
            tcw = hdr_tcw[count - 1] if count > 0 else None
            draws.append(dict(model=model, tcw=tcw, W=cbworld(cur), pas=pas, entry=ei, count=count))
    return draws


def captured(pack):
    man, B = E.load_pack(pack)
    cbs = man['constantBuffers']
    vb = B(man['vb'])
    ib = B(man['ib'])
    IDX = struct.unpack('<%dI' % (len(ib) // 4), ib)
    hud = [h for h, v in cbs.items() if v['len'] == 432 and
           np.array_equal(np.frombuffer(B(v), np.float32).reshape(27, 4)[7:11], np.eye(4, dtype=np.float32))]
    out = []
    for i, d in enumerate(man['draws']):
        hs = [h for h in d['vscbHash'] if h != '00000000']
        if not any(h in hud for h in hs):
            continue
        h48 = [h for h in hs if cbs.get(h, {}).get('len') == 48]
        if not h48:
            continue
        st, vo = d['stride'], d['voff']
        ii = sorted(set(IDX[d['firstIndex']:d['firstIndex'] + d['indexCount']]))
        pos = set(vb[vo + j * st:vo + j * st + 12] for j in ii)
        uv = set(vb[vo + j * st + 32:vo + j * st + 40] for j in ii) if st >= 40 else set()
        t = d['tex'][0]
        te = man['textures'].get(t) if t else None
        page = B(te) if te else b''
        out.append(dict(i=i, W=B(cbs[h48[0]]), pos=pos, uv=uv, tex=t, tw=te['w'] if te else 0, page=page,
                        n=len(ii)))
    return out


def _mask_bit0(f):
    """FUN_1408482a0 clears bit 0 of the x word and of the v word of every vertex it copies to the VB
    (`*puVar14 &= 0xfffffffe; puVar14[7] &= 0xfffffffe` -- the NaomiLib direct-vertex flag lives in
    bit 0 of x). A 1-ulp change; the file values keep the bit."""
    return struct.unpack('<f', struct.pack('<I', struct.unpack('<I', struct.pack('<f', f))[0] & 0xfffffffe))[0]


def model_groups(pol, offs, idx):
    m = RP.rip_model(pol, offs[idx], idx)
    gs = []
    for r in m['records']:
        for g in r['groups']:
            pos = set(struct.pack('<3f', _mask_bit0(v[0][0]), v[0][1], v[0][2]) for v in g['tris'])
            uv = set(struct.pack('<2f', v[1][0], _mask_bit0(v[1][1])) for v in g['tris'])
            gs.append((pos, uv))
    return gs


def bank_pages():
    """{TCW: RGBA8 bytes} for the HUD bank, decoded the way the host does (rip_texbank.decode_host)."""
    m, ents = R.load_afs(R.DEFAULT_ARC)
    pol, _, _ = R.afs_entry(m, ents, RP.POL_ENTRY)
    texf, _, _ = R.afs_entry(m, ents, RP.TEX_ENTRY)
    ram, cnt, recs = R.tex_records(pol)
    first = recs[0]['loc']
    out = {}
    for rec in recs:
        px, err = R.decode_host(texf, rec, first)
        if px is not None:
            out[RP.BANK_BASE + rec['idx']] = bytes(px)
    return out


def gate_frame(frame, cap, pack, pol, offs, hdr_tcw, scales, pages):
    meta, blk = S.load_frame(frame, cap)
    base = int(meta['base']) if meta.get('base') else S.find_base(blk)[0]
    nodes = [n for n in S.pnodes(blk, base) if n['drawn'] and n['list1']]
    print('frame %d: G+0x14 = 0x%X, list-12 nodes drawn with a part list: %d' % (
        frame, struct.unpack_from('<I', blk, 0x3CCC)[0], len(nodes)))
    cap_draws = captured(pack)
    tot = dict(draws=0, cbw=0, pos=0, uv=0, tex=0, groups=0)
    used = set()
    for nd in nodes:
        print(' node slot %d state %d count %d pos (%.6f, %.3f, %.3f) x2 %.3f digits %s list1 0x%X list2 0x%X' % (
            nd['slot'], nd['state'], nd['count'], nd['pos'][0], nd['pos'][1], nd['pos'][2], nd['x2'],
            nd['digits'][:8], nd['list1'], nd['list2']))
        for d in derive(nd, scales, hdr_tcw):
            tot['draws'] += 1
            match = [c for c in cap_draws if c['W'] == d['W']]
            w = struct.unpack('<12f', d['W'])
            print('   part model %3d tcw %s pass %d W diag (%.4g,%.4g,%.4g) T (%.6f, %.3f, %.3f): '
                  '%d captured draws bind this CBWorld' % (
                      d['model'], '0x%X' % d['tcw'] if d['tcw'] else 'file', d['pas'], w[0], w[5], w[10],
                      w[3], w[7], w[11], len(match)))
            if match:
                tot['cbw'] += 1
            groups = model_groups(pol, offs, d['model'])
            tot['groups'] += len(groups)
            for gi, (gpos, guv) in enumerate(groups):
                hit = [c for c in match if c['pos'] == gpos and c['i'] not in used]
                if hit:
                    c = hit[0]
                    used.add(c['i'])
                    tot['pos'] += 1
                    uvok = (c['uv'] == guv)
                    tot['uv'] += uvok
                    texok = bool(d['tcw']) and pages.get(d['tcw']) == c['page']
                    tot['tex'] += texok
                    print('      group %d: draw %d pos %d/%d EXACT, uv %s, texture page %s (%dx%d, TCW 0x%X)' % (
                        gi, c['i'], len(gpos), len(gpos), 'EXACT' if uvok else 'DIFF',
                        'EXACT' if texok else 'DIFF', c['tw'], c['tw'], d['tcw'] or 0))
                else:
                    print('      group %d: NO captured draw with these %d positions under this CBWorld' % (
                        gi, len(gpos)))
    stray = [c for c in cap_draws if c['i'] not in used and struct.unpack('<12f', c['W'])[11] == -40.0]
    print('RESULT frame %d: derived part draws %d, CBWorld bit-exact %d/%d; model groups %d, positions '
          'bit-exact %d/%d, uv bit-exact %d/%d, texture page byte-exact %d/%d; captured z=-40 HUD-camera '
          'draws not explained: %d' % (
              frame, tot['draws'], tot['cbw'], tot['draws'], tot['groups'], tot['pos'], tot['groups'],
              tot['uv'], tot['groups'], tot['tex'], tot['groups'], len(stray)))
    return tot['pos'] == tot['groups'] and tot['tex'] == tot['groups'] and not stray


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', type=int, nargs='+')
    ap.add_argument('--cap', default=os.path.join(HERE, 'capgate', 'state'))
    ap.add_argument('--packdir', default=os.path.join(HERE, 'capgate'))
    a = ap.parse_args()
    pol = RP.load_pol()
    _, offs = RP.model_offsets(pol)
    hdr_tcw = [RP.records(pol, offs[k])[0][0]['texIndex'] + RP.BANK_BASE for k in range(HDR_TABLE_MODELS)]
    scales = scale_table()
    pages = bank_pages()
    print('HUD bank: %d models; header-patch TCWs %s; scale table %s' % (
        len(offs), ['0x%X' % t for t in hdr_tcw], [tuple(round(v, 3) for v in s) for s in scales]))
    ok = True
    for f in a.frames:
        ok &= gate_frame(f, a.cap, os.path.join(a.packdir, 'frame_%d.pack' % f), pol, offs, hdr_tcw, scales, pages)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
