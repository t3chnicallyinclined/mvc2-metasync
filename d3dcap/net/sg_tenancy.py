#!/usr/bin/env python3
"""sg_tenancy.py -- SUPERGUN SERVER ARCH lane (Q5): how many concurrent MvC2 matches fit on one host?

Tris's proposal is a central headless server ticking many matches. The single-tick cost (0.034-0.039 ms p50,
SUPERGUN-NETCODE 1.1) invites the arithmetic "16.667 / 0.039 = 427 matches per core". That arithmetic assumes
the tick cost is independent of how many matches share the machine. It is not: the tick's read set is small
but each match owns a private 212 KB blk + 4 MB ctx + 32 MB DC-RAM image, and rr_runner's own measurements
already show the tick slowing when the working set leaves cache (GATE-N1: per-tick resim 0.030 -> 0.050 ms as
the save ring grows to 24 MB).

This runs K REAL rr_runner processes concurrently on the same anchor and reports the per-tick distribution from
each summary.json, so the density claim is measured on the actual frame function rather than a synthetic proxy.

  python sg_tenancy.py --run <run dir> --inputs <inputs.txt> --ticks 300 --k 1 2 4 8 16 [--json out.json]

NOTE the runner is a SINGLETON by construction (rr_runner.cpp:709 "the image is position-dependent, contract C1";
256 MiB arena at a fixed VA), so tenancy = one PROCESS per match. That is itself the finding.
BYOR: outputs under %TEMP%.
"""
import argparse, json, os, statistics, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, '..', 'receipt', 'runner', 'rr_runner.exe')
OUT = os.path.join(os.environ.get('TEMP', '.'), 'sg_tenancy')


def pct(v, q):
    v = sorted(v)
    return v[min(len(v) - 1, int(len(v) * q))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', required=True)
    ap.add_argument('--inputs')
    ap.add_argument('--ticks', type=int, default=300)
    ap.add_argument('--k', type=int, nargs='+', default=[1, 2, 4, 8, 16])
    ap.add_argument('--json')
    a = ap.parse_args()
    pre = os.path.join(a.run, 'pre') if os.path.isdir(os.path.join(a.run, 'pre')) else a.run
    res = []
    for K in a.k:
        procs, outs = [], []
        t0 = time.time()
        for i in range(K):
            o = os.path.join(OUT, 'k%02d_%02d' % (K, i))
            os.makedirs(o, exist_ok=True)
            outs.append(o)
            cmd = [os.path.abspath(RUNNER), '--pre', pre, '--out', o, '--ticks', str(a.ticks),
                   '--dump-every', '0', '--no-dump-end', '--heap-mb', '256']
            if a.inputs:
                cmd += ['--inputs', a.inputs]
            procs.append(subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        rc = [p.wait() for p in procs]
        wall = time.time() - t0
        ms = []
        for o, r in zip(outs, rc):
            if r != 0:
                print('  K=%d: a process exited %d (%s)' % (K, r, o)); continue
            ms += json.load(open(os.path.join(o, 'summary.json')))['ms']
        if not ms:
            continue
        row = dict(K=K, n=len(ms), min=round(min(ms), 4), p50=round(pct(ms, .5), 4), p90=round(pct(ms, .9), 4),
                   p99=round(pct(ms, .99), 4), max=round(max(ms), 4), mean=round(statistics.fmean(ms), 4),
                   wall_s=round(wall, 1))
        # matches one core could hold at 60 Hz if the tick cost stayed at this value
        row['matches_per_core_p50'] = int(16.667 / row['p50'])
        row['matches_per_core_p99'] = int(16.667 / row['p99'])
        res.append(row)
        print('K=%-3d n=%-6d p50 %.4f  p90 %.4f  p99 %.4f  max %.4f  mean %.4f  wall %.1fs   -> %d matches/core at p50'
              % (K, row['n'], row['p50'], row['p90'], row['p99'], row['max'], row['mean'], wall, row['matches_per_core_p50']))
    if a.json:
        json.dump(res, open(a.json, 'w'), indent=1)


if __name__ == '__main__':
    main()
