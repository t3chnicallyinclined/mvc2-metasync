# The frame background — how Steam MvC2 clears a frame and where the colour comes from (2026-09-03)

Review item M2 of `WORKSTREAM-CLIENT-REPLAY.review-re.md`. Binary: `mvc_dump.bin` (Ghidra `dumpproj`, bridge :8080,
`decompile_function` / `xrefs_to`; constants read at file offset VA-0x140000000). SH4 side: marvelous2
`bank02.asm` / `bank03.asm`. Method: `RE-METHOD.md` (annotation transfer by function matching; block map
`d3dcap/replay/re_map/blkmap.py`). Tags: **CONFIRMED** = decompiled/read on both sides or reproduced by the gate;
**INFERRED** = one side or fingerprint only; **UNKNOWN** = not located. Knowledge graph: seed
`maplecast-flycast/tools/re_kb/110_frame_background.surql`. Consumer: `d3dcap/replay/bg_rule.py` → `tape_to_seq.py`.
Gate: `d3dcap/replay/bg_gate.py`.

## 0. The rule (CONFIRMED)

The scene RT is never cleared by `ClearRenderTargetView`. Every captured frame opens with three full-screen quads
at z = 1.0, in this order:

| # | issuer | vertices (stride, order) | state | what it does |
|---|---|---|---|---|
| (i) | host: `FUN_140070940` (ring executor, "drawJack") entry → `FUN_14033c5c0(dev, 0x3f, DAT_142eb36c0 = black)` | 28 B × 4: `POSITION (x, y, 1, 0)` + 12 zero bytes; TL, TR, BL, BR; indices `0 1 2 2 1 3` | vs `4718687148562057` / ps `cd8012caa4038c99`, blend off, `DepthFunc ALWAYS`, depth write, stencil `ALWAYS/REPLACE` ref 0 write 255, cull NONE, ccw 0 | clears colour to black, depth to 1, stencil to 0 |
| (ii) | engine: `FUN_140843eb0` (frame flush) `FUN_140048370(0x4000, quad, 0x1c, 4, texId 0xffff, 0, 0)` | 40 B × 4 after the executor's format-0x4000 conversion: `POSITION (x, y, 1, 0)`, `NORMAL (0, 1)`, `color0 = (R, G, B, 0xff)`, `color1 = 0`, `TEXCOORD (0, 0)`; **TL, BL, TR, BR**; indices `0 1 2 2 1 3` | vs `eecdd8debcfbab72` / ps `bf338c9550f2b5fd` (texalpha), blend `SRC_ALPHA / INV_SRC_ALPHA`, `LESS_EQUAL`, depth write, stencil off, sampler point/clamp, ps CB `28111758` (32 B) | paints the **background colour**; texId `0xffff` resolves to the executor's 1×1 white page (`ffffffff`) — the "`04000000_ad9513` texture of UNKNOWN origin" of `TEXTURE-BANKS-GHIDRA.md` §8.5 is this placeholder |
| (iii) | host: executor command 0 (pass begin, queued by `FUN_140843eb0` as `FUN_1400483c0(0, &pass, 4)`) → `FUN_14033c5c0(dev, 0x30)` | 28 B × 4 as (i) | ps null, colour mask 0, `ALWAYS`, depth write, stencil REPLACE 0 | resets depth + stencil before the pass; one per non-empty pass (a fight has one pass) |

`FUN_140843eb0` (CONFIRMED, decompile): after the palette uploads (`FUN_140048970`) and the ring reset
(`FUN_140048810(1)`) it builds the quad on the stack — v0 TL `(-1, 1, 1, 0)`, v1 BL `(-1, -1, 1, 0)`, v2 TR
`(1, 1, 1, 0)`, v3 BR `(1, -1, 1, 0)`, each `{x, y, z, 0, 0, colour, 0}` with colour at +20 =
`ctx+0x1f8248 | 0xff000000` (v0), `ctx+0x1f824c | ..` (v1), `ctx+0x1f8250 | ..` (v2 **and** v3) — then cmd 6
(fog/colour block from `ctx+0x1f82c0..` / 255), then cmd 0 + the category flush for passes 2, 3, 0.

Executor format-0x4000 branch (`FUN_140070940`, CONFIRMED): per vertex `out = {x, y, z', w', fVar26 = 0,
fVar7 = 1.0, swap02(colour), swap02(colour2), uv}` where `swap02(w) = (w & 0xff000000) | ((w & 0xff) << 16) |
(w & 0xff00) | ((w >> 16) & 0xff)` — so the engine's `0xAARRGGBB` word lands as **R, G, B, A bytes** in the
`R8G8B8A8` `TANGENT` slot (+24). The order of the four vertices is preserved.

`FUN_1406101b0` (CONFIRMED both sides — SH4 `loc_8c02dc4c`), called once per frame from `FUN_14060a1f0`
(the LayerZ reset, `@0x14060a220`) before the render dispatch:

```
if FUN_14060b400() == 0 && FUN_14060b430() == 0:            # not in a fight: G[0..2] != (2,1,2) or G+0x2E & 1
    A, B, C = uint3 @ blk+0x6CB8, 0x6CBC, 0x6CC0                # raw, no multiplier   (SH4 loc_8c02de12)
else:
    if FUN_140619960() != 0:            # blk+0x6CE4 fade/strobe word (SH4 loc_8c0310f2)
        blk+0x6CB4 = 0;  A = blk+0x6CF0                          # white 0xffffff or black 0, raw
    elif entity+0x96 != 0 and entity+6 != 0:                     # entity = *DAT_142edf628; +0x96 is copied to G+0x98
        blk+0x6CB4 = 0;  A = 0                                   #   every frame by FUN_14061f030 (the blackout gate)
    else:                                                        # SH4 loc_8c02dcd6
        mul(w) = ((int)((f32)byte2(w) * deck[0]) & 0xff) << 16 | ((int)((f32)byte1(w) * deck[1]) & 0xff) << 8
                 | ((int)((f32)byte0(w) * deck[2]) & 0xff)       # deck = f32 @ blk+0x6CA8 / 0x6CAC / 0x6CB0 (R, G, B)
        A = mul(blk+0x6CB8); B = mul(blk+0x6CBC) if mode >= 1; C = mul(blk+0x6CC0) if mode == 3
mode = blk+0x6CB4:  0 -> (A, A, A)   1 -> (A, B, A)   2 -> (A, A, B)   3 -> (A, B, C)   else: return (no update)
FUN_1408450e0(c0, c1, c2, 1e7)  ->  ctx+0x1f8248 = c0 (TL), +0x1f824c = c1 (BL), +0x1f8250 = c2 (TR, BR), +0x1f8254 = 1e7
```

The SH4 twin is instruction-for-instruction the same (`fmul`/`ftrc` per byte, `extu.b`, `shll16`/`shll8`/`or`;
mode switch `loc_8c02dca2..dcc0` with the same argument order; sink `loc_8c11d630` with `fr4 = 0x4b189680 =
1e7`). The multiplied word therefore keeps the source layout `0x00RRGGBB` with byte 2 = R × `blk+0x6CA8`.
Mode 2 is a **left → right gradient** (A on the left edge, B on the right); mode 1 puts B on the bottom-left
vertex only; mode 3 is (TL A, BL B, TR/BR C). The 12-byte word-3 slot (`blk+0x6CC0`) is only read in mode 3.

`FUN_1408450e0` is the **only** match-time writer of `ctx+0x1f8248..50` (the other, `FUN_1408450a0`, sets far
1e5 and is called from the menu `caseD_0 @0x140611cb8`).

## 1. Writers of `blk+0x6CB4 / 0x6CB8..0x6CC3 / 0x6CE4 / 0x6CF0` (CONFIRMED)

| word | writer | when |
|---|---|---|
| `0x6CB4` mode + `0x6CB8` (+ `0x6CBC`) | `FUN_1406104b0(w)` (mode 0, == `loc_8c02dc1c`) and `FUN_140610480(w0, w1)` (mode 2, == `loc_8c02dc32`); SH4 also has mode-1 `loc_8c02dc24` and mode-3 `loc_8c02dc3e` setters (no Steam caller found) | **stage load** `FUN_140620200` (`caseD_5`, `caseD_9`, `FUN_14060efd0`) from the per-stage table `DAT_14097db20[stage*0xC]`: stages **3 and 0xC** → `FUN_140610480(t[0], t[1])` (mode 2), every other stage → `FUN_1406104b0(t[0])` (mode 0); **re-asserted every frame** by `FUN_140620420` (from `FUN_1406283a0`), same table, same rule. Menu/transition writers: `FUN_140615020`, `FUN_1406289c0`, `FUN_140628ac0` (`0xffffffff` white), `FUN_140631eb0`, `FUN_1406320b0`, `FUN_1406331f0/250/300` (`0xff000000`), `FUN_14060af70` (0), `FUN_14062fdc0` (mode 2 from `blk+0x32BB8/BC`, a non-fight screen), the `caseD_*` menu states. `FUN_1406101b0` itself writes mode 0 in the fade/blackout branches. |
| `0x6CE4` | `FUN_140619970` (fade step, per frame): counter `0x6CEC` → 0 ⇒ 0; kind `0x6CE8` 0 ⇒ 1; 1, 3..6 ⇒ `(cnt >> 1) & 1`; 2 ⇒ `cnt & 1`; 7/8 ⇒ 2; 9 ⇒ 3. Also reset by `FUN_14061e170` (object-pool init). | every frame while a fade runs |
| `0x6CE8 / 0x6CEC / 0x6CF0` | `FUN_140619910` (kind 1, 16 frames, **0xffffff**; if `G+0x28 == 0`; callers `FUN_14073d490`, `caseD_4`), `FUN_140619b00` (kind 6, 24 frames, 0xffffff; callers `FUN_14063a4a0/abb0/ac80/cbc0`), `FUN_140619a80` (kind 8, 185 frames, 0; from `FUN_1406277b0`), `FUN_140619ac0` (kind 9, 180, 0), `FUN_140619b50` (kind 0, 120, 0), `FUN_140619b80` (kind 0, 30, 0) | fade/strobe starts (round/KO flashes, transitions); which game event maps to which kind is INFERRED from durations only |
| `G+0x98` (`blk+0x3D50`, the tape's `blackout`) | `FUN_14061f030`: `= entity+0x96` every frame (after a conditional reset of `entity+0x96`) | per frame — so the tape's `blackout` equals the byte `FUN_1406101b0` tests, sampled after the same frame's copy (INFERRED: sampling order) |

Per-stage table `DAT_14097db20` (12 B/stage, read from the image; stages ≥ 0x11 are a different table):

| stage | mode | word 0 | word 1 | background |
|---|---|---|---|---|
| 0x00, 0x04, 0x06, 0x07, 0x0D, 0x0F, 0x10 | 0 | `0x7f7f7f` | — | mid grey × deck |
| 0x01, 0x0A | 0 | `0x6061e3` | — | blue (R 0x60, G 0x61, B 0xe3) × deck |
| 0x02, 0x05, 0x08, 0x09, 0x0B, 0x0E | 0 | `0x000000` | — | black |
| 0x03, 0x0C | 2 | `0x000000` | `0xb0459a` | gradient black (left) → magenta (right) × deck |

The tapes on disk (`replay-kit/tapes-kept`, v5): stages 0x01, 0x03, 0x04, 0x06, 0x07, 0x09, 0x0B, 0x0E, 0x10
(and the `sequences.json` renders: 5, 13, 15, 16) are all covered by the table. SH4 twin of the table:
**UNKNOWN** — the graph pairs `FUN_140620200` with `loc_8c045ce0`, but that SH4 routine (bank04) carries no
colour-table reference; `bank03 loc_8c03ec72` references both setters and is a menu state. Not needed for
rendering: the tape (0.3.42) carries the bytes and the table is the fallback.

Values in the fight are per-frame **constants** except: the deck floats (`blk+0x6CA8..`, `FUN_1406105a0`
writes all three — 0.5 on 103 of 300 rows of the stage-16 tape), the fade word, and the blackout byte
(0x11/0x12 on 193 of 300 rows of the same tape — bit 4 selects the entity slot in `FUN_14061f030`).

## 2. Gate (`bg_gate.py`, deterministic: frozen state dump + frozen pack)

```
python bg_gate.py 4445 4505 7279
GATE: quad bytes 9/9, index order 9/9, 1x1 page 3/3, scene RT 2/2
```

Per frame: the three quads rebuilt from the dump's `blk` bytes through `bg_rule.background_words` are
**byte-exact** against the pack's draws 2/3/4 (4 × 28, 4 × 40, 4 × 28 B), the index order is `0 1 2 2 1 3` on
all nine, the 1×1 page is `ffffffff`, and on the two frames with a scene bmp the most common viewport colour
is the derived background (4505: 355,600 px = 28.9 %, 7279: 382,641 px = 31.1 % of the 1280×960 viewport).

**Limit of the gate.** All three packs are stage 0x0B (training) whose stage word is 0: the gate proves the
layout, the alpha byte, the vertex order, the white page and the black case. The multiplied path, the byte
swap and the mode-2 gradient are CONFIRMED by decompile on both sides but **not yet by a pixel**; the first
capture on a `0x7f7f7f` stage (0, 4, 6, 7, 0xD, 0xF, 0x10) or a mode-2 stage (3, 0xC) closes that.

## 3. Tape (agent) and emitter

* Agent 0.3.41 carries `deck[3]` and `blackout` but none of the rule's other inputs. **0.3.42 proposal**
  (APPEND-only columns, diff in the M2 delivery): `bg_mode` (u32 `blk+0x6CB4`), `bg_col[3]` (u32
  `blk+0x6CB8/BC/C0` raw), `fade_mode` (u32 `blk+0x6CE4`), `fade_col` (u32 `blk+0x6CF0`), `bg_gate[6]` =
  `[G+0, G+1, G+2, G+0x2E, entity+6, entity+0x96]` (entity = `*(exe+0x2edf628)`; 0xFF = read failed). One
  0x40-B read at `blk+0x6CB4` + the G bytes + one pointer deref.
* `tape_to_seq.py`: every frame now opens with the three quads (state copied from the capture's draws 2/3/4,
  vertices synthesised in the executor's layout, `bg_white` = the 1×1 page); the colour comes from
  `bg_rule.from_row` — tape columns when present, else the per-stage table with the row's `deck` and
  `blackout` (fade assumed off, fight assumed, `entity+6` assumed non-zero). `--no-preamble` restores the old
  clear-to-black. The stage-16 render (`tape_v5_59613970_stage16.seq`, rows 1500..1799) was re-emitted with it.

## 4. Open (UNKNOWN / INFERRED)

* `entity+6` (SH4 `*(0x8c2896b0)+6`): meaning UNKNOWN; non-zero during a fight is INFERRED from the gate
  frames only through its consequence (the blackout branch must be reachable — the stage-16 tape shows
  `blackout != 0` rows with the "black background" look). Ship the byte; do not derive it.
* Which fade kind (`0x6CE8`) belongs to which game event (round-start flash, KO, super) — INFERRED from
  durations; the tape carries the resulting `0x6CE4`/`0x6CF0` so the renderer does not need it.
* The deck draw (`FUN_140620960`) also reads `FUN_140619960()` (`blk+0x6CE4`): what the deck does on a
  strobe frame is not in this note.
* `ctx+0x1f8254` (far 1e7 / 1e5): read by whom — not located.

## 5. Address index

Steam: `FUN_1406101b0` rule · `FUN_1408450e0` / `FUN_1408450a0` sinks · `FUN_14060b400` / `FUN_14060b430`
fight gates · `FUN_140619960` fade word · `FUN_140619970` fade step · `FUN_140619910/a80/ac0/b00/b50/b80` fade
starts · `FUN_1406104b0` / `FUN_140610480` setters · `FUN_140620200` stage load · `FUN_140620420` per-frame
re-assert (`FUN_1406283a0 @0x14062851b`) · `FUN_14061f030` blackout copy · `FUN_14060a1f0` per-frame caller ·
`FUN_140843eb0` frame flush · `FUN_140048370` → `FUN_14004b9a0` ring append · `FUN_140070940` executor ·
`FUN_14033c5c0` clear-by-quad · `FUN_14006f5e0` executor caller · tables `DAT_14097db20` (stage colours),
`DAT_140a6ed40` (stage fog), `DAT_142eb36c0` (clear colour) · constants `DAT_1408e35e4` 1e7, `DAT_1408e6048`
255.0, `DAT_1408dd5a8` 1.0.
SH4: `loc_8c02dc4c` rule · `loc_8c02dcd6` multiplied · `loc_8c02de12` raw · `loc_8c02dc1c/24/32/3e` setters ·
`loc_8c11d630` sink · `loc_8c03591e` / `loc_8c03593e` gates · `loc_8c0310f2` fade word · data `0x8c26a8a4`
(deck −4), `0x8c26a8b4` (mode), `0x8c26a8f0` (fade colour), `0x8c2896b0` (entity pointer).
