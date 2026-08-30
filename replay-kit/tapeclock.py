#!/usr/bin/env python3
"""tapeclock.py — is a tape's frame column a real 60 Hz sim clock, or a wrong word?

THE BUG THIS EXISTS TO CATCH (found 2026-08-27, live). The agent used to LOCATE its frame counter by
scanning +-8 MB for "a u32 that ticks monotonically" instead of using blk+0x3CC8, which we already
know. The scan rejects any candidate that ever DECREASES — and blk+0x3CC8 mirrors GGPO's `_framecount`,
which is assigned BACKWARD on every rollback. So the one correct address is the one the filter is
guaranteed to discard, and it fails hardest on the laggiest matches. Two live ranked tapes came back
clocked on `blk+0x4db0` = slot 2's H_SPRITE_ID — a BENCHED CHARACTER'S ANIMATION — retaining 8.8% and
0.84% of their frames. Nothing in the tape looked wrong: `frame_gaps` reads 0 for any wrong counter
that happens to step by 1, so the corruption is invisible to every check we had.

HOW IT WORKS — the tape validates itself, no reference needed.
`hitstun` decrements by EXACTLY 1 per simulated frame and is present in every schema back to 0.2.6.
So for any two consecutive rows, the drop in hitstun IS the true number of sim frames between them:

    implied_d = hitstun[n] - hitstun[n+1]        (ground truth, from the sim)
    recorded_d = frame[n+1] - frame[n]           (what the frame column claims)

    ratio = median(implied_d / recorded_d)
      ~1.0  -> the frame column IS the sim clock                      PASS
      >>1.0 -> the column advances too slowly => WRONG WORD           FAIL
      <<1.0 -> the column advances faster than the sim (a vblank/free-running counter)

This distinguishes the two failure modes that look identical in the envelope:
  * clock CORRECT + frames genuinely dropped -> ratio ~1.0, but rows/span < 1
  * clock WRONG                              -> ratio far from 1.0
Only the first is a sampling problem. The second is unrecoverable — the tape cannot be repaired,
because we never learn which sim frame each row belonged to.

Usage:  tapeclock.py <dir-of-tapes> [limit]
"""
import glob
import gzip
import json
import os
import re
import sys


def cols(schema):
    """schema -> {name: index}. Split on commas OUTSIDE the [6] suffixes."""
    body = schema.strip().lstrip("[").rstrip("]")
    return {tok.strip().split("[")[0]: i
            for i, tok in enumerate(re.split(r",(?![^\[]*\])", body))}


def median(v):
    if not v:
        return None
    s = sorted(v)
    return s[len(s) // 2]


def audit(tape):
    """-> (verdict, ratio, n_samples, rows, span) or None if not enough evidence."""
    rows = tape.get("frames") or tape.get("rows") or []
    if len(rows) < 30:
        return None
    I = cols(tape["schema"])
    if "hitstun" not in I or "frame" not in I:
        return None
    fi, hi = I["frame"], I["hitstun"]

    ratios = []
    for a, b in zip(rows, rows[1:]):
        d = b[fi] - a[fi]
        if d <= 0 or d > 600:                 # rollback revisit, or a wrap — skip
            continue
        ha, hb = a[hi], b[hi]
        if not isinstance(ha, list) or not isinstance(hb, list):
            continue
        for s in range(min(len(ha), len(hb))):
            # only a clean countdown: both in hitstun, strictly decreasing, no new hit
            if ha[s] > 0 and hb[s] > 0 and hb[s] < ha[s]:
                implied = ha[s] - hb[s]
                if implied <= 600:
                    ratios.append(implied / d)

    if len(ratios) < 20:
        return None
    r = median(ratios)
    fr = [x[fi] for x in rows]
    span = max(fr) - min(fr) + 1
    verdict = "PASS" if 0.8 <= r <= 1.25 else "FAIL"
    return (verdict, r, len(ratios), len(rows), span)


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else "/opt/rr-server/gamestates"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 400
    files = [f for f in glob.glob(os.path.join(d, "*.json.gz")) if ".repaired." not in f]
    files.sort(key=os.path.getmtime, reverse=True)

    print(f"{'ver':<8} {'verdict':<7} {'ratio':>7} {'n':>5} {'rows':>6} {'span':>7} {'rows/span':>9}  tape")
    tally = {}
    for f in files[:limit]:
        try:
            t = json.load(gzip.open(f))
        except Exception:
            continue
        r = audit(t)
        if r is None:
            continue
        verdict, ratio, n, rows, span = r
        ver = t.get("ver", "?")
        tally.setdefault(ver, {"PASS": 0, "FAIL": 0})[verdict] += 1
        print(f"{ver:<8} {verdict:<7} {ratio:>7.2f} {n:>5} {rows:>6} {span:>7} "
              f"{rows/span:>8.1%}  {os.path.basename(f)[:26]}")

    print("\n--- by version ---")
    for ver in sorted(tally):
        p, fl = tally[ver]["PASS"], tally[ver]["FAIL"]
        tot = p + fl
        print(f"  {ver:<8} {p:>4} pass  {fl:>4} FAIL   ({100.0*fl/tot:.0f}% of {tot} corrupt)")


if __name__ == "__main__":
    main()
