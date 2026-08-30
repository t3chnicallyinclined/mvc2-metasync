# MvC2 REPLAY ENGINE — system design

> **⚡ CURRENT STATUS — 2026-08-30: the resim → real-TA → WebGPU render pipeline WORKS.** OUR resim's real
> `serverPublish` TA renders clean (bodies + effects + additive blend + 3D stage + HUD) on the tapecanvas
> WebGPU renderer, no flycast mirror — interactive player `web/tapecanvas/play_zcst.html`.
> **→ [`docs/RENDER-ACCURACY-PROGRAM.md`](RENDER-ACCURACY-PROGRAM.md) is the SSOT for how it's done.**
> This doc is the original **Path-A state-tape/emitter** design (still the ships-today fallback); the
> shipping ground-truth render is the real-TA path above.

> **Lead:** Steam RE (synthesis). **Contributors:** mvc2-sprite-render-expert (capture + sprite pipeline),
> mvc2-sh4-re-expert (memory/offset ground truth), flycast-internals-expert (render architecture),
> gsta-verification-harness (proof), senior-re-generalist (skeptic).
> **Status:** DESIGN IN PROGRESS. Round 1 (expert raw material) running; §§ marked ⏳ fill from their docs.

This is the design for a **record-once, replay-anywhere** MvC2 match engine: an agent captures a real
match into a compact tape; a browser renders it faithfully with no game installed. It is deliberately
NOT re-simulation (that path is parked — see `STEAM-GGPO-INPUTQUEUE.md`); this is a **state tape**:
record what was drawn each frame, redraw it.

## 0. Three layers, one contract

```
   CAPTURE (agent, Rust)              TAPE (data contract, JSON+gz)         REPLAY ENGINE (browser, WebGL2)
   reads game memory per frame   ->   append-only columnar schema      ->  indexed-colour, layered, batched
   fighters + satellite pool          per-frame draw list + envelope        stage + fighters + effects
```

The **tape is the contract**. The fleet migrates onto the tape; the renderer is rebuilt without
touching a client. Append-only schema ⇒ the fleet migrates **once**, later columns self-update on.

## 1. Design principles (from what we PROVED today)

1. **Record the engine's own numbers, never reconstruct.** Screen coords `H+0x124/0x128`, scale
   `H+0x130/0x134` — validated live to 0.23px median vs reconstruction, and CORRECT where
   reconstruction breaks (round transitions, edge clamps). The renderer never does world→screen math.
2. **Indexed colour is the render primitive.** R8 index atlas (1 byte/pixel) + 128-entry palette LUT
   resolved in the fragment shader. Proven pixel-correct and memory-cheap. Recolour = a palette upload.
3. **The engine's own draw list is truth — don't sort, don't guess order.** 16 priority layers,
   real order. The renderer is a *dumb executor* of the engine's draw decisions.
4. **Clock = `blk+0x3CC8` (GGPO `_framecount`). Never search for it.** Validated 60Hz, dense.
5. **Ship numbers, pull art.** The tape carries a `stage_id` and per-object `sid`/`cid`; the ART
   (character + stage sprites) is extracted OFFLINE from the Steam Collection `.arc` into atlases and
   lives with the renderer. Tapes stay ~KB, not MB.
6. **Append-only, forever.** New columns go at the END; consumers read by name and fall back when
   absent. This is what makes "migrate the fleet once" safe.

## 2. THE TAPE — data contract

### 2a. Envelope (once per tape) — CURRENT
`ver, schema, ts, id, match_key, reporter, session_id, match_index, p1_team[3], p2_team[3],
winner, loser, side, local_pn, seat_map[4], rollbacks, build_id, `**`stage_id`**`, assist[6],
frame_count/first/last/span, set_start/end, anchor(+blk/arena/frame/hash), select_in`

### 2b. Per-frame columns — CURRENT (character-complete, PROVEN)
`[frame, p1_in, p2_in, kcode, hp[6], px[6], py[6], p1_meter, p2_meter, meter_fill,
combo_dealt[6], combo_recv[6], vx[6], vy[6], red_hp[6], facing[6], hitstun[6], drawn[6], sid[6],
atimer[6], eyeX, eyeY, ground, seat_in[2], `**`sx[6], sy[6], zx[6], zy[6]`**`]`

Renders all 6 fighters exactly (feet-on-floor ≤1px, 36/36 harness frames PASS).

### 2c. Per-frame DRAW LIST — ✅ SPECED (sprite-render + sh4, landed 2026-08-27)
The engine's own draw list enumerates EVERY drawn object in priority order — fighters AND
projectiles/assists/hitsparks/super-flashes:
```
COUNTS   = blk + 0x324d0            // 16 × u8, one per layer
DRAWLIST = blk + 0x2f4d0            // + L*0x300 + i*8  →  u64 ABSOLUTE guest pointer to the object node
```
- **The entry is a POINTER, not an index** (CONFIRMED live). Deref → the node's H-base. The first
  `0x280` bytes of a satellite node are a **PREFIX of the fighter struct**, so the SAME field reads
  (`+0x124/128` screen, `+0x130/134` scale, `+0x154` facing, `+0x170` gate, `+0x188` sid) run verbatim
  on effects. **Capturing effects is not a new reader — it's walking one pointer array + reusing the fighter read.**
- ⚠ derive `blk` from the SAME located fighter base (`base - BLK_BACK`), never a fresh `MATCH_PTR` deref,
  or the draw list and the fighters can come from different (rollback) blocks and desync the frame.
- **Per-frame walk:** 1 read of COUNTS (16B) + 1 read of DRAWLIST (0x3000B) + one 0x200 read per live
  object (~10-30 typical, ~40 in a super) — inside the 3ms budget. (Optimization: once the pool base is
  pinned, one 178KB `blk+0x3DB8..0x2f4d0` read covers all fighters + pool with zero per-handle syscalls.)

**Tape addition (append-only at the FILE level, not the columnar row):** a new top-level `objects`
array parallel-indexed to `frames`, with its own `obj_schema`:
`[L, who, nid, sid, sx16, sy16, sf, zx, zy, face, cat, own, gfxp]` (sx16 = round(sx*16), sub-pixel;
`sf`=0 means resting CPS scale so zx/zy omit; `who` 0..5 = fighter slot else -1; `cat` +0x03 routes
character-art vs effect atlas; `own` = owning fighter for a projectile's palette; `gfxp` resolves
satellite asset ownership offline). **KEEP the 6-slot columns too** — HUD needs stable per-slot
indexing, 2200+ old tapes depend on them, and each `who∈0..5` object cross-checks the columns (a
mismatch is the different-block desync guard). Old consumers read `frames`/`schema` unchanged.
Size: **+0.6–1.1 MB gz** on the ~0.5 MB char tape (≈2–3× total; a binary blob halves it later).

### 2d. Palette + blend
- **Palette:** costume `H+0x6C1` (u8) — a LUT-bank select; **missing column today** (atlases baked at
  costume 0, live play uses others → wrong colors). Add it. Effects have no `+0x6C1`; they carry their
  own Dat_Pal pointer `H+0x1B8`.
- **Blend:** ⚠ **UNLOCATED** — the SH4 expert confirmed it is NOT a struct field; the opaque/additive/
  alpha choice is decided INSIDE the PVR polygon submit, keyed on the render path (`cat` +0x03). SHIP a
  flagged heuristic — `cat==0` normal, `cat!=0` additive — and resolve the true rule in phase 2 via the
  flash-frame differential or a D3D11 blend-state hook (flycast-internals). The tape records `cat`, so
  the interpretation can change without re-capturing.

### 2e-bis. THE PIXEL-PERFECT PATH IS GROUNDED (2026-08-27) → `CONFIRMED-TAPE-AND-FLYR-REPLAY.md`
The flycast-NAOMI re-sim path is proven viable and de-risked, via a determinism test + a source study
of flycast-dojo that CONVERGE:
- flycast reproduces the Steam engine's RAW sim state (px/py/vx/vy/hp/facing) **bit-exact** at a
  constant −6-frame offset → FP faithful, RNG in sync, emulator pacing ruled out (all on raw state).
- The −6 skew is a TAPE artifact: our tape records the PREDICTED latch (`G+0x218`) with rollback-laden
  indexing. dojo's `.flyr` records only CONFIRMED inputs and replays PURE FORWARD (zero rollback) — no skew.
- FIX = record confirmed inputs from the InputQueue ring (already located, `STEAM-GGPO-INPUTQUEUE.md`),
  keyed by frame from 0; anchor is flycast's OWN NAOMI char-select state (Steam savestate is NOT
  loadable cross-core); `srand(1)` reseeds RNG by running the ROM. Convert tape → v3 `.flyr` → dojo's
  proven replay path → maplecast TA-mirror render. The "fork" is small, not a from-scratch engine.
- ⚠ GATE (still open): through-combat determinism is cross-core, must be POSITIVELY proven on a
  confirmed-input tape (exact through the first super's RNG), never assumed. Path 1 primary meanwhile.

### 2e. The TA-stream / function-extraction path — EVALUATED, deferred to phase 2
Steam MvC2 DOES build a real PVR/TA polygon stream (draw-list walker `FUN_140620F10` → emitter → PVR
submit → D3D11) — the NAOMI render lineage is intact. Capturing that stream would be PIXEL-PERFECT
(exact blend/z included). BUT: the step/render functions cannot be cleanly extracted (they ARE the
whole recompiled game); the only route is a MapleCast-style in-process HOOK of the PVR submit, which
needs code injection per client. The draw-list READ (§2c) gets ~95% of it for the cost of memory reads
and no injection — so it is the path. The PVR-hook is documented as the phase-2 upgrade if blend
fidelity demands it (it's the one thing the read can't cleanly get).

## 3. THE CAPTURE — agent (Rust, `RetroReceipts-agent/agent/src/reader.rs`)

- Per frame in `read_gs_row`: the 6 fighter slots (done) + walk the draw list `blk+0x2f4d0` layers
  0..15, counts `blk+0x324d0..DF`, emit each drawn object. ⏳ exact walk from the sh4/sprite experts.
- Cost budget: the 6-slot read is ~18 RPM/frame; the pool adds N. Must stay within the 60Hz loop.
- Clock/anchor/inputs unchanged. `stage_id` added (envelope).
- Append-only: every new field lands AFTER `seat_in`/existing columns.

## 4. THE REPLAY ENGINE — browser (WebGL2) — ⏳ (flycast-internals lead)
→ `maplecast-flycast/replay-file-lane/RENDERER-ARCH.md`

- **Keep:** indexed-colour R8 + palette LUT; engine screen coords; bottom-centre anchor; game-space atlas.
- **Drop (live-renderer cruft):** world→screen reconstruction, garbage-camera filter, clean-run
  clipping, game-space/native scale auto-detect — all workarounds for broken tapes we no longer make.
- **New:** stage as layer 0 (art from Collection arc by `stage_id`); the full draw list composited in
  real layer/z order; per-object blend state; batched draws (per-atlas / per-blend) for 60fps + scrub.
- Timeline driven by the tape's real frame numbers; scrub/step/speed.

## 5. STAGE
Tape ships `stage_id` only (§2a, done). Art extracted offline from the Steam Collection `.arc`/bin
into a stage atlas (same pipeline as character sprites), rendered as the bottom layer. ⏳ extraction
path + does the stage draw through the same 16-layer list or a separate background pass (sh4/sprite).

## 6. OPEN QUESTIONS (resolved in the round-3 discussion)
- Draw-list entry shape: pointer vs pool index; how to reach an object's render fields from it.
- Keep the 6 fighter columns AND the draw list, or derive fighters from the draw list? (migration cost)
- `blend` offset — found, or ship with an opaque default and add later?
- Layer/z compositing order + within-layer rule (painter's vs depth buffer).
- Per-frame byte budget with the full pool (char tape ≈ 500KB gz / 5000 frames; +pool = ?).
- Stage: shared draw list vs separate background pass.

## 7. VERSIONING / MIGRATION
- Character tape (§2b) is the **migration floor** — release now, fleet self-updates off 0.2.6.
- Draw list + palette/blend (§2c/d) APPEND in the next agent version — no re-migration.
- Renderer is independent of the fleet — rebuilt and redeployed server-side any time.
