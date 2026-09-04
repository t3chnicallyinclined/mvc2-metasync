#!/usr/bin/env python3
"""sg_n2.py -- GATE N2-A: how far does VISIBLE state diverge when a real human input stream is
replaced by repeat-last prediction for k frames?  (SUPERGUN NETCODE lane.)

WHY THIS IS N2-A AND NOT N2.  Every input tape available has the REMOTE seat identically zero -- the
stage-9 receipt is one-sided.  Repeat-last predicts an all-zero stream perfectly by construction, so
a naive N2 would report zero divergence at every depth and PASS while measuring nothing.  That is a
confounded gate.  So this harness mispredicts the seat whose inputs are REAL (seat 0).

  MEASURES : visible-state divergence after k frames of repeat-last on a real input stream.
  DOES NOT : two simultaneously-mispredicted streams, or opponent-reaction dynamics.

Method: one truth run (real inputs, dump every tick).  Then for each start frame f, ONE run of f+K
ticks where ticks >= f use repeat-last (the seat word at f-1 held), dumping every tick; state at f+j
is exactly what a player would see after j frames of misprediction, so one run yields every depth.
"""
import argparse, json, os, shutil, struct, subprocess, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, '..', 'receipt', 'runner', 'rr_runner.exe')
FIGHTER0, STRIDE = 0x3DB8, 0x738
OFF_POSX, OFF_POSY, OFF_HP, OFF_CID = 0x50, 0x54, 0x578, 0x6C0
POOLN = 6

def fighters(blk):
    out = []
    for i in range(POOLN):
        o = FIGHTER0 + i * STRIDE
        out.append(dict(px=struct.unpack_from('<f', blk, o + OFF_POSX)[0],
                        py=struct.unpack_from('<f', blk, o + OFF_POSY)[0],
                        hp=struct.unpack_from('<I', blk, o + OFF_HP)[0] & 0xffff,
                        cid=blk[o + OFF_CID]))
    return out

def read_inputs(path):
    rows = []
    for line in open(path):
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        a, b = s.split()[:2]
        rows.append((int(a, 16), int(b, 16)))
    return rows

def write_inputs(path, rows):
    with open(path, 'w') as f:
        for a, b in rows:
            f.write('%x %x\n' % (a, b))

def run(pre, inputs_path, outdir, ticks, dump_every=1):
    os.makedirs(outdir, exist_ok=True)
    cmd = [RUNNER, '--pre', pre, '--out', outdir, '--ticks', str(ticks),
           '--inputs', inputs_path, '--dump-every', str(dump_every)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        sys.stderr.write((p.stdout or '')[-3000:] + (p.stderr or '')[-2000:])
        raise SystemExit('runner failed rc=%d for %s' % (p.returncode, outdir))
    return p.stdout

def load_blk(d, t):
    p = os.path.join(d, 'blk_t%03d.bin' % t)
    return open(p, 'rb').read() if os.path.exists(p) else None

def q(v, p):
    if not v:
        return 0.0
    s = sorted(v)
    return s[min(len(s) - 1, int(p * len(s)))]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pre', required=True)
    ap.add_argument('--inputs', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--depth', type=int, default=30)
    ap.add_argument('--stride', type=int, default=10)
    ap.add_argument('--first', type=int, default=20)
    ap.add_argument('--keep', action='store_true')
    ap.add_argument('--seat', type=int, default=0, choices=(0, 1),
                    help='which seat to mispredict (1 = the REMOTE seat, which is what rollback actually predicts)')
    a = ap.parse_args()

    truth_in = read_inputs(a.inputs)
    N = len(truth_in)
    nz = sum(1 for w0, _ in truth_in if w0)
    nz1 = sum(1 for _, w1 in truth_in if w1)
    print('inputs: %d frames | seat0 non-idle %d (%.0f%%) | seat1 non-idle %d (%.0f%%) | mispredicting seat %d'
          % (N, nz, 100.0 * nz / N, nz1, 100.0 * nz1 / N, a.seat))

    os.makedirs(a.out, exist_ok=True)
    truth_dir = os.path.join(a.out, 'truth')
    if not os.path.exists(os.path.join(truth_dir, 'blk_t%03d.bin' % N)):
        print('truth run: %d ticks ...' % N)
        run(a.pre, a.inputs, truth_dir, N)
    truth = {t: load_blk(truth_dir, t) for t in range(N + 1)}
    if not truth.get(N):
        raise SystemExit('truth run did not dump blk_t%03d.bin' % N)

    starts = list(range(a.first, N - a.depth, a.stride))
    print('mispredict starts: %d (f=%d..%d step %d), depth %d'
          % (len(starts), starts[0], starts[-1], a.stride, a.depth))

    dpx, dpy, dhp = defaultdict(list), defaultdict(list), defaultdict(list)
    anydiff, samples, pred_correct = defaultdict(int), defaultdict(int), defaultdict(int)

    for f in starts:
        S = a.seat
        held = truth_in[f - 1][S]
        def mk(j):
            w = list(truth_in[j]); w[S] = held; return tuple(w)
        rows = list(truth_in[:f]) + [mk(j) for j in range(f, f + a.depth)]
        ip = os.path.join(a.out, 'in_f%03d.txt' % f)
        write_inputs(ip, rows)
        d = os.path.join(a.out, 'p_f%03d' % f)
        run(a.pre, ip, d, f + a.depth)
        for j in range(1, a.depth + 1):
            t = f + j
            pb, tb = load_blk(d, t), truth.get(t)
            if pb is None or tb is None:
                continue
            samples[j] += 1
            if held == truth_in[t - 1][a.seat]:
                pred_correct[j] += 1
            pf, tf = fighters(pb), fighters(tb)
            wx = wy = 0.0
            wh = 0
            for k in range(POOLN):
                if tf[k]['cid'] > 0x40:
                    continue
                wx = max(wx, abs(pf[k]['px'] - tf[k]['px']))
                wy = max(wy, abs(pf[k]['py'] - tf[k]['py']))
                wh = max(wh, abs(pf[k]['hp'] - tf[k]['hp']))
            dpx[j].append(wx); dpy[j].append(wy); dhp[j].append(wh)
            if pb != tb:
                anydiff[j] += 1
        if not a.keep:
            shutil.rmtree(d, ignore_errors=True)

    print('')
    hdr = '%-6s %-7s %-8s %-14s %-26s %-26s %-7s'
    print(hdr % ('depth', 'n', 'blk!=', 'pred bit-ok', '|dpx| p50/p90/max', '|dpy| p50/p90/max', 'dhp'))
    rep = []
    for j in range(1, a.depth + 1):
        if not samples[j]:
            continue
        row = dict(depth=j, samples=samples[j], blk_diff=anydiff[j],
                   blk_diff_pct=100.0 * anydiff[j] / samples[j],
                   pred_bit_correct_pct=100.0 * pred_correct[j] / samples[j],
                   dpx=dict(p50=q(dpx[j], .5), p90=q(dpx[j], .9), max=max(dpx[j])),
                   dpy=dict(p50=q(dpy[j], .5), p90=q(dpy[j], .9), max=max(dpy[j])),
                   dhp_max=max(dhp[j]))
        rep.append(row)
        if j in (1, 2, 3, 4, 6, 8, 12, 16, 24) or j == a.depth:
            print(hdr % (j, samples[j], '%.0f%%' % row['blk_diff_pct'],
                         '%.0f%%' % row['pred_bit_correct_pct'],
                         '%.3f / %.3f / %.3f' % (row['dpx']['p50'], row['dpx']['p90'], row['dpx']['max']),
                         '%.3f / %.3f / %.3f' % (row['dpy']['p50'], row['dpy']['p90'], row['dpy']['max']),
                         str(row['dhp_max'])))
    js = os.path.join(a.out, 'n2a.json')
    json.dump(dict(inputs=a.inputs, frames=N, seat0_nonidle=nz, depth=a.depth,
                   starts=starts, rows=rep), open(js, 'w'), indent=1)
    print('')
    print('wrote ' + js)

if __name__ == '__main__':
    main()
