"""pl_rebuild.py -- check / rebuild the six PL character slots of a receipt run's dcram.bin from the user's arc, per the
slot recipe (docs/RECEIPT-RUNNER-DCRAM.md s2.1, CONFIRMED 66/66): slot base 0x0C420000 + pos*0x150000 holds AFS 209+cid at
+0, then 268/327/386/445/504/563/681/622/740 + cid at +0x130000/0x13C000/0x13D000/0x13E000/0x140000/0x141000/0x142000/
0x143000/0x144000, and the 32 KB 3+cid tail at +0x148000. The 12 KB engine-written region at +0x145000 is NOT rebuilt
(writer INFERRED, FUN_140612180); pass --donor <dcram.bin> to copy a whole slot from an intact mid-match dump.

  python pl_rebuild.py <run_dir> [--donor <dcram.bin> --donor-pos N ...] [--write]
"""
import sys, os, json, struct, argparse
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'replay'))
import rip_texbank as T
ap = argparse.ArgumentParser(); ap.add_argument('run'); ap.add_argument('--donor'); ap.add_argument('--donor-pos', type=int, nargs='*', default=[]); ap.add_argument('--write', action='store_true')
a = ap.parse_args()
pre = os.path.join(a.run, 'pre'); meta = json.load(open(os.path.join(pre, 'meta.json')))
dc_base = int(meta['dc_base'], 16)
dcram = bytearray(open(os.path.join(pre, 'dcram.bin'), 'rb').read())
blk = open(os.path.join(pre, 'blk.bin'), 'rb').read()
# roster from blk: the gate's own reader (FIGHTER0 0x3DB8 + slot*0x738, OFF_CID) -- receipt_gate.fighters
import receipt_gate as RG
cids = [f['cid'] for f in RG.fighters(bytes(blk))]
print('roster (slot order) from blk:', cids)
PL_POS = [0, 2, 4, 1, 3, 5]
SUB = [(268, 0x130000), (327, 0x13C000), (386, 0x13D000), (445, 0x13E000), (504, 0x140000), (563, 0x141000), (681, 0x142000), (622, 0x143000), (740, 0x144000)]
m, ents = T.load_afs(T.DEFAULT_ARC)
donor = open(a.donor, 'rb').read() if a.donor else None
patched = 0; checked = 0; bad = 0
for pos, slot in enumerate(PL_POS):
    cid = cids[slot]; lo = 0x0C420000 - dc_base + pos * 0x150000
    if pos in a.donor_pos and donor is not None:
        seg = donor[lo:lo + 0x150000]
        same = bytes(dcram[lo:lo + 0x150000]) == seg
        print('pos %d slot %d cid %d: DONOR slot copied (%s)' % (pos, slot, cid, 'already identical' if same else '%d bytes changed' % sum(1 for i in range(0x150000) if dcram[lo + i] != seg[i])))
        if a.write: dcram[lo:lo + 0x150000] = seg
        continue
    for afs, off in [(209, 0)] + SUB + [(3, 0x148000)]:
        data, _, sz = T.afs_entry(m, ents, afs + cid)
        cur = bytes(dcram[lo + off:lo + off + sz]); ok = cur == data; checked += 1
        if not ok:
            bad += 1; nd = sum(1 for i in range(sz) if cur[i] != data[i])
            print('pos %d slot %d cid %d: AFS %d @+0x%X (0x%X B) DIFFERS in %d bytes%s' % (pos, slot, cid, afs + cid, off, sz, nd, ' -> patched' if a.write else ''))
            if a.write: dcram[lo + off:lo + off + sz] = data; patched += 1
print('files checked %d, differing %d, patched %d' % (checked, bad, patched))
if a.write:
    open(os.path.join(pre, 'dcram.bin'), 'wb').write(dcram); print('dcram.bin written')
