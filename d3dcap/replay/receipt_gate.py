#!/usr/bin/env python3
"""receipt_gate.py -- THE RECEIPT GATE: tick the real frame function on a same-match memory dump, feeding the TAPE's
seat words, and compare the fighters' world x/y and health per frame against the tape rows.

    python receipt_gate.py --run <d3dcap\\ttd\\runs\\<ts>> --tape <tape.json|.json.gz> [--frames 60]
    python receipt_gate.py --run <run> --selftest            # synthetic tape from the run's own 20-tick dumps (plumbing gate)
    python receipt_gate.py --run <run> --selftest --negative # a flipped seat word must DIVERGE (the gate can fail)

What it proves (docs/DETERMINISM-CONTRACT.md s6c): with ONE blk snapshot (+ game_state page, 0x142edf300 page, ctx slot
table, the six PL slot images) and the tape's two seat words per frame, FUN_140118950 regenerates px/py/hp of every fighter
exactly as the tape recorded them. A divergence names the frame and field.

Inputs and their provenance:
  * run/pre: dump_live.py images (exe_image, dcram, ctx, blk, blk2, game_state; meta.json). The run's blk clock is the
    anchor frame; the tape must contain that frame (`frame` column == blk+0x3CC8).
    With agent 0.3.47+ the anchor comes from the TAPE: build the run with d3dcap/receipt/anchor_to_run.py <tape> <dump> <out>
    (blk/game_state/exe page/ctx slots from the tape's battle_anchor; exe_image/dcram/ctx from a dump of the same boot), then
    d3dcap/receipt/pl_rebuild.py <out> --write (post-match dumps have PL slot 1 overwritten by the results screen; the recipe
    rebuilds every slot from the user's arc, 55/55 files). FIRST REAL PASS 2026-09-03: stage 9 offline tape, 60/60.
  * INPUT SEMANTICS (measured): tape row N's seat_in are the inputs that PRODUCED frame N (sampled at the clock edge after
    the tick) -> tick k consumes row start+k+1 (--input-shift 1, the default).
  * tape: agent GS tape (0.3.24+): tape['schema'] positional columns, tape['frames'] rows; needs seat_in[2], px[6], py[6],
    hp[6], frame. p1_team / p2_team = roster (cids).
  * PL images (DETERMINISM-CONTRACT s6c, CONFIRMED 2026-09-03): position pos of the six 0x150000-B PL regions at DC
    0x0C420000 + pos*0x150000 (pos order = fighter slots 0,2,4,1,3,5) holds AFS entry 209 + cid byte-for-byte for the
    entry's length (six of six slots on runs/20260903-000941), followed by a LOADER-BUILT tail (+0x130000.. cell/runtime
    tables; the frame reads ~40 B of it per drawn fighter). The tail is a function of the character for everything the
    frame reads EXCEPT 8 bytes at +0x137B94 (0xCDCDCDCD = host-uninitialised in 3 of 6 slots) -- see the contract. So a
    receipt needs the dump's roster == the tape's roster (checked here); a per-character image cache is possible for the
    AFS part today and for the tail once the loader (UNKNOWN) is derived or the tail is dumped once per character.

Engine functions, addresses and the job format are those of emu_frame.py / EmuGate.java (RE METHOD step 4).
"""
import argparse, gzip, json, os, struct, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import emu_gate as G          # noqa: E402
import emu_frame as F         # noqa: E402

FIGHTER0, STRIDE = 0x3DB8, 0x738
OFF_POSX, OFF_POSY, OFF_HP, OFF_CID = 0x50, 0x54, 0x578, 0x6C0     # agent reader.rs H_POS_X/H_POS_Y; hp = true-base 0x578 (u32 & 0xffff)
PL_POS = [0, 2, 4, 1, 3, 5]                                       # PL image position -> fighter slot
PL_BASE, PL_STRIDE = 0x0C420000, 0x150000
AFS_FIRST_CHAR = 209


def load_tape(path):
    raw = open(path, 'rb').read()
    t = json.loads(gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw)
    C = schema_cols(t['schema'])
    for need in ('frame', 'seat_in', 'px', 'py', 'hp'):
        if need not in C:
            sys.exit('tape lacks the %s column (schema %s) -- needs agent 0.3.24+' % (need, t['schema']))
    return t, C


def schema_cols(schema):
    """one index per column NAME (array columns are ONE nested JSON list per row: reader.rs serialises r.hp, r.px ... as
    arrays; same convention as tape_to_seq.py); the bare name of an array column maps to the same index."""
    s = schema.strip()
    s = s[1:] if s.startswith('[') else s
    s = s[:-1] if s.endswith(']') else s
    cols = [c.strip() for c in s.split(',')]
    C = {n: i for i, n in enumerate(cols)}
    for n, i in list(C.items()):
        if n.endswith(']') and '[' in n:
            C.setdefault(n[:n.index('[')], i)
    return C


def fighters(blk):
    out = []
    for s in range(6):
        o = FIGHTER0 + s * STRIDE
        out.append(dict(px=struct.unpack_from('<f', blk, o + OFF_POSX)[0], py=struct.unpack_from('<f', blk, o + OFF_POSY)[0],
                        hp=struct.unpack_from('<I', blk, o + OFF_HP)[0] & 0xffff,
                        cid=struct.unpack_from('<H', blk, o + OFF_CID)[0] & 0xff))
    return out


def check_pl_images(R, roster_cids):
    """Every PL slot image must equal AFS entry 209+cid for the entry's length (the static part of the loaded character)."""
    try:
        import rip_texbank as T
        m, ents = T.load_afs(T.DEFAULT_ARC)
    except SystemExit as e:
        return [('arc', False, str(e))]
    dcram = open(os.path.join(R['pre'], 'dcram.bin'), 'rb').read()
    res = []
    for pos, slot in enumerate(PL_POS):
        cid = roster_cids[slot]
        data, off, sz = T.afs_entry(m, ents, AFS_FIRST_CHAR + cid)
        lo = PL_BASE - R['dc_base'] + pos * PL_STRIDE
        res.append(('slot %d cid %d AFS %d (0x%X B)' % (slot, cid, AFS_FIRST_CHAR + cid, sz), dcram[lo:lo + sz] == data, ''))
    return res


def build_job(R, n, seat_words, tag, work):
    """n ticks of FUN_140118950; before tick k the four input words are the tape's seat words of that frame; blk dumped
    after every tick. Same memory model as emu_frame.frame_job (images at their live addresses, CRT stubs, no trace)."""
    ftab, *_ = F.functable(work)
    lines, trace, outs = F.frame_job(R, 'tick', tag, work, 60000000, [0, 0, 0, 0], ftab)
    lines = [l for l in lines if not l.startswith('trace ')]
    i = [k for k, l in enumerate(lines) if l.startswith('reg RCX')][0]
    head, tail = lines[:i], [l for l in lines[i:] if not l.startswith(('run ', 'reg ', 'set4 %x' % F.INPUT_SCRATCH))]
    # SEAT MAP (contract C2): FUN_140118950 zeroes the four pads, then writes pad[seat(k)] = inputs[k] & 0xFFFFFF for every
    # seat(k) >= 0 (game_state+0x258+4k). An OFFLINE image carries {0,0,0,0}: inputs[3] would win for seat 0 and seat 1 is
    # never fed. A receipt routes player k -> seat k: {0, 1, -1, -1}.
    head += ['set4 %x 0' % (F.GS_ADDR + 0x258), 'set4 %x 1' % (F.GS_ADDR + 0x25c), 'set4 %x ffffffff' % (F.GS_ADDR + 0x260),
             'set4 %x ffffffff' % (F.GS_ADDR + 0x264), 'note seat map game_state+0x258.. = {0,1,-1,-1} (receipt_gate)']
    body, dumps = [], []
    for k in range(n):
        w = seat_words[k]
        body += ['set4 %x %x' % (F.INPUT_SCRATCH + 4 * j, w[j] if j < len(w) else 0) for j in range(4)]
        body += ['reg RCX %x' % F.GGPO_STATE, 'reg RDX %x' % F.INPUT_SCRATCH, 'reg R8 0', 'run %x' % F.FRAME_TICK]
        p = os.path.join(work, '%s.blk_t%03d.bin' % (tag, k + 1))
        dumps.append(p)
        body.append('dump %x %x %s' % (R['blk'], R['blk_size'], p))
    return head + body + tail, dumps


def f32eq(a, b):
    return struct.pack('<f', np.float32(a)) == struct.pack('<f', np.float32(b))


def compare(rows, C, dumps, start_clock):
    """per frame: tape row (frame == clock after tick k) vs the emulated blk."""
    by_frame = {int(r[C['frame']]): r for r in rows}
    rep = dict(frames=0, exact=dict(px=0, py=0, hp=0, clock=0), first_div={}, per_frame=[])
    for k, p in enumerate(dumps):
        blk = open(p, 'rb').read()
        clock = struct.unpack_from('<I', blk, 0x3CC8)[0]
        row = by_frame.get(clock)
        rep['frames'] += 1
        if clock == start_clock + k + 1:
            rep['exact']['clock'] += 1
        elif 'clock' not in rep['first_div']:
            rep['first_div']['clock'] = (k + 1, clock, start_clock + k + 1)
        if row is None:
            rep['per_frame'].append(dict(tick=k + 1, clock=clock, tape_row=None))
            continue
        f = fighters(blk)
        ok, bad = dict(px=True, py=True, hp=True), dict(px=[], py=[], hp=[])
        for s in range(6):
            tv = dict(px=float(row[C['px']][s]), py=float(row[C['py']][s]), hp=int(row[C['hp']][s]))
            for fld in ('px', 'py'):
                if not f32eq(f[s][fld], tv[fld]):
                    ok[fld] = False; bad[fld].append((s, f[s][fld], tv[fld]))
            if f[s]['hp'] != tv['hp']:
                ok['hp'] = False; bad['hp'].append((s, f[s]['hp'], tv['hp']))
        for fld in ('px', 'py', 'hp'):
            if ok[fld]:
                rep['exact'][fld] += 1
            elif fld not in rep['first_div']:
                rep['first_div'][fld] = (k + 1, clock, bad[fld][:3])
        rep['per_frame'].append(dict(tick=k + 1, clock=clock, ok=ok))
    return rep


def synthetic_tape(R, n, negative, flip_bit=0x8):
    """--selftest: a tape built from the run's own consecutive-tick dumps (determinism_gate.py multitick --ticks n).
    Gates the plumbing (schema, slot order, offsets, job), not the engine; --negative flips one bit of seat 0 so the
    gate MUST report a divergence (a gate that only ever passes is unverified)."""
    inputs, seats, entry = F.tick_inputs(R)
    src = [os.path.join(G.WORK, 'multitick_%d.blk_t%02d.bin' % (n, k)) for k in range(1, n)] + [os.path.join(G.WORK, 'multitick_%d.blk_out.bin' % n)]
    if not all(os.path.exists(p) for p in src):
        sys.exit('selftest needs the %d-tick dumps: python determinism_gate.py multitick --run <run> --ticks %d' % (n, n))
    pre = R['blk_bytes']
    roster = [x['cid'] for x in fighters(pre)]
    seat = [inputs[0] ^ flip_bit, inputs[1]] if negative else [inputs[0], inputs[1]]
    rows = []
    pf = fighters(pre)
    rows.append([struct.unpack_from('<I', pre, 0x3CC8)[0], [x['hp'] for x in pf], [x['px'] for x in pf], [x['py'] for x in pf], seat])
    for p in src:
        blk = open(p, 'rb').read()
        f = fighters(blk)
        rows.append([struct.unpack_from('<I', blk, 0x3CC8)[0], [x['hp'] for x in f], [x['px'] for x in f], [x['py'] for x in f], seat])
    return dict(schema='[frame,hp[6],px[6],py[6],seat_in[2]]', frames=rows,
                p1_team=[roster[0], roster[2], roster[4]], p2_team=[roster[1], roster[3], roster[5]], synthetic=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', required=True)
    ap.add_argument('--tape')
    ap.add_argument('--frames', type=int, default=60)
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--negative', action='store_true')
    ap.add_argument('--flip-bit', type=lambda x: int(x, 0), default=0x8, help='raw pad bit XORed into seat 0 for --negative (raw->sim table DAT_140a4f780: 0x8->0x8000, 0x1->0x4000, 0x10->0x2000, 0x40->0x1000, 0x80->0x800, 0x20->0x400)')
    ap.add_argument('--json', default=None)
    ap.add_argument('--input-shift', type=int, default=1, help='feed tick k the seat words of tape row start+k+SHIFT. DEFAULT 1 (MEASURED 2026-09-03, stage 9 offline tape: shift 0 -> px 38/60, py 43/60, first divergence tick 2; shift 1 -> 60/60 on clock/px/py/hp): the agent samples seat_in at the clock edge AFTER the tick, so row N carries the inputs that PRODUCED frame N.')
    a = ap.parse_args()
    R = F.load_run(a.run)
    pre = R['blk_bytes']
    start = struct.unpack_from('<I', pre, 0x3CC8)[0]
    if a.selftest:
        t = synthetic_tape(R, 20, a.negative, a.flip_bit)
        n = min(a.frames, 20)
    else:
        if not a.tape:
            sys.exit('--tape required (or --selftest)')
        t, _ = load_tape(a.tape)
        n = a.frames
    C = schema_cols(t['schema'])
    rows = t['frames']
    by_frame = {int(r[C['frame']]): r for r in rows}
    if start not in by_frame:
        sys.exit('tape has no row for the run clock %d (tape frames %d..%d): not the same match, or the dump lies outside the tape'
                 % (start, min(by_frame), max(by_frame)))
    dump_roster = [x['cid'] for x in fighters(pre)]
    tape_roster = None
    if 'p1_team' in t:
        p1, p2 = t['p1_team'], t['p2_team']
        tape_roster = [p1[0] & 0xff, p2[0] & 0xff, p1[1] & 0xff, p2[1] & 0xff, p1[2] & 0xff, p2[2] & 0xff]
    print('run %s clock %d  dump roster %s  tape roster %s' % (a.run, start, dump_roster, tape_roster))
    if tape_roster and tape_roster != dump_roster:
        sys.exit('ROSTER MISMATCH: the six PL images in the dump belong to %s, the tape to %s -- a receipt needs a same-match '
                 'dump (the loader that builds the PL slot tails is UNKNOWN; DETERMINISM-CONTRACT.md s6c)' % (dump_roster, tape_roster))
    pl = check_pl_images(R, dump_roster)
    for name, ok, note in pl:
        print('  PL image %-36s %s %s' % (name, 'byte-equal to the arc entry' if ok else 'DIFFERS', note))
    if not all(ok for _, ok, _ in pl):
        sys.exit('PL images do not match the arc: refusing to tick on a torn character image')
    seat_words = []
    for k in range(n):                    # frame N's seat words produce frame N+1
        r = by_frame.get(start + k + a.input_shift)
        if r is None:
            n = k
            break
        seat_words.append([int(r[C['seat_in']][0]) & 0xffffff, int(r[C['seat_in']][1]) & 0xffffff, 0, 0])
    tag = 'receipt_%s_%d_%d%s' % (os.path.basename(a.run.rstrip('\\/')), start, n, ('_neg%x' % a.flip_bit) if a.negative else '')
    lines, dumps = build_job(R, n, seat_words, tag, G.WORK)
    r = G.run_job(lines, tag)
    print('emulation: %s  (%d ticks; log %s)' % (r['status'], n, r['log']))
    if not all(os.path.exists(p) for p in dumps):
        sys.exit('ticks did not complete: %s' % r['runs'][-1:])
    rep = compare(rows, C, dumps, start)
    print('RECEIPT GATE: %d ticks from clock %d: clock %d/%d  px %d/%d  py %d/%d  hp %d/%d' % (
        rep['frames'], start, rep['exact']['clock'], rep['frames'], rep['exact']['px'], rep['frames'],
        rep['exact']['py'], rep['frames'], rep['exact']['hp'], rep['frames']))
    for fld, v in rep['first_div'].items():
        print('  first divergence %s: tick %d (clock %d): %s' % (fld, v[0], v[1], v[2]))
    passed = all(rep['exact'][f] == rep['frames'] for f in ('px', 'py', 'hp', 'clock'))
    if a.negative:
        ref = [os.path.join(G.WORK, 'multitick_20.blk_t%02d.bin' % k) for k in range(1, 20)] + [os.path.join(G.WORK, 'multitick_20.blk_out.bin')]
        reached = None
        if all(os.path.exists(p) for p in ref):
            reached = 0
            for p, q in zip(ref, dumps):
                x, y = np.frombuffer(open(p, 'rb').read(), np.uint8), np.frombuffer(open(q, 'rb').read(), np.uint8)
                reached += int((x != y).sum())
        print('NEGATIVE selftest: %s; blk bytes differing from the reference dumps over %d ticks: %s' % (
            'the gate DETECTED the flipped input (px/py/hp diverged)' if not passed else
            'px/py/hp unchanged within %d frames (a standing button press does not move a fighter)' % n, n, reached))
    else:
        print('RESULT: %s' % ('PASS' if passed else 'FAIL'))
    if a.json:
        json.dump(dict(run=a.run, start=start, ticks=n, report=rep, pl=pl, emu=r['runs'], negative=a.negative),
                  open(a.json, 'w'), indent=1, default=str)
    return 0 if passed or a.negative else 1


if __name__ == '__main__':
    sys.exit(main())
