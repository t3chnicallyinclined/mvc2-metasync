#!/usr/bin/env python3
"""tape_to_flycast_movie.py <tape.json[.gz]> [out.txt] - 0.3.26 CONFIRMED-input tape -> maplecast movie.

The proven pipeline (gsta-verification-harness, reproduced a Steam match BIT-EXACT in flycast) converts
per-frame inputs into a maplecast-flycast 6-column movie fed via MAPLECAST_MOVIE_IN. That harness used
the PREDICTED `battle_in`/seat_in (G+0x218) and hit a constant −6-frame skew - the tape's rollback-laden
capture. THIS converter reads the 0.3.26 `confirmed_in` column instead: GGPO's CONFIRMED (post-rollback)
inputs from the InputQueue ring, the exact stream dojo's pure-forward replay consumes. With confirmed
inputs re-based to frame 0, the replay lands frame-exact (no skew) - the fix the determinism test named.

Composition (verified by the harness's bit-exact run):
  Steam raw pad word (G+0x218) --ROSETTA--> semantic (Input_DEC) --DC decode--> DC kcode (active-low).
Movie line = `b1 lt1 rt1 b2 lt2 rt2`: P1 kcode u16 (active-low), P1 L/R analog trigger bytes, P2 same.
Routing identity: seat0 -> P1 (left), seat1 -> P2 (right).

! Requires a 0.3.26+ tape (has `confirmed_in`). On an older tape it falls back to the predicted stream
with a loud warning (that stream carries the −6 skew and will NOT replay frame-exact).
"""
import base64
import gzip
import json
import re
import struct
import sys

# raw Steam pad bit -> semantic name (Rosetta, derived + bit-exact-verified by the harness)
ROSETTA = {0x0010: "U", 0x0020: "R", 0x0040: "D", 0x0080: "L",
           0x0200: "A1", 0x0800: "A2", 0x1000: "HP", 0x2000: "HK", 0x4000: "LK", 0x8000: "LP"}
GB = {"U": 0x2000, "D": 0x1000, "L": 0x0800, "R": 0x0400, "LP": 0x0200, "HP": 0x0100,
      "LK": 0x0040, "HK": 0x0020, "A1": 0x0080, "A2": 0x0010, "START": 0x8000}
# semantic name -> DC pad BIT INDEX (game routine loc_8c010080 / tape_to_movie.py DC_PAD_BIT)
DC_PAD_BIT = {"U": 4, "D": 5, "L": 6, "R": 7, "START": 3, "LP": 10, "HP": 9, "LK": 2, "HK": 1, "A1": 8, "A2": 0}


def raw_to_sem(raw):
    sem = 0
    for bit, name in ROSETTA.items():
        if raw & bit:
            sem |= GB[name]
    return sem


def sem_to_cols(sem):
    w = 0xFFFF                              # active-low: a pressed button CLEARS its bit
    for name, idx in DC_PAD_BIT.items():
        if sem & GB[name]:
            w &= ~(1 << idx) & 0xFFFF
    lt = 0xFF if sem & GB["A2"] else 0x00
    rt = 0xFF if sem & GB["A1"] else 0x00
    return w, lt, rt


def load(path):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt") as f:
        return json.load(f)


def decode_triples(b64):
    raw = gzip.decompress(base64.b64decode(b64))
    return [struct.unpack_from("<III", raw, i * 12) for i in range(len(raw) // 12)]


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__.strip().splitlines()[0])
    tape = load(sys.argv[1])
    out = sys.argv[2] if len(sys.argv) > 2 else "flycast_movie.txt"

    if tape.get("confirmed_in"):
        seq = decode_triples(tape["confirmed_in"])          # [(frame, seat0_confirmed, seat1_confirmed)]
        src = "CONFIRMED (0.3.26 ring) - frame-exact"
    else:
        # fallback: predicted stream from the frames' seat_in column (WILL carry the rollback skew)
        cols = [c.strip().split("[")[0] for c in re.split(r",(?![^\[]*\])", tape["schema"].strip().lstrip("[").rstrip("]"))]
        I = {c: i for i, c in enumerate(cols)}
        rows = tape.get("frames") or []
        if "seat_in" not in I:
            sys.exit("tape has neither confirmed_in nor seat_in - cannot build a movie")
        seq = [(r[I["frame"]], r[I["seat_in"]][0], r[I["seat_in"]][1]) for r in rows]
        src = "PREDICTED seat_in (G+0x218) - ! carries the ~6-frame rollback skew, will NOT replay frame-exact"
        print("!! no confirmed_in column - falling back to the predicted stream. Re-record on agent 0.3.26+.")

    seq.sort(key=lambda t: t[0])
    # collapse duplicate frame keys (last wins) and re-base to 0 at the first confirmed frame
    by_frame = {}
    for f, s0, s1 in seq:
        by_frame[f] = (s0, s1)
    frames = sorted(by_frame)
    base = frames[0]
    lines = [f"# {src}  frames {len(frames)}  span {frames[-1]-base+1}  base_frame {base}"]
    # emit CONTIGUOUS from base; a gap (shouldn't happen on a confirmed stream) repeats the last input
    last = (0, 0)
    for f in range(base, frames[-1] + 1):
        s0, s1 = by_frame.get(f, last)
        last = (s0, s1)
        b1, lt1, rt1 = sem_to_cols(raw_to_sem(s0))          # seat0 -> P1
        b2, lt2, rt2 = sem_to_cols(raw_to_sem(s1))          # seat1 -> P2
        lines.append("%04x %02x %02x %04x %02x %02x" % (b1, lt1, rt1, b2, lt2, rt2))

    with open(out, "w", newline="\n") as fo:
        fo.write("\n".join(lines) + "\n")
    print(f"wrote {out}")
    print(f"  source: {src}")
    print(f"  frames {len(frames)}  span {frames[-1]-base+1}  ({'DENSE' if len(frames)==frames[-1]-base+1 else 'HAS GAPS'})")
    nz = sum(1 for f in frames if by_frame[f][0] or by_frame[f][1])
    print(f"  frames with input: {nz}")
    print("  teams p1", tape.get("p1_team"), " p2", tape.get("p2_team"), " stage", tape.get("stage_id"))
    print("  feed to flycast: MAPLECAST_MOVIE_IN=" + out + "  (identity routing seat0->P1)")


if __name__ == "__main__":
    main()
