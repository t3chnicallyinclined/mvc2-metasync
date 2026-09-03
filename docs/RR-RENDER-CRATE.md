# rr-render — the Rust tape decoder + sprite emitter (Track R, W1), as built 2026-09-03

*Crate: `C:\Users\trist\projects\RetroReceipts-agent\rr-render\` (standalone Cargo package; `agent/` is untouched —
there is no workspace `Cargo.toml` at the repo root today, so it is a sibling crate, not yet a workspace member).
Oracle: `mvc-live-skins-quarters/d3dcap/replay/tape_to_seq.py` (+ `v3gate.py`, `rip_gfx2_assembly.py read_cells`).
Method: `RE-METHOD.md` — this is a PORT, not an RE task; every rule was already CONFIRMED and gated. Plan:
`WORKSTREAM-CLIENT-REPLAY.md` §4 W1, review `WORKSTREAM-CLIENT-REPLAY.review-render.md` §1 / §4. Nothing committed.*

## 1. What it is

Milestone 1 of the port: the **tape decoder** (v4 / v5 + the 0.3.39..0.3.45 appended fields) and the **sprite
assembly** (the gated placement law), emitting the SAME RRSQ container the Python writes so the Python can be the
oracle draw by draw. Python was not changed. Core = `std::fs`-free and thread-free; `cargo check --lib --target
wasm32-unknown-unknown` passes. Native bin `emit_seq` = the gate driver.

## 2. Module map (Python function → Rust)

| Rust | Ports (Python) | Notes |
|---|---|---|
| `src/util.rs` | `tape_to_seq.sha8`, `intern` hashing | sha256 (sha2), gunzip+base64, `OrderedMap` (dict insertion order) |
| `src/tape.rs` `Tape::decode` | `main()`: envelope + schema/column map (`C`, bare-name aliases for `look[3]`→`look`), the `nodes` decode loop (`'<BBBbBBBBHHHBBBBHHHfffII'` + v4 tail + 0.3.38 `owner_off`/`oslot`), `pals` (ARGB4444→RGBA×17), `palrows` (148 B/frame) | strides from the envelope (`nodes_stride` 44/50/54, `anodes_stride` 96/100, `palrows_stride`). Record layouts = `agent/src/reader.rs` `spool_gamestate` (2474): `frames` json! 2502-2512 (`GS_SCHEMA` 1226; 0.3.39/0.3.45 row fields 1338/1342), `nodes_raw` 2580 (`ObjNode` 1365, `NODES_STRIDE` 1978), `anodes_raw` 2617 (`ANode` 1419, `ANODES_STRIDE` 1423), `aobjs_raw` 2637, `palrows_raw` 2646, `pals_raw` 2664 |
| `src/tape.rs` `decode_anodes` / `decode_aobjs` / `nl_groups` | `tape_to_seq.decode_anodes`, `nl_groups` (Steam strip winding, ref-vertex mode, synthetic-tape key stash) | decoded now; consumed by W2 |
| `src/tape.rs` `RowView` | the row columns the emitter/renderer read | `frame, eyeX/eyeY/ground/zoom, drawn/sid/sx/sy/facing/layer[6], timer, round_no, cam_state, look[3], fov, yoff, roll, deck[3], blackout, bg_mode, bg_col[3], fade_mode, fade_col, bg_gate[6]` (Option per field; absent on older schemas) |
| `src/assets.rs` `Atlas::from_files` | `tape_to_seq.Atlas.__init__` | consumes exactly: `PLxx_idx.png` (R channel), `PLxx_asm.json` (`parts`, `assemblies`), `PLxx_lut.json` (`banks`, `bodyBank`), `dasm_PLDAT/Output/PLxx_DAT/*GFX_DATA_01.BIN` (raw GFX2 → per-record row `(flags>>4)&7` + FLAGS word), `*GFX_DATA_00.BIN` (GFX1 header `[lw][lh][sw][sh]` → logical dims). Bytes in, no I/O |
| `src/assets.rs` `read_cells` | `rip_gfx2_assembly.read_cells` | 8-B records, cumulative pen `px += dx; py -= dy`, cells with `cnt==0 / >64 / overflow` skipped |
| `src/assets.rs` `part_bitmap`, `palette`, `row_of`, `flag_of` | `Atlas.part_bitmap` (every part stored upside down; logical top-left clip for scale-walker records), `Atlas.palette` (`8*costume`, `bank % len`), `row_of`, `flag_of` | |
| `src/camera.rs` | `scene_block` (fitted `camera_block.json` model, f64 eval → `<108f`), `scene_VP` (rows 7..10 / 15..18), `sprite_vertex_z` (FUN_1408432e0 in f32) | W2 replaces the fitted model with the closed form and must gate against this |
| `src/sprites.rs` `Emitter::emit_row` | the sprite pass of `main()`: held rows, `LAYERZ` order `(-LAYERZ[layer&15], -index)`, owner resolve (`oslot` → `bank_slot[gfx1]` → single unknown slot), `mir = face`, `floor(sx)*3/5`, palette (`palrows[slot*8+row]` → v3 `pals[pal]` + LUT block locate → `Atlas.palette`), REVERSE record order, `hf = flags&0x8000`, `vf = flags&0x4000`, scale-walker (`sid&0x8000`) logical placement vs tiled flip about the LOGICAL box, `rot180`, general rotation about the hotspot in 640-space (f64 cos/sin), `D = depth + 0.001*ri` (f32), vertex pack (stride 40, UV winding = mirror), `sub = (0, walk, ri)` | v2 fallback (six fighter columns) ported; the pre-decoded local `objs` list form is not |
| `src/sprites.rs` `order_draws` | `tape_to_seq.order_draws` | cats 0/1 by submission, cat 3 by `(-key, sub)`; keyless draws inherit the previous key |
| `src/seq.rs` | `template()` / `load_pack_rrpk` (first `psVariant=='indexed'` draw of `frame_2574.pack` + its constant buffers), the frame head + RRSQ writer | pool interned in the Python order (template CBs, then textures first-seen, then vb, ib per frame) |
| `src/bin/emit_seq.rs` | the CLI of `tape_to_seq.py` restricted to `--no-world` | `--start/--count/-o/--atlas/--dasm/--template/--camera/--bank/--pal-lag/--flip-facing/--swap-teams/--forward-records/--no-vflip/--legacy-order` |
| `tools/seq_diff.py` | NEW gate (~110 lines) | per draw: every JSON field, texture records + bytes, the 6 indexed vertices' raw 40 B (f32 bit-compare), CB bytes; `--sprites-only` gates the sprite subsequence of a full (world+sprite) Python run |
| `tools/gate_l1.sh` | the exact L1 invocations below (tape paths + `--start` values live here, not in prose) | |

Not ported (by design, W2+): `WorldTemplate`, `emit_stage`, `emit_world`, the frame preamble, `tsp_state`, `bg_rule`.

Two exactness rules that mattered: (1) `serde_json` `float_roundtrip` is ON — the default parser is best-effort and
put `maxlod` 1 ulp off `3.40282e+38` (and would have moved `eyeX/eyeY`, which feed P and every vertex z);
(2) numpy's `np.float32(depth) + np.float32(0.001)*ri` is f32 under NEP 50 (numpy 2.2.6 here) — the port does the same
in `f32`; the rotation trig is f64 `cos/sin` on both sides (MSVC CRT) and matched bit-exact on 603 rotated parts.

## 3. Gate numbers (L1 — draw-list equality vs Python, 2026-09-03)

Python invoked as `tape_to_seq.py <tape> --start S --count N --no-world` (sprites only; camera_block.json present so
`Ps`/depth keys are live); Rust as `emit_seq <tape> --start S --count N`. `seq_diff.py` = exact per draw.

| tape | clip | draws exact / total | notes |
|---|---|---|---|
| stage 13 `…_59613662_…` (0.3.39, stride 54, anodes 100) | `--start 1500 --count 60` (clocks 2743..) | **1891 / 1891** | 1 held row ("no nodes") on both sides; 443 textures |
| same, sprite subsequence of the FULL Python run (world+preamble+sprites, 24,574 draws) | `--start 1500 --count 60`, `--sprites-only` | **1891 / 1891** | relative order of sprite draws survives the cat-3 sort |
| stage 13, clock **7279** (row 6036) | `--start 6000 --count 60` | **1670 / 1670** | |
| training stage 11 `…_59613506_…` (0.3.38), clocks **4445** (row 3437) + **4505** (row 3497) | `--start 3430 --count 80` | **2962 / 2962** | ⚠ clock 7279 is NOT in this tape (range 1008..5788); it was gated on the stage-13 tape above |
| palrows tape `…_59614009_…` (0.3.41, stage 13) | `--start 1000 --count 60` | **3510 / 3510** | exercises `palrows[slot*8 + rec.flags>>4]` |
| v4 rotation tape `replay-kit/tapes-kept/…_59612784_…` (0.3.34, stride 50) | `--start 3245 --count 60` | **2588 / 2588** | 603 parts through the general-rotation path (0x1400, hotspots (-24,-88)…) |

Totals: **12,621 / 12,621 sprite draws exact, first differing field: none.** Speed: 60-frame clip 1.1 s (Rust, incl.
tape parse + 6 atlas PNG decodes) vs 3.8 s (Python).

Not yet run on Rust output: L2 (`v3gate.py` needs an `--emitter rust` adapter reading the Rust draw list), L3 pixels.

## 4. How to run

```
cd C:\Users\trist\projects\RetroReceipts-agent\rr-render
cargo build --release
bash tools/gate_l1.sh            # all six rows of the table above (writes to %TEMP%, never into the repo)
```
ROM-derived inputs/outputs (atlases, GFX bins, `.seq`) stay out of git (`.gitignore`: `target/`, `*.seq`).

## 5. What is next (W2 — world / state), in order

1. `nl` groups are decoded; port `tsp_state.codes/predict/HOST` → `state::tsp` (pure fn), and freeze the two template
   packs' state tuples as constants (`state::webgpu`) so `WorldTemplate` is not needed (review-render R2; gate =
   `WorldTemplate.select` would report 0 "patched fallback" on 4445/4505/7279).
2. `world::deck` (arc `STGxx.json` model 0, static VB) + `world::emit` (lists 5/6/12/13, 7/8/9, 11; CBWorld = node
   matrix transpose, per-list scene block, colour packing R,G,B,A, `complete_prop`) + the frame preamble
   (`bg_rule.from_row`, three quads).
3. `order::flush` already exists (`order_draws`); extend the sort key to world records (`sort_key_record`).
4. Closed-form camera (`WORLD-CAMERA-GHIDRA.md`) replacing `camera_block.json` — gate bit-identical vs the fitted
   block rows 7..10/15..18 (`emu_gate.py camera 4445`).
5. Gate: `seq_diff.py` without `--sprites-only` against the full Python run (24,574 draws on the stage-13 clip), then
   `tsp_gate` / `worldgeo_gate` / `sort_gate` / `palette_gate` on Rust output.
6. Binary `FrameRecord` for the browser feed (replaces RRSQ JSON heads, 730 KB/frame) — after W2 so both passes share it.
