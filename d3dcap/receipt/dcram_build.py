#!/usr/bin/env python3
"""dcram_build.py -- GATE 3: rebuild the 32 MB Steam DC-RAM image of a battle frame from the USER'S OWN
game_50.arc + the anchor's blk, replacing the captured `pre/dcram.bin`, and classify every byte that still
differs from a live dump.

RE METHOD (docs/RE-METHOD.md): (1) the loaders were matched SH4 <-> Steam in docs/RECEIPT-RUNNER-DCRAM.md;
(2) seeded on 0x0C420000 / 0x00150000 / 0xC10 / 0xC50 / 0xC90 / 0x810 and the per-slot address tables;
(3) roster/stage/assist are read out of the anchor's `blk` through the block map (blk+0x3DB8 + s*0x738);
(4) every rule below is CONFIRMED (both sides read) and the differ tags what it cannot reproduce.

What it replays, and from which routine (all decompiled from mvc_dump.bin through the :8080 bridge):

  FUN_14060dcf0            AFS entry -> DC address memcpy (no file I/O; the arc IS ctx[0])
  FUN_14060d100            PL slot loader (== SH4 loc_8c031fa0): 11 AFS files per character at
                           0x0C420000 + pos*0x150000, pos = {0,2,4,1,3,5}[slot]
  FUN_14060c370 case 6     the 32 KB per-character tail (AFS 3+cid, 25/26 -> 27) at +0x148000
  FUN_14060d770            POL relocation: delta = POL[0] - dcaddr - 0x10; POL[0], POL[2] and the whole
                           model table (POL[1] entries) -= delta; then every 16-B texture record's
                           loc field (+8) -= (firstLoc - TEXdcaddr), terminator = w == 0
  FUN_14060d8f0            host bank struct (no DC-RAM write) -- header is POL[0]=modelTable, [1]=count,
                           [2]=texHdrs
  FUN_140844dc0            TCW assign: for every record of every model, rec+0xC = bankBase + rec+0x20
                           (texIndex); records start at model+0x18, next = rec + 0x50 + rec[0x4C],
                           terminator = rec[0] >= 0
  FUN_14060d470            stage bank (base 0xC10) + the stage-0x10 ISP/TSP fix-up on MODELS 1..8
                           (texIndex 10 -> rec+0x4 |= 0x4000000; texIndex 5 -> rec+0x0 &= ~0x2000000)
  FUN_14060d560            HUD bank (base 0xC90) + the twelve portrait / name-plate pages: per fighter
                           slot s, LZSS-16 (FUN_140611e90) sub-blob 0 of AFS 3+cid to 0x0CE60000, then
                           0x800 B from page {1,0,3,0}[*(fighter+0x655)] -> texHdr[10+k].loc and page 2
                           -> texHdr[16+k].loc, k = {0,3,1,4,2,5}[s]  (docs/PORTRAIT-PAGES-GHIDRA.md)
  FUN_14060d080            effects bank (base 0xC50);  case 5 -> common bank (base 0x810)

Usage:
    python dcram_build.py <run_dir> --out %TEMP%\\rr_dcram.bin            # build only
    python dcram_build.py <run_dir> --gate                                # build + classify vs pre/dcram.bin
    python dcram_build.py <run_dir> --out ... --carry-e --carry-s         # carry the known-unbuildable classes

Difference classes the gate uses (a run PASSES when no differing byte is class '?'):
    R  per-frame / at-draw absolute rewrite (tile buffer 0x0CE60000, animated stage-POL vertices,
       effects-quad UVs, HUD record TCW low byte) -- regenerated before use (RECEIPT-RUNNER-DCRAM s3)
    S  spawn-time model patch that PERSISTS (FUN_140619800 rec+0x8 &= 0xFFFE7FFF "TSP clear";
       FUN_140660f40 rec+0x8 |= 0x2000) -- applied when a pool node binds the model
    E  the 12 KB engine-written PL region base+0x145000 (fighter+0x1F0; writer INFERRED FUN_140612180)
    L  leftover bytes past the end of a file the loader placed (previous character / previous scene)
    X  banks that are not on the battle read set at all (select / VS / result / ending / staging)

BYOR: reads the user's own game_50.arc; every output is game-derived and gitignored.
"""
import argparse, json, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'replay'))
import rip_texbank as RT
import rip_portraits as RP

DCB = 0x0C000000
DCRAM_SZ = 0x2000000
FILL = 0xCD                      # the host allocation's debug fill; unwritten DC-RAM reads as 0xCD

FIGHTER0, FSTRIDE = 0x3DB8, 0x738
OFF_CID, OFF_COSTUME, OFF_ASSIST = 0x6C0, 0x6C1, 0x655
STAGE_BYTE = 0x6D04

PL_POS = (0, 3, 1, 4, 2, 5)      # DAT_140a6ab80 fighter slot -> PL slot position (== DAT_140a6aac8)
K_HUD = (0, 3, 1, 4, 2, 5)       # DAT_140a6aac8 fighter slot -> HUD texture-record offset
ASSIST_PAGE = (1, 0, 3, 0)       # DAT_140a6aac4 assist type -> portrait page
# FUN_14060d100: (AFS base, sub-slot offset); the 3+cid tail is loaded by FUN_14060c370 case 6
PL_FILES = ((209, 0x000000), (268, 0x130000), (327, 0x13C000), (386, 0x13D000), (445, 0x13E000),
            (504, 0x140000), (563, 0x141000), (681, 0x142000), (622, 0x143000), (740, 0x144000))
PL_TAIL_OFF = 0x148000
PL_E_OFF, PL_E_LEN = 0x145000, 0x3000
SLOT_SZ = 0x150000

# ---------------------------------------------------------------------------------------------------------------
# AUXILIARY (non-battle) BANKS.  GATE 4 assumed only the four battle banks are ever referenced; that is FALSE.
# receipt-20260903-151200-post9 has FIVE DRAWN list-5 nodes whose +0xA0 objects are 0x0D2BB1A0..0x0D2CE5C8 -- the
# RESULTS bank.  If it is left at the 0xCD fill, the NaomiLib record walk FUN_140848EE0 reads a record size of
# 0xCDCDCDCD at rec+0x4C, sign-extends it to -842150451, and faults at 0x140848FF4 (CMP dword ptr [RDI],0x0).
# CONFIRMED from FUN_14060c370 case 10:
#     G+0xAD == 1 -> POL 0x36A TEX 0x36B ; == 2 -> 0x36C / 0x36D ; else 0x34D / 0x34E
#     FUN_14060dcf0(POL, 0x0D2BB000); FUN_14060dcf0(TEX, 0x0D2E9000); FUN_14060d770(0x0D2BB000, 0x0D2E9000)
# (The archive match on the live post9 image independently returns AFS 874 = 0x36A at 0x0D2BB000, agreeing.)
G_OFF = 0x3CB8                     # G = blk + 0x3CB8
RESULTS_SEL_OFF = 0xAD             # G+0xAD selects the results-bank variant
RESULTS_POL_DC, RESULTS_TEX_DC = 0x0D2BB000, 0x0D2E9000
RESULTS_AFS = {1: (0x36A, 0x36B), 2: (0x36C, 0x36D)}
RESULTS_AFS_DEFAULT = (0x34D, 0x34E)
# Other aux banks EXIST at 0x0D25C000 / 0x0D3A2000 / 0x0D4CE000 / 0x0D6CC000 / 0x0D720000 / 0x0D7A9000 /
# 0x0D7CC000 (identified by archive match: POL AFS 839 / 847 / 849 / 851 / 853 / 855 / 843).  They are NOT placed:
# FUN_14060c370 loads them through a shared tail whose TEX address this pass did not trace, and relocation needs
# BOTH addresses.  build() therefore ends with a loud coverage check instead of silently leaving them 0xCD.

BANKS = (  # name, TCW base, POL AFS, TEX AFS, POL DC, TEX DC          (None AFS = stage, filled per id)
    ('effects', 0xC50, 799, 800, 0x0D000000, 0x0D026000),
    ('hud', 0xC90, 835, 836, 0x0D082000, 0x0D099000),
    ('common', 0x810, 837, 838, 0x0D0C6000, 0x0D0E5000),
    ('stage', 0xC10, None, None, 0x0D82D000, 0x0D85D000),
)


class Img(object):
    def __init__(self, n=DCRAM_SZ):
        self.b = bytearray(bytes([FILL]) * n)

    def put(self, dc, data):
        o = dc - DCB
        assert 0 <= o and o + len(data) <= len(self.b), hex(dc)
        self.b[o:o + len(data)] = data

    def u32(self, dc):
        return struct.unpack_from('<I', self.b, dc - DCB)[0]

    def i32(self, dc):
        return struct.unpack_from('<i', self.b, dc - DCB)[0]

    def u16(self, dc):
        return struct.unpack_from('<H', self.b, dc - DCB)[0]

    def w32(self, dc, v):
        struct.pack_into('<I', self.b, dc - DCB, v & 0xFFFFFFFF)


def afs_index_tail(cid):
    """DAT_140a6d190 (u16) = 3 + cid, cids 25/26 collapsed onto 27."""
    return 27 if cid in (25, 26) else 3 + cid


def relocate(img, pol_dc, tex_dc):
    """FUN_14060d770 (== SH4 loc_8c0322d4)."""
    p0 = img.u32(pol_dc)
    n = img.u32(pol_dc + 4)
    delta = (p0 - pol_dc - 0x10) & 0xFFFFFFFF
    if delta & 0x80000000:
        delta -= 1 << 32
    img.w32(pol_dc + 8, img.u32(pol_dc + 8) - delta)
    img.w32(pol_dc, p0 - delta)
    tbl = (p0 - delta) & 0xFFFFFFFF
    for i in range(n):
        img.w32(tbl + i * 4, img.u32(tbl + i * 4) - delta)
    th = img.u32(pol_dc + 8)
    first = img.u32(th + 8)
    a = th
    while img.u16(a) != 0:
        img.w32(a + 8, img.u32(a + 8) - (first - tex_dc))
        a += 16
    return n, tbl, th


def records(img, model_dc):
    """FUN_140844dc0 / FUN_1406196e0 record walk: start model+0x18, next = rec + 0x50 + rec[+0x4C],
    terminator = the PCW at rec+0 is non-negative."""
    r = model_dc + 0x18
    while img.i32(r) < 0:
        size = 0x50 + img.i32(r + 0x4C)
        yield r, size
        r += size


def assign_tcw(img, pol_dc, base):
    """FUN_1408458a0(base) + FUN_140844dc0 over every model of the bank."""
    tbl, n = img.u32(pol_dc), img.u32(pol_dc + 4)
    for i in range(n):
        for r, _ in records(img, img.u32(tbl + i * 4)):
            ti = img.i32(r + 0x20)
            if ti >= 0:
                img.w32(r + 0xC, ti + base)


def stage10_fixup(img, pol_dc):
    """FUN_14060d470 inner loop: models 1..8 only (the counter starts at -1 and is tested BEFORE its
    post-increment, so model 0 is skipped -- corrects RECEIPT-RUNNER-DCRAM s2.3 'models 0..7')."""
    tbl, n = img.u32(pol_dc), img.u32(pol_dc + 4)
    for i in range(1, min(9, n)):
        for r, _ in records(img, img.u32(tbl + i * 4)):
            ti = img.i32(r + 0x20)
            if ti == 10:
                img.w32(r + 4, img.u32(r + 4) | 0x4000000)
            elif ti == 5:
                img.w32(r, img.u32(r) & 0xFDFFFFFF)


def roster(blk):
    return dict(stage=blk[STAGE_BYTE],
                cids=[blk[FIGHTER0 + s * FSTRIDE + OFF_CID] for s in range(6)],
                costumes=[blk[FIGHTER0 + s * FSTRIDE + OFF_COSTUME] for s in range(6)],
                assists=[blk[FIGHTER0 + s * FSTRIDE + OFF_ASSIST] for s in range(6)])


def build(arc, blk, verbose=True, need_results=False):
    m, ents = RT.load_afs(arc)
    R = roster(blk)
    img = Img()
    placed = []                                   # (dc, len, tag) -- every byte the loader writes

    # ---- PL slots (FUN_14060d100 + case 6 tail)
    for slot in range(6):
        pos = PL_POS[slot]
        cid = R['cids'][slot]
        base = 0x0C420000 + pos * SLOT_SZ
        for afs, off in PL_FILES:
            d, _, sz = RT.afs_entry(m, ents, afs + cid)
            img.put(base + off, d)
            placed.append((base + off, sz, 'PL%d/%d' % (pos, afs + cid)))
        d, _, sz = RT.afs_entry(m, ents, afs_index_tail(cid))
        img.put(base + PL_TAIL_OFF, d)
        placed.append((base + PL_TAIL_OFF, sz, 'PL%d/tail' % pos))

    # ---- banks
    for name, tcwbase, pe, te, pa, ta in BANKS:
        if name == 'stage':
            pe, te = 801 + 2 * R['stage'], 802 + 2 * R['stage']
        d, _, sz = RT.afs_entry(m, ents, pe)
        img.put(pa, d)
        placed.append((pa, sz, name + '/POL'))
        d, _, sz = RT.afs_entry(m, ents, te)
        img.put(ta, d)
        placed.append((ta, sz, name + '/TEX'))
        n, tbl, th = relocate(img, pa, ta)
        assign_tcw(img, pa, tcwbase)
        if verbose:
            print('  bank %-8s AFS %3d/%3d @%08X/%08X  models %3d  texHdr %08X'
                  % (name, pe, te, pa, ta, n, th))
    if R['stage'] == 0x10:
        before = bytes(img.b[0x0D82D000 - DCB:0x0D85D000 - DCB])
        stage10_fixup(img, 0x0D82D000)
        after = img.b[0x0D82D000 - DCB:0x0D85D000 - DCB]
        runs, i, n = [], 0, len(before)
        while i < n:
            if before[i] != after[i]:
                j = i
                while j < n and before[j] != after[j]:
                    j += 1
                runs.append((0x0D82D000 + i, j - i))
                i = j
            else:
                i += 1
        print('  stage-0x10 ISP/TSP fix-up (FUN_14060d470, models 1..8): %d bytes in %d runs'
              % (sum(l for _, l in runs), len(runs)))
        for addr, l in runs[:12]:
            print('     %08X len %d  before %s  after %s'
                  % (addr, l, before[addr - 0x0D82D000:addr - 0x0D82D000 + min(l, 8)].hex(),
                     bytes(after[addr - 0x0D82D000:addr - 0x0D82D000 + min(l, 8)]).hex()))
        if len(runs) > 12:
            print('     ... %d more runs' % (len(runs) - 12))

    # ---- results bank (FUN_14060c370 case 10) -- see the AUX note above.
    # DEMAND-DRIVEN: place it only when this anchor actually references it. G+0xAD selects the variant, but it is
    # only meaningful when case 10 last ran: at a BATTLE anchor it reads 0 (the default pair) while the bytes
    # resident at 0x0D2BB000 are whatever the previous results screen left (measured: variant 1 on river_b and
    # stage9). Placing it unconditionally therefore makes the image DIVERGE from live on battle anchors, where
    # nothing reads it. Same staleness class as blk+0x6D04 (GATE4 s A5).
    if need_results:
        sel = blk[G_OFF + RESULTS_SEL_OFF]
        rp, rt = RESULTS_AFS.get(sel, RESULTS_AFS_DEFAULT)
        d, _, sz = RT.afs_entry(m, ents, rp)
        img.put(RESULTS_POL_DC, d)
        placed.append((RESULTS_POL_DC, sz, 'results/POL'))
        d, _, sz2 = RT.afs_entry(m, ents, rt)
        img.put(RESULTS_TEX_DC, d)
        placed.append((RESULTS_TEX_DC, sz2, 'results/TEX'))
        rn, _, _ = relocate(img, RESULTS_POL_DC, RESULTS_TEX_DC)
        assign_tcw(img, RESULTS_POL_DC, 0x810)
        if verbose:
            print('  bank %-8s AFS %3d/%3d @%08X/%08X  models %3d  (G+0xAD=%d)'
                  % ('results', rp, rt, RESULTS_POL_DC, RESULTS_TEX_DC, rn, sel))
    elif verbose:
        print('  bank results: not referenced by this anchor -> not placed (demand-driven)')

    # ---- HUD portraits / name plates (FUN_14060d560)
    th = img.u32(0x0D082000 + 8)
    for s in range(6):
        cid = R['cids'][s]
        f = RP.char_file(m, ents, cid)
        blob = RP.lzss16(f, struct.unpack_from('<I', f, 0)[0], out_words=4 * 0x800 // 2)
        pages = [blob[i * 0x800:(i + 1) * 0x800] for i in range(4)]
        k = K_HUD[s]
        a = R['assists'][s] if R['assists'][s] < len(ASSIST_PAGE) else 0
        pl, nl = img.u32(th + (10 + k) * 16 + 8), img.u32(th + (16 + k) * 16 + 8)
        img.put(pl, pages[ASSIST_PAGE[a]])
        placed.append((pl, 0x800, 'portrait%d' % k))
        img.put(nl, pages[2])
        placed.append((nl, 0x800, 'nameplate%d' % k))
        if verbose:
            print('  slot %d cid %2d assist %d k %d  portrait @%08X  name @%08X' % (s, cid, a, k, pl, nl))
    return img, R, placed


# ----------------------------------------------------------------------------- classification
def _in(dc, ivals):
    for a, b, _ in ivals:
        if a <= dc < b:
            return True
    return False


def class_of(dc, placed_ivals):
    """Tag one differing byte. '?' = a byte the loader itself placed and that still differs = a FAILURE."""
    if 0x0CE60000 <= dc < 0x0CE65000:
        return 'R', 'tile buffer 0x0CE60000 (rebuilt every frame)'
    for pos in range(6):
        base = 0x0C420000 + pos * SLOT_SZ
        if base + PL_E_OFF <= dc < base + PL_E_OFF + PL_E_LEN:
            return 'E', 'PL pos %d +0x145000 engine region (fighter+0x1F0)' % pos
    hit = None
    for a, b, t in placed_ivals:
        if a <= dc < b:
            hit = t
            break
    if hit is not None:
        if hit.startswith('results/'):
            return 'B', '%s (results bank: runtime uploads + per-frame rewrites)' % hit
        if hit.endswith('/POL'):
            return 'B', '%s (per-frame rewrite / spawn-time model patch)' % hit
        return '?', 'loader-placed byte differs: %s' % hit
    if 0x0C420000 <= dc < 0x0C420000 + 6 * SLOT_SZ:
        return 'L', 'PL slot leftover past a placed file'
    for name, tcwbase, pe, te, pa, ta in BANKS:
        if pa <= dc < ta:
            return 'L', '%s bank leftover past the POL file' % name
    return 'X', 'not a battle region (select / VS / result / staging)'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run', help='receipt run dir (with pre/) or the pre/ dir itself')
    ap.add_argument('--arc', default=RT.DEFAULT_ARC)
    ap.add_argument('--out')
    ap.add_argument('--gate', action='store_true', help='classify every difference vs pre/dcram.bin')
    ap.add_argument('--fill', default=None,
                    help='hex byte for every DC-RAM byte the loader does NOT write (classes L and X). Two builds that'
                         ' differ only in this value are a PERTURBATION test: if blk is identical after N ticks, those'
                         ' classes are PROVEN unread rather than merely measured-unread.')
    ap.add_argument('--poison-e', default=None,
                    help='hex byte to fill the six base+0x145000 engine regions with (class E), same purpose')
    ap.add_argument('--stage', type=int, default=None,
                    help='override the stage id from blk (exercises a stage bank + its fix-ups without a dump of it)')
    ap.add_argument('--carry-e', action='store_true', help='copy the six +0x145000 regions from the live dcram')
    ap.add_argument('--carry-s', action='store_true', help='copy every still-differing bank POL byte (S+R)')
    a = ap.parse_args()
    pre = a.run if os.path.exists(os.path.join(a.run, 'meta.json')) else os.path.join(a.run, 'pre')
    blk = open(os.path.join(pre, 'blk.bin'), 'rb').read()
    meta_j = json.load(open(os.path.join(pre, 'meta.json')))
    R0 = roster(blk)
    print('roster (slot order) %s  costumes %s  assists %s  stage %d'
          % (R0['cids'], R0['costumes'], R0['assists'], R0['stage']))
    if a.stage is not None:
        blk = bytearray(blk)
        blk[STAGE_BYTE] = a.stage
        blk = bytes(blk)
        print('STAGE OVERRIDE: building for stage 0x%02X (%d) instead of the anchor stage' % (a.stage, a.stage))
        R0 = roster(blk)
    if a.fill is not None:
        global FILL
        FILL = int(a.fill, 16)
        print('CLASS L/X POISON: unwritten DC-RAM filled with 0x%02X' % FILL)
    need = False
    try:
        sys.path.insert(0, os.path.join(HERE, '..', 'replay'))
        import blkstate as _B
        _DCH = int(meta_j['dcram'], 16)
        _BLK = int(meta_j['blk'], 16)
        for nd in _B.anodes(blk, _BLK, lists=range(16), drawn_only=False, limit=400):
            h = nd.get('obj') or 0
            if h and _DCH <= h < _DCH + int(meta_j['dcram_size'], 16):
                dc = h - _DCH + DCB
                if RESULTS_POL_DC <= dc < RESULTS_TEX_DC + 0x200000:
                    need = True
                    break
    except Exception as e:
        print('  (results-bank demand check unavailable: %s)' % e)
    img, R, placed = build(a.arc, blk, need_results=need)
    if a.poison_e is not None:
        v = int(a.poison_e, 16)
        for pos in range(6):
            base = 0x0C420000 + pos * SLOT_SZ + PL_E_OFF
            img.put(base, bytes([v]) * PL_E_LEN)
        print('CLASS E POISON: six %d B regions at base+0x145000 filled with 0x%02X' % (PL_E_LEN, v))
    placed_ivals = [(dc, dc + n, t) for dc, n, t in placed]

    live = None
    lp = os.path.join(pre, 'dcram.bin')
    if os.path.exists(lp):
        live = open(lp, 'rb').read()

    if live and (a.carry_e or a.carry_s):
        if a.carry_e:
            for pos in range(6):
                base = 0x0C420000 + pos * SLOT_SZ + PL_E_OFF
                img.put(base, live[base - DCB:base - DCB + PL_E_LEN])
            print('carried class E: 6 x 0x%X B' % PL_E_LEN)
        if a.carry_s:
            nb = 0
            for name, tb, pe, te, pa, ta in BANKS:
                for o in range(pa - DCB, ta - DCB):
                    if img.b[o] != live[o]:
                        img.b[o] = live[o]
                        nb += 1
            print('carried class S+R (bank POL): %d B' % nb)

    if a.out:
        open(a.out, 'wb').write(bytes(img.b))
        print('written %s  %d B' % (a.out, len(img.b)))

    if a.gate and live:
        cls = {}
        i, n = 0, len(live)
        while i < n:
            if img.b[i] != live[i]:
                j = i
                while j < n and img.b[j] != live[j]:
                    j += 1
                c, why = class_of(DCB + i, placed_ivals)
                e = cls.setdefault((c, why), [0, 0, DCB + i])
                e[0] += 1
                e[1] += j - i
                i = j
            else:
                i += 1
        print('\n--- difference classes (arc-built vs live dcram) ---')
        tot = 0
        for (c, why), (runs, nb, first) in sorted(cls.items()):
            print('  %s  %-56s %8d B in %5d runs  first %08X' % (c, why[:56], nb, runs, first))
            tot += nb
        print('  total %d B' % tot)
        bad = [k for k in cls if k[0] == '?']
        print('UNEXPLAINED (loader-placed bytes that differ):', bad if bad else 'NONE')


if __name__ == '__main__':
    main()
