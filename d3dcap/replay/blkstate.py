#!/usr/bin/env python3
"""blkstate.py -- read the GAME STATE out of a captured frame's blk snapshot.

    python blkstate.py 8931                 # one frame's draw list, as the engine built it
    python blkstate.py 8931 --json          # machine-readable
    python blkstate.py --range 8931 9230 --field 0x31    # histogram a node field over a burst

WHY THIS EXISTS
---------------
Until this capture, the two recordings we had were disjoint:
    the agent TAPE  = state (sid, sx/sy, facing, objs), NO pixels
    the D3D CAPTURE = every draw call and texture, NO state
and they were of DIFFERENT matches, so nothing could be joined. Three open questions all reduce to
that one gap -- which RGBA effect page belongs to which pool object, what `node+0x31` does to
intra-layer draw order, and which palette sub-row a body uses.

The shim now dumps the whole rollback block at openFrame(N) -- the moment the state that BUILT frame
N's draw list is current. This reads it back, so state and pixels finally describe the SAME frame.

THE LAYOUT IS THE ENGINE'S OWN DRAW LIST, not a heuristic walk. Confirmed in the disassembly
(mvc2-sh4-re-expert, bank03/bank04) and mirrored 1:1 by the shipped agent reader:
    blk+0x2F4D0 + L*0x300 + i*8   handle (u64) -- layer L, slot i
    blk+0x324D0 + L               u8 count for layer L, cleared every frame, cap 0x60
    16 layers, walked L = 0..15 ASCENDING then i = 0..count-1  (loc_8c0308c2)
    fighters are handles too, at blk+0x3DB8 + slot*0x738
Registration (bank04 loc_8c04515e) appends at the tail then insertion-sorts ASCENDING and STABLY on
(s8)node+0x31 -- so the array order read here IS the final draw order, +0x31 already applied.

⚠ RECOVERING blk_base. The handles are absolute process pointers and the snapshot has no header
saying where blk lived. It is recoverable and self-validating: guess base = handle - (0x3DB8 +
i*0x738) for each handle and each slot, then score by how many OTHER handles land inside
[base, base+0x33B18). The right base makes nearly all of them land; a wrong one makes almost none.
The tool refuses rather than guess if no candidate dominates.
"""
import argparse
import glob
import json
import os
import struct
import sys
from collections import Counter, defaultdict

CAP = os.path.join(os.environ.get('TEMP', '.'), 'rrcap')
BLK_SZ = 0x33B18

DRAWLIST_OFF, DRAWLIST_COUNTS, DRAWLIST_LAYER = 0x2F4D0, 0x324D0, 0x300
N_LAYERS, MAX_PER_LAYER = 16, 0x60
H0_OFF, SLOT_STRIDE = 0x3DB8, 0x738
H_CATEGORY, H_OBJ_OWNER, H_SCREEN_X, H_SCREEN_Y = 0x03, 0x28, 0x124, 0x128
H_DEPTH, H_DRAWN, H_SPRITE_ID, H_GFX1 = 0x12C, 0x170, 0x188, 0x1A0
# ⭐ THE INTRA-LAYER SORT KEY, LOCATED ON STEAM. The disassembly gives it as (s8)node+0x31 on the
# DC (bank04 loc_8c04515e: append at tail, then insertion-sort backwards, ASCENDING and STABLE).
# DC 0x31 does NOT map straight across -- the DC<->blk map is piecewise, and 0x31 lands at 0x4D here
# (delta +0x1C, a different segment from the +0x44 that covers 0xE0/0xE8/0x12C).
# Found WITHOUT guessing the delta, by the key's own defining property: the draw-list array is
# ALREADY sorted by it, so the true key must be non-decreasing across i within every layer. Scanning
# every byte 0x00..0x1FF over 126 frames and 2,943 adjacent in-layer pairs:
#     +0x4D   417 ordered-differing pairs, ZERO violations      <- the only strong candidate
#     +0xC9   156                          zero violations
#     +0x104 / +0x103 / +0x18C   57 each                        (barely constrained)
# and the signedness corroborates the disassembly independently:
#     +0x4D as (s8)  ->   0 violations, 417 ordered pairs, values {-8, 0, 1, 2, 8}
#     +0x4D as (u8)  -> 109 violations
# ⚠ THE TAPE DOES NOT RECORD THIS, and it is exactly why a cape draws through its body: -8 is the
# "behind" case, and without it a same-layer object falls back to registration order, where the
# fighter registers FIRST and the object lands on top.
H_SORT = 0x4D


def load_frame(frame, cap=CAP):
    side = os.path.join(cap, 'state_%d.json' % frame)
    if not os.path.exists(side):
        sys.exit('no state sidecar for frame %d (%s)' % (frame, side))
    meta = json.load(open(side))
    # the first shim build wrote whole blocks named by hash; the delta build writes
    # blk_<frame>_full.bin + blk_<frame>_delta.bin. Support both rather than force a re-capture.
    for cand in ('blk_%s.bin' % meta.get('blk'), 'blk_%d_full.bin' % frame):
        p = os.path.join(cap, cand)
        if meta.get('blk') and os.path.exists(p):
            return meta, open(p, 'rb').read()
    sys.exit('frame %d has a sidecar but no blk blob; delta chains are not reassembled yet' % frame)


def find_base(blk):
    """Recover the absolute address blk lived at, from the draw-list handles themselves."""
    handles = []
    for L in range(N_LAYERS):
        n = min(blk[DRAWLIST_COUNTS + L], MAX_PER_LAYER)
        for i in range(n):
            o = DRAWLIST_OFF + L * DRAWLIST_LAYER + i * 8
            h = struct.unpack_from('<Q', blk, o)[0]
            if h > 0x10000:
                handles.append(h)
    if not handles:
        return None, 0, handles
    votes = Counter()
    for h in handles:
        for slot in range(6):
            b = h - (H0_OFF + slot * SLOT_STRIDE)
            if b > 0:
                votes[b] += sum(1 for x in handles if b <= x < b + BLK_SZ)
    if not votes:
        return None, 0, handles
    base, score = votes.most_common(1)[0]
    return base, score, handles


def nodes(blk, base):
    """Every node in engine draw order: layer ascending, then array order within the layer."""
    out = []
    for L in range(N_LAYERS):
        n = min(blk[DRAWLIST_COUNTS + L], MAX_PER_LAYER)
        for i in range(n):
            o = DRAWLIST_OFF + L * DRAWLIST_LAYER + i * 8
            h = struct.unpack_from('<Q', blk, o)[0]
            if h <= 0x10000:
                continue
            off = h - base
            if not (0 <= off and off + 0x1C0 <= BLK_SZ):
                continue
            slot = None
            if (off - H0_OFF) >= 0 and (off - H0_OFF) % SLOT_STRIDE == 0 \
                    and (off - H0_OFF) // SLOT_STRIDE < 6:
                slot = (off - H0_OFF) // SLOT_STRIDE
            out.append(dict(
                layer=L, idx=i, off=off, slot=slot,
                cat=blk[off + H_CATEGORY],
                sort=struct.unpack_from('<b', blk, off + H_SORT)[0],
                drawn=blk[off + H_DRAWN],
                sid=struct.unpack_from('<H', blk, off + H_SPRITE_ID)[0],
                owner=struct.unpack_from('<Q', blk, off + H_OBJ_OWNER)[0],
                gfx1=struct.unpack_from('<I', blk, off + H_GFX1)[0],
                sx=struct.unpack_from('<f', blk, off + H_SCREEN_X)[0],
                sy=struct.unpack_from('<f', blk, off + H_SCREEN_Y)[0],
                depth=struct.unpack_from('<f', blk, off + H_DEPTH)[0]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frame', nargs='?', type=int)
    ap.add_argument('--cap', default=CAP)
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--range', nargs=2, type=int, metavar=('LO', 'HI'))
    ap.add_argument('--field', help='histogram one node field over --range, e.g. sort / cat / layer')
    a = ap.parse_args()

    if a.range:
        hist, seen, frames = Counter(), 0, 0
        for fr in range(a.range[0], a.range[1] + 1):
            if not os.path.exists(os.path.join(a.cap, 'state_%d.json' % fr)):
                continue
            _, blk = load_frame(fr, a.cap)
            base, score, _ = find_base(blk)
            if not base:
                continue
            frames += 1
            for nd in nodes(blk, base):
                seen += 1
                hist[nd.get(a.field or 'sort')] += 1
        print('%d frames, %d nodes' % (frames, seen))
        for k, v in sorted(hist.items(), key=lambda t: (-t[1])):
            print('   %-8s x%d' % (k, v))
        return 0

    if a.frame is None:
        ap.error('give a frame, or --range LO HI')
    meta, blk = load_frame(a.frame, a.cap)
    if len(blk) != BLK_SZ:
        sys.exit('blk blob is %d bytes, expected %d' % (len(blk), BLK_SZ))
    base, score, handles = find_base(blk)
    if not base or score < max(3, len(handles) // 2):
        sys.exit('could not recover blk_base (best %d of %d handles) -- refusing to guess'
                 % (score, len(handles)))
    nd = nodes(blk, base)
    if a.json:
        print(json.dumps({'frame': a.frame, 'clock': meta.get('clock'),
                          'base': base, 'nodes': nd}))
        return 0
    print('frame %d  clock %s  blk @ 0x%X  (%d of %d handles inside)'
          % (a.frame, meta.get('clock'), base, score, len(handles)))
    print('%d nodes in the engine draw list\n' % len(nd))
    print('%-3s %-3s %-6s %-5s %-5s %-6s %10s %8s %8s %10s'
          % ('L', 'i', 'kind', 'cat', 'sort', 'sid', 'gfx1', 'sx', 'sy', 'depth'))
    for n in nd:
        kind = 'P%d' % n['slot'] if n['slot'] is not None else 'obj'
        print('%-3d %-3d %-6s %-5d %-5d 0x%04X %10d %8.1f %8.1f %10.4f'
              % (n['layer'], n['idx'], kind, n['cat'], n['sort'], n['sid'],
                 n['gfx1'], n['sx'], n['sy'], n['depth']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
