# TA header words -> Steam D3D11 render state (Ghidra read-set + capture gate, 2026-09-03)

Binary: `mvc_dump.bin` (unpacked Steam MvC2, base 0x140000000, Ghidra project `dumpproj`, GhidraMCP bridge
:8080 `decompile_function?address=` / `disassemble_function?address=`; the two Ghidra mega-blobs were searched
through `d3dcap/replay/re_map/cache/steam_disasm.jsonl`). `ctx` = `DAT_142ef0ab0` (NaomiLib host context),
`R` = `DAT_140acd3a8` (the host renderer object, ctor `FUN_140047a20`). Tags: **CONFIRMED** = function decompiled
and read; **INFERRED** = derived from the capture gate or a fingerprint. Gate: `d3dcap/replay/tsp_gate.py`
(state law) over `capgate/frame_{4445,12033,15323,11943}.pack` against the stage-11 tape
`gs-cache/..._59613506_....json.gz`; predictor: `d3dcap/replay/tsp_state.py`; consumer: `tape_to_seq.py`.

RE method step used: the SH4 side of this path is the TA itself (the DC writes PCW/ISP/TSP verbatim into the TA
FIFO and the PowerVR applies them), so there is no SH4 routine to port -- the whole translation exists only on
Steam. The pair that does exist, `FUN_1408436a0` -> `loc_8c127c80` (queue append, `high`), is in
`docs/steam_sh4_map.csv`; `FUN_1408482a0`/`FUN_140848ee0` have no SH4 counterpart (UNKNOWN in the map, expected).

## 0. Answer

Steam does not guess: every world-space draw's sampler, blend, depth preset, cull mode and pixel-shader
variant is computed by the NaomiLib consumer **`FUN_1408482a0`** from the record's own 0x50-byte mesh header
(PCW @+0, ISP @+4, TSP @+8), the polygon GROUP header (cull word), the draw KIND chosen by the list walker
`FUN_140620cd0` from the node flags, and one alpha multiplier (`node+0x90`). The old `tape_to_seq.py` rule
(`flags & 0x20 or list in 7/8/9 -> texalpha, else opaque`, one sampler/blend/depth/raster for every world draw,
copied from ONE template draw) is replaced by that computation, and the gate says:

```
tsp_gate.py, 4 packs, 824 matched (draw, record-group) pairs, 0 ambiguous, 1145 unmatched (the other session's
effects/HUD objects are not in this tape; every unmatched draw is a geometry miss, not a state miss)
sampler (filter, addressU, addressV)  824 / 824
depth   (write mask, stencil enable)  824 / 824
cull    (D3D11_CULL_MODE)             824 / 824
ps      (opaque | texalpha)           824 / 824
winding (captured tris == Steam rule) 824 / 824   (bit-6 strips: some record with the same geometry reproduces it)
blend   (src, dst)                    820 / 824   the 4 misses are flag-bit-5 nodes drawn with an alpha
                                                  multiplier the tape does not carry (section 3)
vertex colour0 (record colour x 255)  647 / 776   (earlier run) the rest are node colour multipliers (section 4)
```

## 1. The path (all CONFIRMED)

```
FUN_140620cd0(list)                 per node: colour select (flags bits 10/11), draw kind by flags:
  bit 13 -> FUN_140849ac0(obj)        = FUN_140848ee0(obj, 2, 1.0, 2)   [gated on ctx+0x1f8520]
  bit 5  -> FUN_140849c30(obj,+0x90)  = FUN_140848ee0(obj, 1, +0x90, 3) (lists != 0xB/0xD)
            FUN_140849be0(obj,+0x90)  = FUN_140848ee0(obj, 1, +0x90, ctx+0x1f8518 ? 3 : 1) (0xB/0xD)
  else   -> FUN_140849c10(obj)        = FUN_140848ee0(obj, 0, 1.0, 2)   (lists != 0xB/0xD; also the deck)
            FUN_1408499e0(obj)        = FUN_140848ee0(obj, 0, 1.0, ctx+0x1f8518 ? 2 : 0) (0xB/0xD)
FUN_140848ee0(obj, p2, alpha, kind)  walks records (PCW<0, next = rec + rec[0x13] + 0x50), entry[0xC8]=p2,
                                     entry[0xCC]=min(alpha,1.0); FUN_1408436a0(kind, &entry, 0x130)
FUN_1408436a0                        category `cat` (slot+0x18) and `s19` (slot+0x19) from PCW list type + kind;
                                     entry[0xD0..0xD8] = colour mult ctx+0x1f825c..64; slot+0x1a = ctx+0x1f8274
FUN_140842e30(_, cat)                flush per category (cat 3 qsort'ed by the record's sort key):
                                     cmd 1 = BLEND_PRESET[slot+0x1a] (=0x32), cmd 8 = 10|2|5|1 (see 2.3),
                                     cmd 4 = P,V (128 B), cmd 7 = W (64 B), then FUN_1408482a0 for kinds 0-3
FUN_1408482a0(slot)                  THE state derivation (section 2) + vertex copy + FUN_140048370 batch
FUN_1400483c0 / FUN_14004b9a0        ring writers: record {cmd, size, count, seq, ..} at R+0xdbd20 (base
                                     R+0xdbd08, bytes R+0xdbd28, count R+0xdbd2c; reset FUN_140048810)
FUN_140070940                        THE RING EXECUTOR (switch on cmd, then on the payload): selects D3D
                                     state OBJECTS by hash / slot (section 2.5). It is inside no mega-blob;
                                     the object CREATION with the D3D descs was not located (2.5).
```
`FUN_140036560` (called by `FUN_140620cd0` with the scale, with `0x80` on bit 13, and with `+0xA0` on bit 15)
is an empty `ret` on Steam (CONFIRMED) -- those three DC calls compile to nothing here.

## 2. The derivation, bit by bit (CONFIRMED in `FUN_1408482a0` unless marked)

Word layout (PVR TA, as Steam reads it): `TSP` bits 31-29 src alpha instr, 28-26 dst alpha instr, 23-22 fog,
19 ignore-tex-alpha, 18 flip V, 17 flip U, 16 clamp V, 15 clamp U, 14-13 filter; `ISP` bit 26 = Z-write
DISABLE; `PCW` bits 26-24 list type, bit 7 shadow; group header word 0 bits 1-0 cull, bit 3 triangle list,
bit 6 do-not-expand.

### 2.1 Blend -> ring cmd 1 = `BLEND_PRESET[src<<4 | dst]`

```
if entry[0xCC] (alpha multiplier) == 1.0:  src = TSP>>29, dst = TSP>>26 & 7          (the record's own words)
else:                                       src<<4|dst = ctx+0x1f8274 = 0x45 (SRCA, INV_SRCA)   [FUN_140844a10 init; never rewritten]
FUN_140844220: 0x10->1  0x11,0x16->0x11  0x14,0x41,0x46->0x12  0x21->0x16  0x22->0x22  0x30->7  0x31->0x19  0x45->0x32  else 0
```
Executor (`FUN_140070940` cmd 1, CONFIRMED): preset & 0xc00 == 0: `0 -> hash 0x4d2c8180, 7 -> 0xa31e719d,
0x11/0x12/0x21 -> 0xd3b1d189, 0x16 -> 0xb444c20a, 0x19 -> 0xcbec21a3, 0x22 -> 0xeb00e185, everything else
(incl. 1 and 0x32) -> 0x23baf183`; `preset & 0x400 -> 0xa31e719d`; blend state = `*(R2 + 0x358 + (hash & 0xfff)*16)`.
So presets 1 (ONE,ZERO) and 0x32 (SRCA,INV_SRCA) select the SAME D3D blend state -- the capture shows both
as `src 5 dst 6` (SRC_ALPHA, INV_SRC_ALPHA) with srcA ONE / dstA ZERO. INFERRED (gate, single-valued):

| preset | D3D (SrcBlend, DestBlend) | seen |
|---|---|---|
| 1, 0x32 (hash 0x23baf183) | (SRC_ALPHA, INV_SRC_ALPHA) | 609 + 61 draws |
| 0x12 (hash 0xd3b1d189; also 0x11, 0x21) | (SRC_ALPHA, ONE) | 102 draws |
| 0x16, 0x19, 0x22, 7, 0 | UNKNOWN (never in a match capture) | 0 |

### 2.2 Sampler -> ring cmd 2 = `(filter == 0 ? 0x10000 : 0) | addr << 17`

```
clampUV = TSP>>15 & 3   (0 when ctx+0x1f8524 == 4, the UV-scroll mode)
addr = 1 if clampUV == 3 else 0 ; addr = 2 if TSP & 0x60000 (either flip bit)
FUN_140844320(TSP>>13 & 3, addr)     also stores them at ctx+0x1f8284 / +0x1f8288
```
Executor: `point = word>>16 & 1`, `addr = word>>17 & 3`; sampler object = `[R2+0x20] + {linear: addr 1 -> +0x17f0,
2 -> +0x3300, else +0x1790 ; point (or texture flag bit 16): 1 -> +0x17e0, 2 -> +0x32f0, else +0x1780}` (CONFIRMED
structure; the texture-flag term was never exercised -- every world texture is flag 0). INFERRED (gate):

| word | D3D (Filter, AddressU, AddressV) | seen |
|---|---|---|
| 0x00000 (linear, wrap) | (MIN_MAG_MIP_LINEAR 21, WRAP, WRAP) | 6 |
| 0x20000 (linear, clamp) | (21, CLAMP, CLAMP) | 657 |
| 0x30000 (point, clamp) | (MIN_MAG_MIP_POINT 0, CLAMP, CLAMP) | 113 |
| 0x10000 (point, wrap) | (0, WRAP, WRAP) -- the untextured HUD quads (texNum -1, TSP 20880440) | 48 |
| 0x40000, 0x50000 (flips) | UNKNOWN (-> +0x3300/+0x32f0, presumably MIRROR) | 0 |

A single-axis clamp (only bit 15 or only bit 16) is WRAP on both axes on Steam (`clampUV == 3` is the only clamp
case) -- CONFIRMED by code, and consistent with the gate (no per-axis mixed state was ever captured).

### 2.3 Depth -> ring cmd 8 (preset)

```
flush (FUN_140842e30):   10 if cat == 2 ; cat == 3: 2 if s19 == 0, 5 if s19 == 5, else 1 ; else 1
consumer (ctx+0x1f8520 == 1, set once in FUN_140607b50 @0x140607bfd):
   cat == 2                            -> 10
   ISP bit 26 == 0 (Z write ENABLED):     cat == 3 and s19 == 0 -> NO command (the flush's 2 stands)
                                          else                  -> 4 - (PCW bit 7 = shadow)   i.e. 4 or 3
   ISP bit 26 == 1 (Z write disabled)  -> 2
cat / s19 (FUN_1408436a0): PCW list type 0 (opaque): kind 2/0 -> cat 0, s19 0; kind 3 -> cat (0 if alpha==1 else 3), s19 1
                           list type 1 (opaque MV) -> cat 1 ; list type 2/3/4 (translucent/PT) -> cat 3, s19 0
```
Executor (cmd 8, CONFIRMED): DSS slot `1 -> R2+0x1e98, 2 -> +0x1ec8, 3 -> +0x1f08 with stencil ref 0x80, 4 -> +0x1f08,
5 -> +0x3678, 10 -> +0x3688 (+ blend +0x1c38, RS +0x1f58), 0xB -> +0x3698, default -> +0x1e88`. INFERRED (gate):

| preset | D3D (DepthWriteMask, StencilEnable) | captured detail | seen |
|---|---|---|---|
| 2 | (ZERO, off) | func LESS_EQUAL, srmask 255 | 167 |
| 4 | (ALL, on) | func LESS_EQUAL, stencil REPLACE, srmask 0, ref 0 | 609 |
| 3 | same DSS object as 4, stencil ref 0x80 (executor) | never captured | 0 |
| 1, 5, 10, 0xB | UNKNOWN | | 0 |

The ISP depth-compare bits (31-29) and ISP cull bits are NOT read: every captured draw is LESS_EQUAL regardless
(CONFIRMED: `FUN_1408482a0` reads only ISP bit 26 -- `uVar20 >> 0x1a & 1`).

### 2.4 Cull -> ring cmd 9 = `group_flags & 3` per polygon GROUP (only when entry[0xC8] < 2)

Executor: `2 -> RS R2+0x2038, 3 -> +0x1f68, else -> +0x1f58` (CONFIRMED). Gate: `1 -> NONE(1) x117, 2 -> FRONT(2) x627,
3 -> BACK(3) x32` (identity to `D3D11_CULL_MODE`); code 0 = the same object as 1 by the executor's default branch.
One record = several groups with DIFFERENT cull words in 4,099 of 39,585 records of the stage-11 tape, so a
record must be emitted as one D3D draw PER GROUP (tape_to_seq now does). The bit-13 path (`FUN_140849ac0`,
entry[0xC8] = 2) sends no cull word: those draws inherit the ring's previous cull state (stateful; tape_to_seq
carries `last_cull`).

### 2.5 Pixel shader variant and the batch id

`ignoreTexA = TSP bit 19 || (src == ONE && dst != ZERO)` is `FUN_140048370`'s 6th argument; the batch id is
`0x2000 + (TSP>>22 & 3 = fog control) + 1 for triangle lists`; texture id = `TCW & 0xFFFF` (0xFFFF when
`rec[0x20]` texNum < 0, and then the colour mode `rec[0x24]` is clamped to <= 0). Gate: bit 19 -> `opaque`
(classify_shaders' IgnoreTexA shader) x617, clear -> `texalpha` x159, 776/776. The D3D state-object CREATION
(where the hashes 0x23baf183.. and the DSS/RS slots receive their `D3D11_*_DESC`) was searched for in every
function of the dump (the hashes occur only in the executor and the blob `FUN_14006a3f0`; `FUN_1402ed380` /
`FUN_1402f8220` write those offsets in unrelated objects) and NOT found -- hence every "D3D (...)" column above is
INFERRED from the gate, single-valued per code, and refutable by any future capture that maps one code to two
states (`tsp_gate.py --hist` prints exactly that).

## 3. What the tape lacks for this to be exact

| field | used by | effect when missing |
|---|---|---|
| `node+0x90` f32 (alpha multiplier of flag-bit-5 nodes) | blend override 0x45 when != 1.0; cat 3 sort; vertex alpha | 4 of 106 additive draws in the gate were really normal-blended (bit-5 nodes at alpha < 1) |
| `blk+0x6CA8/6CAC/6CB0` (flags bit 11 colour) | vertex colour multiplier; the deck tint | deck/list-6 quads captured with vcol0 (B,G,R)=(0,0,255) on training vs 255,255,255 predicted |
| per-object `ctx+0x1f8524` mode (UV scroll) | clampUV forced 0; `local_res20 == 4` adds `entry+0x110/+0x114` to UVs | never seen != 0 in the gate |

The anode row is 96 B (`list@0, flags@4, matrix@8, colour(+0x94..)@72, obj@84, model@88`); adding `+0x90` is 4 B.

## 4. Vertex colour (CONFIRMED `FUN_1408482a0`, gate 647/776 exact at mult 1.0)

`colour0 = ARGB8((int)(rec+0x2C * 255 * entry[0xCC]), (int)(rec+0x30 * 255 * entry[0xD0]), +0x34 * entry[0xD4],
+0x38 * entry[0xD8])`, each clamped to 255, stored little-endian (bytes B,G,R,A) into vertex word 8; word 9
(offset colour) = 0 unless the config flag `PTR_DAT_140acd3a0[0x44f4] & 0x10` (lighting) -- 0 in every capture.
`entry[0xD0..D8]` = `FUN_140849b00(r,g,b)` clamped to [0,1] from `FUN_140620cd0`: flags bit 10 clear -> 1.0
(bit 11 -> `blk+0x6CA8..`), bit 10 set -> `node+0x94..9C` (bit 11 -> product). Colour mode `rec+0x24 == -3` ->
per-vertex BGRA @+0x10 times the same multipliers; `-1` -> flat; `>= 0` -> lit (needs the lighting flag).
Gate misses: (127,127,127) = node colour 0.5, (255,255,255,127) = alpha 0.5 via `+0x90`, (0,0,255) = the
training deck tint.

## 5. Winding (CONFIRMED `FUN_1408482a0` strip loop; gate 442/454)

Strips are expanded on the CPU unless group bit 6: even `i -> (v[i], v[i+1], v[i+2])`, odd
`i -> (v[i+2], v[i+1], v[i])`; 'triple' groups copied verbatim; the D3D draw is a triangle LIST. The old
`nl_triangles` (ModNao's bit0-dependent winding) reproduced only 133 of 454 captured draws; it never mattered
because the world template's raster was cull NONE. With the per-group cull word applied, Steam's rule is
required and is now what `nl_groups` emits. The 12 misses are bit-6 5-vertex strips (`0x72`, `0xF2`) whose
captured VB order is `(v0, v2, v1, v4, v3)`; the consumer that reorders them is not identified (UNKNOWN; their
state fields all pass).

## 6. Implementation

* `d3dcap/replay/tsp_state.py` -- `codes()` (CONFIRMED part), `HOST` (INFERRED tables), `predict()`, `captured()`.
* `d3dcap/replay/tsp_gate.py` -- the gate; `--hist` prints captured state per predicted code.
* `d3dcap/replay/tape_to_seq.py` -- `nl_groups` (Steam winding, per group), records carry `pcw/isp/tsp/groups/texnum`,
  `WorldTemplate.by_state`/`select()` serve a predicted state with the capture's own state objects (exact hit) or
  the ps-variant fallback patched (counted as `patched fallback` / `partial`), `emit_world` one draw per group with
  kind from the node flags and the node colour multiplier, `emit_stage` from the rip's header words.
* `maplecast-flycast/tools/rip_stage.py` -- meshes now carry `tsp` (u32 @+0x08); rips regenerated (17 stages).
* Fallbacks kept: no header word (old rip) -> ModNao `isOpaque`; unmapped code -> template field; no group cull in
  the rip -> template raster.

## 7. Falsification

1. Any capture where one code of section 2 maps to two D3D states (`tsp_gate.py --hist` flags it `AMBIGUOUS`).
2. A capture with a `blend` miss on a node whose flags lack bit 5 -- the alpha-multiplier explanation would be wrong.
3. Locate the state-object creation (search the retail exe for `D3D11_SAMPLER_DESC` writers feeding
   `[R2+0x20]+0x1790..`): the INFERRED tables must reproduce those descs.

## 8. Address index

`FUN_1408482a0` consumer kinds 0-3 - `FUN_1408436a0` queue append (cat/s19) - `FUN_140842e30` flush -
`FUN_140848ee0` record walk - `FUN_140849c10/c30/be0/ac0/9e0` draw entry points - `FUN_140620cd0` list walker -
`FUN_140849b00` colour mult - `FUN_140844220` blend preset - `FUN_140844320` sampler word - `FUN_1400483c0` /
`FUN_14004b9a0` ring writers - `FUN_140048810` ring reset - `FUN_140070940` ring executor - `FUN_140844a10`
ctx defaults (`+0x1f8274 = 0x45`) - `FUN_140607b50` (`ctx+0x1f8520 = 1`) - `FUN_140036560` empty stub.
ctx fields: `+0x1f8274` blend override, `+0x1f8284/88` last filter/addr, `+0x1f825c..64` colour mult,
`+0x1f8518` no-perspective (HUD kind select), `+0x1f8520` per-draw depth cmd enable, `+0x1f8524` UV mode,
`+0x1f8560` translucent-as-opaque switch (only read). Ring: `R+0xdbd08` base, `+0xdbd20` cursor, `+0xdbd28` bytes,
`+0xdbd2c` count, `+0xdbd38` seq.
