#!/usr/bin/env python3
"""spotcheck_inject.py <tape.json[.gz]> <inject.gsta> <row>

Proves the state-injection stream is a FAITHFUL, DRIFT-FREE copy of the tape's
recorded per-frame state at a given row (by construction — injection copies the
recorded state, it does not compute forward). Decodes .gsta record[row] the way
the engine's deserialize() does, remaps DC->tape slots, and asserts px/py/sid/hp
match the tape row. Use this as the tape-side numeric reference when comparing the
LIVE rendered .zcst frame in the build session (the live-pixel gate).
"""
import gzip, json, re, struct, sys

TAPE_TO_DC = {0: 0, 2: 2, 4: 4, 1: 5, 3: 1, 5: 3}
DC_FROM_TAPE = {dc: tp for tp, dc in TAPE_TO_DC.items()}


def load(p):
    op = gzip.open if p.endswith(".gz") else open
    with op(p, "rt") as f:
        return json.load(f)


def sidx(t):
    cols = [c.strip().split("[")[0]
            for c in re.split(r",(?![^\[]*\])",
                              t["schema"].strip().lstrip("[").rstrip("]"))]
    return {c: i for i, c in enumerate(cols)}


def main():
    tape = load(sys.argv[1])
    gsta = open(sys.argv[2], "rb").read()
    row = int(sys.argv[3])
    I = sidx(tape)
    r = tape["frames"][row]

    assert gsta[:4] == b"GSI1"
    n = struct.unpack_from("<I", gsta, 4)[0]
    assert row < n, f"row {row} >= {n} records"
    base = 8 + row * 380
    gf = struct.unpack_from("<I", gsta, base)[0]
    p = gsta[base + 4: base + 4 + 376]

    print(f"row {row}  tape gframe={r[I['frame']]}  gsta dc_game_frame={gf}  "
          f"(match={r[I['frame']] == gf})")
    print(f"{'dc':>2} {'tape':>4} | {'hp':>4} {'sid':>5} {'facing':>6} "
          f"{'px':>10} {'py':>10}   [gsta==tape]")
    ok = True
    for dc in range(6):
        tp = DC_FROM_TAPE[dc]
        thp = int(r[I["hp"]][tp]); tsid = int(r[I["sid"]][tp])
        tfac = int(r[I["facing"]][tp])
        tpx = float(r[I["px"]][tp]); tpy = float(r[I["py"]][tp])
        o = 25 + dc * 57
        g_face, g_hp = struct.unpack_from("<xxBB", p, o)  # +2 facing,+3 health
        g_sid = struct.unpack_from("<H", p, o + 32)[0]
        g_px, g_py = struct.unpack_from("<ff", p, o + 8)
        same = (g_hp == thp and g_sid == tsid and g_face == tfac
                and abs(g_px - tpx) < 1e-3 and abs(g_py - tpy) < 1e-3)
        ok = ok and same
        print(f"{dc:>2} {tp:>4} | {thp:>4} {tsid:>5} {tfac:>6} "
              f"{tpx:>10.2f} {tpy:>10.2f}   {'OK' if same else 'MISMATCH'}")
    print("RESULT:", "FAITHFUL (injection stream == tape row)" if ok else "MISMATCH")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
