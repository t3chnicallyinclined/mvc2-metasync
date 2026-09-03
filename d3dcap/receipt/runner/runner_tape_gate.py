#!/usr/bin/env python3
"""runner_tape_gate.py -- THE MASTER GATE of the receipt runner (GATE 2; docs/RECEIPT-RUNNER-GATE2.md,
WORKSTREAM-RECEIPT-RUNNER.md s4 step 2, RECEIPT-RUNNER-RENDER.md s2.3-2.4): the v5 TAPE harvested from the NATIVE RUNNER's
memory must equal the LIVE AGENT's tape for the same frames, column by column and section by section, after the documented
live-only noise classes are excluded.

    python runner_tape_gate.py --run <run dir> --live <live tape.json.gz> [--ticks 300] [--out <dir>] [--json <file>]
                               [--skip-runner] [--skip-emit] [--rr-tape <rr-tape.exe>]

Pipeline (each step reusable on its own):
  1. inputs   tick k consumes live row (anchor_clock + k).seat_in  (row N's inputs PRODUCED frame N: receipt_gate --input-shift 1)
  2. runner   rr_runner.exe --harvest-dump: per tick blk + game_state page + exe page + changed DC-RAM pages (Gate 1 runner)
  3. emit     rr-tape.exe (RetroReceipts-agent: rr_agent::harvest over rr_agent::runner::RunnerView) -> runner_tape.json.gz
              = the live agent's OWN harvest + encoders (one implementation) run over the runner's memory
  4. compare  per section on the clock intersection [anchor, anchor+ticks]:
       rows     every GS_SCHEMA column, array columns per element, f32 by value (both sides serialise the same f32)
       nodes    count, order, every record field (kind slot cat sort layer face owner drawn sid pal(resolved 32 B) flash glow
                is_effect blend atimer zx zy effect_key fsx fsy depth gfx1 gfx2 angle hotx hoty owner_off)
       anodes   count, order, list flags matrix colour alpha model(normalised to a DC address) obj(content hash)
       aobjs    window-scoped: the objects in-window nodes reference, both directions
       palrows  48 x 32 B + 48 flags per frame
       pals     window-scoped sets (every row an in-window node or palrow references)
       envelope stage_id p1_team p2_team costume assist local_pn build_id seat_map schema/strides
     Noise classes (RENDER s2.3) a difference may be attributed to -- anything else is UNEXPLAINED and fails the gate:
       P  sampling phase: the live agent reads at the clock edge while the walker FUN_140620f10 may still be writing screen
          placement; a live value equal to the runner's PREVIOUS frame, or any walker field of a frame that is provably
          MID-WALK (some node still previous-frame while the runner moved), is P
       T  torn/held list: the live draw list is a stub/partial of the runner's (fewer nodes, a prefix by sid)
       R  rollback last-write-wins: only if the live tape reports rollbacks > 0 (this pair: 0)
       C  caps: ANODES_CAP_PER_FRAME 96 / OBJS_CAP_PER_FRAME 64 / object bytes 128 KB: the live side is truncated
       K  host pointers: anodes.model, nodes.gfx1/gfx2, pal pointer -- compared after normalising to DC addresses
       L  LUT lag: a consumer rule, not a tape byte (palrows carry the staged rows on both sides) -- never needed here
     Two more, found by this gate (RECEIPT-RUNNER-GATE2.md s3):
       A  0.3.44 object cache: harvest_anodes reuses an object's bytes while its first 0x68 B (headers) match, so an object
          whose VERTICES the frame regenerates (animated stage props, effect u/v; RECEIPT-RUNNER-RE s1.2) ships its
          FIRST-SIGHTING bytes on each side, and the two first sightings differ. Attributed only when the two objects have
          the same length, every record header equal, and differ in vertex payload fields alone.
       F  the runner forces the GGPO seat map {0,1,-1,-1} (DETERMINISM-CONTRACT C2); the live offline tape reports the
          shell's value. An envelope field, never a frame byte.
     Prints exact/total per column/section and the FIRST divergence with its field and both values.

RE METHOD (docs/RE-METHOD.md) step 4: a numeric gate over CONFIRMED pairs; no offset is derived here (the harvest is the
agent's; the runner's addresses are Gate 1's). All inputs are game-derived and live outside the repo (runs/, %TEMP%).
"""
import argparse, base64, collections, gzip, hashlib, json, os, struct, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, 'rr_runner.exe')
AGENT = r'C:\Users\trist\projects\RetroReceipts-agent\agent'
RR_TAPE = os.path.join(AGENT, 'target', 'release', 'rr-tape.exe')
OUT = os.path.join(os.environ.get('TEMP', '.'), 'rrcap_runner')

WALKER_COLS = {'facing', 'drawn', 'sid', 'atimer', 'sx', 'sy', 'zx', 'zy', 'flash', 'glow', 'layer', 'eyeX', 'eyeY', 'zoom',
               'cam_state', 'look', 'fov', 'yoff', 'roll', 'deck', 'blackout', 'bg_mode', 'bg_col', 'fade_mode', 'fade_col', 'bg_gate'}
NODE_FIELDS = ('kind', 'slot', 'cat', 'sort', 'layer', 'face', 'owner', 'drawn', 'sid', 'pal', 'flash', 'glow', 'is_effect', 'blend',
               'atimer', 'zx', 'zy', 'effect_key', 'fsx', 'fsy', 'depth', 'gfx1', 'gfx2', 'angle', 'hotx', 'hoty', 'owner_off')
WALK_NODE_FIELDS = ('fsx', 'fsy', 'zx', 'zy', 'face', 'depth', 'angle', 'hotx', 'hoty', 'layer', 'drawn', 'atimer', 'sid', 'flash', 'glow')
ANODE_FIELDS = ('list', 'flags', 'matrix', 'colour', 'alpha', 'model', 'obj')
CLASS_LEGEND = ('P sampling phase / mid-walk, T torn list, R rollback, C caps, K host pointer, L LUT lag, '
                'A 0.3.44 object cache first-sighting bytes, F runner-forced seat map')


# ------------------------------------------------------------------------------------------------ tape decoding
def load_tape(path):
    raw = open(path, 'rb').read()
    return json.loads(gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw)


def schema_cols(schema):
    s = schema.strip()
    s = s[1:] if s.startswith('[') else s
    s = s[:-1] if s.endswith(']') else s
    cols = [c.strip() for c in s.split(',')]
    return [(c[:c.index('[')] if '[' in c else c) for c in cols]


def b64gz(t, key):
    return gzip.decompress(base64.b64decode(t[key])) if t.get(key) else b''


def decode_pals(t):
    pb = b64gz(t, 'pals')
    return [pb[i * 32:(i + 1) * 32] for i in range(len(pb) // 32)]


def decode_nodes(t):
    nb = b64gz(t, 'nodes'); st = int(t.get('nodes_stride', 44)); pals = decode_pals(t)
    off = 0; out = {}
    while off + 6 <= len(nb):
        fr, n = struct.unpack_from('<IH', nb, off); off += 6; rows = []
        for _ in range(n):
            v = struct.unpack_from('<BBBbBBBBHHHBBBBHHHfffII', nb, off)
            d = dict(zip(NODE_FIELDS[:23], v))
            if st >= 50:
                d['angle'], d['hotx'], d['hoty'] = struct.unpack_from('<Hhh', nb, off + 44)
            if st >= 54:
                d['owner_off'] = struct.unpack_from('<I', nb, off + 50)[0]
            d['pal_bytes'] = pals[d['pal']] if d['pal'] < len(pals) else None
            off += st; rows.append(d)
        out[fr] = rows
    return out


def decode_aobjs(t):
    ab = b64gz(t, 'aobjs')
    if not ab: return []
    n = struct.unpack_from('<H', ab, 0)[0]; off = 2; out = []
    for _ in range(n):
        ln = struct.unpack_from('<I', ab, off)[0]; off += 4; out.append(ab[off:off + ln]); off += ln
    return out


def decode_anodes(t, aobjs):
    ab = b64gz(t, 'anodes'); st = int(t.get('anodes_stride', 96)); off = 0; out = {}
    while off + 6 <= len(ab):
        fr, n = struct.unpack_from('<IH', ab, off); off += 6; rows = []
        for _ in range(n):
            lst, _, _, _, flags = struct.unpack_from('<BBBBI', ab, off)
            matrix = ab[off + 8:off + 72]
            colour = struct.unpack_from('<3f', ab, off + 72)
            obj, _ = struct.unpack_from('<HH', ab, off + 84)
            model = struct.unpack_from('<Q', ab, off + 88)[0]
            alpha = struct.unpack_from('<f', ab, off + 96)[0] if st >= 100 else None
            objh = hashlib.sha256(aobjs[obj]).hexdigest()[:16] if obj != 0xFFFF and obj < len(aobjs) else None
            rows.append(dict(list=lst, flags=flags, matrix=matrix, colour=colour, alpha=alpha, model=model, obj=objh, obj_index=obj))
            off += st
        out[fr] = rows
    return out


def decode_palrows(t):
    rb = b64gz(t, 'palrows'); pals = decode_pals(t); off = 0; out = {}
    while off + 148 <= len(rb):
        fr = struct.unpack_from('<I', rb, off)[0]; idx = struct.unpack_from('<48H', rb, off + 4); flags = rb[off + 100:off + 148]; off += 148
        out[fr] = ([pals[i] if i < len(pals) else None for i in idx], bytes(flags))
    return out


class TapeView:
    def __init__(self, path):
        self.path = path; self.t = load_tape(path)
        self.cols = schema_cols(self.t['schema'])
        self.rows = {r[0]: r for r in self.t['frames']}
        self.nodes = decode_nodes(self.t)
        self.aobjs = decode_aobjs(self.t)
        self.aobj_hashes = {hashlib.sha256(o).hexdigest()[:16]: o for o in self.aobjs}
        self.anodes = decode_anodes(self.t, self.aobjs)
        self.palrows = decode_palrows(self.t)
        self.pals = decode_pals(self.t)
        self.dcram_base = int(self.t.get('battle_anchor_dcram') or 0)


# ------------------------------------------------------------------------------------------------ steps 1-3
def write_inputs(live, clock0, ticks, path):
    ci = live.cols.index('seat_in')
    with open(path, 'w') as f:
        f.write('# tick k consumes live row (%d + k).seat_in (row N inputs PRODUCED frame N; receipt_gate --input-shift 1)\n' % clock0)
        for k in range(1, ticks + 1):
            r = live.rows.get(clock0 + k)
            if r is None: sys.exit('live tape lacks row %d (needed for tick %d)' % (clock0 + k, k))
            f.write('%x %x\n' % (r[ci][0], r[ci][1]))


def run_runner(pre, out, ticks, inputs):
    if not os.path.exists(RUNNER):
        subprocess.run(['cmd.exe', '/c', os.path.join(HERE, 'build.bat')], check=True, cwd=HERE)
    for f in os.listdir(out):
        if f.endswith('.bin') or f.endswith('.dlt'): os.remove(os.path.join(out, f))
    cmd = [RUNNER, '--pre', pre, '--out', out, '--ticks', str(ticks), '--inputs', inputs, '--harvest-dump']
    t0 = time.time(); r = subprocess.run(cmd, capture_output=True, text=True)
    open(os.path.join(out, 'gate_runner_stdout.txt'), 'w').write(r.stdout + r.stderr)
    if r.returncode != 0: sys.exit('runner failed rc=%d:\n%s' % (r.returncode, (r.stdout + r.stderr)[-2000:]))
    return time.time() - t0


def run_emit(pre, out, ticks, rr_tape, tape_out):
    if not os.path.exists(rr_tape):
        subprocess.run(['cargo', 'build', '--release', '--bin', 'rr-tape'], check=True, cwd=AGENT)
    cmd = [rr_tape, '--pre', pre, '--ticks', out, '--n', str(ticks), '-o', tape_out]
    t0 = time.time(); r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0: sys.exit('rr-tape failed rc=%d:\n%s' % (r.returncode, r.stdout + r.stderr))
    return json.loads(r.stdout.strip().splitlines()[-1]), time.time() - t0


# ------------------------------------------------------------------------------------------------ step 4: compare
class Section:
    def __init__(self, name):
        self.name = name; self.exact = collections.Counter(); self.total = collections.Counter()
        self.classed = collections.Counter(); self.first = {}; self.unexplained = []
    def rec(self, key, ok, cls=None, detail=None):
        self.total[key] += 1
        if ok: self.exact[key] += 1; return
        if cls: self.classed[(key, cls)] += 1
        else: self.unexplained.append(detail)
        self.first.setdefault(key, detail)


def compare_rows(live, run, frames, S):
    """every column; a differing walker column whose live value == the runner's PREVIOUS frame is class P."""
    for f in frames:
        lr, rr = live.rows[f], run.rows[f]
        rprev = run.rows.get(f - 1)
        for ci, name in enumerate(live.cols):
            lv, rv = lr[ci], rr[ci]
            if isinstance(lv, list):
                for i, (a, b) in enumerate(zip(lv, rv)):
                    key = '%s[%d]' % (name, i)
                    ok = a == b
                    cls = 'P' if (not ok and rprev is not None and name in WALKER_COLS and a == rprev[ci][i]) else None
                    S.rec(key, ok, cls, dict(frame=f, field=key, live=a, runner=b, runner_prev=(rprev[ci][i] if rprev else None), cls=cls))
            else:
                ok = lv == rv
                cls = 'P' if (not ok and rprev is not None and name in WALKER_COLS and lv == rprev[ci]) else None
                S.rec(name, ok, cls, dict(frame=f, field=name, live=lv, runner=rv, runner_prev=(rprev[ci] if rprev else None), cls=cls))


def norm_ptr(v, base_live, base_run):
    """K: host pointers into the DC-RAM image -> image-relative (Delta = 0 makes the raw values equal anyway)."""
    if base_live and base_run and base_live != base_run:
        return v - base_live if base_live <= v < base_live + 0x2000000 else v
    return v


def compare_nodes(live, run, frames, S):
    for f in frames:
        ln, rn = live.nodes.get(f, []), run.nodes.get(f, [])
        rprev = run.nodes.get(f - 1, [])
        same_count = len(ln) == len(rn)
        cls = None
        if not same_count:
            sig = lambda d: (d['kind'], d['slot'], d['sid'])
            if len(ln) < len(rn) and [sig(d) for d in ln] == [sig(d) for d in rn[:len(ln)]]: cls = 'T'
            elif len(ln) == 64 and len(rn) > 64: cls = 'C'
        S.rec('count', same_count, cls, dict(frame=f, field='count', live=len(ln), runner=len(rn), cls=cls))
        # P at FRAME level: a frame is MID-WALK when at least one live node still carries the runner's PREVIOUS value of a
        # placement field while the runner moved; every walker-field difference in that frame is then P (a node caught
        # between the walker's writes shows a value that is neither frame's final one -- same read, same walk).
        midwalk = any(i < len(rprev) and a['sid'] == rprev[i]['sid'] and a['kind'] == rprev[i]['kind'] and
                      any(a[k] != b[k] and a[k] == rprev[i][k] for k in ('fsx', 'fsy'))
                      for i, (a, b) in enumerate(zip(ln, rn)))
        for i, (a, b) in enumerate(zip(ln, rn)):
            for k in NODE_FIELDS:
                if k not in a or k not in b: continue
                av, bv = (a['pal_bytes'], b['pal_bytes']) if k == 'pal' else (a[k], b[k])
                ok = av == bv
                c2 = None
                if not ok:
                    if k in ('gfx1', 'gfx2'):
                        c2 = 'K' if norm_ptr(av, live.dcram_base, run.dcram_base) == norm_ptr(bv, live.dcram_base, run.dcram_base) else None
                    elif k in WALK_NODE_FIELDS and (midwalk or (i < len(rprev) and rprev[i].get(k) == av and rprev[i]['sid'] == a['sid'] and rprev[i]['kind'] == a['kind'])):
                        c2 = 'P'
                S.rec(k, ok, c2, dict(frame=f, node=i, field=k, live=(av.hex() if isinstance(av, bytes) else av), runner=(bv.hex() if isinstance(bv, bytes) else bv),
                                      runner_prev=(rprev[i].get(k) if i < len(rprev) and k != 'pal' else None), midwalk=midwalk, cls=c2))


def dc_addr(model, dcram_base, dc_base=0x0C000000):
    if dcram_base and dcram_base <= model < dcram_base + 0x2000000: return model - dcram_base + dc_base
    return model


def obj_diff_class(lo, ro):
    """Class A test (see the module doc): same length, every record header equal, vertex payload fields alone differ."""
    if lo is None or ro is None or len(lo) != len(ro) or lo[:0x18] != ro[:0x18]: return None, 'shape differs'
    o = 0x18; fields = collections.Counter(); recs = []
    while o + 0x50 <= len(lo):
        size = struct.unpack_from('<i', lo, o + 0x4C)[0]
        if struct.unpack_from('<i', lo, o)[0] >= 0 or size < 0 or o + 0x50 + size > len(lo): break
        if lo[o:o + 0x50] != ro[o:o + 0x50]: return None, 'record header differs @0x%x' % o
        tcw = struct.unpack_from('<I', lo, o + 12)[0]
        hit = False
        for k in range(o + 0x50, o + 0x50 + size):
            if lo[k] != ro[k]:
                p = k - o - 0x50
                fields['lead' if p < 8 else 'vert.' + ('x', 'y', 'z', 'nx', 'ny', 'nz', 'u', 'v')[((p - 8) % 32) // 4]] += 1
                hit = True
        if hit: recs.append('tcw 0x%X' % tcw)
        o += 0x50 + size
    if lo[o:] != ro[o:]: return None, 'tail differs'
    if not fields: return None, 'no differing bytes (?)'
    return 'A', 'vertex-only diff %s in %s' % (dict(fields), ','.join(sorted(set(recs))))


def compare_anodes(live, run, frames, S):
    for f in frames:
        la, ra = live.anodes.get(f, []), run.anodes.get(f, [])
        same = len(la) == len(ra)
        cls = 'C' if (not same and len(la) == 96 and len(ra) > 96) else None
        S.rec('count', same, cls, dict(frame=f, field='count', live=len(la), runner=len(ra), cls=cls))
        for i, (a, b) in enumerate(zip(la, ra)):
            for k in ANODE_FIELDS:
                if k == 'model':
                    av, bv = dc_addr(a[k], live.dcram_base), dc_addr(b[k], run.dcram_base)
                    S.rec('model(DC)', av == bv, None, dict(frame=f, node=i, field='model', live=hex(a[k]), runner=hex(b[k]), cls=None))
                    continue
                av, bv = a[k], b[k]
                ok = av == bv
                c2 = det = None
                if not ok and k == 'obj':
                    c2, det = obj_diff_class(live.aobj_hashes.get(av), run.aobj_hashes.get(bv))
                S.rec(k, ok, c2, dict(frame=f, node=i, field=k, live=(av.hex() if isinstance(av, bytes) else av), runner=(bv.hex() if isinstance(bv, bytes) else bv), detail=det, cls=c2))


def window_objs(tv, frames):
    s = {}
    for f in frames:
        for i, a in enumerate(tv.anodes.get(f, [])):
            if a['obj']: s.setdefault(a['obj'], (f, i))
    return s


def compare_aobjs(live, run, frames, S):
    """window-scoped: only the objects an in-window node references (the live table covers the whole match)."""
    L, R = window_objs(live, frames), window_objs(run, frames)
    for h, (f, i) in L.items():
        ok = h in R
        cls = det = None
        if not ok:
            rb = run.anodes.get(f, [])
            if i < len(rb) and rb[i]['obj']: cls, det = obj_diff_class(live.aobj_hashes[h], run.aobj_hashes.get(rb[i]['obj']))
        S.rec('live_in_runner', ok, cls, dict(field='aobj', live=h, runner=None, first_use=(f, i), len=len(live.aobj_hashes[h]), detail=det, cls=cls))
    for h, (f, i) in R.items():
        ok = h in L
        cls = det = None
        if not ok:
            lb = live.anodes.get(f, [])
            if i < len(lb) and lb[i]['obj']: cls, det = obj_diff_class(live.aobj_hashes.get(lb[i]['obj']), run.aobj_hashes[h])
        S.rec('runner_in_live', ok, cls, dict(field='aobj', live=None, runner=h, first_use=(f, i), len=len(run.aobj_hashes[h]), detail=det, cls=cls))
    S.rec('objects(both)', True, None, dict(field='both', live=len(L), runner=len(R), both=len(set(L) & set(R))))


def compare_palrows(live, run, frames, S):
    for f in frames:
        lp, rp = live.palrows.get(f), run.palrows.get(f)
        if lp is None or rp is None:
            S.rec('present', False, None, dict(frame=f, field='present', live=lp is not None, runner=rp is not None, cls=None)); continue
        for i in range(48):
            ok = lp[0][i] == rp[0][i]
            S.rec('row', ok, None, dict(frame=f, row=i, field='row', live=(lp[0][i].hex() if lp[0][i] else None), runner=(rp[0][i].hex() if rp[0][i] else None), cls=None))
        S.rec('flags', lp[1] == rp[1], None, dict(frame=f, field='flags', live=lp[1].hex(), runner=rp[1].hex(), cls=None))


def compare_envelope(live, run, frames, S):
    for k in ('stage_id', 'p1_team', 'p2_team', 'costume', 'assist', 'local_pn', 'build_id', 'tape_ver', 'nodes_stride', 'anodes_stride', 'schema'):
        S.rec(k, live.t.get(k) == run.t.get(k), None, dict(field=k, live=live.t.get(k), runner=run.t.get(k), cls=None))
    sm_ok = live.t.get('seat_map') == run.t.get('seat_map')
    S.rec('seat_map', sm_ok, 'F' if (not sm_ok and run.t.get('seat_map') == [0, 1, -1, -1]) else None,
          dict(field='seat_map', live=live.t.get('seat_map'), runner=run.t.get('seat_map'), cls='F'))
    def used(tv):
        u = set()
        for f in frames:
            for d in tv.nodes.get(f, []):
                if d['pal_bytes'] is not None: u.add(d['pal_bytes'])
            pr = tv.palrows.get(f)
            if pr: u |= {r for r in pr[0] if r is not None}
        return u
    lp, rp = used(live), used(run)
    S.rec('pals(window sets)', lp == rp, None, dict(field='pals', live=len(lp), runner=len(rp), live_only=[p.hex() for p in (lp - rp)][:3], runner_only=[p.hex() for p in (rp - lp)][:3], cls=None))


def report(S, only_diffs=False):
    keys = sorted(S.total)
    allok = True; lines = []
    for k in keys:
        e, t = S.exact[k], S.total[k]
        cl = {c: n for (kk, c), n in S.classed.items() if kk == k}
        rest = t - e - sum(cl.values())
        if rest: allok = False
        if only_diffs and e == t: continue
        tag = '' if e == t else ('  classed %s' % cl if cl else '') + ('  UNEXPLAINED %d' % rest if rest else '')
        fd = S.first.get(k)
        fdt = ('  first: ' + json.dumps({kk: vv for kk, vv in fd.items() if kk != 'cls'}, default=str)[:230]) if fd and e != t else ''
        lines.append('   %-22s %7d / %7d%s%s' % (k, e, t, tag, fdt))
    exact_all = all(S.exact[k] == S.total[k] for k in keys)
    print('== %s: %s' % (S.name, 'EXACT' if exact_all else ('attributed' if allok else 'FAIL')))
    for l in lines: print(l)
    return allok, exact_all


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', required=True)
    ap.add_argument('--live', required=True)
    ap.add_argument('--ticks', type=int, default=300)
    ap.add_argument('--out', default=None)
    ap.add_argument('--rr-tape', default=RR_TAPE)
    ap.add_argument('--skip-runner', action='store_true')
    ap.add_argument('--skip-emit', action='store_true')
    ap.add_argument('--only-diffs', action='store_true', help='print only the non-exact columns')
    ap.add_argument('--json', default=None)
    a = ap.parse_args()
    pre = os.path.join(a.run, 'pre') if os.path.isdir(os.path.join(a.run, 'pre')) else a.run
    meta = json.load(open(os.path.join(pre, 'meta.json')))
    clock0 = int(meta['clock_value'])
    out = a.out or os.path.join(OUT, 'gate2_%s_%d' % (os.path.basename(a.run.rstrip('\\/')), a.ticks))
    os.makedirs(out, exist_ok=True)
    live = TapeView(a.live)
    print('live tape %s: %d rows %d..%d, %d node frames, %d anode frames, %d aobjs, %d palrow frames, rollbacks=%s, agent %s' % (
        os.path.basename(a.live), len(live.rows), min(live.rows), max(live.rows), len(live.nodes), len(live.anodes), len(live.aobjs), len(live.palrows), live.t.get('rollbacks'), live.t.get('ver')))
    if clock0 not in live.rows: sys.exit('the live tape has no row at the anchor clock %d' % clock0)
    inputs = os.path.join(out, 'inputs.txt'); write_inputs(live, clock0, a.ticks, inputs)
    if not a.skip_runner:
        wall = run_runner(pre, out, a.ticks, inputs); print('runner: %d ticks in %.1fs -> %s' % (a.ticks, wall, out))
    summ = json.load(open(os.path.join(out, 'summary.json')))
    print('runner DC-RAM write set over %d ticks: %s pages (%s B) [summary.json dcram_delta_per_tick]' % (a.ticks, summ.get('dcram_delta_pages'), summ.get('dcram_delta_bytes')))
    tape_out = os.path.join(out, 'runner_tape.json.gz')
    if not a.skip_emit:
        st, wall = run_emit(pre, out, a.ticks, a.rr_tape, tape_out); print('rr-tape: %s (%.1fs)' % (json.dumps(st), wall))
    run = TapeView(tape_out)
    frames = sorted(set(live.rows) & set(run.rows) & set(range(clock0, clock0 + a.ticks + 1)))
    print('comparing %d frames %d..%d (live rows %d, runner rows %d in window)' % (len(frames), frames[0], frames[-1],
          sum(1 for f in range(clock0, clock0 + a.ticks + 1) if f in live.rows), sum(1 for f in range(clock0, clock0 + a.ticks + 1) if f in run.rows)))
    secs = []
    S = Section('rows'); compare_rows(live, run, frames, S); secs.append(S)
    S = Section('nodes'); compare_nodes(live, run, frames, S); secs.append(S)
    S = Section('anodes'); compare_anodes(live, run, frames, S); secs.append(S)
    S = Section('aobjs'); compare_aobjs(live, run, frames, S); secs.append(S)
    S = Section('palrows'); compare_palrows(live, run, frames, S); secs.append(S)
    S = Section('envelope'); compare_envelope(live, run, frames, S); secs.append(S)
    ok_all, exact_all = True, True
    res = {}
    for S in secs:
        ok, ex = report(S, a.only_diffs); ok_all &= ok; exact_all &= ex
        res[S.name] = dict(exact={k: S.exact[k] for k in S.total}, total=dict(S.total), classed={'%s|%s' % k: v for k, v in S.classed.items()},
                           first={k: v for k, v in S.first.items()}, unexplained=S.unexplained[:20])
    tot = collections.Counter()
    for S in secs:
        for (k, c), n in S.classed.items(): tot[c] += n
    print('attributed differences by class: %s   (%s)' % (dict(tot), CLASS_LEGEND))
    print('GATE 2 (runner tape == live tape per column after P/T/R/C/K/L/A/F): %s%s' % ('PASS' if ok_all else 'FAIL', '' if exact_all else ' (with attributed live-only differences)'))
    if a.json:
        json.dump(dict(run=a.run, live=a.live, ticks=a.ticks, clock0=clock0, frames=[frames[0], frames[-1], len(frames)], out=out,
                       runner_summary={k: summ.get(k) for k in ('dcram_delta_pages', 'dcram_delta_bytes', 'dcram_delta_per_tick', 'ticks', 'clock_start', 'clock_end')},
                       classes=dict(tot), sections=res), open(a.json, 'w'), indent=1, default=str)
    return 0 if ok_all else 1


if __name__ == '__main__':
    sys.exit(main())
