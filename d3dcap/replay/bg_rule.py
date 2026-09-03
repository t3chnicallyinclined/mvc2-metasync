#!/usr/bin/env python3
"""bg_rule.py -- the frame BACKGROUND colour of Steam MvC2, exactly as the engine computes it.

Read in Ghidra (mvc_dump.bin) and in the marvelous2 SH4 disassembly, 2026-09-03; see
docs/FRAME-BACKGROUND-GHIDRA.md and re_kb seed 110_frame_background.surql.

    FUN_1406101b0  ==  SH4 loc_8c02dc4c        (called once per frame from FUN_14060a1f0, the LayerZ reset)
        in a fight (G[0..2] == 2,1,2 and !(G+0x2E & 1); SH4 loc_8c03591e / loc_8c03593e):
            fade word blk+0x6CE4 != 0            -> mode := 0, A = blk+0x6CF0 raw       (white/black strobe)
            entity+0x96 != 0 and entity+6 != 0   -> mode := 0, A = 0                    (super blackout: black)
            else: A/B/C = mul(blk+0x6CB8 / 0x6CBC / 0x6CC0)  where
                  mul(word) = ((int)(byte2 * deck[0]) & 0xff) << 16 | ((int)(byte1 * deck[1]) & 0xff) << 8
                              | ((int)(byte0 * deck[2]) & 0xff)         deck = f32[3] at blk+0x6CA8 (R, G, B)
                  (SH4 loc_8c02dcd6: fmul + ftrc per byte, extu.b, shll16 / shll8 / or)
        outside a fight: A/B/C = the three words read as uint3 (no multiplier; SH4 loc_8c02de12)
        mode = blk+0x6CB4:  0 -> (A, A, A)   1 -> (A, B, A)   2 -> (A, A, B)   3 -> (A, B, C)   else: no update
        -> FUN_1408450e0(c0, c1, c2, 1e7) writes ctx+0x1f8248 / +0x1f824c / +0x1f8250 (+0x1f8254 = far 1e7)

    FUN_140843eb0 (frame flush) then queues ONE full-screen quad, format 0x4000, stride 0x1c, texId 0xffff:
        v0 = TL (-1,  1, 1, 0)  colour c0 | 0xff000000
        v1 = BL (-1, -1, 1, 0)  colour c1 | 0xff000000
        v2 = TR ( 1,  1, 1, 0)  colour c2 | 0xff000000
        v3 = BR ( 1, -1, 1, 0)  colour c2 | 0xff000000
    and the ring executor FUN_140070940 (format 0x4000 branch) turns it into the 40-B layout the scene uses:
        POSITION (x, y, z, 0), NORMAL (0, 1), color0 = word with bytes 0 and 2 SWAPPED (0xAARRGGBB -> R,G,B,A
        bytes), color1 = 0, TEXCOORD (0, 0); texId 0xffff = the 1x1 white placeholder page (ffffffff).
    So the captured vertex colour bytes are (R, G, B, 0xff) with R = byte 2 of the engine word.

The stage constants (Steam FUN_140620200 stage load, re-asserted every frame by FUN_140620420 from
FUN_1406283a0): table DAT_14097db20, 12 B per stage; stages 3 and 0xC use FUN_140610480 (mode 2, two words),
every other stage FUN_1406104b0 (mode 0, one word). Values below were read from mvc_dump.bin at
0x14097db20 (file offset VA-0x140000000). SH4 twin of that table: UNKNOWN (loc_8c045ce0 does not carry it).
"""
import numpy as np

# stage id (blk+0x6D04) -> (mode, [word0, word1, word2]) as the stage initialiser writes blk+0x6CB4..0x6CC3
STAGE_BG = {
    0x00: (0, [0x007f7f7f, 0, 0]),
    0x01: (0, [0x006061e3, 0, 0]),
    0x02: (0, [0x00000000, 0, 0]),
    0x03: (2, [0x00000000, 0x00b0459a, 0]),
    0x04: (0, [0x007f7f7f, 0, 0]),
    0x05: (0, [0x00000000, 0, 0]),
    0x06: (0, [0x007f7f7f, 0, 0]),
    0x07: (0, [0x007f7f7f, 0, 0]),
    0x08: (0, [0x00000000, 0, 0]),
    0x09: (0, [0x00000000, 0, 0]),
    0x0A: (0, [0x006061e3, 0, 0]),
    0x0B: (0, [0x00000000, 0, 0]),
    0x0C: (2, [0x00000000, 0x00b0459a, 0]),
    0x0D: (0, [0x007f7f7f, 0, 0]),
    0x0E: (0, [0x00000000, 0, 0]),
    0x0F: (0, [0x007f7f7f, 0, 0]),
    0x10: (0, [0x007f7f7f, 0, 0]),
}


def mul_word(word, deck):
    """loc_8c02dcd6 / FUN_1406101b0 in-fight path: per byte (int)((float)byte * deck[k]) & 0xff, f32 maths."""
    b0, b1, b2 = word & 0xff, (word >> 8) & 0xff, (word >> 16) & 0xff
    d0, d1, d2 = (np.float32(deck[0]), np.float32(deck[1]), np.float32(deck[2]))
    r = int(np.float32(b2) * d0) & 0xff      # byte 2 (R of 0x00RRGGBB) x blk+0x6CA8
    g = int(np.float32(b1) * d1) & 0xff      # byte 1                   x blk+0x6CAC
    b = int(np.float32(b0) * d2) & 0xff      # byte 0                   x blk+0x6CB0
    return (r << 16) | (g << 8) | b


def background_words(mode, words, deck=(1.0, 1.0, 1.0), fade=0, fade_col=0, blackout=0, ent6=1, in_fight=True):
    """(c0, c1, c2) 24-bit words handed to FUN_1408450e0, or None when the engine leaves them untouched
    (mode outside 0..3). `blackout` stands in for entity+0x96 (G+0x98 is its per-frame copy, FUN_14061f030);
    `ent6` = entity+6 (UNKNOWN meaning; non-zero on every captured fight frame is INFERRED, not read)."""
    mode = int(mode)
    if not in_fight:
        A, B, C = [int(w) & 0xffffff for w in words]
    else:
        if fade:
            mode, A, B, C = 0, int(fade_col) & 0xffffff, 0, 0
        elif blackout and ent6:
            mode, A, B, C = 0, 0, 0, 0
        else:
            A = mul_word(int(words[0]), deck)
            B = mul_word(int(words[1]), deck) if mode >= 1 else 0
            C = mul_word(int(words[2]), deck) if mode == 3 else 0
    if mode == 0:
        return (A, A, A)
    if mode == 1:
        return (A, B, A)
    if mode == 2:
        return (A, A, B)
    if mode == 3:
        return (A, B, C)
    return None


def vertex_colours(c012):
    """The four vertex colour byte tuples (R, G, B, A) of the FUN_140843eb0 quad in its submission order
    TL, BL, TR, BR (the executor keeps the order; the byte swap is the executor's 0x4000 conversion)."""
    c0, c1, c2 = c012
    def rgba(w):
        return ((w >> 16) & 0xff, (w >> 8) & 0xff, w & 0xff, 0xff)
    return [rgba(c0), rgba(c1), rgba(c2), rgba(c2)]


def from_row(r, C, stage_id, stats=None):
    """Background inputs of one tape row. Uses the 0.3.42 columns when present (bg_mode, bg_col[3],
    fade_mode, fade_col, bg_gate[4]); else the per-stage table + deck/blackout rows (fade assumed off,
    fight assumed). Returns (c0, c1, c2) or None."""
    deck = tuple(float(x) for x in r[C['deck']]) if 'deck' in C and isinstance(r[C['deck']], (list, tuple)) else (1.0, 1.0, 1.0)
    blackout = int(float(r[C['blackout']])) if 'blackout' in C else 0
    if 'bg_mode' in C and 'bg_col' in C:
        mode, words = int(r[C['bg_mode']]), [int(w) for w in r[C['bg_col']]]
        fade = int(r[C['fade_mode']]) if 'fade_mode' in C else 0
        fade_col = int(r[C['fade_col']]) if 'fade_col' in C else 0
        gate = r[C['bg_gate']] if 'bg_gate' in C else None
        in_fight = True
        ent6 = 1
        if gate is not None and len(gate) >= 6:
            g0, g1, g2, g2e, e6, e96 = [int(x) for x in gate[:6]]
            in_fight = not ((g0, g1, g2) == (2, 1, 2) and (g2e & 1) == 0) is False   # FUN_14060b400 && !FUN_14060b430
            in_fight = ((g0, g1, g2) == (2, 1, 2)) and ((g2e & 1) == 0)
            if e6 != 0xff:
                ent6 = e6
            if e96 != 0xff:
                blackout = e96
        if stats is not None:
            stats['tape bytes'] += 1
    else:
        if int(stage_id) not in STAGE_BG:
            if stats is not None:
                stats['no table entry for stage %s' % stage_id] += 1
            return None
        mode, words = STAGE_BG[int(stage_id)]
        fade, fade_col, in_fight, ent6 = 0, 0, True, 1
        if stats is not None:
            stats['per-stage table (tape lacks bg bytes)'] += 1
    out = background_words(mode, words, deck, fade, fade_col, blackout, ent6, in_fight)
    if stats is not None:
        stats['mode %d' % mode] += 1
        if fade:
            stats['fade frames'] += 1
        if blackout and ent6 and in_fight and not fade:
            stats['blackout (black) frames'] += 1
    return out
