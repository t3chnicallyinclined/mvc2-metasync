#!/usr/bin/env python3
"""rip_parts.py -- rip the HUD / common-model bank (TCW base 0xC90, AFS 835 POL + 836 TEX) that the
list-0xC "part" walker FUN_140653a70 draws from, into per-model JSON under tcw_pages/parts/ (gitignored).

WHAT THESE MODELS ARE (docs/PARTS-LIST0C-GHIDRA.md): the per-fighter list-0xC nodes are the COMBO HIT
COUNTER. FUN_140652cc0 sprintf's the i16 at node+0x172 into node+0x228..0x22A (digit char - '0';
' ' -> -16 = blank) and points node+0x110 at the static part list DAT_140a7a2f0; FUN_140653a70 walks the
list and draws PTR_DAT_142edf598[modelIdx] (= this bank's host model table) with the HUD camera
FUN_14061d5b0 (P(0x4000), V = I) and W = T(node+0x50) chained with per-part translate/scale.
Before a draw, FUN_14060d8d0(model, count-1) overwrites the model's record header words
(PCW, ISP, TSP, TCW) with DAT_142eed370[count-1] = the first record header of models 0..3 of this bank
(FUN_14060c370 case 4, FUN_140619720), i.e. TCW 0xC92 + (count-1).

Model layout (NaomiLib, same as the stage POL): POL header u32@0 model-table DC ptr, u32@4 count,
u32@8 texHdrs DC ptr; file offset = DC ptr - (u32@0 - 0x10). Model = 0x18 header, then records while
(int)PCW < 0: 0x50 header (PCW@0 ISP@4 TSP@8 TCW@0xC, texIndex i32@0x20, colour mode i32@0x24,
alpha f32@0x2C, colour 3f@0x30, payload size u32@0x4C), payload = polygon groups (tape_to_seq.nl_groups).

    python rip_parts.py                # rip every model -> tcw_pages/parts/part_NNN.json + index
    python rip_parts.py --only 9 17    # subset
    python rip_parts.py --print 9      # dump one model's vertices to stdout
    python rip_parts.py --lists        # every STATIC part list the list-0xC writers point +0x110/+0x118 at,
                                       # read from the exe dump (MVC_DUMP) -> tcw_pages/parts/partlists.json

NOTE: the consumer FUN_1408482a0 clears bit 0 of the x word and of the v word of every vertex it copies
into the D3D VB (x &= ~1, v &= ~1: the NaomiLib direct-vertex flag). The JSON keeps the FILE values;
parts_gate.py applies the mask before comparing (82/82 positions and uvs bit-exact once applied).
"""
import argparse, json, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rip_texbank as R          # noqa: E402  (archive loader, CONFIRMED against the game's own copy)
import tape_to_seq as T          # noqa: E402  (nl_groups: Steam's own strip expansion FUN_1408482a0)

OUT = os.path.join(HERE, 'tcw_pages', 'parts')
BANK_BASE = 0xC90
POL_ENTRY, TEX_ENTRY = 0x343, 0x344      # AFS 835 / 836 (docs/TEXTURE-BANKS-GHIDRA.md s3)


def u32(b, o): return struct.unpack_from('<I', b, o)[0]
def i32(b, o): return struct.unpack_from('<i', b, o)[0]


def load_pol(arc=R.DEFAULT_ARC):
    m, ents = R.load_afs(arc)
    pol, off, sz = R.afs_entry(m, ents, POL_ENTRY)
    return pol


def model_offsets(pol):
    tbl, cnt = u32(pol, 0), u32(pol, 4)
    base = tbl - 0x10
    return base, [u32(pol, tbl - base + 4 * i) - base for i in range(cnt)]


def records(pol, mo):
    """[(header dict, payload bytes)] of the model at file offset mo."""
    out = []
    q = mo + 0x18
    while q + 0x50 <= len(pol):
        pcw = i32(pol, q)
        if pcw >= 0:
            break
        size = u32(pol, q + 0x4C)
        hdr = dict(pcw=u32(pol, q), isp=u32(pol, q + 4), tsp=u32(pol, q + 8), tcw=u32(pol, q + 12),
                   texIndex=i32(pol, q + 0x20), colourMode=i32(pol, q + 0x24),
                   alpha=struct.unpack_from('<f', pol, q + 0x2C)[0],
                   colour=list(struct.unpack_from('<3f', pol, q + 0x30)), size=size,
                   centre=list(struct.unpack_from('<4f', pol, q + 0x10)))
        out.append((hdr, pol[q + 0x50:q + 0x50 + size]))
        q += 0x50 + size
    return out


def rip_model(pol, mo, idx):
    recs = []
    for hdr, pay in records(pol, mo):
        groups = []
        for flags, tris in T.nl_groups(pay, hdr['colourMode'] == -3):
            groups.append(dict(flags=flags, tris=[[list(v[0:3]), list(v[6:8])] for v in tris]))
        recs.append(dict(header=hdr, tcw_file=hdr['tcw'], texIndex=hdr['texIndex'],
                         tcw_runtime=(BANK_BASE + hdr['texIndex']) if hdr['texIndex'] >= 0 else None,
                         groups=groups))
    return dict(model=idx, file_off=mo, records=recs)


DUMP = os.environ.get('MVC_DUMP', 'C:/Users/trist/ghidra_projects/mvc_dump.bin')
IMAGE_BASE = 0x140000000
# every static part-list root the +0x110/+0x118 writers use (docs/PARTS-LIST0C-GHIDRA.md s3):
LIST_ROOTS = {
    'combo_hits': [0x140a7a2f0],                   # FUN_140652cc0: "%3d" + HIT/S   (digits from node+0x228)
    'combo_points': [0x140a7a330],                 # FUN_140652c50 second line: "%8x" (node+0x228, 8 digits)
    'combo_rating': ('ptrs', 0x140a7a3b0, 16),     # FUN_140652c50 first line: DAT_140a7a3b0[node+0x180 & 0xF]
    'round_text': ('ptrs', 0x140a987f0, 16),       # FUN_14073dfb0 callback caseD_0: PTR_LAB_140a987f0[node+0x34]
    'result_time': ('ptrs', 0x140aac980, 7),       # FUN_1407ec920 / FUN_1407ec6b0: DAT_140aac980[node+0x34]
}
SCALE_TABLE = 0x140a7a2b0                          # 8 pointers to (sx, sy, sz)
XOFF_TABLES = {'combo_rating_x2': (0x140a7a430, 16), 'round_text_x': (0x140a98870, 16)}


def dump_lists():
    D = open(DUMP, 'rb').read()

    def rd(a, n):
        return D[a - IMAGE_BASE:a - IMAGE_BASE + n]

    def plist(a):
        out = []
        for k in range(64):
            c, f, si, mi, x = struct.unpack('<bbbbf', rd(a + 8 * k, 8))
            if c < 0:
                break
            out.append(dict(count=c, flags=f, scaleIdx=si, modelIdx=mi, xoff=x))
        return out
    lists = {}
    roots = {}
    for name, spec in LIST_ROOTS.items():
        if isinstance(spec, list):
            addrs = spec
        else:
            _, tbl, n = spec
            addrs = [struct.unpack('<Q', rd(tbl + 8 * i, 8))[0] for i in range(n)]
        roots[name] = ['0x%X' % a for a in addrs]
        for a in addrs:
            lists['0x%X' % a] = plist(a)
    scales = [list(struct.unpack('<3f', rd(struct.unpack('<Q', rd(SCALE_TABLE + 8 * i, 8))[0], 12))) for i in range(8)]
    xoff = {k: list(struct.unpack('<%df' % n, rd(a, 4 * n))) for k, (a, n) in XOFF_TABLES.items()}
    out = dict(image_base='0x%X' % IMAGE_BASE, roots=roots, lists=lists, scale_table=scales, xoff_tables=xoff,
               line2_y=-6.0, header_patch='DAT_142eed370[k] = first record header of HUD model k (k = count - 1)')
    os.makedirs(OUT, exist_ok=True)
    json.dump(out, open(os.path.join(OUT, 'partlists.json'), 'w'), indent=1)
    print('wrote %d lists (%d roots) to %s' % (len(lists), len(roots), os.path.join(OUT, 'partlists.json')))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--arc', default=R.DEFAULT_ARC)
    ap.add_argument('--lists', action='store_true')
    ap.add_argument('--only', nargs='*', type=int)
    ap.add_argument('--print', type=int, default=None)
    a = ap.parse_args()
    if a.lists:
        dump_lists()
        return 0
    pol = load_pol(a.arc)
    base, offs = model_offsets(pol)
    if a.print is not None:
        m = rip_model(pol, offs[a.print], a.print)
        for r in m['records']:
            print('record tcw_file 0x%X texIndex %d -> runtime TCW 0x%X colour %s' % (r['tcw_file'], r['texIndex'], r['tcw_runtime'] or 0, r['header']['colour']))
            for g in r['groups']:
                print('  group flags 0x%X tris %d' % (g['flags'], len(g['tris']) // 3))
                for v in g['tris']:
                    print('    %9.4f %9.4f %9.4f  uv %.4f %.4f' % (*v[0], *v[1]))
        return 0
    os.makedirs(OUT, exist_ok=True)
    index = []
    for i, mo in enumerate(offs):
        if a.only and i not in a.only:
            continue
        m = rip_model(pol, mo, i)
        nv = sum(len(g['tris']) for r in m['records'] for g in r['groups'])
        xs = [v[0][0] for r in m['records'] for g in r['groups'] for v in g['tris']]
        ys = [v[0][1] for r in m['records'] for g in r['groups'] for v in g['tris']]
        zs = [v[0][2] for r in m['records'] for g in r['groups'] for v in g['tris']]
        index.append(dict(model=i, records=len(m['records']), tri_verts=nv,
                          tex=[r['tcw_runtime'] for r in m['records']],
                          x=[min(xs), max(xs)] if xs else None, y=[min(ys), max(ys)] if ys else None,
                          z=[min(zs), max(zs)] if zs else None))
        json.dump(m, open(os.path.join(OUT, 'part_%03d.json' % i), 'w'))
    json.dump(dict(bank_base=BANK_BASE, afs_pol=POL_ENTRY, afs_tex=TEX_ENTRY, models=index),
              open(os.path.join(OUT, 'index.json'), 'w'), indent=1)
    for e in index:
        print('model %3d recs %d triverts %4d tcw %s x %s y %s z %s' % (e['model'], e['records'], e['tri_verts'],
              ['0x%X' % t if t else None for t in e['tex']], e['x'], e['y'], e['z']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
