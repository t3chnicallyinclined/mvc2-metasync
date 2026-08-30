#!/usr/bin/env python3
# proof_hud_slide.py — MULTI-FRAME proof of the NATIVE HUD 32-frame life-bar GLIDE (THE slide).
#
# A single still cannot show an animation, so this replays the tape IN ORDER through a hit and
# renders a sequence of frames as the bar DRAINS. The glide here is a byte-for-byte Python
# mirror of renderer/hud-client.mjs HudAnim (verified numerically by smoke_hud_anim.mjs), so the
# montage is direct evidence of what the browser (gpu.html) draws. Full scene (stage + bodies +
# effects) behind, then the glided HUD on top — exactly the gpu.html stack.
#
# usage: python proof_hud_slide.py [startPreFrame] [out.png] [frame_a frame_b ...]
#   default = the P2 point-char single hit (idx 1107, 144->125): pre / hit+flash / +8 / +16 / +24 / +32.

import sys, os, math
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proof_render as P
import proof_full as PF

HERE = P.HERE
GLIDE = 32
FLASH_FADE = 1.0 / 8.0
COMBO_BOUNCE = 10
P1_SLOTS, P2_SLOTS = [0, 2, 4], [1, 3, 5]


# ── Python mirror of hud-client.mjs HudAnim (glide + red trail + hit-flash + combo bounce) ──
class HudAnim:
    def __init__(self):
        self.reset(); self.lastFrame = None

    def reset(self):
        self.s = [dict(disp=1.0, dispRed=1.0, cd=-1, cdRed=-1, step=0.0, stepRed=0.0,
                       flash=0.0, lastHp=None, lastRed=None) for _ in range(6)]
        self.combo = [dict(n=0, lastN=0, popFrame=-10**9), dict(n=0, lastN=0, popFrame=-10**9)]

    def _step(self, a, hp, red):
        tHp = max(0.0, min(1.0, hp / 144.0)); tRd = max(0.0, min(1.0, red / 144.0))
        if a['lastHp'] is None or hp > a['lastHp']:           # first sight / round reset -> snap
            a['disp'] = tHp; a['dispRed'] = tRd; a['cd'] = -1; a['cdRed'] = -1; a['flash'] = 0.0
        else:
            if hp != a['lastHp']:                              # retarget from CURRENT displayed
                a['step'] = (tHp - a['disp']) / GLIDE; a['cd'] = GLIDE
            if a['cd'] >= 0: a['disp'] += a['step']; a['cd'] -= 1
            else: a['disp'] = tHp
            if red > a['lastRed']:
                a['dispRed'] = tRd; a['cdRed'] = -1
            else:
                if red != a['lastRed']: a['stepRed'] = (tRd - a['dispRed']) / GLIDE; a['cdRed'] = GLIDE
                if a['cdRed'] >= 0: a['dispRed'] += a['stepRed']; a['cdRed'] -= 1
                else: a['dispRed'] = tRd
            a['flash'] = 1.0 if hp < a['lastHp'] else max(0.0, a['flash'] - FLASH_FADE)
        a['lastHp'] = hp; a['lastRed'] = red

    def _stepCombo(self, frameIdx, combos):
        for i in range(2):
            c = self.combo[i]; n = int(combos[i])
            if n > c['lastN'] and n > 1: c['popFrame'] = frameIdx
            c['n'] = n; c['lastN'] = n

    def _snap(self, slots, combos):
        for si in range(6):
            a = self.s[si]; hp = slots[si]['hp']; red = slots[si]['red']
            a['disp'] = max(0, min(1, hp / 144.0)); a['dispRed'] = max(0, min(1, red / 144.0))
            a['cd'] = -1; a['cdRed'] = -1; a['step'] = 0; a['stepRed'] = 0; a['flash'] = 0
            a['lastHp'] = hp; a['lastRed'] = red
        for i in range(2): self.combo[i]['n'] = int(combos[i]); self.combo[i]['lastN'] = int(combos[i])

    def sync(self, frameIdx, slots, combos):
        adv = 0 if self.lastFrame is None else frameIdx - self.lastFrame
        if adv == 1:
            for si in range(6): self._step(self.s[si], slots[si]['hp'], slots[si]['red'])
            self._stepCombo(frameIdx, combos)
        elif 1 < adv <= GLIDE:
            for si in range(6):
                for _ in range(adv): self._step(self.s[si], slots[si]['hp'], slots[si]['red'])
            self._stepCombo(frameIdx, combos)
        else:
            self._snap(slots, combos)
        self.lastFrame = frameIdx

    def comboBounce(self, i, frameIdx):
        d = frameIdx - self.combo[i]['popFrame']
        if d < 0 or d >= COMBO_BOUNCE: return 0.0
        return 1.0 - d / COMBO_BOUNCE


def render_scene(t, fi, disp, frameIdx, bounce):
    """Full gpu.html stack for one frame: stage + hit-flash bodies + effects + GLIDED HUD."""
    Fi = t['_Fi']
    slots, hud = P.slot_state(t, fi)
    row = t['frames'][fi]; gframe = row[Fi['frame']]
    hs = row[Fi['hitstun']]; phs = t['frames'][fi - 1][Fi['hitstun']] if fi > 0 else [0] * 6
    hitstun = [(1 if hs[s] > phs[s] else 0) for s in range(6)]
    canvas = PF.stage_canvas(t, row)
    PF.paint_bodies_flash(canvas, slots, hitstun)
    objs = t['_byf'].get(gframe, []); fxq = []
    for o in objs:
        if not (1 <= o[5] <= 4): continue
        q, cid, g = PF.emit_effect(o, slots, t, guard=True)
        if q: fxq += q
    canvas = PF.paint_additive(canvas, fxq)
    PF.paint_full_hud(canvas, slots, hud, hitstun, disp=disp, frameIdx=frameIdx, bounce=bounce)
    return canvas.convert('RGB')


def main():
    t = PF.load_tape(); Fi = t['_Fi']
    start_pre = int(sys.argv[1]) if len(sys.argv) > 1 else 1101
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, 'proof_hud_slide.png')
    if len(sys.argv) > 3:
        shown = [int(x) for x in sys.argv[3:]]
    else:
        hit = 1107
        shown = [1102, hit, hit + 8, hit + 16, hit + 24, hit + 32]
    shown_set = set(shown); last = max(shown)

    # Which side's point char drains across the window (for the label).
    def point_slot(fi, side):
        drawn = t['frames'][fi][Fi['drawn']]
        for s in side:
            if drawn[s]: return s
        return side[0]
    ps2 = point_slot((start_pre + last) // 2, P2_SLOTS)
    ps1 = point_slot((start_pre + last) // 2, P1_SLOTS)
    hp = lambda fi, s: t['frames'][fi][Fi['hp']][s]
    trackP2 = (hp(start_pre, ps2) - hp(last, ps2)) >= (hp(start_pre, ps1) - hp(last, ps1))
    ps = ps2 if trackP2 else ps1
    side_name = 'P2' if trackP2 else 'P1'

    # Replay the glide IN ORDER from start_pre..last, rendering the scene at each shown frame.
    anim = HudAnim()
    crops = []
    snaps = {}   # fi -> (disp dict, bounce) captured at that exact frame
    print(f'replaying glide {start_pre}..{last}, tracking {side_name} point slot {ps} '
          f'(cid={t["p2_team"][ps//2] if ps%2 else t["p1_team"][ps//2]})')
    for fi in range(start_pre, last + 1):
        slots, hud = P.slot_state(t, fi)
        rawslots = [dict(hp=slots[s]['hp'], red=slots[s]['red']) for s in range(6)]
        anim.sync(fi, rawslots, [hud['p1combo'], hud['p2combo']])
        if fi in shown_set:
            disp = {s: dict(hp=anim.s[s]['disp'], red=anim.s[s]['dispRed'], flash=anim.s[s]['flash'])
                    for s in range(6)}
            bounce = {0: anim.comboBounce(0, fi), 1: anim.comboBounce(1, fi)}
            snaps[fi] = (disp, bounce)
            scene = render_scene(t, fi, disp, fi, bounce)
            a = anim.s[ps]
            cap = t['frames'][fi][Fi['hp']][ps]
            crop = scene.crop((0, 0, 640, 96))              # the life-bar / combo strip
            lab = Image.new('RGB', (640, 22), (12, 14, 20))
            dr = ImageDraw.Draw(lab)
            try: f = ImageFont.truetype('consolab.ttf', 12)
            except Exception: f = ImageFont.load_default()
            txt = (f"frame {fi}  {side_name} captured hp={cap}/144 ({cap/144*100:.0f}%)  "
                   f"DISPLAYED bar={a['disp']*100:.1f}%  flash={a['flash']:.2f}")
            dr.text((6, 4), txt, fill=(210, 230, 250), font=f)
            cell = Image.new('RGB', (640, 96 + 22), (12, 14, 20))
            cell.paste(lab, (0, 0)); cell.paste(crop, (0, 22))
            crops.append(cell)
            print(f'  frame {fi}: captured {cap}/144  displayed {a["disp"]*100:.1f}%  flash {a["flash"]:.2f}')

    gap = 4
    strip = Image.new('RGB', (640, sum(c.height for c in crops) + gap * (len(crops) - 1)), (0, 0, 0))
    y = 0
    for c in crops:
        strip.paste(c, (0, y)); y += c.height + gap
    strip.save(out)
    print(f'\nmontage -> {out}  ({len(crops)} frames, {strip.width}x{strip.height})')

    # also drop the full 640x480 hit frame for context (using that frame's exact glide snapshot)
    full_out = out.replace('.png', '_fullframe.png')
    hf = shown[1] if len(shown) > 1 else shown[0]
    disp_hf, bounce_hf = snaps[hf]
    render_scene(t, hf, disp_hf, hf, bounce_hf).save(full_out)
    print(f'full hit frame {hf} -> {full_out}')


if __name__ == '__main__':
    main()
