#!/usr/bin/env python3
# proof_hud_team.py — CLEAN full-team HUD proof directly comparable to the maplecast ground-truth
# render (_hud_cap_def/hud_0123.png). Renders ONLY the HUD (all 6 life bars + 6 portraits + 6
# names per side + frame backing + timer/meter) via the SAME paint_full_hud() the WebGPU client
# mirrors (renderer/hud-client.mjs), on a dark backdrop. Two outputs:
#   proof_hud_team.png           — the HUD-only render (640x480, dark bg)
#   proof_hud_team_vs_gt.png     — our HUD band stacked ABOVE the ground-truth hud_0123.png
#
# usage: python3 proof_hud_team.py
import os, sys
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proof_full as F

HERE = os.path.dirname(os.path.abspath(__file__))
GT = os.path.normpath(os.path.join(HERE, "..", "..", "..", "maplecast-flycast",
     "tools", "render-replica-poc", "_hud_cap_def", "hud_0123.png"))

# Demonstrative 3v3 state that exercises EVERY element: point chars near-full with a chip trail,
# reserves at varied HP, one KO'd. Interleaved slots (even=P1, odd=P2). cids picked to show real
# DM01 portraits + roster names on both sides.
def slot(active, cid, hp, red):
    return {"active": active, "cid": cid, "hp": hp, "red": red, "slot": 0}

SLOTS = [
    slot(1, 0x2A, 120, 138),  # P1 point  STORM   (hp<red -> red chip shows)
    slot(1, 0x17, 96, 120),   # P2 point  CABLE
    slot(0, 0x2C, 88, 88),    # P1 res1   MAGNETO
    slot(0, 0x34, 40, 60),    # P2 res1   SENTINEL
    slot(0, 0x32, 144, 144),  # P1 res2   COLOSSUS (full)
    slot(0, 0x0F, 0, 0),      # P2 res2   DR.DOOM  (KO'd -> greyed)
]
for i, s in enumerate(SLOTS):
    s["slot"] = i

HUD = {"timer": 42, "p1lvl": 3, "p2lvl": 5, "p1fill": 300, "p2fill": 500,
       "p1combo": 7, "p2combo": 0}


def main():
    canvas = Image.new("RGBA", (640, 480), (18, 20, 26, 255))
    F.paint_full_hud(canvas, SLOTS, HUD, [0] * 6)
    out = os.path.join(HERE, "proof_hud_team.png")
    canvas.convert("RGB").save(out)
    print("wrote", out)

    # stacked comparison vs the ground-truth render (top HUD band only, y 0..120)
    band = 120
    ours = canvas.crop((0, 0, 640, band)).convert("RGB")
    try:
        gt = Image.open(GT).convert("RGB").crop((0, 0, 640, band))
    except Exception as e:
        print("  [warn] ground truth not found:", e); return
    from PIL import ImageDraw, ImageFont
    try: f = ImageFont.truetype("consolab.ttf", 11)
    except Exception: f = ImageFont.load_default()
    cmp = Image.new("RGB", (640, band * 2 + 22), (0, 0, 0))
    cmp.paste(ours, (0, 11)); cmp.paste(gt, (0, band + 22))
    d = ImageDraw.Draw(cmp)
    d.text((4, 0), "OURS (reconstruct-from-state)", fill=(180, 255, 180), font=f)
    d.text((4, band + 12), "GROUND TRUTH  hud_0123.png (real engine HUDQ)", fill=(255, 220, 140), font=f)
    outc = os.path.join(HERE, "proof_hud_team_vs_gt.png")
    cmp.save(outc)
    print("wrote", outc)


if __name__ == "__main__":
    main()
