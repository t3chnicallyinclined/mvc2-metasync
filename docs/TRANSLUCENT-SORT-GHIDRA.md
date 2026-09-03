# The translucent draw order on Steam -- sort key, comparator, qsort (Ghidra read-set + gate, 2026-09-03)

Binary: `mvc_dump.bin` (unpacked Steam MvC2, base 0x140000000, Ghidra project `dumpproj`, bridge :8080; the
comparator is a bare label, read from the dump bytes at file offset VA - 0x140000000). `ctx` = `DAT_142ef0ab0`,
`cur` = `DAT_142ef0ab8` (matrix-stack top), `blk` = `DAT_142edf560`. Tags: **CONFIRMED** = decompiled/read;
**INFERRED** = from the gate only; **UNKNOWN** = not located. Gate: `d3dcap/replay/sort_gate.py` over
`capgate/frame_{4445,4505,7279}.pack` + `capgate/state/` dumps with the stage-11 tape `gs-cache/..._59613506_...`.

RE method step: the DC side of this path is the PowerVR (the TA sorts translucent polygons per tile in hardware);
Steam replaces it with a CPU qsort inside the NaomiLib port, so there is no SH4 routine to pair. `FUN_1408436a0`
-> `loc_8c127c80` (queue append) is the only pair on the path (`docs/steam_sh4_map.csv`).

## 0. Answer

Every draw is appended to a per-(pass, category) queue of 0x20-byte slots (`FUN_1408436a0`). At frame end
`FUN_140843eb0` flushes pass 2, then 3, then 0; within a pass `FUN_140842e30(pass, cat)` runs cat 0, 1, 2, 3 in
order, and **only cat 3 is `qsort`'ed**, by:

```
slot   {u32 seq @0, int kind @4, entry* @8, int size @0x10, f32 key @0x14, u8 cat @0x18, u8 s19 @0x19, u8 blend @0x1a}
key    world/HUD record (kinds 2/3, and 0/1): FUN_140843320(rec+0x10, rec+0x14, rec+0x18, rec+0x1C)
         radius(rec+0x1C) < 0            -> key = -radius                     (forced key)
         cfg+0x48 == 8 && radius > 7000  -> key = 10000.0                     (branch NOT active, section 3)
         else                            -> key = w of [cx cy cz 1] x cur x V x P x Screen
                                            = w of [c 1] x W x V x P          (Screen col 3 = (0,0,0,1))
         kinds 0/1 (HUD lists 0xB/0xD): cur x P x Screen only (V skipped; V = I there anyway)
       sprite record (kind 0xC, FUN_140845e20 from FUN_1406129f0): key = the walker depth D = node+0x12C + 0.001 x k
         (k = record index inside the node's submit loop); THEN entry+0xC is overwritten with
         FUN_1408432e0(D) = max(0, (P[3][2] - D*P[2][2]) / D), which FUN_1408458b0 writes as the quad's vertex z
compar LAB_1408434d0(a, b): a.key < b.key -> 1 ; a.key > b.key -> -1 ; else a.seq <=> b.seq  (unsigned)
       => key DESCENDING (far first), ties by submission sequence ASCENDING: a TOTAL order
qsort  FUN_140817f80 = MSVC 2015 CRT qsort (Ghidra FID "Library Function - Single Match"), median-of-3, cutoff 8
       (`__shortsort` for n < 9), explicit stack. Irrelevant to the result because the comparator is a total order.
```

Depth preset for cat 3 with s19 == 0 is 2 (Z-write OFF, LESS_EQUAL): the sorted phase never writes depth, so the
order IS the compositing. The Z-write categories (0/1) precede it in submission order. That is exactly the gold:
frame 4445 draws 2..191 all depth-write ON in submission order, 192..460 all OFF in key order.

## 1. Read set (all CONFIRMED)

| routine | what it does |
|---|---|
| `FUN_1408436a0(kind, &entry, size)` | queue append. `cat` (uVar14) from PCW list type (bits 26-24) and kind: type 0 -> 0 (kind 1/3 with alpha `entry+0xCC` < 1.0 -> 3, s19 = 1), 1 -> 1, 2/3/4 -> 3 (unless `ctx+0x1f8560`); kinds 4/5 -> 2. Slot at `ctx+0x30 + (cat + pass*4)*0x10000 + n*0x20`, `n = ctx+0x1e0030[cat + pass*4]` (max 0x800): `+0 = n` (the sequence), `+4 = kind`, `+8 = arena copy (ctx+0x100030 + ctx+0x1e0080)`, `+0x10 = size`, `+0x14 = key`, `+0x18 = cat`, `+0x19 = s19`, `+0x1a = ctx+0x1f8274`. `pass = ctx+0x1f828c` (writer UNKNOWN; a fight uses one pass -- the gold has a single W..t..f block). Kinds 2..5 copy slot3/slot2/slot1 into the entry (P, V, W); kinds 0/1/6/7 copy identity for V. |
| `FUN_140843320(cx, cy, cz, r)` | the record key (section 0). `PTR_DAT_140acd3a0+0x48 == 8` and `r > 7000.0 (DAT_140990d84)` -> `10000.0 (DAT_14096a9f0)`; `r < 0` -> `r ^ 0x80000000`; else push, `cur = cur x M(ctx+0x1f812c) x M(ctx+0x1f816c) x Screen(DAT_140ab2080)`, `out = [c 1] x cur` (`FUN_140846880`), pop, return `out[3]`. |
| `FUN_1408432e0(D)` | `D == 0 -> 0`; `v = (ctx+0x1f81a4 - D * ctx+0x1f8194) / D` = `(P[3][2] - D*P[2][2]) / D` with P = slot 3; `max(0, v)`. Used on kinds 0xC (sprites), 0xD..0x12, 0x13/0x14/0x16 to turn a depth key into a vertex z. |
| `FUN_1406129f0(node)` | sprite submit. `entry+0xC = node+0x12C` (`param_1 + 300`); per record: build the quad, `FUN_140845e20(&entry)`, then `entry+0xC += 0.001 (DAT_1408e2a3c)` (line "local_110._4_4_ + fVar27" on the tiled path, `local_dc + fVar3` on the scale-walker path). Returns the record count. |
| `FUN_140845e20(entry)` | copies the 0x48-byte sprite entry, clamps alpha to 1.0, packs the colour, `FUN_1408436a0(0xC, &copy)`. |
| `FUN_1408436a0` case 0xC | `key = entry+0xC` (the raw D), then `entry+0xC = FUN_1408432e0(D)`; `cat = (entry+0x30 != 0) ? 3 : 0`; `entry+0x30` is `blk+0x32BDC` (= 2 in a fight, TAPE-V3-SPEC 10.1) -> every sprite is cat 3. |
| `FUN_1408458b0(slot)` | sprite consumer: 4 vertices, `z = entry+0xC` (the converted key) on all four; texture slot from `entry+0`; `FUN_140048370(0x4000, verts, 0x1c, 4, texId, ..)`. |
| `FUN_140620f10` | sprite walker: per drawn node `FUN_14061d7e0()` (world camera -> slot 3 = P(far 1.4e6)), `FUN_140847d10()`, `FUN_140848120()` (screen x/y), `node+0x12C = blk+0x6928 * 0.1 (DAT_1408e2f64) + blk[0x6D08 + 4*node+0x38]` (zoom x 0.1 + LayerZ[layer]); after the submit `blk[0x6D08 + 4*layer] += records * 0.001`. Order: layer 0..15 (`blk+0x324D0` counts, `blk+0x2F4D0 + L*0x300` handles), array index ascending. |
| `FUN_140842e30(pass, cat)` | flush: `n = ctx+0x1e0030[cat + pass*4]`; if `cat == 3`: `qsort(slots, n, 0x20, LAB_1408434d0)` (CALL 0x140817f80 @0x140842ea5); then per slot: cmd 1 (blend preset from slot+0x1a), cmd 8 (depth preset: 10 | 2 | 5 | 1), then by kind: 0-3 `FUN_1408482a0`, 4/5 `FUN_140848ce0`, 6/7 `FUN_140849030`, 8/9 `FUN_14084b270`, 0xA/0xB `FUN_14084b000`, 0xC `FUN_1408458b0`, 0xD/0xE `FUN_1408460e0`, 0xF/0x10 `FUN_140846280`, 0x11/0x12 `FUN_1408464c0`, 0x13 `FUN_14084b050`, 0x14 `FUN_14084aa70`, 0x15 `FUN_14084ac70`, 0x16 `FUN_14084aeb0`, 0x17 `FUN_14084af20`, 0x18 `FUN_140849c50`. |
| `LAB_1408434d0` | the comparator (bytes `f3 0f 10 42 14 / f3 0f 10 49 14 / 0f 2f c1 / 77 16 / 0f 2f c8 / 77 0b / 8b 09 / 39 0a / 72 0b / 77 03 / 33 c0 c3 / b8 ff ff ff ff c3 / b8 01 00 00 00 c3`): `comiss [rdx+0x14],[rcx+0x14]` -> `ja +1`; `comiss` reversed -> `ja -1`; `cmp [rdx],[rcx]` unsigned -> `jb +1`, `ja -1`; else 0. `comiss` on NaN falls through to the sequence compare. |
| `FUN_140817f80` | `qsort` (MSVC 2015 CRT, FID match). |
| `FUN_140843eb0()` | frame flush: texture uploads, `FUN_140048810(1)` ring reset, a full-screen quad, cmd 6 (fog/colour block), then `FUN_140842e30(2, 0..3)` if `ctx+0x1e0078`, `(3, 0..3)` if `+0x1e007c`, `(0, 0..3)` if `+0x1e0070`. |
| matrices | slot 1 `ctx+0x1f80ec` = W (cur during draws), slot 2 `+0x1f812c` = V, slot 3 `+0x1f816c` = P, `Screen = DAT_140ab2080 = [320 0 0 0; 0 -240 0 0; 0 0 1 0; 320 240 0 1]`, identity `DAT_140ab20c0`. `FUN_1408473d0` = post-multiply `cur = cur x M`; `FUN_140846880` = `[v 1] x cur` (row vectors). Constants: `DAT_1408dd5a8 = 1.0`, `DAT_140990d84 = 7000.0`, `DAT_14096a9f0 = 10000.0`, `DAT_1408e2ac0 = 0x80000000 x4`, `DAT_1408e2f64 = 0.1`, `DAT_1408e2a3c = 0.001`, `DAT_14097dc04 = 812.3573`. |

Consequences already visible elsewhere, now explained by the sort: "paint order within a layer is the REVERSE of
registration" and "draw order within an assembly is the reverse of the record list" (tape_to_seq notes) are both the
0.001 increment: later records / later nodes get a LARGER key and are flushed FIRST (far to near).

## 2. Gate (`sort_gate.py`; deterministic, numeric)

Inputs: gold packs (every draw, its state, CBWorld and the 432-B scene CB), the state dump of the same frame
(`blkstate.load_frame`, `at: walk`), and the stage-11 tape's object table (records with header +0x10..+0x1C).
Per cat-3 draw (depth write OFF): world/HUD -> record by vertex-set join (as `tsp_gate.py`), key from the
record centre with W = captured CBWorld and V/P = captured CB rows 7-10 / 15-18; sprites -> D from the dump's
post-walk LayerZ table (`blk+0x6D08`: `base + 0.001 x records`), vertex z predicted through `FUN_1408432e0`.

| pack | cat-3 draws | keyed | unjoined | key rises | distinct-entry ties / out of submission order | sprite parts | predicted vs captured vertex z |
|---|---|---|---|---|---|---|---|
| 4445 | 269 | 252 | 1 | **0** | 23 / 3 (obj-139 records under a composed W (44.33, 4.06, 0.2) that matches no node's +0x50 -- node IDENTITY unresolved, key equal at 81.0357 as required) | 133 | 133/133, max abs dz 2.4e-7 (float32 rounding) |
| 4505 | 150 | 133 | 1 | **0** | 3 / 0 | 122 | n/a: no captured dump in 4490..4520 carries this pack's 122-record sprite set (the 4505 dump has 118, 4506 103) -- the pack and the dump are different moments; sprite keys taken from the engine's own captured z (inverted `FUN_1408432e0`), world/HUD keys derived |
| 7279 | 140 | 107 | 1 | **0** | 4 / 0 | 96 | 96/96, max abs dz 1.8e-7 |

Frame 5168 has a state dump but no `.pack` (never captured as a draw list) -- not gated. The 16-32 vs_flat draws
with z == 0 per frame are HUD digit quads (list 0xC path) whose D <= 2 clamps to 0; they sort last (D < 68.5) and
among themselves by submission -- their exact D is UNKNOWN (not needed for the order). One unjoined draw per pack
(220 / 573 / 547: geometry absent from the tape) is skipped.

Key values seen (4445): world list-6 records 40812 / 33062 / 1003.7 / 812.36 / 464.2 / 167.2; HUD (kind 0)
190 / 71 / 70 / 68.5; sprites 108.28 .. 96.24 (layer 6: 81.24 + 27, layer 5: + 25, layer 0: + 15); list-7
shadows/markers 81.04 .. 73.8 (x0.1 camera). The sprite block sits between the world and the x0.1 lists by
arithmetic, not by a pass boundary.

### 2.1 What the gate falsified

* **"The sprite key is the vertex z (0.98)"** -- would put every sprite after the list-7 draws (81..73): the gold
  draws them before. The raw D is the key (section 0). This was my first reading and it was wrong.
* **`cfg+0x48 == 8` branch active** -- draws 192/193 of 4445 are records with radius 32776 / 33339 (> 7000) on nodes
  (6,10) / (6,6). Under the branch both keys are 10000 and the sequence tie-break draws node 6 first; the gold draws
  node 10 first, which is the w order (40812 > 33062). INFERRED: the branch is inactive in a fight (one discriminating
  pair). `PTR_DAT_140acd3a0+0x48`'s meaning is UNKNOWN.
* **Per-pass partition** -- no zwrite-ON draw appears after the first zwrite-OFF one in any pack: one pass.

## 3. Implementation (`tape_to_seq.py`, `--legacy-order` keeps the old behaviour)

* `decode_anodes`: records carry `centre` (+0x10) and `radius` (+0x1C); `rip_stage.py` meshes carry `center` /
  `radius` (STG0B / STG0D regenerated; older rips fall back to the vertex centroid, counted).
* every draw is tagged `_cat` (PCW list type + kind + alpha), `_key` (`sort_key_record` = FUN_140843320 with
  V/P from the frame's scene block rows 7-10 / 15-18, W = node +0xA8, HUD kind 0 skips V) and `_sub`
  (submission rank: sprites (walk index, record) < deck < 5 < 6 < 7 < 8 < 0xB < 0xC, per `FUN_140620960`).
* sprites: `D = tape depth (+0x12C) + 0.001 x record index`, vertex z = `FUN_1408432e0(D)` under the world P.
* `order_draws`: cat 0/1 in submission order, then cat 3 by `(-key, submission)`; bit-13 draws inherit the cull
  state of the draw flushed before them (ring state).

## 4. Falsification

1. A capture in which a cat-3 draw with a larger derived key follows one with a smaller key (sort_gate "key rises").
2. A sprite quad whose captured vertex z differs from `FUN_1408432e0(base + 0.001k)` by more than float32 rounding.
3. Two records with radius > 7000 drawn in sequence order against their w order (would revive the cfg+0x48 branch).
4. A frame whose Z-write draws are interleaved with Z-write-off draws (would mean several passes; find the
   `ctx+0x1f828c` writer).

## 5. Address index

`FUN_1408436a0` queue append - `FUN_140843320` record key - `FUN_1408432e0` depth -> vertex z - `FUN_1406129f0` sprite
submit - `FUN_140845e20` sprite entry - `FUN_1408458b0` sprite consumer - `FUN_140620f10` sprite walker -
`FUN_140842e30` flush - `LAB_1408434d0` comparator - `FUN_140817f80` qsort - `FUN_140843eb0` frame flush -
`FUN_1408473d0` / `FUN_140846880` / `FUN_140847950` / `FUN_1408478c0` matrix ops. Data: `DAT_140ab2080` Screen,
`DAT_140ab20c0` identity, `blk+0x6D08` LayerZ[16], `blk+0x32BDC` sprite category word, `ctx+0x1e0030` queue counts,
`ctx+0x1e0070/78/7c` per-pass counts, `ctx+0x1e0080` arena cursor, `ctx+0x1f828c` pass index.
