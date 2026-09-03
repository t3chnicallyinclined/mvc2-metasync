#!/usr/bin/env python3
"""emu_gate.py -- EMULATE a Steam MvC2 function on a captured frame's memory and gate it numerically.

    python emu_gate.py camera 4445                 # FUN_14061d7e0 / FUN_14061d6a0 / FUN_14061d5b0 vs the
                                                   # captured scene CBs of frame_4445.pack and the closed form
    python emu_gate.py walker 4445                 # FUN_140620f10 vs the same frame's post-walk node fields
    python emu_gate.py walker 4445 --composite prev|cur|none
    python emu_gate.py raw job.txt                 # run any EmuGate job file (see re_map/ghidra_emu/EmuGate.java)

RE METHOD, step 4 (docs/RE-METHOD.md): the function pairs are already matched (seed 30, 24); this is the
deterministic GATE. The Steam x86-64 routine runs, instruction by instruction, inside Ghidra's p-code
emulator (EmulatorHelper over the raw dump C:\\Users\\trist\\ghidra_projects\\mvc_dump.bin, headless, a scratch
project so the GUI's lock on `dumpproj` is never touched). The memory it sees is:
  * the image itself (code, float constants, runtime-built sin/cos tables, dump-time globals);
  * the captured rollback block `blk` (blkstate.load_frame) placed at the address the handles say it lived at,
    with DAT_142edf560 = base and DAT_142edf580 = base + 0x3CB8;
  * whatever else the job writes. EVERYTHING ELSE is zero-filled on first read and LOGGED, so the result
    says exactly which memory had to be synthesised (docs/EMU-GATE.md lists them per target).

The gate is a NUMBER: bit-identical float count and max-abs error against the capture, never "looks right".

Ghidra one-time setup (idempotent, done by ensure_project()):
    "C:\\g\\ghidra_12.1.2_PUBLIC\\support\\analyzeHeadless.bat" C:\\Users\\trist\\ghidra_projects\\emu emuproj
        -import C:\\Users\\trist\\ghidra_projects\\mvc_dump.bin -loader BinaryLoader -loader-baseAddr 0x140000000
        -loader-blockName image -processor x86:LE:64:default -cspec windows -noanalysis
"""
import argparse
import json
import os
import struct
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import blkstate as S                      # noqa: E402

GHIDRA_HEADLESS = os.environ.get('GHIDRA_HEADLESS', r'C:\g\ghidra_12.1.2_PUBLIC\support\analyzeHeadless.bat')
PROJ_DIR = os.environ.get('EMU_PROJ_DIR', r'C:\Users\trist\ghidra_projects\emu')
PROJ_NAME = 'emuproj'
PROG_NAME = 'mvc_dump.bin'
DUMP = r'C:\Users\trist\ghidra_projects\mvc_dump.bin'
SCRIPT_DIR = os.path.join(HERE, 're_map', 'ghidra_emu')
WORK = os.path.join(os.environ.get('TEMP', '.'), 'rrcap_emu')       # ROM-derived bytes stay out of the repo
DEF_CAP = os.path.join(HERE, 'capgate', 'state')
DEF_PACKDIR = os.path.join(HERE, 'capgate')

IMAGE_BASE = 0x140000000
BLK_PTR, G_PTR, CTX_PTR, CUR_PTR = 0x142edf560, 0x142edf580, 0x142ef0ab0, 0x142ef0ab8
G_OFF = 0x3CB8
CRT_FMA_FLAG = 0x142eefbd8            # UCRT "__use_fma3" dispatch: 1 in the dump -> vfmadd (not in p-code)
MATH = {0x140817230: 'tanf', 0x1408d577c: 'atanf', 0x140811cd0: 'cosf', 0x1408121d0: 'sinf'}
CAM_WORLD, CAM_X01, CAM_HUD = 0x14061d7e0, 0x14061d6a0, 0x14061d5b0
WALKER, SUBMIT, COMPOSITE = 0x140620f10, 0x1406129f0, 0x140847d10
LAYERZ_TABLE = 0x140a6d888            # FUN_140613390: layers 0..7 from here, 8..15 immediates below
LAYERZ_IMM = [10.0, 11.0, 12.0, 13.0, 30.0, 31.0, 32.0, 33.0]
# NaomiLib host context (docs/WORLD-CAMERA-GHIDRA.md s1)
CTX_MODE, CTX_SLOT0, CTX_COMPOSITE, CTX_NEAR, CTX_SIZE = 0x1f80a4, 0x1f80ac, 0x1f8200, 0x1f82b0, 0x1f8600
# FUN_140846a40(storage, depth): push/pop storage pointer ctx+0x1f81b0, depth counters +0x1f81b8/+0x1f81bc,
# modes 0, all four slots + both scratch matrices = identity. FUN_140847950 (push) does NOTHING -- not even the
# load of its argument -- when +0x1f81bc < 1, so a zeroed ctx silently breaks every point projection.
# The game calls it as FUN_140846a40(DAT_142edf560, 0x40) (FUN_14060b550 @ 0x14060b628, CONFIRMED): the
# storage is the FIRST 0x1000 BYTES OF blk, so the captured block already holds it; only ctx needs the init.
STACK_INIT, MSTACK_DEPTH = 0x140846a40, 0x40
SLOT = {m: CTX_SLOT0 + 0x40 * m for m in range(4)}
STACK_BASE, STACK_SIZE = 0x10000000, 0x100000

# walker outputs per node (TAPE-V3-SPEC.md s10.1)
NODE_FIELDS = [('sx', 0x124, '<f'), ('sy', 0x128, '<f'), ('depth', 0x12C, '<f'), ('scx', 0x130, '<f'),
               ('scy', 0x134, '<f'), ('angle', 0x148, '<I'), ('z150', 0x150, '<I'), ('facing', 0x154, '<i'),
               ('hotx', 0x178, '<H'), ('hoty', 0x17A, '<H')]


# ── dump / project helpers ─────────────────────────────────────────────────────────────────────────────────
_dump = None


def dump_bytes(addr, n):
    global _dump
    if _dump is None:
        _dump = open(DUMP, 'rb').read()
    o = addr - IMAGE_BASE
    return _dump[o:o + n]


def dump_u64(addr):
    return struct.unpack('<Q', dump_bytes(addr, 8))[0]


def ensure_project():
    gpr = os.path.join(PROJ_DIR, PROJ_NAME + '.gpr')
    if os.path.exists(gpr):
        return
    os.makedirs(PROJ_DIR, exist_ok=True)
    cmd = [GHIDRA_HEADLESS, PROJ_DIR, PROJ_NAME, '-import', DUMP, '-loader', 'BinaryLoader',
           '-loader-baseAddr', '0x%x' % IMAGE_BASE, '-loader-blockName', 'image',
           '-processor', 'x86:LE:64:default', '-cspec', 'windows', '-noanalysis']
    print('importing the dump into a scratch Ghidra project (one time):\n  ' + ' '.join(cmd))
    subprocess.run(cmd, check=True)


def run_job(lines, tag):
    """Write a job file, run EmuGate.java on it headless, parse the result file."""
    ensure_project()
    os.makedirs(WORK, exist_ok=True)
    job = os.path.join(WORK, tag + '.job.txt')
    res = os.path.join(WORK, tag + '.result.txt')
    log = os.path.join(WORK, tag + '.ghidra.log')
    if os.path.exists(res):
        os.remove(res)
    body = list(lines) + ['out ' + res, '']
    open(job, 'w').write('\n'.join(body))
    cmd = [GHIDRA_HEADLESS, PROJ_DIR, PROJ_NAME, '-process', PROG_NAME, '-noanalysis', '-readOnly',
           '-scriptPath', SCRIPT_DIR, '-postScript', 'EmuGate.java', job]
    t0 = time.time()
    with open(log, 'w') as lf:
        subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT)
    out = dict(tag=tag, job=job, log=log, result=res, wall=time.time() - t0, runs=[], stubhits=[], uninit=[],
               unknown=[], status='no result file (see %s)' % log, cmd=' '.join(cmd))
    if not os.path.exists(res):
        return out
    for ln in open(res):
        t = ln.strip().split(' ')
        if t[0] == 'run':
            out['runs'].append(' '.join(t[1:]))
        elif t[0] == 'status':
            out['status'] = ' '.join(t[1:])
        elif t[0] in ('stubhit', 'stubmiss', 'mathhook'):
            out['stubhits'].append(ln.strip())
        elif t[0] == 'uninit':
            out['uninit'].append((int(t[1], 16), int(t[2], 16)))
        elif t[0] == 'unknown':
            out['unknown'].append((int(t[1], 16), int(t[2], 16)))
        else:
            out.setdefault('extra', []).append(ln.strip())       # traced / extcount / callother / note / mem
    return out


def classify_uninit(ranges, base, ctx):
    """Which synthesised memory did the code touch: stack / ctx / TEB-null page / blk (should be none) / other."""
    cls = {'stack': [], 'ctx': [], 'nullpage': [], 'blk': [], 'other': []}
    for a, n in ranges:
        if STACK_BASE <= a < STACK_BASE + STACK_SIZE:
            cls['stack'].append((a, n))
        elif ctx <= a < ctx + CTX_SIZE:
            cls['ctx'].append((a - ctx, n))
        elif a < 0x10000:
            cls['nullpage'].append((a, n))
        elif base <= a < base + S.BLK_SZ:
            cls['blk'].append((a - base, n))
        else:
            cls['other'].append((a, n))
    return cls


# ── frame state ────────────────────────────────────────────────────────────────────────────────────────────
def recover_base(blk):
    """blkstate.find_base with one extra constraint: the block is a page-aligned heap allocation (every capture
    with a sidecar base, and every recovered base on frames with >= 4 handles, ends in 0x000). On frames with
    only 2-3 handles the plain vote can pick a shifted base (frame 4518: 0x15DE3BB0) whose node list is garbage."""
    from collections import Counter
    handles = []
    for L in range(S.N_LAYERS):
        n = min(blk[S.DRAWLIST_COUNTS + L], S.MAX_PER_LAYER)
        for i in range(n):
            h = struct.unpack_from('<Q', blk, S.DRAWLIST_OFF + L * S.DRAWLIST_LAYER + i * 8)[0]
            if h > 0x10000:
                handles.append(h)
    votes = Counter()
    for h in handles:
        for slot in range(6):
            b = h - (S.H0_OFF + slot * S.SLOT_STRIDE)
            if b > 0 and (b & 0xFFF) == 0:
                votes[b] += sum(1 for x in handles if b <= x < b + S.BLK_SZ)
    if not votes:
        return None, 0, len(handles)
    b, sc = votes.most_common(1)[0]
    return b, sc, len(handles)


def frame_state(frame, cap):
    meta, blk = S.load_frame(frame, cap)
    if meta.get('base'):
        return meta, blk, int(meta['base'])
    base, score, nh = recover_base(blk)
    if not base or score < nh:
        sys.exit('frame %d: cannot recover a page-aligned blk base (%d of %d handles inside) -- refusing to guess'
                 % (frame, score, nh))
    return meta, blk, base


def f32bits(x):
    return struct.unpack('<I', struct.pack('<f', x))[0]


def base_job(blk, base, tag, math='sse2'):
    """Memory every target needs: the block, the two block globals, the near plane, the stack, the CRT path."""
    os.makedirs(WORK, exist_ok=True)
    bp = os.path.join(WORK, tag + '.blk.bin')
    open(bp, 'wb').write(blk)
    ctx = dump_u64(CTX_PTR)
    lines = ['# %s' % tag,
             'stack %x %x' % (STACK_BASE, STACK_SIZE),
             'mem %x %s' % (base, bp),
             'set8 %x %x' % (BLK_PTR, base),
             'set8 %x %x' % (G_PTR, base + G_OFF),
             # the engine's own matrix-stack init, run as a prologue with the game's own arguments
             'reg RCX %x' % base, 'reg RDX %x' % MSTACK_DEPTH,
             'maxsteps 10000', 'run %x' % STACK_INIT,
             # FUN_140620960 writes 1.0 here at the top of every render frame (CONFIRMED); synthesised
             'set4 %x %x' % (ctx + CTX_NEAR, f32bits(1.0))]
    if math == 'sse2':
        lines.append('set4 %x 0' % CRT_FMA_FLAG)          # take the UCRT SSE2 path (the game's own code)
    elif math == 'hook':
        lines += ['mathhook %x %s' % (a, n) for a, n in MATH.items()]
    else:
        sys.exit('math must be sse2 or hook')
    return lines, ctx


# ── closed forms (docs/WORLD-CAMERA-GHIDRA.md s2), float64 ─────────────────────────────────────────────────
def persp(angle, aspect, near, far, ox, oy):
    t = np.tan(angle * 2 * np.pi / 65536 * 0.5)
    h = np.arctan(t * 240.0 / 320.0)
    cot = np.cos(h) / np.sin(h)
    return np.array([[cot / aspect, 0, 0, 0], [0, cot, 0, 0],
                     [-ox, -oy, -(far + near) / (far - near), -1], [0, 0, -2 * far * near / (far - near), 0]])


def lookat(eye, target, roll):
    eye, target = np.asarray(eye, float), np.asarray(target, float)
    d = eye - target
    d /= np.linalg.norm(d)
    r = np.cross([0, 1, 0], d)
    r /= np.linalg.norm(r)
    u = np.cross(d, r)
    L = np.array([[r[0], u[0], d[0], 0], [r[1], u[1], d[1], 0], [r[2], u[2], d[2], 0],
                  [-eye @ r, -eye @ u, -eye @ d, 1]])
    if roll:
        a = roll * 2 * np.pi / 65536
        Rz = np.array([[np.cos(a), np.sin(a), 0, 0], [-np.sin(a), np.cos(a), 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
        return L @ Rz            # *cur = Rz x I, then *cur = L x *cur  (pre-multiply)
    return L


def camera_closed_forms(blk):
    eye = struct.unpack_from('<3f', blk, 0x6914)
    tgt = struct.unpack_from('<3f', blk, 0x695c)
    fov = struct.unpack_from('<f', blk, 0x6974)[0]
    oy = struct.unpack_from('<f', blk, 0x6988)[0]
    roll = struct.unpack_from('<H', blk, 0x698c)[0]
    angle = int(np.float32(np.float32(fov) * np.float32(65536.0)) / np.float32(360.0) + np.float32(0.5)) & 0xffff
    aspect = 1.3333333730697632
    return {
        CAM_WORLD: (persp(angle, aspect, 1.0, 1400000.0, 0.0, oy), lookat(eye, tgt, roll)),
        CAM_X01: (persp(angle, aspect, 1.0, 12000.0, 0.0, oy),
                  lookat(np.float32(eye) * np.float32(0.1), np.float32(tgt) * np.float32(0.1), roll)),
        CAM_HUD: (persp(0x4000, aspect, 1.0, 12000.0, 0.0, 0.0), np.eye(4)),
    }, dict(eye=eye, target=tgt, fov=fov, oy=oy, roll=roll, angle=angle)


# ── captured scene CBs (emitter_gate.load_pack) ────────────────────────────────────────────────────────────
def scene_cbs(pack_path):
    """{hash: (27x4 f32, ndraws)} for the 432-B CBs, plus which one the identity-CBWorld world draws bind."""
    import emitter_gate as E
    man, B = E.load_pack(pack_path)
    cbs = man['constantBuffers']
    ident48 = struct.pack('<12f', 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0)
    use, world_hash = {}, {}
    for d in man['draws']:
        hs = [h for h in d['vscbHash'] if h != '00000000']
        for h in hs:
            use[h] = use.get(h, 0) + 1
        h48 = [h for h in hs if cbs.get(h, {}).get('len') == 48]
        h432 = [h for h in hs if cbs.get(h, {}).get('len') == 432]
        if d.get('vsVariant') == 'vs_world' and h48 and h432 and B(cbs[h48[0]]) == ident48:
            world_hash[h432[0]] = world_hash.get(h432[0], 0) + 1
    out = {}
    for h, v in cbs.items():
        if v['len'] == 432:
            out[h] = (np.frombuffer(B(v), np.float32).reshape(27, 4).copy(), use.get(h, 0))
    return out, world_hash


def pick_cbs(cbs, world_hash):
    """Structural selection, independent of the emulated values:
       world = the 432-B CB bound by identity-CBWorld vs_world draws; hud = V (rows 7-10) == identity;
       x0.1 = whatever else is bound to at least one draw."""
    hud = [h for h, (m, n) in cbs.items() if n and np.array_equal(m[7:11], np.eye(4, dtype=np.float32))]
    # the HUD / list-0xC draws ALSO bind an identity CBWorld (their V is the identity): exclude them
    cand = {h: n for h, n in world_hash.items() if h not in hud}
    world = max(cand, key=cand.get) if cand else None
    rest = [h for h, (m, n) in cbs.items() if n and h != world and h not in hud]
    return world, hud, rest


def cmp_mats(emuP, emuV, cbm, closedP, closedV):
    cbP, cbV, cbVP = cbm[15:19], cbm[7:11], cbm[0:4]
    VP = (emuV.astype(np.float32) @ emuP.astype(np.float32)).astype(np.float32)
    bits = lambda a, b: int((a.view(np.uint32) == b.view(np.uint32)).sum())
    return dict(P_bits=bits(emuP, cbP), P_maxabs=float(np.abs(emuP - cbP).max()),
                V_bits=bits(emuV, cbV), V_maxabs=float(np.abs(emuV - cbV).max()),
                VP_bits=bits(VP, cbVP), VP_maxabs=float(np.abs(VP - cbVP).max()),
                P_vs_closed=float(np.abs(emuP - closedP).max()), V_vs_closed=float(np.abs(emuV - closedV).max()))


# ── target 1: the camera routines ──────────────────────────────────────────────────────────────────────────
def cmd_camera(a):
    meta, blk, base = frame_state(a.frame, a.cap)
    pack = a.pack or os.path.join(DEF_PACKDIR, 'frame_%d.pack' % a.frame)
    cbs, world_hash = scene_cbs(pack)
    world, hud, rest = pick_cbs(cbs, world_hash)
    closed, cam = camera_closed_forms(blk)
    print('frame %d  blk @ 0x%X  eye %s target %s fov %g oy %g roll %d angle 0x%04X' % (
        a.frame, base, tuple(round(x, 4) for x in cam['eye']), tuple(round(x, 4) for x in cam['target']),
        cam['fov'], cam['oy'], cam['roll'], cam['angle']))
    print('scene CBs in %s: world=%s (identity-CBWorld draws %s) hud=%s x0.1 candidates=%s' % (
        os.path.basename(pack), world, world_hash, hud, rest))
    ctx = dump_u64(CTX_PTR)
    targets = [(CAM_WORLD, 'world', [world] if world else []), (CAM_X01, 'x0.1', rest), (CAM_HUD, 'hud', hud)]
    if a.fn:
        targets = [t for t in targets if t[1] == a.fn]
    report = dict(frame=a.frame, base=base, pack=pack, camera=cam, math=a.math, targets={})
    for fn, name, hashes in targets:
        tag = 'cam_%s_%d_%s' % (name, a.frame, a.math)
        lines, ctx = base_job(blk, base, tag, a.math)
        slots = os.path.join(WORK, tag + '.slots.bin')
        lines += ['maxsteps 200000', 'run %x' % fn, 'dump %x %x %s' % (ctx + CTX_MODE, 0x200, slots)]
        r = run_job(lines, tag)
        print('\n== FUN_%x (%s): %s  [%s]' % (fn, name, r['status'], '; '.join(r['runs'])))
        if not r['runs'] or not r['runs'][0].split(' ', 1)[1].startswith('ok'):
            print('   headless log: %s' % r['log'])
            report['targets'][name] = dict(fn='0x%x' % fn, status=r['status'], runs=r['runs'])
            continue
        s = open(slots, 'rb').read()
        mode = struct.unpack_from('<I', s, 0)[0]
        emuP = np.frombuffer(s[8 + 0xC0:8 + 0x100], np.float32).reshape(4, 4)
        emuV = np.frombuffer(s[8 + 0x80:8 + 0xC0], np.float32).reshape(4, 4)
        cP, cV = closed[fn]
        entry = dict(fn='0x%x' % fn, status=r['status'], runs=r['runs'], final_mode=mode,
                     P=emuP.tolist(), V=emuV.tolist(), vs=[], stubhits=r['stubhits'],
                     uninit=classify_uninit(r['uninit'], base, ctx))
        print('   final matrix mode = %d (expect 1)' % mode)
        print('   P(emu) rows: %s' % ['%.7g' % x for x in emuP.flatten()])
        print('   V(emu) row3: %s' % ['%.7g' % x for x in emuV[3]])
        print('   vs closed form: P max|d| = %.3g  V max|d| = %.3g' % (np.abs(emuP - cP).max(), np.abs(emuV - cV).max()))
        for h in hashes:
            m, n = cbs[h]
            c = cmp_mats(emuP, emuV, m, cP, cV)
            c['hash'], c['draws'] = h, n
            entry['vs'].append(c)
            print('   vs CB %s (%d draws): P %d/16 bit-identical max|d| %.3g | V %d/16 max|d| %.3g | V.P(f32) %d/16 max|d| %.3g'
                  % (h, n, c['P_bits'], c['P_maxabs'], c['V_bits'], c['V_maxabs'], c['VP_bits'], c['VP_maxabs']))
        u = entry['uninit']
        print('   synthesised reads: ctx %s | nullpage(TEB) %d ranges | stack %d | other %s' % (
            ['+0x%x(%d)' % x for x in u['ctx']], len(u['nullpage']), len(u['stack']), ['0x%x(%d)' % x for x in u['other']]))
        if r['stubhits']:
            print('   hooks: %s' % '; '.join(r['stubhits']))
        report['targets'][name] = entry
    if a.json:
        json.dump(report, open(a.json, 'w'), indent=1)
        print('\nwrote %s' % a.json)
    return 0


# ── target 2: the sprite walker ────────────────────────────────────────────────────────────────────────────
def layerz_table():
    t = list(struct.unpack('<8f', dump_bytes(LAYERZ_TABLE, 32))) + LAYERZ_IMM
    return t


def walker_nodes(blk, base):
    """Nodes the walker will submit, in walk order, with their post-walk fields from the dump."""
    out = []
    for nd in S.nodes(blk, base):
        if nd['drawn'] == 0 or nd['cat'] > 4:
            continue
        o = nd['off']
        nd['handle'] = base + o
        nd['fields'] = {k: struct.unpack_from(f, blk, o + off)[0] for k, off, f in NODE_FIELDS}
        nd['cell'] = blk[o + 0x191]
        out.append(nd)
    return out


def quad_counts(nodes, blk, table):
    """Per-node quad count the submit returned, recovered from the post-walk depth chain:
       depth_i = zoom*0.1 + LayerZ[L] + 0.001 * sum(count_j, j<i)   and   LayerZ_post[L] = LayerZ[L] + 0.001*sum(all)."""
    counts, notes = {}, []
    post = struct.unpack_from('<16f', blk, 0x6d08)
    for L in range(16):
        dr = [n for n in nodes if n['layer'] == L]
        if not dr:
            continue
        total = int(round((post[L] - table[L]) / 0.001))
        acc = 0
        for i, n in enumerate(dr):
            if i + 1 < len(dr):
                c = int(round((dr[i + 1]['fields']['depth'] - n['fields']['depth']) / 0.001))
            else:
                c = total - acc
            counts[n['handle']] = c
            acc += c
            if c < 0:
                sys.exit('layer %d node %d: negative quad count %d -- the depth chain of this dump is inconsistent '
                         '(wrong base or torn dump); refusing to synthesise it' % (L, i, c))
        notes.append('layer %d: %d nodes, %d quads (LayerZ %g -> %g)' % (L, len(dr), total, table[L], post[L]))
    return counts, notes


def cmd_walker(a):
    meta, blk, base = frame_state(a.frame, a.cap)
    ctx = dump_u64(CTX_PTR)
    table = layerz_table()
    nodes = walker_nodes(blk, base)
    if not nodes:
        sys.exit('frame %d: no drawn nodes' % a.frame)
    cells = [n for n in nodes if n['cell']]
    counts, notes = quad_counts(nodes, blk, table)
    tag = 'walker_%d_%s_%s' % (a.frame, a.composite, a.math)
    lines, ctx = base_job(blk, base, tag, a.math)
    # pre-walk state the post-walk dump no longer holds (synthesised, see docs/EMU-GATE.md):
    for L in range(16):
        lines.append('set4 %x %x' % (base + 0x6d08 + 4 * L, f32bits(table[L])))     # LayerZ before accumulation
    lines.append('set4 %x 0' % (base + G_OFF + 0x24))                                # per-frame quad total
    # the V.P.Screen composite ctx+0x1f8200 that cat 1..4 nodes walked BEFORE the first fighter project through
    if a.composite in ('cur', 'prev'):
        saved = []
        if a.composite == 'prev':
            for src, dst in ((0x6920, 0x6914), (0x6968, 0x695c)):
                for k in range(3):
                    saved.append((dst + 4 * k, struct.unpack_from('<I', blk, dst + 4 * k)[0]))
                    lines.append('set4 %x %x' % (base + dst + 4 * k, struct.unpack_from('<I', blk, src + 4 * k)[0]))
        lines += ['maxsteps 200000', 'run %x' % CAM_WORLD, 'run %x' % COMPOSITE]
        for off, v in saved:
            lines.append('set4 %x %x' % (base + off, v))
    smap = os.path.join(WORK, tag + '.stubmap.txt')
    open(smap, 'w').write(''.join('%x %x\n' % (h, c) for h, c in counts.items()))
    outblk = os.path.join(WORK, tag + '.blk_out.bin')
    outctx = os.path.join(WORK, tag + '.ctx_out.bin')
    lines += ['stubmap %x FUN_1406129f0 %s' % (SUBMIT, smap),
              'maxsteps %d' % a.maxsteps, 'run %x' % WALKER,
              'dump %x %x %s' % (base, S.BLK_SZ, outblk),
              'dump %x %x %s' % (ctx + CTX_MODE, 0x200, outctx)]
    print('frame %d  blk @ 0x%X  %d drawn nodes (%d with a cell override +0x191)  composite=%s math=%s'
          % (a.frame, base, len(nodes), len(cells), a.composite, a.math))
    for n in notes:
        print('   ' + n)
    r = run_job(lines, tag)
    print('\n== FUN_140620f10: %s  [%s]' % (r['status'], '; '.join(r['runs'])))
    if not os.path.exists(outblk):
        print('   headless log: %s' % r['log'])
        return 1
    out = open(outblk, 'rb').read()
    # per-field comparison
    stats = {k: dict(exact=0, maxabs=0.0, bad=[]) for k, _, _ in NODE_FIELDS}
    for n in nodes:
        o = n['off']
        for k, off, f in NODE_FIELDS:
            got = struct.unpack_from(f, out, o + off)[0]
            exp = n['fields'][k]
            if struct.pack(f, got) == struct.pack(f, exp):
                stats[k]['exact'] += 1
            else:
                d = abs(float(got) - float(exp))
                stats[k]['maxabs'] = max(stats[k]['maxabs'], d)
                stats[k]['bad'].append((n['layer'], n['idx'], n['cat'], exp, got))
    print('\n   field      exact/%d   max|d|   first mismatches (layer,idx,cat,expected,got)' % len(nodes))
    for k, _, _ in NODE_FIELDS:
        s = stats[k]
        print('   %-8s %6d/%d   %-8.3g %s' % (k, s['exact'], len(nodes), s['maxabs'],
                                               '' if not s['bad'] else s['bad'][:3]))
    # whole-block audit: every byte that changed, classified
    expected = set()
    for n in nodes:
        for _, off, f in NODE_FIELDS:
            expected.update(range(n['off'] + off, n['off'] + off + struct.calcsize(f)))
    expected.update(range(0x6d08, 0x6d48))
    expected.update(range(G_OFF + 0x24, G_OFF + 0x28))
    diff = [i for i in range(S.BLK_SZ) if out[i] != blk[i]]
    mstack = [i for i in diff if i < MSTACK_DEPTH * 0x40]                 # push/pop storage = blk+0..0x1000
    unexpected = [i for i in diff if i not in expected and i >= MSTACK_DEPTH * 0x40]
    ranges = []
    for i in unexpected:
        if ranges and i == ranges[-1][1]:
            ranges[-1][1] = i + 1
        else:
            ranges.append([i, i + 1])
    post = struct.unpack_from('<16f', blk, 0x6d08)
    got = struct.unpack_from('<16f', out, 0x6d08)
    print('\n   LayerZ after walk: exact %d/16 (max|d| %.3g); G+0x24 quads: emu %d, dump %d' % (
        sum(1 for x, y in zip(post, got) if x == y), max(abs(x - y) for x, y in zip(post, got)),
        struct.unpack_from('<i', out, G_OFF + 0x24)[0], struct.unpack_from('<i', blk, G_OFF + 0x24)[0]))
    print('   bytes changed in blk: %d (of which %d in the matrix push storage blk+0..0x1000), outside the expected fields: %d %s' % (
        len(diff), len(mstack), len(unexpected), ['0x%X..0x%X' % (x, y) for x, y in ranges[:8]]))
    u = classify_uninit(r['uninit'], base, ctx)
    print('   synthesised reads: ctx %s | nullpage %d | stack %d | other %s' % (
        ['+0x%x(%d)' % x for x in u['ctx']][:12], len(u['nullpage']), len(u['stack']), ['0x%x(%d)' % x for x in u['other']]))
    miss = [h for h in r['stubhits'] if h.startswith('stubmiss')]
    print('   submit stub: %d hits, %d misses' % (len(r['stubhits']) - len(miss), len(miss)))
    if a.json:
        json.dump(dict(frame=a.frame, base=base, composite=a.composite, math=a.math, status=r['status'], runs=r['runs'],
                       nodes=len(nodes), cells=len(cells), notes=notes,
                       fields={k: dict(exact=v['exact'], maxabs=v['maxabs'], bad=v['bad'][:20]) for k, v in stats.items()},
                       unexpected_ranges=ranges, uninit=u, stubmiss=miss), open(a.json, 'w'), indent=1)
        print('   wrote %s' % a.json)
    return 0


# ── target 3: a whole frame on the live TTD images (docs/FRAME-READSET.md) ───────────────────────────────
def cmd_frame(a):
    import emu_frame as F
    R = F.load_run(a.run)
    ftab, fstarts, fsizes, fnames = F.functable(WORK)
    inputs, seats, entry = F.tick_inputs(R)
    kb = F.kb_tables()
    lab = F.Labeler(kb.get('global'), kb.get('field'))
    sh4 = F.sh4_map()
    iat = json.load(open(a.iat)) if a.iat and os.path.exists(a.iat) else {}
    print('run %s  clock %s (after %s)  blk @ 0x%X  ctx @ 0x%X  dcram @ 0x%X  exe 0x%X+0x%X' % (
        a.run, R['clock'], R['clock_after'], R['blk'], R['ctx'], R['dcram'], R['exe'], R['exe_size']))
    print('tick inputs (game_state+0x218..): %s  seat map (+0x258..): %s  sim entry *(gs+0x10) = 0x%x' % (
        ['0x%x' % x for x in inputs], seats, entry))
    targets = ['tick', 'render'] if a.target == 'all' else [a.target]
    report = dict(run=a.run, clock=R['clock'], inputs=inputs, seats=seats, sim_entry='0x%x' % entry, targets={})
    for t in targets:
        runs = []
        for rep in range(a.repeat):
            tag = 'frame_%s_%s_r%d' % (os.path.basename(a.run.rstrip('\\/')), t, rep)
            if a.layerz_reset and t == 'render':
                tag += '_lz'
            lines, trace, outs = F.frame_job(R, t, tag, WORK, a.maxsteps, inputs, ftab, layerz_reset=a.layerz_reset)
            r = run_job(lines, tag)
            hashes = {k: F.sha256(p) for k, p in [('trace', trace)] + list(outs.items()) if os.path.exists(p)}
            extra = r.get('extra', [])
            runs.append(dict(tag=tag, status=r['status'], runs=r['runs'], hashes=hashes, trace=trace, outs=outs,
                             uninit=classify_uninit(r['uninit'], R['blk'], R['ctx']), unknown=r['unknown'][:50],
                             stubhits=r['stubhits'][:40], extra=[e for e in extra if not e.startswith('mem ')],
                             wall=r['wall'], log=r['log']))
            print('\n== %s: %s  [%s]  wall %.0fs' % (tag, r['status'], '; '.join(r['runs']), r['wall']))
            for e in runs[-1]['extra'][:30]:
                print('   ' + e)
            for h in r['stubhits'][:12]:
                print('   ' + h)
        entry_t = dict(runs=runs)
        entry_t['deterministic'] = all(x['hashes'] == runs[0]['hashes'] for x in runs) if len(runs) > 1 else None
        print('   determinism (%d runs): %s  hashes %s' % (len(runs), entry_t['deterministic'], runs[0]['hashes']))
        if os.path.exists(runs[0]['trace']):
            an = F.analyze(runs[0]['trace'], R, fstarts, fsizes, fnames, lab, sh4, iat)
            entry_t['analysis'] = an
            print('   trace: %d records %s; calls %d (%d distinct); extcalls %s; callother %d' % (
                an['records'], an['by_kind'], an['calls']['total'], an['calls']['distinct'], an['extcalls'], an['callother']))
            for rn, rg in an['regions'].items():
                if rn == 'other':
                    print('   region other: reads %d writes %d addrs %s' % (rg['reads'], rg['writes'], ['0x%x' % x for x in rg['addrs'][:12]]))
                else:
                    print('   region %-7s reads %8d (%7d B, %4d ranges)  writes %8d (%7d B, %4d ranges)' % (
                        rn, rg['reads'], rg['read_bytes'], len(rg['read_ranges']), rg['writes'], rg['write_bytes'], len(rg['write_ranges'])))
            print('   blk read groups: %s' % {k: len(v) for k, v in an['blk_read_groups'].items()})
            print('   blk write groups: %s' % {k: len(v) for k, v in an['blk_write_groups'].items()})
        if os.path.exists(runs[0]['outs']['blk']):
            if t == 'render':
                g = F.gate_render(R, runs[0]['outs']['blk'])
                entry_t['gate'] = g
                print('   GATE render: %d/%d node fields exact on %d drawn nodes; blk bytes changed %d; clock %d -> %d' % (
                    g['total_exact'], g['total_fields'], g['nodes'], g['blk_bytes_changed'], g['clock_pre'], g['clock_out']))
                for k, v in g['fields'].items():
                    if v['bad']:
                        print('      %s: %d bad %s' % (k, len(v['bad']), v['bad'][:3]))
            elif t == 'chain':
                g = F.gate_chain(R, runs[0]['outs']['blkA'], runs[0]['outs']['blk'])
                entry_t['gate'] = g
                print('   GATE chain (tick -> reset LayerZ/G+0x24 -> dispatcher): %d/%d node fields identical on %d drawn nodes; blk bytes differing %d; quads %d vs %d; clock %d/%d' % (
                    g['total_exact'], g['total_fields'], g['nodes'], g['blk_bytes_changed'], g['quads_A'], g['quads_B'], g['clock_A'], g['clock_B']))
                for k, v in g['fields'].items():
                    if v['bad']:
                        print('      %s: %d bad %s' % (k, len(v['bad']), v['bad'][:3]))
                print('   LayerZ A %s' % [round(x, 3) for x in g['layerz_A']])
                print('   LayerZ B %s' % [round(x, 3) for x in g['layerz_B']])
            else:
                g = F.gate_tick(R, runs[0]['outs']['blk'], lab)
                entry_t['gate'] = g
                print('   GATE tick: clock %d -> %d (delta %d); blk bytes changed %d; pre->post diff %s; changed outside pre->post diff: %s' % (
                    g['clock_pre'], g['clock_out'], g['clock_delta'], g['changed_bytes'], g.get('pre_post_diff_bytes'), g.get('changed_outside_prepost_diff')))
                print('   changed groups: %s' % {k: len(v) for k, v in g['changed_groups'].items()})
                for v in g.get('violations', [])[:20]:
                    print('      violation %s' % (v,))
        report['targets'][t] = entry_t
    if a.json:
        json.dump(report, open(a.json, 'w'), indent=1, default=str)
        print('\nwrote %s' % a.json)
    return 0


def cmd_raw(a):
    lines = [ln.rstrip('\n') for ln in open(a.job) if not ln.startswith('out ')]
    r = run_job(lines, 'raw_' + os.path.splitext(os.path.basename(a.job))[0])
    print(r['status']); print('\n'.join(r['runs'])); print('\n'.join(r['stubhits']))
    for x in r['uninit']:
        print('uninit 0x%x %d' % x)
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('camera'); c.add_argument('frame', type=int); c.add_argument('--fn', choices=['world', 'x0.1', 'hud'])
    w = sub.add_parser('walker'); w.add_argument('frame', type=int)
    w.add_argument('--composite', default='cur', choices=['cur', 'prev', 'none'],
                   help='what ctx+0x1f8200 holds when the walk starts (the dump does not carry ctx)')
    w.add_argument('--maxsteps', type=int, default=20000000)
    r = sub.add_parser('raw'); r.add_argument('job')
    f = sub.add_parser('frame', help='whole-frame run on the live TTD images (emu_frame.py)')
    f.add_argument('--run', required=True, help='d3dcap/ttd/runs/<ts> (with pre/ and post/)')
    f.add_argument('--target', default='all', choices=['tick', 'render', 'sim', 'chain', 'all'])
    f.add_argument('--repeat', type=int, default=2, help='runs per target (determinism gate)')
    f.add_argument('--maxsteps', type=int, default=60000000)
    f.add_argument('--iat', default=None, help='json {target hex: dll!name} for naming external calls')
    f.add_argument('--json', default=None)
    f.add_argument('--layerz-reset', action='store_true', help='render: reset blk+0x6D08.. to the init constants first (idempotence gate on a post-walk dump)')
    for p in (c, w):
        p.add_argument('--cap', default=DEF_CAP)
        p.add_argument('--pack', default=None)
        p.add_argument('--math', default='sse2', choices=['sse2', 'hook'],
                       help='sse2: force the UCRT non-FMA path (DAT_142eefbd8=0); hook: Java Math for tanf/atanf/sinf/cosf')
        p.add_argument('--json', default=None)
    a = ap.parse_args()
    return {'camera': cmd_camera, 'walker': cmd_walker, 'raw': cmd_raw, 'frame': cmd_frame}[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main())
