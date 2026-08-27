#!/usr/bin/env python3
"""tapev2_validate.py <tape.json[.gz]> - enforce the TAPE v2 render contract.

Spec: docs/TAPE-V2-SCHEMA.md. This is the executable half of it.

WHY A VALIDATOR AND NOT A README. Tape v2 has THREE producers (hand-built fixtures, extended local
capture, server-side re-simulation) feeding ONE renderer. Without a gate they drift, and the renderer
grows per-producer special cases — which is exactly how the previous renderer ended up
re-implementing the engine. A file either satisfies the contract or it does not.

Rule 6 is the one that matters most and the one nobody had. It would have caught this year's worst
capture bug on day one: the agent located its frame counter by scanning for "a u32 that ticks
monotonically", which structurally could not select the real counter (that one runs BACKWARD on every
rollback), and shipped tapes clocked on a benched character's SPRITE ID. Those tapes looked perfect —
`frame_gaps` reads 0 for any wrong word that happens to step by 1 — while retaining under 9% of their
frames. A frame column that does not advance at ~60 Hz against wall clock is unrepairable, because
you never learn which sim frame each row belonged to.

Exit 0 = valid. Exit 1 = rejected (reasons printed). Warnings never fail the run.
"""
import gzip
import json
import sys

MAX_CID = 56
LAYERS = 16
CPS_X, CPS_Y = 640.0 / 384.0, 480.0 / 224.0     # ~1.667, ~2.143 — the FINAL magnifiers


def load(path):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt") as f:
        return json.load(f)


def validate(t):
    errs, warns = [], []

    if t.get("v") != 2:
        errs.append(f"header: v must be 2, got {t.get('v')!r}")
    if t.get("producer") not in ("fixture", "capture", "resim"):
        errs.append(f"header: producer must be fixture|capture|resim, got {t.get('producer')!r}")

    teams = t.get("teams") or []
    if len(teams) != 6:
        errs.append(f"header: teams must have 6 slots, got {len(teams)}")
    else:
        bad = [(i, c) for i, c in enumerate(teams) if not isinstance(c, int) or c > MAX_CID]
        if bad:
            errs.append(f"rule 5: teams entries exceed MAX_CID({MAX_CID}): {bad}")

    frames = t.get("frames") or []
    if not frames:
        errs.append("no frames")
        return errs, warns

    for n, fr in enumerate(frames):
        objs = fr.get("objects") or []
        counts = fr.get("counts") or []
        tag = f"frame[{n}] (frame={fr.get('frame')})"

        # rule 1 — counts must agree with what was emitted
        if len(counts) != LAYERS:
            errs.append(f"{tag}: counts must have {LAYERS} entries, got {len(counts)}")
        else:
            seen = [0] * LAYERS
            for o in objs:
                L = o.get("L")
                if isinstance(L, int) and 0 <= L < LAYERS:
                    seen[L] += 1
            for L in range(LAYERS):
                if seen[L] != counts[L]:
                    errs.append(f"{tag}: rule 1 layer {L}: counts says {counts[L]}, emitted {seen[L]}")

        # rule 2 — non-decreasing L, strictly increasing i within a layer
        lastL, lastI = -1, -1
        for o in objs:
            L, i = o.get("L"), o.get("i")
            if not isinstance(L, int) or not isinstance(i, int):
                errs.append(f"{tag}: rule 2: object missing integer L/i: {o!r}")
                break
            if L < lastL:
                errs.append(f"{tag}: rule 2: draw order went backward (L {lastL} -> {L})")
                break
            if L == lastL and i <= lastI:
                errs.append(f"{tag}: rule 2: i not increasing within layer {L} ({lastI} -> {i})")
                break
            lastL, lastI = L, i   # a new layer resets the `i` baseline, which is intended

        for o in objs:
            # rule 3 — the normalize-the-magnifier bug
            sx_, sy_ = o.get("scaleX"), o.get("scaleY")
            if sx_ == 1.0 and sy_ == 1.0:
                errs.append(f"{tag}: rule 3: scaleX/Y are exactly 1.0 - magnifiers were normalized "
                            f"(expect ~{CPS_X:.3f}/{CPS_Y:.3f}); never re-apply CPS either")
            # rule 4 — sid bit 15 must survive
            sid = o.get("sid")
            if not isinstance(sid, int):
                errs.append(f"{tag}: sid must be an int, got {sid!r}")
            elif sid > 0xFFFF:
                errs.append(f"{tag}: sid {sid} exceeds u16")

    # rule 4 (corpus-level) — if NOTHING in the tape has bit 15 set, it was probably masked
    sids = [o.get("sid") for fr in frames for o in (fr.get("objects") or []) if isinstance(o.get("sid"), int)]
    if sids and not any(s & 0x8000 for s in sids):
        warns.append("rule 4: no sid in the whole tape has bit 15 set — verify it was not masked off")

    # rule 6 — THE CLOCK CHECK
    fnums = [fr.get("frame") for fr in frames if isinstance(fr.get("frame"), int)]
    el = t.get("elapsed_s")
    if len(fnums) >= 2:
        span = max(fnums) - min(fnums)
        if el:
            hz = span / float(el)
            if not (45.0 <= hz <= 75.0):
                errs.append(f"rule 6: frame column advances at {hz:.2f} Hz over {el}s - not a 60 Hz "
                            f"sim clock. The tape is clocked on the wrong word and is UNREPAIRABLE.")
        else:
            warns.append("rule 6: no `elapsed_s` in the tape — the clock check could not run. "
                         "Producers SHOULD emit wall-clock duration so this can be enforced.")
        if span + 1 < len(fnums):
            warns.append(f"rule 6: {len(fnums)} rows across a span of {span+1} frames — duplicates?")
    return errs, warns


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__.strip().splitlines()[0])
    t = load(sys.argv[1])
    errs, warns = validate(t)
    for w in warns:
        print(f"  warn: {w}")
    if errs:
        # ASCII only: the Windows console is cp1252 and any non-ASCII here raises
        # UnicodeEncodeError *while reporting the failure*, turning a clean reject into a traceback.
        print(f"\nREJECTED - {len(errs)} violation(s):")
        for e in errs:
            print(f"  x {e}")
        sys.exit(1)
    print(f"\nVALID - tape v2, producer={t.get('producer')}, "
          f"{len(t.get('frames') or [])} frames"
          + (f", {len(warns)} warning(s)" if warns else ""))


if __name__ == "__main__":
    main()
