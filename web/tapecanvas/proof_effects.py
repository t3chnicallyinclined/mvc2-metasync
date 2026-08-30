#!/usr/bin/env python3
# proof_effects.py — PIXEL proof of the 0.3.29 SPRITE-CLASS EFFECT render path on the REAL tape.
#
# Renders one real frame's bodies + its real effect nodes exactly as the tapecanvas emitter does:
#   • resolve atlas = OWNER's char (tape-adapter resolveFxAtlas; owner-char = 100% sid coverage
#     on the real tape's 48,452 effect nodes; gfx2 is always 0 so gfx1 keys only ownerless nodes).
#   • cell = sid & 0x7FFF ; anchor = OWN origin (obj sx/sy) ; facing = owner slot ; scale = zx/4096.
#   • ADDITIVE composite (dst = dst + src·alpha) = the sprite-gpu pipeAdd analogue.
# Faithful to tape-adapter.mjs applyFrame + proof_render.py emit_body. Bodies real, effects real.
#
# usage: python proof_effects.py [frameIdx] [out.png]

import sys, os, json
from PIL import Image, ImageDraw, ImageChops
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proof_render as P
CPSX = P.CPSX

def load_tape():
    t = json.load(open(os.path.join(P.HERE, 'tape.json')))
    fields = [f.strip() for f in t['schema'].strip('[]').split(',')]
    t['_Fi'] = {n: i for i, n in enumerate(fields)}
    t['_byf'] = {fr: arr for fr, arr in t['objs']}
    return t

def cid_for_slot(t, s):
    return t['p1_team'][s >> 1] if s % 2 == 0 else t['p2_team'][s >> 1]

def emit_effect(o, slots, t):
    """o = real obj list [sid,sx,sy,zx,face,cat,owner,layer,gfx1,gfx2]. Own-origin, additive."""
    sid, sx, sy, zx, face, cat, owner, layer = o[:8]
    if owner >= 6:                       # ownerless super-flash w/o a gfx1 bankMap -> defer
        return [], None
    cid = cid_for_slot(t, owner)
    facing = slots[owner]['facing'] if slots[owner]['active'] else face
    objScale = zx / 4096.0
    sl = dict(slot=owner, cid=cid, active=True, facing=facing, exx=sx, eyy=sy,
              sid=sid & 0x7fff, xform=0, sclX=objScale / CPSX, sclY=objScale / CPSX,
              layer=layer, hp=144, red=144, costume=1)
    return P.emit_body(sl), cid

def paint_additive(canvas, quads):
    base = canvas.convert('RGB')
    for z, (dx, dy, dw, dh), (px, py, pw, ph), um, vf, cid in sorted(quads, key=lambda q: q[0]):
        if dw < .5 or dh < .5: continue
        img = P._cache[f'{cid & 0xff:02X}'][2]
        sub = img.crop((px, py, px + pw, py + ph))
        if um: sub = sub.transpose(Image.FLIP_LEFT_RIGHT)
        if vf: sub = sub.transpose(Image.FLIP_TOP_BOTTOM)
        sub = sub.resize((max(1, round(dw)), max(1, round(dh))), Image.NEAREST)
        layer = Image.new('RGB', base.size, (0, 0, 0))
        rgb = sub.convert('RGB'); a = sub.getchannel('A')
        pm = Image.composite(rgb, Image.new('RGB', rgb.size, (0, 0, 0)), a)
        layer.paste(pm, (round(dx), round(dy)))
        base = ImageChops.add(base, layer)
    return base.convert('RGBA')

def main():
    t = load_tape()
    fi = int(sys.argv[1]) if len(sys.argv) > 1 else 5804
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(P.HERE, 'proof_effects_59598061.png')
    slots, hud = P.slot_state(t, fi)
    gframe = t['frames'][fi][t['_Fi']['frame']]
    objs = t['_byf'].get(gframe, [])

    canvas = Image.new('RGBA', (640, 480), (24, 26, 32, 255))
    ImageDraw.Draw(canvas).line([(0, 433), (640, 433)], fill=(60, 66, 80), width=1)
    P.paint_bodies(canvas, slots)

    fx_quads, drawn, skipped, marks = [], 0, 0, []
    for o in objs:
        if not (1 <= o[5] <= 4):
            continue
        q, cid = emit_effect(o, slots, t)
        if q:
            fx_quads += q; drawn += 1
            marks.append((o[1], o[2], o[5], o[6], cid, o[0] & 0x7fff, o[8]))
        else:
            skipped += 1
    canvas = paint_additive(canvas, fx_quads)

    dr = ImageDraw.Draw(canvas)
    for (mx, my, cat, ow, cid, msid, g1) in marks:
        dr.ellipse([mx - 4, my - 4, mx + 4, my + 4], outline=(0, 255, 255), width=1)
    P.paint_hud(canvas, slots, hud)
    canvas.convert('RGB').save(out)
    print(f'frame idx {fi} (game {gframe}) -> {out}')
    print(f'effects: {drawn} drawn (owner-resolved), {skipped} ownerless-deferred, {len(fx_quads)} additive quads')
    for (mx, my, cat, ow, cid, msid, g1) in marks[:12]:
        print(f"  cat{cat} owner{ow}->PL{cid&0xff:02X} sel={msid} gfx1=0x{g1:x} own-origin=({mx},{my}) ADD")

if __name__ == '__main__':
    main()
