# How the Steam build draws the stage — Ghidra read-set (2026-09-02)

Binary: `mvc_dump.bin` (unpacked Steam MvC2, image base 0x140000000; Ghidra project `dumpproj`, read
through the GhidraMCP HTTP bridge on :8080 plus raw byte scans of the dump). Every claim below is tagged
**CONFIRMED** (function decompiled and read) or **INFERRED** (derived, not directly read). `blk` =
`DAT_142edf560`; `G` = `DAT_142edf580` = `blk + 0x3CB8` (CONFIRMED, `FUN_140608690` / `FUN_14060af70`).

## 0. Answer in one paragraph

The stage deck (STGxxPOL **model 0**) is **not in any System-A list**. It is drawn by a **direct call** in
the per-frame render dispatcher `FUN_140620960`: `FUN_140849c10(*(u64*)PTR_DAT_142edf588)` =
`FUN_140848ee0(model0, 0, 1.0f, 2)` with the matrix stack holding the **identity** and the vertex colour
set from `blk+0x6CA8/0x6CAC/0x6CB0`. `PTR_DAT_142edf588` points at a **static** model-pointer table
(`DAT_142edf630`, 352 x u64 host pointers, count at +0xB00, texture-header pointer at +0xB08) that the
stage loader `FUN_14060c370(1)` fills from the POL file loaded at DC address **0x0D82D000** (host
`ram + 0x182D000`, `ram = *(*(0x142ef0ab0)+8)`), **outside `blk`**. The stage's other models (props,
animated parts) ARE list nodes: the per-stage initialiser table run by `FUN_140620200` at match start
allocates them in **list 5** (`FUN_14061dbe0(0, 5, 1)`) with `node+0xA0 = PTR_DAT_142edf588[i]`. So
the tape is black on real stages because the thing that draws the deck has no node to harvest — the
harvester is looking in the right lists and finding exactly what is there. The fix is on the renderer
side: draw model 0 of `STG<stage_id>` with the identity world matrix, the match camera, and the
`blk+0x6CA8..` colour, gated by two bytes the tape does not yet carry.

## 1. The System-A node pool and lists (CONFIRMED)

| thing | where | source |
|---|---|---|
| node pool | `blk+0x6DD8`, 256 nodes x 0x280 (ends at `blk+0x2EDD8`) | `FUN_14061e170` (init) |
| free list head / tail | `blk+0x2EDD8` / `blk+0x2EDE0` | `FUN_14061e170`, `FUN_14061dbe0`, `FUN_14061df40` |
| list heads | `blk+0x2EDE8 + L*8`, L = 0..15 | same |
| list tails | `blk+0x2EE58 + L*8` | same |
| per-list counts (u16) | `blk+0x2EEC8 + L*2` | same |
| free counts (u16) | `blk+0x2EEE4` (=0xF6 at init), `blk+0x2EEE6` (=0x100) | `FUN_14061e170` |
| node links | `+0x08` prev, `+0x10` next, `+0x03` = list index | `FUN_14061df40` |

**Allocation = insertion.** `FUN_14061dbe0(ctx, L, kind)` pops a node from the free list, zeroes it,
writes `node+3 = L`, then calls the constructor table `PTR_caseD_4_140a6e5c8[kind]` (0x14061dde0,
0x14061dce0, 0x14061dd60, 0x14061dda0 — all bodies inside `FUN_14061d900`'s switch cases 5/6/7/default):
kind 1 = **append at tail** (`head[L]`/`tail[L]` write), default = prepend at head, 6/7 = insert
after/before a given node. `FUN_14061df40(node)` unlinks and returns it to the free list;
`FUN_14061e030(L)` frees a whole list; `FUN_14061e520(L)` runs every node's `+0x18` callback.

**Who allocates into which list** (byte-scan of all 988 `call FUN_14061dbe0` sites, `mov edx, imm`
decoded; sample of containing functions):

| L | count | allocators (examples) | what it is |
|---|---|---|---|
| 1..4 | ~560 | character / effect code (0x14065…–0x1407e…) | System-B sprite objects: `FUN_14060e3f0` feeds `FUN_14061e560(3,4,1,2)` which copies drawn cat<5 nodes into the sorted handle array `blk+0x2F4D0` the sprite walker uses (CONFIRMED) |
| 5 | 156 | **every per-stage initialiser** (`FUN_1406438e0` … `FUN_14064e8b0`), `FUN_14062ded0`, `FUN_140633bf0` | **stage props** (models 1..N of STGxxPOL) |
| 6 | 11 | `FUN_140625680`, `FUN_140625ed0`, `FUN_140632920`, `FUN_140654890`, `FUN_14079f330` | stage backdrop quads (training stage), misc |
| 7 | 69 | effect code | world-space effects (hail chunks, markers) |
| 8 | 21 | `FUN_140625680`, `FUN_140654900/980`, `FUN_140661240` … | 3D models via bank tables |
| 10 | 10 | `FUN_1407457c0` … | never drawn by the render dispatcher (UNKNOWN purpose; kind 0) |
| 11 | 36 | HUD code (`FUN_14062ce60` …) | HUD |
| 12 | 4 | `FUN_1406539a0` (one per fighter slot), `FUN_14073dfb0`, `FUN_1407ec920/c50` | per-fighter 3D part models (see 3.4) |

The table-of-tables `PTR_PTR_140a6ec20[stage_id]` + index lists `PTR_DAT_140a6ecb0[stage_id]` resolve to
(CONFIRMED by dump; stage ids >= 9 reuse the tables of ids 0..7 with different subsets):

```
stage 0x00: FUN_1406438e0 FUN_140643a00 FUN_140643c90 FUN_140643eb0 FUN_140644030
stage 0x01: FUN_140644180 FUN_140644320 FUN_140644710 FUN_1406449b0 FUN_140644ae0 FUN_140644f70
stage 0x02: FUN_140645900 FUN_140646bc0 FUN_140647c60 FUN_140648650 FUN_140648b30 FUN_140649d00 FUN_14064a430
stage 0x03: FUN_14064a930 FUN_14064aa40 FUN_14064ac60 FUN_14064ad60 FUN_14064b240 FUN_14064b750 FUN_14064ba30 FUN_14064bb40 FUN_14064bc50
stage 0x04: FUN_14064bd00 FUN_14064be70 FUN_14064c1f0 FUN_14064c300 FUN_14064c550 FUN_14064c790 FUN_14064c910 FUN_14064cac0
stage 0x05: FUN_14064ccd0 FUN_14064ced0 x3 FUN_14064d040 FUN_14064d220 FUN_14064d3e0 FUN_14064d4e0
stage 0x06: FUN_14064d780 FUN_14064daa0 FUN_14064dc70 FUN_14064e340
stage 0x07: FUN_14064e8b0 FUN_14064ea20
stage 0x08: FUN_14064fee0 FUN_140650390 FUN_140650620 FUN_1406507d0 FUN_1406508f0 FUN_140650a30
stage 0x09: FUN_140643a00 FUN_140644030 FUN_140650c10 FUN_140650d10
stage 0x0A: (= 0x01)
stage 0x0B: (none)  <- the TRAINING stage has no prop initialisers
stage 0x0C: (= 0x03)
stage 0x0D: FUN_14064be70 FUN_14064c550 FUN_14064c910 FUN_14064cac0 FUN_140650df0
stage 0x0E: FUN_14064ccd0 FUN_14064d040 FUN_14064d220 FUN_14064d3e0 FUN_140651050
stage 0x0F: FUN_14064dc70 FUN_14064e340 FUN_1406511c0
stage 0x10: FUN_14064e8b0 FUN_140651310
```

Read two of them: `FUN_140645900` (stage 2) and `FUN_14064d780` (stage 6/15): every node is
`FUN_14061dbe0(0, 5, 1)`, `+0x170 = 1`, `+0x18 = animation callback`, `+0xA0 = *(PTR_DAT_142edf588 + 8*i)`
(model i of the stage POL, i >= 1), `+0x50/54/58` position, `+0x5C/60/64` rotation (u16 angle units),
`+0xF0` flags (0x803/0x805/0x807/0x80F), and for child parts **`+0xE8 = parent_node + 0xA8`** —
i.e. `+0xE8` is a pointer to the PARENT NODE'S MATRIX, not a model (CONFIRMED in
`FUN_1406438e0`, `FUN_140645900`, `FUN_14064d780`; consumed in `FUN_140620740` at 0x140620787:
`mov rcx,[rbx+0xE8]; call FUN_140846c30` = load that 4x4 as the stack top before applying the node's
own pos/rot/scale). This explains the "model pointers at blk+0x12000..0x2EC00": they are addresses inside
the node pool (`blk+0x6DD8..0x2EDD8`) + 0xA8. Falsification: `(ptr - blk - 0x6DD8 - 0xA8) % 0x280 == 0`
for every such pointer in a tape.

## 2. Where the stage POL lives on Steam (CONFIRMED)

Memory model (`FUN_140607b50`): `base = *PTR_DAT_140acd3a0`; `ctx = DAT_142ef0ab0 = base + 0x8000000`;
`ctx[0] = base` (archive image), **`ctx[1] = base + 0x8400000` = the 32 MB DC work-RAM image** (filled 0xCD),
`ctx[3] = base + 0x8200000`, **`ctx[2] = blk = base + ((rand & 0x3F) + 0xC0) << 20`** (randomised per boot,
`FUN_14003ad20`). DC address `X` maps to host `ctx[1] + (X - 0x0C000000)` (`FUN_14060dcf0`,
`FUN_14060d8f0`, `FUN_14060c2f0`). `blk` is therefore NOT inside the DC RAM image and the POL is NOT inside
`blk`; the blk-relative offset of the stage data is not fixed (INFERRED from the random placement).

Stage load, `FUN_14060c370(1)` (called from the match-start case `switchD_14060e183::caseD_5` at
0x14060ed23, right after `FUN_14060b230` resets the bank tables):

```
FUN_14060dcf0(DAT_140a6aa80[stage_id], 0x0D82D000, 0);   // POL  : archive file 801 + 2*stage_id
FUN_14060dcf0(DAT_140a6aa30[stage_id], 0x0D85D000, 0);   // TEX  : archive file 802 + 2*stage_id
FUN_14060d770(0x0D82D000, 0x0D85D000);                   // relocate POL pointer table + patch TEX offsets
FUN_14060d470();                                         // build the model table
```

`stage_id = *(u8*)(blk + 0x6D04)` (CONFIRMED index into both tables; tables hold 17 valid entries,
ids 0x00..0x10: POL 801,803,…,833; TEX 802,804,…,834). `FUN_14060dcf0(i, dc, _)` copies archive entry `i`
(`{u32 offset @ base+8+i*8, u32 size @ base+0xC+i*8}`) to the DC address. Case 0x17 of the same switch
reloads only the POL (`0x0D82D000`) and rebuilds the table.

`FUN_14060d470` -> `FUN_1408458a0(0xC10)` (texture-slot base) then `FUN_14060d8f0(PTR_DAT_142edf588, 0x0D82D000)`:
`count = u32@POL+4`, `modelTable = host(u32@POL+0)` (used unmasked), `table[i] = host(modelTable[i])`,
`table+0xB00 = count`, `table+0xB08 = host(u32@POL+8)` (texture header list). Then per model
`FUN_140844dc0(model, texHeaders)` walks the model's records (PCW negative, `next = rec + rec[0x13] + 0x50`)
and assigns `rec[3] (TCW) = texIndex + 0xC10` -> **TCW = 0xC10 + texIndex** (CONFIRMED; matches the
memory rule). Special case: stage 0x10 patches ISP/TSP words of models 0..7 (`FUN_14060d470`).

Bank tables (all static, 0xB10 B each, set in `FUN_14060af70`/`FUN_14060b230`): `PTR_DAT_142edf588 =
&DAT_142edf630` (stage POL), `142edf590 -> 142ee0140` (0x0D000000 bank), `142edf598 -> 142ee0c50`
(0x0D082000 bank, used by list-12 part nodes), `142edf5a0..142edf620` (further banks, `FUN_14060c370`
cases 5..0x19).

## 3. The per-frame draw (CONFIRMED, `FUN_140620960`)

```
mode = *(int*)(blk + 0x6CE4)            // FUN_140619960
if mode == 0:
    FUN_140620f10()                      // sprite walker (System B)
    if *(u8*)(G + 0x98) == 0:            // G = blk+0x3CB8  -> blk+0x3D50
        if *(u8*)(blk + 0x6D04) != 8:    // stage 8 has no deck
            FUN_14061d7e0()              // camera: eye blk+0x6914/18/1C, look-at blk+0x695C/60/64,
                                         //   FOV blk+0x6974, near/far blk+0x6988/0x698C  (world units)
            FUN_140847950(0)             // push
            FUN_140847ca0()              // stack top = IDENTITY (constant at 0x140ab20c0, verified 1,0,0,0,…)
            FUN_140849b00(blk+0x6CA8, blk+0x6CAC, blk+0x6CB0)   // vertex colour, clamped to [0,1]
            FUN_140849c10(*(u64*)PTR_DAT_142edf588)             // == FUN_140848ee0(model0, 0, 1.0f, 2)
            FUN_1408478c0(1)             // pop
        FUN_14061d7e0(); FUN_140620740(5); FUN_140620cd0(5)     // stage props (list 5)
    FUN_14061d7e0(); FUN_140620740(6); FUN_140620cd0(6)
    FUN_14061d6a0(); FUN_140620740(7); FUN_140620cd0(7)         // camera x0.1 for 7/8/9
    FUN_14061d6a0(); FUN_140620740(8); FUN_140620cd0(8)
    FUN_140620ea0()                      // list 0xB (HUD) then list 0xC (see 3.4)
elif mode == 1:
    FUN_14061d6a0(); FUN_140620740(9); FUN_140620cd0(9); FUN_140620ea0()
else:
    FUN_140620f10(); lists 7, 8, 9 only  // no deck, no props, no HUD
```

### 3.1 The deck draw
`FUN_140848ee0(obj, _, maxColour, kind)` walks the object's records from `obj+0x18` while `(int)PCW < 0`
(`next = rec + rec[0x13] + 0x50`), optionally copies each record into the frame arena
(`ctx+0x100030`, when `ctx+0x1F855C` is set) and submits it with `FUN_1408436a0(kind=2, &rec, 0x130)`
using the CURRENT matrix-stack top (`DAT_142ef0ab8`) — the same consumer the list nodes use. **There is no
tree walk**: model 0 is one flat NaomiLib object. So the deck = `STG<id>POL model 0`, world matrix =
identity, camera = the list-5/6 camera (`FUN_14061d7e0`, world units, NOT the x0.1 variant), colour =
`blk+0x6CA8..0x6CB0`, textures via `TCW = 0xC10 + texIndex` from the stage TEX. Draw order: after the
sprite walk, before list 5.

### 3.2 List-5/6 nodes (`FUN_140620740` then `FUN_140620cd0`)
`FUN_140620740(L)`: per node: push; stack top = `*(+0xE8)` (parent matrix) or identity; if flag bit 14
`FUN_140846ee0(+0xA8)`; if bit 0 translate by `+0x50` (x0.1 for L=7/8/9); bits 8/7 billboard toward
`blk+0x6920/24/28`; bits 3/2/1 rotate `+0x64/+0x60/+0x5C`; bit 4 scale `+0x6C`; **`FUN_140846a00(+0xA8)`
STORES the stack top into `node+0xA8`**; pop. So `+0xA8` in a snapshot taken after this pass is the
fully composed world matrix (parent included) — the tape needs `+0xA8` only, not `+0xE8`.
`FUN_140620cd0(L)`: for nodes with `+0x170 != 0 && +0xA0 != 0`: optional `+0x40` callback; push;
`FUN_140846c30(+0xA8)`; bit 4 -> uniform scale max(+0x6C,+0x70,+0x74); colour = 1.0 / `+0x94..9C` /
`blk+0x6CA8..` / product (bits 10 and 11); bit 13 -> `FUN_140849ac0` (alpha 0x80 path); else L in {0xB,0xD}
-> `FUN_1408499e0`, other L -> `FUN_140849c10` (bit 5 -> `FUN_140849be0/c30` with `+0x90`); pop.

### 3.3 Who does NOT draw list 0xD, 9, 10
Only `FUN_140620960`/`FUN_140620ea0`/`FUN_140620ad0`/`b40`/`b90`/`bb0`/`c30` call the walkers. In
match mode 0 the drawn lists are 5,6,7,8,0xB,0xC. List 9 only in modes != 0; list 0xD and 10 are never
walked by these dispatchers (other screens may; UNKNOWN).

### 3.4 List 12 (0xC) — `FUN_140620ea0` -> `FUN_140653a70(node)` when `*(int*)(G+0x14) != 0x40`
Nodes come from `FUN_1406539a0(slot)`: **`+0xA0 = 0`, `+0xE8 = 0`, `+0xF0 = 0`**, `+0x28 = fighter
struct (blk+0x3DB8+slot*0x738)`, `+0x6C = DAT_140a79b50` scale. Drawn only if `+0x110 != 0` (a part list
`{i8 count, i8 flags, i8 scaleIdx, i8 modelIdx}` x8 B, models from `PTR_DAT_142edf598[idx]`, second pass
from `+0x118`, with `+0x80` rotation and `+0x228..` per-part indices). **The agent's filter
`nd[A_DRAWN] != 0 && (obj != 0 || model != 0)` drops every list-12 node by construction**, and
`ANODES_CAP_PER_FRAME = 96` is reached before list 12 on HUD-heavy frames (77 HUD nodes were seen).
Which characters set `+0x110` is UNKNOWN (not traced).

## 4. What the tape must carry for an exact stage (derived from 2–3)

Already in the tape: `stage_id` (blk+0x6D04), eyeX/eyeY/zoom (blk+0x6914/18/1C), list 5..13 nodes with
`+0xA8` matrix, `+0x94` colour, `+0xF0` flags, the `+0xA0` object.

Missing, and required for the deck to be pixel-exact:

| field | bytes | why |
|---|---|---|
| `G+0x98` = **blk+0x3D50** (u8) | 1 | when non-zero the deck AND list 5 (props) are skipped (super blackout); list 6 still draws (s3 pseudo-code). Set each frame in `FUN_14061f030` from `DAT_142edf628+0x96`. |
| `blk+0x6CE4` (i32 render mode) | 4 | deck drawn only in mode 0 (INFERRED constant 0 in a match — the tapes do contain list-5/6 nodes, which only mode 0 draws) |
| `G+0x14` = **blk+0x3CCC** (u32) | 4 | `== 0x40` disables list 12 and the prop init `FUN_140620200`; default 0x20 (`FUN_14060af70`). UNKNOWN what 0x40 means. |
| `blk+0x6CA8/0x6CAC/0x6CB0` (3 f32) | 12 | deck vertex colour; also multiplies nodes with flag 0x800 |
| `blk+0x695C/60/64` look-at, `blk+0x6974` FOV, `blk+0x6988/0x698C` near/far | 24 | the projection the deck uses (`FUN_14061d7e0`); INFERRED constant per match — verify before dropping |

Renderer rule for the deck (no node needed): `stage_id -> STG%02X` arc rip **model 0**, CBWorld =
identity, view/proj from the camera block in world units, colour = `blk+0x6CA8..`, textures
`STG%02X_t%02d` via `TCW - 0xC10`, submitted with kind 2 through the same path as list-5 objects,
in draw order sprite-walk -> deck -> list 5 -> 6 -> 7 -> 8 -> HUD -> list 12. Not drawn on stage 8.

For props, ship the model INDEX instead of the content hash: `i` such that
`node+0xA0 == *(u64*)(0x142edf630 + 8*i)` (static table, readable once per match, `count` at
`0x142edf630+0xB00`). Objects with `+0xA0` outside that table (banks 0x142ee0140.., HUD, effects) keep the
hash path.

## 5. Falsification tests (before anyone edits the renderer)

1. **Deck-not-a-node.** Live, on stage 2/5/15: `p = *(u64*)(0x142edf630)`; assert no node in lists 0..15
   has `+0xA0 == p`. Assert `p`'s records (walk as in 3.1) have vertices equal to the arc rip's STGxx
   model 0. If a node does hold `p`, section 0 is wrong.
2. **Gate bytes.** Sample `blk+0x3D50` and `blk+0x6CE4` at 60 Hz through a match with a level-3 super:
   expect `0x6CE4 == 0` throughout and `0x3D50` toggling non-zero exactly on the frames whose capture
   has no identity-CBWorld draws. If `0x3D50` never changes, the blackout has another owner.
3. **Identity draws in the capture.** In the d3dcap frame, the deck is the set of `vs_world` draws with
   CBWorld == identity (3x4 `1 0 0 0 | 0 1 0 0 | 0 0 1 0`); their vertex count must equal the rip's
   model-0 vertex count. That is the pixel-free gate; the pixel gate is the existing `v3gate` world-space
   pass with the deck emitted.
4. **List 12.** Count raw list-12 nodes with `+0x170 != 0` ignoring `+0xA0/+0xE8`; if > 0 while the tape
   shows 0, the filter/cap in `harvest_anodes` (reader.rs:1386-1425) is the owner, not the engine.
5. **Parent pointers.** `(node+0xE8 - blk - 0x6DD8 - 0xA8) % 0x280 == 0` for every non-zero `+0xE8` in a
   list-5 node.

## 6. Address index

`FUN_140620960` render dispatcher · `FUN_140849c10` deck draw · `FUN_140848ee0` polygon-list consumer ·
`FUN_1408436a0` queue append · `FUN_140847950/1408478c0/140847ca0/140846c30/140846a00` matrix stack
push/pop/identity/load/store · `FUN_14061d7e0` / `FUN_14061d6a0` / `FUN_14061d5b0` camera setups ·
`FUN_140849b00` colour · `FUN_140620740/140620cd0` list walkers · `FUN_140620ea0` HUD+list 12 ·
`FUN_140653a70` list-12 part draw · `FUN_14061dbe0` node alloc/insert · `FUN_14061df40` unlink ·
`FUN_14061e030` free list · `FUN_14061e170` pool init · `FUN_14061e560` list->sprite handles ·
`FUN_14060c370` bank loader (case 1 = stage) · `FUN_14060dcf0` archive->DC copy · `FUN_14060d770`
POL relocation · `FUN_14060d470` / `FUN_14060d8f0` model table · `FUN_140844dc0` texture slot assign ·
`FUN_140620200` per-stage prop init dispatcher (`PTR_PTR_140a6ec20`, `PTR_DAT_140a6ecb0`) ·
`FUN_140607b50` memory layout · `switchD_14060e183::caseD_5` match start ·
tables `DAT_140a6aa80` (POL file ids), `DAT_140a6aa30` (TEX file ids), `DAT_142edf630` (stage model table).
