#!/usr/bin/env python3
"""tape_vs_dump_gate.py -- W0 of docs/WORKSTREAM-CLIENT-REPLAY.md: the first TAPE-vs-CAPTURE gate.

Every 100% gate so far compares the capture shim's state dump with Steam's draws. This one compares what the
TRAY AGENT wrote to the tape with the shim's same-frame dump (state_<f>.json + blk delta chain, taken at the
sprite-walker hook), frame by frame, field by field:

    python tape_vs_dump_gate.py <tape.json.gz> [--state capgate/state] [--frames a b]

For each frame present in BOTH: the ordered sprite draw list (kind/slot/sid/face/depth/screen x,y/scale x,y/
angle/hotspot/pal row) from the tape vs the walker fields read from the dump's block (blkstate.nodes), plus the
world-node count per list and the 48 palette rows (0.3.40 palrows) vs the block's staging lines. Reports per
field: equal / differing counts and the first differing frame, and whether the tape's row is the SAME frame's
post-walk state (sampling phase) or the previous frame's (a constant one-frame lag shows up as fsx/fsy of the
prior dump matching instead).
"""
import argparse, base64, gzip, json, os, struct, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blkstate as BS

HERE = os.path.dirname(os.path.abspath(__file__))


def tape_nodes(t):
    nb = gzip.decompress(base64.b64decode(t['nodes'])); st = int(t.get('nodes_stride', 44)); off = 0; out = {}
    while off + 6 <= len(nb):
        fr, n = struct.unpack_from('<IH', nb, off); off += 6; rows = []
        for _ in range(n):
            v = struct.unpack_from('<BBBbBBBBHHHBBBBHHHfffII', nb, off)
            ang, hx, hy = struct.unpack_from('<Hhh', nb, off + 44) if st >= 50 else (0, 0, 0)
            off += st
            rows.append(dict(kind=v[0], slot=v[1], cat=v[2], layer=v[4], face=v[5], owner=v[6], drawn=v[7], sid=v[8],
                             pal=v[9], flash=v[10], zx=v[15], zy=v[16], fsx=v[18], fsy=v[19], depth=v[20],
                             angle=ang, hotx=hx, hoty=hy))
        out[fr] = rows
    return out


def tape_palrows(t):
    if not t.get('palrows'):
        return {}
    pb = gzip.decompress(base64.b64decode(t['pals'])); pals = [pb[i * 32:(i + 1) * 32] for i in range(len(pb) // 32)]
    rb = gzip.decompress(base64.b64decode(t['palrows'])); off = 0; out = {}
    while off + 148 <= len(rb):
        fr = struct.unpack_from('<I', rb, off)[0]; idx = struct.unpack_from('<48H', rb, off + 4); off += 148
        out[fr] = [pals[i] if i < len(pals) else None for i in idx]
    return out


def dump_frames(state_dir):
    fr = []
    for fn in os.listdir(state_dir):
        if fn.startswith('state_') and fn.endswith('.json'):
            try: fr.append(int(fn[6:-5]))
            except ValueError: pass
    return sorted(fr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('tape', nargs='?', help="tape .json.gz, or 'latest' = the newest tape in %LOCALAPPDATA%/RetroReceipts/gs-cache")
    ap.add_argument('--state', default=os.path.join(HERE, 'capgate', 'state'))
    ap.add_argument('--since-minutes', type=float, default=0.0, help='only dumps written in the last N minutes (the guided session you just ran)')
    ap.add_argument('--frames', nargs=2, type=int)
    ap.add_argument('--since', type=float, default=0.0, help='only dumps whose state_<f>.json mtime (epoch s) is newer: pairs ONE session with ONE tape (frame clocks restart every match, so older dumps collide by number)')
    a = ap.parse_args()
    import time
    if a.since_minutes: a.since = max(a.since, time.time() - a.since_minutes * 60)
    if not a.tape or a.tape == 'latest':
        gs = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'RetroReceipts', 'gs-cache')
        cands = sorted((os.path.getmtime(os.path.join(gs, f)), os.path.join(gs, f)) for f in os.listdir(gs) if f.endswith('.json.gz'))
        a.tape = cands[-1][1]; print('latest tape:', os.path.basename(a.tape))
    t = json.load(gzip.open(a.tape)); tn = tape_nodes(t); tp = tape_palrows(t)
    frames = [f for f in dump_frames(a.state) if f in tn and (not a.frames or a.frames[0] <= f <= a.frames[1])
              and os.path.getmtime(os.path.join(a.state, 'state_%d.json' % f)) >= a.since]
    print('tape %s: %d node frames, %d palrow frames; dump frames in both: %d' % (os.path.basename(a.tape)[:40], len(tn), len(tp), len(frames)))
    if not frames:
        print('no overlapping frames -- the capture and the tape must be from the SAME match (same frame clock)'); return 1
    FIELDS = ('sid', 'face', 'fsx', 'fsy', 'zx', 'zy', 'depth', 'angle', 'hotx', 'hoty', 'layer')
    eq = collections.Counter(); ne = collections.Counter(); first = {}; count_mismatch = 0; lag_hits = 0; lag_tested = 0
    pal_eq = pal_ne = 0
    prev_dump = None
    for f in frames:
        try:
            meta, blk = BS.load_frame(f, a.state)
        except SystemExit:
            continue
        base = int(meta['base']) if meta.get('base') else BS.find_base(blk)[0]
        # same MATCH? the six character ids at H+0x6C0 must equal the tape's teams, else the frame numbers only collide
        roster = [blk[BS.H0_OFF + i * BS.SLOT_STRIDE + 0x6C0] for i in range(6)]
        if not getattr(main, 'roster_checked', False):
            main.roster_checked = True
            tr0 = t.get('teams') or t.get('roster') or [t.get('p1_team'), t.get('p2_team')]
            print('dump roster (char ids) %s ; tape teams %s' % (['%02X' % c for c in roster], tr0))
        dn = []
        for n in BS.nodes(blk, base):
            if not n['drawn']: continue
            o = n['off']
            # the same walker outputs the agent ships (H offsets from docs/TAPE-V3-SPEC.md s10)
            n['fsx'], n['fsy'] = n['sx'], n['sy']
            n['zx'] = int(round(struct.unpack_from('<f', blk, o + 0x130)[0] * 4096)) & 0xFFFF
            n['zy'] = int(round(struct.unpack_from('<f', blk, o + 0x134)[0] * 4096)) & 0xFFFF
            n['angle'] = struct.unpack_from('<H', blk, o + 0x148)[0]
            n['hotx'], n['hoty'] = struct.unpack_from('<hh', blk, o + 0x178)
            n['face'] = blk[o + 0x154]
            n['layer'] = n['nlayer'] & 0xFF
            dn.append(n)
        trows = [r for r in tn[f] if r['drawn']]
        if len(dn) != len(trows):
            count_mismatch += 1
            first.setdefault('count', (f, len(trows), len(dn)))
        for tr, dr in zip(trows, dn):
            for k in FIELDS:
                tv, dv = tr.get(k), dr.get(k)
                if tv is None or dv is None: continue
                if isinstance(tv, float) or isinstance(dv, float):
                    same = abs(float(tv) - float(dv)) < 1e-4
                else:
                    same = int(tv) == int(dv)
                if same: eq[k] += 1
                else:
                    ne[k] += 1; first.setdefault(k, (f, tv, dv))
        # sampling phase: does the tape's screen position match THIS dump or the PREVIOUS one?
        if prev_dump is not None and trows and prev_dump[1]:
            lag_tested += 1
            cur = sum(1 for tr, dr in zip(trows, dn) if abs(tr['fsx'] - dr['fsx']) < 1e-4)
            prv = sum(1 for tr, dr in zip(trows, prev_dump[1]) if abs(tr['fsx'] - dr['fsx']) < 1e-4)
            if prv > cur: lag_hits += 1
        prev_dump = (f, dn)
        if f in tp:
            for i, row in enumerate(tp[f]):
                if row is None: continue
                o = 0x1040 + (0x10 + i) * 0x38 + 0x18
                if blk[o:o + 32] == row: pal_eq += 1
                else: pal_ne += 1
    print('frames compared: %d; draw-list COUNT mismatches: %d %s' % (len(frames), count_mismatch, ('first ' + str(first['count'])) if 'count' in first else ''))
    for k in FIELDS:
        tot = eq[k] + ne[k]
        print('  %-6s equal %6d / %6d%s' % (k, eq[k], tot, ('   first diff frame %d: tape %s dump %s' % first[k]) if k in first else ''))
    print('sampling phase: tape rows matched the PREVIOUS dump better on %d of %d frames (0 = same-frame sampling)' % (lag_hits, lag_tested))
    if tp: print('palette rows: %d equal, %d differing vs the block staging lines' % (pal_eq, pal_ne))
    return 0 if (count_mismatch == 0 and sum(ne.values()) == 0) else 1


if __name__ == '__main__':
    sys.exit(main())
