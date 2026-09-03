# RECEIPT-RUNNER-GATE2 — the live agent's harvest over the native runner's memory yields the live agent's tape (2026-09-03)

Owner lane: senior-re-generalist. Workstream: `docs/WORKSTREAM-RECEIPT-RUNNER.md` s4 step 2; design of record
`docs/RECEIPT-RUNNER-RENDER.md` s2.1 (option B) – s2.4, `docs/RECEIPT-RUNNER-RE.md` s3.3–3.4. Prerequisite: Gate 1
(`docs/RECEIPT-RUNNER-GATE1.md`). Deliverables: `RetroReceipts-agent/agent/src/{lib.rs,harvest.rs,runner.rs,bin/rr-tape.rs}`
(commit `2410e90`), `d3dcap/receipt/runner/rr_runner.cpp --harvest-dump`, `d3dcap/receipt/runner/runner_tape_gate.py`,
`RetroReceipts-agent/rr-render/tools/gate_tapes.mjs`, `d3dcap/replay/player.html` (`&opts=` for the wasm feed), seed
`maplecast-flycast/tools/re_kb/115_receipt_runner_gate2.surql`.

## RE METHOD (locked; `docs/RE-METHOD.md`)

1. Port the SH4 annotations to the Steam binary by function matching.
2. Seed with unique constants, then propagate along the call graph.
3. Translate globals through the block map before comparing reference sets.
4. Tag CONFIRMED versus INFERRED, and store the pairs as edges in the knowledge graph.

Step this document is at: **4**. No offset is derived here: the harvest is the agent's (`reader.rs` 0.3.48/0.3.49 constants,
now `harvest.rs`), the runner's addresses are Gate 1's, and the comparison is numeric. The new facts (the stage-9 DC-RAM write
set, the object-cache class, the mid-walk read) are measurements, stored in seed 115. Tags: **CONFIRMED** = reproduced by a
byte gate on real images; **INFERRED** = read in the disassembly / gate-consistent; **UNKNOWN** = not located. No time
estimates anywhere. BYOR: every input and output is game-derived and lives in `runs/`, `packs/` or `%TEMP%` (all gitignored).

## 0. Result

Data pair: live tape `d3dcap/replay/packs/local_stage9/tape.json.gz` (offline Versus, stage 9, roster [42,23,52,12,44,46],
agent 0.3.48, 5,222 rows from clock 1716, rollbacks 0) and the run `d3dcap/ttd/runs/receipt-20260903-stage9-anchor` (anchor at
clock 1716, Gate 1). The runner ticked 300 times with the live rows' seat words (row `1716+k` produced tick `k`) and the harvest
emitted ticks 0..300 = clocks **1716..2016, 301 frames**, compared column by column against the live rows of the same clocks.

| section | compared | exact | attributed (class) | unexplained |
|---|---|---|---|---|
| `frames` rows, 61 columns × per element (`GS_SCHEMA`) | 301 rows | every column **301/301** except `sx[1]` 299, `sx[2]` 299, `sy[1]` 300, `sy[2]` 300 | 6 (**P**, frames 1978 and 2013) | **0** |
| `nodes` (draw list, stride 54): count + 27 fields | 301 lists, 1,032 records | count 301/301; 25 fields 1032/1032; `fsx` 1026, `fsy` 1030 | 8 (**P**, the same two frames) | **0** |
| `anodes` (world nodes, stride 100): count + list/flags/matrix/colour/alpha/model(DC)/obj | 301 lists, 15,911 records | count 301/301; list, flags, matrix, colour, alpha, model **15911/15911**; `obj` 15297 | 614 (**A**, 3 objects) | **0** |
| `aobjs` (interned objects referenced in the window) | 124 live / 124 runner | 121 both | 3 + 3 (**A**, the same 3 objects) | **0** |
| `palrows` (48 × 32 B + 48 flags per frame) | 301 frames | rows **14448/14448**, flags **301/301** | — | **0** |
| `pals` (window sets) / envelope (stage, teams, costume, assist, local_pn, build_id, schema, strides) | — | equal | `seat_map` (**F**) | **0** |
| `seat_in`, `kcode` (the inputs, as the tick leaves them in `G+0x218`) | 301 rows | **301/301** | — | **0** |

**Gate 2: PASS** — `runner_tape_gate.py`: 0 unexplained differences; attributed P 14, A 620, F 1 (classes in s3). The runner's
DC-RAM write set on stage 9, measured per tick: 952 changed 4 KiB pages / 3,899,392 B over 300 ticks, at most 9 pages per tick
(s3.1). Tick cost with the harvest dump: p50 0.144 ms (0.088 ms without; Gate 1 0.08 ms). `rr-tape` over 301 ticks: 164,190 B
tape; two runs differ only in the envelope `ts`/`id` (the harvest is deterministic).

Render (`rr-render`, 60 rows from the anchor, pack `local_stage9`): sprite draws **2114/2114** exact (`seq_diff --sprites-only`);
whole emit exact with `--no-world` (2114/2114); full emit 34,619/34,979 draws, the 360 differing = **6 world draws per frame** of
textures `world_00000C12` / `world_00000C1C` = the class-A props. Browser (`player.html` wasm feed, scene-RT sha per frame,
`gate_tapes.mjs`): live vs runner, `no_world` **60/60 byte-equal**; live vs runner full frame 0/60 (the props); live vs the
runner tape with only the three class-A object byte strings swapped for the live tape's: **60/60**, and **299/301 over the whole
window — the two differing clip frames (262, 297) are clocks 1978 and 2013, exactly the two class-P mid-walk live frames** (the live
tape holds previous-frame placements there, so its own render is the wrong one; s3.3). That is Gate 5's first rung: a receipt (battle anchor + 4 B of inputs per frame) reproduces the live replay pixel for pixel, the
only residual being object bytes the live tape itself carries stale (s3.2).

## 1. Design choice: (A) the harvest as a library, one implementation (RENDER s2.1 option B)

The alternative — attaching the live agent reader to the runner as a process (B) — keeps the asynchronous 0.5 ms poll, the torn-list
retries and the caps, i.e. exactly the noise this gate removes, and would still sample at a random phase of the tick. (A) is also
what a host node or the PWA's native companion will link. What changed, and what did not:

| piece | where | what |
|---|---|---|
| `MemSource` trait | `agent/src/harvest.rs` | `read_mem(addr, len) -> Option<Vec<u8>>`; `mem::Proc` implements it (`self.read`); `read_at(h: &dyn MemSource, …)` keeps the 0.3.43 `BLK_SNAP` thread-local in front of it. Every existing call site passes `&mem::Proc` and coerces — no caller changed. |
| the harvest | `agent/src/harvest.rs` (1,286 lines) | MOVED VERBATIM from `reader.rs` by asserted line ranges: the offset table, `GsRow/ObjNode/ANode/ANodeRaw/GsCapture/GsSnapshot`, `rpm_*`, `read_set_score`, `GS_CAP/GS_SCHEMA`, `harvest_anodes`, `read_gs_row`, `read_pal`, `harvest_objs`, `game_build_id`, `gzip_bytes/b64_encode/set_score_json`, `BLK_SNAP/snap_install/snap_clear/read_at/read_at_raw`, `fnv1a64`, `u16le/le32/lef32/le64`, and the body of `spool_gamestate` up to the gzip as `build_gamestate_record` (returns the gz + the "DROPPING anchor" flag the wrapper traces). Edits: `pub` visibility, `&mem::Proc` → `&dyn MemSource`. |
| three inline blocks of the capture loop | `harvest.rs` `read_match_start` + `GsCapture::begin_match`, `read_palrows`, `GsCapture::record_frame`, `GsCapture::to_snapshot` | the match-start envelope, the palette-row read and the per-frame insertion (interning included) were inline under the capture lock; they are now functions with the same bodies, called from the loop and from the runner emitter. |
| `reader.rs` | `git diff`: **1,212 lines out, 35 in** — the 35 are the `pub(crate) use crate::harvest::*;` re-export (so `painter.rs`'s `reader::{read_at, rpm_u8, …}` imports resolve unchanged) and the call sites above | the capture loop, its gating, the poll/retry/stability machinery, the spool wrapper, uploads: untouched. |
| crate layout | `agent/Cargo.toml`, `src/lib.rs`, `src/main.rs` | `[lib] rr_agent = mem + harvest + runner`; the tray bin re-exports `rr_agent::mem`/`harvest` at its root (`crate::mem` paths unchanged); `[[bin]] rr-tape`. `#![recursion_limit = "256"]` mirrored (the record `json!`). |
| `RunnerView: MemSource` | `agent/src/runner.rs` | five regions at the live addresses (Δ = 0): blk (per tick), game_state page (per tick), exe page `0x142edf300..0x700` (per tick), the 32 MB DC-RAM (`pre/dcram.bin` + the per-tick page deltas replayed in order), the exe PE header (`game_build_id`). Anything else → `None` (a failed RPM). `emit_runner_tape` = the capture loop over it: tick 0 `read_match_start`/`begin_match` + the battle anchor from the runner's own regions, then per tick `snap_install`, `read_gs_row`, `harvest_objs`, `harvest_anodes`, `read_palrows`, `record_frame`; then `build_gamestate_record`. |
| `rr_runner --harvest-dump` | `d3dcap/receipt/runner/rr_runner.cpp` | per tick `gs_tNNN.bin` (0x1000 @ `0x140ac6d40`), `exe_tNNN.bin` (0x400 @ `0x142edf300`), `dcram_tNNN.dlt` = every 4 KiB DC-RAM page that differs from the previous tick (memcmp against a shadow; records `{u32 off, u32 4096, bytes}`); `t000` = the state after the loader/self-checks. `summary.json` carries the per-tick page counts. |
| proof the live path is unchanged | `cargo build --release` (tray + rr-tape), `cargo test --release` **6/6** (the `GsRow` test fixture had not been kept exhaustive since 0.3.37 — `cargo test` did not compile at HEAD; fixed, test-only), `git diff` as above; the moved functions exist exactly once (`harvest.rs`) and zero times in `reader.rs`. No tape was recorded and no recording behaviour changed. | |

What the harvest reads and where the runner view serves it from is the RENDER s2.2 table, unchanged; two things that table
left INFERRED are now CONFIRMED: the tick writes the injected inputs to `G+0x218/+0x21C` (`seat_in`/`kcode` equal 301/301 with
no translation), and every object the harvest reads at `*(node+0xA0)` and every palette at `*(H+0x1B8)` lies inside the
DC-RAM image (the view serves nothing else and no row/node/object was rejected).

## 2. The gate (`d3dcap/receipt/runner/runner_tape_gate.py`)

```
cd C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\receipt\runner
python runner_tape_gate.py --run C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\runs\receipt-20260903-stage9-anchor --live C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\replay\packs\local_stage9\tape.json.gz --ticks 300 --out %TEMP%\rrcap_runner\gate2_300 --json %TEMP%\rrcap_runner\gate2_300\gate2.json
python runner_tape_gate.py ... --skip-runner --skip-emit --only-diffs        # re-compare existing outputs, print only non-exact columns
```

Steps: (1) `inputs.txt` from the live rows (tick `k` = row `clock0+k`.`seat_in`); (2) `rr_runner.exe --harvest-dump`; (3)
`rr-tape.exe` (built by `cargo build --release --bin rr-tape` if missing) → `runner_tape.json.gz`; (4) compare per section on the
clock intersection: rows per column and element; nodes per record and field with `pal` compared as the resolved 32 B and `gfx1/gfx2`
normalised (K); anodes per record with `model` normalised to a DC address and `obj` compared by the sha of the interned bytes;
`aobjs` and `pals` window-scoped (the live tables cover the whole match); envelope. Every difference must be attributed to one of
P/T/R/C/K/L (RENDER s2.3) or the two classes below, else the gate FAILS. The first divergence per column is printed with both
values and the runner's previous-frame value.

## 3. Findings

### 3.1 The DC-RAM write set of a REAL stage, measured per tick (CONFIRMED)
`RECEIPT-RUNNER-RE` s1.1 measured the training stage: tile buffer + 50 B of effect u/v + 10 HUD TCW bytes. Stage 9 over 300
receipt ticks: **952 changed 4 KiB pages, 3.9 MB, ≤ 9 pages per tick**. Tick 1: the tile buffer `0x0CE60000..0x0CE62000` and
two pages inside the stage POL bank, `0x0D853000` and `0x0D855000` (`0x0D82D000 + 0x26000..`); later ticks add the effects POL
u/v (TCW `0xC5B`). The two stage-POL pages hold the objects at `0x0D853158` (TCW `0xC12`, 456 B) and `0x0D855800` (TCW `0xC1C`,
512 B) — animated props rewritten in place every frame, the RE s1.2 mechanism (`LAB_14064cb20`-style callbacks: destination
vertices from the pristine sibling model + blk phase counters). This is why the harvest view needs the per-tick delta and not
"the whole image once": without it `aobjs` would hold the dump's phase for every frame. (`summary.json dcram_delta_per_tick`.)

### 3.2 Class A — the 0.3.44 object cache ships first-sighting vertices for animated objects, on both sides (CONFIRMED)
`harvest_anodes` (reader.rs 0.3.44, now harvest.rs) caches each world object by pointer and its first **0x68 bytes** (0x18 object
header + the first 0x50 record header); while those match, the cached bytes are re-shipped without re-reading the vertices. An
object whose vertices the frame regenerates therefore enters the tape with the bytes of its **first sighting** and never changes.
The gate's 614 `obj` mismatches are exactly three (live, runner) object pairs, each same length, every record header equal,
differing in vertex fields alone:

| object | list | TCW | bytes | fields differing | phases seen by the runner in 300 ticks | the live bytes |
|---|---|---|---|---|---|---|
| DC `0x0D853158` | 5 | `0xC12` | 456 | `vert.x` ×12, `vert.z` ×3, `vert.ny` ×3, `vert.u` ×4 | 90 distinct | = the runner's phase at ticks 72 and 144 (a 72-frame cycle; the live cache saw it before the anchor) |
| DC `0x0D855800` | 5 | `0xC1C` | 512 | `vert.y` ×14, `vert.nx` ×14, `vert.v` ×14 | 264 distinct | a phase before the anchor (never reached in 1716..2016) |
| effects object (list 7, 12 frames from 1929) | 7 | `0xC5B` | 2,280 | `vert.u` ×12, `vert.v` ×14 | — | first sighting on each side (RE s1.2 `FUN_140625920` u/v rewrite) |

The runner's per-tick DC-RAM is frame-exact from tick 1 (regeneration is absolute; the runner's tick-0 bytes — the post-match
dump's phase — recur at ticks 35/107/216/288 as a genuine phase). So **both tapes carry non-frame-exact vertices for animated
props**, the live one included; the difference between them is which first sighting. Falsification of the attribution: swapping
only those three byte strings in the runner tape makes the browser render byte-equal to the live tape on 60/60 frames and on 299/301
over the window, the 2 residual frames being the class-P mid-walk frames (s0, s3.3). Consequence for Track R / Gate 5 (not changed here — the agent's recording behaviour is out of scope): animated
props must be posed from keys (node `+0x30/+0x32` phase counters, WORKSTREAM s2 Q3) or the cache must key on content, not
header; the runner path can simply disable the cache and intern one object per phase (90–264 × ~0.5 KB per prop per match).

### 3.3 The live edge read can land INSIDE the sprite walker (CONFIRMED) — the class-P mechanism, seen whole
Frame 1978 of the live tape: the draw-list read holds node 0 (an effect) with the frame's new placement, nodes 1–2 (the same
effect's siblings) and both fighters with the **previous** frame's placement, and fighter slot 2 with an intermediate screen X
(**44.99935**, between the previous 45.0 and the final 44.65829) while the row read a few microseconds earlier still holds
45.0 for that fighter. The runner's post-tick read has the final values on every node. Frame 2013 is the same with two nodes.
`runner_tape_gate.py` therefore classifies P at frame level: a frame where any node still equals the runner's previous frame
is mid-walk, and every walker-field difference in it is P (the intermediate value is neither frame's final one — INFERRED to be
`FUN_140620f10` writing `+0x124` more than once per node; the frame-level evidence is CONFIRMED). 14 values in 301 frames.

### 3.4 Class F — the runner-forced seat map (documented)
The runner writes `{0,1,-1,-1}` to `game_state+0x258` (contract C2, Gate 1 step 4); the live offline game reports `[0,0,0,0]`.
An envelope field, never a frame byte; attributed explicitly so the gate does not pass it silently.

### 3.5 What the gate did NOT need
No T (torn/stub list), C (cap), K (host pointer — Δ = 0 makes the raw values equal; the normalisation is in place for the
general case), R (rollbacks 0) or L attribution was consumed on this pair. `bg_gate[4..5]` (`entity+6/+0x96` through
`DAT_142edf628 = blk+0x324E0`) equal 301/301 — the relocation reading in RENDER s2.2 holds.

## 4. Render gate

```
cd C:\Users\trist\projects\RetroReceipts-agent\rr-render
.\target\release\emit_seq.exe C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\replay\packs\local_stage9\tape.json.gz --pack C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\replay\packs\local_stage9 --start 0 --count 60 -o %TEMP%\rrcap_runner\gate2_300\live_0_60.seq
.\target\release\emit_seq.exe %TEMP%\rrcap_runner\gate2_300\runner_tape.json.gz --pack C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\replay\packs\local_stage9 --start 0 --count 60 -o %TEMP%\rrcap_runner\gate2_300\runner_0_60.seq
python tools\seq_diff.py %TEMP%\rrcap_runner\gate2_300\live_0_60.seq %TEMP%\rrcap_runner\gate2_300\runner_0_60.seq [--sprites-only]
rem browser: copy runner_tape.json.gz into d3dcap\replay\packs\local_stage9\ (gitignored), then in d3dcap\replay: python serve.py 8099
node tools\gate_tapes.mjs --a packs/local_stage9/tape.json.gz --b packs/local_stage9/runner_tape.json.gz --pack packs/local_stage9 --start 0 --count 60 [--extra "&opts=%7B%22no_world%22%3Atrue%7D"]
```

| comparison | result |
|---|---|
| `seq_diff`, full emit, 60 frames | 34,619 / 34,979 draws exact; 360 differing = 6 world draws/frame (`world_00000C12` opaque ×3, `world_00000C1C` texalpha ×3), vertex bytes only |
| `seq_diff --sprites-only` | **2114 / 2114** |
| `seq_diff`, both emitted `--no-world` | **2114 / 2114** |
| browser A/B (`gate_tapes.mjs`), live vs runner, `no_world` | **60 / 60** scene targets byte-equal |
| browser A/B, live vs runner, full frame | 0 / 60 (the two props, class A) |
| browser A/B, live vs runner with the 3 class-A byte strings swapped (`runner_tape_hybridA.json.gz`) | **60 / 60**; over 301 frames **299 / 301** — the 2 differing = clip 262/297 = clocks 1978/2013 = the class-P mid-walk frames of s3.3 (the LIVE tape draws stale placements there) |

`gate_tapes.mjs` renders both tapes through the same `player.html` wasm feed (the PWA's path) and compares the raw BGRA scene
target sha per frame; `&opts=` is new in `player.html` (passed to the wasm `EmitOpts`).

## 5. CONFIRMED / INFERRED / UNKNOWN after Gate 2

| item | tag |
|---|---|
| The agent's harvest over the runner's memory reproduces the live tape per column (rows, nodes, anodes, palrows, envelope), 301 frames, 0 unexplained | CONFIRMED |
| Every difference is a live-only artefact: sampling phase (P), the object cache (A), the forced seat map (F) | CONFIRMED (the hybrid render tests it: 299/301 byte-equal, and the 2 residual frames are precisely the P frames) |
| The tick writes the injected inputs to `G+0x218` (seat_in/kcode equal with no translation) | CONFIRMED |
| Stage-9 per-frame DC-RAM write set: tile buffer + 2 stage-POL pages + effects u/v, ≤ 9 pages/tick | CONFIRMED |
| Animated-prop vertices in BOTH tapes are first-sighting bytes (0.3.44 cache) | CONFIRMED |
| The intermediate screen X on a mid-walk read = the walker writing `+0x124` more than once per node | INFERRED (frame-level evidence CONFIRMED) |
| The live agent's tape bytes for a live match are unchanged by the refactor | CONFIRMED by construction (verbatim move, `git diff` = call sites only, tests 6/6); no new recording taken |
| Runner tape == live tape on an ONLINE (rollback > 0) match | UNKNOWN — needs an online receipt; class R is implemented, untested |
| Runner tape == live tape on a HUD-heavy frame with > 96 world nodes (class C) | UNKNOWN — no frame in this window exceeded the caps |

## 6. What remains

Gate 3 (loader replaces the dump): the runner view already takes DC-RAM from `pre/dcram.bin` + deltas; once the loader path
fills DC-RAM from the user's arc (`RECEIPT-RUNNER-DCRAM` s2), the same `rr-tape` run over the same files is the gate. Gate 5
(pixels): the class-A residual is the only pixel difference on this pair; the fix is renderer-side (keys) or harvest-side (content
key / no cache in the runner path) and belongs to the Track R lane. Not done here: an online pair (class R), a HUD-heavy pair
(class C), a Linux/Proton run of `rr-tape` (nothing in `harvest.rs`/`runner.rs` is Windows-specific; `mem.rs` unchanged).

## 7. Files and commands

- `RetroReceipts-agent/agent/src/harvest.rs` (library), `runner.rs` (`RunnerView`, `emit_runner_tape`), `bin/rr-tape.rs`, `lib.rs`; `reader.rs`/`main.rs`/`Cargo.toml` (call sites, re-exports, targets). Build: `cd C:\Users\trist\projects\RetroReceipts-agent\agent && cargo build --release` (both bins), `cargo test --release`.
- `d3dcap/receipt/runner/rr_runner.cpp` (`--harvest-dump`), `build.bat`; `runner_tape_gate.py`; `d3dcap/replay/player.html` (`&opts=`); `RetroReceipts-agent/rr-render/tools/gate_tapes.mjs`.
- Outputs (gitignored): `%TEMP%\rrcap_runner\gate2_300\{blk,gs,exe}_tNNN.bin, dcram_tNNN.dlt, summary.json, runner_tape.json.gz, gate2.json, *.seq}`; `d3dcap\replay\packs\local_stage9\runner_tape*.json.gz`.
- Seed: `maplecast-flycast/tools/re_kb/115_receipt_runner_gate2.surql`.
