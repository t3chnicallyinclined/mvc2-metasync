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

- **2026-08-30 — ⭐ DRIFT LOCALIZED: cross-core FLOAT rounding (not RNG, not inputs). STATE-INJECTION required.**
  Frame-exact B2 re-run on the CLEAN tape (`…59598769…`) with assists ON + measured alignment: **bit-exact on
  ALL 6 fighters through f1223** (intro, neutral, first assist entrance, first combat hits f1217/f1235) →
  **input/assist/init reconstruction is COMPLETE + correct** (the old "diverge at first assist" was the wrong
  assist_type; the poke fixed it). FIRST divergence f1224: char15.px off by **exactly 1 float32 ULP** (1.5e-5),
  then char44.vx 1 ULP as a constant offset — DC SH4 vs Steam x86-64 rounding. Benign until the **first super**,
  which amplifies it across a hit-decision boundary → HP cascades → a different match. ⟹ **no input/assist/init/
  RNG fix can close a 1-ULP float gap; free-run resim is NOT viable for a full faithful match. STATE-INJECTION
  (drive the engine with the recorded per-frame state — Tris's idea) is the required path** (caveat: the tape
  doesn't record every effect sub-state → effects need separate handling). Optional bounded pre-experiment
  (flycast-internals, LOW probability): match flycast SH4 float to the recompile (rounding mode / FSRRA-FTRV /
  disable fast-math dynarec); if it goes bit-exact through the first super, free-run becomes viable.
  ⚙ Methodology to record: per-tape **slot remap** (this tape `{0:0,2:2,4:4,1:5,3:1,5:3}` — P2 point in slot 5);
  `MAPLECAST_ASSIST` is **per-CHARACTER** (`0,1,1;0,1,1`), not per-tape-slot; **gframe alignment** `tape_frame =
  gframe − 654` (TELE_OUT skips records during supers/round-transitions — align by the DC game-frame, not rec index).

- **2026-08-30 — ⭐ STATE-INJECTION designed + STAGED (turnkey; blocked only on a 2-object flycast rebuild).**
  The mechanism ALREADY EXISTS compiled in: `maplecast_gamestate::writeGameState` (roster `0x8C268340`, stride
  `0x5A4`) + `MAPLECAST_STATE_REPLICA`. **RE gap** (inject-vs-kept-live): pos/vel/screenpos/facing+xflip(`0x1D2`)/
  sprite_id(`0x144`)/anim_timer/hp+red/scale/assist(`0x4C9`)/camera/globals INJECT faithfully from the tape;
  anim_state/special_id/palette/hit-flash/overlay + sub_anim_phase(`0x502`)+char_link(`0x00C`) kept as live SH4
  values (read-overlay-write); **effects/object-pool + per-node HUD sprites = the residual gap** (node-synthesis,
  follow-up; bars/numbers still render off injected meter/hp/timer). ⚠ INFERRED (sh4-re to confirm at build): the
  draw may sample roster `0x268340` (what writeGameState targets; state_replica proved 99.7%) vs on-screen array
  `0x2D7088` — first suspect if injected bodies don't move. **Mechanism CHOSEN:** a per-vblank `applyStateInject()`
  hook inside a normal `MIRROR_SERVER` resim — writeGameState writes only RAM (not VRAM), so the VRAM memwatch
  stays ON and the existing capture pipeline yields a clean `.zcst`. (External WPM = NOT VIABLE — no frame-step in
  the control WS; built-in STATE_REPLICA works no-rebuild but disables the memwatch → PNG only, no `.zcst`.)
  **STAGED** in `tools/render-replica-poc/`: `state_inject.patch` (3 additive hunks at the assist-poke site
  `emulator.cpp:2204`), `tape_to_gsta_inject.py`, pre-produced `inject_59598769.gsta` (5147 recs, full) +
  `inject_59598769_super.gsta` (2600 recs, through the first super), `state_inject_build_run.txt`,
  `spotcheck_inject.py`. **Proof (stream-level):** injection stream is byte-faithful to the tape at post-super
  gframe 3279 + 4920 (px/py/sid/hp/facing identical, all 6 fighters) → **drift-free by construction** past the
  1-ULP wall. REMAINING: a 2-object `ninja flycast.exe` rebuild (blocked from this isolated worktree — same wall
  as the assist poke + the wenzel deploy) → capture → render on `play_zcst.html`; the live-pixel gate (rendered
  `.zcst` diffed vs the tape) is the build session's job. Open hazards for that session: multi-round transitions
  under FREEZE (SH4 KO/round-intro logic firing off injected hp=0) — why the single-round `_super.gsta` is scoped.

- **2026-08-31 — rise3 = the flycast resim/render build host (GO, live-verified).** rise3 = `ns1012691` @
  **15.204.141.58** (OVH, Ubuntu 22.04, passwordless sudo via `~/.ssh/ovh_maplecast` user `ubuntu`); dev0ps =
  65.109.77.178 (Hetzner, current prod). CONFIRMED GO for the headless flycast resim: **no GPU needed** (NO_REND
  null renderer; `.zcst` = CPU TA-list + VRAM memwatch), toolchain present (gcc11 / cmake3.22 / ninja / node22),
  and a **working `build-headless/flycast` already builds + runs** at `/home/ubuntu/src/maplecast-flycast` (branch
  `feat/executor-pool-spawn`, HEAD f6ff8964b — USE THIS TREE; `/home/ubuntu/projects/maplecast-flycast` is NOT
  build-ready, submodules uninit). **ROM present** at `/home/ubuntu/roms/mvc2.gdi` (+tracks; boots via HLE BIOS →
  no BYOR gap, nothing to copy). 25.9 GiB free, Ryzen 5900X / 24t, 381 G disk free. ⚠ rise3 NOT prod yet but
  **cutover ~2026-09-01** + a live-predict flycast (PID 1130, warm-standby, floats CCD 0-23, no systemd unit) runs
  — keep the state-inject build INCREMENTAL (not a from-scratch 24-core compile), moderate `-j`, ideally CCD-pin
  the resim opposite the predictor. The existing binary already has a FREE-RUN offline replay
  (`MAPLECAST_REPLAY_IN/OUT` + `maplecast_replay::spawnMatchWrite`, compiled-but-not-yet-exercised on Linux) — but
  the drift-free demo still needs `state_inject.patch` (+ the assist hook) applied + an incremental rebuild here.

- **2026-08-31 — rise3 build BLOCKED: its build tree is a stale/stripped branch; the inject+autoselect subsystem
  is UNCOMMITTED-local-only.** rise3's `/home/ubuntu/src/maplecast-flycast` (`feat/executor-pool-spawn`) and
  `/home/ubuntu/projects/...` (`feat/play-page`) both LACK `maplecast_autoselect.*`, `applyAssist`,
  MAPLECAST_AUTOSELECT/MENUNAV/MOVIE_IN/STATE_INJECT, `maplecast_replay`, SAVE/LOAD_AT_FRAME, TELE_OUT (verified by
  grep on source + `grep -ao` on the binary → only HEADLESS_AUTOLOAD/MIRROR_SERVER/STATE_REPLICA). ⟹ the full
  match-entry+injection subsystem exists ONLY as **uncommitted working-tree edits on the local Windows box** — no
  branch has it, so `state_inject.patch` (anchored on autoselect + applyAssist) can't apply on rise3. Confirmed
  compatible on rise3: `maplecast_gamestate.*` byte-identical (writeGameState/readGameState/deserialize, WIRE=376),
  vblank graft site emulator.cpp:2115, GPU-less MIRROR_SERVER capture, savestate format (V62). ⚠ CROSS-BUILD
  savestate RESTORE-STALLS (threaded: renderEnd.Wait() never clears; single-threaded: 1 frame then idle) — only a
  rise3-NATIVE state loads clean, but rise3's build can't autoselect a roster (circular). rise3 default roster =
  [42,52,44]/[23,23,23] (Storm/Sentinel/Mag vs Cable), NOT tape 59598769's [42,44,50]/[15,23,44]. Staged on rise3
  at `/home/ubuntu/inject_run/` (gsta + capture + patch + a roster savestate). ⟹ producing the injected `.zcst`
  needs the FULL subsystem source on a box + a real (non-incremental) build; from an isolated session only rise3 is
  reachable (local repo write blocked). **PREREQUISITE regardless: commit the subsystem to a branch** (fragile as
  local-only edits). DECISION PENDING: non-isolated local build (commit+build+demo now, rise3 builds clean post-
  cutover) vs full gcc build on rise3 now (heavy compile / cutover-eve / MSVC→gcc porting risk).

- **2026-08-31 — DECISION: build the injection binary LOCALLY (non-isolated Windows), commit-first.** Tris chose
  the local build over a from-scratch gcc build on rise3 (the latter = heavy compile on the predictor box the eve
  of cutover + MSVC→gcc porting risk). VERIFIED the local tree is ready: `emulator.cpp:51` includes
  `maplecast_autoselect.h` and `applyAssist()` is at `emulator.cpp:2204` — the exact anchor `state_inject.patch`
  needs, so it applies cleanly locally (unlike rise3's stripped tree). ROM local at `C:\roms\roms\mvc2.gdi`, MSVC
  toolchain present. Locally we cold-boot the roster via autoselect MENUNAV — no savestate needed (that was rise3's
  constraint). EXECUTION = `tools/render-replica-poc/state_inject_build_run.txt`, now with **step 0 (commit the
  uncommitted subsystem to branch `feat/render-accuracy-inject` — fixes the local-only fragility)** and **step 6
  (push it → enables a clean `git fetch+checkout` rise3 build after cutover, no working-tree scp)**. ⚠ Needs a
  NON-worktree-isolated session in `maplecast-flycast` (this render worktree can't commit/build there). Flow:
  commit → `git apply state_inject.patch` → `ninja flycast.exe` → run (MENUNAV 42,44,50;15,23,44 + STATE_INJECT
  inject_59598769_super.gsta + MIRROR_SERVER :7300, NO MOVIE_IN) → `capture_mirror_full.mjs` →
  `render_ta_wire_inject_super.zcst` → render on `play_zcst.html` + spot-check post-super vs tape → push branch.

- **2026-08-31 — ⚠⚠ RAW STATE-INJECTION EMPIRICALLY FALSIFIED (built + run on rise3).** The naive "inject recorded
  fields each frame → drift-free by construction" does NOT hold — the running game rejects partial pokes. Two
  measured failure modes (flycast-internals, live on rise3): (1) poking `sprite_id` (0x144) → **100,990 "SH4
  exception when blocked"** faults — the tape lacks `anim_pointer` (0x168)/`animation_state` (0x1D0), so a lone
  sprite_id poke desyncs the anim lookup → fault; dropping sprite_id → crash=0 (cause confirmed). (2) position-only
  injection → **render STALLS** (no GSTA/OBJS after FIRST inject). ⟹ the earlier "drift-free by construction" was an
  UNPROVEN design argument, now falsified for the raw form. The one injector that IS stable —
  `maplecast_state_replica` (99.7%, handles anim-context + warmup + gating) — **disables the VRAM memwatch so it
  cannot emit a `.zcst`**. THAT tension is the real problem. ⟹ **the local `state_inject.patch` build would hit the
  SAME wall — NOT a turnkey demo.** Real fix = sh4-re + sprite-render domain: (a) the full anim-context fields needed
  to inject sprite_id safely, (b) why position injection stalls + how to hold `in_match`, (c) likely inject at the
  STARTRENDER oracle-hook (`maplecast_oracle_hook::mc_sidLatch`, emu-thread, after-update/before-draw) not vblank.
  Reconciled live: savestate autoload = `dc_loadstate(slot0)` at emulator.cpp:836 (XDG dir, not ROM dir); restore-safe
  states need control-WS `savestate_save` (frame-top, clean pend_rend), NOT `MAPLECAST_SAVE_AT_FRAME`; roster-matched
  state produced (char_ids 42,15,44,23,50,44 = tape 59598769). rise3 left pristine (predictor PID 1130 healthy);
  staged `/home/ubuntu/inject_run/`. Fastest FAITHFUL-demo candidate to evaluate: `state_replica` → PNG/video
  (stable, drift-free, anim-correct) IF a build can rasterize it — sidesteps the `.zcst`-capture problem entirely.

- **2026-08-31 — EVALUATING (Tris's pivot): capture STEAM's OWN render stream, drop the flycast resim entirely.**
  Rationale: the drift exists ONLY because we resim on flycast (DC) — Steam replays ITSELF bit-exactly
  (`STEAM-GGPO-DETERMINISM.md §2.3`, restore `blk` + inputs), so a Steam-native render capture has NO cross-core
  float AND no injection. Plan: do ALL RE on the STEAM x86-64 binary (Ghidra; `mvc_dump.bin` — retail exe is PACKED)
  to find where it issues per-frame render/GPU commands, hook + capture that stream while driving a bit-exact
  self-replay, then replay in the browser king.html-style (WebGPU). DC/flycast experts = INFERENCE only. ⚠ KB
  constraints to honor (don't re-derive): Steam spectate = GGPO inputs-only (re-sim, no frame stream); prior "Steam
  has no DC-TA FIFO / draw fn not standalone-callable" (`rr-sprite-render-pipeline`, `mvc-mame-naomi-render-verdict`)
  closed the DC-TA door but did NOT map Steam's native renderer. senior-re-generalist LEADS the feasibility RE
  (consults sh4-re + sprite-render); FALSIFIABLE VERDICT + candidate capture hook required BEFORE any build.

- **2026-08-31 — VERDICT (senior-re-generalist, Ghidra on `mvc2_dump.bin`): STEAM-native render capture = NO-GO.
  STAY ON PATH 1 (flycast — we own the build).** Steam's renderer is **Capcom MT Framework on Direct3D 11**
  (CONFIRMED: imports `D3D11CreateDeviceAndSwapChain`/`D3DReflect`; strings `AppShaderPackage`/`ID3D11Texture2D`/
  bloom params) — NOT a PVR2 rasterizer, NOT a DC TA display list. Per-frame path: `FUN_140620F10` walks the
  16-layer draw list (`blk+0x2f4d0`) → `FUN_1406129F0`/`140612F70` decompress the twiddled 4bpp parts → upload to
  D3D11 textures → issue textured-quad **D3D11** draws. ⚠ Only the SOURCE ART is PVR/NAOMI-shaped; the RENDER is
  native D3D11 — `REPLAY-ENGINE-DESIGN.md:113-114`'s "PVR submit → D3D11" gloss is WRONG (asset-format vs
  render-arch conflation; the trap the pivot rested on — CORRECT THAT DOC). NO passive capturable stream (no TA
  FIFO, no confirmed PVR para-list in RAM — INFERRED-strong; the 32-byte-stride heap probe was never run = the ONE
  disproof test that could move the verdict). Capture ⟹ in-process DLL injection into Capcom's DRM'd binary, and it
  does NOT feed our pvr2 renderer (a byte-exact DC-PVR2 port): case-a = the STATE we already read (emitter path,
  +1 blend bit only); case-b = MT-Framework D3D11 VBs needing a from-scratch browser renderer targeting Steam's
  bloom'd look, which ISN'T the program's ground truth (the gate is the flycast DC-PVR2 TA-mirror). Bit-exact
  self-replay is real but SIM-layer + bounded (rollback≠replay; RNG-through-super open; render/shell state outside
  `blk`, restore garbles the frame). ⟹ the pivot swaps the SOLVED half (render — we own flycast, pixel-perfect incl.
  the Storm super) for the UNSOLVED half. **PATH 1 next steps:** (i) bounded FLOAT-MATCH experiment (flycast
  rounding-mode / FSRRA-FTRV / disable fast-math dynarec → free-run bit-exact through the super; low-prob but cheap;
  NO injection if it hits), else (ii) inject at STARTRENDER (`maplecast_oracle_hook::mc_sidLatch`, after-update/
  before-draw) WITH the missing anim-context (`anim_pointer 0x168` + `animation_state 0x1D0` = the 100,990-fault
  cause). **⚠ GATE G-PIXEL** (frozen-frame browser-vs-TA-mirror region diff, `MAPLECAST_GSTA_SHOT_EVERY=1`) does NOT
  exist yet — no path may claim "pixel-perfect" until it's built + passes; the current "99%" is eyeballed, unmeasured.

- **2026-08-31 — ⭐ PRODUCT DECISION (Tris): a faithful FIXED VIDEO is enough for the replay — no re-render / no
  skins needed.** ⟹ DROP the flycast resim / TA-stream / determinism-fight for the replay use case. New path: run
  the REAL Steam MvC2 on a rendering-capable host, drive a BIT-EXACT self-replay of the tape (restore `blk` + feed
  the tape's inputs — NO cross-core float, it's the real binary), capture the framebuffer (D3D11 `Present` hook) →
  video → serve to the browser as a plain video. Massive simplification: the real game renders (pixel-perfect by
  definition) + self-replays deterministically (same binary). 3 components: (1) DRIVE the replay (blk-restore +
  GGPO input-ring drive — RE exists: `STEAM-GGPO-DETERMINISM.md §2.3` + `rr-ggpo-input-ring`; tool state TBD), (2)
  framebuffer CAPTURE (Present hook → video encode), (3) WHERE it renders (needs GPU/WARP — user's Windows box for
  the demo; GPU-shared container per `mvc-hosting-virtualization` for prod). ⚠ THE risk to verify: is Steam
  self-replay bit-exact THROUGH A SUPER? (RNG-through-super open; `verify.py rng` inconclusive — but same-binary
  self-replay + `srand(1)` at battle-init argues YES.) Verify EMPIRICALLY by comparing the replay video to the known
  match. Tradeoff accepted: a video loses custom skins / 3D re-render / overlays. senior-re-generalist scoping the
  fastest demo + build-vs-have inventory.

- **2026-08-31 — ⭐⭐ VIDEO-DEMO PLAN SCOPED (senior-re-generalist, grounded in `replay-kit`): GO, ~zero new code,
  on Tris's box.** The DRIVE half is TURNKEY + on disk: `replay-kit/rrtape4.py` (`rec`/`play`/`ab`) + `REC4.cmd`/
  `PLAY4.cmd`/`AB.cmd` do the whole Steam self-replay — restore a **char-select** blk anchor (`savestate.py`/
  `restore_blk.py`, portable) + drive inputs via the offline LATCH `IN0 = G+0x218` (NOT the read-only GGPO ring; it
  NOPs the 2 pad stores at `0x14003A33B/35F`, `inputrec.py:35-51`). The only genuine build is FRAMEBUFFER CAPTURE (a
  D3D11 `Present` hook — reuse the proven injector `hook/d3dhook.dll` + `retour`; it currently hooks palette uploads,
  NOT the backbuffer) — **but the demo needs ZERO code: external capture (Win Game Bar / OBS / `ffmpeg gdigrab`)
  records the window while `PLAY4` self-replays.** ⚠ KEY CORRECTION: use a **FRESH match Tris records**, NOT the
  historical agent tapes (`59598769`/`59604428`) — those carry a battle-state anchor (`anchor_frame:3`) that is NOT
  cross-process portable (557 asset-image pointers; crashed twice); the rig anchors at char-select (portable) + runs
  battle-init in-process → `srand(1)` reseed → deterministic through supers. DETERMINISM GATE is self-serving:
  `PLAY4` verifies every 30-frame checkpoint incl. a **CRC32 of the whole blk** vs the recorded game → "VERIFIED: N
  checkpoints matched exactly" = per-frame byte proof the super replayed; `AB` (A==C) is the generator-agnostic
  clincher. Ship the video ONLY on a VERIFIED tape → we MEASURE faithfulness, never guess. FASTEST DEMO: (1) Steam→
  char-select, (2) `REC4.cmd` play a match w/ a super, (3) `PLAY4.cmd` → require VERIFIED, (4) screen-record +
  `PLAY4.cmd` again → mp4, (5) serve as plain video. All ELEVATED. Steps 1-3,5 = HAVE; step-4 capture = external
  record (have) or Present-hook (build later). sh4-re sign-off pending: Steam battle-init ≡ DC `srand(1)` (AB
  substitutes empirically); exact `Present` site in `mvc2_dump.bin`.

- **2026-08-31 — DIVERGENCE RESOLVED = benign +21 frame-phase artifact (senior-re-generalist, code-grounded); use
  AB not PLAY.** The first live `PLAY4` "DIVERGED at 11640 (45/45 CRC differ)" is NOT a match divergence: (1) 11640
  is DEEP in char-select (match-start 12789); (2) every NAMED fighter field matched all 45 checkpoints (only the
  `blk CRC` line printed, none of the per-slot hp/pos/vel/sid lines `compare()` emits — rrtape4.py:341-359); (3)
  root cause CONFIRMED arithmetic-exact — `restore_anchor` writes full state incl. frame counter (blk+0x3CC8)=11614,
  then `time.sleep(0.35)` (rrtape4.py:411) lets the thawed sim free-run 0.35s×60 = **21.0** frames → base=11635,
  drift +21. Inputs are drift-compensated (`fed 1376/1377`, named fields align), but `blk_crc` includes
  counter-DERIVED presentation state — rotating char-preview floats `blk+0x1e000..0x2a000` ("Presentation only; safe
  to ignore or carry", STEAM-GGPO-DETERMINISM.md:123-124) + menu/cursor timers — which differ by 21 at every
  checkpoint. Recording is zero-drift (live), replay is +21 ⟹ `play`-vs-recording CRC ALWAYS mismatches regardless
  of match determinism = WRONG GATE. ✅ CORRECT GATE = **`AB.cmd`** (`rrtape4.py ab` :549-619): two REPLAYS (both
  +21 → frame-phase CANCELS) asking the real question — does anything OUTSIDE blk survive the restore + change the
  match. **A==C ⟹ determinism proven (super incl.) → green-light capture.** ⚠ `--ff` NEVER valid for a verify
  (rrtape4.py:435-436). Optional hardening: fixed-frame-target wait instead of the wall-clock sleep, and/or exclude
  the preview region from blk_crc. ⭐ KEY: **the demo VIDEO does NOT depend on this CRC** — inputs align + named
  fields reproduce ⟹ match footage is faithful; capture from match-start (also skips the char-select shell garble).
  sh4-re confirming the diverging bytes = 100% the cosmetic preview region (moot if AB says A==C).
- **END-GOAL (Tris, restated):** browser-streamable replays ANYONE can watch in-browser. The framebuffer **VIDEO
  fully delivers this** (every browser plays video, no renderer, pixel-perfect) = simplest complete form. Extracting
  Steam's RENDER COMMANDS (smaller / re-renderable / skins / camera) is a LATER optimization and needs a browser-side
  renderer since Steam draws in **D3D11** (the deferred harder path) — NOT required for "anyone streams in-browser."

- **2026-08-31 (sh4-re CONFIRMS from the disasm side — both experts now agree):** the diverging bytes are
  free-running char-select AMBIENT state inside the CRC but outside the fighter digest — the satellite object pool
  (`blk+0x6dd8..0x2ded8`, holds the rotating 3-D preview models incl. the `0x1e000..0x2a000` floats), the draw list
  (`blk+0x2f4d0`), cursor/menu timers, bg animation — all `f(frame_counter)`, offset +21 by construction. Battle-init
  RESET is CONFIRMED in the DC disasm: `loc_8c03dcd8` (bank03), gated on gameflow state `+0x4C==5`, calls init/reset
  then `srand(1)` (`loc_8c11e770`, r4=1) hard-writing `RngVal @ 0x8c16bc2c = 1` BEFORE the match reads RNG → the
  match RNG stream is independent of char-select; fighters re-init from asset data; preview pool freed. ⟹ a
  char-select divergence CANNOT reach the match sim. Named fighter fields matched all 45 checkpoints INCL. in-match
  frames past 12789 ⟹ the match sim reproduces bit-exact. ⚠ ONE caveat: this proves the SIM; ambient animation still
  renders +21 off-phase under restore — irrelevant to a fighter/HUD video, but for pixel-exact STAGE/effect phase,
  pin `FC_OFF=0x3CC8`+mirror post-restore, or use a from-frame-0 resim. VIDEO of the match = faithful (fighters
  exact; background = same stage, harmless phase offset).

- **2026-08-31 (EMPIRICAL byte-localization — senior-re, offline from `curA.blk`/`curB.blk`): char-select diff =
  467/211,736 bytes (0.22%), 100% cosmetic, ZERO sim fields.** Diffing two real char-select blk snapshots: changed
  bytes = frame-counter+mirror (`0x3CC8`/`0x3CD4`, CRC-excluded), input words (tape-fed), char-select cursor/CID/
  anim-timer, RENDER attrs (`0x32BD4/E8`), and — dominant ~430B — the **object-pool preview-model nodes
  (`0x1E000..0x2A000`**, pool base blk+0x6dd8 stride 0x280, `loc_8c044dce`). NONE of worldXY/velXY/screenXY/sprite/
  HP changed → char-select CRC diff is cosmetic, byte-level confirmed. ⚠ STILL OPEN (MEASURE, don't assume): MATCH/
  SUPER determinism — during a match the SAME pool holds RNG-driven effects, so a super-frame CRC diff needs a test.
  TOOLS: `AB.cmd` (A==C ⟹ self-consistent) fast; NEW `replay-kit/blk_localize.py` (`cap A`+`cap C` at [11640,
  post-super frame] → `diff` → flags SIM vs pool-effect) = definitive offset-level super test. Current tape m033020
  = ~200-frame match (short, likely no super) → record a proper super match to test + for the demo.

- **2026-08-31 (Tris's catch — IMPORTANT gotcha): training MODIFIERS break (anchor+inputs)→match determinism.**
  Recording with training **meter regen** ON injected meter OUTSIDE the captured inputs → on replay (anchor=char-
  select, meter 0) the regen didn't reproduce → a triple-meter super the recorded inputs called for had no meter →
  match divergence (meter is NOT in the named-field digest → surfaces only in the whole-blk CRC, consistent with
  "named fields match, CRC differs"). ⟹ RECORD CLEAN: no meter regen / infinite health / any training modifier that
  changes the sim outside the controller inputs; build meter naturally through combat so the super is a pure
  consequence of reproduced inputs. Also: DON'T restart the game between record + replay (this run's arena moved
  +0x1900000 = the untested relocation branch R2, plus RPM 299 / process-not-found from closing the game). (Open: is
  the training-regen SETTING in blk[0..0x33B18)? if yes it'd reproduce; clean-record sidesteps it — sh4-re can
  confirm.) NB the reported "DIVERGED @540" is STILL the char-select cosmetic artifact (540 < match-start 1424);
  PLAY4 stops at first divergence so the meter divergence wasn't even reached — use AB.

- **2026-08-31 — ⭐ DECISION (Tris): PATH A — render the tape's saved per-frame STATE on the WebGPU CANVAS with real
  extracted sprites.** Chosen over B (Steam D3D11 draw-capture + a new browser renderer = pixel-perfect but a big
  net-new build) and C (screen-record video = flat, NOT a canvas render, the detour). Path A = re-renderable in the
  browser, real game art, and REUSES what we built (rr-owned-tape-render, `sprite-client` emitter path, `sprite-gpu`,
  the PLxx atlases, the 3-D stage render). The saved STATE is ALREADY captured (agent tapes carry per-frame render
  state — tape-v2 columns drawn/sid/eyeX/eyeY/ground + objs + camera; ⚠ HUD list-0x0B is NOT in the tape → separate
  handling). flycast-TA is OUT (renders a DIVERGED match, not the real one); Steam-video set aside (flat). OPEN WORK:
  refine the DRAW toward pixel-perfect with the game's REAL blend/layer data (blend modes, layering, effects, HUD) —
  render ONLY real extracted assets (Tris's hard rule, no approximations). NEXT: sprite-render expert renders a real
  tape's state on the canvas (viewable demo) + the precise gap list.

- **2026-08-31 (sh4-re, disasm-grounded): per-part BLEND LOCATED = it's RUNTIME PVR render-state, NOT a part field.**
  Closes the "blend UNLOCATED" open item. The GFX2 part record carries NO blend bit; the emitter descriptor MODE
  (`*0x8C1F9D84`) is globally FIXED at `0x02` for every 2D sprite (bodies AND cat-1-4 effects), and the submit
  `loc_8C1244B0` (bank12:9794) resolves MODE-2 blend straight from the **runtime global register `0x8C2AA4C4`**
  (packed src/dst, set per draw-batch/scene-fade by `loc_8c11d490`, NOT per-object). ⟹ blend CANNOT be baked offline
  per-part (same sid draws opaque/alpha/additive depending only on the register that batch). ⚠ the current
  `tape-adapter.mjs:282` "all cat-1-4 → additive" is WRONG — cat-1-4 sprite objs run MODE-2 = the SAME global blend
  as bodies (alpha/opaque), NOT pure-additive; only beams/auras/hitsparks (many cat 5-13, out of scope) are truly
  additive. **IMMEDIATE Track-A fix (implementing): add the missing ALPHA pipeline to sprite-gpu.mjs, replace 1-bit
  `isAdd` with a 2-nibble blend byte → {opaque 1/0=pipe, alpha 4/5=alphaPipe, additive 1/1=sparkPipe, alpha-add
  4/1=pipeAdd}, DEFAULT cat-1-4 to ALPHA (not additive) → fixes "too bright" now.** Follow-up: a capture-derived
  gfx1 allowlist (BODYCAP pass) promotes the genuinely-additive banks — real data, not a guess. PIXEL-EXACT per-object
  blend stays a Track-B (real-TA) / submit-hook property = the definitional ceiling. (sh4-re to re_kb-UPSERT
  `finding:emitter_blend_is_runtime_state`.)

- **2026-08-31 — ⭐⭐ AUTHORITATIVE RENDER-COMPOSITE MODEL (sh4-re, disasm-grounded) — the root fix for the recurring
  z/layer/depth/fog/transparency bug class.** Scene = TWO machines → ONE PVR frame, rendered fixed **OPAQUE → PT →
  TRANSLUCENT**: the 3D machine (`loc_8c030410`) draws the stage/props **OPAQUE**; the 2D sprite machine
  (Render_sprites `loc_8c0308c2`, bank03:1200) draws **EVERY body/cape/projectile/effect TRANSLUCENT**. ⟹ the stage
  is behind all 2D by **LIST-TYPE, not depth** (never depth-fights the deck). Inside TRANSLUCENT = a REAL z-buffer:
  ISP DepthMode=4 (Greater), ZWrite ON, per-part **Z = 1/W**, W = `node+0xE8` (=0.1·camZ + rparam[layer]) +
  0.001·partIdx ⟹ **first-submitted = frontmost.** Draw-order key = **(`node+0x24` layer ASC, `node+0x31` depth-byte
  ASC, then registration order: body BEFORE its satellites)** — the slot table IS the draw list (16 layers @
  `0x8C287DE0` stride 0x180; registrar `loc_8c04515e` bank04:12166 insertion-sorts by `+0x31`, refuses cat>4).
  **CAPE = CONFIRMED BEHIND** (owner+satellite share layer + `+0xE8` → exact TIE → body registered first writes Z →
  strict-Greater blocks the equal-Z cape → body FRONT, cape BEHIND). **FOG = decisively NONE** (zero fog refs in the
  disasm; body TSP FogCtrl=2=No Fog) → emitter implements NO fog term, stop worrying about it. ⚠ EMITTER DIVERGENCES
  (`sprite-gpu.mjs` is a PAINTER with NO depth buffer — every z/layer bug lives in the sort↔engine-key gap):
  (1) ROOT FIX = give it a `depth32float` + feed Z=1/W, depthWrite ON / compare GREATER (what `pvr2-renderer.mjs`
  already does @ lines 10/338-339/390-396) → kills the whole class; (2) cape tie must act on the engZ path (sort
  satellite BEFORE owner on tie), not just the layer fallback; (3) `satLayer=o.type` uses CATEGORY (node+0x03) not
  the real `node+0x24` LAYER — carry the real layer; (4) keep bodies alpha `0x45`, additive only for the gfx1
  allowlist. WIRE-GAP: carry `node+0x24`/`+0x31`/`+0xE8` per object (reader/tape change) for byte-exact order (engZ
  already validated available, `sprite-client.mjs:2280`). **Blackheart-assist projectile = ownership/gating, NOT
  order:** emitter over-gates (`sprite-client.mjs:2216-2228` requires an ACTIVE same-cid body + sid-in-assembly) so an
  assist projectile that outlives/precedes its caster, is owner-less, is an FX-poly, or is on 3D list-7 gets skipped.
  Fix = resolve atlas by the node's GFX2 bank (`node+0x160`) regardless of owner liveness + bake Blackheart's full
  sel range. (→ re_kb UPSERT `finding:render_composite_model`, pending a non-isolated session.)

- **2026-08-31 — ⭐ DETACHED-OBJECT PLACEMENT reconciled (sh4-re + senior-re cross-diff): the position is ALREADY
  CAPTURED; the bug is RENDER/ATLAS, not the tape.** Both experts CONFIRM the game places every object 100% from its
  OWN node (owner pointer `+0x80/+0x84` NEVER read across `loc_8c030af8`→`loc_8c0344d4`→`loc_8c03462c`, grep-confirmed;
  DC screen origin `+0xE0/+0xE4`, depth `+0xE8`=0.1·camZ+rparam[layer], per-part pen accumulates the wide spread from
  the sprite's OWN GFX2 records — no owner). ⚠ senior-re CORRECTION to the "tape missing placement fields" premise =
  **FALSE.** The reader `harvest_objs` (`RetroReceipts-agent/agent/src/reader.rs:1699-1736`) ALREADY emits each node's
  OWN screen origin `sx/sy` (Steam `H+0x124/0x128` = DC `+0xE0/+0xE4`, CONFIRMED-both-sides via the live uniform +0x44
  delta), `zx` scale (H+0x130), `layer`, `cat`, `sid` (H+0x188), `gfx1/gfx2` (H+0x1A0/1A4), `owner` (H+0x28); the
  renderer already places at `o.sx/o.sy` (`tape-adapter.mjs:263/286`, `sprite-client.mjs:2245`). ⟹ Inferno "wide
  column → small blob" is a PART-ASSEMBLY that failed to EXPAND: `resolveFxAtlas` resolves by OWNER char / gfx1
  bankMap (`tape-adapter.mjs:153-159`), NOT the node's OWN gfx2 → wrong/colliding atlas once Blackheart's owner-body
  leaves + his projectile sel (0x260) not baked. **FIX (Option 2, use-what's-captured): resolve atlas by the node's
  OWN `gfx2` bank + bake Blackheart's full sel range** (all inputs sx/sy+sid+gfx2 already on the wire; "assembly
  anchor" is NOT a capture field — origin = sx/sy, spread = sel→GFX2 table in the atlas). The ONE justified capture
  add = depth `+0xE8`→Steam `H+0x12C` (already inside the reader's 0x1C0 buffer, just not emitted) for Z-ORDER ONLY,
  and only after the test below. Option 3 (TA/Track-B) RULED OUT (drifting/falsified resim). ⚠ RIGOR — FALSIFICATION
  TEST FIRST (extend `replay-kit/probe_render_cols.py`): decode a frozen Inferno frame's OBJS, read `o.sx/o.sy` for
  the Inferno node, diff vs engine ground truth (7200 TA-mirror column anchor / Oracle `+0xE0/+0xE4`). sx/sy≈engine ⟹
  data correct ⟹ render/atlas layer owns it (expected); sx/sy=garbage ⟹ read the RIGHT existing field (still NOT
  owner-anchoring). Post-fix gate = G-PIXEL (frozen vs 7200 mirror). NO owner-anchoring either branch.

- **2026-08-31 — ⚠ CORRECTION (sprite-render, direct atlas+render evidence overturns the atlas hypothesis): Blackheart's
  assist RENDERS CORRECTLY — F3131 was a BAD FRAME, not a bug. The real sprite-object glitches = the LOST EFFECT WIRE
  (blend/depth/isEffect/drawn), NOT atlas/position.** Falsification test (on-disk, tape 59601369): the Inferno node's
  own-origin Y matches the engine ground plane to <1px (F3131 node sy=492 vs body-ground 491.6; F3160 434 vs 433.6) →
  POSITION CONFIRMED correct. The "bottom-left blob" is the ~600px 8-part assembly (sel 0x260 = Blackheart's own summon
  pose, `PL35_asm`) mid-RISE from below-screen, clipped (bbox x0=−263,y1=543) at F3131; fully visible as a large
  Blackheart by F3160 (4-panel proof `web/tapecanvas/_proof_bh_annotated.png`). ⟹ **the prior "atlas-by-gfx2 + bake
  sel range" fix is DISPROVEN** by direct atlas reads: sel 0x260 IS fully baked (8/8 parts, 8 quads), `resolveFxAtlas`
  keys on the stable owner-SLOT (`o.owner`) not body-liveness (resolves PL35 even after the body leaves), and `gfx2`
  ships **always 0** (`tape-adapter.mjs:144`) so "resolve by own gfx2" is infeasible without a new field. No assist
  placement/atlas fix needed. THE REAL GLITCHES (vs the prior LIVE renderer `maplecast-flycast/web/webgpu`): **(B)
  BLEND is the big one** — the live path's per-object `computeObjectBlend` (listType→additive/alpha/opaque) is DROPPED
  by `tape_to_gpujson.py`; tape defaults cat-1-4 to 0x45 alpha → genuinely-additive supers/beams/hitsparks render too
  DIM. (A) `isEffect` (node+0x15c bit0) never set → the FX-atlas single-quad path is DEAD on the tape (effect-polys
  rebuilt as body assemblies). (E) NO per-object drawn flag → 523/1170 parked pool nodes leak the y>544 cull = phantom
  projectiles. (C) no `+0xE8` → z approximate. FIX PRIORITY: (1) ship the per-object BLEND byte in the tape (server
  `computeObjectBlend` exists; converter dropped it) — interim = a gfx1→additive allowlist; (2) per-object DRAWN flag;
  (3) `+0xE8` depth (defer). STAGE CAMERA = NOT entangled (CONFIRMED): sprites draw at engine screen coords (camera
  already applied); Option-B camera only scrolls the backdrop under the sprites → the stage can wait, it does NOT
  cause the sprite glitches. ✅ this is the judge-before-recording loop working — direct evidence overturned a recorded
  hypothesis; KB corrected same-turn. ⭐ GROUND TRUTH (Tris reference screenshot): Blackheart's assist = a **bright
  vertical PILLAR** (the Inferno energy column) on the OPPONENT's side of the screen — a bright ADDITIVE effect. The
  render currently shows it dim/incomplete (dropped effect blend → additive renders as alpha). This is the
  VERIFICATION TARGET for the effect-wire (blend/isEffect/drawn) fix: the render must reproduce the bright pillar.

- **2026-08-31 — ⚠ EFFECT PILLAR: render plumbing FIXED, but the bright pillar is BLOCKED on a READER capture gap —
  the current tapes CANNOT render bright effects (verified by rendering, not assumed).** FIXED in-worktree: (1)
  `sprite-client.mjs` additive branch emitted `blend:0x1` which `_pipeFor` routes to ALPHA not pipeAdd → "additive"
  silently drew dim alpha (the sh4-re "0x1=additive" note is STALE); now honors `o.blend`/`0x11`→pipeAdd. (2)
  `tape-adapter.mjs` hardcoded every effect to `0x45` alpha → new `effectBlendByte()` (ports `computeObjectBlend`).
  Additive routing now ENGAGES (ADD 0→12/36 at the Inferno frames). ⚠ BUT the column still renders DARK not bright:
  `reader.rs harvest_objs` ships only `{sid,sx,sy,zx,face,cat,owner,layer,gfx1,gfx2}` — **NO is_effect bit, NO
  per-object blend, and the Inferno's effect-poly CELLS + effect PALETTE were never captured.** Ownerless demon sels
  resolve to WRONG cells in the char atlases; the shared `fx_atlas` lacks the `0x15xx/0x17xx/0x1bxx` inferno banks;
  forced onto Blackheart they draw his DARK body palette → additive-of-dark ≈ nothing. ⟹ a truly bright pillar is
  UNRECONSTRUCTABLE from the current tapes. FIX (STAGED for a non-isolated `RetroReceipts-agent` session — worktree
  blocks `reader.rs`): add per-node **is_effect** (node ptr `H+0x180..0x1C0` ∈ effect dir `blk+0x6CE8`..+0x10000,
  `fxprobe.py` recipe) + **blend** (port `computeObjectBlend`); extend the shared FX atlas to the inferno effect banks
  + route is_effect→FX_CID; then RE-RECORD. The JS already parses the 11th/12th/13th objs elements `[…,blend,is_effect,
  drawn]` → once the reader emits them the client consumes them with NO further render change. Proof URLs:
  `play_state.html?frame=716&right=Blackheart` (additive engages, still dim), `…?frame=761&fxown=53` (demon-column preview).

- **2026-08-31 — ⭐ FULL-PASS CAPTURE-UPGRADE SPEC staged (sprite-render, end-to-end grounded) — the ONE-pass fix for
  bright effects.** ⚠ KEY finding (why flags alone don't fix the pillar): TWO effect classes — **3D-class**
  (hitsparks/auras, cat 5-13, `0x0CED` bank) carry color IN the 16-bit texels → is_effect→additive lights them;
  **sprite-class** (Blackheart Inferno, cat 1-4, gfx1 `0x15/17/1bxx`, PAL4+Dat_Pal) render via the caster
  part-assembly, and **Steam's recompile replaced the DC `+0x15c`→`0x0CED` pointer with a small handle** so the
  `blk+0x6CE8` value-test returns **is_effect=0** for them → computeObjectBlend→alpha not additive. ⟹ the pillar's
  brightness rides on the **FX-ATLAS extension (real effect cells + Dat_Pal) + an offline `fxBankMap` binding**
  (steam effect_key→DC fx_sprite), NOT just the flag — and the over-capture (ship gfx1+effect_key+is_effect+cat + the
  self-describing `calib` blob) makes that binding DERIVABLE OFFLINE ⟹ **re-record ONCE.** CAPTURE: objs record
  **20B→32B, APPEND-ONLY** (old tapes still decode) — appends is_effect, blend(nibble 0x11/0x45/0x00), drawn, atimer,
  scaleY, effect_key, depth(H+0x12C=DC+0xE8) — all from the existing 0x1C0 buffer (no extra per-node read). STAGED
  EDITS (explicit before/after): `reader.rs`+`Cargo.toml`→0.3.32 (⚠ non-isolated agent session), `tape_to_gpujson.py`
  + `tape-adapter.mjs` (this worktree; route is_effect→FX_CID), NO render change (sprite-client/gpu already consume).
  FX-ATLAS bake = LIVE capture on the maplecast box (`MAPLECAST_DUMP_EFFECTS`+`MAPLECAST_PARTDUMP` → decode_effects /
  build_replica_effects_atlas / rip_gfx2_assembly --realparts → scp, never commit). ⚠ sh4-re re-confirm at build:
  Steam H+0x12C=DC+0xE8 depth; the `blk+0x6CE8` value-test cross-build behavior for the Inferno node. VERIFY gate =
  `webgpu-test.html` DIFF tint (pillar region yellow=match), not eyeball. Execution spans 3 repos + 1 re-record.

- **2026-08-31 — ⭐ DECISION (Tris): finish PATH A to its FULLEST extent, THEN go PATH B.** Path A = state→canvas
  render with real extracted assets (the pragmatic real-match path; the atlas = a one-time asset library, not per-tape
  work). Complete it fully — (1) effect wire = the capture upgrade (32B objs record) + FX-atlas extension → bright
  effects/pillar (in progress; gated on the blk/palette-RAM verification which may shrink the bake); (2) real HUD
  overlays = assemble the already-captured list-0x0B bank (super meter/TIME/combo) into real sprites, replacing the
  placeholder gradient; (3) stage Option-A byte-exact camera (fixes the pink-decal framing + tightens the stage);
  (4) byte-exact ordering (`+0x31` sub-order if a gap remains). THEN Path B = capture Steam's own D3D11 render stream
  + build a browser renderer for it (true pixel-perfect, no baking ever — but a from-scratch renderer). Path A first.

- **2026-08-31 — ⭐ SIMPLIFICATION (Tris's "is it in blk?" instinct was right): the bright pillar needs NO re-record
  and (probably) NO live bake — it's a RENDER bug + offline atlas, not a capture gap.** Verification (sprite-render,
  grounded): (1) **PALETTE = OFFLINE-extractable, NOT in blk** — the asset image (parts+palettes) is a separate 32MiB
  region `arena+0x8400000` (never rolls back); effect sub-palettes are in the char DatPal at the effect offsets
  (>0x600: Cable ~0x700, Sentinel ~0xd00, Storm ~0x1200), read by `rip_gfx2_assembly.py --pal`. ⟹ "Inferno draws dark"
  = a RENDER bug: the emitter used body pal row 0 instead of the **per-part pal row** in the GFX2 record `+4` field
  `(flags>>4)` (offline data the rip already extracts). "DatPal≠rendered palette" resolves: base=offline DatPal,
  runtime tint (flash/glow) already in the tape flash/glow columns. (2) **ATLAS decoupled from the re-record** — cells+
  palette are static per-match ATLAS data, rebuilt anytime, NOT tape data. The 0.3.32 reader upgrade ships only the
  per-object WIRE (is_effect/blend/depth) = a polish, NOT a pillar blocker. (3) **Cell bake GATED on an offline test**
  — `rip_gfx2_assembly.py` on PL35 sel 0x260 WITHOUT `--realparts`; if the 8 inferno parts decode coherent (single-tile
  → likely) NO live bake. ⚠ ONLY genuine live-only case (CONFIRMED): **multi-tile** GFX1 parts (~86%) whose LZSS
  back-refs index the runtime scratch residue `0x0CE60000` absent from the static file (disasm `loc_8c032854`) — only
  if sel 0x260 is multi-tile. ⟹ IN-WORKTREE PATH (no re-record): offline-decode-test → render fix (per-part pal row) →
  extend the FX atlas offline → additive via a gfx1 heuristic → render the CURRENT tape's pillar. ⚠ sh4-re at build:
  Steam palette base H+0x1B8 vs H+0x1A8; whether sel 0x260 is single-tile.

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
