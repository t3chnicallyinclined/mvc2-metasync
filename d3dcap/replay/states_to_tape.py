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
    a = ap.parse_args()
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
        rows.append([clock, [144] * 6, drawn6, sid6, sx6, sy6, face6, 99])
        nframes += 1
    if not rows:
        sys.exit('no state frames in %d..%d' % (a.first, a.last))
    tape = {
        'ver': 'states_to_tape',
        # trailing plain column on purpose: the reader strips ']' characters from both ends
        'schema': '[frame,hp[6],drawn[6],sid[6],sx[6],sy[6],facing[6],timer]',
        'frames': rows, 'p1_team': teams[0], 'p2_team': teams[1], 'costume': [0] * 6,
        'nodes': base64.b64encode(gzip.compress(nodes_blob)).decode(), 'nodes_frames': nframes,
        'nodes_stride': 50, 'nodes_ver': 4,
        'pals': base64.b64encode(gzip.compress(b''.join(pals))).decode(), 'pals_n': len(pals),
        'source': 'capture states %d..%d (%s)' % (a.first, a.last, BS.CAP),
    }
    json.dump(tape, open(a.out, 'w'))
    print('wrote %s: %d frames, teams P1 %s P2 %s, %d palettes' % (
        a.out, nframes, ['PL%02X' % c for c in teams[0]], ['PL%02X' % c for c in teams[1]], len(pals)))


if __name__ == '__main__':
    main()
