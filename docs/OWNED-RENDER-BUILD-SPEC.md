# OWNED RENDER BUILD SPEC — the full re-extract + WebGPU render (bodies · effects/sparks · HUD · layering)

> **⚡ CURRENT STATUS — 2026-08-30: the resim → real-TA → WebGPU render pipeline WORKS.** OUR resim's real
> `serverPublish` TA renders clean (bodies + effects + additive blend + 3D stage + HUD) on the tapecanvas
> WebGPU renderer, no flycast mirror — interactive player `web/tapecanvas/play_zcst.html`.
> **→ [`docs/RENDER-ACCURACY-PROGRAM.md`](RENDER-ACCURACY-PROGRAM.md) is the SSOT for how it's done.**
> This doc specs the **emitter / owned-render** path (Track A — still the no-determinism-needed fallback);
> the ground-truth path is the real-TA render above (blend/palette/effects come for free from the TA).

**Status:** Phase-1 (RE + compositing reference) COMPLETE and reconciled. This is the Phase-2 build
contract for `mvc2-sprite-render-expert`. Every offset/order below is cited to the two Phase-1 consults
(sh4-re HUD/layering/effects-key; flycast-internals compositing) which in turn cite `re_kb` / marvelous2
disasm / the DC→Steam block-map. CONFIRMED vs INFERRED is preserved.

The render path is unchanged and engine-agnostic: **tape → OBJS/GSTA adapter → `sprite-client.mjs` →
`sprite-gpu.mjs` (WebGPU, native 640×480, NEAREST)**. We reuse sprite-client/sprite-gpu VERBATIM; the only
new code is the atlas re-extraction, the HUD/effects wiring, and the composite ordering.

---

## 0. TAPE COMPLETENESS VERDICT (the "don't miss anything" check)

Checked against the staged 0.3.28 reader (`GS_SCHEMA` + the offset table). **0.3.28 is complete for
bodies + effects + the CORE HUD — NO re-record needed to build the render.**

| render input | tape field (0.3.28) | status |
|---|---|---|
| body sprite | `sid[6]` (raw, mask &0x7FFF) | ✅ |
| body screen pos / scale | `sx[6] sy[6] zx[6] zy[6]` (H+0x124/128/130/134) | ✅ |
| facing / draw-gate / anim | `facing[6] drawn[6] atimer[6]` | ✅ |
| super-glow / hit-flash | `glow[6]` (H+0x5C) `flash[6]` (H+0x172) | ✅ |
| costume (LUT swap) | envelope `costume[6]` (H+0x6C1) | ✅ |
| life + chip | `hp[6]` (H+0x40c) `red_hp[6]` (H+0x410) | ✅ |
| meter LEVEL (0-5 pips) | `p1_meter p2_meter` (MET_BARS) | ✅ |
| meter FILL (fine) | `meter_fill` (MET_FILL) | ✅ |
| combo counter | `combo_dealt[6]` | ✅ |
| round timer | `timer` (BG_TIMER) | ✅ |
| portrait-id / name | envelope `teams` + active-slot detect | ✅ (derived) |
| object pool (fx/sparks/capes/proj) | `objs` per-frame `[sid,sx,sy,zx_q,face,cat,owner,layer,gfx]` | ✅ |
| per-object draw layer | obj `layer` + fighter `layer[6]` | ✅ |

**TIER-2 gaps (optional tiny 0.3.29, NOT a Phase-2 blocker):**
- Round-win stars: `round_no` (OFF_ROUND) + the per-set WINS tally (`set_start`) are read by the reader but
  not in the frame schema. Add as a static envelope field (`set_score:[p1,p2]`, `round_no`) — low cost.
- Exact name-plate glyph text (multi-strip) — reconstruct from portrait/name for now.

**Effects key = the one genuine OPEN item** (see §3). Effects render OFF until the binding probe certifies it.

---

## 1. BODIES — indexed atlas + palette LUT (the owned re-extract)

**Bake CELL-NATIVE. The renderer applies CPS at draw time — never bake CPS in.** (Confirmed by both the
size fix and the sh4-re/sprite-render consult.)

- **Format:** per-character `PLxx_i8.png` (indexed, 1 byte/texel) + `pal128` + per-costume `banks[]`. Proven
  bit-identical round-trip, ~4× smaller VRAM (Magneto 69.5→17.4 MB), and **costume = a LUT swap** (one bake,
  every costume/skin free) — feeds `sprite-gpu`'s existing exact-palette-LUT path. Per-char, NOT combined.
- **Key:** `sid & 0x7FFF` (bit15 = xform flag, mask it).
- **True foot-anchor (fixes a ~34px vertical error):** carry the real GFX2 pen anchor (`dx0,dy0`, ≈59.8%
  from left, 73.5% down) instead of bottom-center. Walk it in the rip, store per cell.
- **Scale feed (THE size fix — already live, keep it):**
  `dw = wG × CpsX × objScaleX`, `dh = hG × CpsY × objScaleY`, with `CpsX = 1.6666666 (5/3)`,
  `CpsY = 2.1428570 (15/7)`. Source `objScale` from `zx`/`zy` (H+0x130/134, the composite CpsX·sprite_scale)
  **OR** the factored form — **NEVER both** (double-apply trap). `zx/CpsX`, `zy/CpsY` is correct;
  `zx/CpsX²` was the undersize bug.
- **Asset source:** `game_50.arc → IBIS → AFS entry 209+cid → DAT{GFX1@0, GFX2@4, PAL@8}`. Bake needs only the
  DAT — no packed exe. Pitfalls (all previously bit us): pal-bank bug; full-W×H twiddle
  (`ConvertTwiddlePal4`); GFX1 dims are `sw/sh` at +2/+3 (NOT lw/lh); bottom-up storage; PAL4 vs PAL8.
- **Coverage:** enumerate every sprite_id offline (`rip_gfx2_assembly.py read_cells()`), prove no move draws a
  hole (`scan_atlas_coverage.py`). Any tape renders, no per-match bake.

---

## 2. HUD — procedural reconstruction (Steam tape has NO TA stream)

**Critical:** the DC HudQuad TA-capture path does NOT exist on a Steam GGPO state tape. HUD must be
**RECONSTRUCTED** from the captured fields (all present, §0), NOT replayed as quads.

- **Life bars = procedural, no sprite.** The engine draws a white-texel polygon modulated by a per-team-slot
  vertex color (`bank15 loc_8c15FFB0`). Render two ANGLED parallelograms swept toward center (P1 top-left
  outer, P2 top-right mirrored): draw dark-red **chip** (`red_hp/144`) FIRST, bright **HP** (`hp/144`) ON TOP
  in a shared clip so chip trails behind. Ref geom `hudAngledLifeBar`: outerX 80/560, LEN 212, H 15, SKEW 26.
  Team tint by active point char (C1/C2/C3).
- **Super meters:** sheared bars lower-left/right, `meter_fill/144` from outer corner inward, `p*_meter`
  level number + 0-5 tick pips above. `HP_MAX = METER_MAX = 144`.
- **Timer + combo digits:** boxed-digit atlas from **FONT.BIN rec1** (`@0x10040`, 64×64 **ARGB4444 twiddled**,
  4×4 16px grid, each cell rotated 90° CCW → de-rotate to upright). Timer = 2 centered digits top; combo per
  side when `combo_dealt>1`. Extractor: `tools/rip_hud_atlas.py` → `atlas/hud/hud_atlas.{png,json}`.
- **Portraits/name plate:** **DM01POL.BIN + DM01TEX.BIN** texture #11 (512×512 **RGB565 twiddled**, 8×8 grid
  of 64×64, faces stored 90°-rotated → CCW-rotate), keyed by ROM char_id. Extractor: `tools/rip_portraits.py`.
  51/56 name-verified; 5 fall back to monogram (closing needs a live char+0x20 dump — tier-2).
- **Compositing:** HUD draws **LAST, straight alpha (source-over), never additive, never depth-tested**
  against bodies (both consults agree). In the WebGPU render that's a final HUD sub-pass; the current stacked
  overlay canvas is equivalent.

---

## 3. EFFECTS / SPARKS — atlas + the OPEN binding key

- **Two effect classes** (do not conflate):
  1. **Sprite-class** (cat 1-4, in the slot table): render like a body via GFX2 part-assembly, keyed by
     `(GFX2 = node+0x160, sel = node+0x144 & 0x7FFF)` — the FAITHFUL path (0.00px on DC).
  2. **3D-class** (NaomiLib lists 5-13): POL models from the model dir `0x0CED0000` (241 models). Coarse
     approximation for now = the 25-entry **texture** directory at `*(0x0CED0008) = 0x0CED03D8`
     (`[e0=size 128²/256², e8=VRAM addr, fmt ARGB4444/RGB565/ARGB1555]`), baked to `fx_atlas.{png,json}`.
- **Format:** RGBA (16-bit twiddled-PVR, direct-color — NOT indexed). Blend **additive** (dst=ONE).
- **THE KEY (OPEN — this is why effects render OFF):** the per-node directory key is **`node+0x15C`
  (Dat_GFX1) low-28 bits in `[0x0CED0000, 0x0CEE0000)`**, `dirIdx = ((key & 0x1FFFFFFF) − DBASE)/0x10`.
  - `+0xC8` is WRONG (early DC guess). `H+0x1A8` is **NOT confirmed** — the Steam delta is ambiguous
    (δ0x44→H+0x1A0 vs δ0x54→H+0x1B0; 0x1A8 matches neither). **Do NOT hardcode the offset.**
  - **Robust rule = VALUE-TEST:** read the cluster `H+0x190..H+0x1C0` as u32 words and pick the word whose
    low-28 bits land in the effect bank. Offset-independent; sidesteps the ambiguity.
  - **One read-only probe closes it** (sh4-re owns it, runs on a live contact frame): resolve Steam bank base
    `B = *(u32)(blk+0x6CE8)`, `DBASE = *(u32)(B+0x08)`; for drawn effect nodes dump `H+0x190..H+0x1C0` +
    sid + screen xy, identify the in-bank word → that offset is the confirmed Steam Dat_GFX1 slot and
    `dirIdx` follows. Determinism-safe, no rebuild.
  - **Tape action:** rather than trust `H+0x1A8` alone, emit the value-test result (resolved key + the offset
    it came from) per effect node in `objs.gfx`. Keeps the tape correct regardless of the offset.

---

## 4. LAYERING / Z — the deterministic compositing order

Two render machines (both consults reconcile to the same frame order):

**(A) 2D SLOT-TABLE machine** (`loc_8c0308c2`, primary sprite z, 0.00px on DC):
```
for L in 0..15:                 # 0 = BACK, 15 = FRONT
  for i in 0..count[L]-1:        # within-layer = ENQUEUE order (do NOT re-sort)
    node = handle[L][i]
    if u8(node+0x03) == 0: body path      # cat 0
    else:                  effect path     # cat 1..4 (cape/proj/spark)
```
- **Steam tables (CONFIRMED live):** `count[L] = u8 @ blk+0x324D0 + L`; `handle[L][i] = u64 @ blk+0x2F4D0 +
  L*0x300 + i*8`. (`0x2F4D0 + 16*0x300 = 0x324D0` closes exactly — that's the confirmation. A stray
  `blk+0x300D0` in an older note is `0x2F4D0 + 4*0x300`, a mislabeled layer-4 row — use `0x2F4D0`.)
- Capes/back-effects sit on LOWER layers than their body; bodies ~L5/L6; projectiles/front-sparks HIGHER.

**(B) 3D / NaomiLib machine** (lists 5-13, never in the slot table): stage set pieces (cat 11), shadows/
companions (cat 6), and SOME hit-sparks (`bank10 loc_8c100968` spawns onto list 7).

**Top-level per-frame order the renderer MUST follow:**
> **stage-background → slot-table L0→15 (body vs effect by node+0x03; within layer, enqueue order) →
> 3D-list effects (list-7 hit-sparks, shadows) → HUD (on top).**

**Within each pass, honor PVR OP → PT → TR** (flycast/Holly hardware groups by list type regardless of
submit order; TR autosort by depth). This is why an opaque body draws before an additive spark in the same
pass and the HUD is unconditionally on top.

**THE hard rule (from flycast-internals):** the slot-table enqueue order IS the TR submission order, and the
`draw_layer` wire field already carries it. **The renderer must NOT re-sort — not by z, not by category.**
Any client-side sort scrambles the engine's authored layering (cape-behind-body, beam-in-front).

**Per-object blend classifier (1 byte, RAM-derivable):** is_effect (GFX in `0x0CED0000`) ⇒ additive (dst=ONE);
body/cape ⇒ opaque/alpha; else ⇒ alpha.

---

## 5. COMPOSITING / BLEND (flycast-internals — GPU config to match the engine)

- **List order OP→PT→TR**, never interleaved. Stage/bg→OP; bodies→TR (bit25, translucent-list);
  effects/sparks→TR additive (some PT); HUD→separate late pass.
- **Blends by class** (TSP `src=(tsp>>29)&7`, `dst=(tsp>>26)&7`):
  - Opaque: ONE/ZERO — **forced, ignore the poly's TSP bits** (engine over-writes them).
  - Alpha (bodies/cape/PT): src-alpha / inv-src-alpha.
  - Additive (effects): **not constant** — pure-add ONE/ONE (hit-sparks) vs alpha-weighted-add src-alpha/ONE
    (auras/supers). **Route by the TSP SrcInstr bit.** sprite-gpu already has both (`sparkPipe` + `pipeAdd`).
- **BUILD GAP to fix:** sprite-gpu draws bodies **opaque+discard (punch-through)** — pixel-equivalent for
  binary-alpha sprites but WRONG for see-through bodies (translucent supers, hit-flash ghosts, afterimage
  trails, drop shadows come out solid). **Add a real TR-alpha pipeline** `{src-alpha, one-minus-src-alpha}`
  and route non-additive translucent bodies through it.
- Other gotchas: PT alpha-test is a register (PT-only; sprite-gpu hardcodes 0.5 — fine for binary alpha);
  reverse-Z depth (sprite-gpu is a depthless painter — MUST preserve submission order if kept); premultiplied
  vs straight alpha on a transparent overlay; **upload textures BEFORE the composite** or the quad silently
  drops (reads as flicker); HUD y-band classify heuristic can misroute a body part into the HUD pass.

---

## 6. ACCEPTANCE GATE (Phase 3 — gsta-verification-harness)

- Capture the live engine framebuffer with `MAPLECAST_GSTA_SHOT`, **`MAPLECAST_GSTA_SHOT_EVERY=1`** for
  CONSECUTIVE frames (default 30 masks flicker), diff the WebGPU composite vs the engine framebuffer on the
  SAME frozen frame. Numbers (per-pixel / SSIM / per-region), never impressions.
- Sign-off is REFUSED until live pixels match. `senior-re-generalist` reviews for false wins (Phase 4).

---

## Phase-2 RESULT + corrections (2026-08-28 — supersedes the wrong parts of §1/§3)

Built + verified in `mvc-live-skins-quarters` (worktree-isolated). Proof render:
`web/tapecanvas/proof_render_59598061.png` (recognizable, grounded, correctly-scaled + layered fighters +
live HUD). Keystone: `web/tapecanvas/tape-adapter.mjs` (tape frame → maplecast SpriteClient slot/objects/hud
shape; verified by `smoke.mjs`). Live harness: `web/tapecanvas/gpu.html` (imports sprite-client/sprite-gpu
verbatim). Preprocessor: `replay-kit/tape_to_gpujson.py` → `web/tapecanvas/tape.json`.

**LIVE:** bodies (6 slots, even=P1/odd=P2, char from teams, sid&0x7FFF, scaleX=zx/CpsX — no double-apply),
correct anchor, layering (draw_layer=layer[6], no re-sort), procedural HUD (bars/meters/pips/timer/combo).

**CORRECTIONS to this spec (the render expert flagged these against the code — believe the code):**
- **§1 is WRONG about pixels.** Offline LZSS pixel-decode from the DAT is a DEAD END (GFX1 back-references the
  live `0x0CE60000` scratch bank). §1 holds for *geometry* only. **Pixels come from PARTDUMP `_parts.png`
  (emulator dump), not the static DAT.**
- **We drive the EMITTER (part-assembly) path, not a whole-sprite i8 atlas.** No `PLxx.json/.png` whole-sprite
  atlas exists — only `_parts.png/_asm.json/_idx/_lut`. The tape's `sx/sy/zx/zy/layer` map cleanly onto the
  emitter, and **the emitter's own-origin foot pen already places feet on the ground (+4..+20px)** — so the
  "~34px anchor fix" from §1 was specific to a whole-sprite center-bottom bake we don't use; the emitter
  structurally avoids it. `proof_render.py` is a working offline part-compositor if a whole-sprite i8 path is
  ever still wanted (indexed+LUT stays valid for VRAM/costume, but sourced from PARTDUMP pixels).
- **§0 `meter_fill` is a single shared field**, not per-side p1fill/p2fill — a real (TIER-2) tape gap; both
  sides currently drive off the one value.

**EFFECTS — proven correctly-dark, and the tape `objs` need a re-emit (0.3.29):** whole-tape scan =
**0 / 23742** objs resolve into `[0x0CED0000,0x0CEE0000)` and **0** have owner<6. Every obj is effect-class
(cat 1/3/4) with `owner=255`, a CONSTANT `zx=426.625`, and `gfx=H+0x1A8` that never resolves — i.e. the
value-test empirically CONFIRMS `H+0x1A8` is the wrong offset. To light effects, the tape `objs` capture must
be reworked (0.3.29) after the sh4-re probe delivers **(1)** the real Steam Dat_GFX1 offset (value-test on
`H+0x190..0x1C0`), **(2)** owner attribution (node→slot; currently always 255, also blocks cape/projectile
satellites), **(3)** a real per-object scale (obj `zx` is a useless constant). None of this affects the LIVE
bodies+HUD render (those come from the fighter slots + globals, not `objs`).

**KNOWN cosmetic follow-ups (for the differ / polish, not blockers):**
- Life bars render FLAT in the proof; spec §2 wants ANGLED parallelograms — cosmetic.
- Oversized "strip" parts (e.g. PL2A part 3471 = 32×256 → ~490px runaway quad, the f600 "staff") need
  part-level filtering / per-part clip in the bake.
- Costume/exact palette not yet wired for the emitter RGB path — bodies render at the baked DEFAULT palette
  (some parts read dark). Costume LUT-swap needs `setCharLUT`/`setIndexedAtlas` + the costume bodyBank
  (assets `_idx.png/_lut.json` exist; uses the 0.3.28 `costume[6]`).

**sprite-gpu TR-alpha:** patch written (`docs/patches/agent-sprite-gpu-tr-alpha.md`), NOT applied — the render
expert can't write the maplecast repo. Backward-compatible; the parent applies + bumps `?v=`.

## 0.3.29 CAPTURE DELTA — the ONE complete, self-describing release (2026-08-28)

Completeness audit (senior-re-generalist) cross-checked the staged 0.3.28 reader against both replay paths.
**Verdict: 0.3.28 is already re-sim-complete for Path B SETUP and body/HUD-complete for Path A.** The only
gaps are (i) the `objs`/effects layer captured-but-wrong, (ii) three cheap fills, (iii) one clock tie-point.
**Every outstanding "future probe" is replaced by RAW CAPTURE + offline derivation — except ONE contingent
RNG-location task held behind a deterministic proof gate.** This is exactly the "one release, then matches
self-collect, no follow-up live probes" the user asked for.

### fxprobe LIVE reconciliation (two runs: Storm projectile + triple super) — supersedes some audit assumptions
- **owner = `H+0x28` — CONFIRMED (48/52 & 40/40 nodes; misses are ownerless super-flash).** `H+0x28` is a
  u64 == the owning fighter's H-base (`blk+0x3DB8+i*0x738`). This RESOLVES the audit's "owner unproven / widen
  the scan" item — the scan found it. Replaces the failing `H+0x9c/0xc4`.
- **Effect KEY RESOLVED (sh4-re, the +0x44 delta): gfx = `H+0x1A0` (Dat_GFX1) + `H+0x1A4` (Dat_GFX2), NOT
  `H+0x1A8`.** ROOT CAUSE: the whole render cluster maps DC→Steam at a CONFIRMED **+0x44** delta (5 anchors:
  screen 0xE0→0x124, screen_y 0xE4→0x128, drawgate 0x12C→0x170, sid 0x144→0x188, hitflash 0x12E→0x172). The
  staged `H_GFX1_PTR=0x1a8` was **δ0x4C = DC+0x164 = Dat_Pal** (a *palette* handle) — that is precisely why it
  never resolved into a GFX bank (0/23742). Apply +0x44: Dat_GFX1 (DC+0x15C)→**H+0x1A0** (the field that
  clusters by effect type, ~0x1b0x projectile / ~0x150x super-flash), Dat_GFX2 (DC+0x160)→**H+0x1A4**. Confirmed
  by the delta AND corroborated by the live clustering. `blk+0x6CE8` / the `0x0CED` value-test key **only
  3D-class** effects (cat 5-13, NaomiLib) — none were captured; DROP it for sprite-class (cat 1-4).
- **scale = `H+0x130/0x134` was NEVER wrong.** Live reads 1.6667/2.1429 = the CpsX/CpsY magnifier (same as
  bodies). The "constant 426.625" was a **decode artifact**, not a bad offset: 1.6667×4096=6826; 6826÷16=426.625
  exactly — the tape encodes the obj scale ×4096 but read it back ÷16. FIX: keep 0x130/0x134, decode **÷4096**.

### The delta (all APPEND-ONLY; ~2–4 KB gz/match; tapes stay ≈52–54 KB)
**Per-frame (GS_SCHEMA):**
1. `p2_meter_fill` — ship the 4-byte `MET_FILL` window (both P1/P2 u16), derive P2 offset offline. +2 B/frame.
   Fixes the single-shared-`meter_fill` gap.
2. `round_no` (@0x2e617, already read) — +1 B/frame or move to envelope.

**`objs` node rework (fixes gfx/owner/scale):**
3. **`owner = H+0x28`** (u64==fighter H-base, CONFIRMED). Grow the per-node read `0x1b0 → ≥0x1A8`. Ship
   **gfx1 = `H+0x1A0`** and **gfx2 = `H+0x1A4`** alongside the existing `sid` (H+0x188): sprite-class effects
   render like a body via the **(GFX2, sel=sid)** part-assembly, so the renderer needs the bank handle + sid —
   NOT sid alone (effect sids overlap the body sid space) and NOT `0x1a8` (that's Dat_Pal). Scale stays
   `0x130/0x134`, decode ÷4096. DELETE `H_GFX1_PTR=0x1a8` + the `blk+0x6CE8`/`0x0CED` value-test for cat 1-4.
   Corrected constants (from fxprobe): `H_OBJ_OWNER=0x28`, `H_GFX1=0x1a0`, `H_GFX2=0x1a4`.
4. **Per-tape objs CALIBRATION BLOB (the self-describing key):** for the first ~16 frames containing drawn
   effect nodes, dump each node's raw prefix `H+0x00..H+0x1C0` (448 B) + `cat`. ≈28 KB raw → ~1–3 KB gz/match.
   This is what lets us pin gfx/scale (and re-verify owner) OFFLINE from any normal uploaded match, no live
   session, and survive a build shifting an offset. THIS is the mechanism that makes tapes self-describing.

**Envelope (once/match):**
5. `fighter_bases` = the six node addrs `blk+0x3DB8+i*0x738` + `blk` (~56 B) — offline owner ground-truth.
6. `ggpo_sim_tie` = `{blk+0x3CC8, GGPO frontier}` read at the same instant at battle start (8 B) — pins the
   `confirmed_in`↔`frames` clock offset exactly (the Path-B realignment residual).
   (NOTE: the audit's `fx_bank`/blk+0x6CE8 item is DROPPED — disproven live; the calibration blob replaces it.)

**Deferred / NOT in this release** (Path-A best-effort extras Path B renders for free): live rendered palette
(~384 B/frame), 3D-list effects (NaomiLib lists 5-13: drop shadows, some hit-sparks, 3D stage pieces — a
separate list walk).

### Pixel-perfect ceiling (honest)
Path A (poll → re-render) is faithful BEST-EFFORT and structurally cannot be bit/pixel exact (3 ms poller across
rollback bursts; palette reconstructed from glow/flash; 3D-list effects omitted). **Pixel-exactness is Path B:
re-simulate the match deterministically in flycast from the CONFIRMED inputs + char-select anchor.** 0.3.28
already captures everything Path B's SETUP needs (`confirmed_in`, `seat_map`, `build_id`, teams, `assist`,
`costume`, `stage_id`, `anchor`). The two residuals block the PROOF, not the capture: (1) the 8-byte frame
tie-point above; (2) through-combat cross-core determinism — a VERIFICATION gate (run `AB.cmd` / the
through-combat digest on an RNG-exercising match), NOT a capture gap.

### The ONLY genuine live-only item left (contingent)
**Steam RNG generator LOCATION** — unlocated (measured not in blk/exe/arena). Cannot be raw-captured (can't
capture a word you can't find). **Only needed IF the Path-B through-combat determinism proof FAILS**; otherwise
full-forward ROM re-sim reseeds it (srand(1)) and it stays in sync. Held behind the falsifiable gate — do NOT
block 0.3.29 on it.

### Falsification test for 0.3.29 effects (don't declare a false win)
"objs correctly-dark" (0/23742) is a NULL result, not proof effects are off-by-design. After 0.3.29: ≥1 effect
node per super/projectile frame must resolve to a real key AND land within a few px of the engine spark in the
`SHOT_EVERY=1` frozen-frame diff. If it still resolves 0, the key premise is wrong → escalate to static RE
(marvelous2), not another live guess.

## Phase-2 task list (mvc2-sprite-render-expert)

1. Re-extract bodies: indexed i8 + pal128 + per-costume banks, cell-native, true foot-anchor, full roster +
   coverage scan. Wire costume = LUT swap (uses the 0.3.28 `costume[6]`).
2. Effects/sparks: bake `fx_atlas` (RGBA additive) + sprite-class part path; wire the **value-test** key;
   keep effects gated OFF until sh4-re's binding probe certifies the key.
3. HUD: `rip_hud_atlas.py` (FONT.BIN digits) + `rip_portraits.py` (DM01), procedural angled bars + meters +
   timer/combo, all from the 0.3.28 fields; draw LAST, straight alpha.
4. Layering: emit in slot-table order (§4), NO re-sort; composite OP→PT→TR; additive for effects; add the
   TR-alpha pipeline (§5).
5. Hand to Phase 3 (harness) with `SHOT_EVERY=1` frozen-frame diffs.
