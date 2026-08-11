# Steam MvC2 fighter-struct map (the context dictionary)

Live reverse-engineering of the **Steam "MARVEL vs CAPCOM Fighting Collection"** fighter struct, so the
MetaSync capture reads the COMPLETE per-frame ground-truth state (not just the ~10 fields we had) — the rich
state a behavior-cloning policy needs (velocity, hitstun, cancel windows, action-state…). This is the first
full map of this build's fighter struct.

Branch: `re/steam-struct-fields`. Findings method + expert protocol: `scratchpad/STEAM_RE_PROTOCOL.md`.

---

## How to read the struct

- **Slot** `cl = live_array + i*0x738`, `i=0..5`, order `[P1C1, P2C1, P1C2, P2C2, P1C3, P2C3]`.
- ⚠ **The fighter's fields extend PAST the 0x738 stride** (e.g. health +0xb44). So slot i's fields overlap
  slot i+1's address range — read a WIDE window (0..0x1400 from the array base covers slot0 + slot1 fully),
  and treat everything by ABSOLUTE offset from the array base: field X of slot i = `array + i*0x738 + X`.
- All offsets below are **slot-relative** (add `i*0x738`).

## ⚠ Finding the live array (do NOT hardcode) — use INPUT-DRIVEN liveness

The fixed anchor (`flycast_base + 0x10b33fc8`) can point at a **FROZEN/stale copy** (post-match, or a training
reset copy). ⚠ **"most changing bytes" is NOT enough** — a stale copy still runs its idle breathing animation
(30+ changing bytes) while its position is dead. Training RESETS re-allocate the controlled array and can move
it OUT of the signature-scan window entirely, leaving only stale copies findable.
**Robust method: the live array is the one whose VELOCITY/POSITION responds while the player moves.** Have the
player walk+jump, sample all candidates, pick the one with real posX/posY/velocity variance (idle animation
alone → rejected). Tool: `scratchpad/find_live_array.py` (velocity-based). Then record from that explicit
address (`struct_recorder.py <out> <secs> 0x<addr>`). ✅ This is a TRAINING artifact — in a real match the
anchor is correct (proven by working captures); the app's match-load gate + frame-counter dedup already reject
stale copies (a frozen copy never shows a match starting / never advances its counter).

## Mode invariance

The offsets here are the **compiled struct layout → identical in training / ranked / vs / arcade.** Mode
only changes game logic (rollback, AI) and the array BASE + which-copy handling, not the field layout.
⚠ TO VERIFY in a ranked match: the **input** field (`+0x4FC` read 0 in training on the copy tested; worked
in netplay) and a spot-check of 2-3 fields.

---

## CONFIRMED offsets

### Already known (pre-existing, reconfirmed)
| field | offset | type | notes |
|---|---|---|---|
| char_id | +0x554 | u8 | Ryu=0, Cable=23(0x17), Storm=42, Sentinel=52 |
| color | +0x6 | u8 | palette/costume variant |
| DatPal | +0x4c | u32 | WB ptr 0x10000000..0x14200000 (skin paint target) |
| health | +0xb44 | u16 (of u32) | 0..144 |
| combo_dealt | +0x1ca | u16 | (⚠ read 0 for attacker in one test — recheck) |
| pos_x | +0x61c | f32 | world X |
| pos_y | +0x620 | f32 | world Y |
| input | +0x4fc | u16 | ⚠ 0 in training on the tested copy; live in netplay — VERIFY |
| assist_type | +0x4e9 | u8 | alpha=0 / beta=1 / gamma=2 |
| meter (array-global) | array+0x2e636 | u8 | P1 bars; P2 +1; fine-fill +0x2e658 |

### NEW — confirmed this RE session (2026-08-11, Ryu in training, behavior-validated)
| field | offset | type | signature (how confirmed) |
|---|---|---|---|
| **x_velocity** | +0x644 | f32 | 0 at rest; +6.7 walk-fwd, −5.0 walk-back, ±18 dash spike |
| **y_velocity** | +0x648 | f32 | 0 grounded; +21/−21 through a jump arc |
| **red_health** | +0xb48 | u16 | health+4; recoverable pool, trailed damage 144→112 |
| **combo_recv** | +0x902 | u16 | counted combo hits on the victim (0→7) |
| **hitstun_flag** | +0x909 | u8 | **0xFF SUSTAINED whole combo (health dropping); 0 on BLOCK** — the disambiguator |
| **hit_flash** | +0x856 | u8 | brief 0xFF pulse on contact (attacker/victim flash) — the pal-effect, NOT hitstun |
| **facing** | +0x720 | u8 | {0,1}; flips at crossover (which side you face). Copies at +0x740, +0x84e (like DC's 3 copies) |

## STRONG CANDIDATES (movement pass; confirm via oracle / more isolation)
| field | offset | type | signature |
|---|---|---|---|
| is_walking | +0x5d2 | u8 | 1 while walking (fwd+back) only |
| is_crouching | +0x875 | u8 | 1 while crouched only |
| move-state | +0x76c | u8 | idle=0, crouch=1, walk-fwd=2, walk-back=3 |
| blockstun? | +0x35 / +0x114 | u8 | activated on the victim during BLOCK (not hit) — TBD |
| f32 pair | +0x650 | f32×2 | range −0.7..1.0 near velocity (facing vector / scale?) |

## STILL TO FIND
facing/xflip (crossup) · action-state / sprite_id / anim_flags · undizzy · sp_move_id / sp_strength ·
disable_special/all counters · airborne / superjump / stance-enum · num_wins · assist_call_state ·
EnemyPointer · super/special-move-state + meter-level-per-fighter.

## Wrong predictions (for the record)
- char_pal_effect predicted at 0x628 (posx+0xC) — **WRONG** (stayed 0). Real hit-flash = +0x856.
- The DC→Steam offset map is NON-LINEAR globally (assist DC+0x4C9→Steam+0x4e9, health +0x420→+0xb44 share
  no transform). Only WITHIN a sub-struct do neighbors stay adjacent (pos_y=pos_x+4 both builds;
  red_health=health+4 both builds; y_vel=x_vel+4). Find one landmark per block, then test neighbors.

## Tooling (scratchpad)
- `struct_recorder.py` — records the full window (base..+0x1400) as a time-series; auto-locks the live array.
- `struct_diff.py` — survey / diff(baseline vs action window) / watch(offset) / inputs.
- `find_live_array.py` — liveness probe (frozen vs animating candidates).
- `STEAM_RE_PROTOCOL.md` — the full expert field-map protocol + DC-oracle validation plan.

## Validation TODO (DC twin oracle)
Feed the same input stream to maplecast (mvc2.gdi, DC build) → compare each Steam-offset series to the DC
field (x_vel@+0x5C, stance@+0x1F9, hitstun@+0x275, red_health@+0x424). >0.95 series-match = CONFIRMED.
