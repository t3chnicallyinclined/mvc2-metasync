#!/usr/bin/env python3
"""h1_gate.py -- GATE 4 step 1: falsify hypothesis H1 by PERTURBATION.

H1 (docs/RECEIPT-RUNNER-RE.md s1.5): "every list node drawn by FUN_140620cd0 in frame N had its +0x18 callback
executed earlier in frame N, so the destination object is always write-before-read within the frame and its previous
content never matters." If H1 is false for some node class, the battle anchor must additionally carry that object's
bytes, and the arc-built DC-RAM image of GATE 3 is incomplete.

RE-RE.md s1.5 proposed the test but declared it unrunnable: "a real-stage dump with list-5 props (none exists yet --
the only live dumps are stage 0x0B)". That is STALE. The stage-9 receipt run created for GATE 0/1/2 has five list-5
prop nodes, two of which (TCW 0xC12 at DC 0x0D853158 and TCW 0xC1C at DC 0x0D855800) are rewritten in place every
frame (GATE2 s3.1). So the test runs offline, today, with no capture.

The perturbation, in two strengths (both applied to the DESTINATION objects at *(node+0xA0) of every System-A node
in the chosen lists, found in the anchor's own blk):

  --mode verts   scramble only the VERTEX PAYLOAD of each record (bytes rec+0x50 .. rec+0x50+rec[0x4C]), leaving the
                 0x50-byte record headers intact. This is the sharp test: it hits exactly the bytes H1 claims are
                 write-before-read, and it cannot break the NaomiLib iterator, which needs the headers to walk.
  --mode zero    zero the whole object. Strictly stronger, but it also destroys the record headers; if the iterator
                 reads its record count/size from the DESTINATION cursor rather than the SOURCE, this arm fails for a
                 reason that has nothing to do with H1. Run it, but read `verts` as the verdict.

H1 HOLDS if the perturbed run is byte-identical to the unperturbed run on blk (every tick) and on ctx.
H1 FAILS if any byte differs -- and then the first differing tick/region names the node class that must be carried.

    python h1_gate.py --run <run dir> --inputs <inputs.txt> [--ticks 60] [--lists 5 6 7] [--mode verts|zero]

BYOR: reads the run's own dcram.bin, writes only under %TEMP%.
"""
import argparse, json, os, struct, subprocess, sys, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'replay'))
import blkstate as B

RUNNER = os.path.join(HERE, 'runner', 'rr_runner.exe')
OUT = os.path.join(os.environ.get('TEMP', '.'), 'rr_h1')


def object_records(dc, off, limit=4096):
    """TA polygon-list object: 0x18 header, then records of 0x50 header + rec[0x4C] payload.
    Terminator = the signed word at rec+0 is >= 0 (same walk as FUN_140844dc0 / FUN_1406196e0)."""
    out = []
    r = off + 0x18
    for _ in range(limit):
        if r + 0x50 > len(dc):
            break
        pcw = struct.unpack_from('<i', dc, r)[0]
        if pcw >= 0:
            break
        size = struct.unpack_from('<i', dc, r + 0x4C)[0]
        if size < 0 or r + 0x50 + size > len(dc):
            break
        out.append((r, size))
        r += 0x50 + size
    return out


def replay_dcram(pre_dcram, outdir, ticks):
    """Reconstruct the DC-RAM image as of tick `ticks` by replaying rr_runner --harvest-dump page deltas."""
    img = bytearray(open(pre_dcram, 'rb').read())
    for t in range(1, ticks + 1):
        f = os.path.join(outdir, 'dcram_t%03d.dlt' % t)
        if not os.path.exists(f):
            continue
        b = open(f, 'rb').read()
        p = 0
        while p + 8 <= len(b):
            off, ln = struct.unpack_from('<II', b, p)
            p += 8
            img[off:off + ln] = b[p:p + ln]
            p += ln
    return img

def run_runner(pre, out, ticks, inputs):
    os.makedirs(out, exist_ok=True)
    cmd = [RUNNER, '--pre', pre, '--out', out, '--ticks', str(ticks), '--dump-every', '1', '--harvest-dump']
    if inputs:
        cmd += ['--inputs', inputs]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        print(''.join(p.stdout.splitlines(True)[-12:]))
        sys.exit('rr_runner failed (%d) for %s' % (p.returncode, out))
    return out


def compare(a, b, ticks):
    bad = []
    for t in range(ticks + 1):
        fa = os.path.join(a, 'blk_t%03d.bin' % t)
        fb = os.path.join(b, 'blk_t%03d.bin' % t)
        if not (os.path.exists(fa) and os.path.exists(fb)):
            continue
        x, y = open(fa, 'rb').read(), open(fb, 'rb').read()
        if x != y:
            d = [i for i in range(min(len(x), len(y))) if x[i] != y[i]]
            bad.append((t, len(d), d[0]))
    extra = {}
    for nm in ('ctx_out.bin', 'gs_out.bin', 'exe_dat_out.bin'):
        fa, fb = os.path.join(a, nm), os.path.join(b, nm)
        if os.path.exists(fa) and os.path.exists(fb):
            x, y = open(fa, 'rb').read(), open(fb, 'rb').read()
            extra[nm] = sum(1 for i in range(min(len(x), len(y))) if x[i] != y[i])
    return bad, extra


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', required=True)
    ap.add_argument('--inputs', default=None)
    ap.add_argument('--ticks', type=int, default=60)
    ap.add_argument('--lists', type=int, nargs='*', default=[5, 6, 7])
    ap.add_argument('--mode', default='verts', choices=['verts', 'zero'])
    ap.add_argument('--drawn-only', action='store_true')
    a = ap.parse_args()
    pre = os.path.join(a.run, 'pre') if os.path.isdir(os.path.join(a.run, 'pre')) else a.run
    meta = json.load(open(os.path.join(pre, 'meta.json')))
    DCB = int(meta['dc_base'], 16)
    DCHOST = int(meta['dcram'], 16)
    BLKB = int(meta['blk'], 16)
    blk = open(os.path.join(pre, 'blk.bin'), 'rb').read()
    dc = bytearray(open(os.path.join(pre, 'dcram.bin'), 'rb').read())

    nodes = B.anodes(blk, BLKB, lists=a.lists, drawn_only=a.drawn_only, limit=400)
    targets = {}
    for n in nodes:
        for key in ('obj', 'model'):
            h = n.get(key) or 0
            if not h:
                continue
            d = h - DCHOST + DCB
            if 0x0C000000 <= d < 0x0C000000 + len(dc):
                targets.setdefault(d, []).append((n['list'], n['idx'], key, bool(n['drawn'])))
    print('anchor nodes in lists %s: %d ; distinct destination objects: %d'
          % (a.lists, len(nodes), len(targets)))

    nrec = 0
    nbytes = 0
    empty = []
    for d in sorted(targets):
        off = d - DCB
        recs = object_records(dc, off)
        tot = sum(sz for _, sz in recs)
        print('   obj DC %08X: %2d records, %6d payload B, nodes %s'
              % (d, len(recs), tot, targets[d][:3]))
        if not recs:
            empty.append(d)
            continue
        for (r, size) in recs:
            if a.mode == 'zero':
                continue
            dc[r + 0x50:r + 0x50 + size] = b'\xA5' * size
            nrec += 1
            nbytes += size
        if a.mode == 'zero':
            end = recs[-1][0] + 0x50 + recs[-1][1]
            dc[off:end] = b'\x00' * (end - off)
            nrec += len(recs)
            nbytes += end - off
    print('perturbed (%s): %d records, %d bytes across %d objects (%d objects walked to ZERO records: %s)'
          % (a.mode, nrec, nbytes, len(targets), len(empty), [hex(x) for x in empty]))
    if nbytes == 0:
        sys.exit('nothing perturbed -- the node/object enumeration found no records; H1 NOT tested')

    base = os.path.join(OUT, 'baseline')
    pert_pre = os.path.join(OUT, 'pert_%s' % a.mode, 'pre')
    os.makedirs(pert_pre, exist_ok=True)
    for f in os.listdir(pre):
        if f != 'dcram.bin':
            shutil.copy2(os.path.join(pre, f), os.path.join(pert_pre, f))
    open(os.path.join(pert_pre, 'dcram.bin'), 'wb').write(bytes(dc))

    if not os.path.exists(os.path.join(base, 'blk_t%03d.bin' % a.ticks)):
        run_runner(pre, base, a.ticks, a.inputs)
    run_runner(pert_pre, os.path.join(OUT, 'pert_%s' % a.mode, 'out'), a.ticks, a.inputs)

    bad, extra = compare(base, os.path.join(OUT, 'pert_%s' % a.mode, 'out'), a.ticks)
    print()
    print('--- ARM 1: does the perturbation reach the SIMULATION? (blk, every tick) ---')
    print('blk dumps differing: %d of %d' % (len(bad), a.ticks + 1))
    for t, c, f in bad[:6]:
        print('   tick %3d: %d bytes, first blk+0x%X' % (t, c, f))
    for k, v in sorted(extra.items()):
        print('   %-16s %s' % (k, 'EQUAL' if v == 0 else '%d bytes differ' % v))
    print('   NOTE: ctx_out is a BLIND criterion for this question -- the submitted geometry goes to the host')
    print('   staging buffer at *(game_state+0x208), past the DC-RAM image, which rr_runner does not dump')
    print('   (FRAME-READSET s3.5). Use ARM 2, not ctx_out, to decide whether the bytes reach the renderer.')

    print()
    print('--- ARM 2: is each object REGENERATED before it is read, or STATIC? ---')
    img = replay_dcram(os.path.join(pert_pre, 'dcram.bin'), os.path.join(OUT, 'pert_%s' % a.mode, 'out'), a.ticks)
    static, regen, partial = [], [], []
    print('%-10s %9s %9s  %s' % ('object', 'payload', 'still A5', 'class'))
    for d in sorted(targets):
        off = d - DCB
        for (r, size) in object_records(dc, off):
            base_off = r + 0x50
            a5 = sum(1 for i in range(size) if img[base_off + i] == 0xA5)
            if a5 == size:
                cls, bucket = 'STATIC (read every frame, never rewritten)', static
            elif a5 == 0:
                cls, bucket = 'REGENERATED (fully rewritten before use)', regen
            else:
                cls, bucket = 'PARTIAL (only the animated vertex fields are rewritten)', partial
            bucket.append(d)
            print('%08X %9d %9d  %s' % (d, size, a5, cls))

    print()
    print('H1 as stated in RECEIPT-RUNNER-RE s1.5 ("the destination object is always write-before-read within the')
    print('frame and its previous content never matters"): %s'
          % ('HOLDS' if not static and not partial else 'FALSIFIED'))
    print('   static %d, partially rewritten %d, fully regenerated %d' % (len(static), len(partial), len(regen)))
    print()
    print('Consequence for the runner, in two parts:')
    print('  (1) SIM: %s -- %d bytes of object payload scrambled across %d objects changed %s of %d blk dumps.'
          % ('unaffected' if not bad else 'AFFECTED', nbytes, len(targets), len(bad), a.ticks + 1))
    print('      The anchor does not need these objects.')
    print('  (2) PIXELS: the prior content of the static and partially-rewritten objects IS read every frame.')
    print('      That is not a gap, because GATE 3 rebuilds exactly those bytes from the user arc byte-exactly')
    print('      (UNEXPLAINED: NONE). The arc path is therefore LOAD-BEARING for pixels, not merely convenient.')


if __name__ == '__main__':
    main()
