# RECEIPT-RUNNER-PLAY — the playable loop: a human drives the real frame function (2026-09-04)

Owner lane: SUPERGUN ENGINE. Goal changed from proving correctness to **producing something a person can sit in
front of**. Deliverables: `d3dcap/receipt/runner/rr_runner.cpp` (`--play`, `--play-frames`),
`d3dcap/receipt/play_session.py`, seed `maplecast-flycast/tools/re_kb/141_playable_loop.surql`.

## 0. Status, stated plainly

**The chain closes mechanically, end to end. No human has pressed a button yet.** Everything below was measured
with nobody at the controls, which is why `rr_runner --play` prints, and means, this:

```
PLAY: NO INPUT WAS EVER PRESSED -- nothing was proven about a human in the loop.
```

That guard exists so a green-looking run can never be mistaken for the thing we are actually trying to prove. The
one command Tris needs to run is in §4.

## 1. What the loop is

Four stages, three of them already gated; the only new thing is the person.

| # | stage | status |
|---|---|---|
| 1 | `dcram_build.py` — DC-RAM from the user's own arc, **no memory dump** | GATE 3 / GATE 4 |
| 2 | `rr_runner --play` — gamepad → 2 pad words → `FUN_140118950`, paced 60 Hz | **NEW** |
| 3 | `--harvest-dump` + `rr-tape` — that memory → a v5 tape | GATE 2 |
| 4 | `player.html` — tape → WebGPU pixels | L1 / L3, in production |

### The pad words are not a new invention

`FUN_140118950` takes the two seat words as its entire input (`DETERMINISM-CONTRACT` §1), so **a human pressing a
button produces the identical object a receipt replays** — there is no second input path that could be wrong. The
bit layout was already solved and verified (`docs/CONFIRMED-TAPE-AND-FLYR-REPLAY.md` §5):

```
0x10 UP   0x20 RIGHT   0x40 DOWN   0x80 LEFT
0x200 A1  0x800 A2     0x1000 HP   0x2000 HK   0x4000 LK   0x8000 LP
```

Cross-checked against real recorded tapes before use: `0x000080` = walk left, `0x000020` = walk right,
`0x0020C0` = down-left + HK. Gamepad: X=LP Y=HP A=LK B=HK LB=A1 RB=A2, d-pad or left stick for directions
(XInput loaded dynamically, so no link-time dependency). No gamepad → keyboard: arrows, Z/X/C = LP/HP/A1,
A/S/D = LK/HK/A2.

## 2. Measured cost — the honest baseline

120-frame session, arc-built stage-9 anchor, `--harvest-dump` on, nobody at the controls:

| quantity | value |
|---|---|
| sustained rate | **59.8 fps** (120 frames in 2,005 ms) |
| **tick alone** (`FUN_140118950`) | p50 **0.176** ms, p90 0.266, p99 0.421, max 0.541 |
| **per-frame work** (pad read + tick + harvest dump), excluding the 60 Hz sleep | p50 **8.96** ms, p99 12.26, max 12.30 |
| harvest + `rr-tape` for the whole 120-frame session | 0.2 s |
| tape produced | 121 frames, 70,785 B |
| `emit_seq` on that tape | 60 frames → 35,380 draws, 73.4 MB `.seq` |

**Where the frame actually goes:** the tick is ~1 % of the 16.667 ms budget; the **per-tick state capture is ~54 %**.
The dominant cost is `--harvest-dump`'s 32 MB memcmp against a shadow to find changed DC-RAM pages — not the
simulation. If the loop ever needs headroom, that is the thing to attack (dirty-page tracking instead of a full
compare), and it is a capture concern, not an engine one.

Note the tick p50 here (0.176 ms) is higher than Gate 1's 0.08 ms. Same code, different conditions: the harvest
dump evicts cache between ticks and the 60 Hz `Sleep` leaves a cold cache at the start of each frame. Both numbers
are real; quote the one that matches the workload.

## 3. What is NOT done

- **The render is not live.** The human currently plays *blind*: the console shows their pad word and the
  character's `px`/`py` every frame, and the pixels are produced from the tape **after** the session. That is the
  remaining gap between this and "a human in the loop" in the full sense.
- No opponent (seat 1 is held at 0), no netcode, no rollback — all deliberate.
- The idle animation moves `py` on its own, so `py` is **not** evidence of a human. `rr_runner` reports the first
  frame with a non-zero pad and, separately, the first `px` change *after* one. `px` is stable at rest.

## 4. Running it

```
python C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\receipt\play_session.py --frames 600
```

600 frames = 10 seconds. It builds DC-RAM from the arc, hands you the pad for 10 s, harvests, and prints the URL:

```
cd C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\replay && python serve.py 8099
http://127.0.0.1:8099/player.html?tape=packs/local_stage9/play_tape.json.gz&pack=packs/local_stage9&auto=1
```

## 5. Tags

| item | tag |
|---|---|
| Pad-word bit layout | CONFIRMED (pre-existing, re-checked against recorded tapes) |
| The loop sustains 60 Hz with per-tick harvest | CONFIRMED (120 frames, 59.8 fps) |
| Tick cost inside a 60 Hz interactive loop | CONFIRMED (p50 0.176 ms) |
| A play-produced tape renders through the gated pipeline | CONFIRMED (`emit_seq`, 35,380 draws / 60 frames) |
| **A human moved a character** | **NOT PROVEN — needs Tris at the controls (§4)** |
| Live (in-session) picture | NOT BUILT |

---

# Addendum A — the first human session, and the two defects it exposed (2026-09-04)

Tris ran `--frames 600`. **First input frame 17, first px change frame 277.** The loop closed: the real frame
function ran from his own arc with his hands on it. Two defects in the same log.

## A1. The controller was on XInput user index 1, and `padRead` polled only index 0

**CONFIRMED, and found by the new probe in three seconds without needing him again:**

```
pad: XInput controllers connected on user index mask 0x2
```

Mask `0x2` = user index **1**. The first `padRead` polled index 0 only, got `ERROR_DEVICE_NOT_CONNECTED`, and
**fell through to the keyboard — so his gamepad was invisible for the whole session.** The bits he did produce
(`0x0800`, `0x2000`, `0x4000`) are exactly keyboard **A, S, D**; he never set `0x8000`/`0x1000`/`0x200`, which are
Z/X/C on the row below. So he was holding a controller whose stick and d-pad went nowhere, while three stray
keyboard keys supplied the only input that reached the sim.

Three bugs, each of which drops direction input silently:

1. **the XInput branch `return`ed early**, so with any controller connected the keyboard was never read;
2. **only user index 0 was polled**, so a pad on 1–3 contributed nothing — this is the one that bit;
3. the stick deadzone was **12000** (37 % of full scale) against XInput's own **7849**.

Fixed: all four indices polled, the keyboard **always** OR-ed in, deadzone 7849, and the raw
`xiMask / wButtons / LX / LY / kbBits` recorded in `g_padRaw` so a session can be audited instead of guessed at.

### The headline is now gated on a DIRECTION, not on any input

The old "first human-caused move" fired on pad `000800` = **A2 alone**. An assist call is not locomotion, and the
px slide that follows is animation displacement. `rr_runner` now reports separately:

* `*** FIRST INPUT ***` — first non-zero pad word
* `*** FIRST DIRECTION ***` — first pad word with a bit in `PAD_DIRS` (`0xF0`)
* `*** STEERING PROVEN ***` — first px change **after** a direction was held

and when no direction ever appears it says so in as many words: *inputs reached the sim, but STEERING IS UNPROVEN*.
Same failure shape as `py`'s idle bob: a signal that reads like the claim you want but is not it.

### New: `--pad-probe`, the input path alone

```
C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\receipt\runner\rr_runner.exe --pad-probe 10
```

No image, no anchor, no tick — it polls, prints the raw sources next to the synthesised word, and states whether
any direction was seen. This is what should have existed before the first session.

## A2. The stall is the capture, not the engine — measured, not argued

Tris saw 57.9 fps, p99 **34.36 ms**, max **97.74 ms**, with frames genuinely lost, while the tick stayed at p50
0.164 / max 0.749 ms. The cheap discriminator (600 frames each, same anchor, same build, nobody at the controls):

| arm | fps | per-frame work p50 | p99 | max |
|---|---|---|---|---|
| harvest **inline** (as he ran it) | 58.4 | 10.357 | 34.099 | **58.054** ms |
| harvest **off** | **60.1** | **1.164** | **2.002** | **4.730** ms |

**p99 falls 17×, the worst frame 12×, and the loop holds a clean 60.1 fps.** Confirmed: the per-tick harvest, not
the simulation, breaks the frame. **No memcmp was optimised** — the discriminator came first and settles it alone.

`--play-harvest off` is now the default for `--play`; `play_session.py` needs `--record` to turn it on, and the
trade is stated at the point of use. Moving the harvest to a ring drained by another thread is the real fix and is
**not done**.

## A3. What the first session did and did not prove

| claim | status |
|---|---|
| A human's input reaches the real frame function and changes sim state | **CONFIRMED** (first input frame 17) |
| The chain runs from his own arc with no memory dump | **CONFIRMED** |
| The human can **steer** the character | **NOT PROVEN** — no direction bit was set in 600 frames |
| The loop holds 60 Hz | **CONFIRMED without the harvest** (60.1 fps); with it inline, frames are lost |
