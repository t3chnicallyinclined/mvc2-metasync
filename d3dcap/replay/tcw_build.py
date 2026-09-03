#!/usr/bin/env python3
"""tcw_build.py -- join a session's TCW log (tcw_logger.py) with its capture: every world-space
draw whose CBWorld equals a logged node matrix gets its page saved under the node's TCW.

    python tcw_build.py [--log %TEMP%\\rrcap\\tcw_log.json] [--frames 4329 4508] [--out tcw_pages]

The join key is the 4x4 at node+0xA8: byte-exact both in the live log (the logger copies the 64
bytes) and in the capture (its row-major 3x4 transpose is the draw's CBWorld). A TCW seen on a
static node (HUD, stage) matches in every frame; a transient effect matches on the frames where
the logger caught that exact matrix -- one hit per TCW is enough, the page is the same.
"""
import argparse, glob, hashlib, json, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image
import emitter_gate as EG

CAP = os.path.join(os.environ.get('TEMP', '.'), 'rrcap')


def cbworld_of_matrix_hex(mhex):
    m = struct.unpack('<16f', bytes.fromhex(mhex))
    return struct.pack('<12f', m[0], m[4], m[8], m[12], m[1], m[5], m[9], m[13], m[2], m[6], m[10], m[14])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--log', default=os.path.join(CAP, 'tcw_log.json'))
    ap.add_argument('--frames', nargs=2, type=int, help='frame range to scan (default: every packed frame in capgate/ and rrcap)')
    ap.add_argument('--packs', nargs='*', help='explicit .pack files')
    ap.add_argument('--out', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tcw_pages'))
    a = ap.parse_args()
    by_cb = {}
    if os.path.exists(a.log):
        log = json.load(open(a.log))
        for mhex, rec in log['matrices'].items():
            by_cb[cbworld_of_matrix_hex(mhex)] = rec
        print('log: %d matrices, %d objects' % (len(log['matrices']), len(log['objects'])))
    # the shim's own per-frame object dumps (alist_<f>.bin) are exact and need no poller: join them
    # through the block's nodes -> matrix -> CBWorld
    import blkstate as BS
    alist_frames = 0
    packs = a.packs or sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'capgate', 'frame_*.pack')))
    if a.frames:
        packs = [p for p in packs if a.frames[0] <= int(os.path.basename(p)[6:-5]) <= a.frames[1]]
    os.makedirs(a.out, exist_ok=True)
    idx_path = os.path.join(a.out, 'index.json')
    lib = json.load(open(idx_path)) if os.path.exists(idx_path) else {}
    hits = 0
    for pk in packs:
        man, B = EG.load_pack(pk)
        cbs = man['constantBuffers']
        fr = int(os.path.basename(pk)[6:-5])
        al = BS.load_alist(fr)
        if al:
            try:
                meta, blk = BS.load_frame(fr)
                base = int(meta['base']) if meta.get('base') else BS.find_base(blk)[0]
                for nd in BS.anodes(blk, base):
                    ob = al.get(nd['off'])
                    if ob and ob['records']:
                        by_cb[BS.cbworld(nd['matrix'])] = dict(list=nd['list'], tcw='%08X' % ob['records'][0]['tcw'], obj='alist')
                alist_frames += 1
            except SystemExit:
                pass
        for d in man['draws']:
            if d.get('vsVariant') != 'vs_world' or not d['tex'][0]:
                continue
            for hsh in (d.get('vscbHash') or []):
                rec = cbs.get(hsh)
                if not rec or rec['len'] != 48:
                    continue
                node = by_cb.get(bytes(B(rec)))
                if not node:
                    continue
                t = man['textures'][d['tex'][0]]
                page = np.frombuffer(B(t), np.uint8)
                key = node['tcw']
                sha = hashlib.sha256(page.tobytes()).hexdigest()[:16]
                hits += 1
                if key in lib and lib[key]['sha'] == sha:
                    continue
                if key in lib and lib[key]['sha'] != sha:
                    print('  ⚠ TCW %s seen with a DIFFERENT page (%s vs %s) -- keeping both' % (key, lib[key]['sha'], sha))
                    key = key + '_' + sha[:6]
                img = Image.fromarray(page.reshape(t['h'], t['w'])) if t['fmt'] == 61 else \
                    Image.fromarray(page.reshape(t['h'], t['w'], 4), 'RGBA')
                fn = 'tcw_%s_%dx%d_f%d.png' % (key, t['w'], t['h'], t['fmt'])
                img.save(os.path.join(a.out, fn))
                lib[key] = dict(file=fn, list=node['list'], w=t['w'], h=t['h'], fmt=t['fmt'], sha=sha,
                                obj=node['obj'], frame=int(os.path.basename(pk)[6:-5]))
                print('  + TCW %s  %dx%d fmt %d  list %d  (frame %s)' % (key, t['w'], t['h'], t['fmt'], node['list'], lib[key]['frame']))
    json.dump(lib, open(idx_path, 'w'), indent=1)
    print('%d draw hits (%d frames with in-process object dumps); library now %d pages -> %s' % (hits, alist_frames, len(lib), idx_path))


if __name__ == '__main__':
    sys.exit(main())
