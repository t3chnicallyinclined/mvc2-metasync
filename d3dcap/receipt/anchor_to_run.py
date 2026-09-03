"""anchor_to_run.py -- build a receipt run directory from a TAPE's battle-frame anchor (agent 0.3.47+) plus the static
images of a dump_live.py run of the SAME process instance (exe_image, dcram, ctx; pointers agree because the anchor and the
dump were taken from one boot -- the meta's blk/ctx/dcram must equal the tape's battle_anchor_* fields).

  python anchor_to_run.py <tape.json.gz> <dump_run_dir> <out_run_dir>

Anchor layout (reader.rs 0.3.47 battle_anchor_enc): [blk 0x33B18][game_state page 0x1000 @exe+0xAC6D40][exe page 0x400
@exe+0x2EDF300][ctx texture-slot table 0x319C @ctx+0x1E0030]. The out dir mirrors the dump layout with blk/blk2/game_state
replaced by the anchor's, the exe page and ctx slot table patched in, and meta.clock_value = the anchor frame."""
import sys, os, json, gzip, base64, shutil, struct
BLK, GSP, EXP, CTS = 0x33B18, 0x1000, 0x400, 0x319C
GS_PAGE_OFF, EXE_PAGE_OFF, CTX_SLOT_OFF = 0xAC6D40, 0x2EDF300, 0x1E0030
tape, src, out = sys.argv[1:4]
d = json.loads(gzip.open(tape, 'rb').read() if tape.endswith('.gz') else open(tape, 'rb').read())
raw = gzip.decompress(base64.b64decode(d['battle_anchor']))
assert len(raw) == BLK + GSP + EXP + CTS, len(raw)
blk, gsp, exp, cts = raw[:BLK], raw[BLK:BLK + GSP], raw[BLK + GSP:BLK + GSP + EXP], raw[BLK + GSP + EXP:]
pre = os.path.join(src, 'pre') if os.path.isdir(os.path.join(src, 'pre')) else src
meta = json.load(open(os.path.join(pre, 'meta.json')))
for k in ('blk', 'ctx', 'dcram'):
    assert int(meta[k], 16) == d['battle_anchor_' + k], (k, meta[k], hex(d['battle_anchor_' + k]))
odir = os.path.join(out, 'pre') if pre != src else out
os.makedirs(odir, exist_ok=True)
for f in os.listdir(pre):
    if f not in ('blk.bin', 'blk2.bin', 'game_state.bin', 'exe_image.bin', 'ctx.bin', 'meta.json'):
        shutil.copy2(os.path.join(pre, f), os.path.join(odir, f))
open(os.path.join(odir, 'blk.bin'), 'wb').write(blk)
b2 = open(os.path.join(pre, 'blk2.bin'), 'rb').read()
open(os.path.join(odir, 'blk2.bin'), 'wb').write(blk + b2[BLK:])
open(os.path.join(odir, 'game_state.bin'), 'wb').write(gsp)
exe = bytearray(open(os.path.join(pre, 'exe_image.bin'), 'rb').read()); exe[EXE_PAGE_OFF:EXE_PAGE_OFF + EXP] = exp
open(os.path.join(odir, 'exe_image.bin'), 'wb').write(exe)
ctx = bytearray(open(os.path.join(pre, 'ctx.bin'), 'rb').read()); ctx[CTX_SLOT_OFF:CTX_SLOT_OFF + CTS] = cts
open(os.path.join(odir, 'ctx.bin'), 'wb').write(ctx)
clk = struct.unpack_from('<I', blk, 0x3CC8)[0]
meta['clock_value'] = clk; meta['anchor_source'] = os.path.basename(tape); meta['anchor_frame_field'] = d['battle_anchor_frame']
json.dump(meta, open(os.path.join(odir, 'meta.json'), 'w'), indent=1)
diff_exe = sum(1 for i in range(EXP) if exp[i] != open(os.path.join(pre, 'exe_image.bin'), 'rb').read()[EXE_PAGE_OFF:EXE_PAGE_OFF + EXP][i])
print('run written:', odir, '| anchor blk clock', clk, '(tape field %d)' % d['battle_anchor_frame'], '| exe page bytes differing from the dump:', diff_exe)
