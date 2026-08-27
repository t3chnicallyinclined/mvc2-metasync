#!/usr/bin/env python3
"""probe_render_cols.py [secs] - READ-ONLY. Confirm the render columns before baking them into the agent.

Writes nothing. Safe during a live ranked match (multiple readers can RPM the same process).

The clock fix gave us a dense tape, but it still reconstructs screen coords from world+camera. The
sh4-re-expert says the engine STORES its own screen position at H+0x124/H+0x128 and per-object scale at
H+0x130/H+0x134 - recording those directly removes all reconstruction error and fixes super/juggle
scaling. Before we add them to the agent, CONFIRM the offsets against live data: the engine's own
H+0x124/H+0x128 must equal our reconstruction (px - eyeX + 320, ground - py) on every drawn fighter.

  H = blk + 0x3DB8 + i*0x738          fighter slot (true base, post-0x16C-fix)
  world  px H+0x50   py H+0x54
  screen sx H+0x124  sy H+0x128        <- candidate to confirm
  scale  zx H+0x130  zy H+0x134        <- candidate to confirm (rest = 5/3, 15/7)
  drawn gate H+0x170                   cid H+0x6C0
  camera eyeX blk+0x6914  eyeY blk+0x6918  ground blk+0x6998
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from savestate import Game, BLK_PTR, FC_OFF

H0, STRIDE = 0x3DB8, 0x738
OFF = dict(px=0x50, py=0x54, sx=0x124, sy=0x128, zx=0x130, zy=0x134, draw=0x170, cid=0x6C0)
EYEX, EYEY, GROUND = 0x6914, 0x6918, 0x6998
KX0, KY0 = 5/3, 15/7
SECS = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0

g = Game()


def f32(a):
    return struct.unpack("<f", g.read(a, 4))[0]


print("probe_render_cols - READ ONLY. Play; I compare the engine's screen coords to the reconstruction.\n")
worst_xy = 0.0
worst_scale_note = set()
samples = 0
drawn_seen = 0
last_fc = None
t0 = time.time()
last_line = 0.0

while time.time() - t0 < SECS:
    try:
        blk = g.u64(BLK_PTR)
        if not blk or blk < 0x10000:
            time.sleep(0.2); continue
        fc = g.u32(blk + FC_OFF)
        if fc == last_fc:
            time.sleep(0.004); continue
        last_fc = fc
        samples += 1
        eyeX, eyeY, ground = f32(blk + EYEX), f32(blk + EYEY), f32(blk + GROUND)
        for i in range(6):
            H = blk + H0 + i * STRIDE
            if not (g.read(H + OFF["draw"], 1)[0]):     # draw gate off -> not on screen
                continue
            drawn_seen += 1
            px, py = f32(H + OFF["px"]), f32(H + OFF["py"])
            sx, sy = f32(H + OFF["sx"]), f32(H + OFF["sy"])
            zx, zy = f32(H + OFF["zx"]), f32(H + OFF["zy"])
            rx, ry = px - eyeX + 320, ground - py           # the reconstruction
            dx, dy = abs(sx - rx), abs(sy - ry)
            worst_xy = max(worst_xy, dx, dy)
            # scale note: is it resting CPS, or zoomed?
            if abs(zx - KX0) > 0.01 or abs(zy - KY0) > 0.01:
                worst_scale_note.add(f"{zx:.3f}x{zy:.3f}")
            now = time.time() - t0
            if now - last_line >= 3.0:
                last_line = now
                print(f"  [{now:4.0f}s] slot{i} cid={g.read(H+OFF['cid'],1)[0]:3d}  "
                      f"engine sx,sy=({sx:7.1f},{sy:7.1f})  recon=({rx:7.1f},{ry:7.1f})  "
                      f"d=({dx:.1f},{dy:.1f})  scale=({zx:.3f},{zy:.3f})")
    except OSError:
        time.sleep(0.1)

print(f"\n--- {samples} frames, {drawn_seen} drawn-fighter reads ---")
print(f"WORST |engine screen - reconstruction| = {worst_xy:.2f} px")
if worst_xy < 3.0:
    print("  => H+0x124/H+0x128 CONFIRMED as the engine's own screen coords (matches reconstruction).")
    print("     Recording them directly removes reconstruction error. SAFE TO BAKE IN.")
else:
    print("  => MISMATCH. Either the offset is wrong or the reconstruction is - do NOT bake until resolved.")
print(f"non-resting scale values seen (H+0x130/0x134): {sorted(worst_scale_note)[:8] or 'none (all rested at 5/3,15/7)'}")
print("  (any value != 1.667x2.143 confirms per-object scale is LIVE and worth recording for zoom/juggle)")
