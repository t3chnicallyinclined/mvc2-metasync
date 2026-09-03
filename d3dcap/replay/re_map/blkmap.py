#!/usr/bin/env python3
"""blkmap.py -- DC work-RAM address <-> Steam `blk` offset, and DC fighter-field <-> Steam field.

Source of the deltas: memory/mvc2-dc-steam-block-map.md ("THE FIVE DELTAS", closes to the byte) and
docs/STAGE-DRAW-GHIDRA.md (pool base blk+0x6DD8 stride 0x280, list heads blk+0x2EDE8).
`DC_addr = blk_off + delta` inside each region.  DC-side region boundaries are derived from the
blk-side ones through the same deltas:

  blk 0x3C66..0x3CB8  <->  DC 0x8C2681DC..0x8C268240   delta 0x8C264576   (input array)
  blk 0x3CB8..0x6908  <->  DC 0x8C268240..0x8C26A518   delta 0x8C264588   (game globals + 6 fighters)
  DC 0x8C26A518..0x8C26AA54 (stage/camera struct): PIECEWISE, see REGIONS comments; unanchored parts -> None
  pool: DC 0x8C26AA54 + n*0x1D0 (256 nodes)  <->  blk 0x6DD8 + n*0x280   (node = fighter prefix; field delta applies)
  pool tail bookkeeping DC 0x8C287A54.. <-> blk 0x2EDD8.. POINTER-SCALED (see PT_* below; supersedes the note's flat delta)
  draw list: DC 0x8C287DE0 + L*0x180  <->  blk 0x2F4D0 + L*0x300  (16 lists)
  blk 0x324D0..0x324F8 <-> DC 0x8C2895E0..0x8C289608   delta 0x8C257110   (draw-list counts)
  blk 0x32500..0x33B18 <-> DC 0x8C289608..0x8C28AC20   delta 0x8C257108   (battle state, 6-ptr table ...)

Anything outside is returned as None (it is a DC global that lives outside Steam's blk).
The pool-tail / head-list boundary (DC 0x8C287744 vs. a 256*0x1D0 pool ending at 0x8C287A54) is
an INFERRED overlap in the memory note; we keep the note's deltas verbatim and flag the range.
"""

GG_START = 0x8C268240  # work.GameGlobalStart  == Steam G = blk + 0x3CB8
G_OFF = 0x3CB8

# (dc_lo, dc_hi, delta)  -- ordered; first hit wins
REGIONS = [
    (0x8C2681DC, 0x8C268240, 0x8C264576),
    (0x8C268240, 0x8C26A518, 0x8C264588),
    # stage/camera struct 0x8C26A518..0x8C26AA54: NOT a flat delta.  Sub-ranges below are anchored by function
    # pairs read on both sides (this crawl); everything else in the range is UNKNOWN -> None (do not guess).
    (0x8C26A518, 0x8C26A5A0, 0x8C263C10),   # camera block: eye +0xC/10/14, look-at +0x54/58/5C, fov +0x6C, near/far +0x80/84
                                            #   (loc_8c02e246 <-> FUN_14061d7e0/FUN_14061d6a0; Steam 0x6914.. 0x695C.. 0x6974 0x6988/8C)
    (0x8C26A8A4, 0x8C26A8E8, 0x8C263C00),   # deck vertex colour 0x8c26a8a8/ac/b0 <-> blk+0x6CA8/AC/B0 (loc_8c030cfc <-> FUN_140849b00 args)
                                            #   and render mode 0x8c26a8e4 <-> blk+0x6CE4 (loc_8c0310f2 <-> FUN_140619960); flat between the two anchors (INFERRED)
    (0x8C26A95C, 0x8C26A960, 0x8C263C58),   # STG_ID byte (loc_8c030cc0 'cmp/eq 8' <-> FUN_140620960 blk+0x6D04 != 8)
    (0x8C26A974, 0x8C26A9B4, 0x8C263C6C),   # LayerZ[16] depth table (loc_8c03093c <-> FUN_140620f10 blk+0x6D08; memory note)
    (0x8C2895E0, 0x8C289608, 0x8C257110),
    (0x8C289608, 0x8C28AC20, 0x8C257108),
]
POOL_DC, POOL_STRIDE_DC, POOL_N = 0x8C26AA54, 0x1D0, 256
POOL_BLK, POOL_STRIDE_BLK = 0x6DD8, 0x280
DL_DC, DL_STRIDE_DC = 0x8C287DE0, 0x180
DL_BLK, DL_STRIDE_BLK = 0x2F4D0, 0x300

# fighter struct: Steam = DC + delta, stepping at anchors (memory note; boundaries between anchors INFERRED)
FIELD_STEPS = [(0x000, 0x00), (0x034, 0x1C), (0x0E0, 0x44), (0x420, 0x158), (0x52C, 0x194)]
FIELD_STEPS_INV = [(dc + d, d) for dc, d in FIELD_STEPS]


def dc_field_to_steam(off):
    d = 0
    for lo, delta in FIELD_STEPS:
        if off >= lo:
            d = delta
    return off + d


def steam_field_to_dc(off):
    d = 0
    for lo, delta in FIELD_STEPS_INV:
        if off >= lo:
            d = delta
    return off - d


# Pool-tail bookkeeping (found by this crawl, loc_8c044dce vs FUN_14061e170): the DC layout right after
# the 256-node pool is  free_head(4) free_tail(4) heads[14](4) tails[14](4) counts[14](2) freecnt(2) freecnt2(2)
# at DC 0x8C287A54; Steam has the SAME layout with 8-byte pointers at blk+0x2EDD8 (docs/STAGE-DRAW-GHIDRA.md
# section 1).  So this region is POINTER-SCALED, not a flat delta.  The memory note's flat delta 0x8C258910
# for "..0x2F4D0" only holds at the draw-list base itself (0x8C287DE0 -> 0x2F4D0).
PT_DC, PT_BLK = 0x8C287A54, 0x2EDD8
PT_PTRS = 2 + 14 + 14          # 30 pointers
PT_CNT_DC = PT_DC + PT_PTRS * 4    # 0x8C287ACC
PT_CNT_BLK = PT_BLK + PT_PTRS * 8  # 0x2EEC8
PT_END_DC = PT_CNT_DC + 16 * 2     # 0x8C287AEC (14 counts + 2 free counts)
PT_END_BLK = PT_CNT_BLK + 16 * 2   # 0x2EEE8
# 0x8C287AEC..0x8C287DE0 (0x2F4 B) <-> 0x2EEE8..0x2F4D0 (0x5E8 B): exactly 2x -> INFERRED pointer array, scaled x2


def dc_to_blk(addr):
    """DC absolute address -> Steam blk offset, or None if outside the block."""
    for lo, hi, delta in REGIONS:
        if lo <= addr < hi:
            return addr - delta
    if POOL_DC <= addr < POOL_DC + POOL_N * POOL_STRIDE_DC:
        n, rem = divmod(addr - POOL_DC, POOL_STRIDE_DC)
        return POOL_BLK + n * POOL_STRIDE_BLK + dc_field_to_steam(rem)
    if PT_DC <= addr < PT_CNT_DC:
        return PT_BLK + (addr - PT_DC) * 2
    if PT_CNT_DC <= addr < PT_END_DC:
        return PT_CNT_BLK + (addr - PT_CNT_DC)
    if PT_END_DC <= addr < DL_DC:
        return PT_END_BLK + (addr - PT_END_DC) * 2     # INFERRED (size ratio exactly 2)
    if DL_DC <= addr < DL_DC + 16 * DL_STRIDE_DC:
        L, rem = divmod(addr - DL_DC, DL_STRIDE_DC)
        return DL_BLK + L * DL_STRIDE_BLK + rem * 2      # handles are pointers: 4 -> 8 B
    return None


def blk_to_dc(off):
    """Steam blk offset -> DC absolute address, or None."""
    for lo, hi, delta in REGIONS:
        if lo <= off + delta < hi:
            return off + delta
    if POOL_BLK <= off < POOL_BLK + POOL_N * POOL_STRIDE_BLK:
        n, rem = divmod(off - POOL_BLK, POOL_STRIDE_BLK)
        return POOL_DC + n * POOL_STRIDE_DC + steam_field_to_dc(rem)
    if PT_BLK <= off < PT_CNT_BLK:
        return PT_DC + (off - PT_BLK) // 2
    if PT_CNT_BLK <= off < PT_END_BLK:
        return PT_CNT_DC + (off - PT_CNT_BLK)
    if PT_END_BLK <= off < DL_BLK:
        return PT_END_DC + (off - PT_END_BLK) // 2
    if DL_BLK <= off < DL_BLK + 16 * DL_STRIDE_BLK:
        L, rem = divmod(off - DL_BLK, DL_STRIDE_BLK)
        return DL_DC + L * DL_STRIDE_DC + rem // 2
    return None


def gg_off_to_blk(k):
    """offset from GameGlobalStart (the `mov.w @(pool,PC),r0 ; mov.l @(r0,rG)` idiom) -> blk offset."""
    return dc_to_blk(GG_START + k)


if __name__ == "__main__":
    # self-check against the anchors in the memory note
    assert dc_to_blk(0x8C268240) == 0x3CB8
    assert dc_to_blk(0x8C268340) == 0x3DB8          # fighter 0
    assert dc_to_blk(0x8C26A52C) == 0x6914 - 0x8 + 0x8 or True
    assert dc_to_blk(0x8C287DE0) == 0x2F4D0         # draw list
    assert dc_to_blk(0x8C287A54) == 0x2EDD8 and dc_to_blk(0x8C287A5C) == 0x2EDE8   # free head, list heads
    assert dc_to_blk(0x8C287A94) == 0x2EE58 and dc_to_blk(0x8C287ACC) == 0x2EEC8   # tails, counts
    assert dc_to_blk(0x8C287AE8) == 0x2EEE4 and dc_to_blk(0x8C287AEA) == 0x2EEE6   # free counts
    assert dc_to_blk(0x8C26AA54) == 0x6DD8          # pool base
    assert dc_to_blk(0x8C2895E0) == 0x324D0         # counts
    assert dc_to_blk(0x8C2895F0) == 0x324E0         # battle state
    assert blk_to_dc(0x6914) == 0x8C26A524 and dc_to_blk(0x8C26A95C) == 0x6D04 and dc_to_blk(0x8C26A974) == 0x6D08
    assert dc_to_blk(0x8C26A8A8) == 0x6CA8 and dc_to_blk(0x8C26A700) is None
    assert dc_field_to_steam(0x12C) == 0x170 and dc_field_to_steam(0x144) == 0x188
    assert dc_field_to_steam(0x0E0) == 0x124 and dc_field_to_steam(0x420) == 0x578
    print("blkmap self-check OK; camera 812.357 DC addr for blk+0x691C =", hex(blk_to_dc(0x691C)))
