# FRAME-READSET — the per-frame READ / WRITE SET of Steam MvC2, from whole-frame p-code emulation (2026-09-03)

RE METHOD step 4 (`docs/RE-METHOD.md`): pairs were matched in steps 1-3; this is the deterministic, numeric GATE
and the read-set source. TTD is dead for this title (`docs/TTD-FRAME-TRACE.md` s0), so the read set comes from
the Ghidra p-code harness (`docs/EMU-GATE.md`) extended to run a WHOLE FRAME on the live images that
`d3dcap/ttd/dump_live.py` took mid-match (`d3dcap/ttd/runs/20260903-000941/pre`: exe_image 68 MB at 0x140000000,
dcram 32 MB at 0xFBC1000 = DC 0x0C000000, ctx 4 MB at 0xF7C1000, blk 0x33B18 at 0x146C1000, blk2; nothing
relocated). Every ram access of the run is logged (kind, pc, address, size, ordered) and attributed to the
function by body containment (`re_map/steam_funcs.jsonl`) with its SH4 pair from `docs/steam_sh4_map.csv`.

Harness: `d3dcap/replay/emu_gate.py frame` + `d3dcap/replay/emu_frame.py` + the `trace/functable/image/extstub/
callother/heap/extalloc/extret` commands of `re_map/ghidra_emu/EmuGate.java`. Seed: `maplecast-flycast/tools/re_kb/
36_frame_readset.surql`. Work files (traces, dumps) in `%TEMP%\rrcap_emu\` — ROM-derived bytes never enter the repo.
Tags: **CONFIRMED** = read on both sides / reproduced by the gate; **INFERRED** = decompile- or gate-consistent only;
**UNKNOWN** = not located.

```
cd C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\replay
python emu_gate.py frame --run C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\runs\20260903-000941 --target all   --repeat 2
python emu_gate.py frame --run ...\runs\20260903-000941 --target chain --repeat 2      # tick -> dispatcher (gate ii)
python emu_gate.py frame --run ...\runs\20260903-000941 --target render --layerz-reset # idempotence on the raw dump
```

## 0. Answer (the gates)

| gate | result |
|---|---|
| (i) determinism | tick: 2 runs, trace stream / blk / game_state / ctx / GGPO / beyond-dcram dumps **all SHA-256 identical** (trace `a5942b68…`, blk `03db6732…`). render: 2 runs identical (trace `f75772ca…`). chain: 2 runs identical (`c222205c…`). |
| (ii) walker outputs | **chain** (tick → reset LayerZ/G+0x24 → `FUN_140620960` again on the state the tick built): **50/50 node fields identical on the 5 drawn nodes, 0 of 211,736 blk bytes differ, quad total 125 = 125, LayerZ 16/16**. On the RAW dump (no tick): 45/50, the 5 misses are `+0x12C` depth = exactly one more frame of LayerZ accumulation (the dump is post-walk, the dispatcher does not reset LayerZ); with LayerZ reset 47/50, the 3 misses are depth again (+0.044/+0.040/−0.002 = quad-count deltas) because the snapshot’s per-frame tile table at DC 0x0CE60000 is torn against `blk` (section 4.3). This state has 5 drawn nodes (2 fighters, 1 cat-3, 2 cat-4, layers 5/6), not 47 — the 47/47 of EMU-GATE was frame 4445 of a different capture. |
| (iii) tick | `blk+0x3CC8` **2239 → 2240 (delta 1)**. The tick changes **120 blk bytes**; the pre→post diff (post is **237 frames** later: clock 2476, not 20 — `clock_value_after` is the end of the pre dump) has 7,785 bytes; **116/120 lie inside it**, the 4 outside are `fighter[slot 0]+0x186` (anim_timer), `fighter[slot 0]+0x2FD`, `fighter[slot 0]+0x398`, `node+0x186` (anim_timer) — one-byte countdowns that had returned to the same value 237 frames later. |
| (iv) capgate consecutive frames | **NOT RUNNABLE — data does not match.** The capgate runs with consecutive `"at":"walk"` frames (4329..4508, 7279..7458) have roster `[0x134,0x2A,0x12A,0x34,0x12C,0x2C]` (stage byte 11); the TTD images have `[0x12A,0x34,0x12C,0x117,0x134,0x135]` (000941/000956/001249/001259) or `[0x12C,0x117,0x134,0x10F,0x12A,0x34]` (001536). First divergence: slot 0 `+0x6C0` = 0x134 vs 0x12A; the per-slot PL images (0x0C420000 + k·0x150000, order 0,2,4,1,3,5) and every host pointer in the fighter structs (`+0x1C0` = 0x12531000… vs 0x10111000…) differ, so no capgate frame can be fed to this dcram. |

Instruction counts: tick `FUN_140118950` **459,681** (7.4–8.3 s), dispatcher `FUN_140620960` 149,903 on the raw dump /
136,861 after the tick; 24 external calls (6 imports), 0 unimplemented CALLOTHERs, heap arena used 0xF50 B.

**Nothing failed to run.** The first attempt looped forever in the UCRT (section 2.2); with a bump allocator and
`FlsSetValue → 1` the frame runs to `RET`. No function of the game or of the runtime/protection section was hit
by an unimplemented instruction.

## 1. What a frame IS on Steam (CONFIRMED by the trace + decompiles)

* Offline (`*(0x142E10B98)` = 0, seat map `game_state+0x258..0x264` = 0,0,0,0): `FUN_14003a520` → `FUN_140118dd0`
  (GGPO wrapper, no session) and `FUN_140039de0` stores the pad words at **`game_state+0x218/+0x21C`
  (0x140AC6F58/5C)** then calls `*(game_state+0x10)` = **`FUN_140607d60`** at `0x14003a3ac`. `FUN_140118950` is the
  GGPO-path wrapper of the same entry: `DAT_142d10b90++`, `game_state+0x798 = 1`, `prev = cur` shuffle of the four
  pad words, `pad[seat(k)] = inputs[k] & 0xffffff`, then `(*(game_state+0x10))()`. Its third argument (disconnect
  flags) is not used by its body. ⚠ The task called the pad words "G+0x218, G = blk+0x3CB8": the decompile puts
  them in the **game_state struct at 0x140ac6d40** (the `G` of STEAM-GGPO-DETERMINISM.md), not in `blk`.
* `FUN_140607d60` runs the WHOLE frame: its top-level calls are `FUN_1408441d0`, `FUN_140608a00` (sim: input
  translate, fighters, objects, camera, HUD, registration) and `FUN_14060b960` (the render table loop:
  `FUN_140620960` dispatcher, `FUN_1406185e0` ×2, `FUN_140845130`). So "tick" below = sim + render dispatch + sprite
  walker + NaomiLib submit, and "render" = the dispatcher alone.
* The per-frame LayerZ resetter (EMU-GATE s5 open item) is **`FUN_14060a1f0`, called once per frame by
  `FUN_140609d60`** (inside `FUN_140608a00`); `FUN_140613390` (`loc_8c0338ec`) executes in it (its LayerZ writes are
  in the trace; no CALL record = reached by a jump) — CONFIRMED by the trace, closes `finding:emu_gate_layerz_reset_unknown`.

## 2. Memory model of the run

| memory | source | note |
|---|---|---|
| exe image 0x140000000+0x40E8000 | `pre/exe_image.bin` (live, ~20 frames after `blk.bin`: the dump ran while the game ran, clock 2239→2259) | `DAT_142eefbd8` forced 0 (SSE2 CRT path) |
| dcram, ctx, blk, blk2 | the live files at meta.json addresses | torn by ≤20 frames against each other (2.2, 4.3) |
| stack 0x31000000+0x400000, inputs 0x30000000, heap arena 0x32000000+0x1000000 | synthesised; `frame_job` asserts no overlap with any image (the first smoke run had the stack inside dcram) | |
| imports | any PC outside the image → logged, `RAX = 0`, `RET`; **`RtlAllocateHeap`/`RtlReAllocateHeap` = bump allocator (size in R8/R9), `HeapFree`/`FlsSetValue` → 1**, slots read from the live IAT (`0x1408db240/140/238/218`) | 6 imports hit: GetLastError, FlsGetValue, RtlAllocateHeap, FlsSetValue, HeapFree, SetLastError (4× each) |
| CALLOTHER | log + skip | 0 hit |
| host memory after dcram (0x11BC1000..) | not in any image; zero-filled | written 64,755 times, read 0 (section 4.4) |
| heap object `*(DAT_142ebc010)` = 0x28B5EF9C.. | not in any image | 7 accesses by `FUN_14006b5d0` (UNKNOWN role, timing/perf object INFERRED); does not reach blk |

### 2.2 The UCRT trap (why the first tick never returned)
The sim calls the game’s sprintf wrapper `FUN_14003a4c0` (`loc_8c129740`, medium) from `FUN_140627c50` ←
`FUN_140628320` ← `caseD_7`. `__stdio_common_vsprintf` → `__acrt_getptd_noexit` → `FlsGetValue` (0) →
`_calloc_base` → `RtlAllocateHeap` (0) → `__doserrno` → `__acrt_getptd_noexit` → … : 60 M instructions, 1.64 M
external calls, never returns. The allocator + `FlsSetValue → 1` fix it; the ptd is then built by the CRT’s own
code (0x3C8 B, allocated twice = two `__doserrno` callers).

## 3. The READ SET

Totals (distinct bytes / coalesced ranges): 

| region | tick reads | tick writes | render reads | render writes |
|---|---|---|---|---|
| blk | 10,004 B / 887 | 6,692 B / 368 | 7,265 B / 423 | 4,288 B / 85 |
| dcram (DC RAM image) | 22,545 B / 227 | 11,488 B / 1 (`0x0CE60000..0x0CE62CDF`) | 1,384 B / 196 | 0 |
| exe globals | 2,445 B / 288 (400 read-only addresses + 478 read-and-written) | 716 B / 25 | 1,144 B / 137 | 8 B (`DAT_142ef0ab8`) |
| ctx (NaomiLib host context) | 1,871 B / 149 | 43,217 B / 354 | 933 B / 275 | 43,095 B / 263 |
| beyond dcram | 0 | 64,755 accesses (64,000 B memset + 750 dwords) | 0 | 0 |
| stack | 1,465 B | 1,510 B | 908 B | 900 B |

### 3.1 blk — by field group (offsets are blk-relative; DC names from re_kb `field`/`global`, block map `blkmap.py`)

**Tick reads (887 ranges):**
* `0x3C66..0x3CB8` input array `input[i]+0x00..0x13` (DC 0x8C2681DC): all 40 B of seats 0/1 read, 24 B written (cur/prev/pressed/released).
* `G` = `blk+0x3CB8` (DC 0x8C268240): reads at `G+0x00..0x04, 0x10..0x18, 0x1A, 0x1C..0x27, 0x2A, 0x2E, 0x4C, 0x52..0x54, 0x57..0x58, 0x80..0x81, 0x84..0x85, 0x88, 0x8B..0x8C, 0x90..0x93, 0x98 (blackout_gate), 0xA6, 0xAA, 0xAE, 0xB2..0xB3`; writes `G+0x10..0x13, 0x1A, 0x1C..0x27, 0x80, 0x8A, 0x90..0x93, 0x98`. `G+0x10` is the frame clock (`blk+0x3CC8`).
* fighters `0x3DB8 + slot·0x738`, 100 field runs read (union over the 6 slots; DC offset via `steam_field_to_dc`): `+0x0 active, +0x1..4 character_id, +0x5, +0x10..0x17 update-fn/keyframe, +0x38 layer, +0x4D sort, +0x50..0x5B world x/y, +0x64..0x73, +0x80, +0x120, +0x124..0x137 screen/depth/scale, +0x148..0x14F angle, +0x154 facing, +0x170..0x175 drawn/flash, +0x180, +0x182, +0x186 anim_timer, +0x188..0x18B sid, +0x18C..0x18E, +0x191 cell override, +0x195, +0x1A0 GFX1, +0x1A8 palette, +0x1AC, +0x1B0..0x1B7, +0x1D0..0x1D7, +0x228..0x22C, +0x230 slot, +0x23A, +0x260..0x267, +0x280, +0x282, +0x28C, +0x290..0x293, +0x296..0x297, +0x29B..0x2A5 (dhc_move_id …), +0x2A9, +0x2AD, +0x2B0..0x2B3, +0x2B8..0x2BB, +0x2C0..0x2C7, +0x2F5, +0x2F7, +0x2FD, +0x2FF, +0x310, +0x312..0x313, +0x31C..0x31D, +0x342, +0x349..0x34B, +0x364..0x365, +0x367..0x369, +0x374..0x37C, +0x398..0x39B, +0x3AC..0x3AF, +0x3B4..0x3B7, +0x46C..0x46D, +0x470, +0x472..0x473, +0x488..0x48D, +0x490..0x493, +0x496..0x497, +0x49C, +0x4A1, +0x4A4, +0x4A9, +0x4AC, +0x4B4, +0x4BC, +0x4C4, +0x4CC, +0x4D4, +0x4DC, +0x4E4, +0x4EC, +0x51C, +0x52C..0x535, +0x539..0x53A, +0x548..0x549, +0x558..0x567, +0x569, +0x56C..0x56F, +0x574..0x577, +0x578..0x57B health/health2, +0x580..0x587, +0x648..0x649, +0x654, +0x660..0x67B, +0x6B1`. 55 field runs written (`+0x10..0x17, +0x38, +0x50..0x57, +0x80, +0x120, +0x124..0x137, +0x148, +0x150, +0x154, +0x174..0x175, +0x178..0x17B, +0x186, +0x228..0x22B, +0x28F, +0x2AD, +0x2B0, +0x2C0..0x2C8, +0x2E8, +0x2FA, +0x2FD, +0x31C, +0x334..0x335, +0x338..0x339, +0x33D, +0x33F, +0x360..0x363, +0x366, +0x36C..0x36F, +0x378..0x37B, +0x398..0x39B, +0x488..0x497, +0x4A1, +0x4A9, +0x4AE, +0x4B6, +0x4BE, +0x4C6, +0x4CE, +0x4D6, +0x4DE, +0x4E6, +0x4EE, +0x51E, +0x52C..0x52D, +0x53A, +0x600..0x60B, +0x668..0x684, +0x685..0x68F pal, +0x6B1`).
* pool nodes `0x6DD8 + n·0x280` (39 field runs read, 32 written): the node prefix `+0x1..0x5, +0x10..0x1D, +0x1E..0x21, +0x22..0x24, +0x25..0x33, +0x34..0x3B, +0x40..0x47, +0x4D, +0x50..0x5B, +0x5C..0x77, +0x84..0x87 X_Gravity, +0x88..0xF3 (world matrix +0xA8 etc.), +0x110..0x117, +0x120..0x137, +0x148..0x14F, +0x154, +0x170..0x175, +0x183, +0x186..0x187, +0x188..0x18B, +0x191, +0x198..0x19F, +0x1A8..0x1B7`.
* stage/camera struct `0x6908..0x6DD8`: reads `0x6908..0x690A, 0x690D, 0x690F, 0x6914..0x6923 eye, 0x6928..0x692B, 0x695C..0x6967 look-at, 0x6974 fov, 0x6980, 0x6988..0x698F y-off/roll, 0x699C..0x69A7, 0x69B0..0x69CB, 0x6A00, 0x6A08..0x6A2F, 0x6A88, 0x6A8C..0x6A8F, 0x6A91..0x6A97, 0x6CA8..0x6CBA deck colour, 0x6CD0..0x6CD3, 0x6CE4 render mode, 0x6CEC, 0x6D04 stage id, 0x6D1C..0x6D23`; writes `0x6909..0x690A, 0x6914..0x692B eye+prev, 0x695C..0x6973, 0x6980, 0x6990..0x699F, 0x69B0..0x69B3, 0x69B8..0x69C7, 0x6A08..0x6A2F, 0x6A98..0x6C9B (516 B), 0x6CA8..0x6CBB, 0x6CE4, 0x6D08..0x6D47 LayerZ`.
* pool bookkeeping `0x2EDF0..0x2EE4F` (list heads), `0x2EEE8`, `0x2F1D8`, `0x2F4C8`; draw lists: only the populated handles (layer 5 slots 0-3, layer 6 slot 0) read and written; counts `0x324D0..` all 16 read (+ 0x324E0.. beyond 16: the count array is longer than 16 in this build — read at layers 16..22), 21 written.
* battle state `0x32500..0x33B18` (DC 0x8C289608..): writes `0x32500..0x3252F` (in_match, match_sub_state, round_counter …), `0x32531..0x32535`, `0x32538..0x32539`, `0x3253B`, `0x32541..0x32543`, `0x3254C`, `0x32556..0x32557`, `0x32561`, `0x329D0..0x329D7`, `0x32BD8..0x32BDB`, `0x32BE8..0x32BF3` (texture-slot bases), `0x339F8..0x339FF`, `0x33AAC..0x33AAF`, `0x33ADC..0x33AEB`, `0x33AF0..0x33B0F`.
* **`blk+0x1000..0x3C66` is OUTSIDE the block map** (no DC address): `FUN_140613390` reads one u32 at `+0x48` of 0x38-byte records `0x1000 + n·0x38` (n = 1..~126, 128 reads) and `FUN_14060bab0` reads `0x3C40`. INFERRED: the per-frame render-list record array; DC counterpart UNKNOWN.
* matrix push storage `blk+0x0..0x80` (slots 0/1) read and written by the NaomiLib push/pop.

**Render (dispatcher alone) reads:** fighters `+0x3, +0x38, +0x50..0x5B, +0x64..0x73, +0x120..0x137, +0x148..0x14F, +0x154, +0x170, +0x174..0x175, +0x188..0x18B, +0x191, +0x1A8..0x1B7`; nodes additionally `+0x10..0x17, +0x40..0x47, +0x5C..0x77, +0x90..0xF3, +0x110..0x117`; `G+0x14..0x17, +0x24..0x27 (quad total, written), +0x2E, +0x98`; camera `0x6914..0x6923, 0x6928..0x692B, 0x695C..0x6967, 0x6974, 0x6988..0x698F, 0x6CA8..0x6CB3, 0x6CE4, 0x6D04, 0x6D1C..0x6D23 (written)`; pool lists `0x2EE10..0x2EE4F`; draw counts/handles; `0x32BDC..0x32BE3, 0x32BEC..0x32BEF` (render flag bases); it writes only the 10 walker fields per drawn node (+`+0xA8..0xE7` world matrix on cat-5+ nodes), LayerZ, `G+0x24`, matrix slots — exactly TAPE-V3-SPEC s10.1.

### 3.2 dcram — DC data actually touched (per frame, this roster/stage)
| DC range | region (`emu_frame.DC_REGIONS`) | tick | render | readers |
|---|---|---|---|---|
| 0x0C42006C..0x0C55D7E8 | PL slot 0 (P1 point: GFX1 0x0C420000, GFX2 0x0C508660, pal 0x0C51D8A0, cell table 0x0C550000, +0x1C8..0x208 sub-tables) | 76 ranges, 4,101 B | 64 / 630 B | `FUN_1406129f0` (`loc_8c0344d4` submit), `FUN_140612430`, `FUN_140623d40`, `FUN_140622b60` (`loc_8c04f6e8`), `FUN_1406219a0` |
| 0x0C810200..0x0C94D7E8 | PL slot 1 (P2 point) | 21 / 5,884 B | 3 / 162 B | same |
| 0x0CE60000..0x0CE62EC0 | Texture_Decompress_Buffer: **written by the tick itself** (`FUN_140614210` ← `FUN_140612430`, 11,488 B = the decoded parts of this frame’s cells) then read (11,968 B) by the copy routine `FUN_140800620` | 1 / 11,968 B | 0 | |
| 0x0D000FE0..0x0D0010FC | effects bank 0xC50 (AFS 799/800) | 4 / 28 B | 4 / 28 B | `FUN_140848ee0`, `FUN_1408436a0` (`loc_8c127c80`) |
| 0x0D0903C8..0x0D097CC4 | HUD bank 0xC90 (AFS 835/836) | 120 / 544 B | 120 / 544 B | same |
| 0x0D82D228..0x0D83A6A4 | stage POL (AFS 801+2·id) | 5 / 20 B | 5 / 20 B | same |

No read touched slots 2/3/4/5 this frame (assists off-screen), nor 0x0C010000..0x0C420000 (the DC program image
is not consulted: the recompile carries its tables in the exe).

### 3.3 exe globals
* Read-only (400 addresses, 1,911 B): 136 in `.rdata/.idata` (float constants, `DAT_140a6d888` LayerZ init table,
  sin/cos tables at `0x142ef0ac0/0x142f30ac0`, `DAT_140a4f780` input bit table, `PTR_DAT_140a75020/130` tile
  layout tables), 233 other data-section constants, 22 in `game_state` (`+0x10, +0x48, +0x1F0, +0x208, +0x210, +0x214,
  +0x218..0x224, +0x258..0x264, +0x4F4, +0x520, +0x5DC..0x5EC, +0x80C, +0x828, +0x82C, +0x838, +0x850, +0x878..0x88C,
  +0x8C8, +0x964, +0x968`).
* Read-and-written in the same frame (478 addresses): `game_state+0x210/+0x214` (texture staging cursor,
  `FUN_1408456a0`), `+0x218..0x224` pad words (`FUN_140048630` = the translation into `blk+0x3C66`, `FUN_140118950`),
  `+0x4F4, +0x520, +0x5DC..0x5EC` (`FUN_140607e90`, the battle-globals save-slot sync), `DAT_142d10b90` (counter),
  `DAT_142ec4370/74/78/7C` + `0x142ec4380..0x142ec438B` + `0x142ec43C0..CB` (render table count/flags,
  `FUN_14060b960/b8c0/ba00/ba20`, `FUN_1406185e0`), `PTR_FUN_142ec6780` (render table), `0x142edf318/31C/538/543/546`
  (2-byte counters, `FUN_1406163e0` …; role UNKNOWN), `0x142eed950..+0x1F4` (500 B scratch written by
  `FUN_140612430` and read by the submit `FUN_1406129f0` in the same frame), `DAT_142ef0ab8` (current matrix ptr).
* Written only: `game_state+0x508, +0x51C, +0x548, +0x578, +0x588, +0x598, +0x798, +0x974, +0x984, +0x994`, `0x140acb398`.

### 3.4 ctx (NaomiLib host context, `*0x142ef0ab0`)
Reads: `ctx+0x8` (dcram base), `ctx+0x1e0030..0x1e31CA` (texture-slot table: bank base `+0x1e0098`, 0x18-B slot
records `+0x1e00a0..`), `ctx+0x1f80a4..0x1f8564` (matrix mode/slots/composite/near). Writes: `ctx+0x30..0x7EB`
and `+0x30030..0x3130B` (`FUN_1408436a0` polygon/TA records), **`+0x100030..0x108FC0` (36,752 B contiguous,
`FUN_140800620/640` = memcpy: the decoded texture pages)**, slot table `+0x1e0030..`, matrix slots `+0x1f80a4..0x1f857c`.

### 3.5 Beyond the DC-RAM image (0x11BC1000.. = dcram + 32 MB)
`FUN_140800620` (memset, 64,000 B at `+0x18`) and `FUN_1408456a0` (750 dwords at `+0x0..0x103B8`) ← `FUN_140612430`
(per-fighter sprite-page upload, 125 calls). Decompile of `FUN_1408456a0`: it writes `*(game_state+0x208) +
*(game_state+0x214)` after checking the slot record `ctx+0x1e00a0 + TCW·0x18` — **`game_state+0x208` = the host
texture-staging buffer** that happens to sit right after the DC-RAM image (CONFIRMED site, INFERRED purpose). It is
never read back by the frame: pure render output, regenerated each frame.

### 3.6 By function (SH4 pair from the graph; distinct addresses)
Full table: `%TEMP%\rrcap_emu\…` / `scratchpad/frame_functions.csv` (214 functions touched memory in the tick, 55 in the render). The ones that own the read set:

| Steam | SH4 (conf) | role | blk r/w | dcram r | ctx/exe |
|---|---|---|---|---|---|
| `FUN_140614210` | unmatched | LZSS part decoder into 0x0CE60000 (58 calls) | 0/0 | 17,039 | dcram w 11,488 |
| `FUN_140800620/640` | unmatched | CRT memcpy/memset (texture pages → ctx+0x100030, staging) | 0 | 11,968 | ctx w 26,752 |
| `FUN_140620cd0` | `loc_8c030550` (medium) | world-space walker (5 nodes) | 461/0 | | |
| `FUN_140620740` | `loc_8c0301f6` (confirmed) | category dispatch | 231/0 | | |
| `FUN_1406129f0` | `loc_8c0344d4` (confirmed) | sprite submit (5 calls) | 63/0 | 343 | exe 437 |
| `FUN_140612430` | unmatched | per-fighter sprite pages (calls 140614210, 1408456a0) | 28/7 | 297 | exe w 500 |
| `FUN_140613390` | `loc_8c0338ec` (high) | per-frame render-list init (LayerZ, blk+0x1000.. records) | 130/22 | | |
| `FUN_140620f10` | `loc_8c030af8` (confirmed) | sprite walker | 90/53 | | |
| `FUN_140610730` | `loc_8c030e3a` (high) | | 8/129 | | |
| `FUN_14061f030` | `loc_8c044ccc` (low) | blackout / list gates | 56/25 | | |
| `FUN_14061e520/560` | unmatched | draw-list registration | 178/5 | | |
| `FUN_140846a00/c30, 140847b90/c40` | unmatched (NaomiLib) | matrix get/set/mul | 172..248 | | |
| `FUN_1408436a0` | `loc_8c127c80` (high) | TA record emit (213 calls) | 0 | 73 | ctx w 1,708 |
| `FUN_140848ee0` | unmatched | polygon-list consumer | 0 | 120 | |
| `FUN_140622b60` | `loc_8c04f6e8` (high) | | 29/0 | 8 | |
| `FUN_1406516e0/527e0/51940` | unmatched | (6 calls each, 48/24 …) | | | |
| `FUN_140607e90` | unmatched | battle-globals save-slot sync | 23/0 | | exe w 19 |
| `FUN_14003a4c0` | `loc_8c129740` (medium) | sprintf wrapper (2 calls; UCRT) | | | heap |

## 4. Findings

CONFIRMED (gate / trace / decompile read):
1. The whole frame (sim + render dispatch + walker + submit) is emulable and **deterministic** on the live images;
   the tick advances the clock by exactly one and its blk write set is inside the 237-frame pre→post diff except
   4 one-byte countdowns.
2. `FUN_140607d60` = `*(game_state+0x10)` is the frame entry; `FUN_140118950` wraps it for GGPO; the pad words are
   `game_state+0x218..0x224` (exe global), the seat map `+0x258..0x264`.
3. `FUN_14060a1f0` runs every frame (from `FUN_140609d60`) and is where LayerZ is reset (`FUN_140613390`).
4. The dispatcher re-run on the tick’s own output reproduces every walker field bit-exact (50/50, 0 bytes differ):
   the render pass is a pure function of `blk` + dcram (cell/tile tables) + ctx (slot table) + exe constants.
5. The per-frame tile/part table at DC 0x0CE60000 (11,488 B) is built by the tick (`FUN_140612430` → `FUN_140614210`)
   from PL data + node state; the snapshot’s copy was torn (2,340 B differ from what the tick generates for `blk`’s
   frame), which is the whole explanation of the raw-dump depth misses.
6. `game_state+0x208` is a host texture-staging buffer after the DC-RAM image; the frame writes it and never reads it.

INFERRED: `blk+0x1000..0x3C66` = render-list record array (0x38-B records); `0x28B5EF9C` heap object = timing; the
five 2-byte counters at `0x142edf318..546`.

UNKNOWN: DC counterparts of `blk+0x1000..0x3C66`; the role of `0x142edf318/31C/538/543/546`; the character
loader that places PL data at `0x0C420000 + k·0x150000` (needed for section 5).

## 5. The MINIMUM TAPE (Tris: "only record the blk GGPO snapshot and the diff/inputs per frame; everything else is deterministic")

What the emulation proves about that sentence, per input class of the frame:

| class | per frame | reconstructible offline? |
|---|---|---|
| `blk` (211,736 B) | read 10,004 B, written 6,692 B; the tick maps `blk(N)` + inputs → `blk(N+1)` deterministically (gate i/iii) | **YES from one snapshot + inputs** (or from per-frame diffs; the tick output IS the diff: 120 B changed on this idle-ish frame) |
| inputs | `game_state+0x218/+0x21C` (2 × u32, 24-bit) — already the tape’s `seat_in[2]` | **YES**, tape column exists (0.3.24+) |
| dcram | 22.5 KB read from PL slots (this frame: 0/1), effects bank, HUD bank, stage POL; the 0x0CE60000 table is rebuilt by the frame itself | **from the arc, not the tape**: effects/HUD/stage banks are AFS 799/800, 835/836, 801/802+2·id via `FUN_14060dcf0` (seed 31, CONFIRMED); the per-character PL images at `0x0C420000 + k·0x150000` need the character loader (UNKNOWN entry table) — or a one-time dump of the six slot regions per roster |
| ctx | slot table (`+0x1e0030..0x1e31CA`, 1.3 KB) + matrix state; everything else is written before read | from the bank loaders (seed 31) — one-time per roster/stage, not per frame |
| exe globals | 400 constants (image) + 478 mutable, of which: pad words = inputs; render-table bookkeeping and `0x142eed950` scratch are rebuilt every frame; `game_state+0x4F4..0x5EC` is derived from blk by `FUN_140607e90`; `0x142edf318..546` (8 B) UNKNOWN | **YES except 8 B UNKNOWN** (carry them in the snapshot: they are exe-resident, so a game_state page + the 0x142edf300 page cover it) |
| OS / heap | 6 imports, all for sprintf’s ptd | synthesised |
| pixels | ctx TA records + texture pages (79 KB written per frame) are the render output of the same run | YES — that is the render input the offline renderer needs |

**Answer:** with (a) ONE `blk` snapshot (plus the two exe pages `game_state` 0x140ac6d40+0x1000 and 0x142edf300+0x300,
and the ctx slot table) taken at any frame — the char-select anchor of STEAM-GGPO-DETERMINISM s2 also works, since the
tick is the same function — and (b) the two seat words per frame, the emulated `FUN_140118950` regenerates every
render input the walker/submit consume (node fields, LayerZ, tile table, TA records) byte-exact and deterministically:
the tape needs **nothing per frame beyond the 8 input bytes** (2.1 B/frame compressed, s4 of that doc). Per-frame blk
diffs are then a redundancy/check, not a requirement. What must come from OUTSIDE the tape: the exe image (code +
constants), the arc-derived DC-RAM data (stage/effects/HUD banks by AFS entry, CONFIRMED loaders; the six PL images
per roster — loader UNKNOWN, dump-once workaround), and the bank-loader-built ctx slot table. Gaps still open before a
pixel-perfect offline frame: the PL loader table; the 8 UNKNOWN exe bytes; and the emulation has been gated on ONE
frame of ONE roster (idle-ish: 5 drawn nodes) — hit/effect-heavy frames and a second roster are the next gates.

Versus TAPE-V3-SPEC s10 / the 0.3.39 `GS_SCHEMA`: every state column there (`sx/sy/zx/zy/angle/hotx/hoty/depth/
facing/layer/sort/pal/flash/glow`, camera, deck, blackout, `anodes`) is a WRITE of this frame, i.e. derivable; the
only tape columns that are true INPUTS are `seat_in[2]` (and `frame`). 

## 6. Address index
`FUN_140118950` GGPO tick wrapper · `FUN_140607d60` frame entry (`*(gs+0x10)`, offline caller `FUN_140039de0` @0x14003a3ac) ·
`FUN_140118dd0` GGPO wrapper (offline, `FUN_14003a520`) · `FUN_140608a00` sim · `FUN_14060b960` render table loop ·
`FUN_140620960` dispatcher · `FUN_140620f10` walker · `FUN_1406129f0` submit · `FUN_140609d60` → `FUN_14060a1f0` per-frame
init (LayerZ via `FUN_140613390`) · `FUN_140612430` → `FUN_140614210` (LZSS to 0x0CE60000) / `FUN_1408456a0` (staging
`*(gs+0x208)`) · `FUN_140607e90` save-slot sync · `FUN_14003a4c0` sprintf · game_state 0x140ac6d40: `+0x10, +0x208,
+0x214, +0x218..0x224, +0x258..0x264, +0x798` · `DAT_142d10b90` · `DAT_142ec4370` / `PTR_FUN_142ec6780` · `0x142eed950` ·
`0x142edf318/31C/538/543/546` · UCRT slots `0x1408db240` (RtlAllocateHeap) `0x1408db140` `0x1408db238` `0x1408db218`.
