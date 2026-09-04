#!/usr/bin/env python3
"""gate_n1c.py -- GATE N1c: is the SHIPPED rollback window sufficient on THIS stage?

Designed by the SUPERGUN NETCODE lane, who consume the result. The design question is not "what is the minimum save
set on stage X" -- it is "does the window we intend to ship survive stage X". That is three arms at ONE depth, not a
bisection:

  A  blk + the GGPO counter                      the shipped game's own save set
     FAIL => this stage needs ctx state at all (stage-9 behaviour)
  B  A + the proven 8 bytes ctx+0x1F8230..0x1F8238
     FAIL => the minimum is stage-dependent in its CONTENT, not merely in its necessity -- the interesting case
  C  A + the shipped 64 KB window ctx[0x1F0000..0x200000)
     FAIL => the netcode lane's s9.2 save set is FALSIFIED and deep speculation dies in its current form

Falsification condition, stated so it cannot be fudged:
    THE SAVE SET SURVIVES IFF ARM C PASSES ON EVERY STAGE TESTED. ONE ARM-C FAILURE KILLS IT.

Escalate to the full ladder (gate_n1.py) ONLY where B fails and C passes -- the sole case where a new minimum tells
us anything.

Reporting follows N1b: per-EVENT cost, never the eligibility-weighted per-frame average (a depth-N rollback can only
fire after tick k >= N, so dividing by all ticks understates by (ticks-N)/ticks and is undefined for <= N ticks).
p99 and max, the number of events exceeding the 16.667 ms frame budget, and the tick count of every run.

    python gate_n1c.py --run <run dir> --inputs <inputs.txt> [--depth 8] [--ticks 300] [--label carnival]

BYOR: outputs under %TEMP%/rr_n1c.
"""
import argparse, json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, 'rr_runner.exe')
OUT = os.path.join(os.environ.get('TEMP', '.'), 'rr_n1c')

SHIPPED_CTX_WINDOW = '1F0000-200000'      # 64 KiB, the netcode lane's s9.2 proposal
PROVEN_8_BYTES = '1F8230-1F8238'          # GATE N1


def run_arm(pre, tag, depth, ticks, inputs, ctx_extra, verify):
    out = os.path.join(OUT, tag)
    os.makedirs(out, exist_ok=True)
    cmd = [RUNNER, '--pre', pre, '--out', out, '--ticks', str(ticks), '--dump-every', '0', '--no-dump-end',
           '--rollback', str(depth), '--rb-set', 'blk', '--rb-verify', verify, '--heap-mb', '1024']
    if ctx_extra:
        cmd += ['--rb-ctx-extra', ctx_extra]
    if inputs:
        cmd += ['--inputs', inputs]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        print(''.join(p.stdout.splitlines(True)[-12:]))
        sys.exit('rr_runner failed (%d) for %s' % (p.returncode, tag))
    rb = json.load(open(os.path.join(out, 'summary.json')))['rollback']
    rb['wall_s'] = round(time.time() - t0, 1)
    return rb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', required=True)
    ap.add_argument('--inputs', default=None)
    ap.add_argument('--depth', type=int, default=8)
    ap.add_argument('--ticks', type=int, default=300)
    ap.add_argument('--label', default=None)
    ap.add_argument('--json', default=None)
    a = ap.parse_args()
    pre = os.path.join(a.run, 'pre') if os.path.isdir(os.path.join(a.run, 'pre')) else a.run
    label = a.label or os.path.basename(a.run.rstrip(chr(92) + '/'))
    os.makedirs(OUT, exist_ok=True)

    arms = [('A', 'blk + GGPO (the shipped game set)', None),
            ('B', 'A + the proven 8 B ctx+0x1F8230..38', PROVEN_8_BYTES),
            ('C', 'A + the shipped 64 KB ctx[0x1F0000..0x200000)', SHIPPED_CTX_WINDOW)]
    res = {}
    print('GATE N1c -- %s, depth %d, %d ticks, a rollback after EVERY eligible tick' % (label, a.depth, a.ticks))
    print()
    for name, desc, extra in arms:
        corr = run_arm(pre, '%s_%s_corr' % (label, name), a.depth, a.ticks, a.inputs, extra, 'all')
        time_ = run_arm(pre, '%s_%s_time' % (label, name), a.depth, a.ticks, a.inputs, extra, 'off')
        res[name] = dict(desc=desc, ctx_extra=extra, correctness=corr, timing=time_)
        ev, fr = time_['event_ms'], time_['frame_ms']
        print('  arm %s  %-46s %s' % (name, desc, 'PASS' if corr['pass'] else 'FAIL'))
        print('          events %d of %d ticks | ring %.1f KB | event p50 %.4f p99 %.4f max %.4f ms'
              % (corr['events'], time_['ticks'], time_['ring_bytes'] / 1024.0, ev['p50'], ev['p99'], ev['max']))
        print('          frame (event+tick) p99 %.4f max %.4f ms | over %.3f ms budget: %d of %d events'
              % (fr['p99'], fr['max'], time_['frame_budget_ms'], time_['events_over_budget'], fr['n']))
        if not corr['pass']:
            print('          first mismatch: %s' % corr.get('first_mismatch'))

    A, B, C = (res[k]['correctness']['pass'] for k in 'ABC')
    print()
    print('VERDICT for %s:' % label)
    print('  arm A (shipped game set)          : %s' % ('PASS' if A else 'FAIL -- this stage needs ctx state'))
    print('  arm B (A + the proven 8 bytes)    : %s' % ('PASS' if B else 'FAIL -- the minimum is stage-dependent IN CONTENT'))
    print('  arm C (A + the shipped 64 KB win) : %s' % ('PASS' if C else 'FAIL -- the s9.2 SAVE SET IS FALSIFIED'))
    if not C:
        print('  >> ARM C FAILED. The save set does not survive. Deep speculation dies in its current form.')
    elif not B:
        print('  >> B fails and C passes: ESCALATE to the full ladder (gate_n1.py) -- a new minimum is informative here.')
    else:
        print('  >> C passes; no escalation needed on this stage.')
    if a.json:
        json.dump(dict(label=label, depth=a.depth, ticks=a.ticks, arms=res), open(a.json, 'w'), indent=1)
        print('json ->', a.json)


if __name__ == '__main__':
    main()
