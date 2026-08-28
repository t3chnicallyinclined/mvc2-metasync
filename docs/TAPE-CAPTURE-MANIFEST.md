# MvC2 Steam-Tape Capture Manifest — the complete data contract

> **Purpose:** the definitive, no-guessing list of exactly what the agent must read so a browser replay
> is pixel-perfect. Every field is CONFIRMED with a cited offset, or listed under OPEN with how to close
> it — nothing inferred silently. Produced by the sh4-re expert from `marvelous2` + `re_kb` + the block map,
> 2026-08-27. This is the agent's target schema (0.3.28). Companion: [STEAM-TAPE-RENDER-HANDOFF.md](STEAM-TAPE-RENDER-HANDOFF.md).

## Ground rule — the delta ladder (so every offset is auditable)
A fighter's Steam `blk`-relative base `H = blk+0x3DB8 + slot*0x738`. A DC field at DC-offset `d` maps to
`H + d + δ(d)`, δ stepping `0x00 → 0x1C → 0x44 → 0x158 → 0x194` (`mvc2-dc-steam-block-map`, closes to the
byte). A DC offset **bracketed by two anchors with no step between** is CONFIRMED-by-bracketing; one that
**spans a step** is OPEN. Live-confirmed anchors: DC `+0x000`(δ0)·`+0x034/38,+0x05C/60`(δ0x1C)·
`+0x0E0/E4,+0xEC/F0,+0x110,+0x12C,+0x144`(δ0x44)·`+0x420/24`(δ0x158)·`+0x52C/52D`+stride(δ0x194).

## THE SCHEMA (0.3.28)
Per fighter (×6) unless noted. STATIC = envelope once; PER-FRAME = per tape frame. Delivery invariant:
everything except costume/char_id is active-only + gate-gated (skip `gate==0`, `sprite_id==0xFFFF`) → small wire.

| Field | Bytes | Cadence | CONFIRMED offset + cite | Note |
|---|---|---|---|---|
| **LOCKED (0.3.27) — already captured** | | | | |
| sprite_id | u16 | PER-FRAME | `H+0x188` (DC+0x144+δ0x44) | mask `&0x7FFF`; `0xFFFF`=blank⇒skip. THE render key |
| screen_x / y | 2×f32 | PER-FRAME | `H+0x124` / `H+0x128` (loc_8c03093c) | engine screen coords, 640×480 |
| render_scale_x / y | 2×f32 | PER-FRAME | `H+0x130` / `H+0x134` (DC+0xEC/F0) | = CpsScale×objScale÷(camZ/812.36); ship raw. Size = draw cell × `zx/CpsX` |
| facing | u8 | PER-FRAME | `H+0x154` (DC+0x110) | 1 bit; authoritative xflip is DC+0x1D2 if lag shows |
| draw_gate | u8 | PER-FRAME | `H+0x170` (DC+0x12C) | `!=0`⇒drawn (an ENABLE, not a cull) |
| hp / red_hp | 2×u16 | PER-FRAME | DC+0x420/424 | HUD reconstructs from these |
| char_id | u8 | STATIC | `H+0x6C0` (DC+0x52C) | → which `PL{hex}` atlas |
| effects draw-list | u64×N + u8×16 | PER-FRAME | handles `u64 @ blk+0x2F4D0 + L*0x300 + i*8`, counts `u8 @ blk+0x324D0`, 16 layers | active-only; z-order = layer L |
| pool node (per handle) | via fighter H-offsets | PER-FRAME | node = fighter-struct prefix | non-fighter handles read verbatim |
| camera eyeX / eyeY | 2×f32 | PER-FRAME | `blk+0x6914` / `blk+0x6918` | zoom `blk+0x691c` is CONSTANT — do NOT capture |
| **NEW in 0.3.28 (CONFIRMED)** | | | | |
| **costume / color** | u8 | **STATIC** | `H+0x6C1` (DC+0x52D+δ0x194; rr-sprite measured =1; wire ships this copy) | 3 bits (0–5). Client LUT-swaps `banks[j*8:j*8+8]`. Re-read at round start |
| **fighter layer** | u4 | PER-FRAME | draw-list reverse-lookup: the `L` whose handle == `blk+0x3DB8+slot*0x738` (alt byte `H+0x24`, δ0) | free from the list already walked; interleaves bodies with pool objects |
| **hit-flash / hurt selector** | u16 | PER-FRAME | `H+0x172` (DC char+0x12E+δ0x44; 3 corroborating sources) | offset CONFIRMED; value→visual table is OPEN-A. Idle ≈`0x10/0x18` |

## OPEN — do NOT ship in the main table until confirmed
- **OPEN-A — hit-flash value→visual table.** Offset `H+0x172` + mechanism CONFIRMED, but the on-hit
  `0x10→{0x01..0x0A}` transition was never live-captured. **Cheap close (recommended, zero new field):**
  the dominant white flash fires on **hp-drop** (already captured) → trigger it client-side from the hp
  decrease; the **super-aura** glow is a separate pool-node effect **already in the 0.3.27 draw list**. So
  `H+0x172` is only needed for the exact hurt-bank *tint* — polish. Full close: probe `H+0x172` during a
  live combo and map each value to its overlay.
- **OPEN-B — effects owner Steam offset.** DC owner `+0x80/84` spans a delta step ⇒ Steam is **H+0x9C or
  H+0xC4** (a **u64** on x86-64). The agent's raw `H+0x80` reads a wrong field → the `0xFF`. **Close (one
  read-only scan):** for each non-fighter handle, find the node offset holding a u64 == a fighter base
  `blk+0x3DB8+slot*0x738`. NOTE: many effects are genuinely owner-less globals (correct model, not a bug);
  route by `category @ H+0x3` — `{0x05,0x06,0x0B,0x0C,0x0D}`=body/cape, `{0x07,0x08,0x09}`=projectile/effect.
- **OPEN-C — `char_pal_effect` DC+0x40 (PALF) is NOT the hit-flash field.** A higher-level gate; the
  renderer reads `+0x12E`, not `+0x40`. Do NOT ship it.

## Effects textures — the binding key (why effects don't draw yet)
Effect textures are selected by a **directory index, not sprite_id**: `effect_idx = (node+0x15C − dirBase)/0x10`,
`dirBase = *(0x0CED0008)`. Our `objs` ships `sid`(=node+0x144), which does NOT index the effect atlas. So the
agent must ALSO capture the effect binding key per pool node (`node+0x15C` + per-frame `dirBase`, or the
precomputed idx) — Steam offsets being confirmed by the sh4-re expert (follow-up). AND this-match effect
textures are needed (sels 0–251 offline-rippable; per-char/high-bank ones dynamic). Until both land, effects
are captured (nodes) but not renderable — shipped OFF rather than faked.

## Close-out actions (read-only, gated OFF, no rebuild)
1. `gsta-verification-harness`: owner u64==fighter-base node scan → lock H+0x9C vs H+0xC4 (OPEN-B).
2. `gsta-verification-harness`: `H+0x172` transition during a live combo → lock the hit-flash value table (OPEN-A).
3. `mvc2-sprite-render-expert`: this-match effect atlas (directory-idx keyed) + costume LUT + hp-drop white-flash.

## 0.3.28 FINAL — reconciled from the renderer + RE completeness audits (2026-08-28)

Both audits (mvc2-sprite-render-expert render read-set + mvc2-sh4-re-expert disasm) closed. The full
capture set for the ONE final migration. Everything CONFIRMED unless marked. `H = blk+0x3DB8+slot*0x738`.

**Fix (no column):** **confirmed positions** — kills the shake. Rule (cited, deterministic): poll every ~3ms,
key by `blk+0x3CC8`, last-write-wins; **(a)** emit tape frame F only once `maxSeen ≥ F+8` (rollback bounded
to 8 → F is then final); **(b)** on clock-DECREASE, tight-loop RPM re-read (no sleep) until the clock climbs
back, so a resim burst's corrected values overwrite the predictions. Buffer 9 frames (ring 16). (a) removes
the shake with no probe; a live probe is only needed to certify "confirmed-exact", not to fix the wobble.

**New PER-FIGHTER columns:**
| Field | Steam offset | S/F | Cite / note |
|---|---|---|---|
| costume/color | `H+0x6C1` (u8) | STATIC | recolor is renderer-side (costume-indexed LUT); byte is captured |
| hit-flash | `H+0x172` (u16) | PER-FRAME | OPEN-A value table (probe/hp-drop) |
| super-glow `char_pal_effect` | **`H+0x5C`** (u8) | PER-FRAME | DC+0x40, CONFIRMED-by-bracketing δ0x1C; drives super-freeze brighten |
| fighter layer | draw-list reverse-lookup | PER-FRAME | captured; whole-sprite path hardcodes body z, emitter path uses it |
| sprite_id | `H+0x188` u16 **RAW** | PER-FRAME | ⚠ keep bit15 (rasterization mode) — mask `&0x7FFF` only at atlas-index time |

**New OBJS (pool node) sub-fields** — already capturing sid/x/y/scale/facing/cat/layer; ADD:
| Field | Steam offset | Cite / note |
|---|---|---|
| effect GFX ptr | **`H+0x1A8`** (u64) | node+0x15C → Steam H+0x1A8 CONFIRMED via loader `FUN_14060D100` (64-bit). The effects-atlas/additive routing signal. |
| owner→slot | inline SCAN of `H+0x9C` & `H+0xC4` (u64) vs the 6 fighter bases | ladder-ambiguous → resolve by scan; owner-less globals legitimately match neither (route by `cat`). |
| blend | DERIVED from `cat` (`H+0x03`, already captured) | `{01,05,06,0B,0C,0D}`=body/cape opaque/PT, `{07,08,09}`=projectile/effect additive. No separate byte. |

**New GLOBAL (HUD) columns** (known reader offsets): round **timer** (`0x2e61c`), **round-win** count
(`0x2e61a`/set-score) — join the captured meter (`m1/m2/mfill`) + combo (`cd`). 

**OPEN (capture the input now, resolve later — NO re-record needed):**
- **Effect texture INDEX** — `H+0x1A8` points into the arena, not a `0x0CEDxxxx` addr, so the DC
  `idx=(ptr−dirBase)/0x10` formula does NOT port. Capture the raw `H+0x1A8` pointer now; resolve the
  `pointer→idx` map via a Ghidra pass on the Steam effect loader OR a one-time match-load directory-dump
  probe. Effects render OFF until then. NOT a schema blocker.
- **Owner offset** — resolved by the inline scan above (self-checking vs the 6 fighter bases).
- **Confirmed-position residual** — (a)+(b) fixes the visible shake; a live probe on a laggy match
  certifies the "exact" claim (the fully-robust source is an in-process hook at `FUN_140620F10`, out of scope).

**Explicitly NOT added — captured implicitly (do NOT add fields):** super-freeze/hitstop (sid/atimer/px
stop advancing), screen-shake (folds into eyeX/eyeY→sx/sy), stage scroll (stage_id + eyeX/eyeY). Optional:
stage-background zoom `blk+0x6928` (INFERRED, stage-only, low priority); super-aura overlay `char+0x1a4` (low).

## Sources
`_marv_re/memory/pl_mem.asm` · `maplecast-flycast/re-catalog/00-README.md` (pool node, owner+0x80, layer@+0x24) ·
`docs/MVC2-RECONSTRUCTION-SPEC.md` (+0x12E vs +0x40) · `docs/GSTA-MAPPING-HANDOFF.md` (wire ships +0x52D copy) ·
`re_kb/{02_char_struct,33_replica_live_render_field_gaps,09_objs_effect_blend,40_replica_emitter_effects_fx_atlas}.surql` ·
memory `[[mvc2-dc-steam-block-map]]` (delta ladder), `[[rr-sprite-render-pipeline]]` (H+0x6C1, H+0x172).
