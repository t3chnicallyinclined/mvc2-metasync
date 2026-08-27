# TAPE v2 — the render contract

> **Status: SPEC, nothing emits this yet.** Written 2026-08-27 to unblock the canvas-replay lane.
> Prose source: `RetroReceipts-server/docs/CANVAS-REPLAY-V2.md` (+ the two expert companions).
> This file is the part that was missing there: a schema you can **validate a file against**.

## Why this exists

`CANVAS-REPLAY-V2.md` describes tape v2 as *"what the server emits per re-simulated frame"*. That
couples the renderer to server-side re-simulation — which, as of today, **has never been
demonstrated** (no tape has re-simulated a match at any length past ~20 s, across any process
boundary). If the renderer is built against "whatever re-simulation happens to emit", it cannot
start until that proof lands, and it inherits every assumption the proof is still testing.

So invert it. **Tape v2 is a contract, not an output.** Three producers can satisfy it:

| producer | status | use |
|---|---|---|
| **fixtures** — hand-built / captured frames as static JSON | available now | build the renderer today |
| **extended local capture** — agent reads the draw list live | needs new agent columns | real tapes without re-simulation |
| **re-simulation** — server replays anchor + inputs in the real engine | **unproven** | the endgame; ~free coverage once it works |

The renderer consumes the contract and never learns which produced the file. That is the whole point:
it makes the canvas lane independent of the replay proof, and it makes the producers swappable.

⚠ **The renderer is a dumb executor.** It draws quads in the order given, at the coordinates given,
at the scales given. It does not compute world→screen, does not sort, does not infer anchors, does
not re-apply CPS scaling. Every one of those was a guess in the old renderer and every one is now
carried in the tape. If the renderer is doing math on positions, the tape is missing a field.

---

## 1. Header — once per tape

| field | type | source | notes |
|---|---|---|---|
| `v` | int | — | schema version, `2` |
| `producer` | string | — | `"fixture" \| "capture" \| "resim"` — provenance, never behaviour |
| `stage_id` | u8 | `blk+0x6D3C` | ⚠ RNG-picked at char-select confirm — see §5 |
| `teams` | u8[6] | `H+0x6C0` | slot CID. EVEN = P1 team, ODD = P2 |
| `build_id` | string | PE TimeDateStamp + SizeOfImage | re-sim is only valid for an identical build |
| `anchor_hash` | u64 hex | FNV-1a of the anchor region | ties a render tape to its capture |
| `fps` | int | — | nominal sim rate; `60` |

## 2. Per frame — fixed part (~40 B)

| field | type | source | notes |
|---|---|---|---|
| `frame` | u32 | `blk+0x3CC8` | see §5 — **the one field with an open conflict** |
| `camX`,`camY` | f32 | `blk+0x6914`, `blk+0x6918` | do **NOT** record `blk+0x691c`: the `812.3571` zoom divisor is a CONSTANT |
| `counts` | u8[16] | `blk+0x324d0..0x324DF` | per-layer drawn counts; 16 layers = priority order |
| `hp` | u16[6] | `H+0x578` | ⚠ **0x578, not 0x40c** — see §6 |
| `red` | u16[6] | `H+0x57C` | recoverable (red) health |
| `order` | u8[6] | `blk+0x32500 + 8k` | live tag-order permutation — HUD point/assist portraits need it |
| `meters` | u16[2] | — | P1/P2 super meter |
| `timer` | u16 | — | round timer |

## 3. Per drawn object — in draw-list order (~24–32 B each)

Enumerated from the real draw list at `blk+0x2f4d0 + L*0x300 + i*8`, `L` = layer `0..15`,
`i < counts[L]`. **Emit in exactly this order. The renderer does not sort.**

| field | type | source | notes |
|---|---|---|---|
| `L`,`i` | u8,u8 | — | draw-list slot; makes the tape self-checking against `counts` |
| `who` | i16 | — | fighter slot `0..5`, or pool index (satellite), or `-1` unknown |
| `sid` | u16 | `H+0x188` | **keep bit 15** — do not mask |
| `sx`,`sy` | f32 | `H+0x124`, `H+0x128` | the ENGINE's own screen output, foot-anchored |
| `scaleX`,`scaleY` | f32 | `H+0x130`, `H+0x134` | **final magnifiers. Never normalize. Never re-apply CPS.** |
| `facing` | u8 | — | 0/1 |
| `palid` | u8 | — | palette index |
| `blend` | u8 | *pending capture* | not yet located — emit `0` and treat as opaque |

**Optional interpolation tier** (only for sub-60 Hz tapes): `wx`,`wy` (`H+0x50`, `H+0x54`).
Reconstruct with exactly:

```
sx = wx - camX + 320
sy = (camY + 338.4) - wy
```

Lerp in **world** space, never screen space. If `sx/sy` are present, prefer them — they are ground truth.

⚠ The satellite pool lives inside `blk`, stride `0x280`, and a node is a **PREFIX of the fighter
struct** — so assists, projectiles, hitsparks and super flashes reuse the fighter read path verbatim.
There is no separate code path to write.

---

## 4. Validation rules

A validator should reject, not warn:

1. `counts[L]` equals the number of objects emitted with that `L`, for all 16 layers.
2. Objects appear in non-decreasing `L`, and `i` is strictly increasing within a layer.
3. `scaleX`/`scaleY` are **never** exactly `1.0` for a drawn fighter — that is the old
   normalize-the-magnifier bug. Expect `≈1.667` (640/384) and `≈2.143` (480/224).
4. `sid` bit 15 is preserved (some tapes historically masked it).
5. `teams[i] <= MAX_CID` for all six slots.
6. **Clock sanity** — the check that would have caught this year's worst capture bug:
   `(frame_last - frame_first) / elapsed_seconds ≈ 60`. A tape whose frame column advances at
   0.5 Hz or 15 Hz is clocked on the wrong word and is unrepairable. See §6.

---

## 5. Open items — do not build on these without checking

**`frame` semantics — DIRECT CONFLICT, unresolved.**
`CANVAS-REPLAY-V2.md` states the counter *"resets per mode entry, never compare across"*.
Measured live 2026-08-27, it did **not** reset: character select ran to frame 1255 and battle began
at 1595 on the same counter, continuously. Separately, the DC-side disassembly shows the equivalent
(`GameGlobal+0x10`) is incremented by a **vblank interrupt callback**, not a logic tick — so it
counts vblanks and keeps running when the main loop stalls on asset loading. Both cannot be right.
**Resolve before any producer relies on cross-mode frame arithmetic.**

**`stage_id` is RNG-derived.** The stage is chosen by up to four `rand()` draws at char-select
confirm. The generator is a plain LCG that is seeded `srand(1)` exactly once, in attract-demo mode
only — so in a real match its value is a function of the whole session since boot. Consequence for
the *renderer*: none, `stage_id` is in the header. Consequence for *re-simulation*: a replay may
load a different stage unless the seed is carried. This is the cheapest open test in the project.

**`blend` is unlocated.** Emit `0`. Transparency/additive effects will render opaque until found.

## 6. Corrections folded in

- **health is `H+0x578`.** `0x40c` is an *old-base* offset measured from `blk+0x3F24`, which is
  `0x16C` **inside** the real slot. Against the true base `blk+0x3DB8` every offset shifts by
  `0x16C`: health `0x40c→0x578`, char id `0x554→0x6C0`, DatPal `0x4c→0x1B8`. Mixing the two
  conventions is how a reader silently reads character *i+1*.
- **`replay-kit/mvcmem.py:71-76` is stale** — it still returns `blk+0x3F24` as `array_base` and
  will hand you the `0x16C` error. Do not build a producer on it until it is fixed.
- **The frame counter is `blk+0x3CC8`, and it is never searched for.** The agent used to locate it
  with a ±8 MB heuristic scan that rejected any candidate which ever *decreased*. The real counter
  mirrors GGPO's `_framecount`, which is assigned **backward** on every rollback — so the scan was
  structurally guaranteed to discard the right answer, worst on the laggiest matches. It shipped
  tapes clocked on a benched character's sprite id (`blk+0x4db0` = `blk+0x3DB8+2*0x738+0x188`),
  retaining 0.84% and 8.8% of their frames. Any producer MUST read `blk+0x3CC8` directly.
