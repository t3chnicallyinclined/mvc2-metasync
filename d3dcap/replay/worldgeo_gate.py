#!/usr/bin/env python3
"""worldgeo_gate.py -- deterministic gate for the NaomiLib polygon-group decode (tape_to_seq.nl_triangles).

For every world-space draw in a gold capture (Path B .pack) whose CBWorld equals a node matrix from the
same frame's in-process object dump (alist_<f>.bin), decode that node's object with nl_triangles and
compare the TRIANGLE VERTEX POSITIONS with the captured draw (index buffer -> vertex buffer, stride 40):
same triangle count, and every emitted vertex position present in the captured VB (and vice versa).

    python worldgeo_gate.py capgate/frame_4445.pack [more packs]
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.argv, _a = sys.argv[:1], sys.argv[1:]
import numpy as np
import emitter_gate as EG
import blkstate as BS
import tape_to_seq as T


def main(packs):
    tot = ok_n = ok_pos = 0
    for pk in packs:
        man, B = EG.load_pack(pk)
        fr = int(os.path.basename(pk)[6:-5])
        al = BS.load_alist(fr)
        if not al:
            print('%s: no alist' % pk); continue
        meta, blk = BS.load_frame(fr)
        base = int(meta['base']) if meta.get('base') else BS.find_base(blk)[0]
        by_cb = {}
        for nd in BS.anodes(blk, base):
            ob = al.get(nd['off'])
            if ob and ob.get('raw') is not None:
                by_cb[BS.cbworld(nd['matrix'])] = (nd, ob)
        cbs = man['constantBuffers']
        for d in man['draws']:
            if d.get('vsVariant') != 'vs_world':
                continue
            node = None
            for hsh in (d.get('vscbHash') or []):
                rec = cbs.get(hsh)
                if rec and rec['len'] == 48:
                    node = by_cb.get(bytes(B(rec)))
            if not node:
                continue
            nd, ob = node
            tot += 1
            # emitter side: decode every record of the object, concatenate triangles
            body = ob['raw']
            tris = []
            q = 0x18
            while q + 0x50 <= len(body):
                pcw = struct.unpack_from('<i', body, q)[0]
                if pcw >= 0:
                    break
                size = struct.unpack_from('<i', body, q + 0x4C)[0]
                hdr = body[q:q + 0x50]
                tris += T.nl_triangles(body[q + 0x50:q + 0x50 + max(0, size)],
                                       struct.unpack_from('<i', hdr, 0x24)[0] == -3)
                q += 0x50 + max(0, size)
            em = np.array([v[:3] for v in tris], np.float32).reshape(-1, 3) if tris else np.zeros((0, 3), np.float32)
            # gold side
            ib = np.frombuffer(B(man['buffers'][d['ib']]), np.uint32) if isinstance(d.get('ib'), int) else None
            vb = np.frombuffer(B(man['buffers'][d['vb']]), np.uint8) if isinstance(d.get('vb'), int) else None
            if ib is None or vb is None:
                # pack layouts differ; fall back to the helper used by the truth raster
                P, _ = EG.indexed_quads(man, B, d)[:2] if hasattr(EG, 'indexed_quads') else (None, None)
                gold = np.array(P, np.float32).reshape(-1, 3) if P is not None else None
            else:
                idx = ib[d['firstIndex']:d['firstIndex'] + d['indexCount']]
                V = vb.reshape(-1, d.get('stride', 40))[:, :12].copy().view(np.float32).reshape(-1, 3)
                gold = V[idx]
            if gold is None:
                continue
            same_n = len(em) == len(gold)
            ok_n += same_n
            if len(em) and len(gold):
                a = {tuple(np.round(p, 2)) for p in em}; b = {tuple(np.round(p, 2)) for p in gold}
                pos_ok = (a == b)
            else:
                pos_ok = same_n
            ok_pos += pos_ok
            if not (same_n and pos_ok):
                print('  f%d list %d draw %d: emitter %d verts vs gold %d verts%s' % (
                    fr, nd['list'], d['i'], len(em), len(gold), '' if same_n else '  <- COUNT', ))
    print('world draws matched to objects: %d; triangle count equal: %d; vertex sets equal: %d' % (tot, ok_n, ok_pos))
    return 0 if tot and ok_pos == tot else 1


if __name__ == '__main__':
    sys.exit(main(_a))
