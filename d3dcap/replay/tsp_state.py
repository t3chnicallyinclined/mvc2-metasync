#!/usr/bin/env python3
"""DC polygon-record header words (PCW/ISP/TSP) -> the D3D11 state Steam sets for that draw.

Every rule below is read out of the unpacked Steam exe (mvc_dump.bin, Ghidra project dumpproj) and
tagged. `codes()` is the CONFIRMED part: it reproduces, bit for bit, what the NaomiLib consumer
FUN_1408482a0 and the queue FUN_1408436a0 / flush FUN_140842e30 compute from the record and hand
to the host renderer as small integer commands (blend preset, sampler word, depth preset, cull
word, ignore-tex-alpha flag). `HOST` is the host renderer's translation of those integers into
D3D11 enums; the executor of that command ring was NOT located in Ghidra (it is inside a
Ghidra mega-blob), so HOST is INFERRED from the capture gate (tsp_gate.py): every code observed
maps to exactly one captured D3D state over every matched draw, and the table records that.

Sources (all CONFIRMED by decompile unless marked):
  FUN_1408482a0  kinds 0-3 consumer:
    entry = queue slot +8; rec = *entry; PCW = rec[0], ISP = rec[1], TSP = rec[2], TCW = rec[3]
    alpha_mult = *(float*)(entry+0xCC)   (param_3 of FUN_140848ee0, clamped to <= 1.0)
    if alpha_mult == 1.0: src = TSP>>29, dst = TSP>>26 & 7          (PVR src/dst alpha instr)
    else:                 src/dst = ctx+0x1f8274 byte (0x45 = SRCA/INVSRCA, FUN_140844a10 init,
                          never rewritten) -> alpha-modulated draws are forced to normal blend
    FUN_140844220(src<<4 | dst)           -> command 1 (blend preset, table in that function)
    clampUV = TSP>>15 & 3 (bit15 clamp U, bit16 clamp V); 0 if ctx+0x1f8524 == 4
    addr = 1 if clampUV == 3 else 0; addr = 2 if TSP & 0x60000 (bit17 flip U | bit18 flip V)
    FUN_140844320(TSP>>13 & 3, addr)      -> command 2 = (filter==0 ? 0x10000 : 0) | addr<<17
    depth (ctx+0x1f8520 == 1, FUN_140607b50 0x140607bfd):
      cat == 2                 -> 10
      ISP bit26 == 0 (Z write ENABLED on PVR):
         cat == 3 and s19 == 0 -> no command: keeps the flush's preset 2
         else                  -> 4 - (PCW bit7)
      ISP bit26 == 1           -> 2
    FUN_1400483c0(8, preset)
    per polygon group: FUN_1400483c0(9, group_flags & 3) when entry+0xC8 < 2  (cull word)
    ignoreTexA = TSP>>19 & 1, forced 1 when src == 1 (ONE) and dst != 0 (ZERO)
    untextured when (int)rec[8] (texNum @+0x20) < 0 -> texture id 0xFFFF
    fog = TSP>>22 & 3 -> batch id 0x2000 + fog (+1 for triangle lists)
  FUN_1408436a0  category `cat` = queue slot +0x18, `s19` = slot +0x19 from PCW list type
    (PCW>>24 & 7) and the draw kind (2 = deck/list nodes, 3 = list nodes with flag bit 5 and an
    alpha multiplier, 0 = HUD lists 0xB/0xD under FUN_14061d5b0's perspective):
      listtype 0 (opaque):      kind 2/0 -> cat 0, s19 0;  kind 3 -> cat (0 if alpha==1 else 3), s19 1
      listtype 1 (opaque MV):   cat 1, s19 0
      listtype 2/3/4 (transl.): cat 3, s19 0 (depth-sorted in the flush)
  FUN_140842e30  flush: per entry command 1 = table(slot+0x1a = ctx+0x1f8274 = 0x45 -> 0x32),
    command 8 = 10 if cat 2; cat 3: 2 if s19 == 0, 5 if s19 == 5, else 1; else 1 -- then the
    consumer above overrides 1/8 as listed.
"""

# FUN_140844220 / FUN_140842e30: (src<<4 | dst) -> host blend preset. PVR alpha instructions:
# 0 ZERO 1 ONE 2 OTHER 3 INV_OTHER 4 SRCA 5 INV_SRCA 6 DSTA 7 INV_DSTA.
BLEND_PRESET = {0x10: 1, 0x11: 0x11, 0x16: 0x11, 0x14: 0x12, 0x41: 0x12, 0x46: 0x12,
                0x21: 0x16, 0x22: 0x22, 0x30: 7, 0x31: 0x19, 0x45: 0x32}

D3D_BLEND = {1: 'ZERO', 2: 'ONE', 3: 'SRC_COLOR', 4: 'INV_SRC_COLOR', 5: 'SRC_ALPHA',
             6: 'INV_SRC_ALPHA', 7: 'DEST_ALPHA', 8: 'INV_DEST_ALPHA', 9: 'DEST_COLOR',
             10: 'INV_DEST_COLOR'}
D3D_ADDR = {1: 'WRAP', 2: 'MIRROR', 3: 'CLAMP', 4: 'BORDER', 5: 'MIRROR_ONCE'}
D3D_CULL = {1: 'NONE', 2: 'FRONT', 3: 'BACK'}


def codes(pcw, isp, tsp, gflags, alpha_mult=1.0, kind=2, uvmode=0):
    """The integers Steam hands its host renderer for one polygon group (CONFIRMED, see module doc)."""
    if alpha_mult == 1.0:
        src, dst = tsp >> 29, (tsp >> 26) & 7
    else:
        src, dst = 4, 5                                    # ctx+0x1f8274 = 0x45
    blend_key = src << 4 | dst
    blend = BLEND_PRESET.get(blend_key, 0)
    clamp = 0 if uvmode == 4 else (tsp >> 15) & 3
    addr = 1 if clamp == 3 else 0
    if tsp & 0x60000:
        addr = 2
    filt = (tsp >> 13) & 3
    samp = (0x10000 if filt == 0 else 0) | addr << 17
    listtype = (pcw >> 24) & 7
    if listtype == 0:
        cat, s19 = (0, 0) if kind != 3 else ((0 if alpha_mult == 1.0 else 3), 1)
    elif listtype == 1:
        cat, s19 = 1, 0
    else:
        cat, s19 = 3, 0
    zwrite_disabled = (isp >> 26) & 1
    if cat == 2:
        depth = 10
    elif not zwrite_disabled:
        depth = 2 if (cat == 3 and s19 == 0) else 4 - ((pcw >> 7) & 1)
    else:
        depth = 2
    cull = gflags & 3 if kind in (0, 1, 2, 3) else None   # entry+0xC8 < 2 for kinds 0/2 (param 0) and 3 (param 1)
    ignore_texa = (tsp >> 19) & 1 or (1 if (src == 1 and dst != 0) else 0)
    fog = (tsp >> 22) & 3
    return dict(blend_key=blend_key, blend=blend, samp=samp, filt=filt, addr=addr, cat=cat, s19=s19,
                depth=depth, cull=cull, ignore_texa=int(ignore_texa), fog=fog,
                zwrite_disabled=zwrite_disabled, listtype=listtype)


# ── HOST: code -> D3D11 (INFERRED from the capture gate; each entry is the single value every
#    matched draw with that code carried; tsp_gate.py refuses to accept a code with two values) ──
HOST = {
    # blend preset -> (SrcBlend, DestBlend)   -- filled by the gate run recorded in
    # docs/TSP-RENDER-STATE-GHIDRA.md
    'blend': {1: (5, 6), 0x12: (5, 2), 0x32: (5, 6)},
    # sampler word -> (Filter, AddressU, AddressV)
    'samp': {0x00000: (21, 1, 1), 0x10000: (0, 1, 1), 0x20000: (21, 3, 3), 0x30000: (0, 3, 3)},
    # depth preset -> (DepthWriteMask, StencilEnable)
    'depth': {2: (0, 0), 4: (1, 1)},
    # cull word -> D3D11_CULL_MODE (identity: 1 NONE, 2 FRONT, 3 BACK). Code 0 is never observed
    # but the executor FUN_140070940 selects RS +0x1f58 for every word other than 2 (+0x2038) and
    # 3 (+0x1f68), i.e. the same object as code 1 (CONFIRMED by decompile).
    'cull': {0: 1, 1: 1, 2: 2, 3: 3},
    # ignore_texa -> psVariant name from classify_shaders.py
    'ps': {1: 'opaque', 0: 'texalpha'},
}


FIELDS = ('ps', 'samp', 'blend', 'depth', 'cull')


def state_key(s):
    """Hashable (ps, sampler, blend, depth, cull) of a captured() or predict() dict."""
    return tuple(s.get(f) for f in FIELDS)


def captured(d):
    """The gate-relevant subset of a pack draw's recorded state (pack_replay.py fields)."""
    s0 = (d.get('samp') or [None])[0] or {}
    b = d.get('blend') or {}
    dp = d.get('depth') or {}
    r = d.get('raster') or {}
    return dict(blend=(b.get('src'), b.get('dst')),
                samp=(s0.get('filter'), s0.get('u'), s0.get('v')),
                depth=(dp.get('write'), dp.get('sten')),
                cull=r.get('cull'),
                ps=d.get('psVariant'))


def predict(pcw, isp, tsp, gflags, **kw):
    c = codes(pcw, isp, tsp, gflags, **kw)
    return dict(blend=HOST['blend'].get(c['blend']), samp=HOST['samp'].get(c['samp']),
                depth=HOST['depth'].get(c['depth']), cull=HOST['cull'].get(c['cull']),
                ps=HOST['ps'].get(c['ignore_texa']), _codes=c)
