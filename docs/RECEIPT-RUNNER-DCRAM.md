# RECEIPT-RUNNER-DCRAM — the DC work-RAM image a battle frame needs, from the SH4 side, mapped to Steam (2026-09-03)

## RE METHOD (locked, `docs/RE-METHOD.md`)

1. **Port the SH4 annotations to the Steam binary by function matching.**
2. **Seed with unique constants, then propagate along the call graph.**
3. **Translate globals through the block map before comparing reference sets.**
4. **Tag confirmed versus inferred, and store the pairs as edges in the knowledge graph.**

Steps taken here: (1)+(2) seeded on the constants `0x0C420000`, `0x00150000`, `0x0D82D000`, `0x0CEC5020`, `0x0CE60000`
and the per-slot address tables; propagated along `FUN_14060c370` (bank loader), `caseD_5` (match start),
`FUN_14061e520` (list callbacks) and the per-stage initialiser tables; (3) every DC address below is given next to its
Steam DC-image address and, for `blk`, through `d3dcap/replay/re_map/blkmap.py`; (4) tags on every row, seed sketch in §8.
Nothing was applied to `re_kb`; no code was modified.

Sources: marvelous2 `C:\Users\trist\projects\_marv_re\build\bank*.asm` + `memory/{work,pl_mem}.asm` (SH4);
Ghidra `mvc_dump.bin` via the :8080 bridge (Steam); `docs/STEAM-SH4-FUNCTION-MAP.md` + `steam_sh4_map.csv`;
`docs/{DETERMINISM-CONTRACT,FRAME-READSET,STAGE-DRAW-GHIDRA,TEXTURE-BANKS-GHIDRA,PALETTE-SOURCE-GHIDRA,PARTS-LIST0C-GHIDRA}.md`;
the live images `d3dcap/ttd/runs/20260903-000941/{pre,post}` (32 MB dcram each, clocks 2239 and 2476 = 237 frames apart,
stage 0x0B training, roster cids 42/52/44/23/52/53); `game_50.arc` read with `rip_texbank.load_afs`.
Tags: **CONFIRMED** = both sides read, or a byte-exact check on the live images; **INFERRED** = one side / structure only;
**UNKNOWN** = not located. Host address of a DC address X: `ctx[1] + (X - 0x0C000000)`, `ctx = *(0x142ef0ab0)`, `ctx[1] = ctx+8`
(CONFIRMED, `FUN_14060dcf0`; in the dump `ctx[1] = 0xFBC1000`).

## 0. Answers in one screen

| Q | Answer |
|---|---|
| 1 | The Steam DC-RAM image during a battle is 32 MB, of which the frame touches four kinds of bytes: **(a)** arc-derived, static in the match: six PL character slots `0x0C420000 + pos*0x150000` (each = **11 AFS files** + one engine-written region, recipe in §2.1, byte-exact on all 6 slots), effects bank `0x0D000000/0x0D026000`, HUD bank `0x0D082000/0x0D099000`, stage POL/TEX `0x0D82D000/0x0D85D000`; **(b)** the GGPO block `blk` — NOT inside the DC image at all on Steam (`blk = base + rand`), it is the DC "Game Global" block `0x8C2681DC..0x8C28AC20` plus two DC out-of-block regions the recompile folded in (palette rows `0x8C2659DC..` → `blk+0x1040..`, §1.3); **(c)** per-frame scratch inside the image: the tile table `0x0CE60000..0x0CE65000` (rebuilt every frame) and **in-place rewrites of (a) bytes** — stage-prop vertices (§4), effects-quad UVs (§3.3), HUD record TCWs (§3.4) — all written from `blk` node state before they are drawn; **(d)** outside the image and irrelevant to pixels: ctx TA records/texture staging, exe render bookkeeping, host textures. |
| 2 | Every (a) region is `memcpy(AFS entry -> DC address)` by `FUN_14060dcf0` = SH4 `loc_8c027366` (File Load). Rules: PL `209+cid` at the slot base, then `268/327/386/445/504/563/681/622/740 + cid` at `base+0x130000/0x13C000/0x13D000/0x13E000/0x140000/0x141000/0x142000/0x143000/0x144000`, the 32 KB tail `3+cid` at `base+0x148000`; stage `801/802+2*id`; effects 799/800; HUD 835/836. The Steam PL loader is **`FUN_14060d100(fighter, slot)`** (called 6x from `caseD_5`), SH4 counterpart **`loc_8c031fa0`** (bank03) — on DC the nine sub-tables are sections of ONE PL file (header words `+0x14..+0x34`); the recompile split them into separate AFS entries. Post-copy in-place patches the runner must replay: §2.3. |
| 3 | The tile table is rebuilt from PL data + node state every frame (`FUN_140612430 -> FUN_140614210`; the only read-before-write is 4,320 B copied into the write-only staging buffer — render-only, proven no effect). The in-place rewrites of stage/effects/HUD geometry are **absolute assignments from `blk` node fields + static tables + pristine sibling data**, executed in the sim phase (`FUN_1406283a0 -> FUN_14061e520(L)` callbacks) or at draw (`+0x40` callbacks, `FUN_140653a70`) BEFORE the polygons are submitted in the same frame. Nothing incremental lives in the image; an anchor need not carry any (c) range. What it must carry instead is `blk` (+ the C1/C7 pages of the contract) and pristine arc data placed by §2. |
| 4 | Stage props are pool nodes in list 5; each has a per-frame callback at `node+0x18` (DC `+0x10`) run by `FUN_14061e520(5)` = SH4 `loc_8c108430` loop. Stage 3/0xC (Carnival): `FUN_14064a840` = `loc_8c10eb3e` advances `node+0x30/+0x32` (DC `+0x1C/+0x1E`) and calls the morph `FUN_14064a4a0` = `loc_8c10ec26`, which lerps keyframe vertices from a table INSIDE the stage POL (`0x0D852020` = DC `0x0CEC5020`) into model 1. Stage 16/7 (River Raft): `FUN_14064e8b0` = `loc_8c1123a0` (parent + 8 rocked children) and `FUN_140751220` = `loc_8c1126a8` (3 water meshes 9/11/13 rewritten each frame from pristine models 10/12/14 by `FUN_140750eb0` = `loc_8c11284c` via the NaomiLib vertex iterator `FUN_1406196e0/580` = `loc_8c108060/086`). **Driver state = node shorts `+0x30/+0x32` (and `+0xF4/F8/FC` on the raft), the parent's `+0x60` rotation, the sin table `DAT_142ef0ac0`, exe constant tables — no frame counter.** So a renderer CAN pose them from keys: ship per list-5 node `{model index, +0x30, +0x32, +0xF4..FC, +0x34}` and port the three routines (§4.3). |

## 1. DC-RAM layout during a battle

### 1.1 What the two live images say (dcram pre vs post, 237 frames apart, CONFIRMED)

Only **13 of 8192 pages** differ (12,939 B):

| DC range | bytes | what |
|---|---|---|
| `0x0CE60000..0x0CE65000` | 12,879 | `Texture_Decompress_Buffer` (work.asm:36) = the per-frame decoded body-part tile table |
| `0x0D00C620/640/660/680`, `0x0D00D3E8/408/428/448` | 8 x 8 | effects POL (AFS 799) **model 80 and model 86**, vertex `u,v` words (`rec+0x70/0x90/0xB0/0xD0` = vertices 0..3 at `+0x18/+0x1C` of stride 0x20): `(0.245,0.255) -> (0.995,0.005)` — in-place UV animation (§3.3) |
| `0x0D082E6C`, `0x0D085424`, `0x0D085B9C`, `0x0D0865AC`, `0x0D086D3C`, `0x0D086F94`, `0x0D0872B4`, `0x0D088814`, `0x0D088CC4`, `0x0D0892FC` | 10 x 1 | HUD POL (AFS 835) models 3,10,12,15,17,18,20,27,28,29, byte `rec+0xC` = **TCW low byte `0x92 -> 0x93/0x94/0x95`** (TCW `0xC92..0xC95` = HUD pages) — in-place texture-slot selection (§3.4) |

Zero bytes differ in the six PL slots (`0x0C420000..0x0CC00000`), the stage POL/TEX, or anywhere else. The p-code
trace of ONE tick (FRAME-READSET §3) agrees: the tick's only dcram write range is `0x0CE60000..0x0CE62CDF`. A diff
cannot see writes that return to the same value; the trace can, and it saw none in the PL slots — so the flycast-lane
finding `replica_storm_scramble_is_static_gfx2_self_modify` (GFX2 dispatch entry mutated per sub-frame) is **not observed
on the Steam build on this frame/roster** (OPEN: that finding was on a Storm frame; re-check with a Storm roster trace).

Occupancy of the 32 MB image (sampled every 64 B, non-`0xCD`): `0x0C000000..0x0C400000` empty (the DC program image is
not consulted — the recompile carries code/tables in the exe), `0x0C400000..0x0CF00000` PL slots + misc, `0x0CF00000..
0x0D000000` empty, `0x0D000000..0x0DA00000` banks, `0x0DA00000..` empty.

### 1.2 Region map (DC-native address -> Steam DC-image address), with loaders

`pos` = PL slot position; fighter slot `s` -> `pos` via `DAT_140a6ab80 = {0,3,1,4,2,5}` = SH4 `bank14.loc_8c1491AC` order
(CONFIRMED both: `pl_A,B,C,D,E,F_datfile` = `0x0C420000, 0x0C810000, 0x0C570000, 0x0C960000, 0x0C6C0000, 0x0CAB0000`).

| class | DC (SH4) | Steam DC image | contents | SH4 loader | Steam loader | tag |
|---|---|---|---|---|---|---|
| (a) | `0x0C420000 + pos*0x150000`, 6 slots (pl_mem.asm:40-51) | same | PL character slot, recipe §2.1 | `loc_8c0275f6` state machine (bank02) -> `loc_8c027366` File Load; pointer cluster by **`loc_8c031fa0`** (bank03) | `FUN_14060dd40` (= `loc_8c0275f6`, queue) at select; **`FUN_14060d100`** at match start (`caseD_5` @0x14060ed63) | CONFIRMED |
| (a) | `0x0CC00000` (7th slot; `bank14.loc_8c149220` six 0x30000 areas) | `DAT_140a6d828[6] = 0x0CC00000` | select-screen / opening staging (case 5 `0x95`, case 9 `0x3E`, case 0x10/0x11) | `loc_8c032ca8` etc. | `FUN_14060c370` cases 5/9/0x10/0x11 | INFERRED not battle |
| (a) | `0x0CE30000 + slot*0x8000` (pl_mem `ptr_to_char_programming_A..F`) | **absent** | S_PLxx character CODE overlays | `loc_8c031fa0` tail: `+0x530 = 0x0CE30000 + n<<15`, then `jmp loc_8c02738a` (File Load) | none: per-character code is in the exe (`PTR_LAB_140a6eeb0[cid]` init table, `FUN_140623680`) | CONFIRMED (DC read; Steam absent by the 0x0CE30000 page being `0xCD`) |
| (c) | `0x0CE60000` Texture_Decompress_Buffer (work.asm:36) | same, `0x0CE60000..0x0CE65000` live | per-frame LZSS-decoded body parts (tile table); also load-time portrait pages (`FUN_14060d560`) | `loc_8c03552a` LZSS part decoder | `FUN_140612430 -> FUN_140614210` (unmatched in the map) | CONFIRMED (trace + diff) |
| (a) | `0x0CE80000` "DM00 Poly" (work.asm:37) = HUD/common POL copied there: `loc_8c032c80` memcpy 0x17000 from `0x0CD8D000`; TEX `0x0CD6F000` | `0x0D082000` / `0x0D099000` (AFS 835/836) | HUD bank, TCW base 0xC90 | `loc_8c032c80 -> loc_8c0322d4 (reloc) -> loc_8c032696` | `FUN_14060c370` case 4 -> `FUN_14060d560` (= `loc_8c032696`) | CONFIRMED |
| (a) | `0x0CEA0000` "Stage Poly" (work.asm:38; `loc_8c03223e` sets `*0x8c26a904 = 0x0CEA0000`), loaded via `0x0CC00000` (`loc_8c032c6e`) | `0x0D82D000` POL / `0x0D85D000` TEX (AFS `801/802+2*id`) | stage models, TCW base 0xC10; **Δ = +0x98D000** (the morph-table constants `0x0CEC5020 -> 0x0D852020` prove it) | `loc_8c032c6e -> loc_8c027366(bank14.loc_8c14cf98[STG_ID], 0x0CC00000)`, `loc_8c03223e` | `FUN_14060c370` case 1: `FUN_14060dcf0(DAT_140a6aa80[id], 0xD82D000)`, `(DAT_140a6aa30[id], 0xD85D000)`, `FUN_14060d770`, `FUN_14060d470` | CONFIRMED |
| (a) | `0x0CED0000` "Effect Poly" (work.asm:39), TEX `0x0CDA4000` (`loc_8c032c76`) | `0x0D000000` / `0x0D026000` (AFS 799/800) | effects bank, TCW base 0xC50 | `loc_8c032c76 -> loc_8c0322d4(0x0CED0000, 0x0CDA4000) -> loc_8c032320(0xC50, 0x8C26A908, ..)` | boot `FUN_14060c070`; case 2 -> `FUN_14060d080(0xC50, &PTR_DAT_142edf590, 0xD000000)` | CONFIRMED (TEXTURE-BANKS §2) |
| (a) | UNKNOWN DC address | `0x0D0C6000` / `0x0D0E5000` (AFS 837/838) | common bank 0x810 | opening loader `loc_8c027b64` family (INFERRED `0x0CD00000`) | case 5 `0x345/0x346` | Steam CONFIRMED, DC INFERRED |
| (a) | — | `0x0D25C000, 0x0D2B1000, 0x0D2BB000/0x0D2E9000, 0x0D3A2000, 0x0D4CE000, 0x0D6CC000, 0x0D720000, 0x0D7A9000, 0x0D7CC000`, `0x0CDD0000+k*0x10000` | select / VS / result / ending banks | — | `FUN_14060c370` cases 6,8,9,10,0xB..0x19 | CONFIRMED loaders; **not on the battle read set** (FRAME-READSET §3.2) |
| (b) | `0x8C2681DC..0x8C28AC20` Game Global block (`GameGlobalPointer 0x8c26823c`, work.asm:1) | **`blk[0..0x33B18)`, outside the DC image** (`blk = base + ((rand&0x3F)+0xC0)<<20`, `FUN_140607b50`) | all per-frame sim state | — | — | CONFIRMED (`blkmap.py`, memory note) |
| (b) | `0x8C2659DC + bank*0x30` palette staging rows (`loc_8c035162` pool, bank03:12125) | `blk+0x1040 + bank*0x38` (`FUN_1406146d0`/`FUN_140612930`) | the LUT rows the draws bind | `loc_8c035162`, load copy `loc_8c033aca` | `FUN_1406146d0`, `FUN_140612930` | pair CONFIRMED (PALETTE-SOURCE); address mapping INFERRED (stride 0x30 -> 0x38) |
| (d) | `0x8C28C864..0x8C28C87C` NaomiLib vertex-iterator cursor (`loc_8c108060`) | exe `DAT_142eee568..590` | src/dst record cursors for in-place mesh rewrites; write-before-read inside one callback | `loc_8c108060/086` | `FUN_1406196e0/580` | CONFIRMED |
| (d) | `0x8C16BC2C` RngVal (work.asm:15) | dead object `0x140a5c800`; the live RNG is `blk+0x32BD4/5` | — | — | — | CONFIRMED (DETERMINISM-CONTRACT §1.4) |
| (d) | PVR VRAM / TA FIFO (hardware, not RAM) | ctx TA records `ctx+0x30..`, `+0x30030..`, texture pages `ctx+0x100030..`, staging `*(game_state+0x208)` | render output | NaomiLib `loc_8c127c80` | `FUN_1408436a0`, `FUN_1408456a0` | CONFIRMED rebuilt per frame (FRAME-READSET §3.4-3.5) |
| (d) | AICA sound RAM (G2 bus, not in the 16 MB image); DC sound driver/ADX buffers in main RAM | not on the frame read set | audio | — | — | placement UNKNOWN; not needed for pixels |

### 1.3 The `blk` <-> DC map, one correction

`d3dcap/replay/re_map/blkmap.py` is the executable map (five deltas + pool + pointer-scaled tail + piecewise
stage/camera struct). It marks `blk+0x1000..0x3C66` as "outside the block map / DC counterpart UNKNOWN"
(FRAME-READSET §3.1). This crawl places one part of it: **`blk+0x1040 + bank*0x38` (16-colour LUT rows, first dword =
`1` valid flag, colours at `+4..+0x24`) is DC `0x8C2659DC + bank*0x30`** — `loc_8c035162` computes `r14 = char[+0x12E]*0x30
+ 0x8C2659DC` (bank03:12123-12138), and its Steam pair `FUN_1406146d0` (PALETTE-SOURCE-GHIDRA, "=") uses `blk+0x1040 +
bank*0x38`; `FUN_140612930` fills eight rows from `DatPal + costume*0x100` at `blk+0x1074 + bank*0x38 - 0x2C`. Tag INFERRED
(stride change read on both sides, base pairing by the single pair). On DC this was OUTSIDE the game-global block; the
recompile pulled it into `blk` so GGPO rolls it back — one more reason the Steam `blk` is a superset of the DC block.

## 2. Rebuilding the (a) regions from the user's arc

### 2.1 The PL slot recipe — 11 AFS files per character (CONFIRMED byte-exact on all six slots of the live image)

`FUN_14060d100(fighter, slot)` (Steam, called for `slot = 0..5` from `caseD_5` after `FUN_14060c370(1)`, `(2)`, `(4)`):

```
cid  = (i8)fighter+0x6C0           // = fighter+0x1 (character id; bit 0x100 of the u16 at +0x6C0 is a flag)
base = DAT_140a6d828[slot]         // {0x0C420000, 0x0C810000, 0x0C570000, 0x0C960000, 0x0C6C0000, 0x0CAB0000, 0x0CC00000}
FUN_14060dcf0(DAT_140a6d110[cid], base)                       // AFS 209+cid  -> base            (PL_DAT)
fighter+0x6B8 = host(base)                                     // Dat_FilePointer (DC +0x17C)
fighter+0x1A8 = host(base + u32@base+0x00)                     // Dat_GFX1 (DC +0x15C)   hdr[0] = 0x20
fighter+0x1B0 = host(base + u32@base+0x04)                     // Dat_GFX2 (DC +0x160)
fighter+0x1B8 = host(base + u32@base+0x08)                     // Dat_Pal  (DC +0x164)
fighter+0x1E0 = host(base + u32@base+0x0C)                     // section 3 (DC +0x178 Sprite_Extras, INFERRED)
fighter+0x1E8 = host(base + u32@base+0x10)                     // hdr[4] is 0 on Steam files -> points at base
fighter+0x1F0 = host(DAT_140a6d848[slot])                      // base+0x145000: engine-written region (no file)
fighter+0x171 = 1; +0x172 = DAT_140a6d188[+0x6B0]; +0x4C = DAT_140a6d910[cid]; +0x176 = (cid==0x34) ? 0x200 : 0x100
FUN_140612930(pal + costume(+0x6C1)*0x100, +0x172, 8)          // 8 LUT rows -> blk+0x1040 + bank*0x38
fighter+0x1C0 = host(DAT_140a6d708[slot]) ; FUN_14060dcf0(DAT_140a6d290[cid], ...)   // AFS 268+cid -> base+0x130000  animations (DC +0x168)
fighter+0x1C8 = host(DAT_140a6d728[slot]) ; FUN_14060dcf0(DAT_140a6d310[cid], ...)   // AFS 327+cid -> base+0x13C000  hitbox_pattern_table (DC +0x16C)
fighter+0x1D0 = host(DAT_140a6d748[slot]) ; FUN_14060dcf0(DAT_140a6d390[cid], ...)   // AFS 386+cid -> base+0x13D000  hitbox_data (DC +0x170)
fighter+0x1D8 = host(DAT_140a6d768[slot]) ; FUN_14060dcf0(DAT_140a6d410[cid], ...)   // AFS 445+cid -> base+0x13E000  attack_data (DC +0x174)
fighter+0x200 = host(DAT_140a6d788[slot]) ; FUN_14060dcf0(DAT_140a6d490[cid], ...)   // AFS 504+cid -> base+0x140000
fighter+0x208 = host(DAT_140a6d7a8[slot]) ; FUN_14060dcf0(DAT_140a6d510[cid], ...)   // AFS 563+cid -> base+0x141000
fighter+0x218 = host(DAT_140a6d7c8[slot]) ; FUN_14060dcf0(DAT_140a6d590[cid], ...)   // AFS 681+cid -> base+0x142000
fighter+0x210 = host(DAT_140a6d7e8[slot]) ; FUN_14060dcf0(DAT_140a6d610[cid], ...)   // AFS 622+cid -> base+0x143000
fighter+0x220 = host(DAT_140a6d808[slot]) ; FUN_14060dcf0(DAT_140a6d690[cid], ...)   // AFS 740+cid -> base+0x144000
```
plus, loaded EARLIER (VS screen, `FUN_14060c370` case 6 = SH4 `loc_8c032cbe`): `fighter+0x1F8 = host(DAT_140a6d868[slot])`,
`FUN_14060dcf0(DAT_140a6d190[cid] = 3+cid, base+0x148000)` — the 32 KB per-character HUD/portrait file, read at match start by
`FUN_14060d560` (portrait pages -> `0x0CE60000` -> TCW `0xC9A..0xCA5`) and mid-match by `FUN_1406162e0/FUN_140616330`
(character switch re-uploads), so it IS battle-relevant.

Slot addresses per `slot` index (tables at `0x140a6d708..0x140a6d888`, 7 entries, index 6 = the `0x0CC00000` spare slot):
`base+0x130000, +0x13C000, +0x13D000, +0x13E000, +0x140000, +0x141000, +0x142000, +0x143000, +0x144000, +0x145000 (+0x1F0), +0x148000 (+0x1F8)`.
All file tables are exact `cid + K` with `K = 209, 268, 327, 386, 445, 504, 563, 681, 622, 740, 3` for cids 0..56 (the
`3+cid` table collapses cids 25/26 onto 27). Maximum sizes over the roster fit the sub-slots: PL `0x12CEA0` (< `0x130000`),
anim `0x8E94` (< `0xC000`), hbp `0xDC0`, `0x800`, `0xE00`, `0x8CA`, `0xEC1`, `0xEA5`, `0x950`, `0xD87`, tail `0x7B50` (< `0x8000`).

**Gate run on the live image (2026-09-03):** for every slot `s` and every one of the 11 files, `dcram[addr : addr+size] ==
afs[entry]` — **66/66 byte-exact** (cids 42, 52, 44, 23, 52, 53). This closes the "PL loader table / tail loader UNKNOWN"
of `finding:determinism_pl_image_rule` and `finding:frame_minimum_tape`: the "dumped tail" is these ten extra files plus
the `+0x1F0` region. The `+0x1F0` region (`base+0x145000..+0x148000`, 12 KB) is not loaded from a file; it is identical in
pre and post (static in the match) and starts with a u16 offset table (`0000 0f00 1600 2200 2d00 ...`); its writer is
INFERRED to be `FUN_140612180` (= `loc_8c033d78`, the load-time body-sheet decoder run right after `FUN_14060d100` for the
same slot in `caseD_5`). The frame did not read it (FRAME-READSET §3.2 reads `0x0C42006C..0x0C55D7E8` for slot 0) — dump it
once per character or run `FUN_140612180`.

**SH4 side (CONFIRMED both read): `loc_8c031fa0` (bank03:4600-4690) is `FUN_14060d100`.** Same sequence: `+0x16C = base +
u32@+0x18`, `+0x170 = base+u32@+0x1C`, `+0x174 = base+u32@+0x20`, `+0x168 = base+u32@+0x14`, `+0x188.. = base+u32@+0x24/+0x28/
+0x30/+0x2C/+0x34`, then `+0x12E = table[byte@+0x524]` (= Steam `+0x172`), `+0x30 = table2[byte@+0x52C]` (= Steam `+0x4C`),
`+0x132 = 0x100` or `0x200` when `byte@+0x52C == 0x34` (= Steam `+0x176`), palette rows `jsr loc_8c033aca(pal + costume<<8,
+0x12E)` (= `FUN_140612930`). **The difference that matters to the runner:** on DC all nine sub-tables are SECTIONS OF THE
ONE PL FILE addressed by header words `+0x14..+0x34`; the Steam files have those words zero (`hdr[4..7] = 0`) and the
recompile loads them as separate AFS entries to fixed sub-slot offsets. The DC tail of `loc_8c031fa0` loads the S_PLxx code
overlay to `0x0CE30000 + n*0x8000` — nothing to do on Steam.

The DC load state machine `loc_8c0275f6` (bank02:17825) <-> `FUN_14060dd40` (CONFIRMED both read): 8-byte request descriptors
`{u8 flags, u8, u16 file_or_dstIdx, u32 dst_or_srcIdx}` (DC tables `0x8c1f8eac/0x8c1f938c`, Steam `DAT_142ec6de0/DAT_142ec6900`);
`flags & 0x80` -> queue a **slot-to-slot copy of `0x150000` bytes** (`loc_8c027aa4` 12-byte ring `0x8c1f932c` / Steam
`DAT_142ec6d80`, consumed by `FUN_14060d980`'s tail = `FUN_140800640(dst, src, 0x150000)`) — this is how the game avoids
reloading a character already resident in another slot; else -> File Load (`loc_8c027366` / `FUN_140800640` from the AFS TOC).
Post-load, both push `{u16 slot, u16 texId, u32 addr}` onto a second ring (`loc_8c027a7a` -> `0x8c1f92ac`; Steam
`DAT_142ec6d00`) whose consumer uploads texture slots (`FUN_14060d980`: `FUN_140845460(host(addr), id, 0x4000)` / `FUN_140845420(id)`)
— texture registration, not data placement. The map's `FUN_14060dd40 <-> loc_8c042d0c (low)` row is wrong; `loc_8c0275f6`
is the counterpart.

### 2.2 Banks (already CONFIRMED in TEXTURE-BANKS-GHIDRA §1-3; restated as the runner's rules)

| bank | AFS | Steam DC address | copy | then |
|---|---|---|---|---|
| stage POL / TEX | `801+2*id` / `802+2*id` (`DAT_140a6aa80/aa30`, `id = blk+0x6D04` u8) | `0x0D82D000` / `0x0D85D000` | `FUN_14060dcf0` x2 | `FUN_14060d770(POL,TEX)` relocation (= `loc_8c0322d4`), `FUN_14060d470` (model table `DAT_142edf630`, TCW = `0xC10+ti`, stage 0x10 ISP/TSP patch) |
| effects POL / TEX | 799 / 800 | `0x0D000000` / `0x0D026000` | boot `FUN_14060c070` | case 2 `FUN_14060d080(0xC50, &PTR_DAT_142edf590, 0xD000000)` |
| HUD POL / TEX | 835 / 836 | `0x0D082000` / `0x0D099000` | case 4 | `FUN_14060d560` (portraits from the six `+0x1F8` tails -> `0x0CE60000` -> TEX records 10../16..), then `FUN_140619720(model_i, &DAT_142eed370 + i*0x10)` for HUD models 0..3 |
| common POL / TEX | 837 / 838 | `0x0D0C6000` / `0x0D0E5000` | case 5 (select) | `FUN_14060d770`, base 0x810 |

The AFS POL files carry DC-native pointers (799 header `0x0CED0010`, 801.. `0x0CEA1000`, 835 `0x0CE81000`), i.e. the Steam
files are the DC files at their DC addresses; `FUN_14060d770` rebases them by `delta = *POL - POL - 0x10` — which is why the
DC->Steam bank deltas in §1.2 are exact constants (stage `+0x98D000`, effects `+0x130000`, HUD `+0x202000`).

### 2.3 In-place patches that make the live image differ from the AFS bytes (the runner must replay them or dump once)

| where | what | by | when | tag |
|---|---|---|---|---|
| every POL model record `rec+0xC` | `TCW = base + texIndex` (e.g. effects model 80: `0x44000000 -> 0x00000C63`) | `FUN_140844dc0` = `loc_8C122FD0` (high) | bank load | CONFIRMED (AFS vs live bytes) |
| POL header / model table / TEX `loc` fields | relocation to the Steam address | `FUN_14060d770` = `loc_8c0322d4` | bank load | CONFIRMED |
| stage 0x10 models 0..7 ISP/TSP words | per-stage fix-up | `FUN_14060d470` | case 1 | CONFIRMED (STAGE-DRAW §2) |
| HUD models 0..3 | `FUN_140619720(model, &DAT_142eed370+16*i)` | case 4 | match start | CONFIRMED site, body not read |
| effects model 20 `+0x20 |= 0x2000` | flag OR at effect-node init | `FUN_140660f40` | effect spawn (list 7) | CONFIRMED site; caller UNKNOWN |
| HUD TEX records 10..24 `loc` | portrait pages copied from `0x0CE60000` | `FUN_14060d560` | case 4 | CONFIRMED (TEXTURE-BANKS §6) |
| the per-frame rewrites of §3.3/3.4/§4 | vertices / UVs / TCW bytes | callbacks | every frame or draw | CONFIRMED regenerated |

Recommended runner order (mirrors `caseD_5`, 0x14060ed23, but WITHOUT the pool/camera re-initialisers that would clobber
the anchor's `blk`): `FUN_14060c370(1)`, `(2)`, case 6 for the six slots (tails), `(4)`, then `FUN_14060d100(f,s)` +
`FUN_140612180(f,s)` for `s = 0..5` — these touch the fighter pointer cluster `+0x1A8..+0x220`, `+0x4C`, `+0x171..0x177`,
`+0x6B8` and `blk+0x1040..` rows, all of which the anchor already holds with the SAME values (they are deterministic
functions of cid/costume), so re-running them on top of the anchor is idempotent; then overlay the anchor and relocate the
557 dcram pointers by `Δ_dcram` (DETERMINISM-CONTRACT §1.1b). Do NOT run `FUN_14061e170` (pool init), `FUN_14061c6e0`
(camera), `FUN_140620200` (stage props — allocates the list-5 nodes the anchor already has) on an anchored `blk`.

## 3. Per-frame scratch: is it fully regenerated?

### 3.1 The tile table `0x0CE60000` — YES
Built by the tick (`FUN_140612430 -> FUN_140614210`, 11,488 B; DC `loc_8c03552a`) from PL data + node state, then read by the
same frame's staging copy. The only read-before-write is 4,320 B at `0x0CE60040..` copied by `FUN_140800620` into the
write-only staging buffer `*(game_state+0x208)`; zero-filling it changes no `blk`, ctx or staging byte (DETERMINISM-CONTRACT
§1.1 `dcram_tiletab_prev`). CONFIRMED. An anchor need not carry it.

### 3.2 List-5 stage props — YES (details §4)
Vertices are ABSOLUTE functions of node fields + static data, written in the sim phase of the same frame that draws them:
`FUN_1406283a0` (called from `FUN_14060e3f0` on the match path) runs `FUN_14061e520(L)` for L = 3,4,1,2,5,6,10,7,8,9,0xB,0xC
(order as decompiled; `FUN_14061e520(L)` = for each node in list L call `*(node+0x18)(node)`), and only afterwards does
`FUN_14060b960 -> FUN_140620960` draw. CONFIRMED (decompile + callback bodies read).

### 3.3 Effects-quad UV animation — YES
Pool nodes bound to effects model 80/86 (live: nodes 207..232 in `post/blk.bin`, list 7, `+0x18 = 0x1407972d0` = a state
dispatcher `jmp [0x140AA2940 + node[+4]*8]` on the owner `node+0x28`, `+0x40 = FUN_140797690` on the drawn ones).
`FUN_140797690(node)`: `src = PTR_DAT_142edf590[+0x2B8 or +0x288]` (pristine sibling model 87 or 81, chosen by `node+0xFC`);
`FUN_1406196e0(src, node+0xA0)`; for each vertex `dst.uv = src.uv + DAT_140aa2860[node+0x30*2]` (`FUN_140619530` reads
`+0x18/+0x1C`, `FUN_1406196a0` writes them and sets bit 0 of `v`); then `ctx+0x1f855c = 1`. Absolute, from `node+0x30` (in
`blk`) and a pristine model in the image. CONFIRMED (decompile). SH4 counterpart: the iterator is `loc_8c108060/086`
(CONFIRMED); the UV callback itself UNKNOWN (not traced; find via the DC constant for `DAT_140aa2860`).

### 3.4 HUD record TCW bytes — YES
`rec+0xC` low byte of HUD models 3,10,12,... = `0xC92 + count - 1` written by the combo-counter draw `FUN_140653a70`
(= `loc_8C0F215E`, PARTS-LIST0C-GHIDRA "page via the header patch"). Written at draw, absolute. CONFIRMED site (doc) —
that all ten patched models belong to that path is INFERRED (they are the digit/rating part models; not traced one by one).

### 3.5 What persists across frames and must be in the anchor
Nothing in the DC image beyond the pristine arc bytes of §2 + the load-time patches of §2.3 (which are deterministic
functions of roster/stage). The stale values left in the image (last-frame UVs, TCWs, morphed vertices, the previous tile
table) are overwritten before use or unread. The hidden-state inventory (DETERMINISM-CONTRACT §1.1) found the same by
perturbation. OPEN: only two stages' callbacks (3/0xC and 7/0x10) and one effect family were read; the remaining stage
initialisers (`PTR_PTR_140a6ec20`, STAGE-DRAW §1) may contain a callback that integrates (`v += ...`) into the model — the
falsifier is one emulated tick on a stage-N image with the stage POL zero-filled: if `blk` differs, some callback read it.

## 4. Stage animation — routines, driving state, what a renderer needs

### 4.1 Dispatch (CONFIRMED both read)
Per-stage initialiser lists: Steam `PTR_PTR_140a6ec20[stage]` + index list `PTR_DAT_140a6ecb0[stage]`, run by `FUN_140620200`
at match start; SH4 `bank16.loc_8c165a78[stage]` (routine tables, e.g. Carnival `loc_8c1659c8` = `loc_8c10eadc, loc_8c10ee2a,
loc_8c10ef68, loc_8c10f18c, loc_8c10f4ac, loc_8c10f504, loc_8c10fb24, loc_8c10fba0`; River Raft/Ice River `loc_8c165a50` =
`loc_8c1123a0` (+ `loc_8c165a58` = `loc_8c112a90, loc_8c112bbc`)) + index lists `bank16.loc_8c165c64[stage]` (Carnival
`loc_8c165b10` = 0,1,2,3,4,5,6,7,9; River Raft `loc_8c165c58` = 0,3; Training `loc_8c165bec` = none), run by **`loc_8c108430`**
(bank10:19953: `r11 = loc_8c165a78`, `r10 = loc_8c165c64`, loop until index `0xFF`). The map's `FUN_140620200 <-> loc_8c045ce0`
(high) is a caller/callee slip: `loc_8c045ce0` is the match-start sequence that CALLS `loc_8c108426` (bank04:14015);
`FUN_140620200`'s body is `loc_8c108426 -> loc_8c108430`. Per-frame: `FUN_14061e520(5)` = the `+0x10` callback loop.

### 4.2 The two stages measured

**Carnival (stage 3; 0xC = alt) — the "1008-B meshes".** `FUN_14064a930` = `loc_8c10eadc`: one list-5 node, `+0xA0 = model 1`,
flags `0x807`, callback `FUN_14064a840` = **`loc_8c10eb3e`** (bank10:35270). Per frame: `node+0x30++` (DC `+0x1C`); when it
reaches `DAT_140a771d0[node+0x32]` (duration of phase `+0x32`, DC `+0x1E`, 34 phases `0..0x21`) advance the phase; `t =
sin(angle(+0x30/duration))`-shaped weight (`FUN_140845150` = sin table `DAT_142ef0ac0`); then **`FUN_14064a4a0(node, keyA =
DAT_140a77140[phase], keyB = DAT_140a77144[phase], w)` = `loc_8c10ec26`** (bank10:35400): morph table `T` at DC `0x0CEC5020`
(stage 3) / `0x0CEC4918` (stage 0xC) = Steam `0x0D852020` / `0x0D851918` (**inside the stage POL**): `n = T[0]`, `T[2..2+n]` =
dword indices into the model, then keyframes of `n` xyz floats; for each `i`: `model[idx_i] = lerp(key[A][i], key[B][i], w)`
and `model[idx_i].x |= 1` (the strip flag). Absolute writes into model 1 of the stage POL. Other Carnival nodes
(`FUN_14064aa60` = rotation `+0x5C` from a 360-step counter; `FUN_14064b370` = state machine rotating `+0x60`) only move the
node matrix, not vertices.

**River Raft (stage 0x10; Ice River 7 shares the table) — the "5040-B mesh, 200/1260 dwords per frame".**
`FUN_14064e8b0` = `loc_8c1123a0`: a parent node (no model, `+0x170 = 0`, flags `0x80F`, `+0x32 = 1`) and 8 children (models 1..8,
flags `0x800`, `+0xE8 = parent+0xA8`, `+0x34 = i`), all with callback `LAB_14064e5e0` = `loc_8c112404` (Ghidra has no function
there; disassembled 2026-09-03): a keyframe table (28-byte records at `0x140a78305`-relative `rsi`) indexed by `+0x32` with
`+0x30` as the phase clock; `FUN_140644770` (Catmull/Bezier weights) -> rotation `+0x5C/+0x60/+0x64` (negated) and position
`+0x50/54/58` via a matrix push/rotate/transform/pop; the clock advances by `1 + (stage != 7)` per frame, phase wraps at 0x59.
Then `FUN_140751220(parent)` = `loc_8c1126a8`: 3 nodes (models 9, 11, 13; flags `0x81F`; `+0x30 = +0x32 = 0x3C*i`, `+0xF4 = i<<12`,
`+0xF8 = 0x3000*i`, `+0xFC = 0x5000*i`, `+0x20 = parent`), callback `FUN_1407511c0` = `loc_8c1127c8`: `+0x50 = X_i -
sin(parent+0x60) * k`, then **`FUN_140750eb0` = `loc_8c11284c`**: `+0x30 += +0x34 + 1 (mod 0x5A0)`, `+0x32++ (mod 0x168)`,
`+0xF4 += 0x100`, `+0xF8 += 0x80`, `+0xFC += 0x40`; `FUN_1406196e0(src = model 10/12/14, dst = node+0xA0 = model 9/11/13)`; for
every vertex: `dst.x = src.x + sin(+0x32) * A_i * sin((+0x30>>2) + 30*k)`, `dst.colour = packed(sin(+0xF4+0x800k),
sin(+0xF8+..), sin(+0xFC+..))`. That is the water: x and colour of every vertex (2 dwords each) rewritten from a pristine
sibling model — your 200 changing dwords in a 1260-dword mesh. Absolute; driver = node shorts and the three phase ints, all in
the pool node (`blk`). SH4: `loc_8c11284c` uses the same iterator (`bank10.loc_8c108060` = `FUN_1406196e0`, `loc_8c108086` =
`FUN_140619580`, cursor globals `0x8C28C864..0x8C28C87C` = `DAT_142eee568..590`), constants `0x05A0`, `0x0168`, `0x0100`, `0x0080`
in its pool (bank11:5792-5807) — CONFIRMED both read.

Iterator API (CONFIRMED both): `FUN_1406196e0(src,dst)` sets `cur_src = src+0x18`, `cur_dst = dst+0x18`; `FUN_140619580()`
steps record/vertex (records while `PCW < 0`, `+0x50` header; vertex count `rec+4` (x3 unless `PCW & 0x10`); strip end = bit 0
of the vertex's first word; vertex stride `0x20`), returns `-1` at the end; `FUN_140619510/680` read/write xyz (sets bit 0),
`FUN_140619550/6c0` read/write `+0xC..+0x14`, `FUN_140619530/6a0` read/write `u,v` at `+0x18/+0x1C`.

### 4.3 What decides "poses from keys" for the renderer
Everything the callbacks read is either in the pool node (`+0x30`, `+0x32`, `+0x34`, `+0xF4/F8/FC`, parent `+0x60`, `+0xA0`
model, `+0xE8` parent matrix), in exe constant tables, in the sin table, or in the PRISTINE stage POL (morph keyframes, source
models). No frame counter and no RNG. Therefore a tape/renderer can regenerate the deformed meshes offline from per-node
keys: `{stage_id, model index i = (node+0xA0 - table)/8, +0x30, +0x32, +0x34, +0xF4, +0xF8, +0xFC, parent +0x60}` per list-5
node per frame — 20 bytes instead of the mesh — by porting `FUN_14064a4a0`, `FUN_140750eb0` (+ `LAB_14064e5e0` if the node
matrix is not shipped) and using the `rip_stage`/arc POL as the pristine source. Numeric gate: per-vertex diff of the ported
output against the harvested `node+0xA0` bytes of a stage-16 / stage-3 tape frame (0.0 relative = exact), per cardinal rule 3.
Coverage caveat: 15 other stage tables exist (§4.1); each callback must be classified (matrix-only vs vertex-writing) before
the key form is declared complete — enumerable from `PTR_PTR_140a6ec20` in one Ghidra pass.

## 5. Corrections to existing records (for the seed)

* `steam_sh4_map.csv`: `FUN_14060dd40 <-> loc_8c042d0c (low)` -> **`loc_8c0275f6` (confirmed)**; `FUN_140620200 <-> loc_8c045ce0
  (high)` -> **`loc_8c108426`/`loc_8c108430` (confirmed)**, `loc_8c045ce0` is the caller; `FUN_14060d770 <-> loc_8c129668
  (high)` is already falsified by TEXTURE-BANKS §7 (`loc_8c0322d4`) but still in the csv; `FUN_1408435d0 <-> loc_8c03552a
  (medium)` conflicts with TEXTURE-BANKS §1 (`FUN_1408435d0` = slot fill from a 16-B record) — `loc_8c03552a` (LZSS part
  decoder, KB) pairs with **`FUN_140614210`** (INFERRED: same role and target `0x0CE60000`; unmatched in the map).
* `finding:determinism_pl_image_rule` / `finding:frame_minimum_tape`: "loader UNKNOWN" -> resolved (`FUN_14060d100` =
  `loc_8c031fa0`; 11 files + `+0x1F0` region), see §2.1. C5 of the contract becomes fully arc-derivable except the 12 KB
  `+0x1F0` region (writer INFERRED `FUN_140612180`).
* `finding:frame_readset` "blk+0x1000..0x3C66 outside the block map": `blk+0x1040+bank*0x38` = DC `0x8C2659DC+bank*0x30` (§1.3).
* `re-catalog`/memory note "GFX2 self-modify per sub-frame": not observed on Steam on this frame (§1.1) — OPEN, needs a Storm trace.

## 6. Open items

1. DC address of the common bank (837/838) and of the stage TEX on DC (work.asm names only the POL at `0x0CEA0000`).
2. The `+0x1F0` region writer (INFERRED `FUN_140612180`); confirm by emulating it on a zeroed region and diffing against the dump.
3. Stage callbacks of the other 15 stage tables: matrix-only vs vertex-writing classification.
4. The effects UV state dispatcher table `0x140AA2940` and its SH4 counterpart.
5. Whether any battle path reads `0x0CE30000..0x0CE60000` on Steam (the DC S_PLxx overlay window) — the trace says no; the image page is `0xCD`.
6. HUD TCW patch: trace one frame with a combo counter on screen to attribute all ten models to `FUN_140653a70`.

## 7. Address index

Steam: `FUN_14060c370` bank loader (cases 1,2,4,5,6,9,10,0xC..0x19) · `FUN_14060dcf0` AFS copy · `FUN_14060d100` **PL slot loader** ·
`FUN_14060dd40` select-time load queue · `FUN_14060d980` copy/texture ring consumer · `FUN_14060d560` HUD bank + portraits ·
`FUN_14060d770` relocation · `FUN_14060d470` stage model table · `FUN_140844dc0` TCW assign · `FUN_140612930` LUT rows ·
`FUN_140612180` sheet decoder · `FUN_140612430`/`FUN_140614210` per-frame tile table · `FUN_140620200` stage prop init ·
`FUN_14061e520` list callbacks · `FUN_1406283a0` sim-phase callback driver · `FUN_14064a930/a840/a4a0` Carnival ·
`FUN_14064e8b0`, `LAB_14064e5e0`, `FUN_140751220/11c0`, `FUN_140750eb0` River Raft · `FUN_1406196e0/580/510/680/550/6c0/530/6a0`
vertex iterator · `FUN_140797690` effects UV · `FUN_140653a70` HUD TCW · tables `DAT_140a6d110..0x140a6d690` (AFS by cid),
`DAT_140a6d708..0x140a6d888` (sub-slot addresses), `DAT_140a6abb8`/`DAT_140a6d828` (slot bases), `DAT_140a6ab80` (slot->pos).
SH4: `loc_8c027366` File Load · `loc_8c0275f6` load state machine · `loc_8c027aa4`/`loc_8c027a7a` rings · `loc_8c031fa0` **PL
pointer cluster** · `loc_8c032be0` bank loader (cases at `loc_8c032c6e` stage, `c76` effects, `c80` HUD, `cbe` case 6) ·
`loc_8c03223e` stage register · `loc_8c0322d4` relocation · `loc_8c032320` bank register · `loc_8c033aca` LUT rows ·
`loc_8c035162` LUT staging · `loc_8c03552a` LZSS · `loc_8c108426/430` stage init dispatcher · `loc_8c10eadc/eb3e/ec26`
Carnival · `loc_8c1123a0/112404/1126a8/1127c8/11284c` River Raft · `loc_8c108060/086` iterator · tables `bank14.loc_8c1491AC`,
`bank16.loc_8c165a78/c64`, morph `0x0CEC5020/0x0CEC4918`.

## 8. Seed sketch (NOT applied) — `tools/re_kb/112_runner_dcram.surql`

```sql
USE NS re DB kb;
-- sources
UPSERT source:doc_receipt_runner_dcram SET kind='doc', strength='code', ref='mvc-live-skins-quarters/docs/RECEIPT-RUNNER-DCRAM.md', note='DC work-RAM map for a battle frame, SH4 -> Steam by function matching; PL slot recipe gated 66/66 byte-exact on runs/20260903-000941.';
UPSERT source:dcram_diff_20260903_000941 SET kind='capture', strength='runtime', ref='d3dcap/ttd/runs/20260903-000941 pre/post dcram.bin', note='237-frame diff: 13 pages, 0x0CE60000 tile table + 8x8 B effects UVs (models 80/86) + 10x1 B HUD TCW bytes; PL slots and stage POL unchanged.';
-- routines (Steam side)
UPSERT steam_routine:FUN_14060d100 SET addr='0x14060d100', role='PL slot loader: 10 AFS files per character to base+0/0x130000/0x13C000/0x13D000/0x13E000/0x140000..0x144000, fighter pointer cluster +0x1A8..+0x220, LUT rows', consts=['0xC420000','0x150000'];
UPSERT steam_routine:FUN_14060dd40 SET addr='0x14060dd40', role='select-time character load queue (8-B descriptors; 0x80 = slot copy 0x150000)';
UPSERT steam_routine:FUN_14064a4a0 SET addr='0x14064a4a0', role='Carnival vertex morph: lerp keyframes from the POL table 0x0D852020/0x0D851918 into model 1';
UPSERT steam_routine:FUN_14064a840 SET addr='0x14064a840', role='Carnival prop callback: node+0x30/+0x32 phase clock, 34 phases';
UPSERT steam_routine:FUN_14064e8b0 SET addr='0x14064e8b0', role='River Raft init: parent + 8 rocked children, callback LAB_14064e5e0';
UPSERT steam_routine:FUN_140751220 SET addr='0x140751220', role='River Raft water init: 3 nodes, models 9/11/13, callback FUN_1407511c0';
UPSERT steam_routine:FUN_140750eb0 SET addr='0x140750eb0', role='River Raft water rewrite: dst = pristine model 10/12/14 + sin(node+0x30/+0x32/+0xF4..FC)';
UPSERT steam_routine:FUN_1406196e0 SET addr='0x1406196e0', role='NaomiLib vertex iterator begin (src,dst)';
UPSERT steam_routine:FUN_140619580 SET addr='0x140619580', role='NaomiLib vertex iterator step';
UPSERT steam_routine:FUN_140797690 SET addr='0x140797690', role='effects quad UV rewrite: model 80/86 uv = sibling 81/87 uv + DAT_140aa2860[node+0x30]';
UPSERT steam_routine:FUN_140620200 SET role='per-stage prop initialiser dispatcher (PTR_PTR_140a6ec20 / PTR_DAT_140a6ecb0)';
-- routines (SH4 side)
UPSERT routine:loc_8c031fa0 SET pc='0x8c031fa0', bank='bank03', name='PL pointer-cluster loader', note='+0x168/16C/170/174/188.. = base + header words +0x14..+0x34; +0x12E/+0x30/+0x132 tables; jsr loc_8c033aca LUT rows; loads S_PLxx overlay to 0x0CE30000+n*0x8000';
UPSERT routine:loc_8c0275f6 SET pc='0x8c0275f6', bank='bank02', name='character file-load state machine';
UPSERT routine:loc_8c108430 SET pc='0x8c108430', bank='bank10', name='per-stage init dispatcher loop (tables bank16.loc_8c165a78 / loc_8c165c64)';
UPSERT routine:loc_8c10eb3e SET pc='0x8c10eb3e', bank='bank10', name='Carnival prop callback';
UPSERT routine:loc_8c10ec26 SET pc='0x8c10ec26', bank='bank10', name='Carnival vertex morph (table 0x0CEC5020 / 0x0CEC4918)';
UPSERT routine:loc_8c1123a0 SET pc='0x8c1123a0', bank='bank11', name='River Raft init';
UPSERT routine:loc_8c1126a8 SET pc='0x8c1126a8', bank='bank11', name='River Raft water init';
UPSERT routine:loc_8c11284c SET pc='0x8c11284c', bank='bank11', name='River Raft water rewrite';
UPSERT routine:loc_8c108060 SET pc='0x8c108060', bank='bank10', name='vertex iterator begin (globals 0x8C28C864..)';
UPSERT routine:loc_8c108086 SET pc='0x8c108086', bank='bank10', name='vertex iterator step';
-- pairs
RELATE steam_routine:FUN_14060d100->recompiles->routine:loc_8c031fa0 SET confidence='confirmed', method='both read', evidence='same header->pointer sequence, +0x12E/+0x30/+0x132 (0x100/0x200 if cid 0x34) and LUT-row call; Steam splits the DC sections into AFS 268/327/386/445/504/563/681/622/740+cid';
RELATE steam_routine:FUN_14060dd40->recompiles->routine:loc_8c0275f6 SET confidence='confirmed', method='both read', evidence='8-B descriptor {flags,fileid,dest}, tst 0x80 -> 0x150000 slot copy via 12-B ring (0x8c1f932c / DAT_142ec6d80), else File Load; post-load 8-B ring 0x8c1f92ac / DAT_142ec6d00';
RELATE steam_routine:FUN_140620200->recompiles->routine:loc_8c108430 SET confidence='confirmed', method='both read', evidence='table-of-tables + index list until 0xFF; loc_8c045ce0 is the CALLER (corrects map row)';
RELATE steam_routine:FUN_14064a840->recompiles->routine:loc_8c10eb3e SET confidence='confirmed', method='both read';
RELATE steam_routine:FUN_14064a4a0->recompiles->routine:loc_8c10ec26 SET confidence='confirmed', method='both read', evidence='morph table constants 0x0CEC5020/0x0CEC4918 <-> 0x0D852020/0x0D851918 (delta 0x98D000 = stage POL relocation)';
RELATE steam_routine:FUN_14064e8b0->recompiles->routine:loc_8c1123a0 SET confidence='confirmed', method='both read', evidence='8 children loop, flags 0x80F, +0x1E=1';
RELATE steam_routine:FUN_140751220->recompiles->routine:loc_8c1126a8 SET confidence='confirmed', method='both read', evidence='3 nodes, flags 0x81F, 0x3C*i counters';
RELATE steam_routine:FUN_140750eb0->recompiles->routine:loc_8c11284c SET confidence='high', method='both read (pool constants 0x5A0/0x168/0x100/0x80, iterator calls)';
RELATE steam_routine:FUN_1406196e0->recompiles->routine:loc_8c108060 SET confidence='confirmed', method='both read';
RELATE steam_routine:FUN_140619580->recompiles->routine:loc_8c108086 SET confidence='confirmed', method='both read';
-- globals
UPSERT global:dc_8c2659dc SET addr='0x8C2659DC', name='palette staging rows (DC, stride 0x30)', steam='blk+0x1040 stride 0x38', confidence='inferred', evidence='loc_8c035162 pool + FUN_1406146d0/FUN_140612930';
UPSERT global:dc_8c28c864 SET addr='0x8C28C864..0x8C28C87C', name='NaomiLib vertex iterator cursor', steam='DAT_142eee568..0x142eee590', confidence='confirmed';
-- findings
UPSERT finding:pl_slot_recipe SET status='confirmed', confidence='high', date='2026-09-03', contribution_candidate=true, note='Each PL slot 0x0C420000+pos*0x150000 = AFS 209+cid at +0, 268+cid at +0x130000, 327+cid +0x13C000, 386+cid +0x13D000, 445+cid +0x13E000, 504+cid +0x140000, 563+cid +0x141000, 681+cid +0x142000, 622+cid +0x143000, 740+cid +0x144000, 3+cid +0x148000 (case 6), plus an engine-written 12 KB region at +0x145000 (fighter+0x1F0; writer INFERRED FUN_140612180). Loader FUN_14060d100 = loc_8c031fa0. 66/66 byte-exact on the live image. Closes the loader-UNKNOWN of determinism_pl_image_rule.';
UPSERT finding:dcram_inplace_rewrites SET status='confirmed', confidence='high', date='2026-09-03', note='Per-frame in-place rewrites of arc data on Steam: stage POL vertices (list-5 callbacks), effects POL UVs (FUN_140797690), HUD POL TCW bytes (FUN_140653a70), plus the 0x0CE60000 tile table. All absolute functions of blk node state + static tables + pristine sibling data, written before the draw in the same frame; nothing incremental lives in the DC image.';
UPSERT finding:stage_prop_animation_state SET status='confirmed', confidence='high', date='2026-09-03', contribution_candidate=true, note='Stage props animate from pool-node fields (+0x30/+0x32/+0x34/+0xF4..FC, parent +0x60), exe tables, the sin table and pristine POL data; no frame counter/RNG. Renderer can pose from keys by porting FUN_14064a4a0 / FUN_140750eb0 / LAB_14064e5e0. Only stages 3/0xC and 7/0x10 read; 15 tables remain to classify.';
UPSERT finding:determinism_pl_image_rule SET note_loader='2026-09-03: loader found (finding:pl_slot_recipe).';
RELATE finding:pl_slot_recipe->cites->source:doc_receipt_runner_dcram; RELATE finding:pl_slot_recipe->about->steam_routine:FUN_14060d100; RELATE finding:pl_slot_recipe->about->routine:loc_8c031fa0;
RELATE finding:dcram_inplace_rewrites->cites->source:dcram_diff_20260903_000941; RELATE finding:stage_prop_animation_state->about->steam_routine:FUN_14064a4a0; RELATE finding:stage_prop_animation_state->about->steam_routine:FUN_140750eb0;
-- corrections to 101_steam_function_map rows (apply as UPDATE of the recompiles edges, do not re-run 07_dedup_edges)
-- FUN_14060dd40 -> loc_8c042d0c : demote (falsified) ; FUN_140620200 -> loc_8c045ce0 : reclass as 'called_by' ; FUN_1408435d0 -> loc_8c03552a : demote (TEXTURE-BANKS s1)
```
