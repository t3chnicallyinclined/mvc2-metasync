# DETERMINISM-CONTRACT — what a host must preserve so that `FUN_140607d60` produces the same bytes everywhere (2026-09-03)

RE METHOD step 4 (`docs/RE-METHOD.md`): the frame function and its read set were matched and traced in
`FRAME-READSET.md` (seed 106); this page is the deterministic, numeric gate on **hidden state, external calls, floating
point, uninitialised reads and threading**, measured on the live images of `d3dcap/ttd/runs/20260903-000941/pre`
(offline match, clock 2239, roster cids 42/52/44/23/52/53) with the p-code harness (`d3dcap/replay/emu_gate.py`,
`emu_frame.py`, `re_map/ghidra_emu/EmuGate.java` — new commands `fma`, `probe`, `nudge`) and two new tools:
`d3dcap/replay/determinism_gate.py` (perturb / multitick / native / dispatch) and `d3dcap/replay/receipt_gate.py`.
Seed: `maplecast-flycast/tools/re_kb/111_determinism.surql`. Work files in `%TEMP%\rrcap_emu\` (ROM-derived, never in git).

Tris's requirement, verbatim: *"we'd have to make sure it's deterministic and find out how it is so and make sure we keep it."*
Tags: **CONFIRMED** = measured on both sides / reproduced by a gate; **INFERRED** = decompile- or gate-consistent only;
**UNKNOWN** = not located. Every perturbation below changes ONE variable and re-runs the whole tick (`FUN_140118950`,
459,681 instructions); "sim-relevant" means the `blk` output hash changed.

## 0. Answer

| question | verdict |
|---|---|
| What outside `blk[0..0x33B18)` does the frame READ before it WRITES it (carried state)? | **Exactly:** the 4 pad words `game_state+0x218..0x227` (= the inputs), `game_state+0x520` (render gate, no effect), the GGPO counter `DAT_142d10b90` (wrapper only, no effect), 1 byte `0x142edf543` (HUD re-upload state machine, no effect on blk), 4 B of a heap ring `*(DAT_142ebc010)+0x34AAC` (debug event ring, no effect), the NaomiLib matrix state in ctx (`+0x1f80a4/+0x1f80ac..+0x1f81bc/+0x1f82b0/+0x1f855c`: the frame is a **fixed point** on it), 123 texture-slot flags `ctx+0x1e2624+n*0x18` (render only), 4,320 B of the previous frame's tile table at DC `0x0CE60040..` (render only), and the six PL slot images (static per character). **The sim state that changes per frame lives entirely in `blk`** (section 1). |
| Where is the RNG? | **Inside `blk`: 2 bytes at `blk+0x32BD4/0x32BD5`** (DC `0x8C289CDC`), generator `FUN_14060fa40` (16-bit `*3` byte mixer, 15-bit result), seeder `FUN_14060f9e0` (`{0x01,0xC3}`), 8-bit draw `FUN_14060f990`, float draw `FUN_14060fae0`. It is **not** the DC LCG (`0x8C16BC2C`, `s*0x41C64E6D+0x3039`): the recompile carries that LCG only as a dead, never-referenced library object at `0x140a5c7d8` (state `0x140a5c800` = 1, zero references in the whole image). Rolled back by GGPO with the block, so a snapshot carries it. CONFIRMED (section 1.4). |
| External calls during the sim? | 6 imports, all inside the UCRT `sprintf` path (`GetLastError, FlsGetValue, RtlAllocateHeap, FlsSetValue, HeapFree, SetLastError`, 4× each); **none reads time, ticks, performance counters, rand(), thread ids or Steam**. 0 `RDTSC/CPUID/RDRAND` executed (the only `RDTSC` in the image is `FUN_1405c0010`, not on the path). CONFIRMED (section 2). |
| FMA vs non-FMA? | **No game code uses FMA or x87** (all 16 FMA-bearing functions are the UCRT at `0x140803be0..0x14082b700`; all 13 x87 users are `≥0x1408d6c50`). The four FMA-capable CRT routines the frame calls (`tanf/sinf/cosf/powf`) return **bit-identical results on the SSE2 and the FMA3 path**: 0 differing of 155,001 + 65,536 + 65,536 + 65,536 + 5,064 inputs, measured natively on the game's own code with the dispatch flag `DAT_142eefbd8` forced 0 and 1, FMA3 execution proven (UD2 test). MXCSR is never changed by the frame (`LDMXCSR` only inside `powf`'s own save/restore). CONFIRMED (section 3). |
| Uninitialised reads? | Stack: **12 bytes** (`FUN_1406101b0` 4 B, `FUN_140607e90` 8 B) — filling the stack with `0xCC` instead of 0 changes **nothing** (blk / game_state / ctx identical). Heap: the CRT ptd (calloc, zero-filled). DC-RAM: 8 bytes `0xCDCDCDCD` at PL slot `+0x137B94` in the three P2-side images, **not read this frame** (the P1 copy that IS read holds real animation-script data). Section 4. |
| Threading? | Nothing on the tick path waits, locks or reads another thread: the executed set contains no `LOCK/XCHG/CMPXCHG/PAUSE/GS:` outside the UCRT (`try_get_function` XCHG, memcpy `SFENCE`). GGPO's sync is outside the tick: `FUN_140118f00` = `ggpo_synchronize_input` → `FUN_140118950` (the tick) → `ggpo_advance_frame`. Section 5. |
| Gates | (a) two runs → SHA-identical blk **and** trace for flag=0 (`a5942b68…`/`03db6732…`, repeated), FMA3 CRT path bit-identical natively; (b) 20 consecutive ticks: clock 2239→2259 (= the live `clock_value_after`), 110–231 B change per tick, RNG bytes `c038` untouched (0 draws in 20 idle frames; the 237-frame post image has `51b0`); (c) `receipt_gate.py` written, PL-image rule CONFIRMED six of six (section 6). |

## 1. Hidden-state inventory (tick `FUN_140118950` on the pre images; first-access classification of every non-`blk` byte)

Method: `scratchpad/hidden_state.py` walks the 313,754-record trace and classifies every byte outside `blk` by its FIRST
access. Read-before-write = carried across frames (candidate hidden state); write-before-read = rebuilt by the frame;
read-only = static. Then one perturbation run per candidate (`determinism_gate.py perturb <name>`).

### 1.1 Read-before-write (the only candidates for TRUE hidden state)

| location | bytes | reader → writer | class | perturbation → blk changed? | verdict |
|---|---|---|---|---|---|
| `game_state+0x218..0x227` pad words | 16 | `FUN_140118950` (reads, then writes the seat-mapped inputs) | **input** | (they ARE the input) | the two seat words per frame; the wrapper overwrites them from its argument, so the loader supplies them per tick |
| `game_state+0x520` | 4 | `FUN_140634920 @0x140634a80` (`CMP [gs+0x520],0` gates `FUN_140634600`, the entity-list/debug walk, also `+0x828`), later written by `FUN_140607e90` (save-slot sync) | (c) carried | **no** (`gs520`: 0x12345678 → blk `03db6732…` identical) | render/UI gate; live value 3 |
| `DAT_142d10b90` GGPO frame counter | 4 | `FUN_140118950` `++` (wrapper only; the sim never reads it) | GGPO-side | **no** (`ggpo_ctr`) | outside the sim; `FUN_140118f00` copies it to `DAT_142e111a8` every frame and to `DAT_142e111b0` every 90 |
| `0x142edf543` | 1 | `FUN_1406163e0` (a 29-case HUD texture re-upload state machine: `0x142edf543` = pending flag, `0x142edf546` = step; re-uploads slots 0x811/0x816/0x817/0x81B/0x81C/0x81D from DC `0x0CDD0000`/`0x0CDF4800`/`G+0x94`) | (c) carried | **no** (`edf543`: 0xFF → blk identical, only the `0x142edf300` page differs) | render (texture uploads); the other three counters `0x142edf318/31C/538` are **write-only** zeros from `FUN_14060b7d0` each frame |
| `*(DAT_142ebc010)+0x34AAC` + ring `+0x346AC` | 4 (+16 written) | `FUN_14006b5d0(a,b,c,d)`: `if (n < 0x40) ring[n++] = {a,b,c,d}` | (c) carried (host heap, `0x28B5EF9C`) | **no** (`heapobj`) | a 64-entry event/debug ring on a heap object; never read back by the frame |
| `ctx+0x1f80a4` mode, `+0x1f80ec` slot-1 matrix (64 B), `+0x1f81b0` storage ptr, `+0x1f81bc` depth | 76 | NaomiLib matrix push/pop (`FUN_140846e90`, `FUN_140847950`) | (c) carried | **YES** (`ctx_matrix`: mode 3 + garbage slot 1 → 49 blk bytes: only the walker's `+0x124/+0x128` screen x/y of fighters/nodes and push slot 0) | the frame is a **fixed point** on `ctx+0x1f80a4..0x1f8600` (0 bytes differ before/after; mode 1, depth 64, slots 0-2 identity, slot 3 = HUD P) — so it is deterministic as long as the loader starts from that balanced state (contract C4) |
| `ctx+0x1f82b0` near plane, `+0x1f855c` | 8 | `FUN_14061d7e0` (the sim's game-logic projection via `FUN_14060fb90`) reads near BEFORE the dispatcher writes 1.0; `FUN_140848ee0` | (c) carried | **no** for blk (`ctx_near`: near=2.0 → TA records/pages/slots differ, blk identical) | live value 1.0; render only |
| `ctx+0x1e2624 + n*0x18` (123 × u16) texture-slot flags | 246 | `FUN_140845fa0` (read then written; `FUN_140845e20` re-reads) | (c) carried | **no** for blk (`ctx_slotflags0`: all 0 → blk identical, `game_state+0x210/0x214` cursors and the slot table differ). ⚠ all-0xFFFF makes the slot search loop forever (60 M-step cap) | render bookkeeping; live value 0x10 |
| DC `0x0CE60040..0x0CE60C40`, `0x0CE62760+704`, `0x0CE62AA0+512`, `0x0CE62CC0+32` | 4,320 | `FUN_140800620` (memcpy into staging) reads BEFORE `FUN_140614210` rewrites the region later in the frame | (a)+(c) partly previous frame | **no** for blk (`dcram_tiletab_prev`: zero-filled → blk, ctx and staging identical) | the copy targets the write-only staging buffer; harmless |
| **`DAT_142edf628` entity list head** (`0x142edf628`, 8 B) + the seven stage-model pointers `0x142edf630..0x142edf667` | 64 | `FUN_140634600`, `FUN_14063b920`, `FUN_14063bd70`, `caseD_7`; `FUN_140607e90` (save-slot sync, Track H's AV site `0x1406083be`) | (b) **static per match, process-absolute** | read-only in the tick; live value = **`blk+0x324E0`** (the head of the in-block entity table whose records `+0x20+8k` = `blk+0x32500+8k` are the six ABSOLUTE fighter self-pointers `blk+0x3DB8+n·0x738`, tag order 0,2,4,1,3,5); `0x142edf630..` → DC `0x0D82D210, 0x0D83A6A8, 0x0D83AA48, 0x0D83ADE8, 0x0D83C380, 0x0D83D710, 0x0D83EAA0` (stage POL models, AFS `801+2·id`) | **must be carried and relocated**: a blk-only anchor restored into another process dereferences source-process addresses (docs/RECEIPT-PLAYER-G.md: `c0000005` at `0x1406083be` reading `entity[+0x20]`); the tick touches nothing else in `0x142edf600..0x142edf800` |
| `game_state+0x758` locked picks (`0x2A,0x2C…`) | 8 | not read by the tick (0 accesses) | match-init input | — | needed only if the anchor is taken BEFORE battle init (char-select anchor); a battle-frame anchor has already consumed it |
| PL slot images `0x0C420000 + pos*0x150000` | read 4,101 B (slot 0) + 5,884 B (slot 1) | sprite submit / decoder / **animation-script stepper `FUN_140611f70`** | (b) static per character | **YES** (`pl_137b94`: the 8-B script record at slot-0 `+0x137B94` → 28 blk bytes: node anim timers `+0x184..0x18B`, depth `+0x12C`, quad total `G+0x24`, `blk+0x6D1C`) | the images are INPUT DATA, sim-relevant; section 6c for what they are |

Not in the list (therefore rebuilt or static): the render-table bookkeeping `DAT_142ec4370..`, `PTR_FUN_142ec6780`, the
sprintf scratch `0x142eed950..0x142edb41` (write-before-read), `game_state+0x210/0x214/0x4F4/0x5DC..` (written by
`FUN_140607d60`/`FUN_140607e90` before use), `DAT_142ef0ab8`; all 400 read-only exe addresses (tables, constants,
`game_state` config words, `__security_cookie 0x140ab12d8` which is only compared with its own stack copy).

### 1.1b What a BATTLE-FRAME anchor must carry (Track H's falsification, docs/RECEIPT-PLAYER-G.md)

Track H restored `blk` alone at char select in a live process: match init locked the wrong team and the save-slot sync
`FUN_140607e90` died at `0x1406083be` on `entity[+0x20]` through `DAT_142edf628`. The trace explains it: the tick reads
`DAT_142edf628` (exe) → `blk+0x324E0` (in-block table) → the six absolute fighter pointers at `blk+0x32500+8k` → the
fighter structs. A blk-only anchor carries the pointers of the SOURCE process. Therefore an anchor taken at a battle
frame (mode `[2,1,2,…]`) must carry, and the loader must place or relocate:
1. `blk[0..0x33B18)` — relocated by `Δ = blk_new − blk_old` on the six self-pointers `blk+0x32500+8k` (self-check: they
   form a permutation of `blk+0x3DB8+n·0x738`), the matrix-storage pointer `ctx+0x1f81b0 = blk`, and every other
   in-block absolute (STEAM-GGPO-DETERMINISM §5 counts 804 intra-blk + 243 arena pointers on a char-select block; the
   557 asset pointers of a battle block point into the PL images — relocate by `Δ_dcram`).
2. the `game_state` page `0x140ac6d40+0x1000` (frame fn `+0x10`, `+0x1B0/+0x1B8`, `+0x208` staging, `+0x218..` pads,
   `+0x258..` seat map `{0,1,-1,-1}`, `+0x758` picks, `+0x828/+0x520/+0x80C` gates, `+0x878..` HUD, `+0x964..`).
3. the exe page `0x142edf300..0x142edf700` — **not `..0x600`**: it must include `DAT_142edf560/580` (blk/G, rewrite to
   the new base), `DAT_142edf588/590/598` (bank POL pointers → `Δ_dcram`), **`DAT_142edf628 = blk_new+0x324E0`** and
   `0x142edf630..0x142edf667` (stage models → `Δ_dcram`), plus the `0x142edf543/546` HUD state.
4. ctx: the texture-slot table `ctx+0x1e0030..0x1e31CC` (host texture handles at `+0x10` of each 0x18-B record are
   render-side; the sim never reads them) and the balanced matrix state (C4); `ctx+8 = dcram_new`.
5. DC-RAM: the six PL images (AFS `209+cid` + tail), the effects/HUD/stage banks by AFS entry.
"Heap entities get valid in a target process" = items 1 and 3: every entity the tick dereferences lives in `blk` or in
the DC-RAM image; nothing on the tick path points into a Windows heap except the debug ring `*(DAT_142ebc010)+0x34AAC`
(no effect) and the UCRT ptd (rebuilt). Falsification: `receipt_gate.py` on a battle-frame anchor restored into a second
process (the p-code harness is the same experiment with `Δ = 0`: images at their live addresses — it passes).

### 1.2 What the 20-tick run says about `blk` itself (gate b)

`determinism_gate.py multitick --ticks 20` (idle inputs, both seat words 0 = what the live image held):
clock 2239→2259 by exactly 1 per tick (the dump's own `clock_value_after` is 2259 — the emulated 20 frames end where the
live dump ended); 104–231 bytes change per tick (input array 2, `G` 5–7, fighters 10–28, stage/camera 2–8, pool nodes
23–42, draw counts 1, battle state 16–17, and on every other tick 54–104 bytes of the un-mapped render-list records
`blk+0x1000..`); 323 distinct bytes over 20 ticks. Against the post image (237 frames later): 7,785 bytes differ pre→post,
231 of them are bytes the 20 ticks touch, 7,554 are never touched in 20 idle frames (fighter/node/camera fields that only
move with input: eye/look-at `0x6914..0x696C`, 146 fighter bytes, 280 node bytes, pool bookkeeping, the RNG `0x32BD4/5`
`c038→51b0`, `G+0x11/0x1D/0x91`, battle-state `0x3254C..0x32586`, `0x33A9A..`). 92 bytes are changed by the ticks but
equal in pre and post (countdowns that cycle). Nothing converges to post because post is a different frame with different
inputs; the point of the gate is that the progression is regular and stays inside the write set of FRAME-READSET §3.

### 1.3 The `blk+0x1000..0x3C66` region (outside the block map)

Written on alternate ticks (54–104 B), read by `FUN_140613390` every frame (`+0x48` of each 0x38-B record). It is inside
the GGPO region, so it is carried by any snapshot; its DC counterpart stays UNKNOWN. No action needed for determinism.

### 1.4 The RNG (CONFIRMED by decompile on both sides + call-shape pairing)

* DC `Rng_function loc_8c11e730` (bank11): `RngVal(0x8C16BC2C) = RngVal*0x41C64E6D + 0x3039; return (RngVal>>16)&0x7FFF`;
  seeder `loc_8C11E770` (srand(1) at battle init); float draw `loc_8C11E750`; 54 routines reference it through a
  literal-pool pointer.
* Steam: `FUN_1407491d0` ↔ `loc_8c10235c` (pair **high**, the routine loads `r9 = Rng_function` and `jsr @r9` four times)
  calls **`FUN_14060fa40`** four times; `FUN_14060fa40` reads/writes only `blk+0x32BD4/0x32BD5` and returns
  `((lo_prev<<8)|lo) & 0x7FFF` after two steps of `x = hi*256+lo; c = (3x)>>8; lo += c; hi = c`. Companions on the same
  state: `FUN_14060f990` (one step, returns `lo`; **~300 call sites**, mostly character-program `caseD_*` handlers),
  `FUN_14060fae0` (= `loc_8C11E750`: draw → float ÷ `DAT_140926114`), `FUN_14060f9e0` (= the seeder: writes `1, 0xC3`;
  one caller `caseD_0` ↔ `loc_8c075fe8` low). 75 callers / 203 call sites of `FUN_14060fa40`.
* The DC generator's constants survive only in `FUN_1400298c0`, a static initialiser building
  `{CRITICAL_SECTION @0x140a5c7d8, state=1 @0x140a5c800, A=0x41C64E6D, C=0x3039, shift=0x10, mask=0x7FFF}` + `atexit`;
  a byte-level RIP-relative scan of the whole image finds **no other reference** to `0x140a5c7d8..0x140a5c814`, no pointer
  to it in the exe, ctx, game_state, blk or blk2, and the live state is still 1 at clock 2239. Dead library object.
* Consequences: the Steam sim RNG is rolled back with the block, carried by any snapshot, not reseeded per frame, and
  **not the DC sequence** — which is consistent with (not proof of) the DC-resim divergence at the first RNG-dependent
  event recorded in RENDER-ACCURACY-PROGRAM.md ("X-position-only at the first assist"). `blk_to_dc(0x32BD4) = 0x8C289CDC`
  is unreferenced in the DC disasm. ⚠ `docs/steam_sh4_map.csv` pairs `FUN_14060f990` with `loc_8c05c02e` (high) and
  `FUN_14060fa40` with `loc_8c1294c8` (low): both are wrong by the decompiles above (the seed marks them superseded).

## 2. External calls (CONFIRMED by the trace: kind-3 records + `extcount`)

The tick leaves the image exactly 24 times, all from the UCRT `__stdio_common_vsprintf` path of the game's sprintf wrapper
`FUN_14003a4c0` (2 calls/frame from `FUN_140627c50`): `GetLastError` (`0x7ffc8a9c8640`), `FlsGetValue`, `RtlAllocateHeap`
(0x3C8 B, flags 8 = HEAP_ZERO_MEMORY), `FlsSetValue`, `HeapFree`, `SetLastError`, 4× each. Return values consumed:
`FlsGetValue` (0 → the CRT builds a fresh ptd), the allocation pointer (must be writable, zeroed), `FlsSetValue` (≠0),
`HeapFree` (≠0). The strings written (`0x142eed950..`, 500 B) are read back by the submit `FUN_1406129f0` in the same frame
and do not reach `blk` (they are part of the `pert_*` runs whose blk hash never moved). No import reads time, ticks,
performance counters, `rand()`, thread ids or Steam. Static cross-check over the executed function set (634 functions):
0 `RDTSC/RDTSCP/RDRAND/RDSEED/CPUID/SYSCALL/XGETBV`; the image's only `RDTSC` user `FUN_1405c0010` is not executed.
`__security_check_cookie` (4×) compares `0x140ab12d8` with the stack copy the same prologue wrote — value-independent.
TEB-relative reads (`0x18, 0x28, 0xA0, 0x20A, 0x1380..0x15C0` per the fault log) come from the UCRT path only and are
zero-filled by the harness with identical results on every run.

## 3. Floating point (CONFIRMED natively + by emulation)

1. **Static:** `re_map/cache/steam_disasm.jsonl`: the 16 functions containing `VFMADD/VFMSUB/VFNMADD/VFNMSUB` all lie in
   `0x140803be0..0x14082b700` (UCRT libm); the 13 x87 users in `0x1408d6c50..0x143446480` (CRT/protection layer). No
   game function (`< 0x1407f0000`) uses FMA or x87. `LDMXCSR` users: `FUN_140803be0` (powf: `STMXCSR`/`LDMXCSR` around its
   own conversion, restores the caller's word), `FUN_1408182b4`, `_fclrf`/`FUN_140829a60`, `FUN_1408d6c50`, and four
   protection-layer functions — none executed by the tick except powf's balanced save/restore. No `_controlfp` on the
   path; the frame runs in the process's default MXCSR (round-to-nearest, exceptions masked, FTZ/DAZ off) — contract C3.
2. **CRT routines the tick calls** (from the call trace): `tanf FUN_140817230` ×10, `sinf FUN_1408121d0` ×10,
   `cosf FUN_140811cd0` ×10, `atanf FUN_1408d577c` ×16 (double arithmetic, no FMA branch), `sqrtf FUN_1408d59fc` ×18
   (`SQRTSS`, exact), `floorf FUN_1408444e0` ×10, `powf FUN_140803be0` ×1 (from NaomiLib `FUN_1408433d0`). Actual
   arguments (`probe`): tanf `0x3ec020c7` (= angle 0x1E94·2π/65536·0.5) and `0x3f490fdb` (π/4, HUD), sinf `0x3e931463`,
   `0x3f24bc7d`, …
3. **Native oracle** (`determinism_gate.py native`): the exe image is mapped at its link base inside the Python process
   and the game's own routines are called with `DAT_142eefbd8 = 0` then `= 1`. Result — 0 differing bits: tanf/sinf/cosf
   155,001-point sweep each; tanf on **all 65,536 u16 angles** through the camera chain (`t = tanf(a·2π/65536/2)`,
   `h = atanf(0.75t)`, `sinf(h)`, `cosf(h)`: 0/65,536 each); atanf 70,001; sqrtf 50,000; floorf 50,000; powf
   `(2.0, y)` 2,064 + 3,000 random pairs. **Dispatch proof** (`determinism_gate.py dispatch`): with the SSE2 fall-through
   of each routine patched to `UD2`, the flag=0 child dies (`0xC000001D` illegal instruction for sinf/cosf, `0xC0000409`
   for tanf/powf whose prologue hits the guard first) and the flag=1 child returns the correct value → the FMA3 path
   really executed. CONFIRMED on this CPU (FMA3 present: the live flag is 1).
4. **Emulation cross-check:** `EmuGate.java fma on` implements the FMA3 CALLOTHERs with `Math.fma`; with the flag at 1
   the tick computes 28 FMAs through tanf/sinf/cosf and then stops at `vpunpckldq_avx` inside powf's AVX branch (Ghidra's
   SLEIGH leaves ~30 AVX integer/convert ops as CALLOTHER) — so the p-code path cannot finish the FMA3 variant; the
   native oracle is the measurement. Flag=0 repeat: trace and blk SHA-identical to the first run (`a5942b68…`, `03db6732…`).
5. **Sensitivity (`nudge` = +1 ulp on every return of one routine):** tanf, atanf, powf → nothing changes; sinf/cosf →
   only ctx (P matrix, TA pages); **sqrtf → 9 blk bytes** (walker screen x/y `+0x124/+0x128` of the drawn fighters/nodes,
   via the eye–target normalisation 812.357117…). So the only CRT result that reaches `blk` on this frame is the exact
   `SQRTSS`. Verdict: **bit-exact across hosts**, no function differs.

## 4. Uninitialised reads (CONFIRMED)

* **Stack:** the harness zero-fills the stack, so the trace was classified by first access: 1,518 bytes touched, **12 read
  before written** — `0x313FEF70+4` by `FUN_1406101b0 @0x1406103cf` (background colour) and `0x313FEFF8+8` by
  `FUN_140607e90 @0x140608688` (save-slot sync). Falsification: `stack_cc` pre-fills the whole 4 MB stack with `0xCC` →
  blk, game_state, ctx and staging hashes identical. No host-state leak through the stack on this frame.
* **Heap:** 0 read-before-write in the bump arena (the ptd is `calloc`'d: zero-fill is the CRT's own contract).
* **DC-RAM / PL images:** the six 0x150000-B slots hold AFS entry `209+cid` byte-exact (six of six), then a loader-built
  tail (`+0x130000..`: fighter pointers `+0x1C8..+0x208` point at `+0x130000/+0x13C000/+0x13D000/+0x13E000/+0x140000/
  +0x141000/+0x145000/+0x148000`). Comparing the two cid-52 images (slots 1 and 4): 0 bytes differ below the entry size,
  67,205 above it, but **0 bytes differ among the bytes the frame reads for that character**. The 8 bytes at `+0x137B94`
  are `0xCDCDCDCD` (MSVC uninitialised-heap fill) in the P2-side images (positions 3,4,5) and real animation-script data
  in slot 0 (`00 00 02 00 5A 03 00 00`, the record `FUN_140611f70` steps to via `*(fighter+0x1C0)+offset`). Not read
  this frame in the P2 images: perturbing only positions 3,4,5 leaves blk/game_state/ctx identical, perturbing positions
  0,1,2 changes 28 blk bytes (`pl_137b94_p2` / `_p1`). Risk class: an image dumped once per
  character reproduces the same bytes on every host (contract C5); whether a *live* loader produces the same tail on two
  boots is **UNKNOWN** (gate: dump the same character twice on two boots, diff the tail over a whole-match read set).
* **TEB/null page:** UCRT-only, section 2.

## 5. Threading (CONFIRMED static + trace)

* Executed-function scan: no `LOCK`-prefixed instruction, `XCHG`, `CMPXCHG`, `PAUSE`, `MFENCE/LFENCE` or `GS:`/`FS:` access
  in any game function; the only hits are the UCRT `try_get_function` (XCHG, lazy API resolver) and `FUN_140800640`
  (memcpy, `SFENCE`). No `WaitFor*/Sleep/CreateThread/Interlocked*` import is reached (section 2 lists all 6 imports).
* Boundary: `FUN_140118f00` (GGPO `advance_frame` callback) = `FUN_140119a60(session, &inputs, 0x10, &flags)`
  (`ggpo_synchronize_input`) → **`FUN_140118950(&DAT_142d10b90, inputs, flags)`** (the tick) → `DAT_142e111a8 = counter`
  (every 90 frames also `DAT_142e111b0`) → `FUN_1401198d0(session)` (`ggpo_advance_frame`). Everything that talks to
  the network, waits, or rolls back (`FUN_140119380` save, `FUN_140118fa0` load) is outside `FUN_140118950`. The tick
  consumes only its `inputs[4]` argument (24-bit words) and `game_state+0x258..0x264` (seat map).

## 6. Gates

* **(a) Same state + same inputs → same bytes.** Tick twice: trace `a5942b68…` and blk `03db6732…` SHA-identical
  (FRAME-READSET), repeated here as `fma_flag0_r2` (identical again); every `pert_*` run that did not touch a sim input
  reproduced the same `03db6732…`. FMA variant: p-code cannot complete it (section 3.4); the native oracle shows the CRT
  outputs are identical, so the FMA3 host produces the same `blk` by construction.
* **(b) 20 consecutive ticks**, section 1.2: `determinism_gate.py multitick --ticks 20`.
* **(c) Receipt gate** — `d3dcap/replay/receipt_gate.py --run <dump> --tape <tape>`: anchors at the dump's clock (the
  tape row with `frame == blk+0x3CC8` must exist), checks the tape roster against the dump's fighter cids and each PL slot
  image against AFS `209+cid`, then ticks N frames feeding `seat_in[k]` of row `frame+k` and compares per frame
  `blk+0x3CC8`, `px/py` (`fighter+0x50/+0x54`, f32 bit-exact) and `hp` (`fighter+0x578 & 0xFFFF`) of all six slots against
  the tape rows; prints the first divergence per field. `--selftest` builds a synthetic tape from the 20-tick dumps
  (plumbing gate: **PASS 20/20 on clock, px, py, hp**); `--selftest --negative --flip-bit <raw bit>` XORs one raw pad
  bit into seat 0 on every frame and must diverge — with the raw→sim table `DAT_140a4f780` (`0x8→0x8000, 0x1→0x4000,
  0x10→0x2000, 0x40→0x1000, 0x80→0x800, 0x20→0x400`, `FUN_140048630`; direction bits are NOT in this table — where the
  sim takes directions from is UNKNOWN here) bit 0x8 left px/py/hp unchanged over 20 frames (INCONCLUSIVE), see the
  appendix for the other bits tried. ⚠ First negative runs (bits 0x8/0x1/0x40) injected NOTHING: the offline seat map
  `{0,0,0,0}` makes the wrapper route `inputs[3]` to seat 0 (last write wins) and never feed seat 1 (0 of 211,736 blk
  bytes differed from the reference dumps over 20 ticks). The tool now sets `{0,1,-1,-1}` (contract C2) and diffs the
  negative run against the reference dumps.
  **PL-image requirement:** position `pos` (order 0,2,4,1,3,5 = fighter slots) of `0x0C420000 + pos·0x150000` = AFS entry
  `209 + (fighter+0x6C0 & 0xFF)` (= `fighter+0x1`), CONFIRMED byte-exact on all six slots of the run (cids 42→AFS 251
  0x10E3E0 B, 44→253, 52→261 twice, 23→232, 53→262); the `0x100` bit of `+0x6C0` is a flag (set on five of six slots),
  not part of the id. The same character in two slots gives the same bytes for everything the frame reads (section 4).
  A per-character image cache therefore holds AFS-entry + dumped tail per cid; the loader routine that builds the tail is
  still **UNKNOWN**. A tape AND a same-match dump do not yet exist together (the only live dumps have roster
  42/52/44/23/52/53, the capgate tapes another roster — FRAME-READSET §0 iv); the tool is ready for the first pair.

## 7. THE CONTRACT — invariants a loader / thin client MUST preserve (each with its check)

| # | invariant | check |
|---|---|---|
| C1 | **Memory layout:** `blk` (0x33B18 B) at `*(0x142edf560)`, `G = blk+0x3CB8` at `*(0x142edf580)`, `blk2` right after `blk`, `game_state` page at `0x140ac6d40` (`+0x10` frame fn, `+0x1B0/+0x1B8` blk ptr/size, `+0x208` staging ptr, `+0x218..` pads, `+0x258..` seat map, `+0x758` picks), ctx (0x400000 B) at `*(0x142ef0ab0)` with `ctx+8` = DC-RAM host base and `ctx+0x1f81b0 = blk`, DC-RAM 32 MB, the exe page `0x142edf300..0x142edf700` with **`DAT_142edf628 = blk+0x324E0`** and `DAT_142edf588/590/598/630..667` pointing into the DC-RAM image, the six self-pointers `blk+0x32500+8k` = a permutation of `blk+0x3DB8+n·0x738`, the exe image at `0x140000000` (no relocation; the image is position-dependent) | `meta.json`-style handles agree: `*(gs+0x1B0) == *(0x142edf560)`, size `0x33B18`, `*(ctx+8) == dcram`, `*(0x142edf628) == blk+0x324E0`, self-pointer permutation check; `emu_frame.frame_job` asserts scratch regions do not overlap any image |
| C2 | **Input timing and routing:** exactly one call of `FUN_140118950(&DAT_142d10b90, inputs[4], 0)` per frame with `inputs[k] & 0xFFFFFF` = the tape's `seat_in[k]` for the frame being produced. The wrapper ZEROES all four pads, then writes `pad[seat(k)] = inputs[k]` for every `seat(k) = game_state+0x258+4k >= 0` (decompile). **The seat map must be `{0, 1, -1, -1}`** (player k → seat k); an OFFLINE anchor carries `{0,0,0,0}`, which routes only `inputs[3]` to seat 0 and never feeds seat 1 — the first negative self-tests injected nothing for exactly that reason (0 blk bytes differed) | `blk+0x3CC8` advances by exactly 1 per call (multitick); `receipt_gate.py` sets the map in the job and px/py/hp per frame; the negative self-test must show blk bytes differing |
| C3 | **Float environment:** default MXCSR (0x1F80: RN, all masked, FTZ=DAZ=0); `DAT_142eefbd8` may be 0 or 1 (both paths bit-identical, section 3) but must not be flipped mid-match without reason; no x87 state needed | `STMXCSR` at entry == 0x1F80; `determinism_gate.py native` on the target host (0 differing) |
| C4 | **ctx at frame entry = the balanced NaomiLib state:** `ctx+0x1f80a4 = 1`, push storage ptr `+0x1f81b0 = blk`, depth `+0x1f81b8/+0x1f81bc = 0x40`, slots 0–2 identity (slot 3 = whatever the previous frame's HUD camera left), `+0x1f82b0 = 1.0`; texture-slot table `ctx+0x1e0030..0x1e31CC` as built by the bank loaders (flags 0x10) | the frame is a fixed point on `ctx+0x1f80a4..0x1f8600` (0 bytes differ after a tick); `ctx_matrix` perturbation shows a wrong entry state corrupts screen x/y |
| C5 | **DC-RAM contents per roster:** the six PL images = AFS `209+cid` + the dumped tail (byte-exact copy from a real load, per character); effects bank AFS 799/800 at `0x0D000000`, HUD bank 835/836 at `0x0D082000`, stage POL/TEX `801/802+2·id` at `0x0D82D000/0x0D85D000`; the `0x0CE60000` tile table need not be carried (rebuilt) | `receipt_gate.check_pl_images` (six byte-equal), `rip_texbank.py --gate` (16/16 pages) |
| C6 | **Stubbed imports:** `FlsGetValue → 0` (or a real FLS), `RtlAllocateHeap(…, 8, n) → zeroed writable memory`, `FlsSetValue → 1`, `HeapFree → 1`, `Get/SetLastError` free; nothing else is called | `extcount` of a traced tick lists exactly these 6 targets |
| C7 | **Exe mutable pages carried in the snapshot:** `game_state` (0x1000) and `0x142edf300..0x142edf700` (the `0x142edf543/546` state machine, the blk/G/bank/entity/stage pointers — relocated per C1); everything else the frame reads in the exe is constant, everything else it writes is rebuilt before use | `hidden_state.py` classification: read-before-write set == section 1.1; the tick touches nothing in `0x142edf668..0x142edf800` |
| C8 | **RNG:** nothing to seed; `blk+0x32BD4/5` travels with the block | `multitick` prints the two bytes per tick; a receipt diverging at an RNG event with identical inputs would falsify the location |
| C9 | **Single thread, no waits:** run the tick synchronously; no other thread may touch the pages of C1 during the call | section 5 scan (re-run `hidden_state.py` asm scan on any new build) |

Falsification of the whole contract = the receipt gate: a same-match tape + dump ticked N frames with px/py/hp exact
every frame on two different hosts. Until that pair exists the contract is CONFIRMED on one host, one roster, one idle-ish
frame (+20 idle ticks), and INFERRED beyond that.

## 8. Address index

`FUN_140118950` tick · `FUN_140118f00` advance_frame cb · `FUN_140119a60` sync input · `FUN_1401198d0` advance ·
`FUN_140607d60` frame · `FUN_14060fa40` rand16 (`blk+0x32BD4/5`) · `FUN_14060f990` rand8 · `FUN_14060fae0` randf ·
`FUN_14060f9e0` seed · `FUN_1400298c0` dead LCG init (`0x140a5c7d8/0x140a5c800`) · `FUN_1407491d0`↔`loc_8c10235c` ·
`loc_8c11e730` DC Rng_function · `FUN_140634920/FUN_140634600/FUN_14063b920` (`gs+0x520`, `DAT_142edf628 = blk+0x324E0`, self-pointers `blk+0x32500+8k`) · `FUN_1406163e0` (`0x142edf543/546`) ·
`FUN_14060b7d0` (`0x142edf318/31C/538`) · `FUN_14006b5d0` (`*(0x142ebc010)+0x34AAC` ring) · `FUN_140611f70` script stepper
(`fighter+0x186/+0x198/+0x1C0`) · `FUN_140845fa0` slot flags (`ctx+0x1e2624+n·0x18`) · `FUN_140846e90/FUN_140847950`
matrix (`ctx+0x1f80a4/+0x1f80ec/+0x1f81b0/+0x1f81bc`) · CRT: `FUN_140817230` tanf, `FUN_1408121d0` sinf, `FUN_140811cd0`
cosf, `FUN_1408d577c` atanf, `FUN_1408d59fc` sqrtf, `FUN_1408444e0` floorf, `FUN_140803be0` powf (SSE2 fall-throughs
`0x140817241/0x1408121e1/0x140811ce1/0x140803bfd`), `DAT_142eefbd8` flag, `__security_cookie 0x140ab12d8`,
`FUN_1405c0010` (RDTSC, not executed).

## Appendix — run log (2026-09-03, `%TEMP%\rrcap_emu\pert_*.result.txt`)

| run | blk | game_state | ctx (ta1/ta2/pages/slots/matrix) | note |
|---|---|---|---|---|
| baseline / fma_flag0_r2 / probe_math | `03db6732…` | `699367d7…` | `89614a0b/c80e4729/51ef6bd0/fc42f098/8bf0d076` | trace `a5942b68…` |
| gs520, ggpo_ctr, edf543, edf318, heapobj, dcram_tiletab_prev, stack_cc, nudge_tanf, nudge_atanf, nudge_powf | same | same | same | no effect |
| ctx_near | same | same | ta/pages/slots differ | render only |
| ctx_slotflags0 | same | `3db54a2c…` | slots differ | render only |
| ctx_matrix | `0215e261…` | same | pages/matrix differ | screen x/y + push slot 0 |
| nudge_sinf / nudge_cosf | same | same | pages/matrix differ | render only |
| nudge_sqrtf (`FUN_1408d59fc`) | `7032cd11…` | same | ta2/pages/matrix differ | 9 B: screen x/y |
| pl_137b94 (all six slots) | `202a53a8…` | `a58a9b2e…` | all differ | slot-0 script record is sim input |
| pl_137b94_p1 (slots 0,2,4) | `202a53a8…` | `a58a9b2e…` | all differ | slot 0's real script record is sim input |
| pl_137b94_p2 (slots 1,3,5 = the 0xCD bytes) | same as baseline | same | same | the uninitialised bytes are not read this frame |
| fma_flag1_skip | aborted at `0x14081761f` (`vfmadd213sd_fma`) | | | expected |
| fma_flag1_compute | 28 FMAs computed, aborted at `0x140804346` (`vpunpckldq_avx`) | | | p-code limit |
| receipt_gate --selftest (20 ticks, synthetic tape from the 20-tick dumps) | clock 20/20, px 20/20, py 20/20, hp 20/20 → **PASS** | | | plumbing gate: schema, slot order, offsets, job |
| receipt_gate --selftest (re-run with the seat map `{0,1,-1,-1}` in the job) | clock 20/20, px 20/20, py 20/20, hp 20/20 → **PASS** | | | |
| receipt_gate --selftest --negative --flip-bit 0x8 / 0x1 / 0x40 (seat map `{0,0,0,0}`, before the C2 fix) | 20/20 on every field, **0 of 211,736 blk bytes differ** from the reference dumps on every tick | | | nothing was injected: the offline seat map routes `inputs[3]` only (section 7, C2) |
| receipt_gate --selftest --negative --flip-bit 0x1 (seat map `{0,1,-1,-1}`) | px/py/hp 20/20 (a standing button press does not move a fighter), **360 blk bytes differ** from the reference dumps over 20 ticks | | | the injected input reaches the sim; the gate's px/py/hp columns are insensitive to a button on an idle fighter — a direction or a hit is needed for a px/hp divergence |
