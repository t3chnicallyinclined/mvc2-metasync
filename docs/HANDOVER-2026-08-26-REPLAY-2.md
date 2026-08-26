# HANDOVER — 2026-08-26 (session 2) — the replay lane, after adversarial review

Read `HANDOVER-2026-08-26-REPLAY.md` first for the original discovery. **This page corrects it in
three places and adds what was measured since.** Where the two disagree, this one is newer.

If you are another agent working in this project: §7 says what is mine, what is yours, and what you
must not re-derive.

---

## 0. The one-paragraph version

The previous session proved MvC2 Steam ships GGPO rollback and that `blk[0..0x33B18)` is the single
registered save/restore region, then concluded that region is "the complete deterministic simulation
state." **That conclusion is stronger than the evidence and is now marked unproven.** Rollback
certifies `blk` holds everything that *changes* during a match; replay also needs everything the sim
*reads*. Since then: settings, the 56-bit unlock mask and the stage id were all confirmed *inside*
`blk`; the DC-derived RNG worry was swept out of `blk`, the exe and the arena and found nowhere; the
projectile/assist/effect object pool was confirmed inside `blk` at the stride DC predicted; and the
agent's capture was found to have a real gap that would have made every tape unreplayable. The gap
is fixed. The determinism question is now down to one behavioural test that needs a full-match tape.

---

## 1. ⚠ CORRECTIONS to the previous handover and to agent 0.3.24's first release note

| claim | status |
|---|---|
| "`blk` IS the complete deterministic simulation state, certified by Capcom's own shipping netcode" | **OVERSTATED.** GGPO proves `blk` ⊇ everything that CHANGES in a match. State set before a match and only read during it never needs restoring, so rollback works without it. **Rollback-sufficiency ≠ replay-sufficiency.** Corrected in `STEAM-GGPO-DETERMINISM.md` §1, `Cargo.toml`, and memory. |
| "373× fast-forward is shipping code / a setting" | **Half right.** The *speed* is real (22,403 sim frames/sec, reproducible). The *control* is not: `G+0x798` is a bucket the run loop DRAINS (`G[0x798]--` per frame) and the tick refills to 1, so `ffspeed.py` works by topping it up faster than it empties. You can never say "run exactly N frames". Worse, at that speed an external poller **cannot put a distinct input on each frame** — frames are ~45 µs apart. FF was on by default across every replay's character-select portion, where the cursor input changes every frame. **Now off by default** (`--ff` to opt in). The real fix for a deterministic speed setting is to patch the immediate at `0x14003A2D0` from 1 to N; frame-accurate feeding *at* speed needs in-process injection. |
| "804 intra-blk + 243 arena pointers relocated" | The arena half were **243 no-ops**. `arena == 0x97e1000` in 6/6 captures ever taken, so `d_arena` has always been 0 and that branch has never changed a byte. Its false-positive window is ~1,268× the blk one (6.25% of address space vs 0.005%). `rrtape4.py` now **hard-fails** on a non-zero arena delta rather than trusting untested code. The blk branch is falsified-safe: 804/804 correct across three cold boots, zero false positives. |
| "two replays were bit-identical ⟹ the tape reproduces the match" | Still **self-comparison** — the recorder never stored an outcome, and both compared artifacts came from the replay path. What it does prove: the sim is bit-deterministic given (state, inputs) in one process. Fixed by checkpoints (§3). |
| my own `blk2` similarity check reporting "82.6% match" | **Meaningless and my bug.** `blk2` is all zeros and `blk` is mostly zeros, so it measured zero-matching-zero. Fixed to compare only where `blk` is non-zero, and to say plainly when a region is empty. |

---

## 2. What was MEASURED this session (live, on the running game)

### 2.1 Registration is a FORK — assert it, never assume it
`FUN_140118290` branches on **`G+0x48`**: `< 3` registers **10–18 regions** (the emulated-CPS path —
that is how the collection's CPS2 titles work); `>= 3` registers exactly one. **MvC2 reads 11.**
Everything the replay lane claims depends on that arm.
`DAT_142d10950 / 142d107d0 / 142d108d0` (what GGPO recorded as registered) read **0 offline** —
registration only happens when a session starts. Re-read them during an online match.

### 2.2 `blk2` exists and is empty
`blk2 = blk + 0x33B18`, size `0x33B20` = exactly `sizeof(blk) + 8` — the shape of a savestate slot.
Registered at `G+0x1c0`/`G+0x1c8`, **not** in the rollback list. **Measured entirely zero**, unchanged
across 100 samples of live play. It holds no state, so it cannot be a "written before, read during"
hazard. Almost certainly the rollback save buffer, empty because nothing has saved.
⚠ **Re-check during an online match** — that is the only time it would fill.

### 2.3 The RNG is not the DC one, and is not in `blk`, the exe, or the arena
| region | words | changed in 600 frames | LCG hits |
|---|---|---|---|
| `blk` | 52,934 | 5,643–7,689 | none |
| exe image | 17,014,784 | **315** | none |
| arena (256 MiB) | 67,108,864 | 54,090 | none |

Scanned with the closed form `x1 == x0·A^k + B_k` for the DC constants (`A=0x41C64E6D, C=0x3039`),
k up to 38,400. **The recompile did not keep DC's generator.** The scan cannot see a *different*
generator, so this narrows the question rather than closing it.
⭐ **The useful number is 315.** In the whole 68 MB executable image only 315 four-byte words move
over ten seconds of play. If sim-relevant static state exists outside `blk`, it is in those 315
words — an enumerable set, not a haystack. Nobody has enumerated them yet.

### 2.4 ⭐ The satellite object pool is CONFIRMED and it is INSIDE `blk`
Predicted from DC (base `0x8C26AA54`, stride `0x1D0`, 256 nodes) → **observed live: stride `0x280`
exactly**, as the GCD of the gaps between 139 distinct live handles, spanning `blk+0x72d8` ..
`blk+0x2ded8`. Base must be `0x72d8 − n·0x280`; the head-list prediction at `0x2ee34` forces n ≥ 2,
so **base ≈ `blk+0x6dd8`** (250 of 256 nodes seen) — INFERRED, not pinned.

**The node is a prefix of the fighter struct**, so the existing fighter reader works on it verbatim.
Read live through the fighter layout:
```
world=(698.1, 0.0)  screen=(520.0, 433.4)  sid=986  drawn=1  layer 5
```
and `sy = ground − wy = 433.4 − 0.0 = 433.4` — exactly the node's screen y. The ground line and the
screen-coord formula confirm each other on an object class we had never read.
⟹ **assists, projectiles, hitsparks and super flashes are rolled back, carried by the anchor, and
free to read.** Find them with `verify.py pool` — no scanning, the draw list already points at them.

### 2.5 ⭐ The camera block, settled by watching what moves
```
blk+0x6914  camera X          MOVES
blk+0x6918  camera Y          MOVES
blk+0x691c  812.3571          CONSTANT   <- DC's eye-distance / zoom divisor. Never changes on this
                                            build, so there is nothing to record. Do NOT add it.
blk+0x6990  = camera X − 320.0    (exact, both endpoints)   screen left edge
blk+0x6994  = camera X + 320.0    (exact)                   screen right edge  (640 = CPS native)
blk+0x6998  = camera Y + 338.4    (exact)   <- "ground". CAMERA-RELATIVE SCREEN SPACE, not a stage
                                                constant. That is why sy = ground − wy works, and
                                                why recording it per frame was right.
blk+0x69b0  = camera Y + 98.4     (exact)
blk+0x69a0/4  ±1280               CONSTANT   stage world X bounds
```
Also: `blk+0x68c0..0x6910` is **all zero**, so the fighter array really does end at `0x6908` and the
stage struct starts at `0x6914`. That resolves the 0x10 overlap the SH4 expert flagged — his
semantic anchor at `0x68f8` was wrong. ⚠ The DC spacing does **not** carry through this region; do
not extrapolate DC offsets past the anchors here.

### 2.6 ⭐⭐ Character select is reachable in EVERY mode — and the frame counter RESETS
Walked training / versus / arcade / hosted lobby with `verify.py watch`:
- **`blk+0x3CB8[2] == 1` appears in all four.** The anchor gate is mode-agnostic. Versus, arcade,
  training and lobby can all be anchored.
- **Byte[0] distinguishes modes** (observed 1 and 2) and bytes [3]/[4] are sub-states within a
  screen (picking → assists → confirm → stage). Byte[2] is the only one we rely on.
- ⚠⚠ **The sim frame counter resets to 0 on every mode entry.** Observed repeatedly:
  `[0,0,0,0,0] frame 0` → `[1,0,0,0,0] frame 1` → … It is monotonic *within* a mode session only.
  Anything comparing frame numbers across mode entries is wrong.
- Character select runs **~500–1800 frames** before the mode byte flips to 2.
- Session kind (`session+0xd0328`) reads `custom` in a hosted lobby, and stays latched afterwards —
  it is not a reliable "what am I in right now" signal on its own.

### 2.7 The recorder holds up over a full match
118 s, **7,040 frames at 59.7 fps, `gaps 0, filled 0, lost 0`, 235 checkpoints.** The Python poller
did not miss a single frame in two minutes. That was the open risk for full-length tapes.

---

## 3. What changed in the code

### `RetroReceipts-agent` — branch `replay-capture-0.3.24` (NOT merged, NOT released)
| | |
|---|---|
| `seat_in[2]` per frame | the authoritative raw pad words at `G+0x218+seat*4`, appended to the schema |
| `seat_map` / `rollbacks` / `build_id` | envelope; `build_id` = module PE TimeDateStamp + SizeOfImage |
| **anchor** | gzip+base64 of `blk[0..0x33B18)` at character select, ~17 KB, with a frame-counter torn-read guard |
| **`anchor_hash`** | FNV-1a of the raw region — identity + free server-side dedup, never used to skip a capture |
| **`select_in`** | ⭐ **the fix for §4.1** — every character-select frame's inputs, gzip+base64 |
| `start_sim_frame` | drops an anchor that is not strictly before the match's first sim frame |
| `frame_first/last/span/gaps/truncated` | tape continuity stated instead of assumed |
| `#![recursion_limit = "256"]` | the envelope outgrew `serde_json::json!`'s default expansion depth |

### `mvc-live-skins-quarters/replay-kit`
- **checkpoints** every 30 frames: a pointer-free per-fighter digest (hp/red/pos/vel/sprite/drawn/
  facing) **plus a CRC32 of the whole sim region** with the frame counter and its mirror excluded.
  Playback reports **the frame divergence started on** instead of "the end state looked right".
- **gap fill** from `G+0x228` when the poller misses exactly one frame; wider gaps counted and the
  tape declares itself damaged.
- **auto-stop on a team wipe** held 2.5 s. ⚠ The mode byte is NOT an end-of-match signal — measured
  live, it stayed at 2 through the KO, the win pose and the results screen for a full 118 s.
- **Ctrl-C / ENTER stop and SAVE.** The first version packed only after the loop, so interrupting a
  two-minute recording discarded it. `rec()` also now catches *any* exception and packs anyway,
  because `Game.read` **raises** on a failed RPM rather than returning `None`
  (`savestate.py:83`) — every `if x is None` guard in the kit was dead code.
- **`verify.py`** — the falsification harness: `watch`, `rng`, `pool`, `cam`, `blk2`, `reg`.
- **`rrtape4.py ab`** — the generator-agnostic test (§5).

---

## 4. ⚠⚠ The bug this session found in its own work

### 4.1 The anchor and the match frames did not compose
The agent's frame buffer starts at **match load**. The anchor is a **character-select** state (the
only portable kind). Restore the anchor, feed the battle inputs, and the game is still sitting at
character select with no picks made — **the 500–1800 frames of input that navigated the screen and
locked the teams in were never recorded.** Every tape 0.3.24 would have produced was unreplayable.

Found by walking the modes with `verify.py watch` and noticing how long character select runs.
Fixed by `gs_record_select`: take the anchor, then record character select at ~60 Hz until the mode
byte leaves 1 — which is exactly where the existing match-load gate takes over, so the input stream
is continuous from the anchor frame into the battle frames. Bounded at 120 s / 8,192 frames so a
person idling on character select cannot grow the buffer without limit.

**The manual kit never had this bug** — `rrtape4.py rec` refuses to start anywhere but character
select and records continuously from there. Only the agent path was broken.

---

## 5. What is still OPEN — and what settles each

| # | question | the test | cost |
|---|---|---|---|
| 1 | **Does anything outside `blk` affect a match?** The whole determinism claim. | `AB.cmd` — restore anchor → replay → restore anchor → **churn 900 frames of random input** → restore anchor → replay the same tape → compare **frame-locked** digests. A == C ⟹ nothing outside `blk` survives a restore, regardless of which generator this build uses or where it lives. Strictly stronger than "two replays matched", which had nothing in between. | needs one full-match tape |
| 2 | **Does a full match replay?** Nothing longer than 20 s has ever been re-simulated. | `REC4.cmd` → play it out → `PLAY4.cmd`. Now reports the divergence frame. | ~5 min |
| 3 | **Arcade mode** — P2 is the CPU, so seat 1 carries no input. Re-simulation depends on the AI living entirely inside `blk`. DC evidence is encouraging (the RNG's consumers exclude the CPU AI interpreter) but that is inference. | `REC4`/`PLAY4` **in arcade**. | ~5 min |
| 4 | **The 315 changed exe words.** The only place sim-relevant static state could still hide. | snapshot the exe, advance N frames twice, classify each changed word by its delta pattern (steady increment = counter; erratic = candidate). Not built. | ~1 h |
| 5 | **Cross-boot / cross-machine.** Everything proven is same-process. A cold-boot replay is the first real test of portability, and the first chance to see `d_arena != 0`. | record, restart the game, `PLAY4` the same tape. | ~10 min |
| 6 | **Online / under rollback.** Every test so far ran offline, rollback count 0, seat map zero. Money matches are online. Under rollback the 3 ms sampler will miss frames on every rewind. | record one ranked/lobby match, check `frame_gaps == 0`, then re-simulate. | ~2 h |
| 7 | **Build gating.** `build_id` is captured but **nothing gates on it.** Steam auto-updates. | refuse to re-simulate when `build_id` ≠ the node's; adopt Fightcade's match-timestamp → build manifest. | ~1 h |
| 8 | **Pool base** is inferred (`blk+0x6dd8`), not pinned. | watch the draw list longer to catch node 0/1, or read the head-list pointers at `blk+0x2ee34`. | ~10 min |

**Verdict: this is a replay/highlight feature, not a money-dispute receipt.** Do not let a coin move
on a re-simulation until 1, 2 and 6 have passed and 7 exists.

---

## 6. Prior art — copy these, they solved it first

From reading Flycast Dojo (what Fightcade runs MvC2 on):
- ⭐ **Match-timestamp → build-commit manifest.** Dojo parses the first 10 chars of the Quark as a
  unix epoch and resolves *the newest savestate commit older than the match*. **This is the answer to
  Steam auto-updating under us** and the single most valuable idea in their tree.
- **Savestate by reference**, never embedded, cached under its content id. Our `anchor_hash` is the
  hook for this.
- **Score-detection cooldowns**: 600-frame win debounce, 1200-frame match-end cooldown, and an
  `in_match` gate before trusting win counters. Every one of those is a bug someone shipped first.
- **Batch and always flush the tail**; `memset` the header buffer before each read so a truncated
  file terminates cleanly.
- ⚠ **They have NO per-frame integrity check** — theirs is `#ifdef SYNC_TEST` and ships disabled.
  Nothing to copy for integrity; our checkpoints are the thing they didn't build.
- ⚠ Do not copy their container: 24 B/frame with 12 bytes of hardcoded zero padding, uncompressed.
  Ours is ~2.1 B/frame.

---

## 7. Lanes — for whoever else is working here

**What this lane owns:** the replay/re-simulation path. `mvc-live-skins-quarters/replay-kit/**`,
`docs/STEAM-*.md`, `docs/HANDOVER-*REPLAY*.md`, and in `RetroReceipts-agent` the branch
`replay-capture-0.3.24` (`agent/src/reader.rs` gamestate capture + `docs/`).

**⚠ Do not merge `replay-capture-0.3.24` to main or cut a release from it without Tris.** It is
compile-clean and tested but has never run against a live game, and the determinism question in §5.1
is open.

**Do not re-derive these — they are measured and written down:**
- the block/camera/pool offsets in §2.4–2.5 and `mvc2-dc-steam-block-map` in memory
- that the mode byte is not an end-of-match signal (§3)
- that the frame counter resets per mode entry (§2.6)
- that `Game.read` raises rather than returning None (§3)
- that the arena relocation branch has never been exercised (§1)

**If you touch `agent/src/reader.rs`:** the gamestate capture thread (`start_gamestate_capture`,
`gs_try_anchor`, `gs_record_select`, `read_gs_row`, `spool_gamestate`) is this lane's. The opponent
detection, skins, lobby and result paths are not.

**Experts to ask before guessing** (now in `~/.claude/agents/`, copied from `maplecast-flycast`):
`mvc2-sh4-re-expert` for anything about MvC2's memory layout — the DC disassembly answers most
Steam questions and it is far cheaper than a differential capture; `senior-re-generalist` to attack
a claim before it ships; `flycast-internals-expert` for Dojo/replay prior art.

---

## 8. Full commands

```
C:\Users\trist\projects\mvc-live-skins-quarters\replay-kit\WATCH.cmd     mode byte through every menu (read-only)
C:\Users\trist\projects\mvc-live-skins-quarters\replay-kit\VERIFY.cmd    falsification harness (read-only)
C:\Users\trist\projects\mvc-live-skins-quarters\replay-kit\REC4.cmd      record a tape from character select
C:\Users\trist\projects\mvc-live-skins-quarters\replay-kit\PLAY4.cmd     replay it, report the divergence frame
C:\Users\trist\projects\mvc-live-skins-quarters\replay-kit\AB.cmd        the determinism test (§5.1)
C:\Users\trist\projects\mvc-live-skins-quarters\replay-kit\PROBE.cmd     one-shot anchors + the blk+0x32500 conflict
```
`VERIFY.cmd` takes a subcommand: `watch`, `rng [frames] [--exe] [--arena]`, `pool`, `cam`, `blk2`,
`reg`. Run `rng` and `pool` **during a busy fight** or they see nothing.

⚠ One unresolved conflict worth a single read: `reader.rs:101` reads `phase` as a u8 at
`array+0x2e5dc` = `blk+0x32500`, which is exactly where `rrtape4.py`'s self-check reads the six
fighter self-pointers — and that self-check passes. Both cannot be right. `PROBE.cmd` prints both.

---

## 9. How to work on this

Everything in §10 of the first handover still applies. Added by this session:

- **Measure which fields MOVE before recording them.** `blk+0x691c` looked like the camera zoom and
  is a constant; three seconds of sampling settled it and saved a useless tape column.
- **A similarity metric between two mostly-zero buffers means nothing.** Compare only where the
  reference is non-zero, or you will report agreement that is an artifact.
- **When a probe comes back negative, say what it does and does not rule out.** The RNG scan is
  keyed to specific constants; "no LCG found" is not "no RNG outside blk".
- **Give Tris the full absolute command, every time.** Naming a script makes him hunt for it.
