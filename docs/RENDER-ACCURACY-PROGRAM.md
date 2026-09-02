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
- ⚠ **PROD MOVED 2026-09-01.** `nobd.net` / `play.nobd.net` and the whole arcade stack
  (`rr-server`, `nobd-web`, `maplecast-*`, SurrealDB, the Discord bots) now run on **rise3
  `15.204.141.58`** (`ubuntu@`, key `~/.ssh/ovh_maplecast`, passwordless sudo). rise3 is both
  prod AND the build box. `149.28.44.118` (Vultr, `flycast-inputserver-nyc`) is still powered on
  and still running its own copy of that stack, but it is **no longer the origin** — do not
  treat it as prod. Architecture SSOT: forgily-creations `plans/rise3_handover.md` section 0 (copy `~/HANDOVER.md` on rise3).
- Oracle-tracing instance: `flycast-36g-traced` exists on **both** boxes (`/opt/maplecast/`).
  `maplecast-headless.service` is LIVE-but-idle on `149.28.44.118` and **masked** on rise3
  (which runs `maplecast-flycast.service` instead). ⚠ NEVER disturb a live service or
  wager/tape data on either box — isolated instances only.
- Build box: rise3 **`ubuntu@15.204.141.58`** key `~/.ssh/ovh_maplecast`, 24 cores; holds
  `~/src/maplecast-flycast` + `~/roms/mvc2.gdi`. *(mem: rr-flycast-resim-confirmed-tape)*

### C. The KB — `re_kb` (SurrealDB, namespace `re`). RE knowledge graph; query, don't re-derive.
**On rise3** (`127.0.0.1:8000`) — that copy is **AUTHORITATIVE** (settled 2026-09-02). A stale
copy still runs on `149.28.44.118`; read it if you must, never write to it.

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
  `149.28.44.118:/opt/rr-server/gamestates/` (that box was prod at the time; **since 2026-09-01
  pull tapes from rise3** `ubuntu@15.204.141.58:/opt/rr-server/gamestates/`) → the confirmed-input replay HANDLED it: roster exact, coherent
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
  65.109.77.178 (Hetzner) was prod for forgily at the time. **SUPERSEDED 2026-09-01: rise3 is now
  prod for everything — forgily AND the whole nobd/arcade stack — and dev0ps is a frozen
  rollback standby that runs no maplecast.** The "rise3 NOT prod yet" caveat below is stale. CONFIRMED GO for the headless flycast resim: **no GPU needed** (NO_REND
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

- **2026-08-31 — both Tris steers CHECKED (sprite-render): (a) webgpu-test.html cockpit has NO reusable tape-effect
  fix; (b) the REAL pillar sids ARE multi-tile → the live bake IS necessary; (c) the ?fxown HACK is REMOVED (data
  fxBankMap).** (a) `maplecast-flycast/web/webgpu-test.html` is the LIVE TA-mirror renderer — its `_fxDecode` reads
  effect texels from the WIRE's VRAM (which the tape lacks); FX_CID is skipped on the bridge; the state/emitter path
  imports the SAME SpriteClient/knobs `play_state.html` uses. NO hidden state-path effect fix (cited :613,843-850,
  1030,1055,1183). (b) The ACTUAL pillar demon sids **0x3d(64×64)/0x3e(16×32)/0x3f(32×32)** (+0x30/0x31/0x28/0x2a/
  0x2c0/0x2d3/0x2da/0x64) are single-PART but that part is a MULTI-TILE block whose LZSS back-refs underflow the
  runtime scratch `0x0CE60000` → offline = approximate/recognizable, NOT pixel-faithful ⟹ the live `MAPLECAST_PARTDUMP`
  bake IS required. Tris's "separate sids might be single-tile" = FALSIFIED per-sid. (c) The demons are genuinely
  OWNERLESS global effects — gfx1 bank is NOT char-specific (0x15→{42,44,53}, 0x17→{49,53}, 0x1b→{20,42,44}) and the
  9 ownerless values NEVER appear owner-attributed anywhere in the tape → UNATTRIBUTABLE from the 20B tape; general
  fix = the 0.3.32 reader owner/is_effect WIRE. INTERIM SHIPPED (data, not code): a per-tape `fxBankMap` (9 values→cid
  53) in `tape_59601369.json` (gitignored) — `resolveFxAtlas` consumes it → column renders WITHOUT `?fxown` (drawn
  11→33, ownerless→0, additive 33, brightPx +40%). ⟹ PIXEL-PERFECT step = the staged live PL35 PARTDUMP bake (maplecast
  session + Inferno play; the PPM carries the live palette so no pal-row RE needed) → rip `--realparts` → scp → `?v=`
  bump → `webgpu-test.html` DIFF tint = yellow gate.

- **2026-08-31 — DECISIVE effect-layer diagnosis (sprite-render): Storm/Magneto supers RENDER (owner-attributed); the
  inconsistency = the 90% additive-allowlist gap + the ownerless class + multi-tile cells ⟹ COMMIT to the reader
  0.3.32 upgrade + re-record + per-char bakes.** Storm Lightning Storm (fi1451, 35/35 nodes, ALL owner=42 → PL2A,
  CLEAN bright lightning) + Magneto Magnetic Tempest (fi2995, 31/31, ALL owner=44 → PL2C, energy bursts — Tempest is a
  burst-swarm, NOT literal columns) are 100% OWNER-attributed, 0 ownerless, 0 gated → they render (`_supers_montage.png`).
  The ownerless class (owner=255) is specific to Blackheart's demon-swarm + global flashes. ⚠ THE inconsistency source
  (CONFIRMED): the gfx1-bank additive allowlist {0x15,0x17,0x1b} covers only 90% (16,291/17,958) — **1,667 nodes render
  DIM ALPHA** (banks 0x19=1095 Blackheart, 0x16=411 Magneto, 0x0d=136, 0x0b=25); a hand-tuned bank list CANNOT be made
  correct without the real blend (guessing over-brightens alpha effects). This IS the per-frame/per-character "lost
  effect" Tris saw. ⟹ CONFIRMED GENERAL FIX = 3 parts, 2 need the reader wire + RE-RECORD: (a) per-object BLEND byte
  (0.3.32 `computeObjectBlend`) → the dim/bright inconsistency; (b) is_effect + resolved owner (0.3.32) → ownerless
  attribution (kills the per-tape `fxBankMap`); (c) per-char multi-tile PARTDUMP bakes (PL2A/PL2C/PL35…, offline, NO
  reader) → pixel-perfect cells (all super cells are multi-tile). DO NOT hand-expand the additive allowlist. The
  0.3.32 reader edits (staged earlier) are CONFIRMED REQUIRED, not optional.

- **2026-08-31 — 0.3.32 REAL-WIRE VERIFIED on a live ranked tape (match 59607511): attribution WIN, additive
  assumption CORRECTED.** First 32B ranked capture (VERSION 0.3.32, recBytes=32, 18,647 effect nodes). (a) **OWNER
  attribution EXCELLENT — 99.6%** (owner H+0x28), ownerless-dropped=0 on both rendered supers (Storm fi2205, Sentinel
  fi3679) — the reader owner field fixes the drop for owned effects. ⚠ MATCH-DEPENDENT: ownerless-GLOBAL effects
  (Blackheart Inferno demons) still ship owner=255 (the reader kept H+0x28, added NO global-effect resolution) →
  still need the allowlist/fxBankMap; this roster had none. (b) **blend byte = 80% opaque / 20% alpha / 0% ADDITIVE**;
  **is_effect=1 is 0.0%** (the `blk+0x6CE8` value-test is DEAD on Steam sprite-class — the recompile handle ≠ 0x0CED
  ptr) so `computeObjectBlend` never returns additive. ⟹ ⚠⚠ PLAN CORRECTION: the reader blend byte CANNOT supply
  additive brightness — per-object additive is a RUNTIME PVR register (`0x8C2AA4C4`) absent from Steam RAM; NO reader
  field delivers it. Additive stays the gfx1-bank ALLOWLIST heuristic (kept as an override in `effectBlendByte`) — the
  definitional ceiling of reconstruct-from-state; only Track-B real-TA gives exact per-object additive. FORTUNATELY
  additive-vs-opaque is visually IMPERCEPTIBLE over dark backgrounds (A/B brightPx within 0.5%), and the reader marks
  the big energy banks (0x17=10,162) OPAQUE=bright → the reader byte's real value = (i) the opaque/alpha split that
  KILLS the dim-flicker + (ii) the 99.6% attribution. (c) CELLS still approximate (Storm garbles, Sentinel clean) →
  per-char PARTDUMP bakes still required. 20B tapes re-verified unchanged. NET: 0.3.32 delivers bright+attributed+
  consistent effects (attribution + opaque/alpha); additive is a permanent (imperceptible) heuristic; cells = the
  last bake step. URLs: `play_state.html?tape=./tape.json&frame=` 2205 (Storm) / 3679 (Sentinel) / 403 (Magneto).

- **2026-08-31 — Sentinel drone palette FIXED (Tris-judged GOOD live).** Owned solid satellites
  (drones/capes/projectiles) now inherit the owner's costume (`sprite-client.mjs` emitAssembly passes
  `osl.costume` → costume-LUT bank `bodyBank+costume*8`), so they match the body instead of the RGB-baked
  default (bank 0 = purple). Commit 2f7a807. ⚠ METHOD NOTE: the agent's first montage used a mismatched
  frame — `frame=N` in the harnesses/URL is a ROW INDEX (`applyFrame(fi)=this.frames[fi]`), while objframes
  are keyed by the frame COUNTER (starts 1175; row index = counter−1175). Verify renders at the right index.
- **2026-08-31 — REMAINING GAP TO PIXEL-PERFECT (Path A), grounded:** (1) **CHOPPY** = online rollback smear
  (~2% predicted-then-corrected teleports) — exact fix = reader 0.3.33 confirmed-only capture (needs re-record);
  interim = render-side de-jitter. (2) **HIT/SPARK EFFECTS** = multi-tile cells garble (offline-decode dead-end →
  per-char PARTDUMP bakes) + ownerless globals (owner=255) dropped unless uniquely attributable. (3) **HUD** =
  ALREADY BUILT (hud-client/hud-pvr2, real portraits+FONT.BIN+VRAM in `hud/`); if not showing it's a bug not a
  build. (4) **CELLS** = the recurring per-char PARTDUMP bake. Two non-isolated levers: reader 0.3.33 (choppy+HUD
  list-0x0B+ownerless, one capture) and the maplecast PARTDUMP bakes (cells). Render-side items doable in-worktree.

- **2026-08-31 — HUD OVERLAYS (TIME badge / LEVEL-hyper gauge / name plates) MISSING = top-band-only capture
  (Tris-diagnosed, code-confirmed).** The real HUD = 48 list-0x0B nodes, ALL dumped (`replay-kit/hud_bank_dump.json`
  + `hud_bank/*.bin` via `hud_bankdump.py`) — the ASSETS are complete. But the RENDER is driven by a pvr2 draw-FIFO
  snapshot (`hud/hud_quads.json`, source "maplecast _hud_cap_def hudq_tail.bin", 104 quads, y-span **44–112 only**) —
  the TOP BAND (life bars) alone. The center ∞TIME (x~320,y~30), the bottom LEVEL/hyper gauge (y~440), and clean
  name plates are drawn in the SAME pvr2 HUD pass but were NOT in that snapshot. `hud-client.mjs:16,134-135` already
  documents it: "NOT in the top-band HUDQ capture … Needs one full-band (BAND_H=480) HUDQ capture with a running
  timer + built meter + active combo." ⟹ can't assemble from the node dump (element screen positions are computed by
  each node's native `update_fn`, NOT stored — `bar_geom`=[0,0,0]); the FIFO capture is the only source of real
  positions. FIX = one **full-band HUD FIFO capture** (maplecast, live, mid-match). No render-side shortcut respects
  render-only-real-assets. CONSOLIDATION — the remaining Path-A ceiling = **2 live-capture sessions**: (A) maplecast →
  full-band HUD capture + per-char PARTDUMP cell bakes (two birds); (B) RetroReceipts-agent → reader 0.3.33 (exact
  choppy confirmed-capture + the 68 ownerless effects). Both non-isolated; this worktree is fenced out of both.

- **2026-08-31 — HUD overlays are a CAPTURE dependency, NOT a render-side gap (proven; no fabrication).** Attempted
  to assemble the timer/level/name overlays from the dumped Steam bank; FALSIFIED by 3 tests: (1) `hud_bank/*.bin`
  regions are NODE DESCRIPTORS (`{count=1,type=3,bar_geom,ptrs}`), NOT GFX1 cells — the pixels sit behind the gfx ptr
  in LZSS-compressed GFX1 = the SAME `0x0CE60000` scratch-window offline dead-end as body/effect cells. (2) FONT.BIN
  has ONLY `digit_0..9`+`bar_white` — no letters, no ∞ glyph → text LABELS uncomposable from font. (3) decodable
  `hud_vram.bin` is the top band `[0x400000,0x500000)` y≤112 — excludes the bottom LEVEL gauges. ⟹ NO render change
  made (render-only-real-assets). IMPORTANT REFRAME: for a RANKED tape the FUNCTIONAL HUD is ~complete from real
  assets — life bars+health, frame, DM01 portraits, name plates, **timer COUNTDOWN digits** (ranked TIME is a
  countdown, **∞ is TRAINING-only**), level number, meter fill, combo — the digit overlays are FONT.BIN 2D (in-browser,
  headless-unverifiable → Tris must eyeball). RESIDUAL needing the full-band capture: decorative TIME/LEVEL label+badge
  sprites, per-tape name-plate text (the "SLE" artifact = baked capture-roster name), exact bottom-gauge geometry.
  Capture spec: `rip_hud_quads.py` against a **full-band (BAND_H=480)** HUD TA capture mid-match (running timer, built
  meter, active combo; ∞ badge for training tapes) — same method that baked the top-band bars, real texAddrs+coords.

- **2026-09-01 — capture-session findings (maplecast `_capture_2026_09_01/FINDINGS-2026-09-01.md`), incl. a
  CORRECTION to my HUD diagnosis.** (1) ⚠ **CORRECTION:** the earlier "HUD overlays missing = top-band BAND cull"
  diagnosis is WRONG. The default cull keeps `cy<120 OR cy>=420`, so the TIME badge + bottom gauges ALREADY survive
  it — `BAND_H=480`/`TOPY` is a non-fix. The real reason the deployed `hud_quads.json` is top-band-only is the
  **capture game-STATE** (no running timer / built meter / active combo when it was taken) or last-pass-wins across
  STARTRENDER passes. Capture condition = a live match with timer+meter+combo, NOT a band setting. (2) ⚠⚠ **NEW BUG
  — `MAPLECAST_REPLICA_LIVE` corrupts the flycast render**: it force-enables the dynarec hooks and live-patches
  `0x8C034864` (per-part body render) + `0x8C1248CC` (bank12 quad submit) with NO env escape (`maplecast_replica_live.cpp:530-534`).
  3-run bisect confirms: probes+replica-live → sheared HUD / scattered parts; probes−replica-live → clean. INFERRED
  but important: **prod runs replica-live headless → nobody ever saw its picture → this is a candidate ROOT CAUSE for
  the live render-replica "garbling" class.** Log in re_kb; investigate independently. (3) PARTDUMP is superseded —
  use `MAPLECAST_GFX1DUMP` (partDump reads stale mid-match scratch; both clobber the same filenames). Dumps need a
  mirror-WS subscriber or `MAPLECAST_STATELOG=<path>` to fire at 60Hz headless. (4) The clean cell path = decode every
  selector offline from the **full 16MB guest-RAM** region of the replica-live MCRR prefix (`maplecast_replica_live.cpp:580`)
  — no `rsel<512` cap, no pose-grind — gated behind a ~3-line opt-out of finding-2's render patches (needs a rebuild).
  (5) FREE GROUND TRUTH: the attract-mode demo dumped real Magneto/Sentinel/Colossus cells → `C:\dev\shm\_attract_demo_dumps\`
  (validate the offline decoder against these). Status: neither capture taken; both gated on the finding-2 opt-out call.

- **2026-09-01 - PATH B CAPTURE SHIM BUILT (`d3dcap/`), and two Ghidra findings that materially weaken the
  2026-08-31 NO-GO verdict.** (1) CONFIRMED (Ghidra, `FUN_1402b80f0`): the game resolves D3D11 **at runtime**
  via `LoadLibraryA("d3d11.dll")` (string `14095d180`, err `ERR03 : Failed to d3d11.dll Load.`) then calls
  create-device through `FUN_1407fd5de`; arg shape matches `D3D11CreateDeviceAndSwapChain` exactly. Out-params:
  **swapchain -> renderer+0xC8, device -> +0xB8, immediate context -> +0xC0**; HARDWARE driver, feature level
  0xB000, SDK 7. Swapchain desc: **format 0x1C = R8G8B8A8_UNORM**, 60/1, BufferCount 1, RENDER_TARGET_OUTPUT,
  Windowed, SwapEffect DISCARD. (2) The verdict's blocker was "capture implies injection into a DRM'd binary" -
  but **the tray already ships exactly that**: `sync.rs:4200-4278` injects `hook/d3dhook.dll` by
  CreateRemoteThread+LoadLibraryW and already hooks D3D11 palette COPY/COPYSUB in production. Injection is not a
  blocker here, it is an existing capability. (Corrects the handover's "reuse the proven injector": d3dhook.dll
  has **no source in any repo** - it is a prebuilt blob, so the technique is reusable, the code is not.)
  **BUILT (untested against the live game):** `d3dcap/` - an injected DLL that hooks the immediate-context draw
  entry points + `IDXGISwapChain::Present` by patching the **shared vtable** read off our own throwaway device
  (so: no code patched inside Capcom's binary, no game offsets, no Detours). vtable indices CONFIRMED against
  Windows SDK 10.0.26100.0 declaration order (DrawIndexed 12 / Draw 13 / DrawIndexedInstanced 20 /
  DrawInstanced 21; `IDXGISwapChain::Present` 8). F9 dumps ONE frame to `%TEMP%
rcaprame_<n>.ndjson`:
  per draw = kind/counts, topology, VS/PS/input-layout identity, VB+stride+size, IB+format, PS SRV slots 0-3
  with texture w/h/format/mips, **full blend desc**, depth state, render target, viewport. `summarize.py` turns
  that into the A.5 fork answer. This single artifact replaces the RenderDoc spike AND is the capture format's
  foundation. Blend descs alone settle the additive heuristic (`FX_ADDITIVE_BANKS` guess) with ground truth,
  and the texture list tests whether skins survive - both are Path-A dividends even if the fork lands NO-GO.
  **NEXT: live run** (`d3dcap/build.bat` -> `inject.ps1` -> F9 in a real VS match -> `summarize.py`).

- **2026-09-01 - PATH B INSTRUMENTATION (`d3dcap/`) + a CORRECTION TO MY OWN CLAIM. The prior verdict
  (`:528-543`, MT Framework / D3D11 / textured-quad draws) STANDS - do not retract it.** I first wrote
  here that "Steam MvC2 issues ZERO D3D11 draw calls, contradicting the verdict." **That was an
  overreach and is withdrawn.** `steam-d3d11-capture-expert` refuted it with evidence I did not have:
  `Get-Counter '\GPU Engine(*)\Utilization Percentage'` shows **`pid_..._engtype_3d = 9.26%` under the
  game's own PID with every video engine at zero** => something in that process IS rasterizing. The
  verdict is further CORROBORATED by `config.ini` (`RenderingThread=OFF`, `DeferredLighting*`, `SMAA`)
  and by `nativeDX11x64\app_shader\` (the `AppShaderPackage` the Ghidra verdict named).
  **WHAT IS ACTUALLY MEASURED (the honest, narrower claim):** the game issues no draws *through the four
  vtable slots d3dcap patched, on the one context object d3dcap patched*, over ~41,000 frames:
  `Draw/DrawIndexed/DrawIndexedInstanced/DrawInstanced/DrawAuto/both Indirects/Dispatch = 0`,
  `ExecuteCommandList=0`, `CreateDeferredContext=0`, `ClearRenderTargetView=0`, `UpdateSubresource=0`,
  `CopySubresourceRegion=0`, `CopyResource=1` (init only), `Map=3,764,626` at a **dead-constant
  ~100.0/frame** (3-4/frame in the collection shell, stepping to 100 when the arcade title starts).
  **THE HOOK ITSELF IS SOUND (so the zero is a real blind spot, not a broken tool):** presenting
  swapchain HWND `0x3B932370` == the process's `MainWindowHandle`; `config.ini [DISPLAY]
  Resolution=1280x768` matches the swapchain exactly; Present ticks at **60.06fps across 41k frames**;
  `GetImmediateContext` twice returns the same pointer; the displaced originals
  (`DrawIndexed=0x7FFC85144B70`) are owned by **d3d11.dll**; and `Map` (slot 14) DOES fire on that same
  vtable 100x/frame - proving the patch mechanism and the slot numbering are correct.
  **REFUTED HYPOTHESES:** (a) *D3D9 renders it* - NO: `nvd3dumx.dll` (the NVIDIA D3D9 UMD) is absent;
  only `nvwgf2umx.dll` (D3D11 UMD) is loaded. `d3d9.dll` is present only because
  `gameoverlayrenderer64.dll` and `nvspcap64.dll` LoadLibrary it. (b) *another hook wrapped us* - NO,
  originals are genuine d3d11.dll. (c) *the NV12 path is the render path* - NO, video engines idle.
  **THE NV12 READBACK IS A CAPTURE PATH, NOT THE GAME (INFERRED-strong):** the per-frame `Map READ` on a
  `640x1152 R8G8_UNORM` STAGING texture is a byte-exact **NV12 1280x768 GPU->CPU download** (640*2=1280
  B/row; 768+384=1152 rows), and `nvspcap64.dll` (ShadowPlay) + `MFPlat.DLL`/`MFReadWrite.dll` are
  loaded in-process; the init-only `CopyResource` RT->SRV is a capture tool building its conversion
  source. RGB->NV12 with no Draw/Dispatch implies `ID3D11VideoContext::VideoProcessorBlt` - a SEPARATE
  vtable we never patched. ⚠ the earlier "overlay disabled" control does NOT cover this: `nvspcap64` is
  independent of `gameoverlayrenderer64`, and both were loaded in the quoted run.
  **KNOWN BLIND SPOTS IN `d3dcap` (cited):** `dllmain.cpp:336` `hookGameDevice` is a HARD ONE-SHOT, so a
  second device or second swapchain has never been examined (and `14095dbd0` says `mDisplay[i].pSwapChain`
  = an ARRAY); `dllmain.cpp:110` `patch()` verifies the readback ONCE at t=0, never again; the
  `n <= 8` cap at `:264` means we know 8 of 3.76M Maps; `capture.ps1` sleeps 5s before injecting, so
  anything cached at renderer init is missed.
  **LEADING HYPOTHESIS (H1):** draws are submitted via a path that bypasses the patched slots - either
  MT Framework caching the context's hot-path function pointers at init (H1a; vtable hooking can then
  NEVER work on this title), a second device (H1b), or a different context object (H1c).
  **THE DECISIVE, ZERO-BUILD TEST:** read `renderer+0xB8` (device), `+0xC0` (context), `+0xC8` (swapchain)
  out of the LIVE process (rr-agent already does `process_vm_read` on it) and compare to what d3dcap
  logged (`device=0x0687EC90`, `ctx=0x39587838`). Equal => H1b/H1c dead, it is H1a/reversion.
  Different => the second device is found instantly.
  **FORK STATUS: UNDECIDED, and it MUST NOT be decided on this data.** The draw-call fork is
  **un-costed, not disproven** - draw/shader/device counts remain unmeasured. The framebuffer fork is
  ~40 lines on the confirmed Present hook (`GetBuffer(0)` -> `CopyResource` to STAGING+CPU_READ -> `Map`
  -> encode) and needs none of the unknowns resolved. ⚠ Tris's call, and the tradeoff is unchanged:
  framebuffer = Steam's real pixels shipping now but **skins impossible**; draw-call = skins survive at
  an unknown cost. Do not let "the one that works today" decide a product requirement by default.
  Also corrects the handover's "reuse the proven injector `hook/d3dhook.dll`": that DLL is a prebuilt
  blob with NO SOURCE in any repo - the technique is reusable, the code is not.

- **2026-09-01 - ROOT CAUSE FOUND: the D3D11 context's dispatch table is REWRITTEN at runtime, so
  vtable patching CANNOT hold on this title. Both earlier claims are resolved; neither was right.**
  Probe 1 (in-process, addresses rebased off the live module) settled targeting: `renderer` =
  `*(0x142EBD8F0)` = `0x29B79B20`; **`renderer+0xC0` (context) = `0x39592FC8` == the exact pointer
  d3dcap patched** => the hook was on the right object all along, and `renderer+0xB8` (device) matches
  the censused device too. So "we hooked a decoy" is DEAD.
  **THE MECHANISM (CONFIRMED by re-verification across a run):** `[verify] ctx vtable slot12 still
  ours=1` on the FIRST check, then `ours=0` on every subsequent check. Something restores the original
  `Draw`/`DrawIndexed` pointers into the context's inline dispatch table (the vtable sits at `ctx+8`,
  heap, per-instance). Our hooks are therefore absent for most of any run, which is exactly why
  `draws=0` was measured while the GPU 3D engine was 9.26% busy. **Hypothesis H5 (silent reversion),
  which the expert flagged as "not yet refuted, cheap to kill", is CONFIRMED.**
  ⚠ **This makes vtable patching UNSAFE here, not merely ineffective:** after a rewrite, the originals
  we saved may not match what d3d11 reinstalled, so forwarding through them can call a stale pointer.
  A game crash was observed on the probe run. **Do not ship or reuse the vtable-patch approach on this
  title.** (The DXGI `Present` patch is the exception and IS stable - `IDXGISwapChain`'s vtable lives in
  `dxgi.dll .rdata`, is shared, and has held across 41k+ frames.)
  **ALSO CONFIRMED this run:** exactly 1 device + 1 swapchain (no hidden second of either);
  `CreateDeferredContext` never called; the context DOES expose `ID3D11VideoContext`
  (`vt=0x7FFC851C2090`) = the ShadowPlay/Media-Foundation NV12 readback path, not the game's render;
  `gateA (renderer+0x38)` is set in ~14% of 2.5k samples, so the executor is NOT permanently skipped;
  the nDraw queue read at `*(0x142EF0AB0)+0x1E0080` was flat 0 - UNRESOLVED, likely a rebasing or
  wrong-global issue given the exe is packed, NOT yet evidence the queue is idle.
  **CONSEQUENCE FOR PATH B:** the draw inventory is still UNMEASURED. To get it, hooks must be INLINE
  trampolines on the d3d11.dll draw functions themselves (they cannot be undone by a table rewrite), or
  the capture must come from RenderDoc, which wraps the device from creation and is immune to all of
  this. **The FRAMEBUFFER path, by contrast, needs only the DXGI Present hook that is already proven
  stable** - `GetBuffer(0)` -> `CopyResource` to a STAGING+CPU_READ texture -> `Map` -> encode.
  ⚠ FORK STILL UNDECIDED AND STILL TRIS'S CALL: framebuffer = Steam's real pixels, available now,
  **skins impossible**; draw-call = skins survive, cost still unknown.
  **ALSO CORRECTED (senior-re-generalist, full disassembly):** `FUN_140620F10` contains **ZERO indirect
  calls** - it is a game-side software display list (16 layers, `0x2f4d0`..`0x324d0`, stride `0x300`),
  three layers above any GPU call; `FUN_1406129F0`/`FUN_140612F70` are ONE function that does GFX2
  piece-list quad assembly with sin/cos LUTs and **performs no decompression at all**. The
  `:531-532` clause "decompress twiddled 4bpp parts -> upload to D3D11 textures -> issue textured-quad
  D3D11 draws" was an INFERENCE presented as a traced call chain and is **FALSE for those functions**;
  where texture decode actually lives is **UNLOCATED - do not guess**. The real D3D11 executor is
  `FUN_1402B6F30` (Draw at vtable 0x68, DrawIndexed 0x60, Map 0x70 - all on the same object we hooked),
  called from `FUN_1402B6A50` = `IRender::flip`, with Present at `0x1402B6BBD`. Same correction is
  owed in `docs/RENDER-PIPELINE-HANDOVER.md` and `docs/REPLAY-ENGINE-DESIGN.md:113`.

- **2026-09-01 - PATH B CAPTURE WORKS. Both halves proven on one run, with the fix that mattered:
  INLINE (MinHook) hooks instead of vtable patches.** After the dispatch-table-rewrite root cause
  (previous entry), ALL context vtable patching was removed from `d3dcap/` and replaced with MinHook
  trampolines on the d3d11.dll draw functions themselves - the game rewriting its context table puts
  those SAME addresses back, so inline hooks survive what vtable patches did not.
  **DRAW-CALL HALF - MEASURED AT LAST (the number Path B has never had):** over ~4,800 frames of live
  training-mode play, `Draw` (NON-indexed) fires at **~750 per frame** (3,362,283 by frame 4800) with
  `DrawIndexed` at only ~2/frame (50,695 total) and `DrawIndexedInstanced`/`DrawInstanced` at **0**.
  ⟹ the 2D scene is submitted as **unbatched non-indexed draws**, almost certainly 4-vertex quads.
  Bounded, order-hundreds-per-frame, single draw kind = the tractable shape for a browser re-render.
  **PROBE 2 ALSO CAME ALIVE:** the nDraw command queue (`*(0x142EF0AB0)+0x1E0080`) is churning, up to
  **90,040 bytes**, and `gateA (renderer+0x38)` fires ~20% of samples. The earlier flat-zero reading was
  a menu/idle artefact, NOT a bad address - the RE's queue layout is CONFIRMED live.
  **FRAMEBUFFER HALF - SHIPPING QUALITY NOW:** `GetBuffer(0)` -> STAGING copy -> `Map` -> BMP, taken
  BEFORE Present (SwapEffect=DISCARD leaves the backbuffer undefined after). Output is Steam's real
  1280x768 R8G8B8A8 backbuffer, 3.75 MB/frame, auto-captured every 8s to `%TEMP%\rrcap\shot_*.bmp`.
  Verified visually: a real Magneto-vs-Cable training frame, full HUD, correct stage, correct
  pillarboxing. This is the "faithful FIXED VIDEO" path from the 2026-08-31 product decision, and it is
  now real rather than scoped.
  **WHAT THIS SETTLES AND WHAT IT DOES NOT.** Settled: Path B is viable; the capture mechanism is
  solved; the draw count is finally known. NOT settled: what each of those ~750 draws IS - topology,
  vertex layout, bound texture, blend state - which is the remaining input to the fork. Next step is
  the per-draw inventory (the original `frame_*.ndjson` + `summarize.py`), now re-pointed at the INLINE
  hooks that actually fire. ⚠ FORK REMAINS TRIS'S CALL: framebuffer = Steam's real pixels, working
  today, **skins impossible**; draw-call = skins survive, and its cost is now looking affordable rather
  than unknown.
  **TOOLING NOTE:** `d3dcap/` builds against MinHook (`vcpkg install minhook:x64-windows-static`, /MT).
  The ONLY vtable still patched is `IDXGISwapChain::Present` (dxgi.dll .rdata, shared, stable across
  41k+ frames). RenderDoc is now installed on the dev box as the independent cross-check.

- **2026-09-01 - THE FORK IS ANSWERED BY MEASUREMENT: the DRAW-CALL re-render is VIABLE **and skins
  survive**. Per-draw inventory captured live on gameplay frames, every draw attributed to a Ghidra
  call site.** Method: inline (MinHook) draw hooks now record a full per-draw state dump to
  `frame_<n>.ndjson` AND a `shot_<n>.bmp` of the SAME frame, so every inventory is paired with the
  picture it produced. Each record carries `ret` = the game return address rebased to 0x140000000.
  **CALL-SITE ATTRIBUTION CONFIRMS THE DISASSEMBLY TO THE BYTE:** 649 of 653 gameplay draws return to
  **`0x1402B72F4`** = the instruction after the call at **`0x1402B72F0`**, which the RE named as Draw
  site #1 inside **`FUN_1402B6F30`** (the D3D11 command executor). Also seen: `0x1402B7183`
  (->`0x1402B717F`, DrawIndexed site #1) and `0x1402B7649` (->`0x1402B7645`, Draw site #2). The only
  other sites are in a `0x7FFC...` module (overlay/ShadowPlay), not the game. ⟹ **ONE game code path
  produces essentially the entire scene.**
  **GEOMETRY (measured, gameplay frame 5275 = a 22-hit combo mid-super):** 653 draws; **one shared
  2 MiB DYNAMIC vertex buffer** (`0x39AB7E60`, 2,097,152 bytes -- this is the same 2 MB buffer seen
  being `Map`'d READ_WRITE every frame, i.e. the per-frame VB upload); **stride = 40 bytes** on 99% of
  draws; topology **TRIANGLESTRIP with 4 verts x423** (quads) plus TRIANGLELIST 6-vert x103 and a tail
  of 3/5/8/9/11/12-vert strips. Vertex-layout construction is `FUN_1402BD9A0` = the
  `CreateInputLayout` builder (device vtable +0x58 = index 11; assert string at `0x14095ECA0`;
  semantic-name table at `PTR_s_POSITION_140969f50`).
  **⭐ SKINS SURVIVE - the decisive texture finding.** In-game sprite draws bind **UNCOMPRESSED
  `R8G8B8A8_UNORM`, mips=1** atlases: 256x256 (used by 986 draws in frame 1460), plus 64x64, 128x128,
  512x512. They are per-part uploads, NOT a pre-composited sheet ⟹ a texture-upload intercept can swap
  them, exactly as the current skin hook does for palettes. (By contrast the Collection's own UI/menu
  frames bind BC7/BC1 compressed art -- a different pipeline, irrelevant to the arcade surface.)
  **⭐ BLEND GROUND TRUTH - retires the `FX_ADDITIVE_BANKS` heuristic (a Path-A dividend regardless of
  fork).** Only two states matter on the game call site: `SRC_ALPHA x INV_SRC_ALPHA` x586 (normal) and
  **`SRC_ALPHA x ONE` x53 = ADDITIVE**. Depth on the sprite path: `en=1 func=4 write=0`.
  Per-object additive is therefore DIRECTLY OBSERVABLE at the API, not a guess from gfx1 bank ids.
  **SCENE STRUCTURE:** the arcade image is rendered into an OFFSCREEN RT and then composited - e.g. the
  character-select frame draws 1250 quads into a `2048x1024 B8G8R8A8` RT at viewport `384,32 1280x960`.
  Frame cost scales with scene: 28 draws (menu) -> 191 (char select UI) -> 653-1300 (gameplay/supers).
  **VERDICT: bounded draw count, ONE call site, ONE vertex format, TWO blend states, uncompressed
  swappable atlases. This is the "re-renderable" branch of the A.5 rubric, not the record-only branch.**
  ⚠ STILL TRIS'S CALL, but the tradeoff has moved: the draw-call fork no longer costs "unknown" - and
  it is the ONLY branch that keeps custom skins. The framebuffer path remains built and working as the
  immediate deliverable / fallback.
  **NOT YET DONE:** the exact 40-byte vertex semantics (declared layout is in `FUN_1402BD9A0`'s
  semantic table; the stronger evidence is a live dump of the VB bytes, not yet taken), and HLSL->WGSL
  for the sprite VS/PS. Neither blocks the decision.

- **2026-09-01 - ⚠ FALSIFIED (maplecast lane, relayed): the `MAPLECAST_REPLICA_LIVE` dynarec-hook
  theory for the in-match render corruption is DEAD. Do not act on it.** The earlier entry in this log
  called it "a candidate ROOT CAUSE for the live render-replica garbling class" (INFERRED). It has been
  disproved by its own author: a `MAPLECAST_NO_ORACLE_HOOK` opt-out was added and rebuilt, the log
  shows **zero hook injections, and it still garbles**. The original "confirmed" 3-run bisect compared
  runs differing by **two** variables, observed by different people on different game content -- a
  textbook false confirm. **The corruption is real; its cause is OPEN.** Best surviving hypothesis
  (UNTESTED): `MAPLECAST_HUD_TA`'s second `ta_parse` racing the DX11 parse.
  **STILL STANDING from that findings doc, and these DO change Path-A plans:** (a) `bakes-RUNBOOK.md`'s
  PARTDUMP recipe reaches only **~11-17% of cells** and **fails silently** (probes gate `rsel<512`,
  atlases use selectors to 4685) -- fix is to pull the full 16 MB RAM from the replica-live prefix and
  decode every selector offline (a working `ram16.bin` was captured, so this is demonstrated, not
  theoretical); (b) use `MAPLECAST_GFX1DUMP`, **not** PARTDUMP -- PARTDUMP reads transient scratch that
  is stale mid-match, and **both write the same filenames**, so enabling both clobbers; (c) dumps do
  not fire without a mirror-WS subscriber -- `MAPLECAST_STATELOG=<path>` is the lever; (d) ⚠ **new:
  `MAX_HUD=256` truncates SILENTLY** (45 of 658 frames in a real capture hit the cap with quads
  dropped), and with the band cull off the collector picks up playfield geometry (only 224/256 quads
  came from the HUD VRAM slab) -- frame selection must reject 256-quad frames and rank on HUD-VRAM
  content. Neither capture is taken yet; that lane owns it.
  **⭐ CROSS-LANE NOTE FROM PATH B (may retire the whole PARTDUMP problem):** `d3dcap/` now dumps the
  sprite atlases straight out of Steam's live D3D11 as **uncompressed R8G8B8A8, mips=1** pages
  (256x256 / 128x128 / 64x64 / 512x512), deduped per frame. If those are the same cell pixels PARTDUMP
  is trying to reach, the `rsel<512` gate, the stale-scratch problem and the LZSS-back-ref-into-
  runtime-scratch dead-end (lesson 4 of the render handover) are all SIDESTEPPED -- Steam has already
  decoded them for us. **Worth one comparison before more effort goes into the flycast bake path.**

- **2026-09-01 - PATH B CAPTURE IS ONE COMMAND, AND SHADER/LAYOUT COVERAGE IS SOLVED via a SUSPENDED
  LAUNCH.** `d3dcap/collect.ps1` is now the single entry point: build -> launch -> inject -> wait
  while you play -> detect the first COMPLETE gameplay frame -> print the analysis -> exit by itself.
  **THE CATCH-22 THAT FORCED IT (both halves observed):** the game creates its D3D11 device very early
  in startup, so (a) injecting after the Windows loader settles is ALREADY TOO LATE - the
  `D3D11CreateDeviceAndSwapChain` hook never fires and shader/input-layout bytecode is unrecoverable
  (`ID3D11VertexShader` has no `GetBytecode`); and (b) injecting the instant the process appears
  CRASHES it - `LoadLibraryW` via `CreateRemoteThread` while the loader is initialising deadlocks the
  process. Both failure modes were reproduced live.
  **SOLUTION (CONFIRMED WORKING): `CREATE_SUSPENDED`.** `launch_suspended.ps1` starts
  `MarvelVsCapcomFightingCollection.exe` directly with CREATE_SUSPENDED (Steam already running,
  `SteamAppId`/`SteamGameId` set so the DRM accepts a direct launch), injects into the quiet process,
  then `ResumeThread`. **The DRM did NOT refuse it.** Result, measured: `[game] LAUNCHED 73624` ->
  `[init] game created device=... ctx=... swapchain=...` -> `Present hooked=1` ->
  **`captured at creation: inputLayouts=32 VS=32 PS=116`** (previously 0). The `.cso` bytecode and the
  `D3D11_INPUT_ELEMENT_DESC[]` for every layout are now on disk -- the authoritative vertex format,
  no value-range guessing.
  **⚠ BUG FOUND AND FIXED IN THE SAME RUN:** `MH_Initialize FAILED` -> draw hooks never installed ->
  every inventory read `0 draws`. Cause: the worker calls `MH_Initialize()` to hook the device-creation
  export, then `installDrawHooks` calls it AGAIN and gets `MH_ERROR_ALREADY_INITIALIZED`, which the
  code treated as fatal. Now accepts OK **or** ALREADY_INITIALIZED. (The creation hooks were unaffected
  because they never call MH_Initialize - which is exactly why coverage worked while draws did not.)
  **ALSO IN THIS BUILD (closing the expert's full minimum set in ONE pass rather than one per run):**
  `ClearRenderTargetView`/`ClearDepthStencilView` interleaved in draw order (an uncleared intermediate
  RT carries last frame's contents, so a replay starting black is wrong); 8 slots everywhere (SRVs,
  samplers, VS **and** PS constant buffers, VB streams 1-3, all 8 RTVs) instead of 1-4; the DSV desc;
  blend factor + sample mask (previously computed and discarded); rasterizer + scissor; full
  depth/stencil incl. StencilRef. Plus a crash fix: the texture dump assumed 4 bytes/pixel and walked
  y to Height, which reads ~4x past the end of every BC7/BC1 texture -- it now dumps only uncompressed
  R8G8B8A8/B8G8R8A8 (which is what the arcade atlases are) and skips compressed UI art.
  **ASSET EXTRACTION PROVEN:** live sprite atlases pulled straight from Steam's D3D11 as uncompressed
  RGBA with real alpha (a 256x256 char-select text page verified visually; one 256x256 page served 972
  of 1216 draws in a gameplay frame). ⚠ note they are stored VERTICALLY FLIPPED - that is the V
  orientation the WebGPU port must match.
  **REMAINING:** re-run `collect.ps1` with the MinHook fix to get draws + the authoritative layout
  decode in one pass; then HLSL->WGSL for the 2-3 hot shaders (one VS+PS pair covered 1061 of 1267
  draws). `D3DCOMPILER_43.dll` is already loaded in-process, so `D3DDisassemble`/`D3DReflect` are free.

- **2026-09-01 - ⭐⭐ FULL IN-MATCH CAPTURE ACHIEVED, and the sprite pipeline is INDEXED + 256x1
  PALETTE LUT -- a Steam skin swap is 16 RGBA values.** One `collect.ps1` run, frame 4828: 1252 draws,
  **189 distinct textures**, coverage **8/8 input layouts, 8/8 VS, 16/16 PS**, disjointness gate PASSED
  (1237 ranges, 0 overlaps, 83% density). Every gate green on a real match frame.
  **⭐ THE PALETTE FINDING (CONFIRMED, dumped and inspected):** sprite draws bind a `256x1
  R8G8B8A8_UNORM` texture to **PS slot 1** (110 draws on one, 39 on another, 21 on a third). Dumped and
  decoded: **256 entries, only 16 UNIQUE COLOURS**, index 0 = `(0,0,0,0)` fully transparent, all others
  alpha 255. Sixteen colours = **4bpp indexed sprites**, i.e. the SAME palette model MvC2 uses on
  DC/CPS2. The observed table is Magneto's ((204,119,221),(136,68,153),(102,34,119) purples + skin
  tones + yellow). ⟹ **Steam's sprite path = indexed page in slot 0 + palette LUT in slot 1, resolved
  in the PS.** A skin swap on Path B is therefore writing **16 RGBA values into a 256x1 texture** --
  no atlas rebuild, no re-bake -- and it maps directly onto the existing palette-based skin system.
  This is a much cheaper skin story than "patch the texture upload".
  **⭐ VERTEX FORMAT SETTLED FROM BYTECODE, not from value ranges** (`d3dcap/inspect_shader.py`, new:
  parses the DXBC ISGN/OSGN chunks). Layout `stride=40`: `POSITION float4 @+0`, `NORMAL float2 @+16`,
  `TANGENT unorm4 @+24`, `BINORMAL unorm4 @+28`, `TEXCOORD float2 @+32`. The dominant VS's input
  signature says what is actually CONSUMED: **POSITION read `xyz` only** (the `.w` denormal is
  ignored), **NORMAL read mask is EMPTY - NEVER READ**, TANGENT/BINORMAL/TEXCOORD fully read.
  ⟹ the real sprite vertex is **position.xyz + two RGBA8 vertex colours + uv**, with **8 DEAD BYTES at
  +16** the game never initialises. ⚠ That is why decoded NORMALs show `(nan,nan)` and `-2.5e+38` in
  some frames and clean values in others - it is uninitialised buffer memory, NOT a decode bug and NOT
  a capture bug. A port must IGNORE that field. (Exactly the trap value-range guessing would have hit.)
  **SCENE PROFILE for the kept frame:** blend is `SRC_ALPHA x INV_SRC_ALPHA` x1225 vs additive
  `SRC_ALPHA x ONE` x7 -- ⚠ note this is the INVERSE of character select (1006 additive), so the
  additive/alpha ratio is SCENE-DEPENDENT and no single frame settles the additive question. Depth:
  `en=1 func=4(LESS_EQUAL)` with stencil enabled on 980 draws, `write=0` on 245. 1228 of 1245 draws go
  into the `2048x1024 B8G8R8A8` offscreen RT at viewport `(384,32,1280,960)`, then a 9-pass chain down
  to the 1280x768 backbuffer. Clears captured in order: depth to `1.0`, intermediates to `[0,0,0,1]`,
  the scene RT to `[0,0,0,0]`.
  **TOOLING NOW ONE COMMAND, WITH GATES THAT REFUSE BAD DATA:** `collect.ps1` = build -> CREATE_SUSPENDED
  launch -> inject pre-execution -> wait -> keep recording 45s after the first match frame -> keep the
  RICHEST frame -> print the analysis -> exit. Gate 0 rejects menu/char-select frames by distinct
  texture count (measured: menus 9-30, char select 21-24, in-match 96-298 - draw count CANNOT separate
  them, both render ~1200 draws into the same offscreen RT). Gate 1 = VB-range disjointness. Gate 2 =
  creation-time coverage. Frames failing any gate are skipped, never analysed.
  **⚠ FIXED THIS SESSION (my bugs, each cost a run):** double `MH_Initialize` returning
  ALREADY_INITIALIZED treated as fatal (draw hooks never installed, every inventory read 0 draws);
  a texture-reference LEAK on two early-return paths in `dumpCapturedBuffers` that exhausted the
  device and crashed the game on character select; a BC7 out-of-bounds read in the texture dump
  (block-compressed data has ceil(h/4) rows, not h); `summarize.py` KeyError on the new Clear records.
  **NEXT:** HLSL->WGSL for the 2-3 hot shaders (one VS+PS pair covers 975 of 1252 draws;
  `D3DCOMPILER_43.dll` is in-process so `D3DDisassemble`/`D3DReflect` are free), then a scene-RT-only
  pixel diff via `gsta-verification-harness` BEFORE attempting the post/bloom chain.

- **2026-09-01 - ⚠ CORRECTION TO MY OWN PALETTE CLAIM + THE SHADERS ARE PORTED. The previous entry
  said "a Steam skin swap is 16 RGBA values". That is WRONG for the main character path.** Disassembly
  of the actual bytecode (fxc `/dumpbin`, shaders captured at creation time) shows Steam runs **TWO**
  sprite paths, and the palette one is the minority:
  * **`ps_000000006420CEB8` — DIRECT RGBA, 975 of 1252 draws.** Binds `t0` ONLY. Slot-0 textures are
    `256x256` (631 draws) and `128x128` (347) `R8G8B8A8_UNORM`. **This is what draws the characters.**
    A skin swap here means replacing ATLAS PIXELS, not a palette write.
  * **`ps_00000000642D7378` — INDEXED + PALETTE, 152 draws.** `idx = sample(t0).x` on a `32x32`
    **`R8_UNORM` (fmt 61)** index texture, then `pal = sample(t1, vec2(idx,0))` on the `256x1` palette
    with a **POINT** sampler (`SSPoint`, s1). The palette really does hold 16 entries + transparent
    index 0 (4bpp, the DC/CPS2 model) — but it recolours SMALL EFFECTS, not fighters.
  ⟹ the palette finding stands as a mechanism; my claim about what it covers did not. Skins on Path B
  are a texture-upload intercept on the RGBA pages, with the palette path as a bonus for effects.
  **⭐ THE FULL SPRITE PIPELINE, PORTED LITERALLY** (`d3dcap/replay/sprite.wgsl`, new). Vertex shader
  (`vs_0000000039E22A38`, 16 instrs) is `pos.xyz -> mul(fWorld 3x4, float4(pos,1)) -> mul(fViewProj
  4x4)`, passing colour0/colour1/uv through: positions are **MODEL space**, both matrices come from
  constant buffers we capture (`CBWorld` cb0 48B, `CBViewProjection` cb1). Pixel shader is
  `rgb = tex.rgb * colour0.rgb + colour1.rgb` with **alpha taken from the VERTEX, not the texture**,
  and an alpha-test discard.
  **⭐ TWO RUNTIME CONSTANTS SETTLED FROM THE CAPTURED BUFFERS (not assumed):**
  `CBROPTest.fAlphaRef = **0.0**` (the alpha test discards only fully transparent texels) and
  `CBFog.fFogDensity = **0.0**` ⟹ **the fog term in the pixel shader is a NO-OP.** That
  INDEPENDENTLY CONFIRMS `mvc-render-composite-model`'s "**NO fog**" claim, this time from Steam's own
  live constant buffer rather than from the DC disassembly. The WGSL port omits fog on that basis and
  says so in a comment.
  **NEW TOOL:** `d3dcap/inspect_shader.py` parses the DXBC ISGN/OSGN chunks to report what a shader
  DECLARES vs what it actually READS (per-component mask). That is what proved `NORMAL`'s read mask is
  empty, explaining the NaNs as uninitialised-by-design rather than a capture bug.
  ⚠ **The WGSL is UNVALIDATED** — hand-translated from the disassembly, not yet compiled or pixel
  diffed. `steam-d3d11-capture-expert` + `mvc2-sprite-render-expert` engaged to review before it is
  trusted. Next gate remains a **scene-RT-only** diff (draws into the `2048x1024` offscreen RT at
  viewport `384,32,1280,960`), NOT the final backbuffer, which has been through the bloom chain.

- **2026-09-01 - ⚠⚠ RETRACTION: "fFogDensity = 0 so fog is a no-op" and "fAlphaRef = 0" are NOT
  EVIDENCE. The constant buffers were STALE at snapshot time.** (steam-d3d11-capture-expert, verified
  against the dumped bytes.) I logged both as CONFIRMED from Steam's live constant buffers. They were
  read at Present, and **the post-processing chain reuses the SAME constant-buffer objects and
  overwrites them in place** before that point. Proof: `buf_4828_cb0_*.bin` (CBWorld) is an **exact
  identity** `(1,0,0,0 / 0,1,0,0 / 0,0,1,0)` and `buf_4828_pscb_0000000039744D20.bin`
  (CBViewProjection) is an **exact identity** with `fCameraPos=(-0,-0,-0)`, `fCameraTargetDist=100`,
  `fCameraFarClipLog2=1` -- the canonical FULLSCREEN-QUAD setup used by the post chain (draws
  1230-1251), on the same buffer pointer. But the frame's own vertices decode to e.g.
  `pos=(1070.78, 140.40, -2653.40)`: under an identity view-projection every sprite would be clipped
  away, and they plainly rendered. ⟹ the snapshot describes the BLOOM pass, not the sprite pass.
  **⚠ MY DISJOINTNESS GATE CANNOT CATCH THIS BY CONSTRUCTION** -- it tests vertex-buffer RANGE overlap,
  and a constant buffer is overwritten IN PLACE with no ranges to overlap. Different failure class,
  needs a different gate. (The vertex data itself is fine: draws 5/6/7 occupy 33152..33352,
  33352..33552, 33552..33792 -- contiguous, disjoint, UVs in 0..1.)
  **⟹ The project's "NO fog" finding stands on its ORIGINAL DC-disassembly evidence only. My claim to
  have independently confirmed it from Steam is WITHDRAWN.** The WGSL port must KEEP the fog term and
  bind the real per-draw constants; it is a bit-exact no-op when density really is 0, so keeping it
  costs nothing and removes a silent-failure class we cannot currently rule out.
  **FIX (being implemented): snapshot constant buffers at DRAW time, not at Present** -- shadow them
  via hooked `Map`/`Unmap` and dedupe by content hash. They are tiny (CBWorld 48B, CBFog 80B, largest
  seen 432B), so even undeduped this is under 1 MB/frame.
  **⚠ GENERAL LESSON, worth more than the specific bug:** a Present-time snapshot is only valid for
  resources the frame does not REUSE. It happened to be valid for the 2 MiB vertex buffer (the game
  appends) and is invalid for constant buffers (overwritten per draw). Do not assume a capture point
  generalises across resource types.

- **2026-09-01 - PORT REVIEW: 4 bugs found in `d3dcap/replay/sprite.wgsl` before it was trusted.**
  (The WGSL validates under `naga`, which proves syntax, NOT correctness.) CONFIRMED CORRECT: the
  vertex math instruction-by-instruction incl. left-to-right accumulation order; `NORMAL` omitted (the
  VS declares `v0,v2,v3,v4` -- **there is no `v1`**); alpha from the vertex; discard semantics; and
  **`unorm8x4` byte order needs NO swizzle** (D3D byte0->R and WebGPU byte0->x agree).
  **BUGS:** (1) `fs_indexed` was paired with the wrong vertex shader -- the 152 indexed draws ALWAYS
  use `vs_0000000063F9C9F8`, a **pass-through with NO constant buffers** that emits only THREE
  varyings, with **uv at TEXCOORD2 (`v3`), not TEXCOORD3**; sharing one VSOut made it sample using
  `worldPos.xy`. (2) The index texture must be **POINT** sampled -- captured `D3D11_SAMPLER_DESC`
  `filter:0` on BOTH s0 and s1 for all 152 draws; linear-filtering a palette INDEX blends indices into
  arbitrary colours. ⚠ root cause: the port trusted the shader's sampler NAME (`SSJackShader`) instead
  of the captured desc -- a name is a binding label, not state. (3) Samplers are **per-draw state**:
  character draws are 933 `filter:21` (LINEAR), 24 `filter:0` (POINT), 16 with `u/v/w:1` = **WRAP**,
  not CLAMP. ⚠ WebGPU's default `createSampler()` is nearest+clamp, which is right for the indexed path
  and wrong for 933 character draws. (4) A THIRD sprite shader is unported: `ps_00000000642D7078`,
  69 draws, samples `r0.xyzw` and uses **per-texel alpha** (`a = tex.a * colour0.a`) -- 2 lines, takes
  coverage 1127/1252 -> 1196/1252.
  **WEBGPU TRAPS CONFIRMED FROM THE CAPTURE:** DXBC `linear` = **perspective-correct**, which is WGSL's
  DEFAULT -- so specifying nothing is right and must be commented so nobody "fixes" it to
  `@interpolate(linear)` (= noperspective). **No `_SRGB` format anywhere** (scene RT fmt 87, backbuffer
  fmt 28, textures f28) ⟹ linear throughout; a `bgra8unorm-srgb` canvas injects a global gamma error
  that looks "close". Depth NDC is [0,1] in **both** APIs. ⚠ **DSV is `fmt:44` = R24G8_TYPELESS ⟹
  D24_UNORM_S8_UINT**, so use `depth24plus-stencil8`; this **CONFLICTS with the existing depth32float
  fix in sprite-gpu** (tuned for Path A/DC) -- resolve explicitly, do not inherit. Cull is per-draw and
  VARIES (FRONT x870, BACK x183, NONE x172). Blend alpha is `srcA=ONE, dstA=ZERO` -- destination alpha
  is REPLACED, not `one/one-minus-src-alpha`, and the post chain samples that alpha. `writeMask` varies
  (one draw has mask 0). Non-issues: `bfactor` all `[1,1,1,1]`, `smask` all `0xFFFFFFFF`, `nrt`=1,
  scissor disabled on every scene draw. ⚠ **V-flip: no flip is needed at the API level** (both APIs put
  v=0 at the top row) -- our dumped atlases look flipped because of MY BMP WRITER, so fix the dumper,
  not the UVs; flipping UVs would also break the palette lookup, which uses `v = 0.0` literally.
  **STENCIL IS SAFE TO DROP for a scene-RT colour diff:** every scene draw is `sten:0` (245) or
  `sten:1` with **`srmask:0`** (982), and `(ref & 0) vs (buf & 0)` is content-independent. ⚠ INFERRED
  from the read mask, not measured -- `StencilFunc` and the three ops are not yet captured; add them.
  **THE FIRST DIFF, STAGED:** the scene RT `0x766FBCA0` is bound for draws 2..1229 and **never rebound
  in the frame**, so it can be snapshotted in `hkPresent` like the backbuffer -- no pass-boundary hook
  needed. Then **Diff 0 = ONE draw** (draw 5: 5-vert strip, one 256x256 texture, `c0=(145,159,164,255)`)
  to catch winding/cull inversion, UV flip, byte order and blend errors with a signal readable by eye;
  **Diff 1 = draws 2..1229** into 2048x1024 `bgra8unorm` + `depth24plus-stencil8`, clear `[0,0,0,0]`,
  depth 1.0, viewport `(384,32,1280,960)`, diffed against the dumped scene RT **cropped to
  (384,32)-(1664,992)** -- outside that rect is untouched clear and would flatter the number.
  Diff 2 = the post chain vs `shot_*.bmp`, later. ⚠ capture the reference with BOTH overlays disabled.
  Budget ±1 ULP: `mad` fusion is undefined in both APIs.

- **2026-09-01 - ⚠⚠⚠ THE PREMISE WAS INVERTED. The 975 direct-RGBA draws are the 3D STAGE; the 152
  "small effect" INDEXED draws are THE CHARACTERS.** (mvc2-sprite-render-expert, proved three
  independent ways.) I had it backwards in every prior entry today and in the first WGSL port.
  (1) **Spatial:** computing the NDC bbox of every draw in `frame_4828.ndjson` and mapping it through
  `vp=[384,32,1280,960]` into backbuffer space, the draws landing on Sentinel's body are **41 draws,
  ALL `ps_00000000642D7378`, ALL t0 = 32x32 `DXGI_FORMAT_R8_UNORM` (fmt 61)**. Zero RGBA draws are
  centred there. (2) **The textures:** the dumped 256x256 RGBA pages are photographic 3D STAGE art --
  metal pillars, chains, a ship's wheel, sails -- and their alpha is uniformly 255 (which is why that
  shader sets IgnoreTexA). (3) **The palettes:** the 256x1 t1 textures are **4bpp MvC2 CHARACTER
  palettes** -- 15 non-transparent entries with index 0 transparent, every channel a multiple of 0x11
  (ARGB4444 bit-replicated to 8-bit); one holds 240 = **16 banks x 16**, which is literally the shape
  of our `PLxx_lut.json` `banks[]`.
  **⟹ SKINS ARE A PALETTE WRITE AFTER ALL.** My earlier "correction" (that skins need atlas-pixel
  replacement because characters take the RGBA path) is ITSELF WITHDRAWN. `sprite-gpu.mjs
  setSkin(charId, bodyColors16)` already does exactly the right thing; the Steam equivalent is writing
  those 16 RGBA into the first texels of the 256x1 t1 texture. Index byte -> `bank = idx>>4`,
  `entry = idx&15` is precisely our `_idx.png` R/G encoding. Nothing in the skin architecture changes.
  **⚠⚠ CAPTURE BUG THIS EXPOSED — WE HAD ZERO CHARACTER PIXELS.** `isRGBA32()` in `d3dcap/dllmain.cpp`
  accepted only 4-byte RGBA formats, and **144 of the 189 textures bound in frame 4828 are fmt 61
  (R8_UNORM)**. Every character index tile was silently skipped, as was the **256x128 RGBA HUD bank**.
  FIXED: `isDumpableTex()` now also accepts `R8_UNORM` and the row width follows the format.
  ⭐ Side effect worth having: per `mvc-hud-list0b-live-re` the UI sprite bank **cannot be obtained
  offline at all** -- this path now hands it over as flat RGBA, closing a standing blocker in that lane.
  **⭐⭐ STEAM'S RENDERER IS A PVR2 EMULATOR RUNNING FLYCAST'S SHADING SEMANTICS.** All four pixel
  shaders are specialisations of the DX11 macro matrix in
  `maplecast-flycast/core/rend/dx11/dx11_shaders.cpp`: `6420CEB8` = ShadInstr 3 + IgnoreTexA 1 +
  Offset 1 + fog (opaque stage, depth write=1); `642D7078` = same without IgnoreTexA (translucent
  stage, write=0); `642D7378` = + `pp_Palette` (**the characters**, write=0); `643231F8` = no fog
  (**the HUD**, 256x128 bank). Model them as flycast tuples, not as ad-hoc shaders.
  **TWO VERTEX SHADERS, NOT ONE:** the stage uses `vs_0000000039E22A38` (fWorld 3x4 then fViewProj
  4x4); the characters and HUD use `vs_0000000063F9C9F8`, a **pure pass-through with NO constant
  buffers** whose positions are ALREADY IN NDC (measured -0.4042, -0.6375, z 0.98153). My first port
  ran character verts through both matrices. FIXED: two `@vertex` entries, two varying structs (the
  pass-through emits THREE varyings with uv at TEXCOORD2, not four).
  **MEASURED, AND USEFUL BEYOND PATH B:** the characters use only **SEVEN distinct z values** across
  all 152 draws -- one z per body/layer, NOT per part. That directly corroborates the order-key model
  in `mvc-render-composite-model` and tells the emitter it can assign one z per character.
  **V-FLIP SETTLED BY MEASUREMENT:** decoding draw 1056's verts, `v` DECREASES as screen y goes down,
  so the flip is baked into the game's OWN UVs. ⟹ replaying the captured stream: **flip nothing**.
  Harvesting Steam textures into our atlases: **flip at atlas-build time** -- never at upload, never in
  the shader. (Our convention is fixed and load-bearing: `setAtlas`/`setIndexedAtlas` pass
  `flipY:false`, atlas row 0 = sprite top; and the `flipY` vertex attribute at shaderLocation 5 is the
  per-part Y-MIRROR from `flags & 0x8000`, NOT an orientation control -- putting a global flip there
  would collide with mirrored parts.)
  **⚠ PATH A IS **NOT** OBSOLETED -- tell the maplecast lane it is NOT solved.** Steam does not hand us
  uncompressed character pages: characters go through `pp_Palette` (R8 index + 256x1 palette), which is
  **the same PAL4 model Path A already produces**. The LZSS / `0x0CE60000`-scratch dead-end is
  unchanged for OFFLINE extraction; Steam is a second LIVE source, not an offline one. A Steam tile is
  also a single per-part tile (32x32 dominant), whereas a `PLxx.json` entry is a composited
  whole-sprite crop with `dx,dy,wG,hG` -- different granularity and anchoring, **not drop-in**.
  ⭐ What IS genuinely valuable to that lane: Steam R8 tiles are **comparable to `MAPLECAST_PARTDUMP`
  output tile-for-tile**, i.e. an independent second witness for **re_kb/68** (column-pair-major wide-
  part tile order) and **re_kb/66** (sel==0xFF blank records consuming tiledesc slots).
  **RENDERER DECISION (Tris):** build a CLEAN renderer for the Steam stream rather than extending
  either existing one. Justified: `sprite-gpu.mjs` has **no depth buffer at all** and synthesises quads
  from an instance attribute (no geometry input, two hardcoded blend states); `pvr2-renderer.mjs` uses
  **reversed-Z with a log-depth write** (`depthClearValue 0.0`, greater-equal) where Steam is forward-Z,
  clear 1.0, LESS_EQUAL with z straight from the vertex. And we no longer need anyone's reconstructed
  semantics -- we have Steam's own shaders. Both experts engaged on the design.

- **2026-09-01 - ⭐⭐⭐ THE CAPTURE IS COMPLETE. Every input a pixel-accurate replay needs is on disk
  for frame 6108, and all four gates pass.** `d3dcap/replay/frame_6108.pack` (4.4 MB) written by
  `pack_replay.py`.
  **GATE RESULTS:** in-match (234 distinct textures, vs menus 9-30 / char-select 21-24); coverage
  **8/8 input layouts, 8/8 VS, 16/16 PS**; VB-range disjointness **499 ranges, 0 partial overlaps**;
  and texture coverage **224/224 bound textures have pixel dumps** (the packer REFUSES to pack below
  100% -- it rejected two earlier frames for exactly this).
  **⭐ THE STALE-CONSTANT-BUFFER BUG IS DEAD, and the fix was not where I first looked.** Shadowing
  `Map`/`Unmap` captured NOTHING: all 501 draws in frame 4730 reported hash `00000000` while 496 of
  them had constant buffers BOUND. Root cause: `D3D11_USAGE_DEFAULT` constant buffers **cannot be
  Mapped at all** -- the game writes them with **`UpdateSubresource`** (vtable index 48, confirmed
  against the SDK). With that hooked: **69 distinct CB payloads**, and critically **55 DISTINCT WORLD
  MATRICES** with real translations (+5.0, -14.0, -71.0) plus **6 view-projections**. The identity
  matrix now appears on exactly the 31 fullscreen-quad draws where identity is CORRECT, instead of on
  everything. The captured `fViewProj` is a genuine perspective matrix with the translation in ROW 3
  (`[-2437.07, -872.39, 810.36, 812.36]`), which matches the shader's row-major
  `r1.x*cb1[0] + r1.y*cb1[1] + r1.z*cb1[2] + cb1[3]` accumulation exactly.
  **SCENE PROFILE:** 490 of 507 draws into the `2048x1024 B8G8R8A8` offscreen RT at viewport
  `(384,32,1280,960)`; 408 strips + 82 lists -> **3390 triangle-list indices** after the packer's
  strip conversion; state space **4 blend / 4 depth / 4 raster / 7 sampler** (so the pipeline cache is
  ~30 entries, small enough to review exhaustively). **SIX 256x1 palettes** bound at slot 1
  (95/73/50/25/18/11 draws) = six characters on screen. R8 index tiles now dumping at 8x8, 16x16,
  32x16, 32x32, **64x32**.
  **TOOLING BUILT THIS SESSION (`d3dcap/replay/`):** `sprite.wgsl` (Steam's own shaders: 2 vertex
  entries, 4 fragment entries, naga-validated); `state.mjs` (D3D11->WebGPU translation tables,
  exercised against the real captured tuples -- BORDER address mode correctly THROWS rather than
  silently becoming clamp); `pack_replay.py` (offline packer: strips->lists, drops the post chain,
  content-hashes shaders/layouts so nothing is keyed on a runtime pointer that rots across launches,
  and asserts 100% texture coverage); `inspect_shader.py` (DXBC ISGN read masks).
  ⚠ **THE STRIP TRAP, worth remembering:** 408 of 490 scene draws are TRIANGLESTRIP and adjacent
  character quads share both state and contiguous VB ranges -- so "merge adjacent draws with equal
  state" FUSES two strips and manufactures bridging triangles. It fails silently and looks plausible.
  The packer converts to triangle lists offline, which makes merging safe AND halves the pipeline space.
  **NEXT:** the replayer itself, then the staged diff -- scene RT first, post/bloom chain second.
  ⚠⚠ **EPISTEMIC RULE FOR THAT DIFF (re_kb, 2026-09-01):** a pixel diff that improves is a
  MEASUREMENT, not a mechanism. A matching replay would show our translation of the captured state
  reproduces the pixels; it would establish NOTHING about MvC2 itself. That is
  `record_attempt(..., outcome='masks_only')`, never a `finding`. The diff tool must print this
  alongside its number rather than leaving it to the reader.
  ⚠ **CORRECTION TO MY OWN EARLIER CLAIM:** I twice said the captured 64x32 / 128x32 R8 tiles would be
  "a live arbiter" for the wide-part tile-order question. **FALSE.** `finding:wide_part_colpair_order`
  and `finding:blank_record_desc_slot` are both **confirmed AND FIXED 2026-07-09** from the engine's
  own desc builder (`loc_8c033ba8..ce0`) and walker (`loc_8c0344d4`) -- code-grade disassembly
  evidence, far stronger than any texture comparison. A Steam tile dump is an independent
  CROSS-CHECK of a settled finding, not a resolution of an open one. (I was also citing them by
  number, "re_kb/66"/"re_kb/68", second-hand from an expert report; the KB addresses findings by SLUG.
  Resolve citations before propagating them.)

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

---

## 2026-09-01 — Gate 0: the model is exact; the gap is in the replayer

`d3dcap/replay/verify_alpha.py` (new) hand-executes frame 4261's ALPHA channel in pure Python — no
GPU, no WebGPU, no WGSL. Alpha is the right channel to isolate because every scene draw blends with
`srcA = ONE, dstA = ZERO`, so the RT's final alpha is just the alpha of the last fragment that was
not discarded. That makes it a pure coverage question, independent of texture colour, palette RGB,
fog and blend arithmetic.

```
frame 4261: 760 draws into the 2048x1024 scene RT
ALPHA MASK over the 1280x960 crop (1,228,800 px)
  truth covered : 1,228,764 (99.997%)
  we covered    : 1,228,800 (100.000%)
  MISSING       : 0 (0.000%)
  spurious      : 36 (0.003%)
```

**Our reading of the capture reproduces Steam's alpha channel exactly.** The 36 spurious pixels are
the RT's own 36 alpha-0 pixels at the crop edge. So the transform, the strip→list conversion, the
input layout, the UV mapping, the palette indexing, the alpha test and the draw order are all
correct, and any coverage loss in the WebGPU replay is **plumbing**, not model. That halves the
search space, exactly as the capture expert predicted it would.

### Measured while building it — each of these is now settled, do not re-litigate

| Question | Answer | How it was measured |
| --- | --- | --- |
| Is the capture complete? | Yes. Every truth pixel in the crop is inside some captured primitive. | Rasterised all 760 draws' triangles: `truth covered, NO draw = 0 px`. |
| Is the scene RT cleared? | **No.** RT `0000000076B7D8E0` takes all 760 draws and gets no `ClearRTV`. Steam starts each frame from the previous frame's pixels. | 7 `ClearRTV` calls, none targeting it. Harmless here because this frame's draws cover 100% of the crop, but it is a real hazard on a sparser frame. |
| Is there an alpha test? | Yes, and it matters. `ge fAlphaRef, a` → `discard_nz`, with `fAlphaRef = 0.0` on all 759 draws that bind cb0 — so alpha-0 texels are DISCARDED, never blended. | `fxc /dumpbin` on `ps_00000000642DB9F8` and `ps_00000000643D33F8`. Already implemented correctly in `sprite.wgsl`. |
| Does culling explain the gap? | No. Enabling the captured cull states changes coverage by **0 px**: every triangle in the 566 `CULL_FRONT` draws is back-facing. | `CULL=1 python verify_alpha.py`. |
| Does depth clipping explain it? | No. Clipping NDC z to [0,1] as WebGPU does changes coverage by **0 px**. | `DEPTHCLIP=1 python verify_alpha.py`. |
| Vertex colour byte order | `TANGENT`/`BINORMAL` are `DXGI_FORMAT_R8G8B8A8_UNORM` (format 28), NOT BGRA — so WebGPU's `unorm8x4` needs no swizzle. | The three stride-40 input layouts in the capture are byte-identical. |
| Per-draw input layout | One layout, three aliases. 758 of 760 scene draws are stride 40 with identical elements; 2 draws are stride 28. | `il_*.json` dumps. |
| Scissor | Never enabled (`scissor: 0`), never captured (`null` on all 760), never applied. | pack + ndjson. |

### Retired

* The `only=characters` / `only=stage` **diff numbers**. Alpha blending is not decomposable, so a
  subset replayed over a zero clear cannot equal the composite under any mask. The subset buttons now
  render for LOOKING only and print a warning instead of a verdict.
* The single fused "differing %". `diff.mjs` now reports COVERAGE (geometry) and COLOUR (only among
  pixels both images cover) separately. The old number mixed the two: our target clears to
  `[0,0,0,0]` while truth ends at alpha 255 almost everywhere, so every uncovered pixel tripped the
  threshold on alpha alone.
* The dead degenerate-triangle check in `pack_replay.py`'s `strip_to_list` — `a`, `b`, `c` are always
  three distinct consecutive indices, so it could never fire.

### The bug Gate 0 flushed out: a byte offset packed as a vertex index

With the model proved exact, the WebGPU replay's own split metric read:

```
COVERAGE   we cover 916,417 px (74.578%)   truth 1,228,764 (99.997%)   MISSING 312,348 (25.419%)
```

`pack_replay.py` was computing each draw's first vertex as

```python
first = (d["voff"] + d["start"] * stride) // stride
```

which folds the vertex buffer's **byte** offset into a vertex **index**. That is only valid when
`voff` is a whole number of vertices. In frame 4261 it usually is not:

| voff | stride | draws | voff % stride |
| ---: | ---: | ---: | ---: |
| 65,536 | 28 | 1 | 16 |
| 65,648 | 40 | 1 | 8 |
| 65,808 | 28 | 1 | 8 |
| 65,920 | 40 | 202 | 0 |
| 98,304 | 40 | 172 | **24** |
| 131,072 | 40 | 154 | **32** |
| 163,840 | 40 | 176 | 0 |
| 196,608 | 40 | 53 | **8** |

**382 of 760 draws — 50.3% — fetched POSITION out of the middle of the previous vertex.** It failed
the way a subtle bug does: the surviving half still landed somewhere plausible, so the frame looked
roughly right and two rounds of analysis read it as a shading problem.

Fixed by keeping `voff` a byte offset and binding it with `setVertexBuffer(0, vb, d.voff)`, which
takes one; indices are now relative to it. All offsets are multiples of 4, which is what WebGPU
requires. The packer asserts that and now prints the alignment picture every run.

Two related things fell out of the same look:

* the vertex layout was **hardcoded** to `arrayStride: 40`, but the frame has four input layouts
  including a 28-byte POSITION+NORMAL one with no colours and no texture coordinates. The layout is
  now built from the captured `D3D11_INPUT_ELEMENT_DESC[]`, which the pack carries, and a draw whose
  layout cannot supply every attribute the shader reads is **skipped and counted** rather than
  rendered from invented data (`verify_alpha.py` confirms those 2 draws contribute no coverage);
* the pipeline cache key did not include the layout, so the first draw's layout would have been
  reused for every later draw with matching states.

---

## 2026-09-01 — coverage fixed; the next bug is stale texture content

With the vertex offset fixed the browser reports:

```
COVERAGE  we cover 1,228,760 (99.997%)   truth 1,228,764 (99.997%)   MISSING 5 px   spurious 1 px
COLOUR    mean |delta| B=16.179 G=15.522 R=13.283 A=0.205   differing 170,976 px (13.915%)
```

Geometry is done. The stage, the HUD and the meters are right; the characters come out as scattered
sprite shards.

### `verify_frame.py`: the CPU colour gate

`verify_frame.py` is `verify_alpha.py`'s sibling — it reads the same `.pack` the browser reads, runs
the same fragment maths, composites with the same captured blend states, and does it all in NumPy
with no GPU. It models perspective-correct interpolation (DXBC `dcl_input_ps linear` IS the
perspective-correct mode), point/bilinear sampling per the captured sampler, the alpha test, the
depth test and per-draw blending.

It reproduces the browser to within 0.01% — `mean |delta| B=16.198` vs `16.179`, `13.924%` vs
`13.915%`. **The replayer and the CPU model agree, so the WGSL, the uploads, the samplers and the
blend translation are all off the table. What is left is our MODEL of the capture.**

It also scores every draw on the pixels where it is the last writer:

```
indexed : 123 draws --   8 pixel-exact,  30 wrong somewhere,  85 never the last writer
texalpha:  64 draws --  19 pixel-exact,  24 wrong somewhere,  21 never the last writer
opaque  : 572 draws -- 197 pixel-exact,  28 wrong somewhere, 347 never the last writer
```

Six character draws are **100% wrong on every pixel they own**.

### The cause: textures were snapshotted once, at Present

Searching all 123 dumped index tiles for one that reproduces a 100%-wrong draw found nothing above
8%, and the draw's own tile scored **0.0%** over 2,807 drawn pixels. The content those draws sampled
was not in the capture at all.

`dllmain.cpp` noted each bound texture by pointer and dumped it once at Present — the same mistake
the constant buffers made, and for the same reason. The vertex buffer survives Present-time
snapshotting only because the game APPENDS to it; that property does not generalise across resource
types, and it was generalised anyway. Both `Map`/`Unmap` and `UpdateSubresource` filtered on
`D3D11_RESOURCE_DIMENSION_BUFFER`, so **texture writes were entirely unobserved**.

Fixed by versioning texture content:

* `markTexDirty()` on both write paths — the same two the constant buffers needed;
* at each **draw**, any bound texture that is new or has been written since its last snapshot is
  copied GPU-side into a staging texture. `CopyResource` does not stall; the staging textures are
  mapped and written at Present, when the GPU is done with them anyway;
* each draw records `"ptr#generation"`, so no draw can be handed content from a later upload;
* the dump filename gains a `_v<gen>` suffix. `pack_replay.py`, `verify_alpha.py`, `decode_verts.py`
  and `summarize.py` accept both forms, so captures taken before this still analyse — verified: the
  old frame 4261 still packs and still reports 0 missing coverage.

The capture log now states the answer directly: `N distinct textures, W writes seen this frame, R of
them rewrote a texture a draw had already sampled`. If `R` is 0 on the next capture, this hypothesis
is wrong and the shards are something else.

⚠ The in-match gate counts texture OBJECTS, not generations — a frame that rewrites one page eight
times must not read as eight pages, since the 50-texture threshold was calibrated on objects.

---

## 2026-09-01 — the stale-texture hypothesis is REFUTED; the real bug was the packer's glob

The versioned-texture build's own counter answered it on the first capture, across six frames:

```
[tex] 234 distinct textures, 46928 writes seen, 0 of them rewrote a texture a draw had already
      sampled, 230 snapshots to write
```

**Zero.** Within a frame, once a texture has been sampled by a draw it is never written again — so
the Present-time snapshot was valid after all and the "stale texture content" diagnosis was wrong.
The versioning stays: it costs one staging copy per upload, it is correct rather than
correct-by-luck, and the counter is now the instrument that settles this question on any future
frame. (⚠ the `writes seen` figure spans the ~8 s between captures, not one frame; the rewrite
counter is the one scoped to the captured frame.)

### What was actually wrong: `tex_*` matched every captured frame

`pack_replay.py` looked up a texture's pixels with

```python
glob.glob(os.path.join(CAP, "tex_*_%dx%d_f%d_%s.bin" % (w, h, fmt, ptr)))[0]
```

A capture run keeps every frame it sampled, and a texture object that lives across frames has one
dump per frame. The wildcard matched all of them and `[0]` took the **alphabetically first frame
number**. Measured on frame 4360: **21 of 223 textures were loaded from frames 2965 and 3893.** The
character index tiles change every frame, so on the earlier capture this drew the characters as
scattered shards of a different animation frame over a perfectly correct stage — and read like a
shading bug for two rounds. Fixed to match `tex_<this frame>_…` exactly, and to refuse rather than
guess if more than one dump still matches.

⚠ Honest limit: frame 4261's dumps were cleared by the next capture run, so this cannot be replayed
against the frame that showed the shards. On 4360 the 21 mis-picked textures happened to hold
identical content in both frames, so fixing the glob changed the numbers by nothing there. The
mechanism is confirmed; its responsibility for the 4261 shards is inferred.

### Where frame 4360 stands

```
COVERAGE  MISSING 26 px of 1,228,800
COLOUR    mean |delta| B=0.646 G=0.447 R=0.684 A=0.001   differing 4,797 px (0.390%)

indexed : 196 draws -- 124 pixel-exact, 0 wrong somewhere, 72 never the last writer
texalpha:  52 draws --  25 pixel-exact, 5 wrong somewhere, 22 never the last writer
opaque  : 623 draws -- 244 pixel-exact, 39 wrong somewhere, 340 never the last writer
```

**Every character draw is pixel-exact.** 4,619 of the 4,797 wrong pixels belong to three opaque stage
draws (85, 86, 87) at the extreme left edge of the viewport, `x = 0..42` in crop space. Those draws
paint pure black (`colour0 = (0,0,0,1)`, so `tex*0 + 0`) and truth there is a bright `(127, 74, 129)`
— so in Steam's frame something LATER covers those pixels and in ours it does not. Fog is not
involved: `fFogDensity = 0` on every stage draw in this frame too.

That left edge is the next thread. `FOCUS=<draw> python verify_frame.py <frame>` prints the delta
percentiles, bbox and mean colour for the pixels one draw owns.

---

## 2026-09-02 — PATH B IS PROVEN. The browser reproduces a Steam MvC2 frame.

Frame 4360, replayed on WebGPU from the capture, diffed against Steam's own pre-bloom scene RT over
the full 1280x960 viewport:

```
COVERAGE  we cover 1,228,761 px (99.997%)   truth covers 1,228,761 px (99.997%)
          MISSING 0 px   spurious 0 px   missing bbox: none
COLOUR    max |delta| B=238 G=238 R=255 A=0
          mean |delta| B=0.631 G=0.428 R=0.669 A=0.000
          differing 4,702 px (0.383%) at >1 LSB
870 draws, 9 pipelines, 129 ms
```

**Geometry is exact — zero missing, zero spurious — and 99.617% of pixels are within 1 LSB.** The
render is a complete MvC2 frame: both fighters, the assist, the 3D stage, the HUD, the hit counter,
the lightning, the super meters.

### The four bugs, in the order they were peeled off

| # | Bug | Symptom | How it was found |
| --- | --- | --- | --- |
| 1 | `first = (voff + start*stride) // stride` folded a vertex buffer BYTE offset into a vertex INDEX | 382 of 760 draws (50.3%) fetched POSITION from the middle of the previous vertex; 25% of coverage gone | `verify_alpha.py` reproduced Steam's coverage exactly ⟹ the fault had to be in the pack |
| 2 | `arrayStride` hardcoded to 40, layout not in the pipeline key | the 28-byte POSITION+NORMAL layout read at the wrong pitch | fell out of fixing #1 |
| 3 | `glob("tex_*_…")[0]` matched the dump from EVERY captured frame | 21 of 223 textures loaded from other frames; character tiles change every frame ⟹ characters drawn as shards of a different animation frame | counted the candidate files per texture |
| 4 | single-threaded `serve.py` | the page would not load at all; a wedged instance also blocked the next run from binding | Chrome's speculative pre-connects block `readline()` forever |

A hypothesis that was **refuted** along the way, by the counter written to test it: "textures are
rewritten mid-frame so the Present-time snapshot is stale". Zero rewrites across six frames. The
versioning stays because it is correct rather than correct-by-luck, and the counter now settles that
question on any frame without a debugging round.

### What made the difference: separate the model from the plumbing, and coverage from colour

Two changes turned a stalled investigation into four found bugs in one sitting.

1. **CPU gates.** `verify_alpha.py` and `verify_frame.py` re-execute a captured frame in NumPy with
   no GPU. *Python matches truth but the browser does not* ⟹ the bug is in the replayer. *Neither
   matches* ⟹ the bug is in the model or the capture. That halves the search space on every question.
2. **Report COVERAGE and COLOUR separately.** The single fused percentage let a geometry bug wear a
   shading bug's clothes for two rounds: our target clears to `[0,0,0,0]` while truth ends at alpha
   255 nearly everywhere, so every pixel we simply never covered tripped the threshold on alpha alone.

`verify_frame.py` also scores each draw on the pixels where IT is the last writer, which converts
"13.9% differing" into "these six draws are 100% wrong" — and `FOCUS=<draw>` prints one draw's delta
percentiles, bbox and mean colour.

### The one open defect: a missing character part

4,627 of the 4,796 remaining differing pixels sit in three 64x64 blocks at crop `x = 0..64`,
`y = 384..576` — **Cable's face**. Truth draws his head there; we draw the stage behind it. It is a
colour disagreement, not a coverage one: those pixels ARE covered by us, just by the wrong draw.

Measured, for whoever picks this up: the indexed draws near that region are `i = 573..578` (six
26.7 px-wide quads forming a thin band at `y = 407..442`, each sampling only `uv [0, 0.25]` of a
32x32 tile) and `i = 586/587/588` (the body, full `uv [0, 1]`). **Nothing in the captured draw list
covers `x = 0..42, y = 442..557`**, which is where the face belongs. Either a part is missing from
the capture or one of those thin quads should be sampling a larger sub-rect.

Note the region touches the LEFT VIEWPORT EDGE and draw 573's quad starts at `x = -44`, off-screen.
That is worth checking first.

### Also fixed

The viewer's standing warning "3 draws without a world matrix ... WILL be wrong" was a false alarm:
those three are `vs_flat` draws, and `vs_flat` is a pass-through that declares no constant buffer at
all. The warning now only counts draws that actually need matrices — a permanent false warning is
how a real one gets ignored.

---

## 2026-09-02 — burst capture and sequence playback

A single frame proves the renderer; a run of consecutive frames is a replay. Three pieces:

### 1. `collect.ps1 -Burst N` — N consecutive frames per arm

`D3DCAP_BURST=<n>` makes the shim record n consecutive frames instead of one. The Present hook
continues the burst **in the same call** rather than leaving it to the arm path, which is an
`else if` — re-arming there would record every OTHER frame, and a playback of every other frame is
not a playback of the match.

Three things make a burst affordable, none of them optional:

* **the texture version table is kept alive across the burst.** A texture is re-snapshotted only when
  the game actually rewrites it, so the stage art is dumped once for the whole segment and only the
  character tiles — which really do change every frame — are dumped again. This is the machinery
  built for the (refuted) stale-texture hypothesis finally earning its keep.
* **buffers are dumped only up to the highest byte any draw touched.** The vertex buffer is 2 MiB and
  a frame reads ~220 KB of it; dumping it whole costs 240 MB for two seconds of match. A PREFIX is
  safe where a slice would not be, because the offline tools index by absolute byte offset.
* **the 8 MB scene-RT BMP and the backbuffer are written for the first frame only.** One ground truth
  proves the sequence renders correctly; the rest of the burst is what makes it a playback.

A frame that fails the in-match gate ends the burst — half a burst of menu frames is not a playback.

### 2. `pack_sequence.py` — merge, don't reimplement

It runs the real `pack_replay.py` once per frame and merges the results, because that packer carries
every gate that makes a frame trustworthy (strip→list with the odd-triangle swap, byte-offset vertex
binding, per-frame texture lookup, shader classification from disassembly, the texture-coverage
assertion, the BORDER refusal). A second packer would drift, and the drift would surface as a subtly
wrong replay months later.

Every payload is deduped by content hash across the burst, and each frame's head is the head
`pack_replay.py` produced with its blob offsets rewritten into the shared pool — so the player hands
a frame straight to the same `createResources()` the single-frame viewer uses. No second code path.

Container: `"RRSQ" u32:headLen head(JSON) <blob pool>`. Gitignored, like `.pack` — ROM-derived.

### 3. `player.html` — playback

One `Replayer` is built once; `setFrame()` swaps only the vertex/index buffers and the per-draw
uniform slice. The pipeline cache survives because its key is content-derived (shader hash, layout
hash, blend/depth/raster state), and the bind-group cache survives because its key is the texture's
`pointer#generation`, which IS a content identity — with a shared texture map guaranteeing one view
per content.

Playback **blits** the scene RT to the canvas through a 3-vertex fullscreen pass that crops to the
game's `(384,32)+1280x960` viewport. It must not use `copyTextureToBuffer`: that is the diff path, it
stalls on a GPU sync, and at 60 fps it turns a 2 ms render into a 30 ms frame. Render targets are now
reused across calls rather than reallocated — 16 MB per frame handed to the GC otherwise.

Play/pause, frame step, scrub, loop, and 60/30/15/6 fps. Space and the arrow keys work.

### Verified so far

The container round-trips: on a 6-frame test sequence every blob range lands inside the pool, every
texture payload is exactly `w*h*bpp`, every draw's index range lies inside its frame's index buffer,
and every vertex fetch lands inside its frame's vertex buffer. The module graph imports clean. The
playback itself is unproven until a burst is captured — this is scaffolding plus one validated
container, not a demonstrated replay.

### The sequence's own version of the texture-identity bug

The player worked on the first attempt, and some frames rendered perfectly while others showed the
familiar garbled character shards. The frames themselves were fine — packed and rendered alone,
frame 3893 diffs at **136 wrong pixels of 1,228,800 (0.011%)** against its own ground truth.

The fault was in the sequence, and it was mine: the shared-texture optimisation keyed on the pack's
texture key, `pointer#generation`. **That is a content identity WITHIN one frame and nowhere else.**
In this capture the shim reset its version table every frame, so the same pointer is `#0` in every
frame while holding completely different pixels. Measured across the 6 test frames: **175 of 317
texture keys mean different bitmaps in different frames.** The shared map — and the bind-group cache,
which is keyed the same way — handed frame N's art to frame N+1. Clean frames and garbled frames
alternated depending on which pointers happened to repeat.

This is the same class of bug as the `tex_*` glob that matched every captured frame, reintroduced one
layer up by an optimisation. Fixed in `pack_sequence.py` by re-keying textures to `t<pool offset>` —
the pool dedupes on sha256, so the offset IS a content identity — and rewriting every draw's `tex`
references to match.

**And made into a gate**, because an argument would not have caught it: `pack_sequence.py` now
refuses to write a sequence unless every texture key resolves to exactly one bitmap across every
frame, and every draw reference resolves at all.

```
gate: 597 texture keys, one bitmap each, 597 draw references all resolve
```

⚠ The general rule, now paid for three times: **a runtime pointer is never an identity, and a
per-frame identity is never a cross-frame one.** Key by content, and assert the keying.

### Pacing

Two changes, one of them a real bug rather than an optimisation.

**The play loop was paced off `requestAnimationFrame`'s COUNT.** It advanced one captured frame per
Nth display refresh, which is real time only on a 60 Hz display: on a 144 Hz panel it played the
match at 144 fps — 2.4x too fast — and on a laptop throttled to 30 Hz it played at half speed. The
capture is a fixed 60 fps of GAME time, so the only correct pacing is elapsed milliseconds. The loop
now accumulates wall-clock time against a target interval, and a long stall (tab switch, GC pause)
advances at most 4 frames and drops the rest of the debt rather than fast-forwarding the match. The
speed control is now a target rate (60/30/15/6 fps), not a refresh divisor.

**Every frame's GPU resources are built up front.** Playback used to allocate three GPUBuffers and a
bind group per frame — steady allocation at 60 Hz, which shows up as intermittent hitching rather
than a lower frame rate. `Replayer.prepare()` builds a frame's resources without switching to them
and `use()` switches with no allocation at all. The cost is bounded: the vertex buffer is dumped as a
used-range prefix (~230 KB), the index buffer ~25 KB, uniforms 256 B per draw — about 0.5 MB per
frame, with textures shared across the whole sequence rather than per frame.

The player now reports its measured rate and any skipped frames, so pacing is a number rather than an
impression.

### The burst never armed in a match

First `-Burst 90` run recorded nothing:

```
[cap] frame 1 inventory: 0 draws
[diag]   captured at creation: ...
(nothing further)
```

Two mistakes compounding. The burst armed 3 s after the hooks went in — the Capcom logo — and that
frame has 0 draws, so it failed the in-match gate and the burst ended, correctly. But burst mode also
set `MAX_SHOTS = 1`, so **nothing ever armed again**: the run sat there recording nothing while the
player waited for it.

Arming is cheap — one frame, and a frame that fails the gate is discarded without consuming a dump
slot — so it now retries every second until a burst completes, and stops arming once one is on disk.
Both outcomes are logged rather than silent:

```
[burst] abandoned at N frame(s) -- frame F is not a match (D draws, T textures)
[burst] COMPLETE: N consecutive frames from F
```

The texture version table is now sized for a long burst (4096, from 512). It lives for the whole
burst — that is what makes a texture re-dump only when it is rewritten — so it accumulates every
distinct texture object the game touches over the segment, not the ~230 a single frame binds. It also
holds a reference to each, which is what keeps the pointer a stable identity: without it the game
could free a texture and hand the same address to a different one.

### Recording longer than a moment

`collect.ps1 -Seconds N` is the honest unit: the capture counts GAME frames at 60 fps, so N seconds
of match is N*60 consecutive frames however slowly the game is actually running while it records.

20 seconds is 1200 frames, and that does not fit the "prebuild every frame" design: at ~0.5 MB of
per-frame GPU buffers (vertex-buffer prefix ~230 KB, index buffer ~25 KB, 256 B of uniforms per draw)
that is ~580 MB. So the player now prepares a **window** — 300 frames, ~145 MB — topped up two frames
per displayed frame and evicted behind, with buffers destroyed explicitly rather than left to the GC.
Preparing is pure buffer creation, so the top-up stays well ahead of a 60 fps read-out and never
allocates in the critical path for the frame being shown. Sequences shorter than the window are
prepared entirely and never evict, exactly as before.

Textures are not part of the window: they are shared across the whole sequence and uploaded once.

⚠ Rough cost of 20 s, to be replaced with measurements from the first long run: ~1.6 GB on disk
during capture (the per-frame ndjson dominates at ~1 MB a frame), and a ~360 MB `.seq`. A 5-second
run first would calibrate all of these against reality rather than arithmetic.
