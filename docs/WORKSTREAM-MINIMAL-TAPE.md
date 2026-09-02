# WORKSTREAM — from here to the smallest possible tape

> **STATUS: 2026-09-02, written from three expert reviews** (senior-re-generalist,
> gsta-verification-harness, flycast-internals-expert). This supersedes the first draft of this file
> **including its central premise**, which was wrong. `RENDER-ACCURACY-PROGRAM.md` remains the SSOT
> for what has actually been proven.

---

## 0. ⚠⚠ THE CORRECTION THAT REORDERS EVERYTHING

The first draft of this workstream, and several statements made while writing it, said *"flycast
reproduces Steam's raw sim state BIT-EXACT, so the hard part of Architecture A is already proven."*

**That over-states the SSOT, and the ledger says the opposite.**
`RENDER-ACCURACY-PROGRAM.md:425-436`, 2026-08-30, a frame-exact B2 re-run on a clean tape with
assists on and measured alignment:

> **bit-exact on ALL 6 fighters through f1223** → input/assist/init reconstruction is COMPLETE and
> CORRECT. **FIRST divergence f1224: `char15.px` off by exactly 1 float32 ULP (1.5e-5)**, then
> `char44.vx` 1 ULP as a constant offset — **DC SH4 vs Steam x86-64 rounding**. Benign until the
> **first super**, which amplifies it across a hit-decision boundary → HP cascades → a different
> match. ⟹ **no input/assist/init/RNG fix can close a 1-ULP float gap; free-run resim is NOT viable
> for a full faithful match.**

And gate **G-COMBAT** (`:242-247`) records the status plainly: **"NOT PASSED, NOT KILLED."**

`CONFIRMED-TAPE-AND-FLYR-REPLAY.md`, which the first draft quoted, is the **older and weaker**
result — it labels itself "RNG-blind, bit-exact only up to the first hit". The newer, stricter ledger
entry governs. Two independent expert reviews caught this; it should not have needed catching.

**What this does NOT change:** the input feed is tiny and that number is real and measured.
**What it DOES change:** what a small feed currently buys you.

## 1. The two honest product framings — pick one deliberately

| | **(A) "A faithful replay of this match"** | **(B) "The receipt — THIS match, byte for byte"** |
| --- | --- | --- |
| method | free-run resim from confirmed inputs | needs the 1-ULP gap closed or bypassed |
| feed | **5,610 bytes gzipped for a whole 6,580-frame match** (measured) | same, plus whatever closes the gap |
| fidelity | faithful through neutral and early combat, then **drifts into a different but plausible fight at the first super** | exact |
| status | **works today**, server-side | **falsified as free-run**; one cheap lever untried |
| good for | highlights, a shareable replay, showing what happened | a money-match dispute, a verifiable record |

**Neither is wrong. They are different products, and the difference is invisible in a demo and
decisive in a dispute.** Per `rr-ggpo-determinism`: *do not settle a money dispute on a
re-simulation.* That memory was right and remains right.

⚠ **This decision is Tris's and must be made explicitly, not by default.** If it is (A), Lane A below
ships and Lane C shrinks to a sanity check. If it is (B), Lane C is the whole programme.

## 2. The numbers, measured, so nobody re-derives them

**The feed** — converter run on a real tape this session:
```
tape 59604650: 6,580 frames, teams p1[42,44,50] p2[52,42,56]
movie.txt        144,840 bytes
movie.txt.gz       5,610 bytes    ← the ENTIRE match's input feed
```
Against the TA mirror artefact for a comparable match: `render_ta_wire_full.zcst` = 313,229,658 B for
8,497 frames = **36,864 B/frame**. **Ratio ≈ 50,000 : 1.** The instinct that the feed should be tiny
is right by four and a half orders of magnitude.

**The three per-frame costs, for scale:**
| what | per frame | a 3-minute match |
| --- | --- | --- |
| confirmed inputs (movie.txt.gz) | **~0.9 B** | **~10 KB** |
| the agent's state tape (gzipped) | ~136 B | ~1.5 MB |
| Path B's D3D11 draw stream (gzipped) | ~37-62 KB | ~400 MB |
| the TA mirror `.zcst` | 37-53 KB | **240-350 MB** |

⟹ **Neither the draw stream nor the TA mirror is a delivery format.** Both are internal ground-truth
artefacts. Path B is an ORACLE and an ASSET SOURCE.

**Path B itself** — 300 consecutive frames of a 3-meter triple super replay at 0.011-0.018% of pixels
differing, zero missing coverage. ⚠ That number is our D3D11 replay of a captured draw stream — a
same-engine closed loop. It is a very good number **about the capture** and says nothing about resim,
reconstruction or determinism.

**Assets are bounded:** 379 of 383 texture generations arrive in the first 9 frames of a match;
~1 MB of raw texels covers 4-10 s; 931 KB after sha256 dedupe. ⟹ a **content-addressed library plus a
per-match manifest of hashes**, not a save state.

## 3. Three lanes. C gates B. A ships regardless.

---

# LANE C — DETERMINISM
**Owner: senior-re-generalist + flycast-internals-expert. Gate held by gsta-verification-harness.**

## C0 — ⭐ THE CROSS-BUILD FP CENSUS. Do this first. Zero new code.
Nobody has ever run the determinism harness across build targets, and there are **three different
floating-point targets** in play:
* Windows MSVC (`build-headless-win`) — `/fp:precise`, no scalar FMA contraction
* Linux GCC (rise3) — **`-ffp-contract=fast` is the GCC C++ default**; `a*b+c` may be fused
* wasm32 clang — WASM MVP has **no scalar FMA**, so contraction is impossible

`grep "fp-contract\|ffast-math\|fp:fast" CMakeLists.txt` → **no explicit FP flags anywhere.** And
SH4's `FIPR` (`core/hw/sh4/interpr/sh4_fpu.cpp:400-418`) is a four-term double accumulation —
precisely the shape a compiler contracts. `FSRRA` (`:357-368`) is `1.f/sqrtf()`; the x64 dynarec does
**not** lower it to a hardware approximation (`grep fsrra core/rec-x64/rec_x64.cpp` → no hits), so
interpreter-vs-dynarec is probably safe. Cross-*host* is not.

**Run:** the same movie under `MAPLECAST_GSHASH_LOG` on Windows-MSVC and on Linux-GCC; `diff`.
**PASS:** byte-identical for ≥5,000 frames.
**FAIL:** names the first divergence frame — **and every cross-host resim result to date is suspect.**
*Needs a rise3 build. Highest value-per-hour item in this document, and it was on nobody's list.*

## C0b — executor equivalence. OFFLINE, NO CODE CHANGES.
`MAPLECAST_USE_INTERPRETER` already exists (`core/emulator.cpp:568`) and already switches the
executor. Every determinism result we have came from the **native x64 dynarec**; a browser would run
the **interpreter**, a third engine nobody has compared. `flycast-wasm/README.md:12-15` — the stable
WASM branches are "Interpreter only."
**Run:** two headless runs, identical but for `MAPLECAST_USE_INTERPRETER=1`, both with
`MAPLECAST_GSHASH_LOG`; `diff`. **PASS:** byte-identical through match end.

## C1 — the last untried lever on the ULP wall. Cheap, low probability.
`RENDER-ACCURACY-PROGRAM.md:435-436` already names it. Set explicit FP flags (`-ffp-contract=off`,
`/fp:strict`), audit `FIPR`'s double accumulation and `FSRRA` against the recompile's arithmetic.
**PASS:** free-run resim bit-exact to the tape's recorded Steam raw state **through the first super**
on a clean (`rollbacks:0`) tape with RNG draw count > 0.
**A pass unblocks framing (B) entirely.** A fail closes the input-side approach for good.

## C2 — DECISION GATE. Tris's call, written and dated.
If C1 fails: ship framing **(A)**, or fund **state injection** — driving the engine with the recorded
per-frame state. ⚠ State injection is **not** speculative and **not** free: it was built and run, and
poking `sprite_id (0x144)` without `anim_pointer (0x168)` / `animation_state (0x1D0)` produced
**100,990 SH4 exceptions**; position-only injection stalls the render after the first inject; and the
one stable injector disables the VRAM memwatch so **it cannot emit a `.zcst`** (`:634-648`). That
tension is unresolved and must be costed before anyone commits to it.

## C3-C5 — the Steam-side chain (ONE live session covers all of it)
"Determinism" is **five independent links**, not one gate, and A needs all five:

| link | claim | status |
| --- | --- | --- |
| **L1** | Steam's trajectory is a pure function of (char-select config, inputs) | **OPEN** — `verify.py rng` returned a correctly self-reported *no-information* result |
| **L2** | the inputs we recorded == the inputs Steam consumed | **OPEN, CONFIRMED BUG** — `tape_to_flycast_movie.py:97` hardcodes `seat0→P1`; the mapping is **per-tape**, keyed on `local_pn` |
| **L3** | flycast (native dynarec) reproduces Steam's trajectory | **INCONCLUSIVE** — the 1-ULP wall at f1224 |
| **L4** | flycast (WASM/interpreter) == flycast (native) | **NEVER TESTED** → C0b |
| **L5** | pvr2's render of that TA == Steam's pixels | **NOT BUILT** → Lane B |

* **C3 — `rrtape4.py play m035949.rr4`** on a cold-booted Steam. ⚠ **`play`, not `ab`.** `ab` compares
  two of *our* runs; `play` compares our run against the tape's own **119 checkpoints from the
  original live game**, including a **CRC32 of the whole 211,736-byte region**.
  ⚠ **The confound:** `feed_tape` polls the frame clock from Python, so a missed poll is
  indistinguishable from a determinism failure. **A FAIL is only a finding if the first-divergence
  frame REPRODUCES across three runs. If the frame MOVES, it is the feeder.**
* **C4 — `rrtape4.py ab`, only AFTER a blocking fix.** ⚠ Today `ab` will print
  **"✅ A == C … the claim we needed, and it holds"** for a churn that sat on the character-select
  screen and never fought. `rrtape4.py:527-547` — `churn()` writes random pad words and returns only
  `fed`; it never checks mode, never checks that hp moved, never checks `ROLLBACKS`. **That is a false
  win with a checkmark on it.** Fix first: report frames with `mode[2]==2`, the hp delta, the rollback
  delta, and refuse to pass without evidence of a fight.
* **C5 — `verify.py rng --exe`** during a super, with `lcg_scan` looped over a small constant table
  (DC, MSVC `rand`, glibc) — a generator-*family* probe for ~3× the cost. ⚠ **Do NOT run `--arena`**:
  256 MB × 38,400 steps on a non-frozen read, for the same zero information a negative always gives.
* **Preconditions in the same session:** `verify.py reg` (the `G+0x48` fork ≥ 3 — ⚠ `rrtape4.py:65`
  defines `G_SEL` and **never reads it**) and `verify.py blk2` (the second registered block at
  `blk+0x33B18` is **NOT rollback-saved** — the textbook "set before, read during" hazard, and there
  is no recorded run of it anywhere).

## Hazards that survive all of §6's items
* **H1 — match options live inside `blk`, and a flycast cold boot has its own.** `FUN_140608690`
  copies difficulty/damage/time into `blk+0x3C40…0x3D07`. Damage level changes gameplay outright.
  Fix is cheap and must be designed in **now**: a per-match option block on the wire, plus a poke.
* **H2 — stage id** (`blk+0x6D3C`, `blk+0x32530`), same shape. ⚠ **UNKNOWN whether the resim even
  lands on the right stage** — no stage path was found in `maplecast_autoselect.cpp`.
* **H3 — ⚠ every checkpointed `.rr4` we own is TRAINING MODE.** Derived from the checkpoint stream,
  not a label: only slot 1 takes damage, hp *regenerates* to 144 repeatedly, `timer` pinned at 99.
  **A training-mode result says nothing about versus**, which adds round transitions, KO/results
  phases, switch-in and snapback — and round transitions re-enter `FUN_140608690`.
* **H4 — point characters are identified by sprite-id match, NOT team-array order.** A wrong point
  character reproduces as an X-position divergence at the first assist — **exactly the signature B2
  attempt 1 reported.**
* **H5 — ⚠ Architecture A has ZERO ERROR TOLERANCE and nobody has priced it.** One dropped input frame
  desyncs the client permanently, undetectably. **Ship a periodic state checksum with the inputs** —
  six char-struct XXH3s every N frames is ~8 B/s, ~5% of the feed. It converts a silent catastrophic
  failure into a detected one, **and turns every match played in production into a live determinism
  datapoint.** Design it into the wire, not after.
* **H6 — anchor privacy:** the 56-bit unlock mask makes a `blk` anchor per-account identifiable.

## The anchor is SOLVED — do not re-litigate it
Cold-boot MENUNAV costs **zero bytes** and is already a complete unattended state machine
(`maplecast_autoselect.cpp:212-231`): it pulses START on both pads until char-select, latches
`g_everCS` so it can never mash through the VS intro, reads the **live** 8×8 grid table at
`0x8C161FEC`, BFS's the cursor to each target, handles colour-select, and hands off the instant
`in_match != 0`. And battle-init calls **`srand(1)`** (`loc_8C11E770`, hard-writing `RngVal` at
`0x8C16BC2C`), so **any anchor at or before battle-init is RNG-equivalent** — an anchor buys nothing
that running the ROM does not already give you. Savestates are 5-9.5 MB, restore-stall, and are
format-coupled to the build. The Steam-`blk` anchor is triple-blocked and retired.

---

# LANE A — MAKE THE PIPELINE THAT WORKS TODAY UNATTENDED
**Owner: flycast-internals-expert. Ships regardless of Lane C.**

The path that works end to end today:
```
tape → tape_to_flycast_movie.py → movie.txt
     → flycast headless (MAPLECAST_AUTOSELECT + MENUNAV + MOVIE_IN + MIRROR_SERVER)
     → capture_mirror_full.mjs → .zcst → play_zcst.html (FrameDecoder → TAParser → PVR2 → WebGPU)
```

* **A1 — one-shot tape→resim driver.** One script reads a tape and emits `MAPLECAST_AUTOSELECT`,
  `MAPLECAST_ASSIST` (per-character in **pick order**, with the per-tape slot remap), the movie, **and
  the measured pace offset**. ⚠ Fixes `tape_to_flycast_movie.py:97` — key the seat on `local_pn`.
  ⚠ `ggpo_sim_tie` is MISLEADING (one tape's real offset was **+1**, not the reported +6) — the
  alignment must be **measured** by correlation, not read.
  *Accept:* on ≥5 tapes with mixed `local_pn`, emitted P1/P2 match the tape's `p1_in`/`p2_in` at
  ≥99.9%, and the resim reaches `in_match` with the correct roster read back from guest RAM.
  **This blocks every other resim result from being trustworthy.**
* **A1b — resolve the HP/HK trigger conflict.** `replay_reader.cpp:414-417` says MvC2's HP/HK live on
  the DC analog triggers; `tape_to_flycast_movie.py:32` maps them digital and puts assists on the
  triggers. **If the comment is right, two of six attack buttons are being dropped on every resim to
  date.** *Route to `mvc2-sh4-re-expert` for a `loc_8c010080` citation.*
* **A2 — stage selection.** *Accept:* guest-RAM read-back equals the tape's `stage_id` on ≥5 tapes.
* **A3 — unattended runner.** *Accept:* one command produces a playable artefact for 10/10 tapes with
  no human input, including one with `rollbacks > 500`.
* **A4 — the product loader. ⚠ `play_zcst.html` is demo-grade and its own hint text is false.**
  `:92-97` loads the **entire** `.zcst` via `arrayBuffer()` — 313-440 MB — then `:111-117` runs a full
  index pass decoding every message before frame 0 renders. `:56` claims "a backward seek re-decodes
  from the last keyframe, ~1s"; `seekTo()` at `:133` re-decodes from **message 0** every time. The
  wire *does* force a keyframe every 60 frames (`maplecast_mirror.cpp:2606`) — the player just never
  indexes them. *Accept:* time-to-first-frame < 3 s, peak memory < 500 MB, backward seek < 1 s.
* **A5 — artefact size.** Enable `MAPLECAST_ZSTREAM` / `MAPLECAST_VCACHE` and measure. If a full match
  cannot get well under 100 MB, **the `.zcst` is not a delivery format** and the product wire must be
  re-scoped. *May force a product decision.*

---

# LANE B — PIXEL TRUTH
**Owner: gsta-verification-harness. Contingent on C2.**

## ⚠ B0 — G-PIXEL CANNOT BE BUILT AS SPECIFIED. A build-config impossibility, recorded nowhere.
`RENDER-ACCURACY-PROGRAM.md:249-252` specs it as `MAPLECAST_GSTA_SHOT_EVERY=1` + `GetLastFrame`. But
`core/hw/pvr/Renderer_if.cpp:489-494` forces `norend` **unconditionally when headless, even on GPU
builds**, and `core/rend/norend/norend.cpp` has no framebuffer and no `GetLastFrame`.
⟹ **the resim rig physically cannot produce a client framebuffer.** G-PIXEL must diff the *browser's*
render against a reference from a **second, non-headless build**. Whoever picks up B3 will otherwise
hit this wall with no warning.

## The measurement, ordered cheapest-first — and geometry before pixels
⚠ **A pixel diff between flycast/pvr2 and Steam/D3D11 is confounded across three layers** — sim
divergence, TA-vs-draw-call translation, and rasteriser differences. A number out of it cannot be
attributed to a layer. **That is this project's signature failure mode in new clothes.**

⭐ **Start with the round-start still.** At round start both sides are at fixed spawn positions, fixed
sprite ids, zero RNG consumed — **identical by construction**. That frame is alignable with certainty
on day one, **with no determinism requirement at all**, and it buys the entire asset-identity,
geometry, palette, blend-class and layer-order comparison before anyone argues about supers.

| # | gate | threshold | proves | does NOT prove |
| --- | --- | --- | --- | --- |
| **M0** | Steam sim-clock delta across the burst | 300/300 steps == +1 | 1 Present = 1 sim frame, no rollback | nothing about flycast |
| **M1** | sidecar-vs-draw phase (384×224, corner-aware) | one phase ∈{−1,0,+1} explains ≥99% of drawn fighters | the sidecar describes the frame we captured | nothing about the resim |
| **M2** | preconditions: 6 char ids, stage, round | **exact, zero tolerance** | the two runs are the same fight | nothing about frames |
| **M3** | state fingerprint, bit-exact, single constant `k` | N/N frames, `k` constant, anchor unique within ±600 | alignment is established | that the render agrees |
| **M4** | drawn-object census | exact, per frame | no missing/extra objects — catches compositing bugs geometry cannot see | nothing about where |
| **M6** | **asset identity**: Steam R8 tiles + palettes vs `MAPLECAST_PARTDUMP` | ≥99% byte-identical | the two builds ship the same art — **the precondition that makes any pixel number interpretable** | nothing about layout |
| **M5** | geometry, per-part rects, **union rule** | ≤1 native px on ≥99.5% | positions/sizes agree | nothing about colour or order |
| **M7** | pixel diff, edge-masked, 640×480 | ≥99.5% within ±1 LSB | our two renderers of the same state agree | **nothing about MvC2** |

**Alignment is exact, not searched.** Three clocks are in play — d3dcap's `g_frame` (Present calls),
the publish `frameNum`, and **the game frame**. flycast already reads and publishes the game clock
(`0x8C3496B0`, `maplecast_rollback.cpp:940`, `maplecast_mirror.cpp:3983`), and Steam's is
`blk+0x3CC8`. Join on a **state fingerprint hash**, assert the anchor is **unique within ±600 frames
on both sides**, derive ONE constant `k`, and **ban per-frame offset search in the code** — a tool
allowed to re-search per frame will always find something and will convert a real divergence into a
plausible match.
⚠ **Do NOT compare memory hashes cross-core**: `gshashLogTick` hashes DC char structs at stride
`0x5A4`; Steam's stride is `0x738`. Field-by-field only.
⚠ **Capture the reference burst in an OFFLINE local-VS match.** `blk+0x3CC8` mirrors GGPO's
`_framecount`, which `Sync::LoadFrame` assigns **backward** on rollback; and a presented frame during
rollback shows a mispredicted state the resim will never produce. Offline removes the whole class.

### Expected differences — do NOT chase these
Steam is 2× DC resolution into a 2048×1024 scene RT then a 9-pass bloom/SMAA chain (**diff the scene
RT, never the backbuffer**); reversed-Z + log depth on our side vs forward-Z on Steam (only an
**order** inversion is a bug); `depth32float` vs `D24_UNORM_S8_UINT` (the **cape** is an exact Z tie
resolved by submission order — flicker under diff is expected); ±1 ULP `mad` fusion; Steam uses only
**seven distinct z values** across all character draws; uninitialised vertex `NORMAL` is NaN by design.

### Would indicate a REAL bug
⭐ **Any per-object BLEND difference.** Steam exposes it at the API — `SRC_ALPHA × INV_SRC_ALPHA` vs
**`SRC_ALPHA × ONE`** — and blend is the one thing reconstruction structurally cannot get (it is a
runtime PVR register, not a part field). **This is the Rosetta stone and it is worth every hour.**
Also: palette content mismatch, missing/extra objects, alpha-test coverage differences.

### The corroboration that makes near-exactness a legitimate expectation
Steam's four pixel shaders are **specialisations of flycast's own DX11 macro matrix**
(`core/rend/dx11/dx11_shaders.cpp:263-340`). The shading semantics are literally the same code
lineage. Model differences as **flycast shader tuples**; anything that cannot be expressed as a tuple
difference is a bug.

---

# 4. What NOT to build

1. **❌ A full maplecast-flycast WASM emulator, as the primary plan.** `grep -i emscripten CMakeLists.txt`
   → **zero hits**; the fork has no WASM target. The only WASM assets on this box are a
   **renderer-only** 851 KB module (`packages/renderer/` — TA parser + PVR2 GLES, zero SH4) and a
   **third-party repo against upstream flycast** whose last committed state is `build-error.log`:
   `rec_wasm.cpp.o Error 1`. Measured interpreter performance: **0.4-5 FPS on a 9800X3D**. A 3-minute
   match = 10,800 frames = **36 minutes of wall clock in a tab.**
2. **❌ Fixing the WASM JIT.** 51 of 70 SHIL ops, foreign repo, build failing.
3. **❌ Re-litigating the anchor.** MENUNAV works, costs zero bytes, and `srand(1)` makes any
   pre-battle anchor RNG-equivalent.
4. **❌ Fixing the savestate restore-stall now.** MENUNAV makes it unnecessary. ⚠ Note the existing fix
   (`rend_resync_after_rollback`) is likely aimed at the wrong thing — it Sets `renderEnd` explicitly,
   yet the single-threaded symptom is "1 frame then idle", which a `renderEnd` deadlock cannot explain.
5. **❌ Streaming the TA mirror as the product wire.** 240-350 MB/match.
6. **❌ Chasing rasteriser differences from the EXPECTED list.**
7. **❌ Hand-expanding the additive gfx1 allowlist.** The Steam capture supplies ground truth instead.
8. **❌ A geometry-only gate as a sign-off.** It cannot see texture, decode, texcache or thread-timing
   bugs. But geometry **first**, as a cheap filter — that is different and it is right.
9. **❌ Letting "0.011-0.018% differing" migrate into a sentence about MvC2.**

# 5. Rules. Each one was paid for.

1. **A pixel diff is a MEASUREMENT, not a mechanism.** `record_attempt(outcome='masks_only')`, never a
   finding. re_kb writes go through `tools/re_kb/kb.py`, never raw SQL.
2. **A runtime pointer is never an identity; a per-frame identity is never a cross-frame one.**
   Four bugs in one session.
3. **A statistic derived from an instrument is never evidence about that instrument's blind spot.**
4. **Report coverage and colour separately.**
5. **Hand-execute on the CPU before blaming the GPU.**
6. **Real assets only.** Never an approximation, never a tuned coordinate.
7. **BYOR.** `.pack`, `.seq`, `.bmp`, `.bin`, replay `*.png` are ROM-derived and gitignored.
8. **Prefer an instrument with no blind spot over one that shares the hypothesis's assumption.**
9. **Reproduce a first-divergence frame three times before calling it falsification.** A frame that
   MOVES is a feeder bug; a frame that STAYS is a finding.
10. **Do not generalise a training-mode result to versus.**
11. **Calibrate a threshold on one set of frames, FREEZE it, then evaluate on held-out frames.** A
    threshold tuned after seeing the result is not a gate.
12. **When two docs disagree, the newer and stricter one governs** — and say so out loud. §0 of this
    file exists because that was not done.

# 6. Live-session batching

| batch | what | serves |
| --- | --- | --- |
| **L1** | ONE solo Steam session: `verify.py reg` + `blk2`, `rrtape4.py play`, then `ab` (after the churn fix), then `rng --exe`. ⚠ NOT `--arena`. | C3, C4, C5 |
| **L2** | an **OFFLINE local-VS** match with d3dcap + sidecar + the agent recording a tape of the same match; bursts at **round start** (~120 frames) AND the super (300 frames) | Lane B, M0-M7 |
| **L3** | a **versus** tape with checkpoints (every `.rr4` we have is training mode) | H3 |
| **L4** | a burst with real camera movement | validates the stage-is-static result, measured on a stationary camera |

Everything in Lane C except C3-C5, and everything in Lane B after capture, is **offline**.

# 7. Open contradictions someone must resolve

* ⚠ **`RENDER-ACCURACY-PROGRAM.md:1441+` records a 2026-08-31 product decision to DROP the flycast
  resim** in favour of a Steam self-replay video, while the 2026-08-30 pivot says build the resim
  render. **This is upstream of this entire workstream.** Resolve it before anyone spends a session.
* The G-COMBAT ledger entry has an internal inconsistency — first hit at f1217 but "diverged at the
  first assist entry (f1199)", i.e. the divergence precedes the hit it says was exact. Reconcile
  before quoting.
* Is DC `0x8C3496B0` the same counter as Steam `blk+0x3CC8`? INFERRED-consistent, not proven; the two
  sit in different segments of the 5-delta piecewise DC↔blk map. **Route to `mvc2-sh4-re-expert`.**
* Asset identity Steam vs DC GDI — UNKNOWN until M6 runs. Everything pixel-level is conditional on it.
