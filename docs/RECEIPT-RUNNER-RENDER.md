# RECEIPT-RUNNER-RENDER — the render half of "anchor + inputs -> pixels" (2026-09-03)

*Owner lane: Path B / render. Scope: how the receipt runner's memory (`blk` 0x33B18 + ctx + the 32 MB DC-RAM
image + the two exe pages) becomes pixels through what is ALREADY BUILT (agent harvest -> tape v5 -> `rr-render`
-> WebGPU), and the gates that prove each step. Nothing here modifies code; every claim carries a `file:line`, a
Ghidra address or a gate result, or is marked UNKNOWN. Companion docs: `FRAME-READSET.md` (the frame's read set),
`DETERMINISM-CONTRACT.md` (C1–C9), `RR-RENDER-CRATE.md` (the emitter port), `RENDER-STATUS-2026-09-03.md`
(checkpoint), `WORKSTREAM-CLIENT-REPLAY.md` (plan of record, Track H / G2 / M-interim).*

## RE METHOD (locked, `docs/RE-METHOD.md`)

Steam MvC2 is a static recompilation of the SH4 game; the reference binary is the annotated `marvelous2`
disassembly, the target is the Steam x86-64 exe in Ghidra (`mvc_dump.bin`).

1. **Port the SH4 annotations to the Steam binary by function matching.**
2. **Seed with unique constants, then propagate along the call graph.**
3. **Translate globals through the block map before comparing reference sets.**
4. **Tag CONFIRMED versus INFERRED, and store the pairs as edges in the knowledge graph.**

This document is at **step 4**: it consumes pairs that are already in the graph (seeds 100–111) and specifies
gates. No new function is matched here; where a fact is missing it is written as UNKNOWN, not derived.
Tags: **CONFIRMED** = read on both sides / reproduced by a numeric gate; **INFERRED** = decompile- or
gate-consistent only; **UNKNOWN** = not located.

## 0. The one-paragraph answer

The runner executes `FUN_140118950` (the GGPO tick) once per frame with the two confirmed seat words; that call
IS the whole frame — sim, render dispatch, the sprite walker `FUN_140620f10` and the NaomiLib submit — so after
it returns, `blk` holds every field the agent's tape harvests, in its **post-walk** ("as drawn") state
(`FRAME-READSET.md` §1, §3.6; chain gate 50/50 walker fields, 0/211,736 bytes differ). The same harvest code
that reads the live process (`RetroReceipts-agent/agent/src/reader.rs`: `read_gs_row` :1682, `harvest_objs`
:1998, `harvest_anodes` :1456, the palrows read :2377–2387, `spool_gamestate` :2518) can be pointed at the
runner's memory through the ONE seam every read already goes through (`read_at` :3893 -> `mem::Proc::read`,
`mem.rs:89`), producing a v5 tape row per tick. That tape feeds the built and gated pipeline unchanged:
`rr-render` (L1 90,673/90,673 draws vs Python, L3 60/60 frames byte-exact in the browser,
`RR-RENDER-CRATE.md` §4) -> `FrameRecord` -> `replay.mjs`/`sprite.wgsl`. The master gate is **runner tape ==
live agent tape, section by section**, with three named noise classes on the agent side (sampling phase, torn
rows, rollback last-write-wins) and none on the runner side. What blocks the first END-TO-END GATED pixel is not
render work: it is that **no receipt and Path B capture of the same match exist together yet**
(`FRAME-READSET.md` §0 iv; `DETERMINISM-CONTRACT.md` §6c).

---

## 1. What the runner holds after one tick, and whether the walker runs

### 1.1 The frame function contains the render pass — CONFIRMED by the trace

`FUN_140607d60` (= `*(game_state+0x10)`, set once at `0x140607bef`, `RECEIPT-PLAYER-G.md` "hook point") has
three top-level calls: `FUN_1408441d0`, `FUN_140608a00` (sim) and **`FUN_14060b960` — the render table loop:
`FUN_140620960` dispatcher, `FUN_1406185e0` x2, `FUN_140845130`** (`FRAME-READSET.md` §1). The dispatcher calls
the sprite walker `FUN_140620f10` and the world walkers `FUN_140620740/cd0` (memory `mvc-steam-sprite-walker`,
Ghidra decompile), and the walker appears in the tick's own function table with 90 blk reads / 53 writes
(`FRAME-READSET.md` §3.6). The chain gate (tick -> LayerZ reset -> dispatcher again) reproduces every walker
field bit-exact and changes 0 bytes, i.e. the tick's output already IS the post-walk state (§0 ii).

**Answer to the question in the brief:** the walker is part of the FRAME FUNCTION, not of the shell's render
pass. The shell (`FUN_140039de0`, offline loop) only decides how many ticks to drain (`game_state+0x798`) and
`game_state+0x770` "suppresses rendering on catch-up frames" (`STEAM-GGPO-DETERMINISM.md` §4). **`+0x770` is not
in the tick's read set** (`FRAME-READSET.md` §3.3 lists every game_state address the tick reads: `+0x10, +0x48,
+0x1F0, +0x208, +0x210, +0x214, +0x218..0x224, +0x258..0x264, +0x4F4, +0x520, +0x5DC..0x5EC, +0x80C, +0x828,
+0x82C, +0x838, +0x850, +0x878..0x88C, +0x8C8, +0x964, +0x968`), so that suppression acts downstream of the tick
(INFERRED: in the D3D executor path, which the runner does not have). Consequence: **the runner needs no flag to
make the walker run; every tick writes the "as drawn" fields.** The emitter does NOT have to reproduce the walker.

Caveat (UNKNOWN): the dispatcher's mode comes from `FUN_140619960()` (mode 1 = no sprite walk, memory
`mvc-steam-sprite-walker`); what it reads is not in the docs. It lies inside the carried pages by construction
(the tick reads only blk / game_state page / `0x142edf300` page / ctx / dcram / exe constants, `FRAME-READSET.md`
§3), so a correct anchor carries it — but which byte it is has not been named.

### 1.2 The memory the runner has, by region (`DETERMINISM-CONTRACT.md` C1, C5, C7)

| region | in the receipt? | render-relevant contents |
|---|---|---|
| `blk` 0x33B18 at `*(0x142edf560)` | yes (`battle_anchor`, agent 0.3.47, `reader.rs:2750`) | every harvested field (§2.2); draw lists `0x2F4D0/0x324D0`; System-A list heads `0x2EDE8`; staged palette rows `0x1040..`; camera `0x6908..`; background `0x6CB4..`; the entity table `0x324E0` |
| `game_state` page `0x140ac6d40+0x1000` | yes | pad words `+0x218..` (the inputs), seat map `+0x258`, picks `+0x758`, gates |
| exe page `0x142edf300..0x700` | yes (0x400 B) | `DAT_142edf560/580` blk/G, `DAT_142edf588/590/598` bank POL, **`DAT_142edf628 = blk+0x324E0`**, `0x142edf630..` stage models, `0x142edf543/546` HUD state |
| ctx 4 MB at `*(0x142ef0ab0)` | slot table only (`ctx+0x1e0030`, 0x319C B) | after a tick: TA records `ctx+0x30..0x7EB`, `+0x30030..0x3130B`; decoded texture pages `+0x100030..0x108FC0`; **camera PROJ/VIEW `ctx+0x1f816c/0x1f812c`** (`EMU-GATE.md` §0: 16/16 bit-identical to the bound CB) |
| DC-RAM 32 MB at `ctx+8` | **no** — from a dump / the arc (C5) | PL images `0x0C420000+pos*0x150000` (AFS 209+cid + loader tail), effects bank `0x0D000000` (AFS 799/800), HUD bank `0x0D082000` (835/836), stage POL/TEX `0x0D82D000/0x0D85D000`; the per-frame tile table `0x0CE60000` (rebuilt by the tick) |
| exe image | the user's / our image | constants; static part lists (list 0xC) |

⚠ The DC-RAM image is the runner input that is NOT in the receipt: the PL loader table is UNKNOWN
(`FRAME-READSET.md` §5), so today it comes from `dump_live.py` (`d3dcap/ttd/dump_live.py`) or a per-character
dump-once cache (C5). Everything in §3 that says "read from the runner" assumes this image is present.

---

## 2. Step 1 — the tape as a function of the runner's memory

### 2.1 Where the harvest code is, and its one seam

All game-memory reads in the agent go through `reader.rs read_at(h, addr, len)` (:3893) -> `read_at_raw` (:3904)
-> `mem::Proc::read` (`mem.rs:89` Windows RPM, `:319` Linux `process_vm_readv`). `reader.rs:20`: "ALL
game-memory reads/region-walks + pid/module-base lookups go through this." The 0.3.43 block snapshot
(`BLK_SNAP`, `reader.rs:3887–3901`, installed by `snap_install` at :2342/2361/2375) is already an in-memory
slice served through the same `read_at` — i.e. the harvest ALREADY runs against a byte buffer for the blk part,
with RPM only for pointers that leave the block (exe globals, `node+0xA0` objects, `H+0x1B8` palettes).

Two ways to make the runner produce the tape with the SAME code (no third implementation):

| option | mechanism | what it needs | verdict |
|---|---|---|---|
| A. Attach the agent reader to the runner process | RPM against a process that keeps C1 (`*(exe+0xAC6EF0)` -> blk, exe image at `0x140000000`) | the runner to be a real process with the exe image mapped; bypassing the gamestate thread's live gating (both teams alive, `SHARE_GAMEPLAY`, the 0.5 ms clock-edge poll `reader.rs:2453–2462`, torn-list retries :2350–2378) | works for a G-style runner (real game process) with no code change; the poll/retry machinery is dead weight and the sampling is still asynchronous |
| **B. Share the harvest as a library** | the harvest functions take `h: &mem::Proc` and call `read_at`; give `read_at` a second backend over the runner's slices (blk, game_state page, exe page, ctx, dcram) and call `read_gs_row` + `harvest_objs` + `harvest_anodes` + the palrows read + `spool_gamestate`'s encoders synchronously after each `FUN_140118950` returns | a `MemRead` boundary at `read_at`; the runner exposes its regions; `exe_base = 0x140000000` | **the master-gate form**: sampling is deterministic (post-tick), no torn/held rows, no caps needed |

Both are specification only (this doc changes no code). B is what `WORKSTREAM-CLIENT-REPLAY.md` §2 already
names ("tape codec shared with the agent's encoder", `rr-render` in the agent workspace).

### 2.2 Every tape field and where the runner gets it

Row columns = `GS_SCHEMA` (`reader.rs:1239`), read in `read_gs_row` (:1682–1810). `cl = blk+0x3F24+i*0x738`
(the legacy window), `H = blk+0x3DB8+i*0x738` (true object base, `OBJ_BACK` :78–79). "W" = written by the walker
`FUN_140620f10` during the render pass (`TAPE-V3-SPEC.md` §10.1; the runner has it post-tick, the live agent may
read it one frame stale — §2.3).

| column(s) | live source (`reader.rs`) | runner region | note |
|---|---|---|---|
| `frame` | `blk+0x3CC8` (:270) | blk | the clock; +1 per tick (gate iii) |
| `p1_in/p2_in` | `cl+0x4FC` (:51 OFF_INPUT) | blk | derived from the pads by `FUN_140048630` |
| `kcode`, `seat_in[2]` | `exe+0xAC6F58` = `game_state+0x218/+0x21C` (:234–235) | game_state page | **in the runner these are the INJECTED inputs** (C2) |
| `hp[6]`, `red_hp[6]` | `cl+0x40C`, `cl+0x410` (:55, :58) | blk | |
| `px/py/vx/vy[6]` | `H+0x50/0x54/0x78/0x7C` (:80–83) | blk | sim |
| `p1_meter/p2_meter/meter_fill/p2_meter_fill` | array base `+0x2E636/+0x2E658` (:218–219) | blk | |
| `combo_dealt[6]` (`combo_recv` = zeros) | `cl+0x1CA` (:51) | blk | |
| `facing[6]` | `H+0x154` (:84) | blk | **W** |
| `hitstun[6]` | `cl+0x1D1` (:52) | blk | |
| `drawn[6]` | `H+0x170` (:85) | blk | the draw gate, written at registration and re-checked by the walker |
| `sid[6]`, `atimer[6]` | `H+0x188`, `H+0x186` (:87–88) | blk | |
| `eyeX/eyeY/zoom/ground` | `blk+0x6914/0x6918/0x691C/0x6998` (:100–102) | blk | |
| `sx/sy/zx/zy[6]` | `H+0x124/0x128/0x130/0x134` (:93–96) | blk | **W** |
| `flash[6]`, `glow[6]` | `H+0x172`, `H+0x5C` (:98–99) | blk | |
| `layer[6]` | draw-list walk `blk+0x2F4D0 + L*0x300`, counts `0x324D0` (:139–143) | blk | |
| `timer`, `round_no` | array base `+0x2E61C`, `+0x2E617` (:223, :221) | blk | |
| `cam_state/look[3]/fov/yoff/roll` | `blk+0x6908/0x695C/0x6974/0x6988/0x698C` (:103–104) | blk | |
| `deck[3]`, `blackout` | `blk+0x6CA8`, `blk+0x3D50` (:105–106) | blk | |
| `bg_mode/bg_col[3]/fade_mode/fade_col` | `blk+0x6CB4/0x6CB8..0x6CC0/0x6CE4/0x6CF0` (:126–127) | blk | |
| `bg_gate[0..3]` | `blk+0x3CB8+0/1/2/0x2E` (:1738) | blk | |
| `bg_gate[4..5]` | `entity+6`, `entity+0x96`, `entity = *(exe+0x2EDF628)` (:128, :1741–1747) | exe page -> blk | **relocation:** `DAT_142edf628 = blk+0x324E0` (`DETERMINISM-CONTRACT.md` §1.1), so these are `blk+0x324E6` / `blk+0x32576` |
| **`nodes`** (stride 54, `nodes_enc` :2784) | `harvest_objs` :1998: handles `blk+0x2F4D0..`, per node `H+0x03/0x4D/0x38/0x154/0x28/0x170/0x188/0x172/0x5C/0x186/0x130/0x134/0x124/0x128/0x12C/0x1A8/0x1B0/0x148/0x178` | blk | order = the walker's (layer 0..15, index) — identical in the runner |
| `nodes.pal` -> `pals` | `read_pal(*(H+0x1B8))` :1981 — 32 B at a HOST pointer into the PL image | dcram | pointer is host-absolute: relocate by `Δ_dcram` (C1) |
| `nodes.owner_off` | `*(H+0x28) − blk` (:2074) | blk | |
| **`anodes`** (stride 100, `anodes_enc` :2782) | `harvest_anodes` :1456: heads `blk+0x2EDE8 + L*8`, L = 5..13, next `+0x10`, fields `+0x170/+0xF0/+0xA8/+0x94/+0x90/+0xE8/+0xA0` | blk | cap `ANODES_CAP_PER_FRAME = 96` (:1446) — the runner needs no cap (§4 HUD) |
| `anodes.model` | `*(node+0xE8)` raw u64 (:1432) | pointer into dcram | **host-absolute value** — differs between processes; a comparison must normalise to the DC address (`host − dcram_base + 0x0C000000`); the emitter's use of the raw value is a gate item (§2.4) |
| **`aobjs`** | bytes at `*(node+0xA0)`: 0x18 header + records (0x50 header + payload while PCW < 0), interned by FNV-1a (:1470–1500, :2395–2403) | dcram (INFERRED) | the dispatcher's read set is blk + dcram + exe + ctx only (`FRAME-READSET.md` §3, render column) and "nothing on the tick path points into a Windows heap" (`DETERMINISM-CONTRACT.md` §1.1b) — on the traced 5-node frame. Stage props: `node+0xA0 = PTR_DAT_142edf588[i]` -> DC POL (`STAGE-DRAW-GHIDRA.md`:18). UNKNOWN for HUD/effect-heavy frames until traced |
| **`palrows`** (`palrows_enc` :2775) | one 0x540-B read at `blk+0x13C0` (:160–164, :2379–2387): 48 x (16 x u16 ARGB4444 @`+0x18`, flag @`+8`) | blk | |
| `confirmed_in` | GGPO ring `*(exe+0x2E10B98) -> +0x9F0 -> +0x190`, `harvest_confirmed_in` :1931 | — | **the runner's INPUT**, not an output; equal by construction |
| `battle_anchor` | blk + game_state page + exe page + ctx slots at one clock edge (:2244–2270) | — | the runner's initial state |
| `objs` (legacy 32-B), `calib`, `fighter_bases` | derived from the same walk (:2578–2611) | blk | back-compat streams; same encoders |

Everything the tape carries is therefore in blk, the two exe pages, or dcram (through relocated pointers). No
field depends on the D3D device, the swap chain or Steam. Two fields carry HOST POINTER VALUES (`anodes.model`,
and `nodes.gfx1/gfx2` = `*(H+0x1A8)/*(H+0x1B0)`, :2050–2051) and will differ numerically between the live process
and the runner even when the game state is identical; §2.4 treats them as keys to be normalised, not bytes to
be equal.

### 2.3 Where the live agent tape and the runner tape will legitimately differ

These are properties of the LIVE capture, all measured or documented; the runner has none of them. The master
gate must attribute each difference to one of these classes or fail.

| class | live agent behaviour | evidence | runner |
|---|---|---|---|
| **P — sampling phase** | the gamestate thread polls `blk+0x3CC8` and reads when it ticks (`reader.rs:2453–2462`); the walker writes `+0x124/+0x128/…` later in the same frame, so an edge read can precede the write | first v4 tape: 3.9% of moving-fighter rows carried the PREVIOUS placement (`reader.rs:2266–2270`, `phase_check.py`); the 1 ms `timeBeginPeriod` fix reduced, not removed, it | reads after `FUN_140118950` returns -> always post-walk (= the shim's `"at":"walk"` dump, `dllmain.cpp:741–752`) |
| **T — torn / held rows** | draw-list rebuild mid-read -> stub or partial lists; retried and stability-checked (:2350–2378); the emitter HOLDS the previous frame's nodes on a torn row (`sprites.rs:151–156`) | 88 torn + 30 empty of 5,619 frames on the first v5 tape; "~1%" on 0.3.45 (`RENDER-STATUS-2026-09-03.md`) | none |
| **R — rollback last-write-wins** | rows keyed by clock; a GGPO rollback re-visits frames and the later read overwrites (:2324–2340); bursts that complete between two polls keep the PREDICTED row | `seat_in` = `G+0x218` = the predicted latch (memory `rr-ggpo-input-ring`); `rollbacks` counter in the envelope | pure confirmed-forward from `confirmed_in`; rows where the live tape kept a prediction WILL differ (px/py/hp and everything downstream) — that is the receipt doing its job |
| **C — caps** | `ANODES_CAP_PER_FRAME 96` (:1446), `OBJS_CAP_PER_FRAME 64` (:145), object bytes 128 KB / 128 records (:1442–1443) | 77 HUD nodes seen on one frame (`PARTS-LIST0C-GHIDRA.md` §5) | no caps |
| **K — host pointers** | `anodes.model`, `nodes.gfx1/gfx2`, `pal` pointer resolution | by construction | different values, same targets after relocation |
| **L — LUT lag** | `palrows` carry the STAGED rows + flags; the bound LUT lags by >= 1 frame (`PALETTE-SOURCE-GHIDRA.md`: 494/518, 24 misses = lag) | gated | identical staging bytes; the lag is a consumer rule (`--pal-lag`, `tape_to_seq.py:593–596`) either way |

### 2.4 The master gate — runner tape == live agent tape, section by section

Inputs: one match recorded by agent 0.3.47 (tape with `battle_anchor`, `confirmed_in`, all v5 sections) and the
runner's tape produced from that receipt by the shared harvest (§2.1 B). Compare per clock value on the
intersection of frames; report the frames present on one side only (class T on the agent side; none expected on
the runner side).

| section | equality rule | tolerance | tool basis |
|---|---|---|---|
| `frames` rows | every column bit-equal (f32 by bit pattern, `receipt_gate.py f32eq`) | none on sim columns; walker columns (`sx/sy/zx/zy/facing[6]`) may differ on class-P rows — a P row is one whose live `sx/sy` equal the runner's PREVIOUS frame | `receipt_gate.py compare` (px/py/hp/clock today) extended to all columns |
| `nodes` | same count, same order, every field equal | class P on `fsx/fsy/depth/angle/hotx/hoty/face/zx/zy`; class K on `gfx1/gfx2` (compare as `(host − dcram_base)`); `pal` compared as the 32 resolved bytes | `tape_vs_dump_gate.py tape_nodes` (already decodes the record) + `blkstate.nodes` on the runner blk |
| `anodes` | per list: same count, same order; `flags/matrix/colour/alpha` bit-equal; `obj` compared by the CONTENT HASH of the interned object, not the index; `model` normalised to DC address | class C: the live list may be truncated at 96 — report "runner has N more nodes in list L" | `blkstate.anodes` on the runner blk + the tape decoder |
| `aobjs` | the set of interned object contents of the live tape is a SUBSET of the runner's (caps) and equal where both exist | class C | FNV-1a / sha over bytes |
| `palrows` | 48 rows x 32 B + 48 flags equal per frame | none | `tape_vs_dump_gate.py tape_palrows` |
| `pals` | as sets of 32-B rows | none (interning order may differ) | |
| `confirmed_in` | equal to the inputs the runner was fed | none — by construction | `receipt_gate.py` job |
| envelope | `stage_id`, `p1_team/p2_team`, `costume`, `build_id` equal | none | |

The gate PASSES when every difference is attributed to P, T, R, C or K and the runner side has no unattributed
difference. `tape_vs_dump_gate.py` (W0, `d3dcap/replay/tape_vs_dump_gate.py`) already implements the shape of
this comparison against the shim's post-walk dumps — the runner's post-tick blk IS such a dump, so the runner
version is that tool with the dump replaced by the runner's block. Not yet run on any pair (no same-match tape +
dump exists: `FRAME-READSET.md` §0 iv, `DETERMINISM-CONTRACT.md` §6c).

Two emitter-side items this gate will surface, to be settled before the numbers are read:
1. **`anodes.model` as a key.** `rr-render` decodes it as `u64` (`tape.rs` `ANode.model`) and `world.rs
   complete_prop` uses object contents + the stage rip; whether any consumer keys on the raw pointer VALUE is not
   established here (UNKNOWN). If one does, a runner tape from another process address space breaks it, and the
   fix is a DC-address key.
2. **`nodes.gfx1`** is used by the emitter to resolve ownerless objects to a slot (`sprites.rs:169–178`,
   `bank_slot`); the value is a host pointer. Same normalisation.

---

## 3. Step 2 — the existing pipeline on a runner tape, and the full-match pixel gate

### 3.1 What applies unchanged

| gate | what it proves | applies to a runner tape? |
|---|---|---|
| **L1/L2** `tools/gate_l1.sh` + `seq_diff.py` (`RR-RENDER-CRATE.md` §4: 90,673/90,673 draws, six clips) | `rr-render` == `tape_to_seq.py` per draw (state, indices, vertex bytes, CB bytes, texture bytes) | yes — a runner tape is a v5 envelope; the gate is tape-agnostic |
| **L3** `tools/gate_l3.mjs` (60/60 frames byte-exact, scene RT readback) | browser pixels from the wasm feed == pixels from the Python `.seq` | yes, unchanged |
| capture gates `v3gate/rotgate/emitter_gate` (sprites), `tsp_gate`, `worldgeo_gate`, `sort_gate`, `palette_gate`, `bg_gate`, `parts_gate` | each derived RULE against a Path B frame's own draws | yes — they gate rules, not tapes; a runner tape does not change them |
| `emu_gate.py camera/walker/frame` | the game's routines reproduce captured bytes | this IS the runner in p-code form (7.4–8.3 s/frame, `FRAME-READSET.md` §0) |
| `receipt_gate.py` (selftest 20/20 clock/px/py/hp) | the tick regenerates the tape's sim columns | the sim half of §2.4 |

### 3.2 The full-match pixel gate: receipt -> runner -> tape -> `rr-render` -> scene RT vs Path B

W0 exists in shape (`tape_vs_dump_gate.py`) but needs a guided capture; the pixel form needs one more thing —
the SAME match on both sides. Specification:

**Inputs (one session, one match):**
1. Agent 0.3.47 running (`rr-agent-v21.exe`): tape with `battle_anchor` (+ `battle_anchor_blk/ctx/dcram`,
   `reader.rs:2747–2750`) and `confirmed_in`.
2. The capture shim in the same game (`session-guided.ps1`, `D3DCAP_MANUAL=1`): bursts with walker-hook state
   dumps (`state_<f>.json` carries `"clock"`, e.g. `{"frame":12427,"clock":10903,...}`, and the exact `base`),
   `blk_<f>_full/delta.bin`, `alist_<f>.bin`, and the scene RT at first/middle/last frame of each burst
   (`capgate/scene_<f>_2048x1024_f87.bmp`; Path B trap 10: three points, never one).
3. A DC-RAM image of that session (`dump_live.py`) — the runner's C5 input until the PL loader is derived.

**Alignment:** runner frame k has clock `anchor_frame + k` (`blk+0x3CC8`); a capture frame f has
`state_f.json["clock"]`. Compare where clocks are equal. (Rollback: the runner follows `confirmed_in`; a capture
frame Steam later rolled back has a clock that repeats — take the LAST occurrence, as GGPO did.)

**Ladder, each numeric:**
1. **Sim gate** — `receipt_gate.py --run <dump> --tape <tape>`: `px/py/hp/clock` exact every frame (f32 bits).
   Fails -> stop; the runner is not the match.
2. **State gate** — runner blk vs `blk_<f>_full.bin` at equal clock: `blkstate.nodes/anodes/pnodes` fields
   equal (this is `emu_gate.py frame --target chain` with a real second side).
3. **Tape gate** — §2.4 against the agent's tape.
4. **Draw-list gate** — `rr-render emit_seq` on the runner tape vs the capture's `frame_<f>.pack` draws:
   sprites through `v3gate.py --emitter rust` (`RR-RENDER-CRATE.md` §6.4, not yet wired), world through
   `tsp_gate` / `sort_gate` on the emitted list.
5. **Pixel gate** — render the runner tape in the player (`gate_l3.mjs` mechanics: `__rr.show(i)`,
   `__rr.readback()` = raw BGRA scene target) and diff against `scene_<f>.bmp` over the 1280x960 viewport with
   the Path B instruments, in this order and never fused: `verify_alpha.py` coverage (missing / spurious px),
   then `verify_frame.py` colour (mean |delta| per channel, % differing at >1 LSB, per-draw attribution
   `FOCUS=<draw>`). Report per frame like Path B (`0 / 0 missing-spurious, 0.011–0.018% differing`) and per burst.

**Expected reading:** Path B's own replay of Steam's draws sits at 0.011–0.018% differing; the emitter path
carries the derived-rule residuals of §4 (portraits capture-derived, combo counter absent, 12 bit-6 strips,
LUT lag), so the first full-match number WILL be above Path B's, and the per-draw scoreboard is what turns it
into a list. That is the value of this gate: it is the only one that measures the emitter against Steam on
frames the emitter never saw.

### 3.3 An alternative render input the runner exposes (for the record, UNKNOWN scope)

After a tick the ctx holds what the submit wrote: TA/polygon records at `ctx+0x30..0x7EB` and
`+0x30030..0x3130B` (`FUN_1408436a0`, 213 calls/frame) and the decoded texture pages at `ctx+0x100030..0x108FC0`
(36,752 B, `FRAME-READSET.md` §3.4). For System-A objects "those vertices are exactly the vertices in Steam's
vertex buffer for the draw (checked live)" (`TAPE-V3-SPEC.md` §9). Rendering FROM ctx would bypass the emitter's
world-pass derivations (it is the "scope the emitter" question, D2, from the other side). Not built, not gated;
the sprite records' layout in ctx and the record->draw-state mapping are UNKNOWN here. Recorded so it is not
re-discovered; the plan of record stays tape -> `rr-render`.

---

## 4. Step 3 — residuals that block "pixel perfect" regardless of the runner

For each: status, anchor, and whether the runner makes it easier (state available every frame, no tape field).

| residual | status today | Ghidra / gate anchor | with the runner |
|---|---|---|---|
| **Portraits TCW 0xC99..0xCA8** | capture-derived pages (`tcw_pages/`, 73 entries); derivation from the character DAT INFERRED, not gated (`TEXTURE-BANKS-GHIDRA.md` §6, §7.4) | writers CONFIRMED: `FUN_14060d560` at match load copies 0x800-B RGB565 pages from DC `0x0CE60000+k*0x800` into `texHdr[10+DAT_140a6aac8[s]].loc` / `[16+…]` of the HUD bank (`0xC9A..0xC9F` P1/P2 C1..C3, `0xCA0..0xCA5` alt set); `FUN_1406162e0` / `FUN_140616330` re-upload `0xC99` / `(*(fighter+0x230)>>1)+0xCA6` | **EASIER — the pixels are in the runner's DC-RAM image.** The HUD bank TEX lives at DC `0x0D099000` (0x1E000 B, `TEXTURE-BANKS-GHIDRA.md` table); records 9..24 have `loc >= 0x1E000`, i.e. the patched pages sit right after the file in DC-RAM, written at match load — BEFORE the battle-frame anchor. A post-match-load DC-RAM image therefore already holds them; read `texHdr[k].loc` and take 0x800 B. No `cid -> page` rule needed (the rule remains the gate that the pages are DAT-derived). INFERRED: the destination address arithmetic (`TEX base + loc`) is from the header semantics, not re-read for this doc |
| **Combo counter / rating text (list 0xC)** | rule CONFIRMED and gated (`parts_gate.py`: CBWorld 24/24, vertices 82/82, pages 82/82 on 5 frames); **not in any agent** (`grep pnodes reader.rs` = 0) and **not in the emitter** (`grep pnodes tape_to_seq.py` = 0) | `FUN_140653a70` <-> `loc_8C0F215E`; node -> exe-static part list `+0x110/+0x118` -> HUD-bank model `PTR_DAT_142edf598[idx]`, page `0xC92+count−1`; 44-B `pnodes` record spec `PARTS-LIST0C-GHIDRA.md` §5 | **EASIER — no tape field:** `blkstate.pnodes(blk, base)` (`blkstate.py:321`) reads the list-12 nodes straight from a block; the runner has the block every frame and the exe image for the static lists. What remains is the same either way: port the `parts_gate.py` rule into the emitter (`world.rs`). The sampling caveat of §5 (callback pass rewrites `+0x50.x`/`+0x228` before the render) is moot post-tick |
| **Scripted camera (`blk+0x6908 == 1`)** | fields carried (`cam_state/look/fov/yoff/roll`, 0.3.39); renderer not yet (`RENDER-STATUS` item 6) | state machine `FUN_14061ca70`; keyframes `FUN_14061c0a0` + orbits `FUN_14061ae80/b8e0` writing roll `0x698C` (`WORLD-CAMERA-GHIDRA.md` §5) | **EASIER — the game's own P/V are bytes in ctx after the tick:** PROJ `ctx+0x1f816c`, VIEW `ctx+0x1f812c` (`EMU-GATE.md` §0: 16/16 bit-identical to CB `7793F141`; x0.1 and HUD blocks likewise). The runner can ship the CB bytes instead of a closed form for every camera state. CONFIRMED on fight-camera frames; the scripted case is INFERRED until a scripted frame is gated |
| **LUT lag (M7)** | 494/518 LUT pages; 24 misses = one texture holding the previous frame's bank content (`PALETTE-SOURCE-GHIDRA.md` §… "4505 residual is the LUT lag", INFERRED mechanism, CONFIRMED effect); emitter knob `--pal-lag` (`tape_to_seq.py:593`) default 0 | staging lines `blk+0x1040+bank*0x38`, flag `+8` (1 raw / 2 dim / 0 uploaded), per-frame upload `FUN_140613390` to host PALETTE_RAM `dev+0xd8d04` | **neutral.** The runner has identical staging bytes and flags every frame (no torn palrows), so the lag can be modelled exactly from the flag transitions; but `dev+0xd8d04` is a D3D-side buffer the runner does not have, so the bound-LUT truth stays a capture quantity. Gate unchanged (`palette_gate.py`) |
| **Post chain / bloom (D-post, M1)** | OPEN owner decision; every gate is pre-bloom; the user sees the 9-pass chain incl. a BORDER sampler WebGPU lacks (`WORKSTREAM-CLIENT-REPLAY.md` §3 D-post) | executor `FUN_1402B6F30`; passes captured in every `.pack` (scene RT -> 1280x768) | **neutral.** The runner has no D3D; the post chain is not in the frame function. Recommendation of record stands: ship pre-bloom v1, gate the chain separately |
| **12 bit-6 strips** | winding 442/454; the 12 misses are bit-6 5-vertex strips (`0x72`, `0xF2`) whose captured VB order is `(v0, v2, v1, v4, v3)`; "the consumer that reorders them is not identified" (`TSP-RENDER-STATE-GHIDRA.md` §5) | `FUN_1408482a0` strip loop | **possibly EASIER:** the reordered vertices are what the submit writes into the ctx TA records (§3.3), so a runner can READ the order it cannot yet derive. INFERRED; requires locating those records in ctx (UNKNOWN) |
| **HUD list-0xB coverage** | HUD = System-A list 11 nodes in `anodes` (`harvest_anodes` walks 5..=13); projection gated 171/177 gold list-11 draws (`RENDER-STATUS` table); HUD bank pages 16/16 byte-exact from AFS 835/836 (`TEXTURE-BANKS-GHIDRA.md`, supersedes the 2026-08-29 note "UI bank not offline-extractable" in memory `mvc-hud-list0b-live-re`); **but** the 96-node cap is shared with lists 5..9 walked first, and 77 HUD nodes were seen on one frame (`PARTS-LIST0C-GHIDRA.md` §5) — truncation risk INFERRED, not measured | heads `blk+0x2EDE8+L*8`, next `+0x10` (dispatcher decompile, memory `mvc-steam-sprite-walker`); `FUN_14061d5b0` HUD block | **EASIER:** no cap; every list-11 node read from blk each frame. The 6/177 unexplained gold draws remain a rule question, not a data one |
| **Torn / held frames (~1%)** | agent-side (`RENDER-STATUS` "torn frames ~1%") | `reader.rs:2350–2378` | **GONE** by construction |
| **Hit sparks (RE-C3)** | bank key fixed (56617e6), verify on the stage-13 clip | — | neutral |
| **Frame background** | rule CONFIRMED + gated (`bg_gate.py` 9/9 quads, 2/2 scene-RT pixels; colour path decompile-only, all gated stages black) | `FUN_1406101b0 == loc_8c02dc4c`; entity gates via `DAT_142edf628+6/+0x96` | neutral; the entity pointer resolves to `blk+0x324E0` in the runner (§2.2) |
| **PL loader table** | UNKNOWN (`FRAME-READSET.md` §5) | `0x0C420000 + pos*0x150000` = AFS `209+cid` + loader tail (six of six byte-exact, `DETERMINISM-CONTRACT.md` §6c) | **a runner PREREQUISITE, not a render residual:** until derived, the DC-RAM image is a dump (per session or per character) |

---

## 5. Step 4 — client cost: what a phone receives

### 5.1 The two client shapes

With inputs-only receipts a client either runs the frame function itself or receives emitted frames:

* **Native host (G / G2):** the user's own unpacked image + our loader/recipe (`WORKSTREAM-CLIENT-REPLAY.md`
  §4 G2/G3, BYOR). Then the client runs runner -> harvest -> `rr-render` locally; nothing streams but the
  receipt (~8 B/frame: two 24-bit seat words, `FRAME-READSET.md` §5). Not built (the p-code harness is the only
  runner today).
* **Browser / phone (M-interim, DECIDED):** a server-side runner emits, the phone renders. The browser cannot run
  the frame function (G3 = translated game code on the client = a licensed product, §4 G3). What crosses the
  wire is the question below.

### 5.2 The stream format today and its measured size

`FrameRecord v1` (`rr-render/src/feed.rs:6–17`):

```
"RRFR" u32 ver=1  i64 frame_clock
u32 n_states   { u32 id, u32 len, json }                          first use only
u32 n_textures { u32 id, u32 w, u32 h, u32 fmt, u32 len, bytes }  first use only (fmt 61 R8 index, 28 RGBA)
u32 n_cbs      { u32 id, u32 len, bytes }                          by content hash, first use only
u32 vb_len bytes   u32 ib_len bytes
u32 n_draws    { u32 state, firstIndex, indexCount, stride, voff, i32 tex0, tex1, vscb[4], pscb[4] }   60 B/draw
```

Measured on the stage-13 clip: **719 KB/frame average, 409 draws** (`RR-RENDER-CRATE.md` §3); "~464 KB of it is
the arc deck re-emitted per frame exactly as the Python does". Section composition of the same clip
(`WORKSTREAM-CLIENT-REPLAY.review-render.md` §3.1, parsed seq heads): VB 547 KB avg (stride 40), IB 55 KB, draws
avg 393 / max 476, of which frame 2843 = 321 `vs_world|opaque` deck draws (11,898 indices, 11,877 verts) + 73
`vs_world|texalpha` (2,277 indices) + 35 `vs_flat|indexed` sprites (210 indices); 1,665 distinct textures over
300 frames (6.5 MB, sent once); CBs one CBWorld per world node per frame.

### 5.3 What to strip, and the floor each step reaches

| tier | content | per frame | basis | tag |
|---|---|---|---|---|
| D (today) | FrameRecord v1 as measured | **719 KB** | measured (`RR-RENDER-CRATE.md` §3) | CONFIRMED |
| C | v1 minus the deck: deck VB (~464 KB), deck IB (11,898 idx x 4 B = 47.6 KB) and its ~321 draws (19 KB) sent ONCE per stage as a static buffer | ~547−464 = 83 KB VB + ~7 KB IB + ~6 KB draws + CBs (~20 world nodes x ~56 B) + amortised textures ≈ **~100 KB** | arithmetic on the measured sections; not measured post-strip | INFERRED |
| B | keyed frames (W5 / M-interim wire): sprites as node records (54 B x ~10), world nodes as key + matrix + colour + UV cell (132 B x ~80, `TAPE-V3-SPEC.md` §9.5), rows; the phone builds VB/IB from the pack | **~20–50 KB** | `WORKSTREAM-CLIENT-REPLAY.md` §3 M-interim estimate | INFERRED |
| A | the TAPE itself + the wasm emitter on the device | **0.5–0.9 KB/frame** (1.8–3.1 MB/min gz measured on two matches, `RENDER-STATUS` "Tape size") + a 21 MB pack per match cached (`RR-RENDER-CRATE.md` §3) | measured tape sizes; emitter cost 27.8 ms/frame avg on one desktop worker (L3 run) — **phone UNKNOWN** | sizes CONFIRMED, phone feasibility UNKNOWN |

Reading: tier C is 6 MB/s at 60 fps — above what the pub/sub path was sized for (§3 M-interim: 12 MB/s
"too much for a queue", keyed 1–3 MB/s "fine on wifi, marginal on cellular"). Tier B is the decided wire; tier B
IS `rr-render`'s emitter input, so "keyed frame" and "tape frame" converge on the same records — the difference
is only whether the server or the phone runs the emitter. Tier A is the byte floor and is what the runner's
harvest produces natively; whether a phone emits at 60 fps is the one unmeasured number (review-render §3.2
target "≤ 2 ms/frame" INFERRED; desktop wasm measured 27.8 ms).

Two changes that make tier C are already specified with exact gates (`review-render` §3.3): the static deck VB
(gate: draw-list equality after normalising `firstIndex` per buffer + pixel equality) and one R8 index atlas per
character (gate: pixel equality vs the per-part build on the 300 stage-13 frames).

### 5.4 The byte-exact gate for `stream == local`

`FrameRecord` bytes are a deterministic function of (tape bytes, pack bytes, `EmitOpts`, emission ORDER):
state ids, texture ids and CB ids are assigned on first use in sequence (`feed.rs state_id` / `cb_id` /
`tex_sent`), so two emitters that start at frame 0 and emit in order produce identical bytes.

* **L5 (server emit == client emit):** per-frame `sha256(FrameRecord)` from the server-side emitter vs a local
  emitter on the same tape + pack, both from frame 0 in order. Any byte differs -> fail with the frame index.
* **L5' (pixels):** the `gate_l3.mjs` readback — `sha256` of the raw BGRA scene target after `__rr.show(i)` —
  streamed vs local. Order-independent, so it is the gate for a subscriber that joins mid-match.
* **Keyframe re-sync constraint:** a subscriber joining at a keyframe (one full frame every 60, §3 M-interim)
  has not seen the earlier first-use tables; with sequential ids its FrameRecords cannot be byte-equal to a
  from-zero client's. Either the keyframe re-sends all live tables (ids preserved) or ids become content hashes
  (CBs already are internally: `cb_ids` keyed by hash string). Gate for either: L5' equality between a
  from-zero client and a join-at-keyframe client on the same frames.

---

## 6. Step 5 — CONFIRMED / INFERRED / UNKNOWN, and the shortest path to the first pixel

### 6.1 Ledger

| claim | tag | evidence |
|---|---|---|
| `FUN_140118950` -> `FUN_140607d60` runs sim + render dispatch + walker + submit; the post-tick blk is the post-walk state | CONFIRMED | `FRAME-READSET.md` §1, §3.6; chain gate 50/50, 0 bytes differ |
| The runner needs no flag to make the walker run (`game_state+0x770` is outside the tick's read set) | INFERRED | `FRAME-READSET.md` §3.3 read list; `STEAM-GGPO-DETERMINISM.md` §4 |
| Every tape field is in blk / the two exe pages / dcram via relocated pointers (§2.2) | CONFIRMED for blk/exe-page fields (offsets in `reader.rs`); INFERRED for `aobjs` objects living in dcram (trace of a 5-node frame; C1 "no Windows heap on the tick path") | `reader.rs` constants; `FRAME-READSET.md` §3 render column; `DETERMINISM-CONTRACT.md` §1.1b |
| `DAT_142edf628 = blk+0x324E0` (entity list -> `bg_gate[4..5]` are blk bytes in the runner) | CONFIRMED | `DETERMINISM-CONTRACT.md` §1.1 |
| The agent harvest has one memory seam (`read_at` -> `mem::Proc::read`) and already runs against a blk slice | CONFIRMED | `reader.rs:20, :3887–3906`; `mem.rs:89/319` |
| Live-tape noise classes P/T/R/C/K/L exist and are attributable | CONFIRMED (P measured 3.9%; T 88+30/5,619 and ~1%; R by design; C by constants; L 24/518) | `reader.rs:2266–2270, :2350–2378`; `RENDER-STATUS`; `PALETTE-SOURCE-GHIDRA.md` |
| L1/L3/capture gates apply to a runner tape unchanged | CONFIRMED (they are tape-agnostic by construction) | `RR-RENDER-CRATE.md` §4; tool headers |
| Camera P/V readable from `ctx+0x1f816c/0x1f812c` post-tick | CONFIRMED on fight-camera frames; INFERRED for scripted | `EMU-GATE.md` §0 |
| Portrait pages present in a post-match-load DC-RAM image at `HUD TEX base + loc` | INFERRED | `TEXTURE-BANKS-GHIDRA.md` §6 writers CONFIRMED; destination arithmetic not re-read |
| Combo counter renderable from blk with no tape field | CONFIRMED rule (`parts_gate.py` 24/24, 82/82); emitter port not done | `PARTS-LIST0C-GHIDRA.md`; `blkstate.py:321` |
| FrameRecord 719 KB/frame; tape 1.8–3.1 MB/min | CONFIRMED | `RR-RENDER-CRATE.md` §3; `RENDER-STATUS` |
| Tier C ~100 KB, tier B 20–50 KB | INFERRED (arithmetic / plan estimate) | §5.3 |
| Phone can run the wasm emitter at 60 fps | UNKNOWN | desktop 27.8 ms/frame measured |
| Which byte `FUN_140619960()` reads for the dispatcher mode | UNKNOWN | inside the carried pages by the read-set argument |
| Polygon-list objects of HUD/effect-heavy frames all inside blk/dcram/ctx | UNKNOWN (traced frame had 5 nodes) | trace a super frame |
| `anodes.model` / `nodes.gfx1` used as raw-pointer keys anywhere in the emitter | UNKNOWN | §2.4 items 1–2 |
| PL loader table (the DC-RAM image without a dump) | UNKNOWN | `FRAME-READSET.md` §5 |
| A same-match receipt + Path B capture pair | DOES NOT EXIST | `FRAME-READSET.md` §0 iv; `DETERMINISM-CONTRACT.md` §6c |

### 6.2 Shortest path to the first end-to-end pixel from a receipt (ordered; a gate per step)

Every tool named exists; the steps are ordering and one converter extension. No durations.

1. **Produce the pair.** One guided session with agent 0.3.47 AND the shim in the same game
   (`d3dcap/session-guided.ps1` with the agent up), plus `dump_live.py` during the match for the DC-RAM image.
   Yields: tape (`battle_anchor`, `confirmed_in`, v5 sections), walker-hook dumps with clocks, scene RT bmps at
   three points per burst, DC-RAM. **Gate:** `receipt_gate.py --run <dump> --tape <tape>` — `px/py/hp/clock`
   exact per frame. This is the step nothing else can precede.
2. **Tick the receipt.** Today's runner is the p-code harness: `emu_gate.py frame` / `determinism_gate.py
   multitick --ticks N` writes a blk per tick (`%TEMP%\rrcap_emu\<tag>.blk_tNN.bin`) and post-run ctx / gs /
   tiletab dumps (`emu_frame.py:170, :228–233`). **Gate:** step-2 of §3.2 — runner blk vs `blk_<f>_full.bin` at
   equal clock through `blkstate.nodes/anodes/pnodes`.
3. **Block -> tape.** `states_to_tape.py` (`d3dcap/replay/states_to_tape.py`) already turns a burst of state
   dumps into a v4 tape in the walker's order; it ships default palettes ("the block does not hold the live
   palette bytes … the agent reads them through a pointer the dump does not follow") and takes System-A
   vertices from `.pack` files. With the runner both gaps close inside the block/dcram: `palrows` from
   `blk+0x13C0` (in blk), objects from the dcram image at the relocated `node+0xA0`. That extension makes it a
   v5 emitter of the runner's memory — or, per §2.1 B, the agent's own encoders do it. **Gate:** §2.4 against
   the agent's tape from step 1.
4. **Tape -> draws -> pixels.** `rr-render emit_seq` on the runner tape; **L1** vs `tape_to_seq.py`; then the
   player (`serve.py` + `player.html`) with the `gate_l3.mjs` readback vs `scene_<f>.bmp` through
   `verify_alpha.py` then `verify_frame.py`. **That readback is the first end-to-end gated pixel.** Read
   coverage before colour; attribute to draws before theorising (Path B method, `RENDER-ACCURACY-PROGRAM.md`).

What the first number will contain, by construction: Path B's floor (0.011–0.018%), plus the §4 residuals the
emitter does not yet draw (combo counter, portraits from a capture library, 12 strips, LUT lag). Each of those
already has its rule and gate; the runner removes their DATA dependence (§4, "EASIER" column) but not the port.

---

## 7. Address / file index

`FUN_140118950` tick · `FUN_140607d60` frame (`*(game_state+0x10)`) · `FUN_140608a00` sim · `FUN_14060b960` render
table loop · `FUN_140620960` dispatcher · `FUN_140620f10` sprite walker · `FUN_140620740/cd0` world walkers ·
`FUN_1406129f0` submit · `FUN_1408436a0` TA record emit · `FUN_140619960` dispatcher mode (reads UNKNOWN) ·
`FUN_14061d7e0/d6a0/d5b0` cameras -> `ctx+0x1f816c/0x1f812c` · `FUN_140653a70` list-0xC parts · `FUN_14060d560`,
`FUN_1406162e0`, `FUN_140616330` portrait uploads · `FUN_1406146d0`/`FUN_140613390` palette staging/upload ·
`FUN_1406101b0` background · `DAT_142edf560` blk · `DAT_142edf628 = blk+0x324E0` · `game_state 0x140ac6d40`
(`+0x218` pads, `+0x258` seat map, `+0x770` render suppress — outside the tick, `+0x798` frames-to-run).

`RetroReceipts-agent/agent/src/reader.rs` — `GS_SCHEMA` :1239 · `read_gs_row` :1682 · `harvest_confirmed_in`
:1931 · `harvest_objs` :1998 · `harvest_anodes` :1456 (`ANODES_CAP_PER_FRAME` :1446) · palrows read :2377–2387 ·
battle anchor :2244–2270 · edge sampling :2453–2462 · `spool_gamestate` :2518 (`battle_anchor_enc` :2750,
`confirmed_in` :2764, `palrows_enc` :2775, `anodes_enc` :2782, `nodes_enc` :2784) · `read_at` :3893 · `mem.rs:89`.
`RetroReceipts-agent/rr-render/src/feed.rs` FrameRecord · `sprites.rs:138` `emit_row` · `tools/gate_l1.sh`,
`tools/seq_diff.py`, `tools/gate_l3.mjs`.
`mvc-live-skins-quarters/d3dcap/replay/` — `receipt_gate.py`, `emu_gate.py`, `emu_frame.py`,
`determinism_gate.py`, `tape_vs_dump_gate.py`, `states_to_tape.py`, `blkstate.py` (`nodes` :240, `anodes` :284,
`pnodes` :321), `parts_gate.py`, `palette_gate.py`, `bg_gate.py`, `tsp_gate.py`, `sort_gate.py`, `v3gate.py`,
`verify_alpha.py`, `verify_frame.py`, `tape_to_seq.py` (`--pal-lag` :593). `d3dcap/dllmain.cpp:741–835` walker
hook + `alist` dump. `d3dcap/session-guided.ps1`, `d3dcap/ttd/dump_live.py`.
