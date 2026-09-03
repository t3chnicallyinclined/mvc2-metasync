#!/usr/bin/env python3
"""TSP/ISP/PCW -> D3D11 state gate.

Matches every vs_world draw of a capture .pack to a polygon GROUP of a tape object record (same
stage) by vertex positions, then checks that the render state PREDICTED from the record's header
words (PCW @0, ISP @4, TSP @8) through tsp_state.codes()/HOST equals the state the capture
recorded on that draw (sampler filter/address, blend src/dst, depth write/stencil, cull, ps
variant). With --hist it prints, per predicted code, the histogram of captured values -- that is
how the HOST table was derived and how it would be refuted (a code with two captured values).

    python tsp_gate.py [--hist] <tape.json.gz> <pack> [<pack> ...]
"""
import base64, gzip, json, os, struct, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tsp_state as TS


def load_pack(path):
    f = open(path, 'rb'); assert f.read(4) == b'RRPK'
    n = struct.unpack('<I', f.read(4))[0]; man = json.loads(f.read(n)); body = f.read()
    return man, (lambda b: body[b['off']:b['off'] + b['len']])


def groups(pay):
    """Polygon groups of a NaomiLib mesh payload: (group flags, [(x,y,z,u,v)...]) in strip order
    (same walk as tape_to_seq.nl_triangles, kept per group because one group = one D3D draw)."""
    n = len(pay); sa = 0; res = []
    while sa + 8 <= n:
        flags, vcount = struct.unpack_from('<II', pay, sa)
        if flags == 0 and vcount == 0:
            break
        triple = bool((flags >> 3) & 1)
        sa += 8; vs = []; ended = False
        for _ in range(vcount * (3 if triple else 1)):
            if sa + 8 > n:
                ended = True; break
            head = struct.unpack_from('<I', pay, sa)[0]
            if head == 0:
                ended = True; sa += 8; break
            if 0x5FF0 <= (head >> 16) <= 0x5FFF:
                voff = struct.unpack_from('<i', pay, sa + 4)[0]; ca = sa + voff + 8; sa += 8
            else:
                ca = sa; sa += 0x20
            if 0 <= ca and ca + 0x20 <= n:
                v = struct.unpack_from('<8f', pay, ca)
                vs.append((v[0], v[1], v[2], v[6], v[7]))
        res.append((flags, vs))
        if ended:
            break
    return res


def tape_groups(tape):
    """[(obj, rec, group, hdr dict, group flags, verts)] for every polygon group in the tape's objects."""
    ob = gzip.decompress(base64.b64decode(tape['aobjs']))
    n = struct.unpack_from('<H', ob, 0)[0]; o = 2
    out = []
    for oi in range(n):
        ln = struct.unpack_from('<I', ob, o)[0]; body = ob[o + 4:o + 4 + ln]; o += 4 + ln
        q = 0x18; ri = 0
        while q + 0x50 <= len(body):
            pcw, isp, tsp, tcw = struct.unpack_from('<4I', body, q)
            if pcw < 0x80000000:
                break
            size = struct.unpack_from('<i', body, q + 0x4C)[0]
            hdr = dict(pcw=pcw, isp=isp, tsp=tsp, tcw=tcw,
                       texnum=struct.unpack_from('<i', body, q + 0x20)[0],
                       colmode=struct.unpack_from('<i', body, q + 0x24)[0],
                       colour=struct.unpack_from('<4f', body, q + 0x2C))
            pay = body[q + 0x50:q + 0x50 + max(0, size)]
            for gi, (gflags, vs) in enumerate(groups(pay)):
                out.append((oi, ri, gi, hdr, gflags, vs))
            q += 0x50 + max(0, size); ri += 1
    return out


def key_of(pts):
    return tuple(sorted(set((round(x, 2), round(y, 2), round(z, 2)) for x, y, z in pts)))


def pack_draws(man, B):
    vb, ib = B(man['vb']), B(man['ib'])
    out = []
    for d in man['draws']:
        if d.get('vsVariant') != 'vs_world':
            continue
        idx = struct.unpack_from('<%dI' % d['indexCount'], ib, d['firstIndex'] * 4)
        pts = []
        for k in sorted(set(idx)):
            o = d['voff'] + k * d['stride']
            pts.append(struct.unpack_from('<3f', vb, o))
        P = lambda k: struct.unpack_from('<3f', vb, d['voff'] + k * d['stride'])
        tris = tri_set([(P(idx[i]), P(idx[i + 1]), P(idx[i + 2])) for i in range(0, len(idx) - 2, 3)])
        out.append((d, key_of(pts), len(set(idx)), tris))
    return out


def steam_tris(vs, flags):
    """Steam's CPU strip expansion (FUN_1408482a0): even i (i,i+1,i+2), odd i (i+2,i+1,i);
    'triple' groups (bit 3) verbatim. Winding-preserving."""
    if flags & 8:
        return [tuple(vs[i:i + 3]) for i in range(0, len(vs) - 2, 3)]
    return [((vs[i], vs[i + 1], vs[i + 2]) if i % 2 == 0 else (vs[i + 2], vs[i + 1], vs[i]))
            for i in range(len(vs) - 2)]


def tri_set(tris):
    """Rotation-invariant, winding-preserving triangle keys (degenerates dropped)."""
    out = []
    for t in tris:
        p = [tuple(round(c, 2) for c in v[:3]) for v in t]
        if len(set(p)) < 3:
            continue
        k = min(range(3), key=lambda i: p[i])
        out.append(tuple(p[k:] + p[:k]))
    return sorted(out)


FIELDS = ('samp', 'blend', 'depth', 'cull', 'ps', 'winding')


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    hist = '--hist' in sys.argv
    tape = json.load(gzip.open(args[0]))
    print('tape stage %s, %s objects' % (tape.get('stage_id'), tape.get('aobjs_n')))
    tg = tape_groups(tape)
    print('%d polygon groups in the tape object table' % len(tg))
    bykey = collections.defaultdict(list)
    for g in tg:
        bykey[key_of([(v[0], v[1], v[2]) for v in g[5]])].append(g)
    tot = collections.Counter()
    per_field = {f: collections.Counter() for f in FIELDS}
    mism = collections.Counter()
    code_hist = {f: collections.defaultdict(collections.Counter) for f in FIELDS}
    for pk in args[1:]:
        man, B = load_pack(pk)
        draws = pack_draws(man, B)
        n_m = n_u = n_amb = 0
        for d, key, nv, ptris in draws:
            cands = bykey.get(key)
            if not cands:
                n_u += 1; tot['unmatched'] += 1; continue
            # several records may share the geometry (e.g. the untextured HUD quads, TSP 20080440 vs
            # 20880440); that is only ambiguous if their PREDICTED codes differ
            preds = {}
            for c in cands:
                pc = TS.predict(c[3]['pcw'], c[3]['isp'], c[3]['tsp'], c[4])
                cd0 = pc['_codes']
                preds.setdefault((cd0['samp'], cd0['blend'], cd0['depth'], cd0['cull'], cd0['ignore_texa']), []).append((c, pc))
            if len(preds) > 1:
                n_amb += 1; tot['ambiguous'] += 1; continue
            n_m += 1; tot['matched'] += 1
            same = next(iter(preds.values()))
            c, pred = same[0]
            got = TS.captured(d)
            # winding: the captured triangles (pack index order) vs Steam's own strip expansion of
            # the record's group -- this is what makes a per-group cull word applicable verbatim.
            # Same geometry in several records = one of them is the drawn one: any of them counts.
            pred['winding'] = 'steam-rule'
            got['winding'] = 'steam-rule' if any(tri_set(steam_tris(cc[5], cc[4])) == ptris for cc, _ in same) else 'DIFFERS'
            cd = pred['_codes']
            code_of = dict(samp=cd['samp'], blend=cd['blend'], depth=cd['depth'], cull=cd['cull'],
                           ps=cd['ignore_texa'], winding='bit6=%d' % bool(c[4] & 0x40))
            for f in FIELDS:
                code_hist[f][code_of[f]][got[f]] += 1
                ok = pred[f] == got[f]
                per_field[f]['ok' if ok else 'BAD'] += 1
                if not ok:
                    mism[(f, 'code=%s' % (code_of[f],), 'pred=%s' % (pred[f],), 'got=%s' % (got[f],),
                          'TSP %08X ISP %08X PCW %08X G %X' % (c[3]['tsp'], c[3]['isp'], c[3]['pcw'], c[4]))] += 1
        print('%s: %d vs_world draws: matched %d, unmatched %d, ambiguous %d' % (
            os.path.basename(pk), len(draws), n_m, n_u, n_amb))
    if hist:
        print('\nCAPTURED STATE PER PREDICTED CODE (a code with >1 value refutes the model):')
        for f in FIELDS:
            for code, cnt in sorted(code_hist[f].items(), key=lambda kv: str(kv[0])):
                flag = '' if len(cnt) == 1 else '   <-- AMBIGUOUS'
                print('  %-6s code %-8s -> %s%s' % (f, code, dict(cnt), flag))
    print('\nFIELD     ok    BAD')
    for f in FIELDS:
        print('%-8s %5d %5d' % (f, per_field[f]['ok'], per_field[f]['BAD']))
    if mism:
        print('\nmismatches:')
        for k, v in mism.most_common(40):
            print('%5d  %s' % (v, '  '.join(k)))
    print('\ntotals', dict(tot))


if __name__ == '__main__':
    main()
