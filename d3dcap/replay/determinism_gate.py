#!/usr/bin/env python3
"""determinism_gate.py -- the measurements behind docs/DETERMINISM-CONTRACT.md (2026-09-03). Four sub-commands, all on the
dump_live images of one process (d3dcap/ttd/runs/<ts>/pre) and the p-code harness of emu_gate.py / EmuGate.java:

    python determinism_gate.py perturb  --run <run> [name ...]   # one variable per run: perturb ONE read-before-write
                                                                 # location the tick consumes, re-run FUN_140118950, hash blk /
                                                                 # game_state / ctx parts. sim-relevant <=> the blk hash changes.
                                                                 # Also probe/nudge variants (CRT math inputs; +1 ulp on a CRT
                                                                 # result -> does blk change?) and the FMA-flag variants.
    python determinism_gate.py multitick --run <run> --ticks 20  # gate (b): N consecutive ticks, the run's own seat words held
                                                                 # constant; blk dumped after every tick (feeds
                                                                 # receipt_gate.py --selftest)
    python determinism_gate.py native                            # gate 3: map the exe image at its link base IN THIS PROCESS and
                                                                 # call the game's own CRT tanf/sinf/cosf/atanf/sqrtf/floorf/powf
                                                                 # with DAT_142eefbd8 = 0 (SSE2) and 1 (FMA3); bitwise compare
    python determinism_gate.py dispatch                          # proves the native run really takes the FMA3 path for flag=1:
                                                                 # the SSE2 fall-through is patched to UD2 in a child process --
                                                                 # flag=0 must die, flag=1 must return the right value

Ghidra headless holds a project lock: never run two harness jobs at once (the 2026-09-03 batches that overlapped died with
LockException). Work files in %TEMP%\\rrcap_emu (ROM-derived bytes stay out of the repo).
"""
import argparse, ctypes, hashlib, json, math, os, struct, subprocess, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import emu_gate as G          # noqa: E402
import emu_frame as F         # noqa: E402

DEFAULT_RUN = r'C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\runs\20260903-000941'
CRT = {'tanf': 0x140817230, 'sinf': 0x1408121d0, 'cosf': 0x140811cd0, 'atanf': 0x1408d577c, 'sqrtf': 0x1408d59fc, 'floorf': 0x1408444e0}
POWF = 0x140803be0
# SSE2 fall-through of the `CMP [DAT_142eefbd8],0 ; JNZ <fma path>` dispatch at the entry of each FMA-capable CRT routine
SSE2_FALLTHROUGH = {'tanf': 0x140817241, 'sinf': 0x1408121e1, 'cosf': 0x140811ce1, 'powf': 0x140803bfd}
CTX_PARTS = dict(ta1=(0x30, 0x7EC), ta2=(0x30030, 0x3130C), pages=(0x100030, 0x108FC0), slots=(0x1e0030, 0x1e31CC), matrix=(0x1f80a4, 0x1f8600))


def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()[:16] if os.path.exists(p) else None


# -- perturb ---------------------------------------------------------------------------------------------------
def cmd_perturb(a):
    R = F.load_run(a.run)
    ftab, *_ = F.functable(G.WORK)
    inputs, seats, entry = F.tick_inputs(R)
    trace0 = os.path.join(G.WORK, 'frame_%s_tick_r0.trace.bin' % os.path.basename(a.run.rstrip('\\/')))
    if not os.path.exists(trace0):
        sys.exit('needs the baseline tick trace first: python emu_gate.py frame --run <run> --target tick --repeat 1')
    tr = np.fromfile(trace0, F.TRACE_DT)
    ctx, dc = R['ctx'], R['dcram']
    open(os.path.join(G.WORK, 'stack_cc.bin'), 'wb').write(bytes([0xCC]) * F.STACK_SIZE)
    MATH = dict(CRT, powf=POWF)

    def rets(entry_):
        sel = (tr['kind'] == 2) & (tr['pc'] == entry_)
        return sorted(set(int(x) for x in tr['addr'][sel]))
    V = {
        'baseline': ([], None),
        'gs520': (['set4 140ac7260 12345678'], None),                       # game_state+0x520 (read before written)
        'ggpo_ctr': (['set4 142d10b90 7777'], None),                        # DAT_142d10b90 GGPO frame counter
        'edf543': (['set4 142edf540 ffffffff'], None),                      # 0x142edf543 (FUN_1406163e0 state byte)
        'edf318': (['set4 142edf318 ffffffff', 'set4 142edf538 ffffffff', 'set4 142edf544 ffffffff'], None),
        'heapobj': (['set4 28b5f39c ffffffff', 'set4 28b5ef9c ffffffff'], None),   # *(DAT_142ebc010)+0x34aac ring (FUN_14006b5d0)
        'ctx_near': (['set4 %x 40000000' % (ctx + 0x1f82b0), 'set4 %x 12345678' % (ctx + 0x1f855c)], None),
        'ctx_slotflags0': (['set4 %x 0' % (ctx + 0x1e2624 + 0x18 * k) for k in range(123)], None),
        'ctx_matrix': (['set4 %x 3' % (ctx + 0x1f80a4)] + ['set4 %x 41000000' % (ctx + 0x1f80ec + 4 * k) for k in range(16)], None),
        'dcram_tiletab_prev': (['fill %x c00' % (dc + 0xE60040), 'fill %x 2c0' % (dc + 0xE62760), 'fill %x 200' % (dc + 0xE62AA0), 'fill %x 20' % (dc + 0xE62CC0)], None),
        'pl_137b94': (['set4 %x 5a5a5a5a' % (dc + 0x420000 + k * 0x150000 + o) for k in range(6) for o in (0x137b94, 0x137b98)], None),
        'pl_137b94_p1': (['set4 %x 5a5a5a5a' % (dc + 0x420000 + k * 0x150000 + o) for k in (0, 1, 2) for o in (0x137b94, 0x137b98)], None),
        'pl_137b94_p2': (['set4 %x 5a5a5a5a' % (dc + 0x420000 + k * 0x150000 + o) for k in (3, 4, 5) for o in (0x137b94, 0x137b98)], None),
        'stack_cc': (['mem %x %s' % (F.STACK_BASE, os.path.join(G.WORK, 'stack_cc.bin'))], None),
        'probe_math': (['probe %x %s' % (ad, n) for n, ad in MATH.items()], None),
        'fma_flag1_skip': ([], 1),
        'fma_flag1_compute': (['fma on'], 1),
        'fma_flag0_r2': ([], 0),
    }
    for n, ad in MATH.items():
        V['nudge_' + n] = (['nudge %x %s_ret' % (r, n) for r in rets(ad)], None)
    sel = a.names or list(V)
    out = []
    for name in sel:
        extra, fma = V[name]
        tag = 'pert_' + name
        lines, trace, outs = F.frame_job(R, 'tick', tag, G.WORK, 60000000, inputs, ftab)
        i = [k for k, l in enumerate(lines) if l.startswith('reg RCX')][0]
        lines = lines[:i] + extra + lines[i:]
        if fma is not None:
            lines = [('set4 %x %x' % (F.CRT_FMA_FLAG, fma)) if l.startswith('set4 %x' % F.CRT_FMA_FLAG) else l for l in lines]
        r = G.run_job(lines, tag)
        res = dict(name=name, status=r['status'], runs=r['runs'], hashes={k: sha(p) for k, p in outs.items()}, trace_sha=sha(trace),
                   extra=[e for e in r.get('extra', []) if e.startswith(('callother', 'fmacount', 'probe', 'nudge'))][:80],
                   uninit=['%x+%x' % u for u in r['uninit']])
        if os.path.exists(outs['ctx']):
            c = open(outs['ctx'], 'rb').read()
            res['ctx_parts'] = {k: hashlib.sha256(c[x:y]).hexdigest()[:12] for k, (x, y) in CTX_PARTS.items()}
        print(json.dumps(res)); sys.stdout.flush()
        out.append(res)
    if a.json:
        json.dump(out, open(a.json, 'w'), indent=1)
    return 0


# -- multitick -------------------------------------------------------------------------------------------------
def cmd_multitick(a):
    R = F.load_run(a.run)
    ftab, *_ = F.functable(G.WORK)
    inputs, seats, entry = F.tick_inputs(R)
    N = a.ticks
    tag = 'multitick_%d' % N
    lines, trace, outs = F.frame_job(R, 'tick', tag, G.WORK, 60000000, inputs, ftab)
    lines = [l for l in lines if not l.startswith('trace ')]
    i = [k for k, l in enumerate(lines) if l.startswith('run ')][0]
    per, extra = [], []
    for k in range(1, N):
        p = os.path.join(G.WORK, '%s.blk_t%02d.bin' % (tag, k))
        per.append(p)
        extra += ['dump %x %x %s' % (R['blk'], R['blk_size'], p), 'run %x' % F.FRAME_TICK]
    lines = lines[:i + 1] + extra + lines[i + 1:]
    r = G.run_job(lines, tag)
    print(r['status']); print('\n'.join(r['runs']))
    per.append(outs['blk'])
    pre, post = R['blk_bytes'], R.get('post_blk')
    prev = pre
    kb = F.kb_tables(); lab = F.Labeler(kb.get('global'), kb.get('field'))
    ever = np.zeros(len(pre), bool)
    for k, p in enumerate(per, 1):
        b = open(p, 'rb').read()
        x, y = np.frombuffer(prev, np.uint8), np.frombuffer(b, np.uint8)
        d = x != y; ever |= d
        g = {}
        for off in np.flatnonzero(d):
            grp, l = lab.blk(int(off)); g.setdefault(grp, set()).add(l)
        print('tick %2d: clock %d  changed vs prev %3d B  groups %s  rng(blk+0x32BD4)=%s' % (
            k, struct.unpack_from('<I', b, 0x3CC8)[0], int(d.sum()), {kk: len(v) for kk, v in g.items()}, b[0x32bd4:0x32bd6].hex()))
        prev = b
    print('bytes changed by at least one tick: %d' % int(ever.sum()))
    if post is not None:
        pp = np.frombuffer(pre, np.uint8) != np.frombuffer(post, np.uint8)
        print('pre->post diff %d B: touched by the %d ticks %d, never touched %d; changed by ticks but equal in pre/post %d' % (
            int(pp.sum()), N, int((pp & ever).sum()), int((pp & ~ever).sum()), int((ever & ~pp).sum())))
    json.dump(dict(tag=tag, status=r['status'], runs=r['runs'], dumps=per), open(os.path.join(G.WORK, 'multitick_%d.json' % N), 'w'), indent=0)
    return 0


# -- native oracle ---------------------------------------------------------------------------------------------
def map_image(run):
    import ctypes.wintypes as W
    R = F.load_run(run)
    k32 = ctypes.windll.kernel32
    k32.VirtualAlloc.restype = ctypes.c_void_p
    k32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, W.DWORD, W.DWORD]
    p = k32.VirtualAlloc(ctypes.c_void_p(R['exe']), R['exe_size'], 0x3000, 0x40)
    if p != R['exe']:
        sys.exit('VirtualAlloc at 0x%x failed (got %s): the link base is not free in this process' % (R['exe'], hex(p) if p else None))
    img = open(os.path.join(R['pre'], 'exe_image.bin'), 'rb').read()
    ctypes.memmove(ctypes.c_void_p(R['exe']), img, len(img))
    return R, img, ctypes.c_uint32.from_address(F.CRT_FMA_FLAG)


def cmd_native(a):
    R, img, flag = map_image(a.run)
    print('image mapped at 0x%x (%d B); live DAT_142eefbd8 = %d' % (R['exe'], len(img), flag.value))
    F1 = ctypes.CFUNCTYPE(ctypes.c_float, ctypes.c_float)
    F2 = ctypes.CFUNCTYPE(ctypes.c_float, ctypes.c_float, ctypes.c_float)
    fn = {n: F1(ad) for n, ad in CRT.items()}
    powf = F2(POWF)

    def bits(f):
        return struct.unpack('<I', struct.pack('<f', f))[0]

    def run(name, xs):
        out = {}
        for fl in (0, 1):
            flag.value = fl
            out[fl] = np.array([bits(fn[name](ctypes.c_float(float(x)))) for x in xs], np.uint32)
        d = out[0] != out[1]
        return dict(n=len(xs), differ=int(d.sum()), examples=[(float(xs[i]), '0x%08x' % out[0][i], '0x%08x' % out[1][i]) for i in np.flatnonzero(d)[:5]])
    rng = np.random.default_rng(1)
    rep = {}
    sweep = np.concatenate([np.linspace(-2 * math.pi, 2 * math.pi, 100001, dtype=np.float32), rng.uniform(-100, 100, 50000).astype(np.float32),
                            rng.uniform(-1e-3, 1e-3, 5000).astype(np.float32)])
    for n in ('tanf', 'sinf', 'cosf'):
        rep[n + '_sweep'] = run(n, sweep); print(n, 'sweep', rep[n + '_sweep'])
    rep['atanf_sweep'] = run('atanf', np.concatenate([np.linspace(-50, 50, 50001, dtype=np.float32), rng.uniform(-1e4, 1e4, 20000).astype(np.float32)])); print('atanf', rep['atanf_sweep'])
    rep['sqrtf_sweep'] = run('sqrtf', rng.uniform(0, 1e6, 50000).astype(np.float32)); print('sqrtf', rep['sqrtf_sweep'])
    rep['floorf_sweep'] = run('floorf', rng.uniform(-1e5, 1e5, 50000).astype(np.float32)); print('floorf', rep['floorf_sweep'])
    # the camera chain on EVERY u16 angle: t = tanf(angle*2pi/65536*0.5); h = atanf(t*0.75); sinf(h), cosf(h)
    ang = np.arange(65536, dtype=np.float64)
    t_in = (ang * np.float32(2 * math.pi) / np.float32(65536.0) * np.float32(0.5)).astype(np.float32)
    rep['tanf_all_u16_angles'] = run('tanf', t_in); print('tanf(all u16 angles)', rep['tanf_all_u16_angles'])
    flag.value = 0
    t = np.array([fn['tanf'](ctypes.c_float(float(x))) for x in t_in], np.float32)
    h_in = (t * np.float32(240.0 / 320.0)).astype(np.float32)
    rep['atanf_from_tan'] = run('atanf', h_in); print('atanf(t*0.75)', rep['atanf_from_tan'])
    h = np.array([fn['atanf'](ctypes.c_float(float(x))) for x in h_in], np.float32)
    rep['sinf_h'] = run('sinf', h); rep['cosf_h'] = run('cosf', h); print('sinf(h)', rep['sinf_h']); print('cosf(h)', rep['cosf_h'])
    x0 = struct.unpack('<f', img[0x920a18:0x920a1c])[0]          # FUN_1408433d0: powf(*0x140920a18, float(ebx>>4))
    ys = [float(k) for k in range(64)] + list(rng.uniform(0, 8, 2000).astype(np.float32))
    xs2 = rng.uniform(0.01, 100, 3000).astype(np.float32); ys2 = rng.uniform(-4, 4, 3000).astype(np.float32)
    for key, pairs in (('powf_x0', [(x0, y) for y in ys]), ('powf_sweep', list(zip(xs2, ys2)))):
        out = {}
        for fl in (0, 1):
            flag.value = fl
            out[fl] = np.array([bits(powf(ctypes.c_float(float(x)), ctypes.c_float(float(y)))) for x, y in pairs], np.uint32)
        d = out[0] != out[1]
        rep[key] = dict(n=len(pairs), differ=int(d.sum()), examples=[(float(pairs[i][0]), float(pairs[i][1]), '0x%08x' % out[0][i], '0x%08x' % out[1][i]) for i in np.flatnonzero(d)[:5]])
        print(key, rep[key])
    if a.json:
        json.dump(rep, open(a.json, 'w'), indent=1)
    return 0


def cmd_dispatch(a):
    """child per (routine, flag): SSE2 fall-through := UD2. flag=0 must crash (illegal instruction), flag=1 must return."""
    if a.child:
        name, fl = a.child, a.flag
        R, img, flag = map_image(a.run)
        flag.value = fl
        ctypes.memmove(ctypes.c_void_p(SSE2_FALLTHROUGH[name]), bytes([0x0f, 0x0b]), 2)
        if name == 'powf':
            v = ctypes.CFUNCTYPE(ctypes.c_float, ctypes.c_float, ctypes.c_float)(POWF)(ctypes.c_float(2.0), ctypes.c_float(3.0))
        else:
            v = ctypes.CFUNCTYPE(ctypes.c_float, ctypes.c_float)(CRT[name])(ctypes.c_float(0.7))
        print('%s flag=%d returned %.9g' % (name, fl, v))
        return 0
    ok = True
    for name in SSE2_FALLTHROUGH:
        for fl in (0, 1):
            p = subprocess.run([sys.executable, os.path.abspath(__file__), 'dispatch', '--run', a.run, '--child', name, '--flag', str(fl)],
                               capture_output=True, text=True)
            died = p.returncode != 0
            line = (p.stdout.strip().splitlines() or [''])[-1]
            expect = died if fl == 0 else (not died and 'returned' in line)
            ok &= expect
            print('%-5s flag=%d: exit 0x%08x %s -> %s' % (name, fl, p.returncode & 0xffffffff, line, 'as expected' if expect else 'UNEXPECTED'))
    print('DISPATCH PROOF: %s' % ('flag=1 executes the FMA3 path, flag=0 the SSE2 path (SSE2 patched to UD2 dies only for flag=0)' if ok else 'FAILED'))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('perturb'); p.add_argument('--run', default=DEFAULT_RUN); p.add_argument('names', nargs='*'); p.add_argument('--json')
    m = sub.add_parser('multitick'); m.add_argument('--run', default=DEFAULT_RUN); m.add_argument('--ticks', type=int, default=20)
    n = sub.add_parser('native'); n.add_argument('--run', default=DEFAULT_RUN); n.add_argument('--json')
    d = sub.add_parser('dispatch'); d.add_argument('--run', default=DEFAULT_RUN); d.add_argument('--child'); d.add_argument('--flag', type=int, default=0)
    a = ap.parse_args()
    return {'perturb': cmd_perturb, 'multitick': cmd_multitick, 'native': cmd_native, 'dispatch': cmd_dispatch}[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main())
