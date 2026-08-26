#!/usr/bin/env python3
"""rrtape4.py rec <name> [secs] | play <file.rr4> | ab <file.rr4> | info <file.rr4> | probe

TAPE v4 — SAVESTATE + INPUTS. The way every replay system works.

    tape = relocatable character-select savestate + input stream + ground-truth checkpoints

WHY THIS WORKS WHERE v2 DID NOT. v2 shipped a BATTLE savestate and crashed cross-process: a battle
state holds 557 pointers into the decompressed per-character asset image, and relocation fixes
their addresses but not the fact that the bytes there belong to whichever characters that session
loaded. At CHARACTER SELECT no characters are loaded, so those pointers are absent or inert.
PROVEN live: a char-select state captured in one process restored into another with blk moved
36 MB (0x15ce1000 -> 0x180e1000), 804 + 243 pointers relocated, self-check passed, game kept
running at 60fps. The same test with a battle state killed the process twice.

Relocation: blk moves every launch; the 256 MiB arena has been stable across every launch measured.
    p in [old_blk, old_blk+0x33B18)   -> += (new_blk - old_blk)
    p in [old_arena, old_arena+256M)  -> += (new_arena - old_arena)
Self-check before writing: blk+0x32500+8k must be the six fighter bases in ANY order (that table is
the live team/tag order, not a fixed permutation).

Inputs are FRAME-LOCKED, not fed one-per-poll: each is written on its own recorded frame number,
one frame ahead of the sim reading it. Feeding by poll drifts, and a few frames of drift on a
character-select cursor picks the wrong character.

── 2026-08-26 additions, all needed before a FULL match can be trusted ─────────────────────────
1. GAP FILL. The recorder polls the frame counter from Python; over 20s it never missed a frame,
   but a 5-minute match is 18,000 chances to miss one, and ONE missing input word desyncs the rest
   of the replay. When the counter jumps by 2 we recover the skipped frame from the engine's own
   previous-input registers (G+0x228). Jumps of 3+ are counted and reported as tape damage — a
   tape with lost>0 is not trustworthy and says so.
2. CHECKPOINTS. Every CHK_EVERY frames the recorder stores a pointer-free digest of the real
   fighter state. On playback each checkpoint is compared against the live game, so a divergence is
   reported WITH THE FRAME IT STARTED ON instead of "the end state looked right". Comparing a
   replay only against itself is how this project has fooled itself before.
3. AUTO-STOP. `rec` with no seconds records until the match ends on its own, so a real match can be
   captured without guessing a duration up front.

Format: magic b"RRTAPE40" | u32+JSON header | u32+zlib(state) | u32+zlib(inputs) [| u32+zlib(chk)]
The checkpoint section is optional and appended — v4 tapes written before it still load.
"""
import json
import os
import struct
import sys
import time
import zlib

try:                      # Windows only: lets ENTER stop a recording without Ctrl-C, which
    import msvcrt         # also hits the batch file and pops 'Terminate batch job (Y/N)?'
except ImportError:       # mid-pack.
    msvcrt = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from savestate import Game, BLK_PTR, BLKSZ, FC_OFF
from inputrec import IN0, patch, sanity
from mvcmem import EXE

MAGIC = b"RRTAPE40"
HERE = os.path.dirname(os.path.abspath(__file__))
ASZ = 0x10000000
ARENA_PTR = EXE + 0xAC6D40
FRAMES_TO_RUN = EXE + 0xAC74D8      # G+0x798
G = EXE + 0xAC6D40                   # the engine global block; arena = *(G+0), blk = *(G+0x1b0)
G_SEL = G + 0x48                     # <3 = the MULTI-region (emulated CPS) path, >=3 = single region
BLK2_PTR, BLK2_SZ = G + 0x1c0, G + 0x1c8   # a SECOND block at blk+0x33B18 — registered but NOT rollback-saved
REG_COUNT, REG_BASE, REG_SIZE = 0x142D10950, 0x142D107D0, 0x142D108D0   # what GGPO actually registered
ROLLBACKS = EXE + 0xAC74AC          # G+0x76C — GGPO load_game_state count
FF_RATE = 8                          # frames per tick while skipping character select
PREV_REL = 0x10                      # G+0x228 (previous frame's inputs) = IN0 + 0x10

MODE_OFF = 0x3CB8                    # byte[2]: 1 = character select, 2 = in battle
FC_MIRROR = 0x3CD4                   # the frame counter is mirrored here; both are excluded from the CRC
ARR_ADD = 0x3F24                     # fighter array = blk + this
H0 = 0x3DB8                          # slot 0 object base = blk + this
SLOT_PTRS = 0x32500                  # six absolute self-pointers = blk+H0+n*STRIDE (live tag order)
STRIDE = 0x738

# ── the checkpoint digest: REAL fields only, no pointers ────────────────────────────────────────
# Pointers would differ between processes purely from relocation and would report a divergence that
# is not one. Everything here is simulation output that MUST match frame for frame if the replay is
# faithful.
CHK_EVERY = 30                       # every half second at 60fps
SLOT_FMT = "<HHffffHBBBB"            # hp, red, x, y, vx, vy, sprite_id, drawn, facing, anim, pad
GLOB_FMT = "<BBHBBBBfff"             # m1, m2, mfill, phase, in_match, round, timer, eyeX, eyeY, ground
CHK_SIZE = 4 + 6 * struct.calcsize(SLOT_FMT) + struct.calcsize(GLOB_FMT) + 4   # + whole-region CRC32
SLOT_FIELDS = ("hp", "red", "x", "y", "vx", "vy", "sid", "drawn", "facing", "anim", "_pad")
GLOB_FIELDS = ("m1", "m2", "mfill", "phase", "in_match", "round", "timer", "eyeX", "eyeY", "ground")
# phase/in_match/round/timer come from the DC BattleState mapping at array+0x2e5dc.. . ⚠ array+0x2e5dc
# is blk+0x32500, which is ALSO where the six fighter self-pointers live — the two cannot both be
# right. They are recorded and compared like everything else; `probe` prints both so the conflict
# gets settled by a read instead of by argument.
FIELDS_SOFT = ("phase", "in_match", "round", "timer")

# fighter window: slot 0 .. slot 5, plus the camera globals just past it (0x6914/0x6918/0x6998)
FWIN_OFF, FWIN_LEN = H0, 0x2C00
CAM_REL = 0x6914 - H0
GROUND_REL = 0x6998 - H0
GWIN_OFF, GWIN_LEN = 0x32500, 0x100  # battle globals window (array+0x2e5dc == blk+0x32500)


def _slot(fw, i):
    b = i * STRIDE
    return struct.pack(SLOT_FMT,
                       struct.unpack_from("<H", fw, b + 0x578)[0],   # hp
                       struct.unpack_from("<H", fw, b + 0x57C)[0],   # red
                       struct.unpack_from("<f", fw, b + 0x50)[0],    # x
                       struct.unpack_from("<f", fw, b + 0x54)[0],    # y
                       struct.unpack_from("<f", fw, b + 0x78)[0],    # vx
                       struct.unpack_from("<f", fw, b + 0x7C)[0],    # vy
                       struct.unpack_from("<H", fw, b + 0x188)[0],   # sprite id (raw)
                       fw[b + 0x170], fw[b + 0x154], fw[b + 0x186], 0)


def blk_crc(b):
    """CRC32 of the WHOLE sim region, with the frame counter and its mirror excluded.

    The per-field digest below is pointer-free so it survives relocation; this is the opposite
    trade — it covers every byte the sim owns (projectiles, effects, RNG, the draw list, everything
    we have not named), so an in-process replay that diverges ANYWHERE is caught, not only where we
    happened to look. The counter is excluded because a replay runs at a different absolute frame
    number; every other byte must match exactly.
    """
    c = zlib.crc32(b[:FC_OFF])
    c = zlib.crc32(b[FC_OFF + 4:FC_MIRROR], c)
    return zlib.crc32(b[FC_MIRROR + 4:], c) & 0xFFFFFFFF


def digest(g, blk, frame):
    """One checkpoint, or None if the read tore across a frame boundary."""
    f0 = g.u32(blk + FC_OFF)
    b = g.read(blk, BLKSZ)
    if b is None or g.u32(blk + FC_OFF) != f0:
        return None
    fw, gw = b[FWIN_OFF:FWIN_OFF + FWIN_LEN], b[GWIN_OFF:GWIN_OFF + GWIN_LEN]
    gb = GWIN_OFF
    out = struct.pack("<I", frame) + b"".join(_slot(fw, i) for i in range(6))
    out += struct.pack(GLOB_FMT,
                       gw[ARR_ADD + 0x2E636 - gb], gw[ARR_ADD + 0x2E637 - gb],
                       struct.unpack_from("<H", gw, ARR_ADD + 0x2E658 - gb)[0],
                       gw[ARR_ADD + 0x2E5DC - gb], gw[ARR_ADD + 0x2E610 - gb],
                       gw[ARR_ADD + 0x2E617 - gb], gw[ARR_ADD + 0x2E61C - gb],
                       struct.unpack_from("<f", fw, CAM_REL)[0],
                       struct.unpack_from("<f", fw, CAM_REL + 4)[0],
                       struct.unpack_from("<f", fw, GROUND_REL)[0])
    return out + struct.pack("<I", blk_crc(b))


def unpack_chk(rec):
    """A packed checkpoint -> (frame, [slot dicts], globals dict)."""
    frame, = struct.unpack_from("<I", rec, 0)
    n = struct.calcsize(SLOT_FMT)
    slots = [dict(zip(SLOT_FIELDS, struct.unpack_from(SLOT_FMT, rec, 4 + i * n))) for i in range(6)]
    gl = dict(zip(GLOB_FIELDS, struct.unpack_from(GLOB_FMT, rec, 4 + 6 * n)))
    off = 4 + 6 * n + struct.calcsize(GLOB_FMT)
    gl["crc"] = struct.unpack_from("<I", rec, off)[0] if len(rec) >= off + 4 else None
    return frame, slots, gl


def rec(name, secs=0.0):
    g = Game()
    blk = g.u64(BLK_PTR)
    mode = list(g.read(blk + MODE_OFF, 5))
    if mode[2] != 1:
        sys.exit(f"REFUSING: not on character select (mode {mode}). "
                 "A battle state is not portable — see the module docstring.")

    held = g.freeze()
    try:
        f0 = g.u32(blk + FC_OFF)
        state = g.read(blk, BLKSZ)
        f1 = g.u32(blk + FC_OFF)
    finally:
        g.thaw(held)
    if f0 != f1:
        sys.exit("torn read")
    cap = secs if secs > 0 else 900.0
    print(f"savestate captured at character select, frame {f0}")
    print(f"recording until the match ends" if secs <= 0 else f"recording {secs:.0f}s",
          f"(cap {cap:.0f}s) — go.", flush=True)
    print("  (press ENTER at any time to STOP AND SAVE what has been recorded)", flush=True)

    rows, chks = [], []
    last, t0 = None, time.time()
    nextmsg = t0 + 1.0
    match_start, gaps, filled, lost, torn = None, 0, 0, 0, 0
    ended_at, wiped_at, stop_why = None, None, "time cap"
    # Everything below is inside try/except KeyboardInterrupt so that Ctrl-C FALLS THROUGH to the
    # pack step. The first version packed only after the loop, so interrupting a two-minute
    # recording threw the whole thing away — which is exactly what a person does when the
    # auto-stop misses.
    try:
      while time.time() - t0 < cap:
          fc = g.u32(blk + FC_OFF)
          if fc is None or fc == last:
              continue
          w = g.read(IN0, PREV_REL + 8)
          if w is None:
              continue
          cur0, cur1, prev0, prev1 = struct.unpack("<II", w[:8]) + struct.unpack("<II", w[PREV_REL:PREV_REL + 8])
          # GAP FILL — one missed poll is recoverable exactly, because the engine still holds the
          # previous frame's input words. Anything wider is genuinely lost and gets counted.
          if last is not None and fc > last + 1:
              gaps += 1
              if fc == last + 2:
                  rows.append((fc - 1, prev0, prev1))
                  filled += 1
              else:
                  lost += fc - last - 1
          last = fc
          rows.append((fc, cur0, cur1))

          m2 = g.read(blk + MODE_OFF, 5)
          m2 = m2[2] if m2 else 0
          if match_start is None and m2 == 2:
              match_start = fc            # mode 1 -> 2: character select ended, fight begins
              print(f"  MATCH START at frame {fc} "
                    f"({len(rows)} frames of character select)", flush=True)
          elif match_start is not None and m2 != 2:
              # back at a non-battle screen. Give it a beat, then stop.
              ended_at = ended_at or time.time()
              if secs <= 0 and time.time() - ended_at > 1.5:
                  stop_why = f"left battle mode (byte {m2})"
                  print(f"  MATCH END at frame {fc} — {stop_why}", flush=True)
                  break
          else:
              ended_at = None

          if fc % CHK_EVERY == 0:
              d = digest(g, blk, fc)
              if d is None:
                  torn += 1
              else:
                  chks.append(d)
                  # ⚠ THE MODE BYTE IS NOT AN END-OF-MATCH SIGNAL. Measured 2026-08-26: it stayed
                  # at 2 through the KO, the win pose and the results screen for a full 118 s, so
                  # the original auto-stop never fired and the recording had to be interrupted.
                  # A TEAM WIPE is the real end: three dead characters on one side, held for a
                  # couple of seconds so a momentary zero during a tag-out cannot end the tape.
                  if match_start is not None:
                      _, slots, _ = unpack_chk(d)
                      hp = [sl["hp"] for sl in slots]
                      if (hp[0] == 0 and hp[2] == 0 and hp[4] == 0) or \
                         (hp[1] == 0 and hp[3] == 0 and hp[5] == 0):
                          wiped_at = wiped_at or time.time()
                          if secs <= 0 and time.time() - wiped_at > 2.5:
                              stop_why = f"team wiped, hp {hp}"
                              print(f"  MATCH END at frame {fc} — {stop_why}", flush=True)
                              break
                      else:
                          wiped_at = None

          # A key press is the clean way out: Ctrl-C also reaches the batch file, which pops
          # 'Terminate batch job (Y/N)?' while we are still packing. This just breaks the loop.
          if msvcrt is not None and msvcrt.kbhit():
              msvcrt.getch()
              stop_why = "stopped by you (key press)"
              print(f"\n  {stop_why} — packing what we have.", flush=True)
              break

          now = time.time()
          if now >= nextmsg:
              nextmsg = now + 1.0
              act = sum(1 for _, a, b in rows if a or b)
              print(f"  {now-t0:4.0f}s   {len(rows):6d} frames, {act} with input, "
                    f"{len(chks)} checkpoints, gaps {gaps} (filled {filled}, lost {lost})", flush=True)

    except KeyboardInterrupt:
        stop_why = "stopped by you (Ctrl-C)"
        print(f"\n  {stop_why} — packing what we have.", flush=True)
    except Exception as e:
        # ⚠ Game.read RAISES on a failed RPM rather than returning None (savestate.py:83), so every
        # "is None" guard in this file is dead code and ONE transient hiccup — blk relocating, a
        # page briefly unreadable, the game exiting — would otherwise destroy an entire recording.
        # Whatever was captured before the failure is still a valid tape, so pack it and say what
        # happened rather than losing the take.
        stop_why = f"read failed: {type(e).__name__}: {e}"
        print(f"\n  ⚠ {stop_why} — packing what we have anyway.", flush=True)

    print(f"\nrecording ended: {stop_why}")
    inp = b"".join(struct.pack("<III", *r) for r in rows)
    chk = b"".join(chks)
    hdr = json.dumps({
        "ver": 4, "start_frame": f0, "frames": len(rows), "mode": mode,
        "match_start": match_start,
        "blk": blk, "arena": g.u64(ARENA_PTR), "exe": EXE,
        "teams": [state[H0 + i * STRIDE + 0x6C0] for i in range(6)],
        "chk_every": CHK_EVERY, "chk_size": CHK_SIZE, "chk_count": len(chks),
        "gaps": gaps, "filled": filled, "lost": lost, "torn_chk": torn, "stop_why": stop_why,
        "rollbacks": g.u32(ROLLBACKS),
        "ts": int(time.time()), "note": "char-select savestate + inputs + checkpoints",
    }).encode()
    cs, ci, cc = zlib.compress(state, 9), zlib.compress(inp, 9), zlib.compress(chk, 9)
    out = os.path.join(HERE, name + ".rr4")
    with open(out, "wb") as f:
        f.write(MAGIC)
        f.write(struct.pack("<I", len(hdr))); f.write(hdr)
        f.write(struct.pack("<I", len(cs)));  f.write(cs)
        f.write(struct.pack("<I", len(ci)));  f.write(ci)
        f.write(struct.pack("<I", len(cc)));  f.write(cc)
    print(f"\npacked {out}  {os.path.getsize(out):,} B  "
          f"(state {len(state):,}->{len(cs):,}, inputs {len(inp):,}->{len(ci):,}, "
          f"checkpoints {len(chk):,}->{len(cc):,})")
    if lost:
        print(f"⚠ {lost} input frames were LOST (poll gaps wider than one frame). This tape will "
              f"diverge on replay — re-record it.")
    else:
        print(f"tape quality: {gaps} poll gaps, all recoverable ({filled} filled from G+0x228)")


def load(path):
    d = open(path, "rb").read()
    if d[:8] != MAGIC:
        sys.exit("not an rr4 tape")
    o = 8
    hl, = struct.unpack_from("<I", d, o); o += 4
    hdr = json.loads(d[o:o + hl]); o += hl
    sl, = struct.unpack_from("<I", d, o); o += 4
    state = zlib.decompress(d[o:o + sl]); o += sl
    il, = struct.unpack_from("<I", d, o); o += 4
    inp = zlib.decompress(d[o:o + il]); o += il
    chk = b""
    if o + 4 <= len(d):                                   # optional, appended after v4 shipped
        cl, = struct.unpack_from("<I", d, o); o += 4
        chk = zlib.decompress(d[o:o + cl])
    return hdr, state, inp, chk


def info(path):
    hdr, state, inp, chk = load(path)
    print(json.dumps(hdr, indent=1))
    n = hdr.get("chk_size", CHK_SIZE)
    print(f"state {len(state):,} B, inputs {len(inp)//12} frames, "
          f"checkpoints {len(chk)//n if n else 0}, file {os.path.getsize(path):,} B")
    if chk:
        f, slots, gl = unpack_chk(chk[-n:])
        print(f"last checkpoint @frame {f}: hp={[s['hp'] for s in slots]} "
              f"pos0=({slots[0]['x']:.1f},{slots[0]['y']:.1f}) globals={gl}")


def compare(live, tape):
    """-> list of human-readable field differences between two packed checkpoints."""
    _, ls, lg = unpack_chk(live)
    _, ts, tg = unpack_chk(tape)
    out = []
    for i in range(6):
        for k in SLOT_FIELDS:
            if k == "_pad":
                continue
            a, b = ls[i][k], ts[i][k]
            if a != b:
                out.append(f"slot{i}.{k} live={a} tape={b}")
    if lg.get("crc") is not None and tg.get("crc") is not None and lg["crc"] != tg["crc"]:
        out.append("blk CRC live=0x%08x tape=0x%08x (the sim region differs SOMEWHERE, "
                   "even if every named field matches)" % (lg["crc"], tg["crc"]))
    for k in GLOB_FIELDS:
        if lg[k] != tg[k]:
            out.append(f"{'~' if k in FIELDS_SOFT else ''}{k} live={lg[k]} tape={tg[k]}")
    return out


def restore_anchor(g, hdr, state, quiet=False):
    """Relocate the tape's character-select state and write it into the live game. Returns blk."""
    blk = g.u64(BLK_PTR)
    arena = g.u64(ARENA_PTR)
    buf = bytearray(state)
    d_blk, d_arena = blk - hdr["blk"], arena - hdr["arena"]
    # ⚠ The arena has been IDENTICAL (0x97e1000) in every capture ever taken, so the arena branch
    # below has never actually changed a byte — it is untested code on a 6.25%-of-address-space
    # window, where a random (u32 >= 0x097E1000, 0) pair would be "relocated" into corruption. The
    # blk branch is falsified-safe (804/804 correct across three cold boots, zero false positives)
    # because its window is 0.005%. Until a real arena delta has been tested, refuse rather than
    # write a state we cannot vouch for.
    if d_arena != 0 and "--force-arena" not in sys.argv:
        sys.exit(f"REFUSING: arena moved ({d_arena:+#x}). The arena relocation branch has never been "
                 f"exercised on a real delta and its false-positive window is ~1,268x the blk one. "
                 f"Re-record on this launch, or pass --force-arena if you are deliberately testing it.")
    nb = na = 0
    for off in range(0, len(buf) - 7, 8):
        p = int.from_bytes(buf[off:off + 8], "little")
        if hdr["blk"] <= p < hdr["blk"] + BLKSZ:
            buf[off:off + 8] = (p + d_blk).to_bytes(8, "little"); nb += 1
        elif hdr["arena"] <= p < hdr["arena"] + ASZ:
            buf[off:off + 8] = (p + d_arena).to_bytes(8, "little"); na += 1
    seen = set()
    for k in range(6):
        p = int.from_bytes(buf[SLOT_PTRS + 8 * k:SLOT_PTRS + 8 * k + 8], "little")
        rel = p - blk - H0
        if rel < 0 or rel % STRIDE or not (0 <= rel // STRIDE < 6):
            sys.exit(f"SELF-CHECK FAILED: slot entry {k} = 0x{p:x} — refusing to write")
        seen.add(rel // STRIDE)
    if seen != set(range(6)):
        sys.exit(f"SELF-CHECK FAILED: not a permutation ({sorted(seen)}) — refusing to write")
    if not quiet:
        print(f"relocated {nb} intra-blk + {na} arena pointers (blk delta {d_blk:+#x}); "
              f"self-check PASS")

    # (Tried forcing the palette dirty flags at blk+0x1048+row*0x38 to fix the washed-out select
    # screen — it did not help. The grid geometry draws but the character PORTRAITS are missing
    # entirely, so it is not a palette problem: those portrait textures are MT Framework UI assets
    # the SHELL loads when IT enters character select, and they live outside blk. Restoring the sim
    # into char-select mode never triggers that load. Left out rather than ship an unproven write.)
    held = g.freeze()
    try:
        g.write(blk, bytes(buf))
    finally:
        g.thaw(held)
    # Let the sim settle before feeding inputs. Coming from another screen the shell needs a few
    # frames to notice the mode changed; feeding inputs into that window wastes the head of the
    # tape and can shift the character-select cursor.
    time.sleep(0.35)
    if not quiet:
        print(f"state loaded — frame {g.u32(blk + FC_OFF)}, mode now {list(g.read(blk + MODE_OFF, 5))}")
    return blk


def feed_tape(g, blk, hdr, rows, chks, ff=False, quiet=False):
    """Drive the recorded inputs back in, frame-locked, checking every checkpoint on the way.

    Returns {end_frame, fed, checked, diverged, first_div, end_digest}.
    """
    by_frame = {fc: (s0, s1) for fc, s0, s1 in rows}
    first, last_tape = rows[0][0], rows[-1][0]
    ms = hdr.get("match_start")
    fed, last, seenf = 0, None, set()
    checked, diverged, first_div = 0, 0, None
    live = {}          # tape frame -> the digest THIS run produced there (frame-locked, comparable)
    patch(g, True)
    try:
        base = g.u32(blk + FC_OFF)
        drift = base - first
        if not quiet:
            print(f"clock aligned: game {base}, tape {first} (drift {drift:+d})")
            if ms and not ff:
                print(f"replaying character select in real time ({ms - first} frames) — pass --ff "
                      f"to skip it (nondeterministic; verification runs should not)")
        deadline = time.perf_counter() + (len(rows) / 60.0) * 3 + 5
        while time.perf_counter() < deadline:
            cur = g.u32(blk + FC_OFF)
            if cur is None or cur == last:
                continue
            last = cur
            tf = cur - drift
            nxt = tf + 1
            if nxt > last_tape:
                break
            # GROUND TRUTH: at every recorded checkpoint, compare the live sim against what the
            # game actually did when the tape was made. This is the whole point — a replay that
            # only agrees with itself proves nothing. Skipped while fast-forwarding character
            # select, where the sim runs many frames per poll by design.
            if tf in chks and not (ms and ff and tf < ms):
                d = digest(g, blk, tf)
                if d is not None:
                    checked += 1
                    live[tf] = d
                    hard = [x for x in compare(d, chks[tf]) if not x.startswith("~")]
                    if hard:
                        diverged += 1
                        if first_div is None:
                            first_div = (tf, hard)
            v = by_frame.get(nxt)
            if v is not None and nxt not in seenf:
                g.write(IN0, struct.pack("<II", *v))
                seenf.add(nxt); fed += 1
                # G+0x798 = frames-to-run; G+0x770 suppresses rendering on catch-up frames.
                # FUN_140039de0 already loops on it, so this is the engine's own fast-forward.
                if ms and ff and nxt < ms:
                    g.write(FRAMES_TO_RUN, struct.pack("<I", FF_RATE))
    finally:
        patch(g, False)
    end = g.u32(blk + FC_OFF)
    # ⚠ deliberately NOT a fresh digest here: the sim keeps running after the tape ends, so a
    # post-loop read compares two moments an arbitrary number of frames apart. Everything returned
    # is keyed to a TAPE FRAME, so two runs are compared at identical points in the match.
    return {"end_frame": end, "fed": fed, "checked": checked, "diverged": diverged,
            "first_div": first_div, "live": live}


def play(path, ff=False):
    hdr, state, inp, chk = load(path)
    rows = [struct.unpack_from("<III", inp, i) for i in range(0, len(inp), 12)]
    csz = hdr.get("chk_size", CHK_SIZE)
    chks = {struct.unpack_from("<I", chk, i)[0]: chk[i:i + csz]
            for i in range(0, len(chk) - csz + 1, csz)} if chk else {}
    g = Game()
    sanity(g)
    mode = list(g.read(g.u64(BLK_PTR) + MODE_OFF, 5))
    print(f"tape v4: {hdr['frames']} frames, anchor {hdr['start_frame']}, mode {hdr['mode']}, "
          f"{len(chks)} checkpoints")
    if hdr.get("lost"):
        print(f"⚠ this tape LOST {hdr['lost']} input frames while recording — expect divergence.")
    print(f"game mode {mode}")
    if mode[2] != hdr["mode"][2]:
        # Loading a char-select state from ANOTHER screen works — the state carries the mode, so
        # the sim jumps to character select (verified live). The one artifact is that the MT
        # Framework shell/UI lives OUTSIDE blk, so the select screen can render garbled for a
        # moment until the shell re-syncs. Cosmetic; it clears on confirm.
        print(f"   note: game is on a different screen; the state will pull the sim to "
              f"mode {hdr['mode']}. The UI may render briefly garbled while the shell catches up.")
    blk = restore_anchor(g, hdr, state)
    r = feed_tape(g, blk, hdr, rows, chks, ff)
    print(f"fed {r['fed']}/{len(rows)} on their exact frame -> frame {r['end_frame']}")
    print(f"tape teams {hdr['teams']}")
    for i in range(6):
        H = blk + H0 + i * STRIDE
        if g.read(H + 0x170, 1)[0]:
            hp = struct.unpack("<I", g.read(H + 0x578, 4))[0] & 0xFFFF
            x, y = struct.unpack("<ff", g.read(H + 0x50, 8))
            print(f"   slot{i} cid={g.read(H+0x6C0,1)[0]:3d} hp={hp:3d} pos=({x:.1f},{y:.1f})")
    if not chks:
        print("\nNO CHECKPOINTS in this tape — replay fidelity is UNVERIFIED "
              "(re-record with this build to get a real check).")
    elif r["checked"] == 0:
        print("\nNO CHECKPOINTS REACHED — the replay never got to a checked frame.")
    elif r["diverged"] == 0:
        print(f"\n✅ VERIFIED: {r['checked']} checkpoints matched the recorded game exactly "
              f"(every fighter's hp, position, velocity and sprite, plus a CRC of the WHOLE sim "
              f"region, every half second).")
    else:
        tf, why = r["first_div"]
        print(f"\n❌ DIVERGED at frame {tf} ({r['diverged']}/{r['checked']} checkpoints differ). First:")
        for line in why[:8]:
            print(f"     {line}")
    return r


def churn(g, blk, frames, seed=1):
    """Feed pseudo-random inputs for a while, to make the game consume as much hidden state as it
    is going to consume. Deliberately NOT a replay — the point is to move anything that moves."""
    import random
    rnd = random.Random(seed)
    # the low 12 bits of the pad word are the real buttons/directions; higher bits are unused here
    fed, last = 0, None
    patch(g, True)
    try:
        t0 = time.perf_counter()
        while fed < frames and time.perf_counter() - t0 < frames / 60.0 * 3 + 5:
            cur = g.u32(blk + FC_OFF)
            if cur is None or cur == last:
                continue
            last = cur
            g.write(IN0, struct.pack("<II", rnd.getrandbits(12), rnd.getrandbits(12)))
            fed += 1
    finally:
        patch(g, False)
    return fed


def ab(path, churn_frames=900):
    """THE TEST THAT DOES NOT CARE WHICH GENERATOR IT IS.

    Everything else we have tried asks "where is the RNG?". This asks the question we actually
    need answered: does ANY state outside blk survive an anchor restore and change the match?

        A) restore anchor -> replay tape        -> end state D1
        B) restore anchor -> play RNG-heavy junk for a while (deliberately churn hidden state)
        C) restore anchor -> replay the SAME tape -> end state D2

    D1 == D2  =>  nothing outside blk survives the restore to affect a match. The anchor+inputs
                  model is sound, whatever generator the recompile uses and wherever it lives.
    D1 != D2  =>  falsified. Something outside blk carries state into the match, and the tape has
                  to carry it too. The CRC tells you the whole region differs; the field lines tell
                  you where it showed up first.

    Note this is strictly stronger than "two replays matched", which is what we had before: that
    compared two runs with nothing in between, so hidden state that simply persisted unchanged
    would have passed.
    """
    hdr, state, inp, chk = load(path)
    rows = [struct.unpack_from("<III", inp, i) for i in range(0, len(inp), 12)]
    csz = hdr.get("chk_size", CHK_SIZE)
    chks = {struct.unpack_from("<I", chk, i)[0]: chk[i:i + csz]
            for i in range(0, len(chk) - csz + 1, csz)} if chk else {}
    g = Game()
    sanity(g)
    print(f"A/B: {hdr['frames']} frames, {len(chks)} checkpoints, churn {churn_frames} frames\n")

    print("── A: restore + replay ─────────────────────────────────────────────")
    blk = restore_anchor(g, hdr, state, quiet=True)
    r1 = feed_tape(g, blk, hdr, rows, chks, ff=False, quiet=True)
    print(f"   end frame {r1['end_frame']}, fed {r1['fed']}, "
          f"{r1['checked']} checkpoints checked, {r1['diverged']} diverged")

    print("── B: restore + CHURN (random inputs, to move any hidden state) ────")
    blk = restore_anchor(g, hdr, state, quiet=True)
    n = churn(g, blk, churn_frames)
    print(f"   churned {n} frames of random input")

    print("── C: restore + replay the SAME tape ───────────────────────────────")
    blk = restore_anchor(g, hdr, state, quiet=True)
    r2 = feed_tape(g, blk, hdr, rows, chks, ff=False, quiet=True)
    print(f"   end frame {r2['end_frame']}, fed {r2['fed']}, "
          f"{r2['checked']} checkpoints checked, {r2['diverged']} diverged\n")

    common = sorted(set(r1["live"]) & set(r2["live"]))
    if not common:
        print("INCONCLUSIVE: the two runs share no checked frame. Does this tape have "
              "checkpoints? (`info` will say.) Re-record with the current build if not.")
        return
    hard, worst = [], None
    for tf in common:
        d = [x for x in compare(r1["live"][tf], r2["live"][tf]) if not x.startswith("~")]
        if d and worst is None:
            worst = (tf, d)
        hard += d
    print(f"compared {len(common)} frame-locked checkpoints present in both runs")
    if not hard:
        print("✅ A == C. The churn in between changed NOTHING about how the tape replayed.")
        print("   Nothing outside blk survives an anchor restore to affect a match — which is the")
        print("   claim we needed, and it holds regardless of which generator the recompile uses")
        print("   or where it lives. (Still same-process: a cold-boot A/B is the next rung.)")
    else:
        tf, d = worst
        print(f"❌ A != C — FALSIFIED. First difference at tape frame {tf} "
              f"({len(hard)} in total across {len(common)} checkpoints):")
        for line in d[:12]:
            print(f"     {line}")
        print("   Something outside blk carried state across the restore. The tape must carry it")
        print("   too before any re-simulation can be trusted.")


def probe():
    """Settle the blk+0x32500 conflict with a read instead of an argument, and dump the anchors."""
    g = Game()
    blk = g.u64(BLK_PTR)
    arena = g.u64(ARENA_PTR)
    mode = list(g.read(blk + MODE_OFF, 5))
    print(f"pid {g.pid}  blk 0x{blk:x}  arena 0x{arena:x}  frame {g.u32(blk + FC_OFF)}  mode {mode} "
          f"({'CHAR SELECT' if mode[2] == 1 else 'IN BATTLE' if mode[2] == 2 else '?'})")
    print(f"blk sim size field @0x{EXE + 0xAC6EF8:x} = 0x{g.u32(EXE + 0xAC6EF8):x} "
          f"(expect 0x{BLKSZ:x})")
    print(f"rollbacks (G+0x76C) = {g.u32(ROLLBACKS)}")
    seat = struct.unpack("<4i", g.read(EXE + 0xAC6F98, 16))
    print(f"seat map (G+0x258) = {seat}")
    print(f"seat inputs (G+0x218) = {struct.unpack('<2I', g.read(IN0, 8))}  "
          f"prev (G+0x228) = {struct.unpack('<2I', g.read(IN0 + PREV_REL, 8))}")
    print("\nblk+0x32500 — the CONFLICT. reader.rs reads a u8 'phase' here (array+0x2e5dc);")
    print("rrtape4's self-check reads six fighter self-pointers here. Both cannot be right:")
    w = g.read(blk + 0x32500, 0x40)
    for k in range(6):
        p = struct.unpack_from("<Q", w, 8 * k)[0]
        rel = p - blk - H0
        ok = p and rel >= 0 and rel % STRIDE == 0 and 0 <= rel // STRIDE < 6
        print(f"   +0x{8*k:02x}: 0x{p:016x}  {'= slot %d base' % (rel // STRIDE) if ok else 'NOT a slot base'}")
    print(f"   as reader.rs reads it: phase=u8@+0x00 = {w[0]}  "
          f"(the doc says <5 = active fight, 5 = KO, 6 = win-pose, 9 = results)")
    print(f"\nteams (H+0x6C0 per slot) = {[g.read(blk + H0 + i * STRIDE + 0x6C0, 1)[0] for i in range(6)]}")
    d = digest(g, blk, g.u32(blk + FC_OFF))
    if d:
        f, slots, gl = unpack_chk(d)
        print(f"live digest @frame {f}:")
        for i, s in enumerate(slots):
            print(f"   slot{i} hp={s['hp']:3d} red={s['red']:3d} pos=({s['x']:9.2f},{s['y']:8.2f}) "
                  f"vel=({s['vx']:7.2f},{s['vy']:7.2f}) sid={s['sid']:5d} drawn={s['drawn']} face={s['facing']}")
        print(f"   globals {gl}")


if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "info"
    if c == "rec":
        rec(sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 0.0)
    elif c == "play":
        # ⚠ FF is OFF by default. 0x14003A2D0 stores 1 into G+0x798 unconditionally at the top of
        # every tick, so writing it from outside is a RACE — the number of frames the sim runs per
        # tick is nondeterministic, and using it across the character-select portion feeds those
        # inputs with nondeterministic gaps. Fine for "get there fast", not for verification.
        play(sys.argv[2], "--ff" in sys.argv)
    elif c == "ab":
        ab(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].isdigit() else 900)
    elif c == "probe":
        probe()
    else:
        info(sys.argv[2])
