# Confirmed-input tape + `.flyr` replay — the pixel-perfect path, grounded

> Written 2026-08-27. This is the convergence of two independent efforts: the flycast-NAOMI
> **determinism test** (gsta-verification-harness) and the **GGPO/dojo replay source study**
> (flycast-internals-expert). They agree exactly. This is not a guess — it is dojo's own recipe.

## 0. The one-sentence result

**flycast-dojo replay is pure forward playback of the CONFIRMED (post-rollback) input stream from a
savestate anchor, with ZERO rollback on replay.** That is why dojo has no frame skew, and it is
exactly the fix for our tape. Our tape currently records the *predicted* input latch (`G+0x218`) with
rollback-laden frame indexing; the fix is to record the *confirmed* inputs from the InputQueue ring,
keyed by frame from 0 at the anchor, and replay pure-forward.

## 1. What the determinism test PROVED (raw sim state, exact — the skeptic's gate)

On the IzzyBear match (59595179), comparing **raw** `px,py,vx,vy,hp,facing` at exact equality (not
screen coords):
- **A constant −6-frame shift makes flycast BIT-EXACT to the Steam match** across f1626–1643, all six
  fighters, every raw float. flycast runs exactly 6 frames ahead of the tape.
- **NOT FP** — bit-exact floats at the offset; if FP differed cross-core it would be impossible.
- **NOT emulator pacing** — a game-frame-paced feeder was built and was a **no-op** (kb: game-frame =
  vblank in MvC2, so the emulator can shift input at most ±1 frame; a 6-frame skew can't come from it).
- **NOT RNG** — the exact window is RNG-blind, `srand(1)` seeds identically, state matches bit-exact,
  so the RNG stream is in sync; the f1645 whiff is *geometry* from the index drift, not a random roll.
- **Root cause:** the tape carries **941 GGPO rollbacks**; ~6 rollback re-sim frames accumulated during
  a rollback-heavy idle. The tape is the RAW rollback-laden capture, not the collapsed confirmed sequence.

⚠ Still **RNG-blind** — bit-exact only up to the first hit. Through-combat determinism is strongly
evidenced but **not yet definitively proven** (see §6 gate). Cross-core (Steam→flycast), so it must be
positively demonstrated on a confirmed-input tape, never assumed.

## 2. How dojo does it — the proven recipe (CONFIRMED from `flycast-dojo-ref` source)

### The `.flyr` format (v3 = the GGPO/rollback replay)
- Length-prefixed messages, 12-byte header (`size:u32, seq:u32, cmd:u32`).
- `SPECTATE_START(3)` header: `version, GameName, PlayerName, OpponentName, Quark, MatchCode, analog`,
  and for v3: **`state_md5`, `state_commit`**.
- `MAPLE_BUFFER(6)`: `frame_size:int(=24)`, then N × **24-byte frames = `{frame_num:u32, input payload 20B}`**
  (`_input_size*_num_players` bytes used; MvC2 NAOMI = 4 bytes/player kcode, analog=0). Batched 120/msg.
- `PLAYER_WIN(7)`: round-win markers.
- **NO savestate bytes** — the anchor is a separate `<slot>.state.net.<commit>` file, referenced by md5+commit.

### The replay loop (pure forward, zero rollback)
```
dc_loadstate(anchor)        // full machine snapshot: SH4 regs, RAM, VRAM, ARAM
FrameNumber = 0
maple_inputs[]  fully preloaded from the .flyr
loop:
   maple DMA → setMapleInput reads maple_inputs[FrameNumber] → kcode = ~inputs[player*4]
   run exactly one game frame (runInternal until sh4_cpu.Stop())
   STARTRENDER → endOfFrame(): FrameNumber++
   nextFrame() → true            // NO ggpo_advance_frame / save / load — pure forward
```
Input latched at maple DMA; frame index bumped at render — the *same two boundaries* used when
recording, so frame N's input is exactly the input confirmed for frame N. Playback is a **keyed
lookup** `maple_inputs[frame_num]`, not a positional stream — no off-by-delay possible.

### Why NO skew (the crux)
The recorder writes **only `total_min_confirmed`** — frames both players' real inputs have arrived for
(`p2p.cpp:135-155`, `GetConfirmedInputs`). The predicted leading edge (up to `MAX_PREDICTION_FRAMES=8`
ahead) is **never written**. Rolled-back/mispredicted frames are discarded; only the survivor is
emitted. The skew lives entirely in the network present tense and never reaches the file.

### The determinism gates (copy these)
- **`state_commit`** (build/git SHA) → selects the exact `.state.net` anchor
- **`state_md5`** → both sides must hold the byte-identical anchor
- **`gameMD5`** → ROM/content hash
Frame clock = `dojo.FrameNumber`, one tick per rendered game frame — not vblank, not wall-clock.

## 3. The corrected anchor — flycast's own, NOT Steam-injected

⚠⚠ flycast **cannot load a Steam savestate** — the Steam FC is an x86-64 recompile; it shares DC
lineage with NAOMI but NOT serialized machine state. So:
- The anchor is **flycast's own NAOMI MvC2 char-select `.state.net`** (or a deterministic cold-boot to
  char-select), never the Steam `blk` anchor.
- We **transplant our Steam-captured CONFIRMED inputs** onto flycast's anchor, keyed from frame 0.
- `srand(1)` at battle init reseeds the RNG **by running the ROM** — so the anchor only has to be
  at/before battle init; nothing needs "carrying." This retires the blk-injection idea entirely (it was
  triple-blocked anyway: layout mismatch, missing out-of-blk regions, ~20-cycle mid-restore drift).

## 4. THE TAPE CHANGE (the actionable fix)

Record the **confirmed** input stream instead of the predicted latch:
- Read both players' inputs from the **InputQueue ring** we located
  (`session=*(u64*)0x142E10B98 → Sync=+0x9F0 → queues=*(u64*)(sync+0x190) → _inputs[f%128]`, stride
  `0xE44`, GameInput `{i32 frame; i32 size; u8 bits[]}` at +40), gated on the confirmed watermark
  (`Sync::_last_confirmed_frame` @ `sync+0x184`, or `min(_last_added_frame)` over the queues).
- Emit each frame ONCE, in order, keyed by its confirmed frame number, collapsing the rollback re-sims.
- Keep `G+0x218` alongside for one release (audit), but the RING is the source of truth for replay.
- Number from 0 at the anchor frame.
See `STEAM-GGPO-INPUTQUEUE.md` for the ring RE (confirmed live: 128-slot ring, `frame%128` index).

## 5. THE CONVERTER (tape → `.flyr`)

`steamtape_to_flyr(tape) -> .flyr`:
1. `SPECTATE_START(v3, names, analog=0, state_md5=<flycast anchor md5>, state_commit=<flycast build sha>)`
2. `MAPLE_BUFFER(frame_size=24, [{frame_num:u32, p1_kcode:u32, p2_kcode:u32} for each confirmed frame])`
   — Steam raw pad → semantic → DC kcode via the solved Rosetta table (below), `~kcode` convention,
   4 bytes/player, numbered from 0 at the anchor.
3. optional `PLAYER_WIN` per round.
4. place the matching `<slot>.net.<commit>` flycast anchor file; set `PlayMatch=true`.
Then dojo's `LoadReplayFileV1`/`ProcessBody`/`setMapleInput`/`endOfFrame` runs it untouched.

### The input mapping (Rosetta, solved + verified)
Steam raw pad word (`G+0x218`) → semantic:
`0x10=UP 0x20=RIGHT 0x40=DOWN 0x80=LEFT | 0x200=A1 0x800=A2 0x1000=HP 0x2000=HK 0x4000=LK 0x8000=LP`.
Semantic → DC kcode (`DC_PAD_BIT`): U/D/L/R=bits 4/5/6/7, LP=X(10), HP=Y(9), LK=A(2), HK=B(1), A1=Z(8),
A2=C(0). Routing identity (seat0→P1). ⚠ point characters identified by sprite-id match, NOT team-array
order (fixture point chars were P1=42/P2=27, not the array-first 44/15).

## 6. THE GATE — before the fork is worth committing

The acceptance test, per the RE-process audit — exact, on raw state, on an RNG-exercising match:
1. **Full match exact THROUGH COMBAT** — load flycast anchor, feed the confirmed inputs forward, assert
   byte-identical raw sim state through the first super's RNG consumption (hitspark/stun), not just
   round start. First-divergence frame ≥ match end. Log the RNG-draw count to prove the window wasn't
   a neutral re-run.
2. **The realignment test** already settled pacing-vs-RNG (constant −6 shift = pacing/tape-index, not
   drift). Re-confirm on the confirmed-input tape: with correct frame keying there should be NO shift.
3. **Cross-boot reproduction** — record, restart flycast, replay, exact (first portability test).
4. **Arcade/CPU-AI exact** — the AI is the largest reads-not-writes hazard (partly out of blk).
Until 1–4 pass, the fork is premature. Path 1 (browser draw-list read) is primary and ships now.

## 7. Sequencing (unchanged from the audit)
- **Path 1 (browser draw-list)** — no re-sim determinism needed, ~proven (36/36 harness). Primary; ships.
- **Path 2 (flycast `.flyr` replay → TA-mirror render)** — pixel-perfect; gated on §6. The "fork" is now
  small: dojo's replay path + maplecast's TA render, fed a converted tape. Not a from-scratch engine.

## Source anchors
- Determinism test: `scratchpad/realign3.py` (the decisive per-frame exact-match shift), `tape_izzy.json`.
- Dojo replay: `flycast-dojo-ref/core/dojo/DojoSession.cpp` (.flyr write/parse), `core/network/ggpo.cpp`
  (`setMapleInput` 941-977, `nextFrame` 653-766, `endOfFrame` 931-939, VerificationData 100-107),
  `core/deps/ggpo/lib/ggpo/backends/p2p.cpp:135-155` (confirmed-input recorder), `sync.cpp`/`input_queue.cpp`
  (rollback algo, MAX_PREDICTION_FRAMES=8, INPUT_QUEUE_LENGTH=128), `maple_if.cpp:147-152`, `gui.cpp:113-170`.
- Ring RE: `docs/STEAM-GGPO-INPUTQUEUE.md`. Audit: `docs/REPLAY-ENGINE-DESIGN.md` §6.
