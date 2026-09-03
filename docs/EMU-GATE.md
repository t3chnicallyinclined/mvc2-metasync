# EMU-GATE — emulating Steam MvC2 functions on captured state (Ghidra p-code, 2026-09-02)

RE METHOD step 4 (`docs/RE-METHOD.md`): the pairs were matched in steps 1-3 (seeds 24, 30); this is the
deterministic, numeric GATE. A Steam x86-64 routine is executed instruction by instruction in Ghidra's
p-code emulator with the memory of a captured frame, and its outputs are compared bit-for-bit with what the
same frame's capture holds. Tags: **CONFIRMED** = read on both sides / reproduced by the gate; **INFERRED** =
fingerprint or gate-consistent only; **UNKNOWN** = not located.

Harness: `d3dcap/replay/emu_gate.py` (driver) + `d3dcap/replay/re_map/ghidra_emu/EmuGate.java` (Ghidra
script). Seed: `maplecast-flycast/tools/re_kb/104_emu_gate.surql`. Work files (block dumps, job files, logs,
results) live in `%TEMP%\rrcap_emu\` — ROM-derived bytes never enter the repo.

## 0. Answer

| target | frame | result |
|---|---|---|
| `FUN_14061d7e0` world camera | 4445 | PROJ (ctx+0x1f816c) and VIEW (ctx+0x1f812c) **16/16 floats bit-identical** to the captured scene CB `7793F141` rows 15-18 / 7-10; their float32 product = rows 0-3 **16/16 bit-identical**. Closed form (WORLD-CAMERA-GHIDRA.md s2, float64): max abs 3.94e-7 (P), 0 (V). 1149 instructions. |
| `FUN_14061d6a0` x0.1 camera | 4445 | **16/16 / 16/16 / 16/16** vs CB `AD5C2A43` (106 draws, lists 7/8/9). Closed form 3.94e-7 / 0. 1156 instructions. |
| `FUN_14061d5b0` HUD camera | 4445 | **16/16 / 16/16 / 16/16** vs CB `04E19F4C` (339 draws). Closed form 7.95e-8 / 0. 637 instructions. |
| `FUN_140620f10` sprite walker | 4445 | 47 drawn nodes: `+0x124/+0x128/+0x12C/+0x130/+0x134/+0x148/+0x150/+0x154/+0x178/+0x17A` **47/47 bit-exact each**; LayerZ table 16/16; quad total G+0x24 133 = 133; **0 of 211,736 block bytes differ** after the walk (the post-walk dump is a fixed point of the walk). 14,767 instructions. |
| same | 4505 / 5168 / 7279 | 6/6, 5/5, 4/4 nodes bit-exact on all ten fields; 0 block bytes differ; quad totals 118/112/96 reproduced. |
| same, cell-override frames | 5227 / 5232 | sx/sy/depth/facing/+0x150 exact on all 8 / 10 nodes; scale, angle, hotspot WRONG on exactly the 3 / 5 nodes with `+0x191 != 0` — the walker read 12 bytes at `0x12531020` and `0x12531050`, the owner's animation-cell table inside the DC-RAM host image, which no capture holds (section 5). |

Both CRT strategies (section 2.3) give identical bits.

## 1. Exact invocation

One-time import of the dump into a scratch project (the GUI keeps `dumpproj` locked; the emulator only needs
bytes, so a fresh raw import with no analysis is used — `ensure_project()` runs this if the project is missing):

```
"C:\g\ghidra_12.1.2_PUBLIC\support\analyzeHeadless.bat" C:\Users\trist\ghidra_projects\emu emuproj -import C:\Users\trist\ghidra_projects\mvc_dump.bin -loader BinaryLoader -loader-baseAddr 0x140000000 -loader-blockName image -processor x86:LE:64:default -cspec windows -noanalysis
```

Gates:

```
cd C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\replay
python emu_gate.py camera 4445                       # three camera routines vs capgate\frame_4445.pack CBs + closed form
python emu_gate.py camera 4445 --math hook           # same with Java Math replacing tanf/atanf/sinf/cosf
python emu_gate.py walker 4445                       # sprite walker vs the post-walk dump (composite = current camera)
python emu_gate.py walker 4445 --composite prev      # falsification variant: previous-frame camera in ctx+0x1f8200
python emu_gate.py walker 4445 --composite none      # falsification variant: identity composite
python emu_gate.py walker 5232                       # a frame with cell overrides (+0x191): shows the DC-RAM blocker
python emu_gate.py raw <job.txt>                     # any hand-written job (format in EmuGate.java header)
```

Each run executes, per job, one headless process:

```
"C:\g\ghidra_12.1.2_PUBLIC\support\analyzeHeadless.bat" C:\Users\trist\ghidra_projects\emu emuproj -process mvc_dump.bin -noanalysis -readOnly -scriptPath C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\replay\re_map\ghidra_emu -postScript EmuGate.java %TEMP%\rrcap_emu\<tag>.job.txt
```

Wall time is ~9 s per job (Ghidra start-up); the emulation itself is 50-800 ms.

The job the world-camera gate ran (verbatim, frame 4445, base recovered from the handles = 0x163E1000):

```
stack 10000000 100000
mem 163e1000 %TEMP%\rrcap_emu\cam_world_4445_sse2.blk.bin      # blkstate.load_frame(4445), 211,736 B
set8 142edf560 163e1000                                        # DAT_142edf560 = blk
set8 142edf580 163e4cb8                                        # DAT_142edf580 = blk + 0x3CB8
reg RCX 163e1000
reg RDX 40
maxsteps 10000
run 140846a40                                                  # FUN_140846a40(blk, 0x40): matrix-stack init
set4 119d92b0 3f800000                                         # ctx+0x1f82b0 (near) = 1.0
set4 142eefbd8 0                                               # UCRT: take the SSE2 path
maxsteps 200000
run 14061d7e0
dump 119d90a4 200 ...slots.bin                                 # ctx+0x1f80a4: mode, then the four 64-B slots
```

The walker job adds: `set4 blk+0x6d08+4L <LayerZ[L]>` for L = 0..15, `set4 blk+0x3CDC 0` (G+0x24),
`run 14061d7e0; run 140847d10` (the composite prologue), `stubmap 1406129f0 FUN_1406129f0 <file>` and
`run 140620f10`, then dumps the whole block.

## 2. Memory model — what was provided and what had to be synthesised

The emulator's backing store is the raw dump (`mvc_dump.bin` is a flat memory image: section VAs equal file
offsets, verified by reading `_DAT_1408fefd0` = 65536.0, `DAT_140a6e518` = 1400000.0, `DAT_140ab2080` = the
Screen matrix, `DAT_142ef0ab8` = 0x119D90EC = `ctx+0x1f80ec` at dump time). Every read the job did not
provide and the image does not cover is zero-filled AND logged by a `MemoryFaultHandler`; the driver
classifies the log (stack / ctx / null page / blk / other). What the targets needed:

| memory | provided by | tag |
|---|---|---|
| code, float constants, identity `DAT_140ab20c0`, Screen `DAT_140ab2080`, sin/cos tables `DAT_142ef0ac0/142f30ac0` | the image | CONFIRMED (dump-time values) |
| `blk` (211,736 B) at its live base | `blkstate.load_frame` + base from the handles (page-aligned vote, `emu_gate.recover_base`; sidecars newer than these captures carry `base` directly) | CONFIRMED |
| `DAT_142edf560`, `DAT_142edf580` | job (`set8`) | CONFIRMED (dump holds the dump-time pointers 0x15AE1000 / +0x3CB8, same relation) |
| `ctx` = `*DAT_142ef0ab0` = 0x117E1000 (NaomiLib host context, 0x1f8600 B, heap) | NOT in the dump. Initialised by running the engine's own `FUN_140846a40(blk, 0x40)` — the exact call the game makes at `0x14060b628` in `FUN_14060b550` (`MOV RCX,[0x142edf560]; MOV EDX,0x40`) — plus `ctx+0x1f82b0 = 1.0` (first statement of `FUN_140620960`, CONFIRMED). | CONFIRMED init state; that the slots are still identity when the walker runs is INFERRED (push/pop balance) and gate-consistent |
| matrix push/pop storage | **is `blk+0x0..0x1000`** (0x40 slots x 64 B): `FUN_140846a40` stores its first argument = `DAT_142edf560` at `ctx+0x1f81b0`. So the captured block already holds it; after the emulated walk those bytes are unchanged (0 diffs). | CONFIRMED (call site + gate) |
| stack | job (`stack 10000000 100000`, RSP = top-0x1008 so RSP ≡ 8 mod 16 at entry) | synthesised |
| TEB / null page (`0x18, 0x28, 0x38, 0x1300.., 0x1380..0x15c0` in 16-B steps) | zero-filled: the UCRT `tanf/atanf/sinf/cosf` touch GS-relative TLS/FP-state; harmless (their outputs are bit-exact) | synthesised, logged |
| `ctx+0x1f81ac..+0x1f82a4` (248 B) | reported as first-touch uninitialised; it is the stack pointer/counter/scratch area `FUN_140846a40` writes before anything reads it (page-granular report) | synthesised, logged |
| `DAT_142eefbd8` (UCRT FMA3 dispatch flag) | the dump holds **1** (AVX/FMA paths: `vfmadd213sd` is `CALLOTHER` in Ghidra's x86 SLEIGH, unimplemented — the first run died at `0x14081761f` inside `tanf` after 99 instructions). Set to 0 → the SSE2 path of the same CRT runs (default, `--math sse2`). Alternative `--math hook`: `FUN_140817230/1408d577c/140811cd0/1408121d0` replaced by Java `Math.tan/atan/cos/sin` on float. Both give bit-identical P/V. | synthesised (one u32) |
| walker: `blk+0x6d08..0x6d44` LayerZ table BEFORE accumulation | the dump is post-walk (`"at":"walk"`), so the table already contains `+0.001 x quads`; restored from the constants `FUN_140613390` writes (`DAT_140a6d888` = 15,17,19,21,23,25,27,29 then immediates 10,11,12,13,30,31,32,33). The per-frame resetter is UNKNOWN (no other function carries a 0x6d08..0x6d44 displacement; `FUN_140613390` is called only from `FUN_14060a1f0`). | synthesised from CONFIRMED constants |
| walker: `G+0x24` (per-frame quad total) | set to 0; after the walk it equals the dump on every frame (133/118/112/96/146/152) | synthesised |
| walker: `FUN_1406129f0(node)` (submit; returns the quad count) | STUBBED: its body walks the GFX1/GFX2/template pointers `+0x1A8/+0x1B0/+0x1F0` into the DC-RAM host image, which no capture holds. Return values recovered from the dump's own depth chain (`depth_i+1 - depth_i = 0.001 x count_i`, last node from the LayerZ total); they only feed later nodes' `+0x12C` and `G+0x24`. | synthesised; the count is NOT emulated |
| walker: `ctx+0x1f8200` composite at walk start | see section 4.2: must hold the CURRENT frame's V·P·Screen (`run 14061d7e0; run 140847d10` before the walker) | synthesised; owner INFERRED |
| cell-override nodes: `*(blk+0x3F78 + owner*0x738) + cell*16` | a host pointer (0x12531000 on 5227/5232) into the DC-RAM image: NOT available → zeros → wrong scale/angle/hotspot on those nodes only | BLOCKED, section 5 |

## 3. Target 1 — the camera routines (frame 4445)

State read from the block: eye (256.51828, 190.71429, 812.35712), target (256.51828, 190.71429, 0), fov 43.0,
`0x6988` = -0.41, roll 0, camera state bytes (0, 1, 0); angle = 0x1E94.

Captured CB selection is structural (independent of the emulated values): `world` = the 432-B CB bound by
`vs_world` draws whose 48-B CBWorld is the identity AND whose V (rows 7-10) is not the identity (the 25 HUD
draws also bind an identity CBWorld — the first picker fell into that); `hud` = V is the identity; `x0.1` =
whatever else is bound to at least one draw. Frame 4445: world `7793F141` (11 draws, 6 identity-CBWorld),
hud `04E19F4C` (339), x0.1 `AD5C2A43` (106).

| routine | P bits | P max abs | V bits | V max abs | V·P (f32) bits | vs closed form P / V | final mode | steps |
|---|---|---|---|---|---|---|---|---|
| `FUN_14061d7e0` vs `7793F141` | 16/16 | 0 | 16/16 | 0 | 16/16 | 3.94e-7 / 0 | 1 | 1149 |
| `FUN_14061d6a0` vs `AD5C2A43` | 16/16 | 0 | 16/16 | 0 | 16/16 | 3.94e-7 / 0 | 1 | 1156 |
| `FUN_14061d5b0` vs `04E19F4C` | 16/16 | 0 | 16/16 | 0 | 16/16 | 7.95e-8 / 0 | 1 | 637 |

Emulated `P` (world): `[2.538616 0 0 0 | 0 3.384821 0 0 | 0 0.41 -1.0000014 -1 | 0 0 -2.0000014 0]`;
`V` row 3 `(-256.5183, -190.7143, -812.3571, 1)`. The x0.1 routine gives `-1.000167 / -2.000167` and
`V` row 3 `(-25.65183, -19.07143, -81.23571, 1)`; the HUD routine `[0.9999999 0 0 0 | 0 1.333333 0 0 |
0 0 -1.000167 -1 | 0 0 -2.000167 0]` with `V = I`. **These are the bytes the host D3D layer received**
(rows 15-18 and 7-10 of the scene CB are the raw 128-B command-4 payload), so the SH4 → x86 recompile of
`loc_8c02e1a4 / loc_8c02e246 / loc_8c02e334` and the NaomiLib matrix routines is gated byte-exact on real state.
The float64 closed form is 1 ulp away on `P[0][0]`, i.e. its own rounding.

## 4. Target 2 — the sprite walker

### 4.1 Result

Input = the frame's own post-walk dump (`state_<f>.json "at":"walk"` — one dump per frame). The walker's
outputs are pure functions of inputs it does not modify, so running it on a post-walk block must reproduce the
block: the gate is idempotence, byte for byte. Only three things are not idempotent and were reset (LayerZ,
`G+0x24`, and the composite; section 2).

| frame | drawn nodes | fields bit-exact | LayerZ | G+0x24 | block bytes changed | steps |
|---|---|---|---|---|---|---|
| 4445 | 47 (43 cat-1 layer 0, 2 fighters, 2 cat-4) | 10/10 fields x 47/47 | 16/16 | 133 = 133 | **0** | 14,767 |
| 4505 | 6 | 10 x 6/6 | 16/16 | 118 = 118 | 0 | 5,580 |
| 5168 | 5 | 10 x 5/5 | 16/16 | 112 = 112 | 0 | 5,356 |
| 7279 | 4 | 10 x 4/4 | 16/16 | 96 = 96 | 0 | 5,132 |
| 5227 | 8 (3 with `+0x191`) | sx/sy/depth/facing/+0x150 8/8; scx/scy/angle 5/8; hotspot 7/8 | 16/16 | 146 = 146 | 31 (all inside the 3 cell nodes) | 6,115 |
| 5232 | 10 (5 with `+0x191`) | sx/sy/depth/facing/+0x150 10/10; scx/scy/angle 5/10; hotspot 9/10 | 16/16 | 152 = 152 | 49 (all inside the 5 cell nodes) | 6,621 |

"Block bytes changed = 0" means: every byte the walker wrote (the ten fields of every drawn node, the
LayerZ table, `G+0x24`, and the 64-B push slots in `blk+0..0x1000`) equals the captured byte, and nothing
else was written. That is the strongest form of the gate this data allows.

### 4.2 The composite experiment (a finding)

Cat-1..4 nodes walked BEFORE the first fighter (layer 0 on frame 4445: 43 hail chunks) do not call the camera;
`FUN_140848120` projects them through whatever `ctx+0x1f8200` (V·P·Screen, written only by `FUN_140847d10`)
holds. `FUN_140620960` does not compose before calling the walker. Three seeds, one variable:

| `ctx+0x1f8200` at walk start | sx exact | sy exact | max abs |
|---|---|---|---|
| identity (`--composite none`) | 4/47 (the fighters and their satellites) | 4/47 | 63.5 / 2250 |
| previous frame's camera (`blk+0x6920..`, `--composite prev`) | 4/47 | 47/47 | 0.164 px |
| current frame's camera (`blk+0x6914..`, `--composite cur`) | **47/47** | **47/47** | 0 |

**CONFIRMED by gate:** at walker time the composite already holds the CURRENT frame's camera. **INFERRED
owner:** `FUN_14060fb90(point, out)` — world-point-to-screen for game logic, which calls `FUN_14061d7e0` then
`FUN_140847d10` then `FUN_140848120`; it is the only non-debug writer of `ctx+0x1f8200` besides the walker
(`xrefs_to 0x140847d10`: `FUN_14060fb90`, `FUN_140613cd0` debug overlay, `FUN_140620f10`, `FUN_14062fdc0`).
Falsification: hook `FUN_140847d10` live and log the caller per frame; if the last caller before the walker is
not `FUN_14060fb90` (or `FUN_14062fdc0`), the owner is elsewhere. Consequence for a reconstruction: the
current camera is the right one for ALL sprite nodes, never the previous frame's (the previous-frame lag of
`blk+0x6920..` documented in WORLD-CAMERA-GHIDRA.md s6 does not reach the sprite positions).

### 4.3 Where the input comes from vs. the task statement

The task allowed "previous frame's dump as input, current as expected". Not needed: with a post-walk dump the
idempotence gate is stricter (same frame, byte-exact) and it does not depend on the game state having stayed
still between frames.

## 5. What the emulator could NOT do — precisely

1. **Cell-override nodes need the DC-RAM host image.** When `node+0x191 != 0` the walker reads the 16-B cell
   `*(node+0x1C0) + cell*16` (fighters) or `*(blk+0x3F78 + owner*0x738) + cell*16` (objects). On frames
   5227/5232 that is `0x12531020` and `0x12531050` (owner slot 0, table pointer `0x12531000`) — a host
   pointer into `ram = *(*(0x142ef0ab0)+8)`, which is heap memory in neither the dump nor any capture.
   The emulator zero-filled it: scale became 0, angle 0 (expected 0x1400 = 5120, the bolt rotation of
   `mvc-rotation-path-180`), hotspot 0 (expected 65480/65412 on the cat-3 node). Every other field on those
   nodes and every field on the other nodes stayed exact. **Smallest missing piece: the 6 x u16 cell at
   `ram + 0x531020` / `ram + 0x531050`** (or generally the owner's animation table, 16 B per cell) — a
   capture-side dump of `*(blk+0x3F78+slot*0x738)[cell]` for the drawn nodes would close it.
2. **`FUN_1406129f0` (submit) is stubbed.** Its body needs GFX1/GFX2/template data in DC RAM
   (`+0x1A8/+0x1B0/+0x1F0`) and the texture-slot tables; the per-node quad count was recovered from the
   dump's depth chain instead. The count only influences later nodes' `+0x12C` and `G+0x24`, both of which
   then reproduce exactly — but the count itself is NOT an emulation result.
3. **Per-frame LayerZ reset: UNKNOWN.** Restored from `FUN_140613390`'s constants (CONFIRMED values; its only
   caller is `FUN_14060a1f0`, an init). The routine that resets `blk+0x6d08..` every frame was not located
   (no other function carries those displacements; it may use a register base or a block copy).
4. **Base recovery on sparse frames.** Frame 4518 (2 handles) made `blkstate.find_base` return 0x15DE3BB0;
   the driver now requires a page-aligned base with every handle inside and refuses otherwise (36 of the 288
   sampled frames fail that test — all sparse ones). Captures made after the sidecar gained `base` do not
   need the vote.
5. **AVX/FMA CRT paths** are not in Ghidra's x86 p-code (`vfmadd213sd_fma` = unimplemented CALLOTHER). Forcing
   `DAT_142eefbd8 = 0` runs the same CRT's SSE2 code and matched bit-for-bit; the Java-math hooks also match.
   Any target that hits AVX code outside the CRT dispatch would need a hook.

## 6. Findings

CONFIRMED (gate, byte-exact on captured state):
* `FUN_14061d7e0 / FUN_14061d6a0 / FUN_14061d5b0` produce exactly the P and V bytes the D3D scene CBs carry
  (rows 15-18 / 7-10), and `V x P` in float32 = rows 0-3.
* `FUN_140620f10` reproduces every render field of every drawn node on 4 frames (62 nodes) byte-exact, and
  the post-walk block is a fixed point of the walk.
* `FUN_140846a40(DAT_142edf560, 0x40)`: the NaomiLib matrix push/pop storage is the first 0x1000 bytes of
  `blk` (call site `0x14060b628`); push slots in the capture equal the emulated pushes.
* `FUN_140847950` (push) returns 0 without loading its argument when `ctx+0x1f81bc < 1` — a zeroed ctx makes
  every point projection return (0, 0) through the `w == 0` branch of `FUN_140848120`.
* At walker time `ctx+0x1f8200` holds the CURRENT frame's V·P·Screen (prev-frame and identity both falsified).

INFERRED: `FUN_14060fb90` is the pre-walker composite writer; matrix slots are identity at walker entry
(push/pop balance).

UNKNOWN: the per-frame LayerZ resetter; the host address of the DC-RAM image at capture time.

## 7. Extending the gate

* New frame: `python emu_gate.py walker <f>`; needs `state_<f>.json` + its delta chain in `capgate/state`.
  Camera needs `capgate/frame_<f>.pack`.
* New function: write a job (EmuGate.java header documents the 12 commands) and run `emu_gate.py raw`.
  Provide `blk`, the two block globals, the stack-init prologue, `near`, and the CRT flag; read the
  `uninit`/`unknown` lines of the result to see what else the function needed.
* Deterministic gate rule: compare bits, not pictures; when a field is not bit-exact, the run's `uninit`
  list names the memory that was synthesised — that is the suspect, before any code is edited.

## 8. Address index

Steam: `FUN_14061d7e0` world camera · `FUN_14061d6a0` x0.1 · `FUN_14061d5b0` HUD · `FUN_140620f10` walker ·
`FUN_1406129f0` submit (stubbed) · `FUN_140848120` point projection · `FUN_140847d10` composite ·
`FUN_140846a40` stack init (`0x14060b628` call site, args `(DAT_142edf560, 0x40)`) · `FUN_140847950/1408478c0`
push/pop (`ctx+0x1f81b0` storage ptr, `+0x1f81b8/+0x1f81bc` depth) · `FUN_140613390` LayerZ init
(`DAT_140a6d888`) · `FUN_14060fb90` game-logic projection · `FUN_140620960` dispatcher · `FUN_140817230` tanf ·
`FUN_1408d577c` atanf · `FUN_140811cd0` cosf · `FUN_1408121d0` sinf · `DAT_142eefbd8` CRT FMA flag ·
`DAT_142edf560/580` blk/G · `DAT_142ef0ab0/ab8` ctx/cur · ctx slots `+0x1f80ac/+0x1f80ec/+0x1f812c/+0x1f816c`,
composite `+0x1f8200`, near `+0x1f82b0`.
SH4: `loc_8c02e1a4`, `loc_8c02e246`, `loc_8c02e334` (camera), `loc_8c0308c2` (walker), `loc_8C1204F0`,
`loc_8C121100`, `loc_8C121710`, `loc_8C1219B0`, `loc_8C11FF90` (matrix routines).
