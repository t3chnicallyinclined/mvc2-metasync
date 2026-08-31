# RENDER ACCURACY PROGRAM — "Ship A + Prove B"

> **Single source of truth for the tape/replay render-accuracy job.** Long-running, multi-agent.
> Read this file first, at the start of every session and every agent task. Update the LEDGER and
> DECISION LOG in place — never fork a second plan doc.
>
> Owner lane: `mvc-live-skins-quarters` (this worktree) + `RetroReceipts-agent`. The engine/oracle
> lives in `maplecast-flycast` (the RE panel's repo). BYOR — ship no ROM/game data.
>
> Status: **ACTIVE** · Strategy chosen by Tris 2026-08-30: **Ship A (reconstruction) + Prove B (resim)**.

---

## 0. NORTH STAR

Render a captured MvC2 match on a canvas as a pixel-accurate replay of the fight (characters,
effects, stage, HUD), driven frame-by-frame from a tape.

**The definitional finding (3-expert accuracy pass, 2026-08-30 — CONFIRMED against source):**

| Path | What it is | maplecast render ledger rank | Accuracy |
|---|---|---|---|
| **TA mirror** | the engine's real TA display list → pvr2 | **rank 4 — "byte-perfect deterministic wire, THE ground truth for every gate"** (`RENDER-STATE.md:38`) | pixel-exact BY CONSTRUCTION |
| **Emitter / state reconstruction** | our current `web/tapecanvas` — rebuild bodies from state columns | **"approximation BY DESIGN"** (`RENDER-STATE.md:39-40`) | bounded; 3 known residuals |

Feeding the engine's real TA to pvr2 is **strictly more accurate than reconstructing from state — not
a judgment call, the definitional relationship in the ledger.** We are currently on the approximation
path. The higher path (regenerate the real TA by re-running the ROM headless) is reachable: the engine,
the input-carrying tapes, and the converter all already exist. **What is missing is a determinism PROOF,
not machinery.**

**The two tracks (run in parallel):**
- **TRACK A — reconstruction. SHIPS TODAY.** Keep polishing the browser renderer. Honest ceiling at
  `OWNED-RENDER-BUILD-SPEC.md:279-286`: it "structurally cannot be bit/pixel exact." It is the
  no-determinism-needed fallback and the thing users see now.
- **TRACK B — resim → real-TA → pvr2. PROVE, DON'T PIVOT YET.** Definitionally the 100% renderer.
  Blocked ONLY by an unproven cross-core determinism gate. Run ONE clean experiment to settle it. Do
  **not** reorganize around B until the gate passes.

---

## 1. WORK RULES — STRICT. EVERY AGENT ON THIS JOB OBEYS THESE.

Paste this section (or link it) into every task prompt. Violating any of these invalidates the result.

1. **NO GUESSING.** Every factual claim needs a `file:line` citation from a repo in this projects
   folder, a `loc_8c…` PC, an Oracle capture, a kb entry, or a doc §. If you cannot cite it, write
   **UNKNOWN** and stop — do not fill the gap with a plausible value. *(feedback-never-guess-use-repo-context)*
2. **TAG EVERY CLAIM `CONFIRMED` or `INFERRED`.** CONFIRMED = you verified it against raw evidence
   this session. INFERRED = derived/reasoned, not directly observed. Never present INFERRED as fact.
3. **VERIFY AGAINST RAW EVIDENCE BEFORE RECORDING OR ACTING. Suspect your own inspection path first.**
   A tool that has only ever reported success is unverified. Concrete traps that have burned us:
   `cmd | filter; echo $?` reports the FILTER's exit code — use `${PIPESTATUS[0]}`; `cargo check` ≠
   `cargo test`; a Windows compile builds no linux-cfg code; cp1252 stdin (`PYTHONIOENCODING=utf-8`);
   CRLF breaks multi-line anchors. *(feedback-verify-before-recording)*
4. **DERIVE BEFORE YOU CAPTURE.** Default to deriving/inferring from the disassembly, the kb, the docs,
   and data already captured. A request to live-probe, add a reader field, or do new RE is a RED FLAG
   that you skipped the derive step. Capture/live-probe is the LAST resort. *(feedback-derive-before-capture)*
5. **ASK THE RE PANEL — NEVER GUESS — for ANY rom/ram/flycast/sh4/disasm/pointer/memory/offset
   question.** The 5 experts are listed in §2. This is not optional. *(feedback-consult-mvc2-re-panel)*
6. **RENDER ONLY THE GAME'S REAL ASSETS, PIXEL-PERFECT.** Never draw custom, approximated, monogram,
   flat-color, or hand-tuned-coordinate graphics. Only the game's actual extracted textures + geometry
   + colors. *(feedback-render-only-game-assets)*
7. **PORT PROVEN CODE VERBATIM.** When porting validated RE/logic, copy it as-is. Never add untested
   filters, guards, or "cleanups" on top of proven code. *(feedback-port-proven-code-asis)*
8. **DETERMINISTIC GATES ONLY. NEVER "looks better".** Sign-off = a number: per-pixel / SSIM / region
   diff, or a byte-identical hash. **Offline geometry is NOT a live-pixel proof** — a geometry gate
   (e.g. "36/36 vs H+0x124 coords") cannot stand in for a live-pixel diff. *(gsta-verification-harness)*
9. **LIVE TESTS: give Tris the FULL absolute copy-pasteable command, then `▶ READY, do X then tell
   me`.** A flat reading usually means no input arrived, not a bug. Coordinate; never assume the result.
   *(user-coordination-live-testing)*
10. **NO TIME ESTIMATES / ETAs.** Report scope + the next concrete step only. *(feedback-no-time-estimates)*
11. **BYOR.** Never commit ROM, GDI, atlas, savestate, or any game-derived binary. Vendored assets stay
    gitignored.
12. **REUSE, DON'T REINVENT — we have all the answers already.** We built working renderers, tools, and a
    kb from scratch. Never write a new renderer or re-derive a fact the kb / experts / disasm already hold.
    See §2H for the inventory. If you think you need something new, first PROVE the existing asset can't do
    it (cite why) — then ask the panel before building.

---

## 2. WHERE KNOWLEDGE LIVES (the map — consult in this order)

**Derive from these before any capture (rule 4).**

### A. The RE panel (ask, don't guess — rule 5) — `C:\Users\trist\projects\maplecast-flycast\.claude\agents\`
- **mvc2-sh4-re-expert** — MvC2 memory layout, `marvelous2` SH4 disasm (`loc_8c…` == PC), struct
  offsets, GSTA/OBJS wire, the `re_kb`. → char/RAM offsets, DC-vs-NAOMI, anchor location.
- **mvc2-sprite-render-expert** — sprite/atlas/bake/sprite-client pipeline (state → drawn pixels,
  SH4 OFF). → the emitter path, palette LUTs, effect/hit-flash routing, rip→bake→deploy.
- **flycast-internals-expert** — flycast's own render pipeline inside the GSTA client (TA parser,
  pvr2 software renderer, TexCache, VRAM, palette RAM, WS→render thread handoff). → live-only symptoms
  (garble/flicker/blend/stale sprites), the real-TA emit + resim render path.
- **gsta-verification-harness** — the anti-false-win gate. Owns the savestate-freeze A/B rig, live
  framebuffer capture (`MAPLECAST_GSTA_SHOT`), the differs. → runs every determinism + live-pixel gate.
- **senior-re-generalist** — outside view / methodology owner. "How would we DISPROVE this?" Ghidra on
  the binaries. → keeps the panel honest, cross-checks, refuses false wins.

### B. The Oracle (the live engine = ground truth; derive from it, don't re-RE)
- Headless: `maplecast-flycast/build-headless-win/flycast.exe` on `C:\roms\roms\mvc2.gdi`; autoloads
  slot 0; live replica `ws://127.0.0.1:7212`. *(mem: mvc-hud-list0b-live-re)*
- Remote oracle box **`149.28.44.118`** — `flycast-36g-traced` + `maplecast-headless.service`
  (LIVE-but-idle, separate instance only — ⚠ NEVER disturb the live service or wager/tape data).
- Build box: OVH Rise **`ubuntu@15.204.141.58`** key `~/.ssh/ovh_maplecast`, 24 cores.
  *(mem: rr-flycast-resim-confirmed-tape)*

### C. The KB — `re_kb` (SurrealDB) on `149.28.44.118`. RE knowledge graph; query, don't re-derive.

### D. The disassembly — `marvelous2` / `maplecast-flycast/_marv_re/build/*.asm`
   (`loc_8c…` label address == PC). e.g. camera in `bank03.asm:1281,1495-1516`, `bank12.asm:5271`.

### E. The docs (this worktree `mvc-live-skins-quarters/docs/`)
- `STEAM-GGPO-DETERMINISM.md` — blk registration, RNG open question, self-verified caveats.
- `CONFIRMED-TAPE-AND-FLYR-REPLAY.md` — §3 flycast anchor, §6 the through-combat gate.
- `REPLAY-ENGINE-DESIGN.md` — Path A design; §2c draw-list; §2d blend UNLOCATED; §2e Steam-can't-hook.
- `OWNED-RENDER-BUILD-SPEC.md` — the emitter path; §5 blend; §6 live-pixel gate; ceiling @279-286.
- `STEAM-TAPE-RENDER-HANDOFF.md` — the 2026-08-27 decision; the DC-not-NAOMI retraction (commit 24a084b).
- (also `RetroReceipts-agent/docs/`: STEAM-CODE-MAP, STEAM-RE-NOTES, STEAM-REPLAY-*.)

### F. Agent memory — `C:\Users\trist\.claude\projects\c--Users-trist-projects\memory\MEMORY.md`
   (index) + linked files. Point-in-time; verify file:line before asserting as fact.

### G. Tapes — `replay-kit/tapes-kept/*.json.gz` (full agent tapes, carry `confirmed_in`).
   Tools: `tape_to_flycast_movie.py` (→ movie), `rrtape4.py`/`AB.cmd`/`verify.py` (Steam-side rig),
   `tape_to_gpujson.py` (strips to render-only STATE — the current renderer's input).

### H. Existing working assets — REUSE these (do NOT rebuild; rule 12)
- **Real-TA → pixels (GROUND TRUTH, the "99% full TA stream" render):** the engine's own render
  (`maplecast-flycast/core/ui/mainui.cpp` Render/Present) + the GSTA client path (`maplecast_mirror.cpp`
  clientReceiveGsta / gstaApplyFrame / Process(fr.ta)). **The resim render uses THIS — no new renderer.**
- **Vendored pvr2 (browser):** `web/tapecanvas/renderer/pvr2-renderer.mjs` (+ `ta-parser.mjs`,
  `shaders.mjs`, `texture-manager.mjs`) — byte-identical to maplecast's; already renders HUD + stage TA.
- **Emitter/body render (Track A):** `web/tapecanvas/renderer/sprite-gpu.mjs` + `sprite-client.mjs`
  (WebGPU owned tape render — bodies + HUD + layering).
- **Resim harness (reuse, don't rewrite):** `maplecast_autoselect.cpp` (cold-boot MENUNAV),
  `MAPLECAST_MOVIE_IN` input replay (`emulator.cpp`), capture (`MAPLECAST_GSTA_SHOT`/`GetLastFrame`).
- **Tape/atlas tooling:** `tape_to_flycast_movie.py`, `tape_to_gpujson.py`, `rrtape4.py`, `verify.py`,
  `AB.cmd`, `rip_gfx2_assembly.py`, `extract_gfx1_atlas.py`.
- **Knowledge:** `re_kb` (SurrealDB), `marvelous2`/`_marv_re` disasm, the 5-expert panel, the docs (§2E).

---

## 3. THE LEDGER — proven vs open (update in place)

### CONFIRMED
- **Weak determinism**: everything that *changes* mid-match lives in `blk[0..0x33B18)` (211,736 B). GGPO
  guarantees it (else online desyncs). *(STEAM-GGPO-DETERMINISM)*
- **Resim machinery exists**: headless maplecast-flycast re-runs the ROM and emits the real TA at
  `serverPublish` (`maplecast_mirror.cpp:2840`, hook `0x8C03093C`/`0x8C033E90` @2942-2944); input feed
  `MAPLECAST_MOVIE_IN` (`emulator.cpp:852-866`); converter `tape_to_flycast_movie.py` reads `confirmed_in`
  (VERIFIED on disk 2026-08-30). Determinism harness `MAPLECAST_GSHASH_LOG` (`emulator.cpp:856-859`).
- **The right resim input = the FULL agent tape's `confirmed_in`** (`tapes-kept/*.json.gz`). NOT the
  render-only `tape.json` (no inputs, `tape_to_gpujson.py:57-70`), NOT `.rrtape` (Steam `blk`, un-loadable
  cross-core).
- **The full agent tape (ver 0.3.31) carries the ground truth for B2 OFFLINE** (VERIFIED 2026-08-30):
  `frames` = per-frame Steam raw state, schema `[frame,p1_in,p2_in,kcode,hp[6],px[6],py[6],meter…,vx[6],
  vy[6],red_hp[6],facing[6],hitstun[6],…,sid[6],…]` (9904 fr) — **every B2 gate field (px/py/vx/vy/hp/
  facing ×6) is present.** Plus `confirmed_in` (10027 fr), a full Steam `blk` snapshot (`anchor`, 211736 B
  = 0x33B18, @frame 3), `fighter_bases[6]`, and the realignment `ggpo_sim_tie {ggpo_frame:870,
  sim_frame:876}` (the +6 sim↔ggpo offset — the old "−6 skew", now a captured constant). ⟹ **B2 needs NO
  live Steam.**
- **B2 (2026-08-30) — resim determinism looks STRONG (not yet certified):** (a) resim is **self-deterministic**
  — two identical runs byte-identical across 2809 in-match frames; (b) **cross-core BIT-EXACT** to the
  recorded Steam raw state through round intro + neutral + the **first combat hit (f1217: hp 144→134,
  hitstun 255, full knockback)**, on a clean tape with correct point recon; (c) **NO cross-core RNG/float
  divergence signature** — first divergence is X-position-ONLY at assist/dash events = harness recon, not
  engine.
- **⚠ METHODOLOGY (B2, CONFIRMED):** the **B2 determinism GROUND-TRUTH comparison** MUST use a
  **rollback-free tape** (`rollbacks:0`) — rollback-heavy tapes store PREDICTED sim state with catch-up
  discontinuities (px +8.75 in one frame while vx=2.917), unusable as the state reference. Clean tapes:
  `…59598769…`, `…59601369…`.
  **⚠ SCOPE CORRECTION (Tris, 2026-08-30): this applies ONLY to the determinism comparison — NOT to
  RENDERING.** For rendering, the resim is driven from `confirmed_in` (the GGPO/blk-RE'd post-rollback
  stream, keyed to the confirmed frame) and replays the rollbacks forward BY DESIGN, so **rollback-heavy
  real-match tapes render fine** — the predicted `frames` are never used for the render. Rollback-heaviness
  is the normal case and is exactly what the confirmed-input RE handles.
- **⚠ BUG (B2, CONFIRMED) — `tape_to_flycast_movie.py`:** for these tapes the `confirmed_in` triple is
  `(frame, s0=seat1/P2, s1=seat0/P1)` — **seat-swapped** vs the converter's `s0→P1` (line 97); it also
  feeds char-select-era frames (no `in_match` skip). P1(local) correlates to `conf[f-1].s1` at 99.56% (+2f
  apply-delay). Fix (or use `p1_in`/`p2_in` for clean tapes) before the next B2 run.
- **DC fighter-struct field offsets** (`pl_mem.asm`, base `0x8C268340 + slot*0x5A4`): x_pos `+0x34`,
  y_pos `+0x38`, x_vel `+0x5c`, y_vel `+0x60`, xflip `+0x1d2`, health `+0x420`.
- **Assist type — RESOLVED (read + poke, 2026-08-30).** Steam READ offset **`+0x4e9`** (agent `sync.rs:55`,
  `STEAM-RE-NOTES:67`, live); DC POKE offset **`+0x4C9`** (sh4-re, DIRECT from the DC disasm: `pl_mem.asm:289`
  `assist_type 0x04c9`; char-select SET-site `bank03.asm:27540` (mod-3 → 0/1/2); in-match READ-sites
  bank08/bank0f — every `0x4C9` access accounted for). ⚠ DC `+0x4C9` ≠ Steam `+0x4e9`; they do NOT map via
  the block-map — both correct for their build. u8, α/β/γ=0/1/2, fixed at char-select; sticks (char-select
  writes in place, no battle-init memcpy, match only READS). **POKE recipe** (DC base `0x8C268340`, stride
  `0x5A4`, `+0x4C9`; masked `mem_b[addr & 0x1FFFFFF]`): re-assert the 6 slot bytes every in-match frame
  (idempotent, read-only match constant — zero desync) from the char-select→match handoff
  (`in_match 0x8C289624 != 0`, `maplecast_autoselect.cpp:173/257`) until the first assist call. Impl = sibling
  env `MAPLECAST_ASSIST="p1a,p1b,p1c;p2a,p2b,p2c"` parsed like `MAPLECAST_AUTOSELECT`, applied via a `wr8`
  mirror of `rd8`. Slots P1=0/2/4, P2=1/3/5. ⚠ Verify tape `assist[i]`↔`char[i]` is in PICK order (same
  order concern as B2a).
- **Steam cannot capture its own TA without a per-client PVR-submit hook** (`REPLAY-ENGINE-DESIGN.md:105-112`
  §2e) ⟹ resim is the mechanism to obtain the real TA from a tape.
- **Reconstruction's 3 residuals** (why it can't be exact): (1) per-parcel **blend** UNLOCATED as a struct
  field, shipped as a heuristic (`REPLAY-ENGINE-DESIGN.md:82-89` §2d) — *this is why Cable's beam is
  purple*; (2) **palette** — bodies at baked default (`OWNED-RENDER-BUILD-SPEC.md:220-221`); (3) **effects**
  — 0/23742 objs resolved (`:206`), 3D-machine hitsparks/shadows omitted (`:275-277`).
- **DC LCG `0x41C64E6D`/`0x3039` is absent from blk, exe, AND arena** (`verify.py rng`) — the recompile
  did not keep DC's verbatim generator. *(STEAM-GGPO-DETERMINISM:49-56)*
- **RESOLVED G-DCNAOMI → DC GDI** (sh4-re B0, 4 axes, cited): Steam FC is a native x86-64 recompile of
  the **DC** lineage (build banner `__DEV_TYPE_DC__`; 0.000% SH4 opcodes across 2 GB live; Steam `blk`
  maps to **DC** bases `0x8C264588…`, not NAOMI+0x6C068). DC work-RAM ↔ Steam `blk` is a **field-exact
  piecewise map** (5 deltas, 12 anchor pairs, fighter struct grows 0x5A4→0x738 in 5 steps; growth ladder
  closes `0xD480=0x978+0xB310+0x1800+0x8`) — sufficient for a field-for-field determinism comparison. No
  NAOMI↔blk map exists (net-new RE). DC core already on box (`C:/roms/roms/mvc2.gdi`).
- **srand(1) confirmed in the DC ROM, OFFLINE** (sh4-re B0): RNG LCG `bank16.loc_8c16BC2C`
  (`RngVal*0x41C64E6D+0x3039`), seeder `loc_8C11E770`, caller `bank03:33181-33183` does `srand(1)` gated
  on battle-init state==5. ⟹ the sim RNG reseeds to the constant **1** by running the ROM through battle
  init; **a DC resim from a char-select anchor is RNG-deterministic BY CONSTRUCTION** — nothing about RNG
  needs "carrying." DC and NAOMI share the same SH4 game code, so this is a RAM-map/anchor question only.

- **⚠ RESTORE-STALL (B0b, CONFIRMED):** restoring a savestate stalls the threaded headless render loop —
  the first post-restore frame never renders (`renderEnd.Wait()`-forever, `emulator.cpp:1753-1760`;
  `rend_resync_after_rollback()` doesn't clear it). NOT anchor-specific (mid-match states stall too; only
  the 3 native-rig states render). ⟹ **B2 must reach char-select by COLD-BOOT MENUNAV (proven), not by
  restoring `mvc2_50.state`** — the .state is a reference/verification artifact. (Restore-sync fix = a
  flycast-internals task only if ever needed.)

### OPEN (each blocks Track B; each needs a falsifiable gate)
- **G-RNG** — does the STEAM recompile's RNG produce the same sequence as DC's? The A/C-keyed scan is
  BLIND to a swapped generator, so this can't be settled analytically. **KEY INSIGHT (sh4-re B0): we
  don't need to LOCATE Steam's RNG — B2 MEASURES it.** If the DC resim matches Steam `blk` through the
  first super's RNG draw, Steam's RNG ≡ DC's behaviorally and resim works; if it diverges, Steam swapped
  it and resim is dead. **B2 settles G-RNG and G-COMBAT together.** **B2 attempt 1: no swapped-generator
  signature** — the first hit (RNG-adjacent) reproduced bit-exact — but `RngVal (0x8C16BC2C)` was not
  directly counted (TELE_OUT lacks it); B2b adds it to certify the draw count.
- **G-AB** — the generator-agnostic in-process test (`AB.cmd` / `rrtape4.py ab`: restore→churn 900→
  restore→replay→compare). Settles whether ANYTHING outside blk matters. **NOT YET RUN on a full match.**
- **G-COMBAT** — cross-core through-combat determinism. **B2 attempt 1 (2026-08-30): NOT PASSED, NOT
  KILLED.** On a CLEAN tape with correct point recon, the DC resim was BIT-EXACT to Steam raw state through
  intro + neutral + the **first combat hit (f1217, knockback incl.)**, then diverged **X-position-ONLY** at
  the first assist entry (f1199), ~1160 fr before the first super (f2359). Signature (X-only at assist/dash;
  py/sid/hp/hitstun/knockback exact) = **harness reconstruction, NOT engine.** Close via B2a+B2b+B2c. Do
  NOT advance to B3 until a clean through-super comparison passes.
- **G-PIXEL** — the live-pixel acceptance gate (`MAPLECAST_GSTA_SHOT_EVERY=1`, `GetLastFrame`, diff
  consecutive vs engine mirror, `OWNED-RENDER-BUILD-SPEC.md:174-178` §6). ⚠ default SHOT_EVERY=30 masks
  flicker; ⚠ preserve the WS→render tile/TA pairing (`maplecast_mirror.cpp:7267-7277`). **Not built for
  either path.** Until it exists, NO path may claim "pixel-perfect" — the current "99%" is an eyeballed/
  geometry estimate, NOT a measured number.

---

> **⚡ STRATEGY PIVOT 2026-08-30 (Tris): "just build it, tweak after."** B2 attempt 1 showed the resim
> reproduces Steam raw state bit-exact through real combat (first hit + knockback), no cross-core signature
> — low enough risk to BUILD on. So we now prioritize **building the resim → real-TA → pvr2 render
> end-to-end (B4) and looking at it**, over certifying determinism first. The strict through-super gate
> (B2c) is **demoted to a post-build diagnostic** — we render, watch where it visibly drifts, and tweak
> (assist recon, converter, etc.) against what we actually see. B2b (faithful char-select recon) is the
> enabler for the build, so it stays on the critical path.

## 4. TRACK A — RECONSTRUCTION (ships today)

| ID | Step | Gate | Owner | State |
|---|---|---|---|---|
| A1 | Effect palette bake + effect layer order | render proof + true-color beam | mvc2-sprite-render | ✅ 2026-08-30 — palette model resolved (`bank = charBaseRow + flags_row`); beam CONFIRMED blue/white/yellow (not purple — coordinator-verified f6392); Iceman re-baked `--bank 1` (green→blue). ⚠ residual: banded beam-TRAIL art (real fix = re-rip PL17 w/ live PARTDUMP), scattered particles at super-freeze (uncertain). `?v=sharp2`. |
| A1b | Re-rip PL17 beam parts with live PARTDUMP (kills the banded trail) | clean (non-striped) beam trail | mvc2-sprite-render + capture | backlog (live) |
| A2 | Systemic character body-bank calibration (all 56) | no green-blob / dark parts | mvc2-sprite-render | ✅ UNBLOCKED 2026-08-30 (sh4-re B0): the "charBaseRow/node+0x172" premise was WRONG — +0x172 (=DC +0x12e) is the runtime hit-flash overlay word, NOT a load-time table. Full 56-char body palette IS offline-derivable: `Dat_Pal(node+0x164) + pl_palid_match(node+0x25)*0x100` + 4 special char-ids (Zangief 0x01→+0x08, Sakura 0x22→+0x14, Jin 0x37, SonSon 0x14). ⚠ stride `*0x100` (8 banks/costume), NOT `*0x80`. → bake per recipe (`loc_8c035000`) |
| A3 | Build **G-PIXEL** live-pixel gate for the browser path | differ vs engine mirror on a frozen frame, region-masked | gsta-verification-harness | not started |
| A4 | Measure the honest reconstruction % with A3 (retire the eyeballed "99%") | a real region-diff number | gsta-verification-harness | blocked on A3 |
| A5 | Hit-flash → hurt-palette bank | flash frames render correct tint | mvc2-sprite-render | backlog |
| A6 | HUD back as a TRANSPARENT overlay (was opaque = the "no characters" bug) | bodies visible + HUD composited | mvc2-sprite-render | backlog |
| A7 | Stage Option A (byte-exact cam `M1@0x8C2D6B18·M2@0x8C2D6AD8`) + props + zoom | deck-pin + prop presence vs mirror | flycast-internals | backlog |

Track-A note: blend mode is a **definitional ceiling** of this path (G-blend UNLOCATED). A1/A2 improve
color; exact additive-vs-alpha is what only Track B fixes for free.

---

## 5. TRACK B — PROVE RESIM (the 100% path). Gated, in order. Do not skip a gate.

| ID | Step | Passing gate | Owner | State |
|---|---|---|---|---|
| B0 | Decide DC-vs-NAOMI resim core (resolve G-DCNAOMI) | one cited decision | mvc2-sh4-re | ✅ 2026-08-30 → **DC GDI** (4 axes, see ledger); srand(1) confirmed ⟹ resim RNG-deterministic by construction |
| B0b | Verify/produce the char-select **DC anchor** | a headless state CONFIRMED at char-select | gsta-verification-harness | ✅ 2026-08-30 — PRODUCED `build-headless-win/data/mvc2_50.state` (slot 50), clean char-select grid, CONFIRMED via engine `atCharSelect()` read-back (in_match=0, charsel-state=1, locks 0x00). Recipe: cold-boot MENUNAV autoselect. Existing states all mid-match (read-back, not names). ⚠⚠ RESTORE-STALL — see ledger |
| B1 | (cheapest disprove) Run **G-AB** on a full-match `.rr4` — restore→churn 900→restore→replay→compare digests | A==C ⟹ nothing outside blk matters; A≠C ⟹ resim premise dead | gsta-verification-harness + Tris (LIVE, Steam) | blocked on a full-match .rr4 |
| B2 | Prove **cross-core determinism** — DC resim vs tape's recorded Steam raw state (cold-boot MENUNAV, no restore) | first-divergence ≥ first super, RNG drawn | gsta-verification-harness | ⚠ 2026-08-30 **INCONCLUSIVE (not KILL)** — bit-exact through the **first hit** (incl. knockback); self-deterministic; NO cross-core signature. Diverged X-ONLY at first assist (f1199) < super (f2359) = harness recon gaps, not engine. Strict gate unmet. |
| B2a | Fix `tape_to_flycast_movie.py` (seat-swap s0↔s1, char-select skip) — verify on both clean tapes | movie P1/P2 = tape p1_in/p2_in ≥99.9% | (our lane) | not started |
| B2b | **Assist poke** — set DC `assist_type` (`+0x4C9`) per slot via `MAPLECAST_ASSIST` env | first assist reproduces the tape's variant | flycast-internals | ✅ recipe + PATCH STAGED (`tools/render-replica-poc/assist_poke.patch`; hook-corrected — a per-vblank `applyAssist()` OUTSIDE the movie-pace `active()` gate, self-gated on `in_match`+600fr). ⚠ **BUILD BLOCKED from this worktree-isolated session** (git apply + Write/Edit both refuse the `maplecast-flycast` checkout) → needs a NON-isolated maplecast session: `git apply` → `ninja flycast.exe` (stop local oracle PIDs first) → run w/ `MAPLECAST_ASSIST` → capture. Runbook: `tools/render-replica-poc/assist_build_run.txt`. |
| B2c | Re-run B2 through a super on a clean tape w/ the assist-faithful harness + RngVal count | first-divergence ≥ first super, RNG drawn >0 | gsta-verification-harness | blocked on B2a+B2b |
| B3 | Gate the RESIM RENDER with **G-PIXEL** (live consecutive-frame diff of resim real-TA pvr2 vs engine mirror) | region diff within tolerance on frozen frames | gsta-verification-harness | blocked on B2 |
| B4 | Only if B1–B3 all pass: wire resim → real-TA → pvr2 as the primary tape renderer | — | flycast-internals + sprite-render | blocked |

**Test selection for B2:** an RNG-EXERCISING match — a landed super with hitsparks (Storm/Sentinel/
Blackheart per the effect-bank call sites), NOT an idle/damage-only clip. **Log the RNG-draw count in the
window** to prove the run wasn't a neutral re-run. KILL = any divergence at/after the first hitspark.

**Rig reality:** the wired input path is **maplecast-flycast + `MAPLECAST_MOVIE_IN`**, NOT dojo `.flyr`
(that lives only in the separate `flycast-dojo-ref` repo). The `.flyr` doc is the proof spec, not our tooling.

---

## 6. DECISION LOG
- **2026-08-30** — 3-expert accuracy pass (sh4-re, flycast-internals, senior-generalist) → TA=ground
  truth, emitter=approximation (definitional). Strategy: **Ship A + Prove B**. Chosen by Tris.
- **2026-08-30** — B0b: char-select DC anchor PRODUCED + CONFIRMED (`mvc2_50.state`, engine
  `atCharSelect()` read-back). ⚠ savestate-RESTORE stalls the headless render loop ⟹ B2 uses cold-boot
  MENUNAV (proven), not restore. B2 (decisive offline determinism test) kicked off.
- **2026-08-30** — Assist poke BUILT + LIVE (maplecast session; patch had bad `@@` counts + literal-`\n`
  escapes → applied by hand + fixed; read-back CONFIRMED `slots0/2/4=0/2/2 1/3/5=1/0/2`). Assists changed
  the sim (clocks differ from the drifted run). ⚠ BUT spot-checks (f6000 TIME54, f8496 TIME29) show
  **P1-favorable** (P1 all 3 alive, P2 down to Spiral/Sentinel) — the OPPOSITE of the real **P2-wins-0-2**
  → resim LIKELY STILL DIVERGES; **assists necessary but not sufficient** → points to the deeper cross-core
  RNG/determinism gate (B2 G-COMBAT, still unproven). Bigger-budget re-run (`--max-frames 20000`) to a clean
  `match_end` needed to CONFIRM the actual outcome — handed to the native maplecast session (my from-here
  launch failed on git-bash `/c`→path MSYS mangling; the resim never ran). If it diverges: localize via a
  frame-exact B2 comparison (with assists) on a **rollback-free** tape → is the new first-divergence the
  first super/RNG?
- **2026-08-30** — Full-match CAPTURE window **FIXED** (root cause = a client-side `setTimeout(15000)` in
  `capture_mirror.mjs:62`, NOT a server drop; also dropped 4/5 redundant side-channels → 1 msg = 1 frame,
  ~5× smaller). New `tools/render-replica-poc/capture_mirror_full.mjs` → `render_ta_wire_full.zcst` = **8497
  frames**, full match end-to-end (verified: T.Bonne vs Spiral, Cable KO'd by f6000, TIME 09 at end). ⚠
  assist-DRIFTED (doesn't reach the real KO — P1 survives to time-over vs losing 0-2 in reality). Assist
  patch STAGED but ⚠ **BUILD BLOCKED by this session's worktree isolation** (can't git-apply/rebuild
  `maplecast-flycast`) → handed to Tris to run `assist_build_run.txt` in a non-isolated session.
- **2026-08-30** — Tris chose **FIX ASSISTS → true full match**. Plan: (1) assist-type recon — sh4-re finds
  the DC location to set `assist_type` — **RESOLVED: DC `+0x4C9`** (direct from the DC disasm; ≠ Steam `+0x4e9`,
  don't map — both correct) with a full battle-init POKE recipe (see ledger) → flycast pokes it via a new
  `MAPLECAST_ASSIST` env so the resim sets the tape's assist types; (2) full-match CAPTURE — flycast fixes the
  ~15s mirror WS drop (`maplecast_mirror.cpp:1899`; keepalive / server cap / segment-stitch); (3) render the
  FULL match → must play out to the KNOWN outcome of **59603897: P2 (Cable/Spiral/Sentinel) wins, set 0-2**
  over P1 (Magneto/Storm/T.Bonne). Fresh-tape dense-combo blocky bodies RESOLVED = a POC-renderer limitation;
  the tapecanvas full-VRAM renderer (`render_ta_wire.mjs` / `play_zcst.html`) renders them CLEAN, no fix needed.
- **2026-08-30** — Baseline PUSHED (`origin/quarters-tigerbeetle`, `e9a4066`). Fresh-tape validation **DONE**:
  pulled a real server tape (match **59603897**, 19:08, **800 rollbacks**, confirmed_in 6394 fr) from
  `149.28.44.118:/opt/rr-server/gamestates/` → the confirmed-input replay HANDLED it: roster exact, coherent
  combat, **clean Magneto super** (`build-headless-win/render_ta_wire_fresh.zcst`, 894 fr). Rollbacks are
  irrelevant to the resim BY DESIGN (confirmed_in = linear forward stream → forward-only, no desync).
  ⚠ **Seat mapping is PER-TAPE** (keyed on `local_pn`): this tape P1=seat0/P2=seat1 (local_pn=1), OPPOSITE
  the Aug-28 clean tape (P1=seat1) — the converter must key on `local_pn`, not hardcode. OPEN: dense
  multi-overlapping-body combo frames render blocky in the POC (bodytex VRAM churn); sprite-render
  confirming POC-limitation vs genuine capture-gap on the tapecanvas full-VRAM renderer.
- **2026-08-30** — Interactive WebGPU player SHIPPED: `web/tapecanvas/play_zcst.html` — fetches
  `render_ta_wire.zcst` and plays/scrubs the resim match in-browser on WebGPU (reuses the `render_ta_wire.mjs`
  decode path + `webgpu-test.html` init; len=0-robust; `?src=` overridable). Run: serve projects root
  (`python -m http.server 8011 --directory C:/Users/trist/projects`) → open
  `http://127.0.0.1:8011/mvc-live-skins-quarters/web/tapecanvas/play_zcst.html` in Chrome/Edge.
- **2026-08-30** — 🎯 **RENDER SIDE DONE**: OUR resim's real TA renders **CLEAN on the tapecanvas WebGPU**
  (no flycast mirror). Coordinator-verified frames: **Cable's Hyper Viper Beam** (bright-blue ADDITIVE beam,
  NOT the purple Track-A residual — because it's real TA), multi-char combat + "ASSIST OK!", 3D ice stage +
  full HUD, **all bodies clean**. The blocky bodies were a **POC-renderer artifact** (`render_ta.mjs` uses
  the dirty-page list; our `FrameDecoder` accumulates ALL VRAM dirty pages incl. the bodytex band) — NOT a
  wire/capture bug, NOT our renderer. `.mcrr`=rank-3 (taSize=0, transpiled reconstruction), `render_ta_wire.zcst`=
  rank-4 real TA (taSize>0) — CONFIRMED by direct parse. Pipeline: resim `MAPLECAST_MIRROR_SERVER` → `.zcst`
  → `web/tapecanvas/render_ta_wire.mjs` (len=0-robust). **Remaining tweaks:** assist-type recon (sh4-re),
  full-match capture (mirror WS ~15s keepalive), B2c determinism cert (deferred).
- **2026-08-30** — END-TO-END from the REAL TA proven: flycast delivered `build-headless-win/render_ta_wire.zcst`
  (47MB, 892 TA frames, spans the Storm super ~1439) = the **serverPublish TA-mirror wire from the CORRECT
  resim**; the POC renderer decoded it → a real MvC2 frame (**3D ICE STAGE + full HUD + clean Storm**,
  correct teams Storm/Magneto/Colossus vs Magneto/Doom/Cable). ⚠ Actively-comboing BODIES render BLOCKY in
  the POC (`render_ta.mjs` uses the dirty-page list; the bodytex band `[0x410000,0x460000)` may ship stale)
  — BUT tapecanvas `render_ta_wire.mjs` FORCES full-VRAM decode, so it may NOT reproduce it. sprite-render
  is rendering the `.zcst` on tapecanvas to settle **capture-bug vs POC-artifact** before any flycast fix.
  Constraints: mirror WS drops ~15s (≈900 frames/capture; full match needs a keepalive fix); skip len=0.
- **2026-08-30** — Resim TA-stream EXPORT delivered: `build-headless-win/render_ta_stream_from0.mcrr`
  (121MB, 1699 frames, incl. the super region) — a correctly-input-driven resim via `MAPLECAST_REPLICA_LIVE`
  (render-replica wire, reused, no new export code). Seat decode PROVEN offline (tape `p1_in`==confirmed
  seat1, `p2_in`==seat0, 1.0000; resim Input_DEC matches p1/p2 at 97%/96.6%, −3f pipeline delay). "Doom
  walking" was a FALSE ALARM (smoke test hit an attract server; fixed by rebasing the movie to battle-frame
  920). ⚠ Faithful through ~battle-frame 297 then ASSISTS DRIFT (assist types default 0x00; `select_in`
  replay DEAD — no directional bits captured; needs sh4-re for the assist-select input flow → autoselect).
  ⚠ WIRE RECONCILE: `.mcrr` = render-replica (transpiled `render_frame`, rank-3?) vs the serverPublish
  real-TA `.zcst` (rank-4) — sprite-render to render the `.mcrr` on WebGPU + settle which is ground truth.
- **2026-08-30** — WebGPU render side **PROVEN**: the tapecanvas renderer draws the real TA stream
  (bodies + effects + HUD + stage + **ADDITIVE BLEND** — the Storm super, which the emitter can't do),
  headless Dawn, no flycast mirror; two renders byte-identical (determinism PASS). `.mctele` confirmed =
  STATE tele (emitter/approximation), NOT the TA. TA export = `serverPublish` wire via
  `MAPLECAST_MIRROR_SERVER=1` + `capture_mirror.mjs` → `.zcst`; consumer `web/tapecanvas/render_ta_wire.mjs`.
  Render side UNBLOCKED — remaining: resim emits the wire (B-conn) + determinism (B2c).
- **2026-08-30** — Resim **MILESTONE**: faithful reconstruction WORKS — the resim plays the tape's ACTUAL
  match on the mirror (the "Doom just walking forward" input bug is fixed). Architecture confirmed (Tris):
  flycast **exports the TA stream**, **WebGPU** (tapecanvas, reusing `king.html`/`webgpu-test.html`) renders
  it — the mirror is the SOURCE only, not the renderer. Lag on the mirror is MOOT: the resim is a one-time
  capture; WebGPU plays the captured TA back smoothly regardless of resim speed.
- **2026-08-30** — B2 attempt 1 = **INCONCLUSIVE, not KILL.** Resim bit-exact to Steam through the first
  hit (+ knockback), self-deterministic, no cross-core signature; diverged X-only at the first assist
  (harness recon, not engine). Strict through-super gate NOT met. Determinism fear substantially reduced;
  Path B not certified. Blockers = assist-faithful char-select recon (B2b, engine work) + converter bug
  (B2a). **DECISION PENDING (Tris): invest to close B2, proceed on current evidence, or hold.**
- **2026-08-30** — B0 RESOLVED (sh4-re): resim target = **DC GDI** (Steam FC is a DC-lineage recompile;
  DC↔blk field-exact map; DC core on box; all semantic RE is DC-addressed). `srand(1)`@battle-init
  confirmed ⟹ resim RNG deterministic by construction; **G-RNG now settled empirically by B2, not
  analytically.** A2 unblocked (56-char palette offline-derivable). A1 delivered (beam true-color).
- **2026-08-30** — Corrected memory `rr-flycast-resim-confirmed-tape`: the "PROVEN VIABLE / MUST USE
  NAOMI" claim was retracted (DC-not-NAOMI, contaminated); resim NOT PROVEN.
- **2026-08-27** — Prior team decision (`STEAM-TAPE-RENDER-HANDOFF.md`, commit 24a084b): Path A =
  pixel-perfect target; Path B (flycast) parked NOT-PROVEN. Survives adversarial review.
- **2026-08-30 — ⭐ RESTORE POINT (session close).** Committed as a return spot. State of play:
  • **Render = DONE + PURE TA.** `web/tapecanvas/play_zcst.html` renders the real serverPublish TA on WebGPU
    (king.html's exact pipeline: FrameDecoder→TAParser→pvr2) with a **60fps-paced speed control** + a
    **RetroReceipts name overlay** (`?left=&right=`). NO prebaked sprites — the emitter/atlas path is retired.
  • **Full-match CAPTURE fixed** (budget bug: `capture_mirror.mjs` 15s `setTimeout`; match runs ~12.7k frames;
    `capture_mirror_full.mjs` stops on `match_end`).
  • **Input decode is FAITHFUL (98.8%) but per-tape** — the alignment must be MEASURED; `ggpo_sim_tie` is
    MISLEADING (Tris's tape 59604428: real offset **+1**, not the reported +6; P1=seat s0 at local_pn=0).
    Duc's tape likely looked wrong from a bad offset. Tool: `scratchpad/build_movie_59604428.py` (offset scan).
  • **But the resim still DRIFTS over a full match** — cross-core (DC flycast ≠ Steam). Tris's match: 12.7k
    resim frames vs 3.8k real input frames; reaches `match_end` with the CORRECT winner (nachero/P2) but via a
    divergent longer fight. Tris confirmed by eye ("doesn't look like how duc plays"). ⟹ **input reconstruction
    SOLVED; the wall is cross-core determinism = the RNG.**
  • **ROM lineage re-confirmed:** Steam = DC-lineage recompile (`__DEV_TYPE_DC__`), NOT NAOMI.
  • **king.html clarity:** it renders LIVE TA from a running engine (no resim/determinism) — that's why it's
    pixel-perfect; the replay player is the SAME renderer, so the render half is done.
  • **DETERMINISM RIG we built but NEVER RAN:** `replay-kit/verify.py rng` (read-only, ~1 min — settles
    whether the RNG is inside `blk`) and `AB.cmd` / `rrtape4.py ab <tape.rr4>` (the full A/B falsification:
    restore anchor→replay→churn 900 random→restore→replay same→compare A==C). §2.3 already PROVED bit-identical
    in-engine replay from a full `blk` snapshot + inputs — so faithful replay IS achievable in the matching
    engine; the drift is the flycast cross-core mismatch.
  **NEXT:** run `verify.py rng` + `AB.cmd` against the live Steam game to settle the RNG-determinism question
  — decides whether faithful full-TA replay = "restore full blk + feed inputs, capture the engine's TA", or
  whether we drive the render from the recorded state each frame (state-injection — Tris's idea, no drift).

## 7. OPEN QUESTIONS PARKING LOT
- Does the Option-B camera focal 812.357 stay constant across a superjump? (Oracle probe
  `0x8C26A518+0x20` + `blk+0x6990/0x6994`) — Track A7 dependency.
- B1 (`AB.cmd`) needs a full-match `.rr4` captured via `rrtape4.py` — do we have one, or is a fresh
  live capture with Tris required? (resolve before scheduling B1.)
- ⚠ **Correction to route to sprite-render with the A2 bake:** `maplecast-flycast/docs/MVC2-RECONSTRUCTION-SPEC.md:183`
  says costume palette stride `*0x80`; the disasm (`bank03.asm:11900-11906`, `shll2×3+shll×2` = `<<8`)
  says `*0x100`. Load-bearing for baking. (RE-panel repo, not our lane — flag, don't edit blindly.)
- ✅ **B2 design RESOLVED 2026-08-30: FULLY OFFLINE.** The tape's `frames` carries per-frame Steam raw
  state with every gate field (px/py/vx/vy/hp/facing ×6) + `ggpo_sim_tie` for alignment + a `blk` snapshot.
  DC resim RAM vs recorded `frames` via the DC↔blk map — no live Steam session needed. (B1/`AB.cmd` still
  needs live Steam; B2 alone may suffice to prove/kill resim.)
