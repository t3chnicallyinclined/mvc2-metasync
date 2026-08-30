#!/usr/bin/env python3
# proof_render.py — PIXEL proof for the owned tape render, WITHOUT WebGPU.
#
# This is a FAITHFUL PYTHON PORT of maplecast sprite-client.mjs buildEmitterDrawList
# (the selKeyed body path, DEFAULT knobs) + drawHUD, driven by the SAME state the
# tape-adapter produces. It composites the real GFX2 part pixels (PLxx_parts.png +
# PLxx_asm.json) at the emitter's placement, then draws the procedural HUD. Because it
# reuses the validated emitter geometry and the adapter's field mapping, a correct output
# (characters standing on the ground at the right scale + a live HUD) is direct evidence
# the anchor + scale + layer + HUD wiring are right. The WebGPU pixel render (gpu.html)
# uses the identical inputs; this is the headless stand-in for the acceptance PNG.
#
# Emitter port (buildEmitterDrawList selKeyed, DEFAULTS faceInv=T, faceFlip=F,
# partFlipX=T, emitFlipY=T, tileScale=1, S=1, offMul=1, sizeMul=1, ax=ay=gdx=gdy=0):
#   cpsx=sclX, cpsy=sclY ; tsX=(5/3)*cpsx, tsY=(15/7)*cpsy
#   bodyFace = not facing ; posReflect = bodyFace ; axisX = exx
#   per record r{part,dx,dy,flip,flipy}:
#     w=part.w*tsX ; h=part.h*tsY
#     tlx=exx + r.dx*tsX ; tly=eyy + r.dy*tsY
#     if not posReflect: tlx-=w   else: tlx = 2*axisX - tlx
#     if r.flip: tlx = 2*axisX - (tlx+w)
#     if r.flipy: tly = 2*eyy - (tly+h)
#     U-mirror = (not bodyFace) xor r.flip ; V-flip = r.flipy xor emitFlipY(True)
#   z = layer*1e6 + (len(recs)-ri) ; paint ascending z (lower layer/further first).

import sys, os, json
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ATLAS = os.environ.get('ATLAS_BASE',
    r'C:/Users/trist/projects/maplecast-flycast/web/test-atlas/chars')
CPSX, CPSY, HPMAX = 5/3, 15/7, 144
P1_SLOTS, P2_SLOTS = [0, 2, 4], [1, 3, 5]

# ── adapter mapping (mirror of tape-adapter.mjs applyFrame) ─────────────────────
F = dict(frame=0, hp=4, p1_meter=7, p2_meter=8, meter_fill=9, combo_dealt=10,
         red_hp=14, facing=15, drawn=17, sid=18, sx=24, sy=25, zx=26, zy=27,
         flash=28, glow=29, layer=30, timer=31)

def slot_state(t, fi):
    row = t['frames'][fi]
    p1, p2, cos = t['p1_team'], t['p2_team'], t['costume']
    slots = []
    for s in range(6):
        cid = (p1[s >> 1] if s % 2 == 0 else p2[s >> 1])
        raw = row[F['sid']][s]
        slots.append(dict(
            slot=s, cid=cid, active=bool(row[F['drawn']][s]),
            facing=row[F['facing']][s], exx=row[F['sx']][s], eyy=row[F['sy']][s],
            sid=raw & 0x7fff, xform=1 if raw & 0x8000 else 0,
            sclX=(row[F['zx']][s] or CPSX) / CPSX, sclY=(row[F['zy']][s] or CPSY) / CPSY,
            layer=row[F['layer']][s], hp=row[F['hp']][s], red=row[F['red_hp']][s],
            costume=cos[s]))
    hud = dict(timer=row[F['timer']], p1lvl=row[F['p1_meter']], p2lvl=row[F['p2_meter']],
               p1fill=row[F['meter_fill']], p2fill=row[F['meter_fill']],
               p1combo=max((row[F['combo_dealt']][s] for s in P1_SLOTS), default=0),
               p2combo=max((row[F['combo_dealt']][s] for s in P2_SLOTS), default=0))
    return slots, hud

# ── atlas cache ─────────────────────────────────────────────────────────────────
_cache = {}
def load_char(cid):
    hexn = f'{cid & 0xff:02X}'
    if hexn in _cache: return _cache[hexn]
    base = os.path.join(ATLAS, f'PL{hexn}')
    try:
        asm = json.load(open(base + '_asm.json'))
        parts = json.load(open(base + '_parts.json'))
        parts = parts.get('parts', parts)
        img = Image.open(base + '_parts.png').convert('RGBA')
        assemblies = asm.get('assemblies', asm.get('asm', asm))
        _cache[hexn] = (assemblies, parts, img, asm.get('name', 'PL' + hexn))
    except Exception as e:
        _cache[hexn] = None
        print(f'  [warn] PL{hexn}: no emitter atlas ({e})')
    return _cache[hexn]

# ── emitter placement (faithful port) ───────────────────────────────────────────
def emit_body(sl):
    """Return list of (z, screen_rect(x,y,w,h), part_rect, umirror, vflip, cid) quads."""
    ch = load_char(sl['cid'])
    if not ch: return []
    assemblies, parts, img, name = ch
    recs = assemblies.get(str(sl['sid'])) or assemblies.get(sl['sid'])
    if not recs: return []
    cpsx, cpsy = sl['sclX'], sl['sclY']
    tsX, tsY = CPSX * cpsx, CPSY * cpsy
    body_face = (not sl['facing'])          # faceInv TRUE, faceFlip FALSE
    pos_reflect = body_face
    axisX, exx, eyy = sl['exx'], sl['exx'], sl['eyy']
    out, n = [], len(recs)
    for ri, r in enumerate(recs):
        pkey = r.get('part')
        part = parts.get(str(pkey)) or parts.get(pkey)
        if not part: continue
        w, h = part['w'] * tsX, part['h'] * tsY
        tlx = exx + r.get('dx', 0) * tsX
        tly = eyy + r.get('dy', 0) * tsY
        if not pos_reflect: tlx = tlx - w
        else:               tlx = 2 * axisX - tlx
        if r.get('flip'):   tlx = 2 * axisX - (tlx + w)
        if r.get('flipy'):  tly = 2 * eyy - (tly + h)
        umirror = (not body_face) != bool(r.get('flip'))
        vflip   = bool(r.get('flipy')) != True          # emitFlipY True
        z = (sl['layer'] if sl['layer'] != 0xFF else 15) * 1e6 + (n - ri)
        out.append((z, (tlx, tly, w, h), (part['x'], part['y'], part['w'], part['h']),
                    umirror, vflip, sl['cid']))
    return out

def paint_bodies(canvas, slots):
    quads = []
    for sl in slots:
        if sl['active']:
            quads += emit_body(sl)
    # spec §4: draw ascending z (lower layer / further = first = behind)
    quads.sort(key=lambda q: q[0])
    drawn = 0
    for z, (dx, dy, dw, dh), (px, py, pw, ph), umirror, vflip, cid in quads:
        if dw < 0.5 or dh < 0.5: continue
        ch = _cache[f'{cid & 0xff:02X}']
        img = ch[2]
        sub = img.crop((px, py, px + pw, py + ph))
        if umirror: sub = sub.transpose(Image.FLIP_LEFT_RIGHT)
        if vflip:   sub = sub.transpose(Image.FLIP_TOP_BOTTOM)
        sub = sub.resize((max(1, round(dw)), max(1, round(dh))), Image.NEAREST)
        canvas.alpha_composite(sub, (round(dx), round(dy)))
        drawn += 1
    return drawn, len(quads)

# ── procedural HUD (port of drawHUD, monospace-digit fallback) ───────────────────
BARCOL = {0: ('#FF40FF', '#FFFF00'), 1: ('#00FF00', '#FFFF00'), 2: ('#00C0FF', '#FFFF00')}
def _hx(c):
    c = c.lstrip('#'); return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))

def _point(slots, side):
    for i, s in enumerate(side):
        if slots[s]['active']: return slots[s], i
    return None, 0

def _bar(dr, x, y, w, h, frac, colB, from_right):
    frac = max(0.0, min(1.0, frac)); fw = round(w * frac)
    if fw <= 0: return
    fx = (x + w - fw) if from_right else x
    dr.rectangle([fx, y, fx + fw, y + h], fill=_hx(colB))

def paint_hud(canvas, slots, hud):
    dr = ImageDraw.Draw(canvas)
    try: font = ImageFont.truetype('consolab.ttf', 22)
    except Exception: font = ImageFont.load_default()
    try: cfont = ImageFont.truetype('consolab.ttf', 15)
    except Exception: cfont = font
    p1, i1 = _point(slots, P1_SLOTS); p2, i2 = _point(slots, P2_SLOTS)
    c1 = BARCOL[i1 if p1 else 0]; c2 = BARCOL[i2 if p2 else 0]
    hp = lambda s: (max(0, min(1, s['hp'] / HPMAX)) if s else 0)
    rd = lambda s: (max(0, min(1, s['red'] / HPMAX)) if s else 0)
    LBx1, LBx2, LBy, LBw, LBh = 18, 330, 16, 292, 14
    # life bars: red chip behind, HP on top
    _bar(dr, LBx1, LBy, LBw, LBh, rd(p1), '#601010', False)
    _bar(dr, LBx1, LBy, LBw, LBh, hp(p1), c1[0], False)
    _bar(dr, LBx2, LBy, LBw, LBh, rd(p2), '#601010', True)
    _bar(dr, LBx2, LBy, LBw, LBh, hp(p2), c2[0], True)
    dr.rectangle([LBx1, LBy, LBx1 + LBw, LBy + LBh], outline=(255, 255, 255), width=1)
    dr.rectangle([LBx2, LBy, LBx2 + LBw, LBy + LBh], outline=(255, 255, 255), width=1)
    # super meters
    _bar(dr, 18, 456, 250, 9, (hud['p1fill'] or 0) / HPMAX, c1[0], False)
    _bar(dr, 372, 456, 250, 9, (hud['p2fill'] or 0) / HPMAX, c2[0], True)
    # meter pips
    for i in range(hud['p1lvl'] or 0): dr.rectangle([18 + i * 12, 446, 27 + i * 12, 452], fill=(255, 210, 77))
    for i in range(hud['p2lvl'] or 0): dr.rectangle([613 - i * 12, 446, 622 - i * 12, 452], fill=(255, 210, 77))
    # timer (2 digits centered)
    tstr = f"{max(0, min(99, hud['timer'])):02d}"
    dr.text((320, 12), tstr, fill=(255, 255, 255), font=font, anchor='ma')
    # combo
    if (hud['p1combo'] or 0) > 1: dr.text((24, 38), f"{hud['p1combo']} HIT", fill=(255, 225, 77), font=cfont)
    if (hud['p2combo'] or 0) > 1: dr.text((616, 38), f"{hud['p2combo']} HIT", fill=(255, 225, 77), font=cfont, anchor='ra')

# ── main ─────────────────────────────────────────────────────────────────────────
def main():
    tape = json.load(open(os.path.join(HERE, 'tape.json')))
    fi = int(sys.argv[1]) if len(sys.argv) > 1 else 600
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, f'proof_render_59598061_f{fi}.png')
    slots, hud = slot_state(tape, fi)
    gframe = tape['frames'][fi][F['frame']]
    canvas = Image.new('RGBA', (640, 480), (24, 26, 32, 255))
    # ground line for anchor reference
    ImageDraw.Draw(canvas).line([(0, 433), (640, 433)], fill=(60, 66, 80), width=1)
    drawn, total = paint_bodies(canvas, slots)
    paint_hud(canvas, slots, hud)
    canvas.convert('RGB').save(out)
    print(f'\nframe idx {fi} (game {gframe}) -> {out}')
    print(f'body quads: {drawn}/{total} painted')
    for sl in slots:
        if sl['active']:
            ch = load_char(sl['cid'])
            nm = ch[3] if ch else '??'
            recs = (ch[0].get(str(sl['sid'])) if ch else None) or []
            print(f"  slot{sl['slot']} {nm} cid={sl['cid']} sid=0x{sl['sid']:x} "
                  f"foot=({sl['exx']:.0f},{sl['eyy']:.0f}) scale=({sl['sclX']:.2f},{sl['sclY']:.2f}) "
                  f"face={sl['facing']} layer={sl['layer']} recs={len(recs)}")
    print('HUD:', hud)

if __name__ == '__main__':
    main()
