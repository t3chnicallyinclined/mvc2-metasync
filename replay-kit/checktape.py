#!/usr/bin/env python3
"""checktape.py [watch|check <file.json.gz>|last]

Read an AGENT tape (the .json.gz the tray spools before upload) and say whether the 0.3.24
re-simulation capture actually worked. This is the acceptance test for the whole train.

!! THE SPOOL DRAINS. The uploader posts a tape between matches and deletes the local copy, so a tape
is on disk only briefly. `watch` copies anything that appears into ./tapes-kept/ the moment it shows
up, so a match played while it runs is preserved whatever the uploader does.

THE ONE NUMBER THAT MATTERS
    coverage = frames_recorded / (frame_span)
Before the fix this was ~9%: hunt_frame_counter had locked onto fighter slot 2's SPRITE ID
(blk+0x4DB0), so a row was stored only when that character's sprite changed - two live games gave
300 and 308 rows for 55 s and 59 s of play. The replay kit, polling the real counter at blk+0x3CC8,
records 7,040 frames across 118 s with zero gaps. A fixed agent should be at essentially 100%, and
anything below that means the counter is wrong again and every downstream claim is void.
"""
import glob
import gzip
import json
import os
import shutil
import sys
import time

# a .cmd console defaults to cp1252; make sure output can never be the thing that fails
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CACHE = os.path.join(os.environ.get("LOCALAPPDATA", ""), "RetroReceipts", "gs-cache")
KEEP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tapes-kept")


def ok(c):    return "[OK]" if c else "[!!]"
def warn(c):  return "[OK]" if c else "[ ~]"


def check(path):
    with gzip.open(path, "rb") as f:
        r = json.loads(f.read())
    frames = r.get("frames", [])
    print(f"\n=== {os.path.basename(path)} ===")
    print(f"ver {r.get('ver')}  reporter {r.get('reporter')}  side {r.get('side')}  "
          f"winner {r.get('winner')}  match {r.get('match_key','')[:40]}")
    print(f"teams  P1 {r.get('p1_team')}   P2 {r.get('p2_team')}")

    # ── 1. THE COVERAGE CHECK - everything else is decoration if this fails ────────────────────
    span = r.get("frame_span")
    gaps = r.get("frame_gaps")
    if span is None:
        print(f"\n{ok(False)} NO frame_span field - this tape predates 0.3.24. Nothing else to check.")
        return
    cov = (len(frames) / span * 100.0) if span else 0.0
    print(f"\n-- COVERAGE (the whole point) --")
    print(f"   frames recorded : {len(frames):,}")
    print(f"   frame span      : {span:,}   (first {r.get('frame_first')} .. last {r.get('frame_last')})")
    print(f"   gaps            : {gaps:,}")
    print(f"   truncated       : {r.get('truncated')}")
    print(f"   {ok(cov > 99.0)} COVERAGE = {cov:.1f}%   "
          f"{'GOOD - every frame captured' if cov > 99.0 else 'BAD - frames are missing, the counter is wrong again'}")
    if span:
        print(f"   (~{span / 60.0:.0f}s of play at 60fps)")

    # ── 2. the re-simulation envelope ─────────────────────────────────────────────────────────
    print(f"-- RE-SIMULATION ENVELOPE --")
    anc = r.get("anchor")
    print(f"   {ok(bool(anc))} anchor            {len(anc) if anc else 0:,} b64 chars "
          f"(gz {r.get('anchor_gz_len', 0):,} B of {r.get('anchor_sim_len', 0):,})")
    print(f"   {ok(bool(r.get('anchor_hash')))} anchor_hash       {r.get('anchor_hash')}")
    print(f"   {ok(bool(r.get('anchor_blk')))} anchor_blk/arena  0x{r.get('anchor_blk', 0):x} / 0x{r.get('anchor_arena', 0):x}")
    af, sf = r.get("anchor_frame"), r.get("start_sim_frame")
    fresh = af is not None and sf not in (None, 0) and af < sf
    print(f"   {ok(fresh)} anchor freshness  anchor_frame {af} < start_sim_frame {sf}"
          f"{'' if fresh else '   <-- STALE: the anchor belongs to an earlier match'}")
    sel = r.get("select_in_frames", 0)
    print(f"   {ok(sel > 0)} select_in         {sel:,} character-select frames "
          f"{'' if sel else '<-- WITHOUT THESE THE ANCHOR AND THE MATCH DO NOT COMPOSE'}")
    print(f"   {warn(r.get('rollbacks') == 0)} rollbacks         {r.get('rollbacks')} "
          f"{'(clean timeline)' if r.get('rollbacks') == 0 else '(GGPO rewound during capture)'}")
    print(f"   {ok(bool(r.get('build_id')))} build_id          {r.get('build_id')}")
    print(f"   seat_map          {r.get('seat_map')}"
          f"{'   <-- all zeros: offline, or never populated' if not any(x not in (0, -1) for x in (r.get('seat_map') or [])) else ''}")

    # ── 3. seat_in must be the RAW word, not a copy of the decoded one ─────────────────────────
    sch = r.get("schema", "")
    print(f"-- INPUTS --")
    # Locate seat_in BY NAME from the schema's top-level columns (ignoring [] groups), NOT by tail
    # position: 0.3.25 appends sx/sy/zx/zy and 0.3.28 appends flash/glow/layer/timer AFTER seat_in, so
    # the old `len-1` read `timer` (an int) → "'int' object is not iterable".
    def _cols(s):
        s = s.strip()
        s = s[1:] if s.startswith("[") else s
        s = s[:-1] if s.endswith("]") else s
        out, depth, cur = [], 0, ""
        for ch in s:
            if ch == "[": depth += 1; cur += ch
            elif ch == "]": depth -= 1; cur += ch
            elif ch == "," and depth == 0: out.append(cur.strip()); cur = ""
            else: cur += ch
        if cur.strip(): out.append(cur.strip())
        return out
    names = [c.split("[")[0] for c in _cols(sch)]
    has_seat = "seat_in" in names
    print(f"   {ok(has_seat)} schema has seat_in[2]"
          f"{'' if has_seat else '   <-- got columns: ...' + ','.join(names[-4:])}")
    if frames and isinstance(frames[0], list) and has_seat:
        try:
            i_seat = names.index("seat_in")          # BY NAME (was len-1, broke on appended columns)
            seat_vals = {tuple(f[i_seat]) for f in frames if f[i_seat] != [0, 0]}
            p_vals = {(f[1], f[2]) for f in frames if (f[1], f[2]) != (0, 0)}
            print(f"   {ok(bool(seat_vals))} seat_in non-zero on {sum(1 for f in frames if f[i_seat] != [0, 0]):,} frames "
                  f"({len(seat_vals)} distinct)")
            print(f"   {ok(bool(seat_vals) and seat_vals != p_vals)} seat_in differs from p1_in/p2_in "
                  f"({len(p_vals)} distinct decoded) - proves it is the RAW word, not the downstream copy")
        except Exception as e:
            print(f"   !! could not read the input columns: {e}")

    print(f"\n   VERDICT: {'PASS - this tape can be re-simulated' if cov > 99 and anc and sel and fresh else 'FAIL - see the marks above'}")


def watch():
    os.makedirs(KEEP, exist_ok=True)
    print(f"watching {CACHE}")
    print(f"keeping copies in {KEEP}")
    print("play a match. the uploader deletes tapes after upload, so this grabs them first.")
    print("ctrl-c to stop.\n")
    seen = set()
    try:
        while True:
            for p in glob.glob(os.path.join(CACHE, "*.json.gz")):
                if p in seen:
                    continue
                seen.add(p)
                time.sleep(0.4)                      # let the writer finish
                dst = os.path.join(KEEP, os.path.basename(p))
                try:
                    shutil.copy2(p, dst)
                    print(f"kept {os.path.basename(p)}")
                    check(dst)
                except Exception as e:
                    print(f"could not keep {p}: {e}")
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nstopped.")


def last():
    pool = glob.glob(os.path.join(KEEP, "*.json.gz")) + glob.glob(os.path.join(CACHE, "*.json.gz"))
    if not pool:
        print(f"no tapes in {KEEP} or {CACHE}.")
        print("run `checktape.py watch` BEFORE playing - the uploader drains the spool between matches.")
        return
    check(max(pool, key=os.path.getmtime))


if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "last"
    if c == "watch":
        watch()
    elif c == "check":
        check(sys.argv[2])
    else:
        last()
