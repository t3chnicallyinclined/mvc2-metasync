#!/usr/bin/env python3
"""sort_gate.py -- reproduce Steam's TRANSLUCENT (category 3) draw order from derived sort keys.

    python sort_gate.py <tape.json.gz> capgate/frame_4445.pack [more packs]

Ghidra (docs/TRANSLUCENT-SORT-GHIDRA.md), all CONFIRMED by decompile:
  FUN_1408436a0   queue append: slot {u32 seq @0, kind @4, entry* @8, size @0x10, f32 key @0x14, cat @0x18}
  FUN_140843320   record key = w of [centre(rec+0x10..0x18) 1] x W x V x P x Screen  (Screen col 3 = 0,0,0,1)
                  radius(rec+0x1C) < 0 -> key = -radius ; (cfg+0x48 == 8 and radius > 7000 -> 10000)
  case 0xC        sprite key = the walker depth node+0x12C (+0.001 per record inside FUN_1406129f0), taken
                  BEFORE FUN_1408432e0 turns it into the vertex z = max(0, (P32 - D*P22)/D)
  FUN_140842e30   qsort(slots, n, 0x20, LAB_1408434d0) for cat 3 only; MSVC 2015 CRT qsort (FUN_140817f80)
  LAB_1408434d0   key DESC (comiss), tie -> seq ASC (unsigned)  => total order, qsort variant irrelevant
  FUN_140843eb0   flush passes 2, 3, 0; per pass cats 0,1,2,3   => all Z-write draws first, then cat 3 sorted
Submission order (FUN_140620960): sprite walker (layer asc, array idx) -> deck -> lists 5,6,7,8 -> 0xB -> 0xC.

Gate: for every cat-3 draw of a gold pack (depth write OFF) derive the key (records via the tape's own
object table joined by vertex set, W from the captured CBWorld, V/P from the captured scene CB rows 7-10 /
15-18; sprites from the state dump's LayerZ table blk+0x6D08) and check the gold sequence is key-descending
with distinct-entry ties in submission order.
"""
import base64, gzip, hashlib, json, os, struct, sys, collections
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tsp_gate as TG
import blkstate as BS

CAP = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'capgate', 'state')
LAYERZ0 = [15, 17, 19, 21, 23, 25, 27, 29, 10, 11, 12, 13, 30, 31, 32, 33]   # blk+0x6D08 per-layer depth bases
LIST_SUB = {'deck': 0.5, 5: 1, 6: 2, 7: 3, 8: 4, 11: 5, 12: 6, 13: 5}
f32 = np.float32
P22, P32 = f32(-1.0000014), f32(-2.0000014)    # world camera P (far 1.4e6): what the sprite walk leaves in slot 3


def tape_records(tape):
    ob = gzip.decompress(base64.b64decode(tape['aobjs']))
    n = struct.unpack_from('<H', ob, 0)[0]; o = 2; out = []
    for oi in range(n):
        ln = struct.unpack_from('<I', ob, o)[0]; body = ob[o + 4:o + 4 + ln]; o += 4 + ln
        q = 0x18; ri = 0
        while q + 0x50 <= len(body):
            pcw = struct.unpack_from('<I', body, q)[0]
            if pcw < 0x80000000:
                break
            size = struct.unpack_from('<i', body, q + 0x4C)[0]
            cx, cy, cz, rad = struct.unpack_from('<4f', body, q + 0x10)
            hdr = dict(pcw=pcw, centre=(cx, cy, cz), radius=rad, obj=oi, rec=ri)
            for gi, (gflags, vs) in enumerate(TG.groups(body[q + 0x50:q + 0x50 + max(0, size)])):
                out.append((oi, ri, gi, hdr, gflags, vs))
            q += 0x50 + max(0, size); ri += 1
    return out


def W_from_cbw(b):
    r = struct.unpack('<12f', b); W = np.identity(4, dtype=f32)
    for i in range(3):
        for j in range(4):
            W[j, i] = r[i * 4 + j]          # CBWorld row i = column i of the row-vector W
    return W


def key_world(hdr, W, V, P, hud):
    """FUN_140843320 (kind 2/3: cur=W, then slot2=V, slot3=P; kind 0 HUD: slot 3 only)."""
    r = f32(hdr['radius'])
    if r < 0:
        return float(-r)
    v = np.array([*hdr['centre'], 1.0], dtype=f32)
    return float((v @ ((W @ P) if hud else (W @ V @ P)))[3])


def sprite_keys_from_dump(blk):
    """The walker's D per submitted record, from the post-walk LayerZ table (base + 0.001 * parts)."""
    lz = struct.unpack_from('<16f', blk, 0x6D08); out = []
    for L in range(16):
        n = int(round((lz[L] - LAYERZ0[L]) / 0.001))
        for k in range(n):
            D = f32(812.3572998046875 * f32(0.1)) + f32(LAYERZ0[L]) + f32(0.001) * k
            out.append((float(D), float(max(f32(0), (P32 - D * P22) / D)), L, k))
    out.sort(reverse=True)
    return out


def run(pk, bykey, use_dump_sprites=True):
    fr = int(os.path.basename(pk).split('_')[1].split('.')[0])
    man, B = TG.load_pack(pk); cbs = man['constantBuffers']; vb, ib = B(man['vb']), B(man['ib'])
    cb = lambda h: next((B(cbs[k]) for k in cbs if k.startswith(h)), None)
    meta, blk = BS.load_frame(fr, cap=CAP); base, _, _ = BS.find_base(blk)
    nodeby = {}
    for nd in BS.anodes(blk, base):
        m = nd['matrix']
        cbw = struct.pack('<12f', m[0], m[4], m[8], m[12], m[1], m[5], m[9], m[13], m[2], m[6], m[10], m[14])
        nodeby.setdefault(hashlib.sha256(cbw).hexdigest()[:8].upper(), []).append((nd['list'], nd['idx']))
    identh = hashlib.sha256(struct.pack('<12f', 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0)).hexdigest()[:8].upper()
    # the dump is taken at the sprite walk ('at': 'walk'), BEFORE FUN_140620740(7/8/11) rewrites +0xA8, so a
    # moving node's matrix is one frame stale: identify those by this frame's position +0x50 (x0.1 on 7/8/9)
    posby = {}
    for nd in BS.anodes(blk, base):
        sc = 0.1 if nd['list'] in (7, 8, 9) else 1.0
        posby.setdefault(tuple(round(c * sc, 2) for c in nd['pos']), []).append((nd['list'], nd['idx']))
    skeys = sprite_keys_from_dump(blk) if use_dump_sprites else []
    rows = []; si = 0
    for d in man['draws']:
        if d['depth']['write']:
            continue
        idx = struct.unpack_from('<%dI' % d['indexCount'], ib, d['firstIndex'] * 4)
        pts = [struct.unpack_from('<3f', vb, d['voff'] + k * d['stride']) for k in sorted(set(idx))]
        if d['vsVariant'] == 'vs_flat':
            z = max(p[2] for p in pts)
            if z <= 0:
                rows.append(dict(i=d['i'], ent=('digit', d['i']), key=None, how='D<=2 (clamped z; exact D UNKNOWN)', z=z))
            elif si < len(skeys):
                D, zp, L, k = skeys[si]; si += 1
                rows.append(dict(i=d['i'], ent=('sprite', L, k), key=D, how='dump', z=z, zpred=zp, sub=0))
            else:
                rows.append(dict(i=d['i'], ent=('sprite', d['i']), key=float(P32 / (f32(z) + P22)), how='vz-inverted', z=z, sub=0))
            continue
        cands = bykey.get(TG.key_of(pts))
        if not cands:
            rows.append(dict(i=d['i'], ent=None, key=None, how='UNJOINED')); continue
        scb, wcb = cb(d['vscbHash'][1]), cb(d['vscbHash'][0])
        V = np.array(struct.unpack_from('<16f', scb, 7 * 16), dtype=f32).reshape(4, 4)
        P = np.array(struct.unpack_from('<16f', scb, 15 * 16), dtype=f32).reshape(4, 4)
        W = W_from_cbw(wcb); hud = bool(np.allclose(V, np.identity(4)) and abs(P[0, 0] - 1.0) < 1e-3)
        ks = sorted(set((round(key_world(c[3], W, V, P, hud), 4), c[0], c[1], c[3]['radius']) for c in cands))
        wh = d['vscbHash'][0][:8]
        tr = tuple(round(c, 2) for c in struct.unpack_from('<12f', wcb)[3::4])
        if wh not in nodeby and tr not in posby and wh != identh:
            print('       unidentified W translation', tr, 'draw', d['i'])
        node = (nodeby.get(wh) or ([('deck', 0)] if wh == identh else None) or posby.get(tr) or [('?', 0)])[0]
        rows.append(dict(i=d['i'], ent=(node, ks[0][1], ks[0][2]), key=ks[0][0], how='w', rad=ks[0][3],
                         sub=LIST_SUB.get(node[0], 9), amb=len(set(k[0] for k in ks)) > 1))
    prev = None; rises = 0; joined = 0
    for r in rows:
        if r['key'] is None:
            continue
        joined += 1
        if prev is not None and r['key'] > prev + 1e-4:
            rises += 1; r['RISE'] = True
        prev = r['key']
    ties = tie_bad = 0
    for a, b in zip(rows, rows[1:]):
        if a['key'] is None or b['key'] is None or a['ent'] == b['ent']:
            continue
        if abs(a['key'] - b['key']) <= 1e-4:
            ties += 1
            sa = (a.get('sub', 9),) + (tuple(a['ent'][0][1:]) if isinstance(a['ent'][0], tuple) else ()) + tuple(a['ent'][1:])
            sb = (b.get('sub', 9),) + (tuple(b['ent'][0][1:]) if isinstance(b['ent'][0], tuple) else ()) + tuple(b['ent'][1:])
            if sa > sb:
                tie_bad += 1; b['TIEBAD'] = (sa, sb)
    dz = [abs(r['z'] - r['zpred']) for r in rows if 'zpred' in r]
    nspr = sum(1 for r in rows if r['ent'] and r['ent'][0] == 'sprite')
    print('== %s: cat-3 draws %d | keyed %d | unjoined %d | key rises %d | distinct-entry ties %d (out of submission order %d)'
          % (os.path.basename(pk), len(rows), joined, sum(1 for r in rows if r['how'] == 'UNJOINED'), rises, ties, tie_bad))
    print('   sprites %d (%s), dump-predicted vertex z max|dz| %s ; digits (z=0) %d ; r>7000 records %s'
          % (nspr, 'from state dump' if use_dump_sprites else 'engine key inverted from captured z',
             ('%.2g' % max(dz)) if dz else 'n/a', sum(1 for r in rows if r['ent'] and r['ent'][0] == 'digit'),
             [(r['i'], r['ent'][0], round(r['key'])) for r in rows if r.get('rad', 0) > 7000]))
    for n, r in enumerate(rows):
        if r.get('RISE') or r.get('TIEBAD') or r['how'] == 'UNJOINED' or r.get('amb'):
            print('   ', r)
            if r.get('TIEBAD') and r['ent'][0][0] == '?':
                print('       list-7 node positions x0.1:', sorted(k for k, v in posby.items() if v[0][0] == 7))
            if r.get('RISE'):
                for q in rows[max(0, n - 3):n]:
                    print('       prev:', {k: q[k] for k in ('i', 'ent', 'key', 'how', 'z') if k in q})
    return rows


def main():
    tape = json.load(gzip.open(sys.argv[1])); recs = tape_records(tape)
    bykey = collections.defaultdict(list)
    for g in recs:
        bykey[TG.key_of([(v[0], v[1], v[2]) for v in g[5]])].append(g)
    print('tape stage %s: %d polygon groups' % (tape.get('stage_id'), len(recs)))
    for pk in sys.argv[2:]:
        fr = int(os.path.basename(pk).split('_')[1].split('.')[0])
        # the 4505 pack and the 4505 state dump are not the same frame (no dump in 4490..4520 carries its
        # 122-part sprite set): sprite keys there come from the engine's own captured z
        run(pk, bykey, use_dump_sprites='--no-dump-sprites' not in sys.argv and fr != 4505)


if __name__ == '__main__':
    main()
