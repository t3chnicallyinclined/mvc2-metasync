#!/usr/bin/env python3
"""states_to_tape.py -- turn a burst of captured STATE dumps into a TAPE v4 file, so the very
frames the pixel gate proves can be played through the tape path (tape_to_seq -> player.html).

    python states_to_tape.py 4329 4508 -o cap_storm-hail_tape.json

The tape carries exactly what the v4 agent would have recorded for these frames: the engine's
draw list in walk order (fighters and pool objects interleaved), per node the placement fields the
walker wrote (fsx/fsy, facing, sid, sort, layer, angle, hotspot). Palettes are the characters'
default costume rows from the atlas LUT -- the block does not hold the live palette bytes (the
agent reads them through a pointer the dump does not follow), so colours here are default-costume
while every GEOMETRY field is the captured one. Rows carry hp = 144 placeholders; this tape is for
the render path, not the receipt.
"""
import argparse, base64, gzip, json, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blkstate as BS
import v3gate as V3

ATL = V3.ATL


def lut_pal(cid):
    """32 B ARGB4444 for the character's default body palette (row 0 of its bodyBank block)."""
    lut = json.load(open(os.path.join(ATL, 'PL%02X_lut.json' % cid)))
    bank = lut['banks'][lut.get('bodyBank', 0)]
    out = b''
    for i in range(16):
        r, g, b, a = bank[i][:4]
        w = ((a >> 4) << 12) | ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4)
        out += struct.pack('<H', w)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('first', type=int)
    ap.add_argument('last', type=int)
    ap.add_argument('-o', '--out', required=True)
    ap.add_argument('--packs', default='capgate', help='dir of frame_<f>.pack files: world-space nodes get their '
                    'vertices/pages from the matching draws (the state block has no polygon-list objects)')
    a = ap.parse_args()
    import hashlib
    aobjs, aobj_idx, anodes_blob, aframes = [], {}, b'', 0
    tcw_index = {}
    tp = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tcw_pages', 'index.json')
    if os.path.exists(tp):
        for k, v in json.load(open(tp)).items():
            tcw_index[v['sha']] = k
    pages = {}                       # pseudo-TCW -> page bytes (shipped beside the tape for the offline test)
    pals, pal_idx = [], {}
    rows, nodes_blob = [], b''
    teams = None
    nframes = 0
    for fr in range(a.first, a.last + 1):
        try:
            meta, blk = BS.load_frame(fr)
        except SystemExit:
            continue
        base, _, _ = BS.find_base(blk)
        if meta.get('base'):
            base = int(meta['base'])
        if not base:
            continue
        cids = [blk[BS.H0_OFF + s * BS.SLOT_STRIDE + V3.H_CID] for s in range(6)]
        if teams is None:
            teams = ([cids[0], cids[2], cids[4]], [cids[1], cids[3], cids[5]])
        fighters = {base + BS.H0_OFF + s * BS.SLOT_STRIDE: s for s in range(6)}
        recs = b''
        n = 0
        drawn6, sid6, sx6, sy6, face6 = [0] * 6, [0] * 6, [0.0] * 6, [0.0] * 6, [0] * 6
        for nd in BS.nodes(blk, base):
            o = nd['off']
            if nd['slot'] is not None:
                kind, slot, owner, cid = 0, nd['slot'], nd['slot'], cids[nd['slot']]
                drawn6[slot], sid6[slot] = 1, nd['sid']
                sx6[slot], sy6[slot], face6[slot] = nd['sx'], nd['sy'], blk[o + 0x154]
            else:
                os_ = fighters.get(nd['owner'])
                if os_ is None:
                    continue
                kind, slot, owner, cid = 1, 0xFF, os_, cids[os_]
            if cid not in pal_idx:
                try:
                    pals.append(lut_pal(cid))
                except FileNotFoundError:
                    pals.append(b'\x00' * 32)
                pal_idx[cid] = len(pals) - 1
            ang = struct.unpack_from('<I', blk, o + 0x148)[0] & 0xFFFF
            hx, hy = struct.unpack_from('<hh', blk, o + 0x178)
            zx = int(max(0.0, min(15.999, struct.unpack_from('<f', blk, o + 0x130)[0])) * 4096)
            zy = int(max(0.0, min(15.999, struct.unpack_from('<f', blk, o + 0x134)[0])) * 4096)
            recs += struct.pack('<BBBbBBBBHHHBBBBHHHfffII',
                                kind, slot, nd['cat'], nd['sort'], nd['layer'], blk[o + 0x154], owner, 1,
                                nd['sid'], pal_idx[cid], struct.unpack_from('<H', blk, o + 0x172)[0],
                                blk[o + 0x5C], 0, 0, blk[o + 0x186], zx, zy, nd['gfx1'] & 0xFFFF,
                                nd['sx'], nd['sy'], nd['depth'], nd['gfx1'],
                                struct.unpack_from('<I', blk, o + 0x1A4)[0])
            recs += struct.pack('<Hhh', ang, hx, hy)
            n += 1
        clock = int(meta.get('clock', fr))
        nodes_blob += struct.pack('<IH', clock, n) + recs
        # ── v5 world-space nodes: matrix/colour/flags from the block; vertices + page from the pack ──
        pk = os.path.join(a.packs, 'frame_%d.pack' % fr)
        if os.path.exists(pk):
            import emitter_gate as EG
            man, B = EG.load_pack(pk)
            cbs = man['constantBuffers']
            draws_by_cb = {}
            for d in man['draws']:
                if d.get('vsVariant') != 'vs_world' or not d['tex'][0]:
                    continue
                hs = d.get('vscbHash') or []
                if hs and cbs.get(hs[0]) and cbs[hs[0]]['len'] == 48:
                    draws_by_cb.setdefault(bytes(B(cbs[hs[0]])), []).append(d)
            vb, ib = B(man['vb']), B(man['ib'])
            IDX = struct.unpack('<%dI' % (len(ib) // 4), ib)
            arecs = b''
            an = 0
            for nd in BS.anodes(blk, base):
                ds = draws_by_cb.get(BS.cbworld(nd['matrix']))
                if not ds:
                    continue
                # one synthetic object per (node, page): records = the draw's own triangles as 32-B verts
                obj = bytearray(b'\x01\x00\x00\x00\x03\x00\x00\x00' + b'\x00' * 16)
                for d in ds:
                    t = man['textures'][d['tex'][0]]
                    page = bytes(B(t))
                    sha = hashlib.sha256(page).hexdigest()[:16]
                    tcw = tcw_index.get(sha)
                    key = tcw if tcw else 'sha_' + sha
                    pages[key] = dict(w=t['w'], h=t['h'], fmt=t['fmt'], data=page)
                    st, vo = d['stride'], d['voff']
                    verts = b''
                    nv = 0
                    for i in IDX[d['firstIndex']:d['firstIndex'] + d['indexCount']]:
                        raw = vb[vo + i * st:vo + (i + 1) * st]
                        f = struct.unpack('<%df' % (st // 4), raw)
                        verts += struct.pack('<8f', f[0], f[1], f[2], f[3], f[4], f[5], f[8], f[9])
                        nv += 1
                    payload = struct.pack('<II', nv, 5) + verts
                    tcw_word = int(tcw, 16) if tcw and all(c in '0123456789ABCDEFabcdef' for c in tcw) else 0
                    hdr = struct.pack('<4I', 0x8200002C, 0x83000000, 0x9481A424, tcw_word) + b'\x00' * (0x4C - 16) + struct.pack('<i', len(payload))
                    # stash the page key in the record's spare words so the emitter can find a sha-keyed page
                    hdr = hdr[:0x10] + key.encode()[:32].ljust(32, b'\x00') + hdr[0x30:]
                    obj += hdr + payload
                ob = bytes(obj)
                h = hashlib.sha256(ob).hexdigest()
                if h not in aobj_idx:
                    aobjs.append(ob)
                    aobj_idx[h] = len(aobjs) - 1
                arecs += struct.pack('<BBBBI', nd['list'], 0, 0, 0, nd['flags']) + struct.pack('<16f', *nd['matrix']) + \
                    struct.pack('<3f', *nd['colour']) + struct.pack('<HH', aobj_idx[h], 0) + struct.pack('<Q', nd['model'])
                an += 1
            anodes_blob += struct.pack('<IH', clock, an) + arecs
            aframes += 1
        cam = struct.unpack_from('<3f', blk, 0x6914)   # the RENDER camera (== the scene CB's, byte-exact)
        rows.append([clock, [144] * 6, drawn6, sid6, sx6, sy6, face6, 99, cam[0], cam[1], cam[2]])
        nframes += 1
    if not rows:
        sys.exit('no state frames in %d..%d' % (a.first, a.last))
    tape = {
        'ver': 'states_to_tape',
        # trailing plain column on purpose: the reader strips ']' characters from both ends
        'schema': '[frame,hp[6],drawn[6],sid[6],sx[6],sy[6],facing[6],timer,eyeX,eyeY,zoom]',
        'frames': rows, 'p1_team': teams[0], 'p2_team': teams[1], 'costume': [0] * 6,
        'nodes': base64.b64encode(gzip.compress(nodes_blob)).decode(), 'nodes_frames': nframes,
        'nodes_stride': 50, 'nodes_ver': 4,
        'pals': base64.b64encode(gzip.compress(b''.join(pals))).decode(), 'pals_n': len(pals),
        'source': 'capture states %d..%d (%s)' % (a.first, a.last, BS.CAP),
        # v5 world-space stream, synthesized: nodes from the block, objects from the capture's draws
        'tape_ver': 5,
        'anodes': base64.b64encode(gzip.compress(anodes_blob)).decode(), 'anodes_frames': aframes, 'anodes_stride': 96,
        'aobjs': base64.b64encode(gzip.compress(struct.pack('<H', len(aobjs)) + b''.join(struct.pack('<I', len(o)) + o for o in aobjs))).decode(),
        'aobjs_n': len(aobjs),
        # the pages the synthetic objects reference (keyed by TCW when known, else sha) -- an offline aid only
        'pages': {k: dict(w=v['w'], h=v['h'], fmt=v['fmt'], data=base64.b64encode(gzip.compress(v['data'])).decode()) for k, v in pages.items()},
    }
    json.dump(tape, open(a.out, 'w'))
    print('wrote %s: %d frames, teams P1 %s P2 %s, %d palettes' % (
        a.out, nframes, ['PL%02X' % c for c in teams[0]], ['PL%02X' % c for c in teams[1]], len(pals)))


if __name__ == '__main__':
    main()
