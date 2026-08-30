#!/usr/bin/env python3
# demo_montage.py — SHOWCASE montage of the owned tape/render replay engine on the real
# 0.3.29 tape, STAGE OFF (black background — the stage is parked for last). This is the
# "solid parts" demo: costume-accurate bodies + the FULL HUD + sprite-class effects,
# composited exactly as gpu.html does, at a few curated key frames.
#
# It reuses the validated proof tooling:
#   - proof_render.emit_body       (the faithful emitter geometry / anchor / scale port)
#   - proof_full.emit_effect / paint_additive / paint_full_hud   (effects + FULL HUD)
#   - the costume-LUT recolor validated in proof_costume_before_after.png:
#         palette index (recovered from the bank-0 baked parts) -> banks[bodyBank + costume*8]
#     with costume read from the tape (costume ?? 0). Bodies carry a costume -> LUT path
#     (gpu.mjs). Effects carry NO costume -> baked-default (bank 0), matching gpu.mjs render().
#
# usage: python demo_montage.py                (writes demo_montage.png)
#        python demo_montage.py <fi> out.png   (single-frame debug render)

import sys, os, json
from PIL import Image, ImageDraw, ImageFont, ImageChops
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proof_render as P
import proof_full as PF

HERE = P.HERE
ATLAS = P.ATLAS
NAMES = PF.NAMES

# ── costume-LUT recolor (the exact gpu.mjs math) ─────────────────────────────────
# parts.png is baked at the body bank (bodyBank == bank 0); every opaque pixel is one of
# the 16 bank-0 colors (verified 100%). So the palette INDEX is recoverable by matching the
# pixel RGB against bank 0, then remapped to banks[bodyBank + costume*8]. costume ?? 0.
_RECOLOR = {}   # hex -> recolored parts image (bodies).  original stays in P._cache (effects)

def _load_lut(cid):
    try:
        return json.load(open(os.path.join(ATLAS, f'PL{cid & 0xff:02X}_lut.json')))
    except Exception as e:
        print(f'  [warn] PL{cid & 0xff:02X}_lut.json: {e}'); return None

def build_recolor(cid, costume):
    """Recolor the cid's baked parts atlas to its costume bank. costume ?? 0."""
    hexn = f'{cid & 0xff:02X}'
    costume = int(costume or 0)
    ch = P.load_char(cid)
    if not ch: return
    img = ch[2]
    lut = _load_lut(cid)
    if not lut or 'banks' not in lut:
        _RECOLOR[hexn] = img.copy(); return
    banks = lut['banks']; bodyBank = int(lut.get('bodyBank', 0))
    bank = bodyBank + costume * 8
    if bank >= len(banks): bank = bodyBank
    bank0 = banks[bodyBank]; newbank = banks[bank]
    if bank == bodyBank:                              # costume 0 -> baked default, no remap
        _RECOLOR[hexn] = img.copy(); return
    # rgb -> index (prefer the OPAQUE entry when two indices share an RGB, e.g. black)
    rgb2idx = {}
    for i, e in enumerate(bank0):
        rgb = (e[0], e[1], e[2])
        if rgb not in rgb2idx or (len(e) > 3 and e[3] >= 128): rgb2idx[rgb] = i
    try:
        import numpy as np
        arr = np.array(img); out = arr.copy()
        opaque = arr[:, :, 3] >= 8
        for rgb, i in rgb2idx.items():
            dst = newbank[i]
            if (dst[0], dst[1], dst[2]) == rgb: continue
            m = opaque & (arr[:, :, 0] == rgb[0]) & (arr[:, :, 1] == rgb[1]) & (arr[:, :, 2] == rgb[2])
            out[m, 0] = dst[0]; out[m, 1] = dst[1]; out[m, 2] = dst[2]
        _RECOLOR[hexn] = Image.fromarray(out, 'RGBA')
    except ImportError:                              # pure-PIL fallback
        px = img.load(); cp = img.copy(); cx = cp.load()
        for y in range(img.height):
            for x in range(img.width):
                r, g, b, a = px[x, y]
                if a < 8: continue
                i = rgb2idx.get((r, g, b))
                if i is None: continue
                d = newbank[i]; cx[x, y] = (d[0], d[1], d[2], a)
        _RECOLOR[hexn] = cp

def cidcos_from_tape(t):
    """cid(&0xff) -> costume, read from the tape (costume ?? 0). Teams distinct in this tape."""
    cc = {}
    for s in range(6):
        cid = (t['p1_team'][s >> 1] if s % 2 == 0 else t['p2_team'][s >> 1]) & 0xff
        cc[cid] = int((t.get('costume') or [0] * 6)[s] or 0)
    return cc

# ── body paint (recolored + hit-flash), effects (baked default), FULL HUD ─────────
def paint_bodies_recolored(canvas, slots, hitstun, guard=True):
    quads = []
    for sl in slots:
        if sl['active']:
            for q in P.emit_body(sl):
                px, py, pw, ph = q[2]
                if guard and PF.is_degenerate(sl['cid'], {'x': px, 'y': py, 'w': pw, 'h': ph}): continue
                quads.append(q + (hitstun[sl['slot']] > 0,))
    quads.sort(key=lambda q: q[0])
    drawn = 0
    for z, (dx, dy, dw, dh), (px, py, pw, ph), um, vf, cid, flash in quads:
        if dw < 0.5 or dh < 0.5: continue
        img = _RECOLOR.get(f'{cid & 0xff:02X}') or P._cache[f'{cid & 0xff:02X}'][2]
        sub = img.crop((px, py, px + pw, py + ph))
        if um: sub = sub.transpose(Image.FLIP_LEFT_RIGHT)
        if vf: sub = sub.transpose(Image.FLIP_TOP_BOTTOM)
        sub = sub.resize((max(1, round(dw)), max(1, round(dh))), Image.NEAREST)
        if flash:                                    # victim hit-flash: additive near-white
            r, g, b, a = sub.split()
            boost = lambda ch, amt: ch.point(lambda v: min(255, int(v + amt)))
            sub = Image.merge('RGBA', (boost(r, 128), boost(g, 115), boost(b, 115), a))
        canvas.alpha_composite(sub, (round(dx), round(dy)))
        drawn += 1
    return drawn

def render_frame(t, fi):
    Fi = t['_Fi']
    slots, hud = P.slot_state(t, fi)
    row = t['frames'][fi]; gframe = row[Fi['frame']]
    hs = row[Fi['hitstun']]
    phs = t['frames'][fi - 1][Fi['hitstun']] if fi > 0 else [0] * 6
    hitstun = [(1 if hs[s] > phs[s] else 0) for s in range(6)]
    canvas = Image.new('RGBA', (640, 480), (0, 0, 0, 255))     # STAGE OFF -> pure black
    nb = paint_bodies_recolored(canvas, slots, hitstun)
    objs = t['_byf'].get(gframe, [])
    fxq = []; nfx = 0
    for o in objs:
        if not (1 <= o[5] <= 4): continue
        q, cid, g = PF.emit_effect(o, slots, t, guard=True)
        if q: fxq += q; nfx += 1
    canvas = PF.paint_additive(canvas, fxq)          # effects: baked default (no costume)
    PF.paint_full_hud(canvas, slots, hud, hitstun)
    return canvas, gframe, nb, nfx, slots, hud

# ── montage assembly ─────────────────────────────────────────────────────────────
def _font(sz, bold=True):
    for name in (('consolab.ttf', 'arialbd.ttf', 'seguisb.ttf') if bold else ('consola.ttf', 'arial.ttf')):
        try: return ImageFont.truetype(name, sz)
        except Exception: pass
    return ImageFont.load_default()

PANELS = [
    (150,  'NEUTRAL / SPACING',  'Magneto (costume 1, blue) vs Dr. Doom - both at full life, round start, TIME 99'),
    (6407, '25-HIT COMBO',       "Cable's blast connects; Magneto knocked down with hit-sparks - combo 25, meter L4, TIME 39"),
    (7401, 'SUPER / MULTI-FX',   'Storm (costume 1, gold) mid-super vs Sentinel + Cable - 64 effect nodes, 4 bodies'),
    (5344, 'COMBO + EFFECTS',    'Magneto (costume 1, blue) pressures Cable - dense hit-spark cluster, meter L4, TIME 49'),
]

def main():
    t = PF.load_tape()
    # single-frame debug mode
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        fi = int(sys.argv[1]); out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, f'demo_f{fi}.png')
        cc = cidcos_from_tape(t)
        for cid, cos in cc.items(): build_recolor(cid, cos)
        canvas, gf, nb, nfx, slots, hud = render_frame(t, fi)
        canvas.convert('RGB').save(out)
        print(f'fi={fi} gf={gf} bodies={nb} fx={nfx} -> {out}'); return

    cc = cidcos_from_tape(t)
    print('costume map (cid->costume):', {f'{k:02X}': v for k, v in cc.items()})
    for cid, cos in cc.items(): build_recolor(cid, cos)

    PW, PH = 640, 480
    LABEL_H = 46                      # per-panel caption strip
    TITLE_H = 60                      # montage header
    GAP = 8
    cols, rows = 2, 2
    cellW, cellH = PW, PH + LABEL_H
    W = cols * cellW + (cols + 1) * GAP
    H = TITLE_H + rows * cellH + (rows + 1) * GAP
    mont = Image.new('RGB', (W, H), (14, 15, 20))
    dr = ImageDraw.Draw(mont)
    ftitle = _font(30); fsub = _font(15, bold=False); flab = _font(19); fcap = _font(13, bold=False); ftag = _font(11, bold=False)
    dr.text((GAP + 4, 12), 'RETRO RECEIPTS - TAPE RENDER REPLAY', fill=(255, 210, 77), font=ftitle)
    dr.text((GAP + 4, 42), 'reconstruct-from-state - costume-accurate bodies + full HUD + effects  |  STAGE OFF (parked)  |  tape 0.3.29',
            fill=(150, 158, 172), font=fsub)

    for idx, (fi, tag, cap) in enumerate(PANELS):
        c = idx % cols; r = idx // cols
        x0 = GAP + c * (cellW + GAP)
        y0 = TITLE_H + GAP + r * (cellH + GAP)
        canvas, gf, nb, nfx, slots, hud = render_frame(t, fi)
        mont.paste(canvas.convert('RGB'), (x0, y0 + LABEL_H))
        # caption strip
        dr.rectangle([x0, y0, x0 + cellW, y0 + LABEL_H], fill=(24, 26, 34))
        dr.rectangle([x0, y0 + LABEL_H, x0 + cellW - 1, y0 + LABEL_H + PH - 1], outline=(60, 66, 80), width=1)
        dr.text((x0 + 10, y0 + 4), tag, fill=(120, 235, 140), font=flab)
        dr.text((x0 + 10, y0 + 27), cap, fill=(210, 216, 228), font=fcap)
        badge = f'gf {gf}  |  idx {fi}  |  {nb} quads + {nfx} fx'
        dr.text((x0 + cellW - 8, y0 + 7), badge, fill=(150, 158, 172), font=ftag, anchor='ra')
        print(f'panel {idx}: fi={fi} gf={gf} bodies={nb} fx={nfx} [{tag}]')

    out = os.path.join(HERE, 'demo_montage.png')
    mont.save(out)
    print('\nWROTE', out, mont.size)

if __name__ == '__main__':
    main()
