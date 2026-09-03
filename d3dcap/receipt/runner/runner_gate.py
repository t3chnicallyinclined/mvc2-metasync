#!/usr/bin/env python3
"""runner_gate.py -- GATE 1 of the receipt runner (docs/WORKSTREAM-RECEIPT-RUNNER.md s4 step 1, docs/RECEIPT-RUNNER-RE.md s3.2):
the NATIVE runner's per-tick blk dumps must equal the p-code harness's dumps for the same run + inputs BYTE FOR BYTE, and
(when the tape is available) the runner's px/py/hp/clock must equal the tape rows (receipt_gate.compare).

    python runner_gate.py --run <run dir> --mode idle20            # 20 idle ticks vs determinism_gate.py multitick --tag <oracle>
    python runner_gate.py --run <run dir> --mode tape --ticks 300  # the tape's inputs vs receipt_gate.py's per-tick dumps
    python runner_gate.py --run <run dir> --mode all [--tape <tape.json.gz>] [--runner-args "--crt real"]

Oracle dumps live in %TEMP%\\rrcap_emu (emu_gate.WORK):
  idle : <oracle-tag>.blk_t01..t19.bin + <oracle-tag>.blk_out.bin (= tick 20)   [determinism_gate.py multitick --ticks 20 --tag T]
  tape : receipt_<run>_<clock>_<n>.blk_t001..tNNN.bin                            [receipt_gate.py --run <run> --tape <tape> --frames n]
The inputs the tape mode feeds are read from the ORACLE JOB FILE (receipt_*.job.txt: `set4 30000000 w0` / `set4 30000004 w1`
before every `run 140118950`), so the byte-exact comparison is defined even when the tape file itself is not at hand; the
tape rows (px/py/hp/clock) are compared when --tape is given.

RE METHOD (docs/RE-METHOD.md) step 4: this is the numeric gate; the pairs it rests on are FRAME-READSET / DETERMINISM-CONTRACT.
All inputs are game-derived and live outside the repo (runs/, %TEMP%); this script and the runner source are the only artefacts.
"""
import argparse, glob, json, os, re, struct, subprocess, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPLAY = os.path.normpath(os.path.join(HERE, '..', '..', 'replay'))
sys.path.insert(0, REPLAY)
import emu_frame as F          # noqa: E402  (Labeler names the first differing blk byte)
import receipt_gate as RG      # noqa: E402  (tape loader + px/py/hp/clock compare)

WORK = os.path.join(os.environ.get('TEMP', '.'), 'rrcap_emu')
OUT = os.path.join(os.environ.get('TEMP', '.'), 'rrcap_runner')
RUNNER = os.path.join(HERE, 'rr_runner.exe')


def build_runner():
    if os.path.exists(RUNNER):
        return
    print('building the runner:', os.path.join(HERE, 'build.bat'))
    subprocess.run(['cmd.exe', '/c', os.path.join(HERE, 'build.bat')], check=True)


def run_native(pre, out, ticks, inputs_path, extra):
    os.makedirs(out, exist_ok=True)
    cmd = [RUNNER, '--pre', pre, '--out', out, '--ticks', str(ticks)] + (['--inputs', inputs_path] if inputs_path else []) + list(extra)
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    log = r.stdout + r.stderr
    open(os.path.join(out, 'gate_stdout.txt'), 'w').write(log)
    return r.returncode, log, time.time() - t0


def job_inputs(job_path):
    """the exact seat words the oracle job fed before every `run 140118950` (emu_frame.INPUT_SCRATCH = 0x30000000)."""
    w0 = w1 = 0
    out = []
    for ln in open(job_path):
        t = ln.split()
        if len(t) == 3 and t[0] == 'set4' and t[1] == '30000000':
            w0 = int(t[2], 16)
        elif len(t) == 3 and t[0] == 'set4' and t[1] == '30000004':
            w1 = int(t[2], 16)
        elif len(t) == 2 and t[0] == 'run':
            out.append((w0, w1))
    return out


def compare_dumps(runner_dir, oracle_paths, labeler, blk_base):
    rows = []
    first_bad = None
    for k, op in enumerate(oracle_paths, 1):
        rp = os.path.join(runner_dir, 'blk_t%03d.bin' % k)
        if not os.path.exists(rp) or not os.path.exists(op):
            rows.append(dict(tick=k, status='missing', runner=os.path.exists(rp), oracle=os.path.exists(op)))
            if first_bad is None:
                first_bad = rows[-1]
            continue
        a = np.frombuffer(open(rp, 'rb').read(), np.uint8)
        b = np.frombuffer(open(op, 'rb').read(), np.uint8)
        d = np.flatnonzero(a != b)
        clk_r, clk_o = struct.unpack_from('<I', a, 0x3CC8)[0], struct.unpack_from('<I', b, 0x3CC8)[0]
        row = dict(tick=k, differing=int(len(d)), clock_runner=int(clk_r), clock_oracle=int(clk_o))
        if len(d):
            off = int(d[0])
            grp, lab = labeler.blk(off)
            row.update(first_off='0x%X' % off, group=grp, label=lab, runner_byte='%02x' % a[off], oracle_byte='%02x' % b[off],
                       ranges=[('0x%X' % s, n) for s, n in F.ranges_from_mask(a != b)[:12]])
            if first_bad is None:
                first_bad = row
        rows.append(row)
    return rows, first_bad


def gate_idle(R, pre, a, labeler):
    tag = a.oracle_tag
    oracle = [os.path.join(WORK, '%s.blk_t%02d.bin' % (tag, k)) for k in range(1, 20)] + [os.path.join(WORK, '%s.blk_out.bin' % tag)]
    if not all(os.path.exists(p) for p in oracle):
        sys.exit('idle oracle missing: python %s multitick --run %s --ticks 20 --tag %s' % (os.path.join(REPLAY, 'determinism_gate.py'), a.run, tag))
    out = os.path.join(OUT, 'idle20' + a.suffix)
    rc, log, wall = run_native(pre, out, 20, None, a.runner_args)
    rows, bad = compare_dumps(out, oracle, labeler, R['blk'])
    return dict(name='idle20', runner_rc=rc, wall=wall, rows=rows, first_bad=bad, out=out, log_tail=log[-1500:])


def gate_tape(R, pre, a, labeler, n):
    start = R['clock']
    tag = 'receipt_%s_%d_%d' % (os.path.basename(a.run.rstrip('\\/')), start, n)
    job = os.path.join(WORK, tag + '.job.txt')
    oracle = [os.path.join(WORK, '%s.blk_t%03d.bin' % (tag, k)) for k in range(1, n + 1)]
    if not os.path.exists(job) or not all(os.path.exists(p) for p in oracle):
        sys.exit('tape oracle missing for %d ticks: python %s --run %s --tape <tape> --frames %d' % (n, os.path.join(REPLAY, 'receipt_gate.py'), a.run, n))
    words = job_inputs(job)
    if len(words) < n:
        sys.exit('oracle job %s has %d ticks, need %d' % (job, len(words), n))
    out = os.path.join(OUT, 'tape%d%s' % (n, a.suffix))
    os.makedirs(out, exist_ok=True)
    inp = os.path.join(out, 'inputs.txt')
    open(inp, 'w').write('# tick k: seat0 seat1 (hex), from the oracle job %s\n' % job + ''.join('%x %x\n' % w for w in words[:n]))
    rc, log, wall = run_native(pre, out, n, inp, a.runner_args)
    rows, bad = compare_dumps(out, oracle, labeler, R['blk'])
    res = dict(name='tape%d' % n, runner_rc=rc, wall=wall, rows=rows, first_bad=bad, out=out, inputs=inp, log_tail=log[-1500:])
    if a.tape and os.path.exists(a.tape):
        t, C = RG.load_tape(a.tape)
        dumps = [os.path.join(out, 'blk_t%03d.bin' % k) for k in range(1, n + 1)]
        if all(os.path.exists(p) for p in dumps):
            res['tape_compare'] = RG.compare(t['frames'], C, dumps, start)
    return res


def timing(out):
    p = os.path.join(out, 'summary.json')
    if not os.path.exists(p):
        return None
    s = json.load(open(p))
    ms = sorted(s['ms'])
    if not ms:
        return None
    q = lambda x: ms[min(len(ms) - 1, int(x * len(ms)))]
    return dict(n=len(ms), min=ms[0], p50=q(0.5), mean=sum(ms) / len(ms), p90=q(0.9), p99=q(0.99), max=ms[-1], ext=s.get('ext'), cfg={k: s[k] for k in ('gs', 'crt', 'fma', 'prot') if k in s})


def report(res):
    rows = res['rows']
    exact = sum(1 for r in rows if r.get('differing') == 0)
    clock_ok = sum(1 for r in rows if r.get('clock_runner') == r.get('clock_oracle') and 'differing' in r)
    print('== %s: runner rc=%s wall %.1fs  blk byte-exact %d/%d ticks  clock equal %d/%d' % (res['name'], res['runner_rc'], res['wall'], exact, len(rows), clock_ok, len(rows)))
    tm = timing(res['out'])
    if tm:
        print('   timing per tick (ms): n=%d min %.3f p50 %.3f mean %.3f p90 %.3f p99 %.3f max %.3f  [real-time budget 16.667]  cfg %s  ext %s' % (
            tm['n'], tm['min'], tm['p50'], tm['mean'], tm['p90'], tm['p99'], tm['max'], tm['cfg'], tm['ext']))
    b = res['first_bad']
    if b:
        print('   FIRST DIVERGENCE: tick %d: %s' % (b['tick'], json.dumps({k: v for k, v in b.items() if k != 'tick'}, default=str)))
        for r in rows:
            if r.get('differing'):
                print('     tick %3d: %6d B differ  first blk+%s %s' % (r['tick'], r['differing'], r.get('first_off'), r.get('label')))
                if r['tick'] >= b['tick'] + 5:
                    break
    if res['runner_rc'] not in (0, None):
        print('   runner log tail:\n' + '\n'.join('     ' + l for l in res['log_tail'].strip().splitlines()[-25:]))
    tc = res.get('tape_compare')
    if tc:
        e = tc['exact']
        print('   vs TAPE rows: %d ticks: clock %d/%d px %d/%d py %d/%d hp %d/%d  first_div %s' % (tc['frames'], e['clock'], tc['frames'], e['px'], tc['frames'], e['py'], tc['frames'], e['hp'], tc['frames'], tc.get('first_div')))
    return exact == len(rows) and len(rows) > 0 and res['runner_rc'] == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', required=True)
    ap.add_argument('--mode', default='all', choices=['idle20', 'tape', 'all'])
    ap.add_argument('--ticks', type=int, nargs='*', default=[60, 300], help='tape-mode tick counts (each needs its receipt_gate oracle)')
    ap.add_argument('--tape', default=None)
    ap.add_argument('--oracle-tag', default=None, help='multitick tag of the idle oracle (default multitick_<runname>_20 then multitick_20)')
    ap.add_argument('--runner-args', default='', help='extra rr_runner flags, e.g. "--crt real" or "--gs file" (one variable per run)')
    ap.add_argument('--suffix', default='', help='output dir suffix for variant runs')
    ap.add_argument('--json', default=None)
    a = ap.parse_args()
    a.runner_args = a.runner_args.split()
    build_runner()
    R = F.load_run(a.run)
    pre = R['pre']
    if a.oracle_tag is None:
        cand = 'multitick_%s_20' % os.path.basename(a.run.rstrip('\\/')).replace('receipt-', '').replace('-anchor', '').replace('20260903-', '')
        a.oracle_tag = cand if os.path.exists(os.path.join(WORK, cand + '.blk_out.bin')) else 'multitick_20'
    kb = F.kb_tables()
    labeler = F.Labeler(kb.get('global'), kb.get('field'))
    results, ok = [], True
    if a.mode in ('idle20', 'all'):
        results.append(gate_idle(R, pre, a, labeler)); ok &= report(results[-1])
    if a.mode in ('tape', 'all'):
        for n in a.ticks:
            results.append(gate_tape(R, pre, a, labeler, n)); ok &= report(results[-1])
    print('GATE 1 (native runner == p-code oracle, byte-exact blk per tick): %s' % ('PASS' if ok else 'FAIL'))
    if a.json:
        json.dump(dict(run=a.run, oracle_tag=a.oracle_tag, runner_args=a.runner_args, results=results, timing={r['name']: timing(r['out']) for r in results}), open(a.json, 'w'), indent=1, default=str)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
