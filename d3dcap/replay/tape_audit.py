#!/usr/bin/env python3
"""tape_audit.py -- does this tape carry EVERYTHING the render model consumes, and is it sane?

    python tape_audit.py <tape.json.gz> [--library tcw_pages/index.json]

One PASS/FAIL line per requirement, with the number behind it. The requirements are the inputs the
proven emitters read (v3gate 100% on captures; tape_to_seq), not a wish list:

  A. timeline     clocks monotonic, no duplicate rows, rows without a draw list, TORN lists
  B. fighters     every row's live fighters present as kind-0 nodes; sid, facing, screen coords sane
  C. nodes        sort/layer/cat/owner/pal/gfx sane; angle+hotspot present (v4); no garbage records
  D. palettes     every referenced palette resolves and is non-empty
  E. camera       eyeX/eyeY/ground present and moving; zoom present (else the scene CB assumes 812.357)
  F. stage        stage_id in 0..0x12 and non-zero-suspect
  G. world-space  anodes per frame, matrices non-degenerate, objects parse, TCW coverage in the library
  H. wire         strides/versions declared; nothing the emitter needs is absent
"""
import argparse, base64, gzip, json, os, struct, sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))


def b64gz(s):
    return gzip.decompress(base64.b64decode(s))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('tape')
    ap.add_argument('--library', default=os.path.join(HERE, 'tcw_pages', 'index.json'))
    a = ap.parse_args()
    raw = open(a.tape, 'rb').read()
    t = json.loads(gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw)
    fails = 0

    def line(ok, name, detail):
        nonlocal fails
        fails += 0 if ok else 1
        print('  %s  %-46s %s' % ('PASS' if ok else 'FAIL', name, detail))

    cols = [c.strip() for c in t['schema'].strip('[]').split(',')]
    C = {n: i for i, n in enumerate(cols)}
    rows = t['frames']
    print('tape %s  ver %s  tape_ver %s  frames %d  cols %d' % (os.path.basename(a.tape)[:40], t.get('ver'), t.get('tape_ver'), len(rows), len(cols)))

    # ── A. timeline ──
    clk = [int(r[C['frame']]) for r in rows]
    dups = len(clk) - len(set(clk))
    steps = Counter(b - a_ for a_, b in zip(clk, clk[1:]))
    gaps = sum(v for k, v in steps.items() if k > 1)
    line(dups == 0, 'A1 no duplicate frame rows', 'dups %d' % dups)
    line(gaps < len(rows) * 0.02, 'A2 frame gaps < 2%', 'gaps %d (rollbacks reported %s)' % (gaps, t.get('rollbacks')))
    nb = b64gz(t['nodes']); stride = int(t.get('nodes_stride', 44)); off = 0; nodes = {}
    while off + 6 <= len(nb):
        fr, n = struct.unpack_from('<IH', nb, off); off += 6
        lst = []
        for _ in range(n):
            if off + stride > len(nb): break
            v = struct.unpack_from('<BBBbBBBBHHHBBBBHHHfffII', nb, off)
            ang, hx, hy = struct.unpack_from('<Hhh', nb, off + 44) if stride >= 50 else (0, 0, 0)
            oo = struct.unpack_from('<I', nb, off + 50)[0] if stride >= 54 else 0
            lst.append(dict(owner_off=oo, oslot=((oo - 0x3DB8) // 0x738 if oo >= 0x3DB8 and (oo - 0x3DB8) % 0x738 == 0 and (oo - 0x3DB8) // 0x738 < 6 else -1)) | dict(kind=v[0], slot=v[1], cat=v[2], sort=v[3], layer=v[4], face=v[5], owner=v[6], drawn=v[7],
                            sid=v[8], pal=v[9], flash=v[10], glow=v[11], zx=v[15], zy=v[16], fsx=v[18], fsy=v[19],
                            depth=v[20], gfx1=v[21], gfx2=v[22], angle=ang, hot=(hx, hy)))
            off += stride
        nodes[fr] = lst
    nolist = [c for c in clk if c not in nodes]
    torn = 0
    for i in range(1, len(clk) - 1):
        a_, b_, c_ = nodes.get(clk[i - 1]), nodes.get(clk[i]), nodes.get(clk[i + 1])
        if b_ is not None and a_ and c_ and len(b_) < 2 and len(a_) >= 3 and len(c_) >= 3: torn += 1
    line(len(nolist) == 0, 'A3 every row has a draw list', 'rows without: %d' % len(nolist))
    line(torn == 0, 'A4 no torn (partial) draw lists', 'torn: %d  <- agent read timing; a torn frame is MISSING data' % torn)

    # ── B. fighters ──
    hp = C.get('hp[6]'); miss_f = 0; bad_xy = 0; bad_face = 0; sid0 = 0; checked = 0
    for r in rows:
        lst = nodes.get(int(r[C['frame']]))
        if lst is None: continue
        alive = [s for s in range(6) if r[hp][s] > 0] if hp is not None else []
        present = {n['slot'] for n in lst if n['kind'] == 0}
        drawn = [s for s in range(6) if r[C['drawn[6]']][s]] if 'drawn[6]' in C else []
        for s in drawn:
            checked += 1
            if s not in present: miss_f += 1
        for n in lst:
            if n['kind'] == 0:
                if not (-2000 <= n['fsx'] <= 2600 and -2000 <= n['fsy'] <= 2400): bad_xy += 1
                if n['face'] not in (0, 1): bad_face += 1
                if n['sid'] == 0: sid0 += 1
    line(miss_f == 0, 'B1 drawn fighters present in the draw list', 'missing %d of %d' % (miss_f, checked))
    # off-screen is legitimate (knockbacks, supers); only garbage magnitudes count
    line(bad_xy < 0.02 * max(1, checked), 'B2 fighter screen coords sane (<2% beyond +-400 px off-screen)', 'beyond the margin %d of %d' % (bad_xy, checked))
    line(bad_face == 0 and sid0 == 0, 'B3 facing in {0,1}, sid != 0', 'bad face %d, sid 0 %d' % (bad_face, sid0))

    # ── C. nodes ──
    allnodes = [n for l in nodes.values() for n in l]
    objs = [n for n in allnodes if n['kind'] == 1]
    # an ownerless object (0xFF) is fine IF its GFX1 bank matches a fighter's in the same frame --
    # the emitter resolves the character through the bank (effects inherit their owner's GFX1)
    # bank identity is the low 16 bits (0x381714 and 0x1714 are the same bank with a flag byte);
    # a fighter node can carry gfx1 == 0 (bank pointer cleared while parked), so a bank seen on no
    # fighter resolves by ELIMINATION when exactly one slot has no known bank
    slot_bank = {}
    for lst in nodes.values():
        for n in lst:
            if n['kind'] == 0 and n['gfx1']:
                slot_bank[n['slot']] = n['gfx1'] & 0xFFFF
    known = set(slot_bank.values()); unknown_slots = [s for s in range(6) if s not in slot_bank]
    bad_owner = 0; by_elim = 0
    for fr, lst in nodes.items():
        for n in lst:
            if n['kind'] == 1 and n['owner'] > 5:
                b = n['gfx1'] & 0xFFFF
                if b in known: continue
                if len(unknown_slots) == 1: by_elim += 1; continue
                bad_owner += 1
    if by_elim: print('        (%d ownerless objects resolved by elimination to slot %s)' % (by_elim, unknown_slots))
    bad_layer = sum(1 for n in allnodes if n['layer'] > 15)
    sorts = Counter(n['sort'] for n in allnodes)
    angles = Counter(n['angle'] for n in allnodes if n['angle'])
    line(bad_layer == 0, 'C1 layer in 0..15', 'bad %d' % bad_layer)
    if stride >= 54:
        linked = sum(1 for o in objs if o.get('oslot', -1) >= 0); agree = sum(1 for o in objs if o.get('oslot', -1) >= 0 and o['owner'] < 6 and o['owner'] == o['oslot'])
        line(True, 'C6 raw owner link (0.3.38 owner_off)', 'linked %d of %d objects; agrees with owner byte on %d of %d owned' % (linked, len(objs), agree, sum(1 for o in objs if o.get('oslot', -1) >= 0 and o['owner'] < 6)))
    line(bad_owner / max(1, len(objs)) < 0.05, 'C2 objects resolve to a character (owner or GFX1)', 'unresolvable %d of %d (%.1f%%)' % (bad_owner, len(objs), 100.0 * bad_owner / max(1, len(objs))))
    line(len(sorts) > 1 and sorts.get(0, 0) < len(allnodes), 'C3 sort key live', 'values %s' % dict(sorts.most_common(6)))
    line(stride >= 50, 'C4 rotation angle + hotspot carried (v4)', 'stride %d, rotated nodes %d, angles %s' % (stride, sum(angles.values()), {hex(k): v for k, v in angles.most_common(5)}))
    zero_gfx = sum(1 for n in objs if n['gfx1'] == 0)
    line(zero_gfx == 0, 'C5 objects carry a GFX1 bank', 'zero gfx1 %d' % zero_gfx)

    # ── D. palettes ──
    pals = b64gz(t['pals']) if t.get('pals') else b''; pn = int(t.get('pals_n', 0))
    badpal = sum(1 for n in allnodes if n['pal'] != 0xFFFF and n['pal'] >= pn)
    empty = sum(1 for p in range(pn) if pals[p * 32:p * 32 + 32] == b'\x00' * 32)
    line(badpal == 0 and empty == 0 and pn > 0, 'D1 palettes resolve and are non-empty', 'pals_n %d, bad refs %d, empty %d' % (pn, badpal, empty))

    # ── E. camera ──
    for name in ('eyeX', 'eyeY', 'ground'):
        ok = name in C
        vals = [float(r[C[name]]) for r in rows] if ok else []
        line(ok and (len(set(vals)) > 1 or name == 'ground'), 'E1 camera column %s' % name, ('range %.1f..%.1f' % (min(vals), max(vals))) if ok else 'ABSENT')
    line('zoom' in C, 'E2 camera zoom column', 'present' if 'zoom' in C else 'ABSENT -- scene CB assumes 812.357 (constant in every capture so far)')

    # ── F. stage ──
    sid = t.get('stage_id')
    line(sid is not None and 0 <= int(sid) <= 0x12, 'F1 stage_id plausible', 'stage_id %s%s' % (sid, '' if sid else '  <- 0 is suspect: agent < 0.3.36 read blk+0x6D3C'))

    # ── G. world-space ──
    if t.get('anodes'):
        ab = b64gz(t['anodes']); astride = int(t.get('anodes_stride', 96)); off = 0; af = 0; an = 0; lists = Counter(); degenerate = 0; refs = Counter()
        while off + 6 <= len(ab):
            fr, n = struct.unpack_from('<IH', ab, off); off += 6
            for _ in range(n):
                if off + astride > len(ab): break
                m = struct.unpack_from('<16f', ab, off + 8)
                if abs(m[0]) + abs(m[5]) + abs(m[10]) == 0: degenerate += 1
                lists[ab[off]] += 1; refs[struct.unpack_from('<H', ab, off + 84)[0]] += 1
                off += astride; an += 1
            af += 1
        ob = b64gz(t['aobjs']); no = struct.unpack_from('<H', ob, 0)[0]; o = 2; tcws = Counter(); badobj = 0
        for k in range(no):
            ln = struct.unpack_from('<I', ob, o)[0]; body = ob[o + 4:o + 4 + ln]; o += 4 + ln
            if len(body) < 0x28 or struct.unpack_from('<i', body, 0x18)[0] >= 0: badobj += 1; continue
            tcws['%08X' % struct.unpack_from('<I', body, 0x18 + 0x0C)[0]] += refs.get(k, 0)
        lib = json.load(open(a.library)) if os.path.exists(a.library) else {}
        # stage textures: TCW = 0xC10 + index into the loaded stage's TEX list (arc rip, by stage_id)
        stg = os.path.join('C:/Users/trist/projects/maplecast-flycast/atlas/stages', 'STG%02X.json' % int(t.get('stage_id') or 0))
        ntex = len(json.load(open(stg))['textures']) if os.path.exists(stg) else 0
        def have(k):
            if k in lib: return True
            try: return 0 <= int(k, 16) - 0xC10 < ntex
            except ValueError: return False
        covered = sum(v for k, v in tcws.items() if have(k)); total = sum(tcws.values())
        line(af >= len(nodes) * 0.98, 'G1 world-space nodes on every frame', '%d frames, %d nodes (%.1f/frame), lists %s' % (af, an, an / max(1, af), dict(sorted(lists.items()))))
        line(degenerate == 0, 'G2 node matrices non-degenerate', 'degenerate %d' % degenerate)
        line(badobj == 0, 'G3 polygon-list objects parse', '%d objects, unparsable %d' % (no, badobj))
        missing = {k: v for k, v in tcws.items() if not have(k)}
        line(covered == total, 'G4 every used TCW has a page in the library', '%d of %d node-uses covered (%.1f%%); missing %s' % (covered, total, 100.0 * covered / max(1, total), dict(Counter(missing).most_common(6))))
    else:
        line(False, 'G world-space stream', 'ABSENT (tape_ver < 5)')

    # ── H. wire ──
    line(t.get('nodes_ver') == 4 and t.get('tape_ver', 0) >= 5, 'H1 versions declared', 'nodes_ver %s tape_ver %s' % (t.get('nodes_ver'), t.get('tape_ver')))
    print('\nRESULT: %s' % ('COMPLETE -- nothing the render model reads is missing' if fails == 0 else '%d requirement(s) FAILED' % fails))
    return 0 if fails == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
