#!/usr/bin/env python3
"""emu_frame.py -- the `frame` job of emu_gate.py: run a WHOLE engine frame (sim tick, render dispatcher) in
Ghidra's p-code emulator on the live TTD images and produce the per-frame READ / WRITE SET.

    python emu_gate.py frame --run C:\\...\\d3dcap\\ttd\\runs\\20260903-000941 --target tick     # FUN_140118950
    python emu_gate.py frame --run ... --target render                                      # FUN_140620960
    python emu_gate.py frame --run ... --target sim                                         # FUN_140607d60 (offline entry)
    python emu_gate.py frame --run ... --target all --repeat 2 --json out.json              # + determinism gate

RE METHOD step 4 (docs/RE-METHOD.md). Memory = the live images of ONE process (runs/<ts>/pre: exe_image.bin at
0x140000000, dcram.bin, ctx.bin, blk.bin, blk2.bin at the addresses meta.json records) -- nothing is relocated,
DAT_142edf560 etc. are whatever the live image holds. Every ram access is logged by EmuGate.java (`trace`):
kind / pc / addr / size, ordered. This module builds the job, runs it, and turns the stream into the read set:
per function (containment in re_map/steam_funcs.jsonl), per region (blk offset with the field / global name,
DC-RAM address with the data region, exe RVA with the global name, ctx offset, stack), reads and writes.

Gates (docs/FRAME-READSET.md): (i) determinism = two runs give byte-identical trace streams and dumps;
(ii) render run reproduces the walker fields of every drawn node of the dump; (iii) tick advances blk+0x3CC8 by 1
and every blk byte it changes lies in the pre->post diff; (iv) capgate consecutive-frame gate (data permitting).
"""
import hashlib
import json
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 're_map'))
import blkstate as S          # noqa: E402
import blkmap                 # noqa: E402

FRAME_TICK, FRAME_SIM_ENTRY, FRAME_DISPATCHER = 0x140118950, 0x140607d60, 0x140620960
GS_ADDR, GGPO_STATE = 0x140ac6d40, 0x142d10b90
# The scratch stack and the input array must not overlap ANY live image (the first smoke run put the stack at
# 0x10000000, inside dcram 0xFBC1000..0x11BC1000, and the game's stack traffic landed in PL slot data). frame_job()
# asserts the hole against every image range of the run.
INPUT_SCRATCH = 0x30000000
STACK_BASE, STACK_SIZE = 0x31000000, 0x400000
CRT_FMA_FLAG = 0x142eefbd8
HEAP_BASE, HEAP_SIZE = 0x32000000, 0x1000000
# UCRT import slots (call [rip+slot] sites read in the live image with capstone, 2026-09-03): the sim tick calls the
# game's sprintf wrapper FUN_14003a4c0 -> __stdio_common_vsprintf -> __acrt_getptd_noexit, which needs a working
# allocator; with every import stubbed to 0 the CRT recursed forever (_calloc_base -> __doserrno -> getptd -> calloc).
CRT_SLOTS = {'RtlAllocateHeap': (0x1408db240, 'extalloc', 'R8'), 'RtlReAllocateHeap': (0x1408db140, 'extalloc', 'R9'),
             'HeapFree': (0x1408db238, 'extret', '1'), 'FlsSetValue': (0x1408db218, 'extret', '1')}
TRACE_DT = np.dtype([('kind', 'u1'), ('pc', '<u8'), ('addr', '<u8'), ('size', '<u4')])
KIND = {0: 'read', 1: 'write', 2: 'call', 3: 'extcall', 4: 'callother', 5: 'mark'}
REGION_NAMES = ['exe', 'blk', 'blk2', 'ctx', 'dcram', 'stack', 'inputs', 'nullpage', 'other']
NODE_FIELDS = [('sx', 0x124, '<f'), ('sy', 0x128, '<f'), ('depth', 0x12C, '<f'), ('scx', 0x130, '<f'),
               ('scy', 0x134, '<f'), ('angle', 0x148, '<I'), ('z150', 0x150, '<I'), ('facing', 0x154, '<i'),
               ('hotx', 0x178, '<H'), ('hoty', 0x17A, '<H')]

# exe globals with a known meaning (docs/STEAM-CODE-MAP.md, EMU-GATE.md, TTD-FRAME-TRACE.md, this run)
EXE_GLOBALS = {
    0x140acd3a0: 'PTR_DAT_140acd3a0 (game_state ptr)', 0x140acd3a8: 'DAT_140acd3a8 (session ptr)',
    0x142edf560: 'DAT_142edf560 (blk)', 0x142edf580: 'DAT_142edf580 (G = blk+0x3CB8)',
    0x142edf590: 'PTR_DAT_142edf590 (effects POL)', 0x142edf598: 'PTR_DAT_142edf598 (HUD POL)',
    0x142edf628: 'DAT_142edf628 (entity list)', 0x142ef0ab0: 'DAT_142ef0ab0 (ctx)', 0x142ef0ab8: 'DAT_142ef0ab8 (cur matrix)',
    0x142eefbd8: 'DAT_142eefbd8 (CRT FMA flag)', 0x142d10b90: 'DAT_142d10b90 (GGPO frame counter / save root)',
    0x142e10b98: 'DAT_142e10b98 (GGPO session)', 0x140a4f780: 'DAT_140a4f780 (12-entry input bit table)',
    0x140a6d888: 'DAT_140a6d888 (LayerZ init table)', 0x142ec6780: 'PTR_FUN_142ec6780 (render table)',
    0x142ec4370: 'DAT_142ec4370 (render table count)', 0x140ab2080: 'DAT_140ab2080 (Screen matrix)',
    0x140ab20c0: 'DAT_140ab20c0 (identity)', 0x142ef0ac0: 'DAT_142ef0ac0 (sin table)', 0x142f30ac0: 'DAT_142f30ac0 (cos table)',
}
GS_FIELDS = {0x10: 'sim entry fn ptr (FUN_140607d60)', 0x1b0: 'blk ptr', 0x1b8: 'blk size', 0x218: 'pad word seat 0',
             0x21c: 'pad word seat 1', 0x220: 'pad word seat 2', 0x224: 'pad word seat 3', 0x228: 'prev pad seat 0',
             0x22c: 'prev pad seat 1', 0x230: 'prev pad seat 2', 0x234: 'prev pad seat 3', 0x258: 'player0 -> seat',
             0x25c: 'player1 -> seat', 0x260: 'player2 -> seat', 0x264: 'player3 -> seat', 0x768: 'frame stamp (from FUN_140118dd0)',
             0x76c: 'rollback counter', 0x798: 'tick flag (set 1 by FUN_140118950)', 0x7c: 'local player', 0x82c: 'side swap'}
# DC-RAM data map (docs/TEXTURE-BANKS-GHIDRA.md, seeds 04/31; per-slot PL regions from the fighter pointers of this run)
# Per-slot PL regions measured on runs/20260903-000941 pre blk (fighter pointers +0x198..+0x208 into dcram): each slot
# owns 0x150000 B from 0x0C420000 in the order 0,2,4,1,3,5 (GFX1 at +0x0, GFX2/palette/cell table/templates inside).
DC_REGIONS = [
    (0x0C000000, 0x0C010000, 'DC low / vectors'), (0x0C010000, 0x0C420000, 'DC program image + static tables (1ST_READ)'),
    (0x0C420000, 0x0C570000, 'PL slot 0 (P1 point) data'), (0x0C570000, 0x0C6C0000, 'PL slot 2 (P1 assist 1) data'),
    (0x0C6C0000, 0x0C810000, 'PL slot 4 (P1 assist 2) data'), (0x0C810000, 0x0C960000, 'PL slot 1 (P2 point) data'),
    (0x0C960000, 0x0CAB0000, 'PL slot 3 (P2 assist 1) data'), (0x0CAB0000, 0x0CC00000, 'PL slot 5 (P2 assist 2) data'),
    (0x0CC00000, 0x0CC60000, 'effects VQ texture pixels (0x0CC00000 + loc)'), (0x0CC60000, 0x0CD00000, 'RAM texture scratch pages (0x0CC60000/0x0CC80000/0x0CCF0000)'),
    (0x0CD00000, 0x0CDA0000, 'UNKNOWN 0x0CD00000..'), (0x0CDA0000, 0x0CDD0000, 'effects TEX rebase (0x0CDA0000, case 0x18)'),
    (0x0CDD0000, 0x0CE00000, 'part-decode VRAM window'), (0x0CE00000, 0x0CE30000, 'boot list 0x0CE1D000 / UNKNOWN'),
    (0x0CE30000, 0x0CE60000, 'char-programming overlay'), (0x0CE60000, 0x0CE80000, 'Texture_Decompress_Buffer (0x0CE60C00 dyn list)'),
    (0x0CE80000, 0x0CEA0000, 'DM00 directory/pool'), (0x0CEA0000, 0x0CED0000, 'stage POL base (SH4 0x0CEA0000)'),
    (0x0CED0000, 0x0D000000, 'Effect Poly bank (SH4)'), (0x0D000000, 0x0D082000, 'effects bank 0xC50 POL/TEX (AFS 799/800)'),
    (0x0D082000, 0x0D0C6000, 'HUD bank 0xC90 POL/TEX (AFS 835/836)'), (0x0D0C6000, 0x0D25C000, 'common bank 0x810 (AFS 837/838)'),
    (0x0D25C000, 0x0D82D000, 'select / vs / result banks'), (0x0D82D000, 0x0D85D000, 'stage POL (AFS 801+2*id)'),
    (0x0D85D000, 0x0E000000, 'stage TEX (AFS 802+2*id) ..'),
]


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def load_run(run):
    pre = os.path.join(run, 'pre')
    m = json.load(open(os.path.join(pre, 'meta.json')))
    hx = lambda k: int(m[k], 16)
    R = dict(run=run, pre=pre, post=os.path.join(run, 'post'), meta=m, blk=hx('blk'), blk_size=hx('blk_size'),
             blk2=hx('blk2'), blk2_size=hx('blk2_size'), ctx=hx('ctx'), ctx_size=hx('ctx_size'), dcram=hx('dcram'),
             dcram_size=hx('dcram_size'), dc_base=hx('dc_base'), exe=hx('exe_base'), exe_size=hx('exe_size'),
             clock=m['clock_value'], clock_after=m.get('clock_value_after'))
    R['blk_bytes'] = open(os.path.join(pre, 'blk.bin'), 'rb').read()
    pm = os.path.join(R['post'], 'meta.json')
    if os.path.exists(pm):
        R['post_meta'] = json.load(open(pm))
        R['post_blk'] = open(os.path.join(R['post'], 'blk.bin'), 'rb').read()
    return R


def functable(work):
    """sorted function starts / sizes / names from re_map/steam_funcs.jsonl (also written for EmuGate.java)."""
    rows = []
    for ln in open(os.path.join(HERE, 're_map', 'steam_funcs.jsonl')):
        d = json.loads(ln)
        rows.append((d['addr'], d['size'], d['name']))
    rows.sort()
    path = os.path.join(work, 'functable.txt')
    if not os.path.exists(path):
        with open(path, 'w') as f:
            for a, s, n in rows:
                f.write('%x %x %s\n' % (a, s, n))
    return path, np.array([r[0] for r in rows], np.uint64), np.array([r[1] for r in rows], np.uint64), [r[2] for r in rows]


def sh4_map():
    """steam addr -> (sh4 label, confidence, role) from docs/steam_sh4_map.csv (seed 30)."""
    import csv
    out = {}
    p = os.path.join(HERE, '..', '..', 'docs', 'steam_sh4_map.csv')
    if not os.path.exists(p):
        return out
    for r in csv.DictReader(open(p, encoding='utf-8')):
        out[int(r['steam_addr'], 16)] = (r['sh4_label'], r['confidence'], r.get('sh4_role', ''))
    return out


def tick_inputs(R):
    """The raw seat words the live image holds at game_state+0x218/+0x21C (exe_image.bin; CONFIRMED site of the pad
    words by the decompile of FUN_140118950 and FUN_140039de0 stores at 0x14003A33B/0x14003A35F)."""
    exe = open(os.path.join(R['pre'], 'exe_image.bin'), 'rb')
    exe.seek(GS_ADDR + 0x218 - R['exe'])
    w = struct.unpack('<4I', exe.read(16))
    exe.seek(GS_ADDR + 0x258 - R['exe'])
    seats = struct.unpack('<4i', exe.read(16))
    exe.seek(GS_ADDR + 0x10 - R['exe'])
    entry = struct.unpack('<Q', exe.read(8))[0]
    return list(w), list(seats), entry


LAYERZ_TABLE, LAYERZ_IMM = 0x140a6d888, [10.0, 11.0, 12.0, 13.0, 30.0, 31.0, 32.0, 33.0]


def layerz_lines(R):
    exe = open(os.path.join(R['pre'], 'exe_image.bin'), 'rb')
    exe.seek(LAYERZ_TABLE - R['exe'])
    vals = list(struct.unpack('<8f', exe.read(32))) + LAYERZ_IMM
    return ['set4 %x %x' % (R['blk'] + 0x6d08 + 4 * L, struct.unpack('<I', struct.pack('<f', v))[0]) for L, v in enumerate(vals)]


def frame_job(R, target, tag, work, maxsteps, inputs, ftab, layerz_reset=False):
    pre = R['pre']
    trace = os.path.join(work, tag + '.trace.bin')
    outs = dict(blk=os.path.join(work, tag + '.blk_out.bin'), gs=os.path.join(work, tag + '.gs_out.bin'),
                ggpo=os.path.join(work, tag + '.ggpo_out.bin'), ctx=os.path.join(work, tag + '.ctx_out.bin'),
                beyond=os.path.join(work, tag + '.beyond_dcram_out.bin'),     # host memory right after the DC-RAM image (no image covers it)
                tiletab=os.path.join(work, tag + '.tiletab_out.bin'))         # DC 0x0CE60000..+0x3000: per-frame tile descriptor table (FUN_140614210)
    images = [(R['exe'], R['exe_size']), (R['dcram'], R['dcram_size']), (R['ctx'], R['ctx_size']),
              (R['blk'], R['blk_size']), (R['blk2'], R['blk2_size'])]
    for lo, n in [(STACK_BASE, STACK_SIZE), (INPUT_SCRATCH, 0x1000), (HEAP_BASE, HEAP_SIZE)]:
        for ilo, isz in images:
            assert lo + n <= ilo or lo >= ilo + isz, 'scratch region 0x%x..0x%x overlaps a live image 0x%x..0x%x' % (lo, lo + n, ilo, ilo + isz)
    lines = ['# frame job %s target=%s' % (tag, target),
             'note run=%s target=%s clock=%s' % (R['run'], target, R['clock']),
             'stack %x %x' % (STACK_BASE, STACK_SIZE),
             'mem %x %s' % (R['exe'], os.path.join(pre, 'exe_image.bin')),
             'mem %x %s' % (R['dcram'], os.path.join(pre, 'dcram.bin')),
             'mem %x %s' % (R['ctx'], os.path.join(pre, 'ctx.bin')),
             'mem %x %s' % (R['blk'], os.path.join(pre, 'blk.bin')),
             'mem %x %s' % (R['blk2'], os.path.join(pre, 'blk2.bin')),
             'set4 %x 0' % CRT_FMA_FLAG,
             'image %x %x' % (R['exe'], R['exe'] + R['exe_size']),
             'functable %s' % ftab, 'extstub on', 'callother skip', 'heap %x %x' % (HEAP_BASE, HEAP_SIZE)]
    exe = open(os.path.join(pre, 'exe_image.bin'), 'rb')
    for nm, (slot, cmd, arg) in CRT_SLOTS.items():
        exe.seek(slot - R['exe'])
        tgt = struct.unpack('<Q', exe.read(8))[0]
        lines.append('%s %x %s' % (cmd, tgt, arg))
        lines.append('note %s = *0x%x = 0x%x (%s %s)' % (nm, slot, tgt, cmd, arg))
    lines += [
             'trace %s' % trace, 'maxsteps %d' % maxsteps]
    if target == 'tick':
        lines.append('fill %x 1000' % INPUT_SCRATCH)
        lines += ['set4 %x %x' % (INPUT_SCRATCH + 4 * k, v) for k, v in enumerate(inputs)]
        lines += ['reg RCX %x' % GGPO_STATE, 'reg RDX %x' % INPUT_SCRATCH, 'reg R8 0', 'run %x' % FRAME_TICK]
    elif target == 'sim':
        lines += ['run %x' % FRAME_SIM_ENTRY]
    elif target == 'chain':
        # tick (frame N -> N+1, including its own render pass) -> dump A -> reset the two per-frame accumulators the
        # dispatcher does not reset itself (LayerZ, G+0x24; synthesised exactly as EMU-GATE s2) -> dispatcher again ->
        # dump B. Gate: the walker fields of every drawn node in B == A (idempotence on a self-consistent state: no
        # torn snapshot involved, the tick built the tile table and the node state itself).
        outs['blkA'] = os.path.join(work, tag + '.blkA_out.bin')
        lines.append('fill %x 1000' % INPUT_SCRATCH)
        lines += ['set4 %x %x' % (INPUT_SCRATCH + 4 * k, v) for k, v in enumerate(inputs)]
        lines += ['reg RCX %x' % GGPO_STATE, 'reg RDX %x' % INPUT_SCRATCH, 'reg R8 0', 'run %x' % FRAME_TICK,
                  'dump %x %x %s' % (R['blk'], R['blk_size'], outs['blkA'])]
        lines += ['note chain: LayerZ + G+0x24 reset (synthesised) then FUN_140620960 again']
        lines += layerz_lines(R) + ['set4 %x 0' % (R['blk'] + 0x3CB8 + 0x24), 'run %x' % FRAME_DISPATCHER]
    elif target == 'render':
        if layerz_reset:
            lines += ['note LayerZ blk+0x6D08..0x6D44 reset to the FUN_140613390 constants (synthesised, as EMU-GATE s2)']
            lines += layerz_lines(R)
        lines += ['run %x' % FRAME_DISPATCHER]
    else:
        sys.exit('target must be tick, sim, render or chain')
    outs['exe_misc'] = os.path.join(work, tag + '.exe_misc_out.bin')      # 0x142ec4000..+0x3000 render table area
    outs['exe_dat'] = os.path.join(work, tag + '.exe_dat_out.bin')        # 0x142edf300..+0x300 DAT_142edf3xx/5xx
    outs['exe_str'] = os.path.join(work, tag + '.exe_str_out.bin')        # 0x142eed900..+0x300 sprintf target
    lines += ['dump 142ec4000 3000 %s' % outs['exe_misc'], 'dump 142edf300 300 %s' % outs['exe_dat'],
              'dump 142eed900 300 %s' % outs['exe_str']]
    lines += ['dump %x %x %s' % (R['blk'], R['blk_size'], outs['blk']),
              'dump %x 1000 %s' % (GS_ADDR, outs['gs']),
              'dump %x 10 %s' % (GGPO_STATE, outs['ggpo']),
              'dump %x %x %s' % (R['ctx'], R['ctx_size'], outs['ctx']),
              'dump %x %x %s' % (R['dcram'] + R['dcram_size'], 0x100000, outs['beyond']),
              'dump %x 3000 %s' % (R['dcram'] + 0x0CE60000 - R['dc_base'], outs['tiletab'])]
    return lines, trace, outs


# ── labelling ──────────────────────────────────────────────────────────────────────────────────────────────
class Labeler:
    def __init__(self, kb_globals=None, kb_fields=None):
        self.globals_by_steam = {}
        self.globals_by_dc = {}
        for g in kb_globals or []:
            so, addr = g.get('steam_off'), g.get('addr')
            name = g['id'].split(':', 1)[1]
            if so and so.startswith('0x') and not so.startswith('ctx'):
                try:
                    self.globals_by_steam[int(so, 16)] = name
                except ValueError:
                    pass
            if addr and addr.startswith('0x8C') or (addr and addr.startswith('0x8c')):
                try:
                    self.globals_by_dc[int(addr, 16)] = name
                except ValueError:
                    pass
        self.fields = {}
        for f in kb_fields or []:
            off = f.get('offset')
            if not off:
                continue
            try:
                o = int(off.replace('+', ''), 16)
            except ValueError:
                continue
            self.fields.setdefault(o, f['name'])

    def field_name(self, steam_rem):
        """Steam fighter/node field offset -> DC offset + re_kb field name (char_struct, marvelous2 pl_mem)."""
        dc = blkmap.steam_field_to_dc(steam_rem)
        nm = self.fields.get(dc)
        return '+0x%X (DC +0x%X%s)' % (steam_rem, dc, ' ' + nm if nm else '')

    def blk(self, off):
        """blk offset -> (group, label)."""
        if off < 0x1000:
            return 'matrix_stack', 'nl_matrix_push_storage slot %d' % (off // 0x40)
        if off < 0x3C66:      # outside the block map: 0x38-B records read by FUN_140613390 (render-list init); DC UNKNOWN
            n, rem = divmod(off - 0x1000, 0x38)
            return 'unmapped_1000', 'blk+0x1000 rec[%d]+0x%X (DC UNKNOWN)' % (n, rem)
        if 0x3C66 <= off < 0x3CB8:
            i, rem = divmod(off - 0x3C66, 0x14)
            return 'input_array', 'input[%d]+0x%X (DC 0x%08X)' % (i, rem, blkmap.blk_to_dc(off))
        if 0x3CB8 <= off < 0x3DB8:
            g = off - 0x3CB8
            nm = self.globals_by_steam.get(off) or self.globals_by_dc.get(blkmap.blk_to_dc(off) or -1)
            return 'G_globals', 'G+0x%X (DC 0x%08X)%s' % (g, blkmap.blk_to_dc(off), ' ' + nm if nm else '')
        if 0x3DB8 <= off < 0x6908:
            slot, rem = divmod(off - 0x3DB8, 0x738)
            return 'fighter', 'fighter[*]%s' % self.field_name(rem)
        if 0x6908 <= off < 0x6DD8:
            nm = self.globals_by_steam.get(off)
            if not nm:
                for k, v in self.globals_by_steam.items():
                    if 0 <= off - k < 16 and 0x6908 <= k < 0x6DD8:
                        nm = v + '+%d' % (off - k)
                        break
            dc = blkmap.blk_to_dc(off)
            return 'stage_camera', 'blk+0x%X%s%s' % (off, ' (DC 0x%08X)' % dc if dc else '', ' ' + nm if nm else '')
        if 0x6DD8 <= off < 0x2EDD8:
            n, rem = divmod(off - 0x6DD8, 0x280)
            return 'pool_node', 'node[*]%s' % self.field_name(rem)
        if 0x2EDD8 <= off < 0x2F4D0:
            dc = blkmap.blk_to_dc(off)
            return 'pool_lists', 'pool bookkeeping blk+0x%X (DC 0x%08X)' % (off, dc)
        if 0x2F4D0 <= off < 0x324D0:
            L, rem = divmod(off - 0x2F4D0, 0x300)
            return 'draw_list', 'drawlist[layer %d] slot %d' % (L, rem // 8)
        if 0x324D0 <= off < 0x32500:
            return 'draw_counts', 'drawlist count layer %d' % (off - 0x324D0)
        dc = blkmap.blk_to_dc(off)
        nm = self.globals_by_dc.get(dc) if dc else None
        if not nm and dc:
            for k, v in self.globals_by_dc.items():
                if 0 <= dc - k < 4:
                    nm = v
                    break
        return 'battle_state', 'blk+0x%X (DC 0x%08X)%s' % (off, dc or 0, ' ' + nm if nm else '')

    def dc(self, addr):
        for lo, hi, nm in DC_REGIONS:
            if lo <= addr < hi:
                return nm
        return 'outside map'

    def exe(self, addr):
        if GS_ADDR <= addr < GS_ADDR + 0x1000:
            o = addr - GS_ADDR
            nm = GS_FIELDS.get(o)
            for k, v in GS_FIELDS.items():
                if not nm and 0 <= o - k < 4:
                    nm = v
            return 'game_state', 'game_state+0x%X%s' % (o, ' ' + nm if nm else '')
        if GGPO_STATE <= addr < GGPO_STATE + 0x100004:
            return 'ggpo_save', 'DAT_142d10b90+0x%X (GGPO save region)' % (addr - GGPO_STATE)
        for k, v in EXE_GLOBALS.items():
            if 0 <= addr - k < 8:
                return 'exe_global', v
        return 'exe_global', 'RVA 0x%X' % (addr - 0x140000000)


# ── trace analysis ─────────────────────────────────────────────────────────────────────────────────────────
def ranges_from_mask(mask, base=0):
    d = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1)
    return [(int(base + s), int(e - s)) for s, e in zip(starts, ends)]


def mark_mask(n, addrs, sizes, lo):
    m = np.zeros(n, bool)
    a = addrs - lo
    for sz in np.unique(sizes):
        sel = sizes == sz
        for k in range(int(sz)):
            idx = a[sel] + k
            idx = idx[idx < n]
            m[idx] = True
    return m


def analyze(trace_path, R, fstarts, fsizes, fnames, labeler, sh4, iat_names=None, max_examples=6):
    arr = np.fromfile(trace_path, TRACE_DT)
    kind, pc, addr, size = arr['kind'], arr['pc'], arr['addr'], arr['size'].astype(np.int64)
    res = dict(records=int(len(arr)), by_kind={KIND[k]: int((kind == k).sum()) for k in KIND})
    # function containment
    fi = np.searchsorted(fstarts, pc, side='right') - 1
    fi = np.clip(fi, 0, len(fstarts) - 1)
    inside = (pc >= fstarts[fi]) & (pc < fstarts[fi] + fsizes[fi])
    # regions
    reg = np.full(len(arr), 8, np.uint8)
    bounds = [(0, R['exe'], R['exe'] + R['exe_size']), (1, R['blk'], R['blk'] + R['blk_size']),
              (2, R['blk2'], R['blk2'] + R['blk2_size']), (3, R['ctx'], R['ctx'] + R['ctx_size']),
              (4, R['dcram'], R['dcram'] + R['dcram_size']), (5, STACK_BASE, STACK_BASE + STACK_SIZE),
              (6, INPUT_SCRATCH, INPUT_SCRATCH + 0x1000), (7, 0, 0x10000)]
    for code, lo, hi in bounds:
        reg[(addr >= lo) & (addr < hi) & (reg == 8)] = code
    mem = (kind == 0) | (kind == 1)
    # ordered call sequence (first N) + call counts
    calls = np.flatnonzero(kind == 2)
    cc = {}
    seq = []
    for i in calls:
        f = fi[i]
        name = fnames[f] if inside[i] else 'gap@%x' % pc[i]
        cc[name] = cc.get(name, 0) + 1
        if len(seq) < 400:
            seq.append(name)
    res['calls'] = dict(distinct=len(cc), total=int(len(calls)), counts=cc, first_400=seq)
    # external calls
    ext = {}
    for i in np.flatnonzero(kind == 3):
        t = '%x' % pc[i]
        nm = (iat_names or {}).get('0x' + t, 'target 0x' + t)
        ext[nm] = ext.get(nm, 0) + 1
    res['extcalls'] = ext
    res['callother'] = int((kind == 4).sum())
    # per-region byte masks: reads / writes
    regions = {}
    for code, lo, hi in bounds:
        nm = REGION_NAMES[code]
        n = hi - lo
        if n > (1 << 27):
            continue
        rsel = mem & (reg == code) & (kind == 0)
        wsel = mem & (reg == code) & (kind == 1)
        rm = mark_mask(n, addr[rsel], size[rsel], lo) if rsel.any() else np.zeros(n, bool)
        wm = mark_mask(n, addr[wsel], size[wsel], lo) if wsel.any() else np.zeros(n, bool)
        regions[nm] = dict(reads=int(rsel.sum()), writes=int(wsel.sum()), read_bytes=int(rm.sum()), write_bytes=int(wm.sum()),
                           read_ranges=ranges_from_mask(rm, lo), write_ranges=ranges_from_mask(wm, lo), _rm=rm, _wm=wm)
    other = mem & (reg == 8)
    regions['other'] = dict(reads=int((other & (kind == 0)).sum()), writes=int((other & (kind == 1)).sum()),
                            addrs=sorted(set(int(x) for x in np.unique(addr[other])[:200])))
    res['regions'] = regions
    # per function x region: distinct (addr,size) for reads and writes, with labels
    keyfn = np.where(inside, fi, -1)
    rec = np.rec.fromarrays([keyfn[mem], reg[mem], kind[mem], addr[mem], size[mem]], names='fn,reg,kind,addr,size')
    uniq, counts = np.unique(rec, return_counts=True)
    funcs = {}
    for u, c in zip(uniq, counts):
        name = fnames[u.fn] if u.fn >= 0 else 'gap'
        d = funcs.setdefault(name, dict(addr='0x%x' % (fstarts[u.fn] if u.fn >= 0 else 0), sh4=None, reads={}, writes={}))
        if u.fn >= 0 and d['sh4'] is None:
            s = sh4.get(int(fstarts[u.fn]))
            d['sh4'] = ('%s (%s)' % (s[0], s[1])) if s else 'unmatched'
        rn = REGION_NAMES[u.reg]
        side = d['reads'] if u.kind == 0 else d['writes']
        lst = side.setdefault(rn, [])
        a = int(u.addr)
        if rn == 'blk':
            grp, lab = labeler.blk(a - R['blk'])
            lst.append(('0x%X' % (a - R['blk']), int(u.size), int(c), lab))
        elif rn == 'dcram':
            dc = a - R['dcram'] + R['dc_base']
            lst.append(('0x%08X' % dc, int(u.size), int(c), labeler.dc(dc)))
        elif rn == 'exe':
            grp, lab = labeler.exe(a)
            lst.append(('0x%x' % a, int(u.size), int(c), lab))
        elif rn == 'ctx':
            lst.append(('ctx+0x%x' % (a - R['ctx']), int(u.size), int(c), ''))
        elif rn == 'stack':
            lst.append(('stack', int(u.size), int(c), ''))
        else:
            lst.append(('0x%x' % a, int(u.size), int(c), ''))
    # collapse stack entries to a count
    for d in funcs.values():
        for side in ('reads', 'writes'):
            if 'stack' in d[side]:
                d[side]['stack'] = dict(accesses=sum(x[2] for x in d[side]['stack']), distinct=len(d[side]['stack']))
    res['functions'] = funcs
    # grouped blk read/write set (by field group)
    def group(mask):
        g = {}
        for off in np.flatnonzero(mask):
            grp, lab = labeler.blk(int(off))
            g.setdefault(grp, set()).add(lab)
        return {k: sorted(v) for k, v in g.items()}
    res['blk_read_groups'] = group(regions['blk']['_rm'])
    res['blk_write_groups'] = group(regions['blk']['_wm'])
    for r in regions.values():
        r.pop('_rm', None)
        r.pop('_wm', None)
    return res


def kb_tables():
    """re_kb global / field tables (SurrealDB :8001); empty if the server is down."""
    import urllib.request
    import base64
    out = {}
    for tbl, q in (('global', 'SELECT id, addr, steam_off, type FROM global;'), ('field', 'SELECT id, name, offset FROM field;')):
        try:
            req = urllib.request.Request('http://127.0.0.1:8001/sql', data=q.encode(), method='POST',
                                         headers={'surreal-ns': 're', 'surreal-db': 'kb', 'Accept': 'application/json',
                                                  'Authorization': 'Basic ' + base64.b64encode(b'root:root').decode()})
            r = json.load(urllib.request.urlopen(req, timeout=5))
            out[tbl] = r[0]['result']
        except Exception as e:      # noqa: BLE001
            print('re_kb %s unavailable: %s' % (tbl, e))
            out[tbl] = []
    return out


# ── gates ──────────────────────────────────────────────────────────────────────────────────────────────────
def gate_render(R, blk_out):
    """(ii) walker fields of every drawn node of the dump vs the emulated render pass (idempotence)."""
    pre = R['blk_bytes']
    out = open(blk_out, 'rb').read()
    nodes = [n for n in S.nodes(pre, R['blk']) if n['drawn'] != 0 and n['cat'] <= 4]
    stats = {k: dict(exact=0, bad=[]) for k, _, _ in NODE_FIELDS}
    for n in nodes:
        o = n['off']
        for k, off, f in NODE_FIELDS:
            a, b = struct.unpack_from(f, out, o + off)[0], struct.unpack_from(f, pre, o + off)[0]
            if struct.pack(f, a) == struct.pack(f, b):
                stats[k]['exact'] += 1
            else:
                stats[k]['bad'].append((n['layer'], n['idx'], n['cat'], b, a))
    diff = [i for i in range(len(pre)) if out[i] != pre[i]]
    return dict(nodes=len(nodes), fields={k: dict(exact=v['exact'], bad=v['bad'][:6]) for k, v in stats.items()},
                total_exact=sum(v['exact'] for v in stats.values()), total_fields=10 * len(nodes),
                blk_bytes_changed=len(diff), changed_ranges=ranges_from_mask(np.isin(np.arange(len(pre)), diff))[:40],
                clock_pre=struct.unpack_from('<I', pre, 0x3CC8)[0], clock_out=struct.unpack_from('<I', out, 0x3CC8)[0])


def gate_chain(R, blkA, blkB):
    """walker fields of every drawn node after the tick (A) vs after a second dispatcher pass on that state (B)."""
    A = open(blkA, 'rb').read()
    B = open(blkB, 'rb').read()
    nodes = [n for n in S.nodes(A, R['blk']) if n['drawn'] != 0 and n['cat'] <= 4]
    stats = {k: dict(exact=0, bad=[]) for k, _, _ in NODE_FIELDS}
    for n in nodes:
        o = n['off']
        for k, off, f in NODE_FIELDS:
            a, b = struct.unpack_from(f, A, o + off)[0], struct.unpack_from(f, B, o + off)[0]
            if struct.pack(f, a) == struct.pack(f, b):
                stats[k]['exact'] += 1
            else:
                stats[k]['bad'].append((n['layer'], n['idx'], n['cat'], a, b))
    Aa, Ba = np.frombuffer(A, np.uint8), np.frombuffer(B, np.uint8)
    diff = Aa != Ba
    return dict(nodes=len(nodes), fields={k: dict(exact=v['exact'], bad=v['bad'][:6]) for k, v in stats.items()},
                total_exact=sum(v['exact'] for v in stats.values()), total_fields=10 * len(nodes),
                blk_bytes_changed=int(diff.sum()), changed_ranges=ranges_from_mask(diff)[:40],
                layerz_A=list(struct.unpack_from('<16f', A, 0x6d08)), layerz_B=list(struct.unpack_from('<16f', B, 0x6d08)),
                quads_A=struct.unpack_from('<i', A, 0x3CB8 + 0x24)[0], quads_B=struct.unpack_from('<i', B, 0x3CB8 + 0x24)[0],
                clock_A=struct.unpack_from('<I', A, 0x3CC8)[0], clock_B=struct.unpack_from('<I', B, 0x3CC8)[0])


def gate_tick(R, blk_out, labeler):
    """(iii) clock +1; every blk byte the tick CHANGES lies inside the pre->post diff."""
    pre = R['blk_bytes']
    out = open(blk_out, 'rb').read()
    post = R.get('post_blk')
    pre_a, out_a = np.frombuffer(pre, np.uint8), np.frombuffer(out, np.uint8)
    changed = pre_a != out_a
    g = dict(clock_pre=int(struct.unpack_from('<I', pre, 0x3CC8)[0]), clock_out=int(struct.unpack_from('<I', out, 0x3CC8)[0]),
             changed_bytes=int(changed.sum()), changed_ranges=ranges_from_mask(changed)[:400])
    g['clock_delta'] = g['clock_out'] - g['clock_pre']
    if post is not None:
        post_a = np.frombuffer(post, np.uint8)
        pdiff = pre_a != post_a
        viol = changed & ~pdiff
        g['post_clock'] = int(struct.unpack_from('<I', post, 0x3CC8)[0])
        g['pre_post_diff_bytes'] = int(pdiff.sum())
        g['changed_outside_prepost_diff'] = int(viol.sum())
        g['violations'] = [(('0x%X' % a), n, labeler.blk(a)[1]) for a, n in ranges_from_mask(viol)[:60]]
    g['changed_groups'] = {}
    for off in np.flatnonzero(changed):
        grp, lab = labeler.blk(int(off))
        g['changed_groups'].setdefault(grp, set()).add(lab)
    g['changed_groups'] = {k: sorted(v) for k, v in g['changed_groups'].items()}
    return g
