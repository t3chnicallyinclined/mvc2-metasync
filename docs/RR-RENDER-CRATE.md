# rr-render — the Rust tape decoder, frame emitter and browser feed (Track R, W1 + W2 + W3), as built 2026-09-03

*Crate: `C:\Users\trist\projects\RetroReceipts-agent\rr-render\` (standalone Cargo package; `agent/` untouched — no
workspace `Cargo.toml` exists at the repo root, so it is a sibling crate, not yet a workspace member). W1 committed
as c141164, W2 as 039afa6; W3 (this revision) uncommitted. Oracle: `mvc-live-skins-quarters/d3dcap/replay/tape_to_seq.py`
(+ `tsp_state.py`, `bg_rule.py`, `v3gate.py`, `rip_gfx2_assembly.py read_cells`). Method: `RE-METHOD.md` — a PORT, not
an RE task. Plan: `WORKSTREAM-CLIENT-REPLAY.md` §4, review `WORKSTREAM-CLIENT-REPLAY.review-render.md` §1 / §3 / §4.*

## 1. What it is

The **tape decoder** (v4 / v5 + the 0.3.39..0.3.45 appended fields), the **whole-frame emitter** (preamble, arc
deck, world lists 5/6/12/13, sprites, lists 7/8/9, HUD 11, the two-phase flush), and — W3 — the **browser feed**:
the crate built to wasm runs in a Web Worker, takes the TAPE and an asset pack as bytes, and posts one binary
`FrameRecord` per frame to the existing WebGPU replayer. **No `.seq` on disk; the browser plays the tape.**
Core = `std::fs`-free, thread-free. Native bin `emit_seq` = the L1/L2 gate driver (+ `--camera-gate`, `--feed-bench`).

## 2. Module map (Python function → Rust)

| Rust | Ports (Python) | Notes |
|---|---|---|
| `src/util.rs` | `sha8`, `intern` hashing | sha256, gunzip+base64, `OrderedMap` |
| `src/tape.rs` `Tape::decode` | `main()`: envelope + schema map, `nodes` (44/50/54), `pals`, `palrows`, synthetic `pages`; `decode_anodes`, `nl_groups`; `RowView` | layouts = `agent/src/reader.rs` `spool_gamestate` 2474 (`frames` 2502-2512, `GS_SCHEMA` 1226, fields 1338/1342, `nodes_raw` 2580 / `ObjNode` 1365 / `NODES_STRIDE` 1978, `anodes_raw` 2617 / `ANode` 1419 / `ANODES_STRIDE` 1423, `aobjs_raw` 2637, `palrows_raw` 2646, `pals_raw` 2664) |
| `src/assets.rs` | `Atlas.__init__/part_bitmap/palette/row_of/flag_of`, `read_cells` | `PLxx_idx.png`, `_asm.json`, `_lut.json`, `GFX_DATA_01/00.BIN` |
| `src/camera.rs` | `scene_block` (fitted `camera_block.json`), `scene_VP`, `sprite_vertex_z`; closed form (WORLD-CAMERA-GHIDRA §2) + `closed_form_gate` | the emitter USES the fitted model (§5) |
| `src/state.rs` | `tsp_state.codes/predict/state_key/BLEND_PRESET/HOST`; `WorldTemplate.__init__/select` from frozen `src/frozen/world_4445.json` (`capgate/frame_4445.pack` sha256 `2399a079…6ad6`) | |
| `src/bg.rs` | `bg_rule` | |
| `src/world.rs` | `emit_stage`, `emit_world`, `complete_prop`, the preamble block, `sort_key_record` (numpy f32 BLAS orders: sequential FMA for 4×4, `(a0*b0 + a2*b2) + (a1*b1 + a3*b3)` for `v @ M`) | |
| `src/sprites.rs` `Emitter` | the body of `for r in rows:`; `emit_sprites` = the sprite loop; `order_draws` | **W3: the Emitter OWNS its inputs** (Tape, atlases, camera, WorldTemplate, WorldAssets) so it lives inside wasm |
| `src/seq.rs` | `template()` (frozen `src/frozen/template_2574.json`, `frame_2574.pack` sha256 `0b22d966…38b1`), the RRSQ writer | the gate container |
| **`src/pack.rs`** (W3) | the in-memory asset pack: relative path → bytes; `atlas(cid)`, `atlases`, `camera()`, `world_assets(stage)`, `png_page` | the ONE loader for the bin (files from disk) and the browser (bytes from fetch) |
| **`src/feed.rs`** (W3) | `FrameFeed::open(tape bytes, pack, opts)` → `info_json()` → `frame(i)` → `FrameRecord` bytes | the browser feed; format below |
| **`src/web.rs`** (W3, feature `web`) | wasm-bindgen `WebFeed::new(tape, pack_index_json, pack_blob, opts_json)`, `info()`, `frame_count()`, `frame(i)` | `console_error_panic_hook` |
| `src/bin/emit_seq.rs` | the CLI of `tape_to_seq.py`; `--pack DIR` or the source rips; `--camera-gate`; `--feed-bench` | |
| `tools/seq_diff.py`, `tools/gate_l1.sh` | L1/L2 draw-list gates | |
| **`tools/pack_assets.py`** (W3) | the browser asset pack from the existing rips | output gitignored (writes its own `.gitignore`) |
| **`tools/gate_l3.mjs`** (W3) | headless-Chrome pixel gate, `.seq` vs tape-through-worker | puppeteer-core from `render-replica-poc/node_modules` |
| `tools/freeze_template.py` | generator of the two frozen JSONs | |

Browser side (`mvc-live-skins-quarters/d3dcap/replay/`): **`tape-worker.mjs`** (loads `wasm/rr_render.js` +
`rr_render_bg.wasm`, `open` → `opened`, `frame` → transferable FrameRecord), **`tape-player.mjs`** `TapePlayer extends
SequencePlayer` (fetches manifest + files + tape, decodes FrameRecords into the `{head, slice}` shape `replay.mjs` /
`resources.mjs` consume unchanged, 16-frame prepared ring + 16-frame decode-ahead window, per-tape texture/CB/state
tables), `player.mjs` (`_initBlit` factored, `readback()` added; the `.seq` path unchanged), `player.html`
(`?tape=&pack=&start=&count=` → TapePlayer; `__rr.show` async, `__rr.readback`/`__rr.stats` gate hooks).

## 3. FrameRecord v1 (`src/feed.rs`)

```
"RRFR" u32 ver=1  i64 frame_clock
u32 n_states   { u32 id, u32 len, json }                 pipeline state dict (template/world/preamble state minus the
                                                          per-draw keys), FIRST USE ONLY
u32 n_textures { u32 id, u32 w, u32 h, u32 fmt, u32 len, bytes }   first use only (fmt 61 = R8 index tile, 28 = RGBA)
u32 n_cbs      { u32 id, u32 len, bytes }                 constant buffers by content hash, first use only
u32 vb_len bytes   u32 ib_len bytes
u32 n_draws    { u32 state, u32 firstIndex, u32 indexCount, u32 stride, u32 voff,
                 i32 tex0, i32 tex1, i32 vscb[4], i32 pscb[4] }      -1 = none; 60 B per draw
```
JS keys textures `T<id>` / CBs `C<id>`; ids are stable for the feed's lifetime, so `shared.textures` uploads each
texture once per tape. Measured on the stage-13 clip: 719 KB/frame average (409 draws; ~464 KB of it is the arc deck
re-emitted per frame exactly as the Python does — the static-deck buffer of review-render §3.3 is the next lever).

Asset pack (`tools/pack_assets.py <tape> -o packs/<match> [--tape-copy]`): `manifest.json` + `chars/PLxx_{idx.png,
asm.json,lut.json,GFX_DATA_00.BIN,GFX_DATA_01.BIN}` for the roster, `stage/STGxx.json` + `STGxx_tNN.png`,
`tcw/stage_XX/`, `tcw/index.json` + PNGs, `camera_block.json`, `frozen/*.json` (informational; the crate embeds
them), optional `tape.json.gz`. Tape 59613662: 118 files, 21.3 MB (5 characters, stage 0x0D).

## 4. Gates

### L1/L2 — draw-list equality vs `python tape_to_seq.py` (full frame), `tools/gate_l1.sh`

| tape / clip | stage | draws exact / total |
|---|---|---|
| `…_59613662_…` (0.3.39) `--start 1500 --count 60` | 13 | **24,574 / 24,574** (re-run after the W3 refactor: same) |
| same, `--start 6000 --count 60` (clock 7279 @ row 6036) | 13 | 17,969 / 17,969 |
| `…_59613506_…` (0.3.38) `--start 3430 --count 80` (clocks 4445 @ 3437, 4505 @ 3497) | 11 | 21,061 / 21,061 |
| `…_59614009_…` (0.3.41, palrows) `--start 1000 --count 60` | 13 | 24,481 / 24,481 |
| `replay-kit/tapes-kept/…_59612784_…` (v4 rotation) `--start 3245 --count 60` | 0 | 2,588 / 2,588 |

Total 90,673 / 90,673, first differing field: none.

### L3 — browser pixels, `.seq` (Python) vs TAPE through the wasm worker (`tools/gate_l3.mjs`, 2026-09-03)

Headless Chrome (`--enable-unsafe-webgpu`, ANGLE d3d11), tape 59613662 rows 1500..1559 (clocks 2743..), the scene RT
read back with `copyTextureToBuffer` (not the canvas) and hashed per frame:

| path | frames | page load + prepare | show + readback | worker |
|---|---|---|---|---|
| A `gold_13_1500.seq` (73 MB, Python) | 60 | 2.5 s | 3.1 ms/frame | — |
| B tape (3.2 MB) + pack (21 MB) via `tape-worker.mjs` | 60 | 10.7 s (pack fetch + wasm open 1.6 s + 16-frame prime) | 4.4 ms/frame | **27.8 ms/frame avg, 41 ms max**, 719 KB/frame, 473 textures uploaded once |

**Frames byte-exact: 60 / 60. GATE PASS.** Native `emit_seq --feed-bench` on the same rows: 39.8 ms/frame (includes
building the RRSQ-equivalent tables; the wasm figure is the feed only). 27.8 ms/frame is 1.7× real time on one
worker — playback at 60 fps needs the static deck buffer (§3) and/or a second worker; the 16-frame decode-ahead hides
it for scrubbing and short clips today.

### Camera closed form vs the fitted block (report only)
`list6`/`hud` differ only by signed zeros; `list7` max abs 7.6e-6 (the fitted regression's residual on eye×0.1).
Not bit-identical → the emitter keeps the fitted model.

## 5. How to run

```
cd C:\Users\trist\projects\RetroReceipts-agent\rr-render
cargo build --release && cargo test --release --lib
bash tools/gate_l1.sh                                     # L1/L2, six clips + camera gate

# wasm module + glue (wasm-bindgen-cli 0.2.126 matches the crate)
cargo build --lib --release --target wasm32-unknown-unknown --features web
wasm-bindgen --target web --out-dir C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\replay\wasm target\wasm32-unknown-unknown\release\rr_render.wasm

# asset pack for one tape (ROM-derived, self-gitignored)
python tools\pack_assets.py "%LOCALAPPDATA%\RetroReceipts\gs-cache\76561197999665347_76561199789482789_76561199789482789_59613662_76561197999665347.json.gz" -o C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\replay\packs\59613662 --tape-copy

# the browser replay (serve.py in d3dcap/replay), then open:
cd C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\replay && python serve.py
http://localhost:8099/player.html?tape=packs/59613662/tape.json.gz&pack=packs/59613662&start=1500&count=300&auto=1

# L3 gate (serve.py running; the gold .seq = tape_to_seq.py output copied to d3dcap/replay/gold_13_1500.seq)
node tools\gate_l3.mjs --seq gold_13_1500.seq --tape packs/59613662/tape.json.gz --pack packs/59613662 --start 1500 --count 60
```
ROM-derived inputs/outputs stay out of git: `packs/` and `wasm/` carry their own `.gitignore` (`*`), `*.seq` is
ignored by the repo, the frozen JSONs hold state words/hashes/small CBs only.

## 6. What is next

1. **Real-time playback:** static deck VB uploaded once per stage (drops ~464 KB/frame and most of the emit time —
   `emit_stage` is re-run per frame today because the Python does), one index atlas per character (review-render
   §3.3); gate = L3 unchanged (pixels byte-exact). Then a second worker or SIMD if still > 16 ms.
2. **Tape memory in wasm:** `Tape::decode` keeps the JSON rows as `serde_json::Value` (a 40 MB envelope → hundreds of
   MB of heap); a binary row form (review-render §1.2 `tape::rows`) is the fix before phone targets.
3. **Pack distribution (D0):** the pack is built per tape from local rips; the server-side pack + IndexedDB cache
   (review-render §2.5) is the product path.
4. L2 `v3gate.py --emitter rust`; the `complete_prop` clip (stage 16, `…_59613970_…`); stages without host pages (R11).
5. Closed-form camera: settle signed zeros + the `list7` residual against the captured CB, then switch and re-gate.
