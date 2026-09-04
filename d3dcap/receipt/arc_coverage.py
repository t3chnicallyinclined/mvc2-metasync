#!/usr/bin/env python3
"""arc_coverage.py -- does every pointer an anchor's blk hands to the renderer land in a region the ARC BUILD fills?

Why: ticking an arc-rebuilt anchor can fault at 0x140848FF4 inside FUN_140848EE0 (the NaomiLib model record walk)
with RAX = 0xCDCDCDCD. That instruction is the walk's bottom terminator test:

    140848fe2: MOVSXD RAX, dword ptr [RDI + 0x4c]     ; record SIZE
    140848fe6: ADD    RDI, 0x50
    140848ff1: ADD    RDI, RAX
    140848ff4: CMP    dword ptr [RDI], 0x0            ; <-- faults

so a size field read as 0xCDCDCDCD sign-extends to -842150451 and RDI jumps ~800 MB backwards into nothing. The
0xCD is the host allocation's fill, i.e. the walk entered DC-RAM that the arc build never populated.

NOTE (measured, 2026-09-04): the four banks are NOT the cause. dcram_build.py reproduces the effects/HUD/common/
stage POL byte-exactly INCLUDING the 0xCD past each file end -- the live game leaves 0xCD there too -- and each
bank's last model terminates on a zero PCW in the final 8 bytes of its file. So a fault of this shape means a node
is pointing at an object OUTSIDE the set of regions the loader fills, which is what this tool reports.

    python arc_coverage.py <run dir> [--lists 0..15] [--all-nodes]

Prints, per System-A node with an object/model pointer: the DC address, whether it lands inside a region
dcram_build places, and which one. Any OUTSIDE line is a located arc-coverage gap.
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'replay'))
import dcram_build as D
import blkstate as B


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run')
    ap.add_argument('--arc', default=D.RT.DEFAULT_ARC)
    ap.add_argument('--lists', type=int, nargs='*', default=list(range(16)))
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()
    pre = a.run if os.path.exists(os.path.join(a.run, 'meta.json')) else os.path.join(a.run, 'pre')
    meta = json.load(open(os.path.join(pre, 'meta.json')))
    blk = open(os.path.join(pre, 'blk.bin'), 'rb').read()
    DCH = int(meta['dcram'], 16)
    BLKB = int(meta['blk'], 16)
    # two passes: build without the demand-driven aux banks, see what the anchor references, then rebuild with
    # them so the verdict reflects what dcram_build.py actually produces for this anchor.
    img, R, placed = D.build(a.arc, blk, verbose=False)
    need = False
    for nd in B.anodes(blk, BLKB, lists=range(16), drawn_only=False, limit=400):
        h = nd.get('obj') or 0
        if h and DCH <= h < DCH + int(meta['dcram_size'], 16):
            dc = h - DCH + 0x0C000000
            if D.RESULTS_POL_DC <= dc < D.RESULTS_TEX_DC + 0x200000:
                need = True
                break
    if need:
        img, R, placed = D.build(a.arc, blk, verbose=False, need_results=True)
    ivals = sorted((lo, lo + n, t) for lo, n, t in placed)

    def where(dc):
        for lo, hi, t in ivals:
            if lo <= dc < hi:
                return t
        return None

    # Route every pointer to the region it actually lives in BEFORE judging it. node+0xE8 is NOT a DC-RAM
    # object pointer: RECEIPT-RUNNER-DCRAM s4.2 shows the River Raft children carry +0xE8 = parent+0xA8, i.e.
    # it points at another NODE's matrix inside blk. Only +0xA0 (the TA polygon-list object) is a DC-RAM
    # pointer, and only those can be an arc-coverage gap.
    DC_LO, DC_HI = DCH, DCH + int(meta['dcram_size'], 16)
    BK_LO, BK_HI = BLKB, BLKB + int(meta['blk_size'], 16)
    B2_LO = int(meta.get('blk2', '0x0'), 16)
    B2_HI = B2_LO + int(meta.get('blk2_size', '0x0'), 16)
    EX_LO = int(meta['exe_base'], 16)
    EX_HI = EX_LO + int(meta['exe_size'], 16)

    def region(h):
        if DC_LO <= h < DC_HI: return 'dcram'
        if BK_LO <= h < BK_HI: return 'blk'
        if B2_LO <= h < B2_HI: return 'blk2'
        if EX_LO <= h < EX_HI: return 'exe'
        return 'other'

    nodes = B.anodes(blk, BLKB, lists=a.lists, drawn_only=False, limit=400)
    out, inside = [], 0
    tally = {}
    for nd in nodes:
        for key in ('obj', 'model'):
            h = nd.get(key) or 0
            if not h:
                continue
            rg = region(h)
            tally[(key, rg)] = tally.get((key, rg), 0) + 1
            if rg != 'dcram':
                continue
            dc = h - DCH + 0x0C000000
            t = where(dc)
            if t is None:
                out.append((nd['list'], nd['idx'], key, dc, bool(nd['drawn'])))
            else:
                inside += 1
    print('%-26s stage %-3d roster %s' % (os.path.basename(a.run.rstrip('/' + chr(92))), R['stage'], R['cids']))
    print('   nodes %d ; pointer census %s' % (len(nodes), sorted(tally.items())))
    print('   DC-RAM pointers inside a placed region %d ; OUTSIDE %d' % (inside, len(out)))
    for L, i, key, dc, drawn in out:
        print('   OUTSIDE  list %-2d node %-3d %-5s DC %08X  drawn=%s  <-- arc build leaves this 0x%02X'
              % (L, i, key, dc, drawn, D.FILL))
    return len(out)


if __name__ == '__main__':
    sys.exit(0 if main() == 0 else 1)
