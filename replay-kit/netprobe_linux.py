#!/usr/bin/env python3
"""netprobe_linux.py [secs] — READ-ONLY probe: IS THE ARCADE HOST NODE SIMULATING THE MATCH?

⚠⚠ THIS SCRIPT NEVER WRITES TO THE GAME. No process_vm_writev, no /proc/<pid>/mem writes, no ptrace
ATTACH, no SuspendThread. It opens /proc/<pid>/mem O_RDONLY and preads. That is the whole surface.
It is safe to run on a production host node during a real money match.

THE QUESTION IT ANSWERS
The node hosts the lobby, and it runs the game. But HOSTING A LOBBY AND BEING A GGPO PARTICIPANT ARE
NOT THE SAME THING. If the node's game process is genuinely in the netcode — receiving both players'
inputs and simulating the match, which is what a GGPO spectator does — then the whole capture problem
moves off the players' machines onto the one box we control: the node alone knows the TRUE PAIR (each
player's own agent sees the bot as its opponent), it is present for every money match, and it can read
GGPO's CONFIRMED input ring instead of the 1-frame latch the agent currently polls.
If instead it just brokers the lobby and sits at a menu, there is no ring to read and that plan dies.

VERDICT CRITERIA — all four must hold for "the node is simulating":
  1. mode byte blk+0x3CB8[2] reaches 2 (in battle) while the players fight
  2. the sim frame counter blk+0x3CC8 advances at ~60 Hz
  3. GGPO registered ONE region: base == blk, size == 0x33B18
  4. the rollback counter G+0x76C CLIMBS (it only moves when the netcode rewinds THIS sim)
(4) is the strongest single signal: a process that is not simulating never rolls back.

Also samples both seats' input words. On the node BOTH should carry data — it is a third party to two
remote players, so unlike a player's own client neither seat is "local".

PORTED VERBATIM from the agent's proven Linux path (RetroReceipts-agent/agent/src/mem.rs:448-540).
⚠ The argv[0] rule is load-bearing: under Proton the Wine `steam.exe` launcher passes the game's path
as a LATER ARG and maps a PE at 0x140000000 too, but has NONE of the live state (session ptr reads
null). The real game is the process whose argv[0] IS the game exe. Do not "simplify" this.

Usage:  sudo python3 netprobe_linux.py [seconds]     (default: run until Ctrl-C)
"""
import os
import struct
import sys
import time

EXE_PREFIX = "MarvelVsCapcom"
PREFERRED_BASE = 0x140000000        # Wine maps the PE at its preferred ImageBase; no ASLR under Proton

# ── exe-relative offsets (NOT absolute — so a non-preferred base still works) ────────────────────
BLK_PTR_OFF = 0xAC6EF0              # *(u64*)(exe+this) = blk, the GGPO-registered match block
G_OFF = 0xAC6D40                    # the game-global struct ("G")
IN0_OFF = 0xAC6F58                  # G+0x218 — the raw per-seat input words (two u32)
SEATMAP_OFF = 0xAC6F98              # G+0x258 — ggpo player k -> seat index (-1 = unmapped)
ROLLBACK_OFF = 0xAC74AC             # G+0x76C — load_game_state calls, CUMULATIVE SINCE LAUNCH
G_SEL_OFF = 0xAC6D40 + 0x48         # the registration fork: <3 = multi-region arm, >=3 = single
REG_COUNT_OFF, REG_BASE_OFF, REG_SIZE_OFF = 0x2D10950, 0x2D107D0, 0x2D108D0

BLK_MODE_OFF = 0x3CB8               # byte[2]: 1 = character select, 2 = in battle
BLK_FRAME_OFF = 0x3CC8              # the sim frame counter (runs BACKWARD on rollback — by design)
BLK_SIM_LEN = 0x33B18               # the registered region size
H0, STRIDE, H_CID = 0x3DB8, 0x738, 0x6C0


def find_game_pid():
    """argv[0] IS the game exe -> the real process. Game only in a later arg -> Wine launcher/helper."""
    def base_matches(arg):
        s = arg.decode("utf-8", "replace")
        return s.replace("\\", "/").rsplit("/", 1)[-1].startswith(EXE_PREFIX)

    argv0, any_arg = [], []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        pid = int(name)
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmdline = f.read()
        except OSError:
            continue
        args = [a for a in cmdline.split(b"\0") if a]
        if not args:
            continue
        if base_matches(args[0]):
            argv0.append(pid)
        elif any(base_matches(a) for a in args):
            any_arg.append(pid)

    for pid in argv0:
        if maps_have_base(pid, PREFERRED_BASE):
            return pid
    if argv0:
        return argv0[0]
    for pid in any_arg:
        if maps_have_base(pid, PREFERRED_BASE):
            return pid
    return any_arg[0] if any_arg else None


def maps_have_base(pid, want):
    try:
        with open(f"/proc/{pid}/maps") as f:
            for line in f:
                start = line.split()[0].split("-")[0]
                if int(start, 16) == want:
                    return True
    except OSError:
        pass
    return False


def exe_base(pid):
    """Lowest readable mapping of the game exe; fall back to the preferred base if it is mapped."""
    by_name, has_preferred = None, False
    try:
        with open(f"/proc/{pid}/maps") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 2:
                    continue
                start = int(parts[0].split("-")[0], 16)
                perms = parts[1]
                path = parts[5] if len(parts) > 5 else ""
                if start == PREFERRED_BASE:
                    has_preferred = True
                if "r" in perms and path.replace("\\", "/").rsplit("/", 1)[-1].startswith(EXE_PREFIX):
                    if by_name is None or start < by_name:
                        by_name = start
    except OSError:
        return 0
    if by_name is not None:
        return by_name
    return PREFERRED_BASE if has_preferred else 0


class Reader:
    """READ-ONLY. The fd is opened O_RDONLY; there is no write path in this class by construction."""

    def __init__(self, pid):
        self.pid = pid
        self.fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY)

    def read(self, addr, n):
        try:
            return os.pread(self.fd, n, addr)
        except OSError:
            return None

    def u8(self, addr):
        b = self.read(addr, 1)
        return b[0] if b else None

    def u32(self, addr):
        b = self.read(addr, 4)
        return struct.unpack("<I", b)[0] if b and len(b) == 4 else None

    def i32(self, addr):
        b = self.read(addr, 4)
        return struct.unpack("<i", b)[0] if b and len(b) == 4 else None

    def u64(self, addr):
        b = self.read(addr, 8)
        return struct.unpack("<Q", b)[0] if b and len(b) == 8 else None


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else float("inf")

    pid = find_game_pid()
    if pid is None:
        sys.exit("no MarvelVsCapcom process found — is the game running on this node?")
    exe = exe_base(pid)
    if not exe:
        sys.exit(f"pid {pid}: could not resolve the exe base from /proc/{pid}/maps")
    print(f"netprobe (READ-ONLY) — pid {pid}, exe base 0x{exe:x}"
          f"{' (preferred)' if exe == PREFERRED_BASE else ' ⚠ NOT the preferred base'}")
    print("Play a money match on this node. Nothing is written, ever.\n")

    g = Reader(pid)
    seen_reg = None
    seen_seats = None
    rb_first = rb_max = None
    modes = {}
    seat0_nz = seat1_nz = 0
    samples = 0
    fc_first = fc_last = None
    t0 = time.time()
    last_line = 0.0
    last_fc = None

    try:
        while time.time() - t0 < secs:
            blk = g.u64(exe + BLK_PTR_OFF)
            if not blk or blk < 0x10000:
                time.sleep(0.2)
                continue
            fc = g.u32(blk + BLK_FRAME_OFF)
            # ⚠ 20 ms, NOT a tight spin. This runs on the PRODUCTION host node during real money
            # matches, and an instrument that perturbs the game it measures is worse than no
            # instrument. We do not need every frame: the sim RATE is derived from
            # (fc_last - fc_first) / elapsed, which is exact at any sampling rate, and the mode /
            # rollback / registration signals are all slow-moving. 50 samples/s is ample.
            time.sleep(0.02)
            if fc is None or fc == last_fc:
                continue
            last_fc = fc
            samples += 1
            if fc_first is None:
                fc_first = fc
            fc_last = fc

            mode = g.u8(blk + BLK_MODE_OFF + 2)
            if mode is not None:
                modes[mode] = modes.get(mode, 0) + 1

            rb = g.u32(exe + ROLLBACK_OFF)
            if rb is not None:
                if rb_first is None:
                    rb_first = rb
                rb_max = rb if rb_max is None else max(rb_max, rb)

            seats = tuple(g.i32(exe + SEATMAP_OFF + 4 * k) for k in range(4))
            if seats != (0, 0, 0, 0) and seats != seen_seats and all(s is not None for s in seats):
                seen_seats = seats
                print(f"  [{time.time()-t0:5.0f}s] SEAT MAP populated: {list(seats)}")

            n = g.u32(exe + REG_COUNT_OFF)
            if n and seen_reg != n:
                seen_reg = n
                rbase = g.u64(exe + REG_BASE_OFF) or 0
                rsize = g.u32(exe + REG_SIZE_OFF) or 0
                ok = (rbase == blk and rsize == BLK_SIM_LEN)
                sel = g.u32(exe + G_SEL_OFF) or 0
                print(f"  [{time.time()-t0:5.0f}s] GGPO REGISTERED {n} region(s): base=0x{rbase:x} "
                      f"size=0x{rsize:x}  {'== blk / 0x33B18 OK' if ok else '⚠ NOT blk/0x33B18'}")
                print(f"            G+0x48 = {sel} "
                      f"({'single-region arm (>=3) OK' if sel >= 3 else '⚠ multi-region arm (<3)'})")

            s0, s1 = g.u32(exe + IN0_OFF), g.u32(exe + IN0_OFF + 4)
            if s0:
                seat0_nz += 1
            if s1:
                seat1_nz += 1

            now = time.time() - t0
            if now - last_line >= 15.0:
                last_line = now
                rate = (fc_last - fc_first) / now if now > 0 else 0
                print(f"  [{now:5.0f}s] frame {fc}  mode {mode}  rollbacks {rb}  "
                      f"sim {rate:.1f} Hz  seat-inputs {seat0_nz}/{seat1_nz}")
    except KeyboardInterrupt:
        print("\n  (stopped)")

    el = max(1e-9, time.time() - t0)
    print(f"\n--- {el:.0f}s, {samples} distinct sim frames sampled ---")
    rate = (fc_last - fc_first) / el if fc_first is not None else 0.0
    rb_delta = (rb_max - rb_first) if (rb_max is not None and rb_first is not None) else 0

    print(f"1. battle mode reached : {'YES' if modes.get(2) else 'NO'}   modes seen {dict(sorted(modes.items()))}")
    print(f"2. sim frame rate      : {rate:.1f} Hz over {el:.0f}s   {'OK' if rate > 45 else '⚠ not a running sim'}")
    print(f"3. GGPO registration   : {seen_reg if seen_reg is not None else 'NEVER REGISTERED'}")
    print(f"4. rollbacks (delta)   : {rb_delta}   {'<- the netcode rewound THIS sim' if rb_delta else '⚠ never rolled back'}")
    print(f"   seat map            : {list(seen_seats) if seen_seats else 'never populated'}")
    print(f"   frames w/ input     : seat0 {seat0_nz}, seat1 {seat1_nz}")

    simulating = bool(modes.get(2)) and rate > 45 and rb_delta > 0
    print("\nVERDICT: " + (
        "THE NODE IS SIMULATING THE MATCH. It is a real GGPO participant — it can read the confirmed\n"
        "         input ring for BOTH players and stamp the true pair. Move capture here."
        if simulating else
        "NOT CONFIRMED as simulating. One or more criteria failed above — read them before concluding;\n"
        "         a probe run outside an actual match will also fail them, so check you caught a fight."))


if __name__ == "__main__":
    main()
