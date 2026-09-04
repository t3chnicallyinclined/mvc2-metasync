#!/usr/bin/env python3
"""gate_n1.py -- GATE N1: rollback-state SUFFICIENCY + interleaved save/tick/restore timing for the receipt runner.

Why this gate exists (SUPERGUN NETCODE lane): the shipped MvC2 netcode persists only `blk` in its GGPO save/load
callbacks and pays 4 frames (66.7 ms) of unconditional input delay to avoid ~0.42 ms of resimulation CPU. Our runner
ticks the same frame function in ~0.08 ms, so that trade is not worth paying -- but only if rollback is actually SOUND
for our process, which additionally touches host state the shipped game never has to think about (the lazily committed
device-object page *(0x140acd3a8) whose PALETTE_RAM the tick writes, GATE1 s3.4; the ctx page-table records, GATE1
s3.5 / GATE3 s5). Composing a separately measured memcpy with a separately measured tick is not a rollback
measurement, and it proves nothing about sufficiency. `rr_runner --rollback N` does both in one interleaved loop.

Three arms per depth, deliberately:
  control      --rollback 1 --rb-set full --rb-verify all
               EVERY region restored (blk, blk2, gs page, exe page, the whole 4 MB ctx, the whole 32 MB DC-RAM, the
               GGPO counter), then ONE tick re-executed with the same input word. Whatever still differs cannot be
               missing rollback state -- it is nondeterminism in the tick itself. Run FIRST, every time, so the
               nondeterminism class is re-derived rather than assumed.
  correctness  --rb-verify all : every region is copied before the rollback and byte-compared after the resim. The
               36 MB of copying makes the timings meaningless, so they are ignored in this arm.
  timing       --rb-verify off : blk-only comparison (211 KB), i.e. what a real rollback would actually do. These are
               the numbers reported.

    python gate_n1.py --run <run dir> --inputs <inputs.txt> [--ticks 200] [--depths 0 2 4 8 16 30 60 120]
                      [--sets blk] [--json out.json]

BYOR: every input and output is game-derived and lives under %TEMP% (gitignored).
"""
import argparse, json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, 'rr_runner.exe')
OUT = os.path.join(os.environ.get('TEMP', '.'), 'rr_n1')


def run_one(run, inputs, ticks, depth, rbset, verify, tag):
    out = os.path.join(OUT, tag)
    os.makedirs(out, exist_ok=True)
    pre = os.path.join(run, 'pre') if os.path.isdir(os.path.join(run, 'pre')) else run
    cmd = [RUNNER, '--pre', pre, '--out', out, '--ticks', str(ticks), '--dump-every', '0', '--no-dump-end',
           '--rollback', str(depth), '--rb-set', rbset, '--rb-verify', verify, '--heap-mb', '1024']
    if inputs:
        cmd += ['--inputs', inputs]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True)
    wall = time.time() - t0
    if p.returncode != 0:
        print(''.join(p.stdout.splitlines(True)[-15:]))
        sys.exit('rr_runner failed (exit %d) for %s' % (p.returncode, tag))
    rb = json.load(open(os.path.join(out, 'summary.json'))).get('rollback')
    if rb is None:
        sys.exit('no rollback block in %s/summary.json' % out)
    rb['wall_s'] = round(wall, 2)
    return rb


def p50(d):
    return (d or {}).get('p50', 0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', required=True)
    ap.add_argument('--inputs', default=None)
    ap.add_argument('--ticks', type=int, default=200)
    ap.add_argument('--depths', type=int, nargs='*', default=[0, 2, 4, 8, 16, 30, 60, 120])
    ap.add_argument('--sets', nargs='*', default=['blk'])
    ap.add_argument('--json', default=None)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    # -- control arm: is anything that differs actually MISSING state, or is the tick nondeterministic? -----------
    ctl = run_one(a.run, a.inputs, min(40, a.ticks), 1, 'full', 'all', 'control_full_1')
    print('CONTROL depth 1, save set = FULL (blk+blk2+gs+exe+ctx+dcram+ggpo), 1 re-executed tick:')
    print('   %d events, %d fatal mismatch, ctx render-scratch nondeterminism on %d events (%d B)'
          % (ctl['events'], ctl['mismatch_events'], ctl['ctx_nondet_events'], ctl['ctx_nondet_bytes']))
    for k, v in sorted(ctl.get('ctx_buckets', {}).items()):
        print('     ctx bucket %-46s %d B' % (k, v))
    if ctl['mismatch_events']:
        print('   !! the control itself FAILS: something outside the full save set carries state. %s' % ctl.get('first_mismatch'))
    else:
        print('   => everything that still differs with EVERYTHING restored is tick nondeterminism, not rollback state.')
    print()

    print('N1b: per-EVENT cost (save+restore+resim); frame = that + the tick of the same frame. The old amortised')
    print('ms/frame column was ELIGIBILITY-WEIGHTED (a depth-N rollback only fires after tick k >= N) and is not used.')
    print()
    res = []
    for rbset in a.sets:
        for d in a.depths:
            if d >= a.ticks:
                print('skip depth %d (>= ticks %d)' % (d, a.ticks))
                continue
            c = run_one(a.run, a.inputs, a.ticks, d, rbset, 'all', 'corr_%s_%d' % (rbset, d))
            t = run_one(a.run, a.inputs, a.ticks, d, rbset, 'off', 'time_%s_%d' % (rbset, d))
            res.append(dict(set=rbset, depth=d, correctness=c, timing=t))
            ev, fr = t['event_ms'], t['frame_ms']
            print('%-6s depth %3d : %-4s events %4d of %d ticks | ring %7.1f KB | event p50 %8.4f p99 %8.4f max %8.4f'
                  ' | frame p99 %8.4f max %8.4f | over %.3f ms: %d'
                  % (rbset, d, 'PASS' if c['pass'] else 'FAIL', c['events'], t['ticks'], t['ring_bytes'] / 1024.0,
                     ev['p50'], ev['p99'], ev['max'], fr['p99'], fr['max'],
                     t['frame_budget_ms'], t['events_over_budget']))
            if not c['pass']:
                print('        first mismatch: %s' % c.get('first_mismatch'))
    print()
    for rbset in a.sets:
        rows = [r for r in res if r['set'] == rbset]
        ok = all(r['correctness']['pass'] for r in rows)
        bad = [r['depth'] for r in rows if not r['correctness']['pass']]
        print('GATE N1 rollback sufficiency, save set %-7s: %s%s'
              % (rbset, 'PASS' if ok else 'FAIL', '' if ok else '  (diverged at depths %s)' % bad))
    if a.json:
        json.dump(dict(control=ctl, matrix=res), open(a.json, 'w'), indent=1)
        print('json ->', a.json)


if __name__ == '__main__':
    main()
