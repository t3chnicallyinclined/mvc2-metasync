#!/usr/bin/env python3
"""make_fixtures.py — emit a minimal VALID and a deliberately BROKEN tape v2 file.

The broken one reproduces the two real defects the contract exists to catch: magnifiers normalized
to 1.0 (the old renderer's world->screen guess), and a frame column advancing at ~15 Hz instead of
60 (a tape clocked on the wrong word). Both produce files that look fine to the naked eye.

These double as the canvas lane's day-one input: a renderer can be built against fixture_ok.json
before any producer exists.
"""
import json


def obj(L, i, sid):
    return {"L": L, "i": i, "who": 0, "sid": sid, "sx": 100.0, "sy": 200.0,
            "scaleX": 1.6667, "scaleY": 2.1429, "facing": 0, "palid": 0, "blend": 0}


def frame(n):
    return {"frame": n, "camX": 0.0, "camY": 0.0, "counts": [1] + [0] * 15,
            "hp": [144] * 6, "red": [0] * 6, "order": [0, 1, 2, 3, 4, 5],
            "meters": [0, 0], "timer": 99, "objects": [obj(0, 0, 0x8001)]}


good = {"v": 2, "producer": "fixture", "stage_id": 3, "teams": [42, 44, 50, 6, 52, 44],
        "build_id": "pe681af6cb-40e8000", "anchor_hash": "bc170fdea92f2444", "fps": 60,
        "elapsed_s": 2.0, "frames": [frame(100), frame(219)]}   # 119 frames / 2.0s = 59.5 Hz

bad = json.loads(json.dumps(good))
for f in bad["frames"]:
    f["objects"][0]["scaleX"] = 1.0     # rule 3: magnifiers normalized
    f["objects"][0]["scaleY"] = 1.0
bad["frames"][1]["frame"] = 130         # rule 6: 30 frames / 2.0s = 15 Hz -> wrong clock

with open("fixture_ok.json", "w") as f:
    json.dump(good, f, indent=1)
with open("fixture_bad.json", "w") as f:
    json.dump(bad, f, indent=1)
print("wrote fixture_ok.json and fixture_bad.json")
