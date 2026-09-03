#!/usr/bin/env python3
"""replay_receipt.py -- Workstream G: replay a RETRO RECEIPTS tape's RECEIPT (char-select anchor + per-frame
seat words) inside a real Steam MvC2 process driven by the d3dcap shim, and gate the regenerated fighters
against the tape's own rows.

    python replay_receipt.py --tape 59613666                    # prepare + run + gate (game must be at CHARACTER SELECT)
    python replay_receipt.py --tape 59613666 --prepare-only     # decode anchor/inputs, relocate for the live process
    python replay_receipt.py --gate-only <out_dir>              # re-gate an existing tick log against the tape

Mechanism (docs/RECEIPT-PLAYER-G.md):
  1. anchor  = tape["anchor"] (gzip+base64 of blk[0..0x33B18) taken at character select, clock tape["anchor_frame"]),
     relocated to the LIVE process's blk (rrtape4.restore_anchor's rule: every 8-aligned u64 inside
     [anchor_blk, anchor_blk+0x33B18) moves by new_blk-anchor_blk; the arena branch only with --force-arena).
  2. inputs  = one (entry_clock, seat0, seat1) per sim frame, keyed by the clock the shim's FrameTick hook reads at
     entry of FUN_140607d60 (the tick that runs while blk+0x3CC8 == c consumes inputs[c]):
        char select : select_in (f, s0, s1) sampled while clock == f -> inputs[f-1]        (latch: stored, then ticked)
        battle      : confirmed_in (N, s0, s1) = GGPO GameInput.frame N -> inputs[N]       (--battle-src confirmed)
                      or rows' seat_in sampled at clock f -> inputs[f-1]                   (--battle-src rows)
     Frames with no record get (0, 0) so the pad cannot leak in; --shift k moves every battle key by k for experiments.
  3. the shim (d3dcap/receipt_player.inl) writes the anchor into blk at the next tick, then on every tick overwrites
     game_state+0x218/+0x21C (0x140AC6F58/5C) with inputs[clock] and appends a 128-B state record.
  4. gate: for every tape row (frame f) find the tick record with clock == f and compare hp/px/py of the six slots.

Safety: refuses unless the live process is OFFLINE (*(exe+0x2E10B98) == 0 and the net flag *(*(exe+0xACD3A8)+0x1cd) == 0)
and, unless --any-mode, at CHARACTER SELECT (blk+0x3CB8 byte[2] == 1). Read-only RPM here; every write goes through the
shim's command file and is refused there too if a GGPO session is live. ROM/game-derived bytes stay in %TEMP%.
"""
import argparse
import base64
import ctypes
import ctypes.wintypes as w
import glob
import gzip
import json
import os
import struct
import sys
import time

GHIDRA_BASE = 0x140000000
RVA_GAME_STATE_PTR = 0xACD3A0      # PTR_DAT_140acd3a0 -> game_state (0x140AC6D40)
RVA_SESSION2_PTR = 0xACD3A8        # DAT_140acd3a8 -> net session object; +0x1cd != 0 = GGPO path in FUN_140039de0
RVA_BLK_PTR = 0x2EDF560            # DAT_142edf560 = blk (what the walker/dispatcher dereference)
RVA_GGPO_SESSION = 0x2E10B98       # ggpo session handle (0 offline)
GS_ARENA = 0x0                     # *(game_state+0) = the 256 MiB arena (reader.rs ARENA_PTR_OFF 0xac6d40)
GS_PAUSE = 0x780
BLK_SIZE = 0x33B18
CLOCK_OFF = 0x3CC8
MODE_OFF = 0x3CB8
H0, HSTRIDE = 0x3DB8, 0x738
SLOT_PTRS = 0x32500
ARENA_SIZE = 0x10000000
REC_FMT = "<6I8s" + "BBHffHBB" * 6
REC_SIZE = struct.calcsize(REC_FMT)
assert REC_SIZE == 128
CAP_DIR = os.path.join(os.environ.get("TEMP", "."), "rrcap")

k32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi
k32.OpenProcess.restype = w.HANDLE
k32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
k32.ReadProcessMemory.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.ReadProcessMemory.restype = w.BOOL
psapi.EnumProcessModules.argtypes = [w.HANDLE, ctypes.POINTER(ctypes.c_void_p), w.DWORD, w.LPDWORD]
psapi.GetModuleFileNameExW.argtypes = [w.HANDLE, ctypes.c_void_p, w.LPWSTR, w.DWORD]


def fnv1a64(b):
    """the agent's anchor_hash (reader.rs fnv1a64). NOTE its prime literal 0x1000_0000_01b3 is 2^44+0x1b3, not the
    FNV prime 2^40+0x1b3 -- so this is 'FNV-1a with the agent's constant', reproduced exactly for the identity check."""
    h = 0xcbf29ce484222325
    for x in b:
        h ^= x
        h = (h * 0x1000000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


def find_tape(spec):
    if os.path.exists(spec):
        return spec
    root = os.path.join(os.environ["LOCALAPPDATA"], "RetroReceipts", "gs-cache")
    hits = sorted(glob.glob(os.path.join(root, "*_%s_*.json.gz" % spec)))
    if len(hits) != 1:
        sys.exit("tape %s: %d matches in %s" % (spec, len(hits), root))
    return hits[0]


def triples(b64):
    raw = gzip.decompress(base64.b64decode(b64))
    return [struct.unpack_from("<III", raw, i) for i in range(0, len(raw) - 11, 12)]


class Proc:
    """read-only view of the live game (PROCESS_VM_READ only)."""
    def __init__(self, name="MarvelVsCapcomFightingCollection"):
        import subprocess
        out = subprocess.check_output(["tasklist", "/FI", "IMAGENAME eq %s.exe" % name, "/FO", "CSV", "/NH"]).decode(errors="replace")
        self.pid = None
        for line in out.splitlines():
            if line.startswith('"'):
                self.pid = int(line.split('","')[1])
        if not self.pid:
            sys.exit("game process %s.exe not running" % name)
        self.h = k32.OpenProcess(0x10 | 0x400, False, self.pid)
        if not self.h:
            sys.exit("OpenProcess(%d) failed" % self.pid)
        mods = (ctypes.c_void_p * 512)()
        needed = w.DWORD()
        psapi.EnumProcessModules(self.h, mods, ctypes.sizeof(mods), ctypes.byref(needed))
        self.base = mods[0]
        self.modules = []
        buf = ctypes.create_unicode_buffer(1024)
        for i in range(min(512, needed.value // ctypes.sizeof(ctypes.c_void_p))):
            psapi.GetModuleFileNameExW(self.h, mods[i], buf, 1024)
            self.modules.append(buf.value)

    def read(self, a, n):
        buf = ctypes.create_string_buffer(n)
        got = ctypes.c_size_t()
        return buf.raw[:got.value] if k32.ReadProcessMemory(self.h, ctypes.c_void_p(a), buf, n, ctypes.byref(got)) else None

    def q(self, a):
        b = self.read(a, 8); return struct.unpack("<Q", b)[0] if b else None

    def d(self, a):
        b = self.read(a, 4); return struct.unpack("<I", b)[0] if b else None

    def rv(self, rva):
        return self.base + rva

    def live(self):
        gs = self.q(self.rv(RVA_GAME_STATE_PTR))
        blk = self.q(self.rv(RVA_BLK_PTR))
        s2 = self.q(self.rv(RVA_SESSION2_PTR))
        return {
            "pid": self.pid, "exe_base": self.base, "game_state": gs, "blk": blk,
            "arena": self.q(gs) if gs else None,
            "ggpo_session": self.q(self.rv(RVA_GGPO_SESSION)),
            "net_flag": (self.read(s2 + 0x1cd, 1) or b"\xff")[0] if s2 else None,
            "paused": self.d(gs + GS_PAUSE) if gs else None,
            "clock": self.d(blk + CLOCK_OFF) if blk else None,
            "mode": list(self.read(blk + MODE_OFF, 5) or b"") if blk else None,
            "shim": any(m.lower().endswith("d3dcap.dll") for m in self.modules),
        }


# ── the command channel (matches receipt_player.inl) ─────────────────────────────────────────────
def cmd(line, timeout=8.0):
    ack = os.path.join(CAP_DIR, "CMD.ack")
    if os.path.exists(ack):
        os.remove(ack)
    with open(os.path.join(CAP_DIR, "CMD.tmp"), "w") as f:
        f.write(line + "\n")
    os.replace(os.path.join(CAP_DIR, "CMD.tmp"), os.path.join(CAP_DIR, "CMD"))
    t0 = time.time()
    while time.time() - t0 < timeout:
        if os.path.exists(ack):
            time.sleep(0.05)
            try:
                r = open(ack).read().strip()
            except OSError:
                continue
            print("  shim: %s" % r)
            return r
        time.sleep(0.05)
    print("  shim: NO ACK for %r (is the shim's worker thread alive? see %s\\d3dcap.log)" % (line.split()[0], CAP_DIR))
    return None


def status():
    try:
        return json.load(open(os.path.join(CAP_DIR, "receipt_status.json")))
    except (OSError, ValueError):
        return None


# ── prepare: anchor + inputs from the tape ───────────────────────────────────────────────────────
def relocate(anchor, old_blk, new_blk, old_arena, new_arena, force_arena):
    buf = bytearray(anchor)
    d_blk, d_arena = new_blk - old_blk, new_arena - old_arena
    nb = na = 0
    for off in range(0, len(buf) - 7, 8):
        p = int.from_bytes(buf[off:off + 8], "little")
        if old_blk <= p < old_blk + BLK_SIZE:
            buf[off:off + 8] = (p + d_blk).to_bytes(8, "little"); nb += 1
        elif old_arena <= p < old_arena + ARENA_SIZE:
            na += 1
            print("  arena-range word at anchor+0x%05x = 0x%x (arena+0x%x)%s" % (off, p, p - old_arena,
                  " -> relocated" if (d_arena and force_arena) else ""))
            if d_arena and force_arena:
                buf[off:off + 8] = (p + d_arena).to_bytes(8, "little")
    return bytes(buf), nb, na, d_blk, d_arena


def build_inputs(tape, battle_src, shift, gap_fill=True):
    """-> dict entry_clock -> (s0, s1), plus a description of the segments."""
    ins = {}
    seg = {}
    sel = triples(tape["select_in"])
    # select_in is sampled while clock == f; that latch is what the tick that PRODUCED f consumed, i.e. the
    # tick that ran at entry clock f-1. Later occurrences of a frame (GGPO rolled the clock back) win.
    for f, s0, s1 in sel:
        if f >= 1:
            ins[f - 1] = (s0, s1)
    seg["select"] = (min(ins), max(ins), len(sel)) if ins else None
    rows = tape["frames"]
    sch = [s.strip() for s in tape["schema"].strip("[]").split(",")]
    i_seat = sch.index("seat_in[2]")
    if battle_src == "confirmed" and tape.get("confirmed_in"):
        conf = triples(tape["confirmed_in"])
        for n, s0, s1 in conf:
            ins[n + shift] = (s0, s1)
        seg["battle"] = ("confirmed_in", conf[0][0] + shift, conf[-1][0] + shift, len(conf))
    else:
        first = None
        for r in rows:
            f = r[0]
            ins[f - 1 + shift] = tuple(r[i_seat])
            first = f if first is None else first
        seg["battle"] = ("rows.seat_in", first - 1 + shift, rows[-1][0] - 1 + shift, len(rows))
    if gap_fill:
        lo, hi = min(ins), max(ins)
        gaps = [c for c in range(lo, hi + 1) if c not in ins]
        for c in gaps:
            ins[c] = (0, 0)
        seg["gap_filled"] = (len(gaps), gaps[0] if gaps else None, gaps[-1] if gaps else None)
    return ins, seg


def prepare(tape, out, live, force_arena, battle_src, shift, ignore_arena=False):
    os.makedirs(out, exist_ok=True)
    anchor = gzip.decompress(base64.b64decode(tape["anchor"]))
    if len(anchor) != BLK_SIZE:
        sys.exit("anchor is %d bytes, expected %d" % (len(anchor), BLK_SIZE))
    h = fnv1a64(anchor)
    if "%016x" % h != tape.get("anchor_hash", "%016x" % h):
        sys.exit("anchor hash mismatch: %016x vs tape %s" % (h, tape["anchor_hash"]))
    a_clock = struct.unpack_from("<I", anchor, CLOCK_OFF)[0]
    a_mode = list(anchor[MODE_OFF:MODE_OFF + 5])
    cids = [anchor[H0 + i * HSTRIDE + 0x6C0] for i in range(6)]
    print("anchor: %d B, fnv %016x OK, clock %d (tape anchor_frame %d), mode %s, cids %s, blk 0x%x arena 0x%x" % (
        len(anchor), h, a_clock, tape["anchor_frame"], a_mode, cids, tape["anchor_blk"], tape["anchor_arena"]))
    reloc, nb, na, d_blk, d_arena = relocate(anchor, tape["anchor_blk"], live["blk"], tape["anchor_arena"],
                                             live["arena"], force_arena)
    print("relocated for blk 0x%x (delta %+#x): %d intra-blk pointers; %d arena-range words (arena delta %+#x, %s)" % (
        live["blk"], d_blk, nb, na, d_arena, "applied" if (d_arena and force_arena) else ("no-op" if not d_arena else "NOT applied -- --force-arena")))
    if d_arena and not force_arena and not ignore_arena:
        sys.exit("REFUSING: arena moved (%+#x); the arena branch has never been exercised (HANDOVER-2026-08-26-REPLAY-2 s1). "
                 "Look at the words printed above: --force-arena relocates them, --ignore-arena leaves them (they are "
                 "constants like 0x10000000, not pointers, on tape 59613666)." % d_arena)
    # self-check, same rule as the shim: six self-pointers all zero (fresh block) or a permutation of slot bases
    ptrs = [struct.unpack_from("<Q", reloc, SLOT_PTRS + 8 * k)[0] for k in range(6)]
    if any(ptrs):
        rel = [(p - live["blk"] - H0) for p in ptrs]
        if any(r < 0 or r % HSTRIDE or r // HSTRIDE >= 6 for r in rel) or sorted(r // HSTRIDE for r in rel) != list(range(6)):
            sys.exit("self-check FAILED on the relocated anchor: %s" % [hex(p) for p in ptrs])
        print("self-check: slot-pointer permutation %s" % [r // HSTRIDE for r in rel])
    else:
        print("self-check: fresh block (six self-pointers zero; FUN_140628020 fills them at match start)")
    open(os.path.join(out, "anchor_reloc.bin"), "wb").write(reloc)
    ins, seg = build_inputs(tape, battle_src, shift)
    with open(os.path.join(out, "inputs.bin"), "wb") as f:
        for c in sorted(ins):
            f.write(struct.pack("<III", c, *ins[c]))
    nz = sum(1 for v in ins.values() if v[0] or v[1])
    print("inputs: %d entry clocks %d..%d (%d non-zero); segments %s" % (len(ins), min(ins), max(ins), nz, seg))
    meta = {"tape_id": tape["id"], "anchor_clock": a_clock, "anchor_mode": a_mode, "anchor_cids": cids,
            "reloc_blk": live["blk"], "reloc_arena": live["arena"], "d_blk": d_blk, "d_arena": d_arena,
            "ptrs_blk": nb, "ptrs_arena": na, "inputs": {"n": len(ins), "lo": min(ins), "hi": max(ins), "nonzero": nz},
            "segments": seg, "battle_src": battle_src, "shift": shift,
            "tape": {"frame_first": tape["frame_first"], "frame_last": tape["frame_last"], "frames": tape["frame_count"],
                     "start_sim_frame": tape["start_sim_frame"], "p1_team": tape["p1_team"], "p2_team": tape["p2_team"],
                     "stage_id": tape["stage_id"], "rollbacks": tape.get("rollbacks"), "ver": tape.get("ver"),
                     "local_pn": tape.get("local_pn"), "seat_map": tape.get("seat_map")}}
    json.dump(meta, open(os.path.join(out, "prepare.json"), "w"), indent=1)
    return meta


# ── run ──────────────────────────────────────────────────────────────────────────────────────────
def focus_game(pid):
    """the offline loop only ticks while game_state+0x780 == 0, and the game pauses when it loses focus."""
    try:
        import subprocess
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "$w = New-Object -ComObject WScript.Shell; $w.AppActivate(%d) | Out-Null" % pid], timeout=10)
    except Exception as e:  # noqa
        print("  (focus: %s)" % e)


def run(tape, out, meta, live, proc, timeout_s, speed):
    log = os.path.join(out, "ticks.bin")
    for stale in ("ticks.bin",):
        p = os.path.join(out, stale)
        if os.path.exists(p):
            os.remove(p)
    if cmd("status") is None:
        sys.exit("the shim did not answer: launch the game through d3dcap/launch_suspended.ps1 (or session-guided.ps1) so d3dcap.dll is inside it")
    st = status()
    if not st or not st.get("hooked"):
        sys.exit("FrameTick hook is not installed in this process (status %s) -- see %s\\d3dcap.log '[mh] FrameTick'" % (st, CAP_DIR))
    if st.get("online"):
        sys.exit("REFUSED: the shim reports a live GGPO session")
    r = cmd("start %s" % log)
    if not r or not r.startswith("OK"):
        sys.exit("start failed")
    r = cmd("inputs %s" % os.path.join(out, "inputs.bin"))
    if not r or not r.startswith("OK"):
        sys.exit("inputs failed")
    if speed and speed > 1:
        cmd("speed %d" % speed)
    focus_game(proc.pid)
    time.sleep(0.5)
    r = cmd("anchor %x %x %d %s" % (meta["reloc_blk"], meta["reloc_arena"], 1 if meta["d_arena"] else 0,
                                     os.path.join(out, "anchor_reloc.bin")), timeout=6.0)
    if not r or not r.startswith("OK"):
        cmd("stop")
        sys.exit("anchor load failed: %s" % r)
    last_tape = tape["frame_last"]
    t0 = time.time()
    last_print = 0
    entered_battle = None
    stall = 0
    prev_clock = None
    while time.time() - t0 < timeout_s:
        time.sleep(0.5)
        st = status() or {}
        clk = st.get("clock")
        mode = st.get("mode")
        if mode and mode[2] == 2 and entered_battle is None:
            entered_battle = clk
            print("  BATTLE entered at clock %s (tape start_sim_frame %d)" % (clk, tape["start_sim_frame"]))
        if time.time() - last_print >= 5:
            last_print = time.time()
            print("  t=%4.0fs clock=%s mode=%s ticks=%s fed=%s paused=%s" % (
                time.time() - t0, clk, mode, st.get("ticks"), st.get("fed"), st.get("paused")))
        if clk == prev_clock:
            stall += 1
            if stall == 20:
                print("  clock has not moved for 10 s (paused=%s) -- is the game window focused?" % st.get("paused"))
                focus_game(proc.pid)
        else:
            stall = 0
        prev_clock = clk
        if clk is not None and clk > last_tape + 5:
            print("  clock %d passed the tape's last row %d" % (clk, last_tape))
            break
        if entered_battle is not None and mode and mode[2] != 2 and clk and clk > entered_battle + 120:
            print("  left battle mode at clock %s" % clk)
            break
    cmd("stop")
    if speed and speed > 1:
        cmd("speed 1")
    return log


# ── gate ─────────────────────────────────────────────────────────────────────────────────────────
def read_log(path):
    raw = open(path, "rb").read()
    recs = []
    for i in range(0, len(raw) - REC_SIZE + 1, REC_SIZE):
        v = struct.unpack_from(REC_FMT, raw, i)
        if v[0] != 0x31434552:
            continue
        slots = [dict(active=v[7 + 8 * k], cid=v[8 + 8 * k], hp=v[9 + 8 * k], x=v[10 + 8 * k], y=v[11 + 8 * k],
                      sid=v[12 + 8 * k], drawn=v[13 + 8 * k]) for k in range(6)]
        recs.append(dict(clock=v[1], in0=v[2], in1=v[3], flags=v[4], present=v[5], mode=list(v[6][:5]), s=slots))
    return recs


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def gate(tape, recs, out):
    sch = [s.strip() for s in tape["schema"].strip("[]").split(",")]
    i_hp, i_px, i_py = sch.index("hp[6]"), sch.index("px[6]"), sch.index("py[6]")
    by_clock = {}
    for r in recs:
        by_clock[r["clock"]] = r          # a rolled-back clock repeats; the last tick at that clock is the state that stood
    rows = tape["frames"]
    total = len(rows)
    exact = 0
    missing = 0
    first_div = None
    first_missing = None
    per_field = {"hp": 0, "px": 0, "py": 0}
    for row in rows:
        f = row[0]
        r = by_clock.get(f)
        if r is None:
            missing += 1
            if first_missing is None:
                first_missing = f
            continue
        diffs = []
        for i in range(6):
            if r["s"][i]["hp"] != row[i_hp][i]:
                diffs.append(("hp", i, r["s"][i]["hp"], row[i_hp][i]))
            if f32(r["s"][i]["x"]) != f32(row[i_px][i]):
                diffs.append(("px", i, r["s"][i]["x"], row[i_px][i]))
            if f32(r["s"][i]["y"]) != f32(row[i_py][i]):
                diffs.append(("py", i, r["s"][i]["y"], row[i_py][i]))
        if not diffs:
            exact += 1
        else:
            for d in diffs:
                per_field[d[0]] += 1
            if first_div is None:
                first_div = (f, diffs)
    # phases
    anchor_ticks = [r for r in recs if r["flags"] & 2]
    modes = {}
    for r in recs:
        modes.setdefault(tuple(r["mode"]), [r["clock"], r["clock"], 0])
        m = modes[tuple(r["mode"])]
        m[0] = min(m[0], r["clock"]); m[1] = max(m[1], r["clock"]); m[2] += 1
    battle = [r for r in recs if r["mode"][2] == 2]
    fed = sum(1 for r in recs if r["flags"] & 1)
    rep = {
        "ticks": len(recs), "fed": fed, "anchor_applied_at_clock": anchor_ticks[0]["clock"] if anchor_ticks else None,
        "clock_range": [recs[0]["clock"], recs[-1]["clock"]] if recs else None,
        "modes": {"/".join(map(str, k)): v for k, v in modes.items()},
        "battle_first_clock": battle[0]["clock"] if battle else None,
        "battle_cids": [s["cid"] for s in battle[0]["s"]] if battle else None,
        "tape_start_sim_frame": tape["start_sim_frame"], "tape_teams": [tape["p1_team"], tape["p2_team"]],
        "rows_total": total, "rows_exact": exact, "rows_missing": missing, "first_missing_row": first_missing,
        "rows_differing_by_field": per_field,
        "first_divergence": {"frame": first_div[0], "fields": [dict(field=d[0], slot=d[1], live=d[2], tape=d[3]) for d in first_div[1]]} if first_div else None,
    }
    json.dump(rep, open(os.path.join(out, "gate.json"), "w"), indent=1)
    print("\nGATE  rows exact %d / %d   (missing %d, first missing row %s)" % (exact, total, missing, first_missing))
    print("      ticks %d, fed %d, anchor applied at clock %s, clock range %s" % (len(recs), fed, rep["anchor_applied_at_clock"], rep["clock_range"]))
    print("      modes seen: " + "; ".join("%s clocks %d..%d x%d" % (k, v[0], v[1], v[2]) for k, v in rep["modes"].items()))
    print("      battle entered at clock %s (tape %d); cids at battle start %s (tape teams p1 %s p2 %s)" % (
        rep["battle_first_clock"], tape["start_sim_frame"], rep["battle_cids"], tape["p1_team"], tape["p2_team"]))
    if first_div:
        print("      FIRST DIVERGENCE frame %d: %s" % (first_div[0], first_div[1][:6]))
    print("      -> %s" % os.path.join(out, "gate.json"))
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tape", help="match id or path to the gs-cache .json.gz")
    ap.add_argument("--out", help="work dir (default %%TEMP%%\\rrcap\\receipt_<id>)")
    ap.add_argument("--battle-src", choices=["confirmed", "rows"], default="confirmed")
    ap.add_argument("--shift", type=int, default=0, help="add k to every battle entry clock (experiments)")
    ap.add_argument("--force-arena", action="store_true", help="apply the arena relocation branch (untested)")
    ap.add_argument("--ignore-arena", action="store_true", help="proceed with a moved arena WITHOUT touching arena-range words")
    ap.add_argument("--any-mode", action="store_true", help="do not require the game to sit at character select")
    ap.add_argument("--speed", type=int, default=1, help="frames per vsync while replaying (patch at 0x14003A2D6); 1 = real time")
    ap.add_argument("--timeout", type=float, default=0, help="seconds to wait (default tape_frames/60*1.3 + 90)")
    ap.add_argument("--prepare-only", action="store_true")
    ap.add_argument("--gate-only", help="work dir with ticks.bin to re-gate")
    a = ap.parse_args()

    if a.gate_only:
        meta = json.load(open(os.path.join(a.gate_only, "prepare.json")))
        tape = json.load(gzip.open(find_tape(meta["tape_id"].split("_")[3] if "_" in meta["tape_id"] else meta["tape_id"])))
        gate(tape, read_log(os.path.join(a.gate_only, "ticks.bin")), a.gate_only)
        return
    if not a.tape:
        ap.error("--tape required")
    path = find_tape(a.tape)
    tape = json.load(gzip.open(path))
    for k in ("anchor", "select_in", "frames"):
        if not tape.get(k):
            sys.exit("tape has no %r -- not a receipt-capable tape (agent 0.3.24+ needed)" % k)
    tid = tape.get("match_key", tape["id"]).split("_")[3]
    out = a.out or os.path.join(CAP_DIR, "receipt_%s" % tid)
    print("tape %s: ver %s, %d rows %d..%d, anchor frame %d, select_in %d, confirmed_in %s, rollbacks %s, stage %s" % (
        tid, tape.get("ver"), tape["frame_count"], tape["frame_first"], tape["frame_last"], tape["anchor_frame"],
        tape.get("select_in_frames"), tape.get("confirmed_in_frames"), tape.get("rollbacks"), tape.get("stage_id")))

    proc = Proc()
    live = proc.live()
    print("live: pid %d blk 0x%x arena 0x%x clock %s mode %s ggpo_session 0x%x net_flag %s paused %s shim %s" % (
        proc.pid, live["blk"] or 0, live["arena"] or 0, live["clock"], live["mode"], live["ggpo_session"] or 0,
        live["net_flag"], live["paused"], live["shim"]))
    if not live["blk"] or not live["arena"]:
        sys.exit("blk/arena not resolvable (game not past boot?)")
    if live["ggpo_session"]:
        sys.exit("REFUSED: a GGPO session is live (0x%x) -- never write into an online match" % live["ggpo_session"])
    if live["net_flag"]:
        sys.exit("REFUSED: net session flag *(0x140ACD3A8)+0x1cd = %d (the GGPO frame path is active)" % live["net_flag"])
    meta = prepare(tape, out, live, a.force_arena, a.battle_src, a.shift, a.ignore_arena)
    if a.prepare_only:
        print("prepared in %s" % out)
        return
    if not live["shim"]:
        sys.exit("d3dcap.dll is not loaded in pid %d: launch the game with d3dcap/launch_suspended.ps1 (D3DCAP_MANUAL=1)" % proc.pid)
    if not a.any_mode and (not live["mode"] or live["mode"][2] != 1):
        sys.exit("the game is not at CHARACTER SELECT (blk+0x3CB8 = %s; byte[2] must be 1). Go to character select (offline) and rerun, or --any-mode" % live["mode"])
    timeout = a.timeout or (tape["frame_last"] - meta["anchor_clock"]) / 60.0 * 1.3 / max(1, a.speed) + 90
    print("running: timeout %.0f s, speed %d" % (timeout, a.speed))
    log = run(tape, out, meta, live, proc, timeout, a.speed)
    recs = read_log(log)
    if not recs:
        sys.exit("no tick records were written (%s) -- the hook never ran with logging on" % log)
    gate(tape, recs, out)


if __name__ == "__main__":
    main()
