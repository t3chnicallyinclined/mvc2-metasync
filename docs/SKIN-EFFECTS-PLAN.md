# Skin ↔ Effects: effect-safe live palette painting

Status: **DESIGN, RE-CONFIRMED** (2026-08-18). Grounded in the marvelous2 DC disassembly (`maplecast-flycast/refs/marvelous2/bank03.asm`, `pl_mem.asm`), the `re_kb`, PalMod's data model, and our own `sync.rs`/`rom.rs`. Fixes: dead effects with skins on (Storm tint, Cable grenade flash, Colossus hyper-armor) + wrong-variant application.

## ★ AUTHORITATIVE per-character data (PalMod / Preppy source, 2026-08-18)

The game does **NOT** re-derive effects at runtime — it **indexes STORED palettes**. PalMod physically writes each one, which is why our block-overwrite kills them. There are **two structurally different effect-palette kinds, needing OPPOSITE handling:**

1. **DERIVED supplementals** — regenerated from the base by copy-then-transform. Characters with a `supp_data_*` entry. → **regenerate from the new skin base** (port `proc_supp`).
2. **INDEPENDENT authored palettes** — projectile/status/effect palettes PalMod never derives (`supp_data` empty or unreferenced). → **PRESERVE byte-for-byte; never overwrite with the skin.**

**Layout (all chars):** 16-color ARGB4444 palettes, `0x20` bytes each. Six button-color groups (LP,LK,HP,HK,A1,A2), `0x100` (8 palettes) apart. **Main Color = slot `0x00` of each group.** After the 6 groups: a shared **"Status Effects"** block (Burning/Shocked/Kinetic Charge — fire/electrocuted tints, INDEPENDENT, preserve), then **"Extras."**

**`proc_supp` transforms** (`SuppProc.cpp`): each `SUPP_NODE` copies the base then applies `MOD_LUM d,n,amt` (HLS lightness += amt/100), `MOD_SAT` (S += amt/255), `MOD_WHITE` (set pure white), `MOD_TINT` (add r/g/b ARGB4444 steps), `MOD_COPY` (memcpy).

| Character | Effect the user reported | Kind | Where | Fix |
|---|---|---|---|---|
| **Cable** | **grenade** (+ gunfire, Viper Beam, Psy-Charge) | **INDEPENDENT** (`supp_data` empty) | slot `0x03` = button_base+`0x60` (per-costume) | **write only Main Color `0x00`; PRESERVE `0x01–0x05`** |
| **Colossus** | **hyper-armor flash** | **DERIVED** | Extras `0x09–0x0E` + `0x22–0x28` (per button, stride 32) | regenerate: copy base + `MOD_LUM` ramp + moving `MOD_WHITE` |
| **Storm** | damage/**lightning** | **MIXED** | body-tint `0x19+` = DERIVED (`MOD_LUM` +7/+17); lightning projectile/wind/super `0x09–0x0B,0x0F–0x17` = INDEPENDENT | regenerate body-tint; PRESERVE the projectile lightning |
| **(every char)** | on-fire / electrocuted | INDEPENDENT | "Status Effects" block after the 6 groups | PRESERVE |

**⟹ The correct paint is per-character, NOT uniform:** write the **Main Color slot(s)** (base) → PRESERVE independent palettes → REGENERATE derived supplementals. Minimum-viable = write Main Colors only, preserve everything else (all effects return, stock-colored). Full fidelity = also regenerate the derived rows from the skin base.

Steam ROM addresses captured: Storm main LP `0x49d9e80`; Cable main LP `0x3c2d5a0` (grenade `0x3c2d600`); Colossus main LP `0x5235a60` (armor-shine Extras from `0x5236160`). PalMod files saved in scratchpad.

## 0. Root cause (CONFIRMED — and now explained per-character)

`paint_live` writes the skin into **every** "real" 32-byte row of the fighter's DatPal block. That block is not one palette — it's the **DAT source palette table**: the base color banks **plus** the resident effect/derived palettes. Effects that **swap** to a resident alternate row (hyper-armor, hurt tint, character tints) then render the *skin* instead of the effect → the effect visually disappears. Baking doesn't break effects because `bake_palette` writes **only the base bank** and leaves effect rows stock. **The fix is to do the same live: paint only the base banks of the selected color; leave the effect rows.**

## 1. The three palette layers (do not conflate)

| Layer | What | Where | We touch? |
|---|---|---|---|
| **1. DAT SOURCE block = `DatPal`** | table of 32-byte ARGB4444 rows: base color banks + effect rows | fighter `+0x4c` (Steam) / `+0x164` (DC). Set by loader: `DatPal = dat_base + *(dat_base+0x08)` | **YES — paint here** |
| **2. Working/rendered buffer** | game re-derives the rendered palette here **every frame** from Layer 1 | DC global `0x8C2659DC` + `player[0x12e]*0x30`; each desc `{+0x08 blend flag, +0x10 = 16 colors}` | no (game owns it) |
| **3. PVR PALETTE_RAM** | GPU-facing copy | `pvr_regs+0x1000`, bank `16*(pair+1)+8*side` | no (Steam path) |

**Layout inside Layer 1 (the key fact):**
- **Base color banks** = `DatPal + color*0x100` — each of the **6 button-selected colors** (LP/LK/HP/HK/A1/A2) occupies `0x100` bytes = **8 banks × 32 bytes**. `color` = **`cl+0x6` (OFF_COLOR)** — the field we already read per fighter.
- **Effect/derived rows** live in the **same block at higher offsets** (the hurt/hyper/tint region; `+0x300`/`+0x600` biases seen in the disasm).

So: **base = `[color*0x100, +0x100)`; effect = everything else.**

## 2. How effects work — SWAP + COMPUTE (CONFIRMED)

Dispatcher `loc_8c035162(player, effect_id 0..0x0A)`, called from ~50 sites with immediate effect ids:

| id | effect | reads | type |
|---|---|---|---|
| 0 | normal | base banks | swap(base) |
| 1 | hit/white-flash | base + per-char tweak | swap+compute |
| 3 | hyper-armor (Colossus/Zangief-class; gated by `Buff_HyperArmor`) | **resident alternate row** | **SWAP** |
| 4/5/6/7 | super-freeze / brighten | **base row × brightness** | **COMPUTE** |
| 8/9 | white / green silhouette | fill const | compute |

- **SWAP effects** read a **resident row** in `DatPal`. Clobber it → effect shows the skin → **disappears**. (Storm/Cable/Colossus.)
- **COMPUTE effects** read the **base** row and transform it. Skin the base → they come out **skin-tinted for free** (why baking looks right).

This reconciles with PalMod: the resident swap rows ARE PalMod's **supplemental palettes** — deterministic transforms of the base (`MOD_LUM`/`MOD_TINT`/`MOD_SAT`/`MOD_WHITE`/`MOD_COPY` in `mvc2_supp.h`), pre-stored, not runtime-generated.

## 3. Addressing model — signature-free, slot-native

Signatures are **redundant for targeting** and fail on same-variant mirrors. Address every skin by slot instead:

```
locate array (pointer-follow *(exe+0xac6ef0)+0x3f24 — deterministic)
for slot i in 0..6:
    cl      = base + i*0x738
    cid     = *(cl + 0x554)          // character
    variant = *(cl + 0x6)            // which of the 6 colors (OFF_COLOR)
    side    = (i even) ? P1 : P2     // team ownership — fixed, never flips on cross-ups
    mine    = (side == localPlayerNum-side)
    skin    = mine ? myLoadout[cid] : oppLoadout[cid]
    datpal  = *(cl + 0x4c)
    // EFFECT-SAFE WRITE:
    write skin base into  datpal + variant*0x100  (0x100 bytes = 8 base banks)   // Phase 1
    (Phase 2) regenerate the resident effect rows from the new base via proc_supp
```

Slot parity = team ownership (not screen position → survives cross-ups). Mirror Magneto-vs-Magneto: slot 0 = P1's, slot 1 = P2's, `localPlayerNum` says which is ours. No signature can distinguish two identical Magnetos; the slot index can.

## 4. The fix, ranked (from the SH4 analysis)

- **(B) BEST — paint only the selected color's base banks.** Change `paint_live` from "every `is_real_row` in `0x2000`" to "the rows in `[color*0x100, +0x100)`" (`color = rpm_u8(cl+0x6)`). Swap effects read untouched rows → stock effect colors; compute effects read the skinned base → skin-tinted. **Matches the bake result. Cheaper** (one bounded write vs a 256-row scan). Keep the per-poll re-apply + stale-DatPal read-back gate (DatPal relocates under rollback).
- **(A) FALLBACK if the offset rule mis-fires on Steam — active-set match.** Read the currently-rendered banks (PVR bank `16*(pair+1)+8*side`, or the working buffer) → find those exact palettes in the `DatPal` block → those offsets are the base rows; paint only them. Layout-agnostic, provably effect-safe.
- **(D) HIGHEST FIDELITY (later) — regenerate effect rows.** Port PalMod's `proc_supp` (per-character supplemental table + `MOD_*` transforms) to regenerate the resident swap rows from the new skin base → swap effects become **skin-tinted** too, not just stock. Or hook the recompiled `loc_8c035162`.

## 5. Phased build

- **Phase 1 — base-banks-only paint (the 80/20).** Implement (B). Effects return immediately (compute = skin-tinted, swap = stock colors — identical to what baking gives today). Small, cheap, low-risk. → Storm/Cable/Colossus effects come back.
- **Phase 2 — effect-row regeneration (full fidelity).** Port `proc_supp`: for each character, regenerate the resident effect rows from the skin base with the right `MOD_*` transform so swap effects are skin-tinted. Ship per-character as the tables land (start with the named ones: Colossus, Storm, Cable, Shuma).
- **Phase 3 — slot-native render hook (optional).** Feed the render hook the array-derived `slot→{cid,variant,side,palette}` map so it repaints by slot at round-start instead of by content signature — kills the last signature dependence + the round-start lag.

## 6. Live verification protocol (before shipping Phase 1)

On the running Steam build (build the probe capture):
1. Dump `0x2000` at `*(cl+0x4c)` for a fighter.
2. Change the **color** selection (different button) → re-dump. Confirm the **rendered/base rows shift by `0x100`** (proves base = `color*0x100`, and that DatPal is the block base, not already color-offset).
3. Snapshot, then **force an effect** (super freeze, get hit, Colossus armor move) → watch which working-buffer banks change; the source rows they pull from = the effect rows. Anything never rendered in neutral = safe to skip.
4. Confirm effect rows sit **above** the base region.

## 7. Effect-active flags (for Phase 2 / gating)

- **`hit_flash` = Steam `+0x856` (u8)** — brief 0xFF pulse on contact (the pal-effect). CONFIRMED.
- **`Buff_HyperArmor` = DC `0x202`** — gates the hyper-armor swap. Steam offset TBD (find by watching a byte → 1 during armored moves).
- Layer-2 descriptor `+0x08` blend/mode flag (1/2) marks additive/silhouette banks.

## 8. Offset reference (Steam build)

| Field | Offset | Note |
|---|---|---|
| fighter stride | `0x738` | even slot = P1 team, odd = P2 |
| `OFF_CHARID` | `cl+0x554` | character id |
| `OFF_COLOR` | `cl+0x6` | selected color/variant (0–5) — indexes base bank `color*0x100` |
| `OFF_DATPAL` | `cl+0x4c` | → DAT source palette **block base** |
| `hit_flash` | `cl+0x856` | effect-flash pulse |
| array locator | `*(exe+0xac6ef0)+0x3f24` | deterministic pointer-follow |
| `localPlayerNum` | `exe+0xac7230` | 0=P1, 1=P2 (your side) |

Base bank of the active fighter = `*(cl+0x4c) + (*(cl+0x6))*0x100`, `0x100` bytes. **Paint here; leave the rest.**
