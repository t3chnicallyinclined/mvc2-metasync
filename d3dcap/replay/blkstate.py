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
# ⚠ THE LAYER IS node+0x38, NOT +0x24. Confirmed in STEAM's own code (FUN_14061e560 @ 0x14061E5AF:
# `MOVSX RCX, byte ptr [RBX + 0x38]`, signed) and then independently against this capture: +0x38
# equals the layer we walked the node from on 4,080 of 4,080 nodes, while +0x24 disagrees 3,154
# times. We only got away with reading +0x24 elsewhere because the layer is derived STRUCTURALLY
# here -- from which row of the array the handle came out of -- not from the node.
H_LAYER = 0x38
# ⚠⚠ VISIBILITY IS CHECKED TWICE. node+0x170 gates REGISTRATION (FUN_14061e560 @ 0x14061E590) and
# is re-checked at DRAW time in the walker (FUN_140620F10). A node can be registered and then hidden
# before the walk, so reproducing only the registration check draws PHANTOMS.
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


_chain_cache = {'cap': None, 'frames': None, 'last': None}   # last = (frame, bytes)


def _captured_state_frames(cap):
    if _chain_cache['cap'] != cap or _chain_cache['frames'] is None:
        fr = []
        for n in os.listdir(cap):
            if n.startswith('state_') and n.endswith('.json') and n[6:-5].isdigit():
                fr.append((os.path.getmtime(os.path.join(cap, n)), int(n[6:-5])))
        _chain_cache['cap'] = cap
        # ⚠ CAPTURE ORDER, NOT FRAME ORDER. A delta is relative to the previously WRITTEN frame.
        # With -Keep the directory holds several game sessions whose frame numbers restart, so
        # sorting by number interleaves sessions and applies one session's deltas onto another's
        # block (storm-down re-gated at 73-97% after two more sessions were kept alongside it).
        # The sidecar's mtime is the write order. (Copy state files with `cp -p` to keep it.)
        _chain_cache['frames'] = [f for _, f in sorted(fr)]
        _chain_cache['last'] = None
    return _chain_cache['frames']


def _apply_delta(buf, path):
    d = open(path, 'rb').read()
    o = 0
    while o + 8 <= len(d):
        off, ln = struct.unpack_from('<II', d, o)
        o += 8
        buf[off:off + ln] = d[o:o + ln]
        o += ln
    return buf


def load_frame(frame, cap=CAP):
    """The whole rollback block for `frame`.

    The shim writes blk_<f>_full.bin for the first frame it dumps and blk_<f>_delta.bin (runs of
    u32 off, u32 len, payload) for every later CAPTURED frame -- relative to the previously
    CAPTURED frame, whatever its number. ⚠ That chain runs across bursts: the second burst's first
    frame is a delta against the first burst's last frame (g_blkHavePrev was never reset), so the
    reassembly walks the sorted list of captured frames from the nearest full block forward,
    skipping nothing. The last reassembled block is cached so a sequential scan applies one delta
    per frame instead of replaying the chain.
    """
    side = os.path.join(cap, 'state_%d.json' % frame)
    if not os.path.exists(side):
        sys.exit('no state sidecar for frame %d (%s)' % (frame, side))
    meta = json.load(open(side))
    # the first shim build wrote whole blocks named by hash; support it rather than force a re-capture
    if meta.get('blk'):
        p = os.path.join(cap, 'blk_%s.bin' % meta['blk'])
        if os.path.exists(p):
            return meta, open(p, 'rb').read()
    full = os.path.join(cap, 'blk_%d_full.bin' % frame)
    if os.path.exists(full):
        b = open(full, 'rb').read()
        _chain_cache['last'] = (frame, b)
        return meta, b
    frames = _captured_state_frames(cap)
    if frame not in frames:
        sys.exit('frame %d is not among the captured state frames' % frame)
    i = frames.index(frame)
    last = _chain_cache['last']
    if last and i > 0 and frames[i - 1] == last[0]:
        buf = bytearray(last[1])                       # one step from the cached predecessor
        start = i
    else:
        j = i
        while j >= 0 and not os.path.exists(os.path.join(cap, 'blk_%d_full.bin' % frames[j])):
            j -= 1
        if j < 0:
            sys.exit('frame %d: no full block precedes it in the capture -- chain cannot be rebuilt' % frame)
        buf = bytearray(open(os.path.join(cap, 'blk_%d_full.bin' % frames[j]), 'rb').read())
        start = j + 1
    for k in range(start, i + 1):
        dp = os.path.join(cap, 'blk_%d_delta.bin' % frames[k])
        if not os.path.exists(dp):
            sys.exit('frame %d: delta for captured frame %d is missing -- chain broken' % (frame, frames[k]))
        _apply_delta(buf, dp)
    b = bytes(buf)
    _chain_cache['last'] = (frame, b)
    if len(b) != meta.get('size', BLK_SZ):
        sys.exit('frame %d: reassembled %d bytes, sidecar says %s' % (frame, len(b), meta.get('size')))
    return meta, b


def find_base(blk):
    """Recover the absolute address blk lived at, from the draw-list handles themselves.
    Prefers the sidecar's exact base when the caller passes one via find_base.hint."""
    blk_ref = blk
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
    # ⚠⚠ THE VOTE IS BLIND TO A WHOLE-SLOT SHIFT. Every handle is stride-aligned, so a base that is
    # off by k*0x738 collects exactly the same votes (a fighter in slot 2 "is" slot 0 from a base
    # 0xE70 too high) and most_common() then picks whichever was inserted first. That is how every
    # super-step capture of 2026-09-02 read the PARKED point characters (slots 0/1) as the
    # fighters, with +0x170 == 0 and constant sids, while the active pair sat in slots 2/3 -- the
    # block was right, the base was 0xE70 off. Break the tie by things a shifted base cannot fake,
    # i.e. by reading POINTER FIELDS at candidate-relative offsets: under the true base an object
    # node's owner (+0x28) is 0 or a fighter handle, and the System-A lists at blk+0x2EDE8+L*8
    # chain through `next` (+0x10) pointers that all stay inside the block; under a shifted base
    # both reads land mid-struct in other nodes and come back as garbage. (Do NOT use +0x170 here:
    # a post-walk snapshot has it cleared on the very nodes that were drawn.)
    def fighter_slot(off):
        if 0 <= off - H0_OFF < 6 * SLOT_STRIDE and (off - H0_OFF) % SLOT_STRIDE == 0:
            return (off - H0_OFF) // SLOT_STRIDE
        return None
    def coherence(b):
        sc = 0
        for h in handles:
            off = h - b
            if not (0 <= off and off + 0x1C0 <= BLK_SZ):
                sc -= 3
                continue
            sl = fighter_slot(off)
            if sl is not None:
                sc += 1 if blk_ref[off + 0x6C0] <= 0x40 else -2
            else:
                own = struct.unpack_from('<Q', blk_ref, off + H_OBJ_OWNER)[0]
                sc += 1 if (own == 0 or fighter_slot(own - b) is not None) else -2
        for L in range(16):
            head = struct.unpack_from('<Q', blk_ref, 0x2EDE8 + L * 8)[0]
            p, n, ok = head, 0, True
            while p and n < 128:
                off = p - b
                if not (0 <= off and off + 0x18 <= BLK_SZ):
                    ok = False
                    break
                p = struct.unpack_from('<Q', blk_ref, off + 0x10)[0]
                n += 1
            if head:
                sc += 2 if ok else -4
        return sc
    ranked = votes.most_common()
    top = ranked[0][1]
    cands = [(b, sc) for b, sc in ranked if sc >= top - 1]
    best = max(cands, key=lambda t: (coherence(t[0]), t[1]))
    # ⚠ A ROLLBACK COPY of the block (the first captures read the save-state buffer through
    # 0x140AC6EF0) carries the LIVE block's absolute pointers, so relative to the copy every
    # pointer anchor is garbage for EVERY candidate. In that case the anchors say nothing and the
    # old vote order stands (it was pixel-exact on those captures). New captures carry the exact
    # base in the sidecar and never reach this code path.
    if coherence(best[0]) <= 0:
        best = ranked[0]
    return best[0], best[1], handles


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
                nlayer=struct.unpack_from('<b', blk, off + H_LAYER)[0],
                depth=struct.unpack_from('<f', blk, off + H_DEPTH)[0]))
    return out


# ── SYSTEM A: the world-space class (Ghidra FUN_140620740 / FUN_140620cd0, 2026-09-02) ──────────
# Singly-linked lists at blk+0x2EDE8 + L*8 (next = node+0x10). A node is drawn when +0x170 != 0
# (the textured-quad path also needs an object at +0xA0). Its 4x4 at +0xA8 (column-major, 16 f32)
# IS Steam's per-draw CBWorld transposed (254/307 vs_world draws byte-exact on f4445). +0xA0 points
# at a DC-style TA polygon-list object (header 0x18, records: PCW/ISP/TSP/TCW + 32-B vertices) that
# lives OUTSIDE the block -- the capture has its vertices in the VB, the agent must read it by
# pointer. Lists seen: 6 stage backdrop, 7 hail chunks / fighter shadow+marker set, 8 3D models
# (+0xE8), 11 HUD, 12 stage root.
ALIST_HEADS = 0x2EDE8
A_NEXT, A_CALLBACK, A_POS, A_SCALE, A_COLOUR, A_OBJ, A_MATRIX, A_MODEL, A_FLAGS, A_DRAWN =     0x10, 0x40, 0x50, 0x6C, 0x94, 0xA0, 0xA8, 0xE8, 0xF0, 0x170


def anodes(blk, base, lists=range(16), drawn_only=True, limit=256):
    """Every System-A node in list order: list, off, drawn, flags, pos, scale, colour, matrix16,
    obj (absolute pointer, outside the block), model (absolute pointer or 0)."""
    out = []
    for L in lists:
        p = struct.unpack_from('<Q', blk, ALIST_HEADS + L * 8)[0]
        n = 0
        while p and n < limit:
            off = p - base
            if not (0 <= off and off + 0x180 <= BLK_SZ):
                break
            drawn = blk[off + A_DRAWN]
            if drawn or not drawn_only:
                out.append(dict(
                    list=L, idx=n, off=off, drawn=drawn,
                    flags=struct.unpack_from('<I', blk, off + A_FLAGS)[0],
                    pos=struct.unpack_from('<fff', blk, off + A_POS),
                    scale=struct.unpack_from('<fff', blk, off + A_SCALE),
                    colour=struct.unpack_from('<fff', blk, off + A_COLOUR),
                    matrix=struct.unpack_from('<16f', blk, off + A_MATRIX),
                    obj=struct.unpack_from('<Q', blk, off + A_OBJ)[0],
                    model=struct.unpack_from('<Q', blk, off + A_MODEL)[0],
                    callback=struct.unpack_from('<Q', blk, off + A_CALLBACK)[0]))
            n += 1
            p = struct.unpack_from('<Q', blk, off + A_NEXT)[0]
    return out


def load_alist(frame, cap=CAP):
    """The world-space OBJECTS the shim dumped in-process right after the walk (alist_<frame>.bin):
    {node_off: dict(list, obj_ptr, model_ptr, records=[dict(pcw, isp, tsp, tcw, colour, verts)])}.
    Records are the node's DC-TA polygon list: 0x50 header + 32-byte vertices x y z nx ny nz u v.
    Absent for captures made before 2026-09-03 (use tcw_logger.py's log for those)."""
    path = os.path.join(cap, 'alist_%d.bin' % frame)
    if not os.path.exists(path):
        return None
    b = open(path, 'rb').read()
    if len(b) < 4:
        return {}
    count = struct.unpack_from('<I', b, 0)[0]
    o, out = 4, {}
    for _ in range(count):
        if o + 28 > len(b):
            break
        L = b[o]
        off, objp, modelp, ln = struct.unpack_from('<IQQI', b, o + 4)
        body = b[o + 28:o + 28 + ln]
        o += 28 + ln
        recs = []
        q = 0x18
        while q + 0x50 <= len(body):
            pcw = struct.unpack_from('<i', body, q)[0]
            if pcw >= 0:
                break
            size = struct.unpack_from('<i', body, q + 0x4C)[0]
            hdr = body[q:q + 0x50]
            pay = body[q + 0x50:q + 0x50 + max(0, size)]
            recs.append(dict(pcw=struct.unpack_from('<I', hdr, 0)[0], isp=struct.unpack_from('<I', hdr, 4)[0],
                             tsp=struct.unpack_from('<I', hdr, 8)[0], tcw=struct.unpack_from('<I', hdr, 12)[0],
                             colour=struct.unpack_from('<4f', hdr, 0x2C),
                             verts=[struct.unpack_from('<8f', pay, v) for v in range(8, len(pay) - 31, 32)],
                             raw=body[q:q + 0x50 + max(0, size)]))
            q += 0x50 + max(0, size)
        out[off] = dict(list=L, obj=objp, model=modelp, records=recs, raw=body)
    return out


def cbworld(matrix16):
    """The 48-byte row-major 3x4 Steam binds as CBWorld, from the node's column-major 4x4."""
    m = matrix16
    return struct.pack('<12f', m[0], m[4], m[8], m[12], m[1], m[5], m[9], m[13], m[2], m[6], m[10], m[14])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frame', nargs='?', type=int)
    ap.add_argument('--cap', default=CAP)
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--range', nargs=2, type=int, metavar=('LO', 'HI'))
    ap.add_argument('--field', help='histogram one node field over --range, e.g. sort / cat / layer')
    ap.add_argument('--alist', action='store_true', help='print the System-A (world-space) lists instead')
    a = ap.parse_args()
    if a.alist and a.frame is not None:
        meta, blk = load_frame(a.frame, a.cap)
        base, score, handles = find_base(blk)
        if meta.get('base'):
            base = int(meta['base'])
        for nd in anodes(blk, base):
            print('list %2d i%-3d off 0x%05X flags %08X obj %s model %s pos (%.1f,%.1f,%.1f) scale (%.2f,%.2f,%.2f) col (%.2f,%.2f,%.2f) T (%.2f,%.2f,%.2f)' % (
                nd['list'], nd['idx'], nd['off'], nd['flags'], 'Y' if nd['obj'] else '-', 'Y' if nd['model'] else '-',
                *nd['pos'], *nd['scale'], *nd['colour'], nd['matrix'][12], nd['matrix'][13], nd['matrix'][14]))
        return 0

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
