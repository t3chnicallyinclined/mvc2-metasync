# rr-render — the Rust tape decoder, frame emitter and browser feed (Track R, W1 + W2 + W3), as built 2026-09-03; FrameRecord v2 + the emit-cost pass 2026-09-04

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

## 3. FrameRecord v2 (`src/feed.rs`)

```
"RRFR" u32 ver=2  i64 frame_clock
u32 n_states   { u32 id, u32 len, json }                 pipeline state dict (template/world/preamble state minus the
                                                          per-draw keys), FIRST USE ONLY
u32 n_textures { u32 id, u32 w, u32 h, u32 fmt, u32 len, bytes }   first use only (fmt 61 = R8 index tile, 28 = RGBA)
u32 n_cbs      { u32 id, u32 len, bytes }                 constant buffers by content hash, first use only
u32 n_blobs    { u32 id, u32 len, bytes }                 SHARED GEOMETRY blobs, first use only
u32 n_vb_segs  { i32 blob, u32 len }                      blob >= 0 = that blob's bytes; -1 = `len` inline bytes
u32 vb_inline_len bytes                                   the inline stream the -1 segments consume in order
u32 n_ib_segs  { i32 blob, u32 len }                      same shape, index words (len in BYTES)
u32 ib_inline_len bytes
u32 n_draws    { u32 state, u32 firstIndex, u32 indexCount, u32 stride, u32 voff,
                 i32 tex0, i32 tex1, i32 vscb[4], i32 pscb[4] }      -1 = none; 60 B per draw
```
JS keys textures `T<id>` / CBs `C<id>`; ids are stable for the feed's lifetime, so `shared.textures` uploads each
texture once per tape.

### 3.1 Shared geometry (v2, 2026-09-04) -- the static deck stops being re-sent

v1 re-sent the **whole** vertex and index buffer every frame. On the stage-13 clip that was 719 KB/frame, **~464 KB of
it the arc stage DECK** -- geometry whose bytes depend only on the deck colour and are therefore identical for a whole
match. v2 extends the first-use-only idea from textures/CBs/states to geometry:

- a **blob** is a run of vertex bytes or index words sent once, under an id stable for the feed's lifetime
  (`util::BlobStore`); the deck is one vertex blob plus one index blob per deck colour;
- a frame's VB and IB are each a **list of segments** (`util::VbSegs` / `IbSegs`), every segment either inline bytes
  this record carries or a reference to a blob;
- **the concatenation of a frame's segments is byte-for-byte the buffer v1 sent whole.** `VbSegs::len()` counts the
  total, so every `voff` and `firstIndex` computed during emit is unchanged, no draw is remapped, and nothing above
  the sink type knows sharing exists. `flatten()` reproduces the whole buffer for the `.seq` writer, which is why the
  L1/L2 gate output is byte-identical (verified: same md5 as the pre-sharing writer on five clips).
- the deck's per-mesh index runs are contiguous by construction (`DeckGeo.first_rel` is the running vertex count), so
  the whole deck is the single ascending run `base..base+total` -- exactly the words the per-frame loop pushed. The
  index blob is keyed by that `base` and rebuilt if it ever moves.

Browser side, `resources.mjs geometryBuffer()` writes each segment straight into the GPU buffer at its running offset
(`queue.writeBuffer`), so sharing costs **no CPU copy at all** -- assembling a ~700 KB `Uint8Array` per frame on the
main thread would have handed back most of what the worker saved. The `.seq` path (one whole buffer, `{off,len}`)
goes down the same function's first branch, unchanged.

### 3.2 The rest of the frame: intern the state map (2026-09-04)

The deck was the recorded lever but not the biggest one. Profiling with `RR_PROF=1` (per-phase ms every 60 rows,
`util::prof`) put **2.4 ms of a 12 ms frame inside `WorldTemplate::select`** alone: it deep-cloned a ~15-key nested
JSON state map for every one of ~500 draws a frame, `feed.rs` then re-walked each clone to hash it for a state id,
and the whole lot was freed again -- allocator churn, not arithmetic. Three changes, all pure memoisation:

| change | what it removes |
|---|---|
| `WorldTemplate::select` memoised on `(ps, samp, blend, depth, cull)`, result interned as `Rc<Map>` with its content fingerprint (`state.rs`; `draw_state` / `preamble_state` likewise) | ~500 deep map clones + frees per frame. The `"i"` every caller stripped afterwards is stripped once, in the intern, so the shared map needs no mutation |
| `Draw` carries `state_fp` (`util::state_fp`), so `feed.rs state_id` is a `u64` lookup | ~500 recursive JSON hashes per frame |
| `deck_pscb` memoised per pixel-state variant (`WorldState.pscb_memo`); the scene block, its `sha8` and its V/P decomposition memoised per `(cam, variant)` inside `emit_world`; `world_<key>` texture keys memoised | ~1,500 SHA-256 of frozen template buffers, plus one `format!` per record per frame |

`order_draws`' bit-13 raster patch (the one place a state map is mutated after selection) uses `Rc::make_mut` and
recomputes the fingerprint. Every emitter stat line, warning and count is byte-identical to before the pass.

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

Total 90,673 / 90,673, first differing field: none. **Re-run 2026-09-04 after FrameRecord v2 and the emit-cost
pass: the same 90,673 / 90,673, and the `.seq` bytes themselves are md5-identical to the pre-change writer.**
(`gs-cache` is a ring and had rolled over; `gate_l1.sh` now reads the four gate tapes from `replay-kit/tapes-kept`.)

### L3 -- browser pixels, `.seq` (Python) vs TAPE through the wasm worker (`tools/gate_l3.mjs`, re-run 2026-09-04)

Headless Chrome (`--enable-unsafe-webgpu`, ANGLE d3d11), tape 59613662 rows 1500..1559 (clocks 2743..), the scene RT
read back with `copyTextureToBuffer` (not the canvas) and hashed per frame:

| path | frames | page load + prepare | show + readback | worker |
|---|---|---|---|---|
| A `gold_13_1500.seq` (73 MB, Python) | 60 | 2.2 s | 3.2 ms/frame | -- |
| B tape (3.2 MB) + pack (21 MB), FrameRecord **v1** | 60 | 10.7 s | 4.7 ms/frame | 11.63 ms/frame avg, 26.5 max, **719 KB/frame** |
| B tape + pack, FrameRecord **v2** | 60 | 10.4 s | 4.0 ms/frame | **2.86 ms/frame avg, 26.7 max, 217 KB/frame**, 473 textures uploaded once |

**Frames byte-exact: 60 / 60 on both. GATE PASS.**

### Seek gate (`tools/gate_seek.mjs`, stage-9 pack, rows 600..719)

`3/3 frames byte-equal to the sequential render` -- 60 = `7d1728da669e`, 100 = `a8ad740954f2`, 119 = `00611cd3f402`:
the same three hashes as before the change.

### Speed, measured on the stage-9 pack (rows 600..719, ~507 draws/frame)

Native `emit_seq --feed-bench`, and the browser worker driven through `player.html` (`__rr.timings()`):

| | v1 | v2 |
|---|---|---|
| native ms/frame (stage 9 / stage 13) | 9.6-9.8 / 7.7-8.8 | **1.5-1.9 / 1.7-1.9** |
| KB/frame (stage 9 / stage 13) | 706 / 670 | **320 / 164** |
| browser worker: median | 11.00 ms | **2.50 ms** |
| p95 / p99 | 16.50 / 19.40 ms | **4.10 / 5.30 ms** |
| frames over the 16.7 ms budget | 5 / 120 | **1 / 120** -- frame 0 only |
| frames over 8 ms | 108 / 120 | **1 / 120** |

Frame 0 costs ~32 ms in both (cold: it builds the deck cache and serialises the first-use tables) and is absorbed by
the 16-frame decode-ahead prime before playback starts. Every subsequent frame sits at ~15% of the frame budget.

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
# the PWA serves its own copy of the engine: copy the glue + .wasm into pwa/static/replay/engine/wasm/ and BUMP
# ENGINE_BUILD in pwa/src/lib/replay/engine.ts (the engine files are cached by URL version). d3dcap/replay's
# copies of tape-player.mjs / resources.mjs / player.mjs / replay.mjs must stay byte-identical to the PWA's.

# asset pack for one tape (ROM-derived, self-gitignored)
python tools\pack_assets.py "%LOCALAPPDATA%\RetroReceipts\gs-cache\76561197999665347_76561199789482789_76561199789482789_59613662_76561197999665347.json.gz" -o C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\replay\packs\59613662 --tape-copy

# the browser replay (serve.py in d3dcap/replay), then open:
cd C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\replay && python serve.py
http://localhost:8099/player.html?tape=packs/59613662/tape.json.gz&pack=packs/59613662&start=1500&count=300&auto=1

# L3 gate (serve.py running; the gold .seq = tape_to_seq.py output copied to d3dcap/replay/gold_13_1500.seq)
node tools\gate_l3.mjs --seq gold_13_1500.seq --tape packs/59613662/tape.json.gz --pack packs/59613662 --start 1500 --count 60

# seek gate (serve.py running) -- seek must equal sequential, byte for byte
node tools\gate_seek.mjs "http://localhost:8099/player.html?tape=packs/local_stage9/tape.json.gz&pack=packs/local_stage9&start=600&count=120&auto=1" 60 100 119

# the PWA's own gates (vite dev on :5173, serve.py on :8099)
cd C:\Users\trist\projects\RetroReceipts-agent\pwa && node scripts\smoke-replay.mjs --l3 http://localhost:8099
node scripts\smoke-replay.mjs --art
```
ROM-derived inputs/outputs stay out of git: `packs/` and `wasm/` carry their own `.gitignore` (`*`), `*.seq` is
ignored by the repo, the frozen JSONs hold state words/hashes/small CBs only.

## 6. What is next

1. ~~Real-time playback: static deck VB uploaded once per stage.~~ **Done 2026-09-04** -- see 3.1 / 3.2; the worker
   sits at 2.5 ms median against a 16.7 ms budget. Still open: one index atlas per character (review-render 3.3),
   and the cold first frame (~32 ms) could pre-build the deck cache at `open` instead of on frame 0.
2. **Tape memory in wasm:** `Tape::decode` keeps the JSON rows as `serde_json::Value` (a 40 MB envelope -> hundreds of
   MB of heap); a binary row form (review-render 1.2 `tape::rows`) is the fix before phone targets.
3. **Pack distribution (D0):** the pack is built per tape from local rips; the server-side pack + IndexedDB cache
   (review-render 2.5) is the product path.
4. L2 `v3gate.py --emitter rust`; the `complete_prop` clip (stage 16, `...59613970...`); stages without host pages (R11).
5. Closed-form camera: settle signed zeros + the `list7` residual against the captured CB, then switch and re-gate.

## 7. Invariants (deliberate properties that are easy to lose in a refactor)

Each of these is a decision, not an accident. If you are about to change one, the note says what it buys and
which gate catches you.

**7.1 The torn-guard verdict is a pure function of the TAPE, never of render order.**
`sprites.rs emit_row` decides "is this row a torn capture?" from `Emitter::node_counts` — a snapshot of the
pristine per-clock node counts taken in `new()`. It must NOT read `self.nodes`, because *the guard itself
mutates `self.nodes`* (it substitutes the held list at that clock). Reading the mutated map would make a row's
verdict depend on which rows were rendered before it, so a seek and a sequential play could disagree about
whether a frame is torn at all. Keeping the counts pristine is what makes seeking safe here.
*Gate:* `tools/gate_seek.mjs` over a window containing a held row —
`packs/59613662 start=2190 count=60`, targets `26 27 28 40` (clip frame 27 = row 2217, a held row).
4/4 byte-equal to the sequential render, 2026-09-04.
⚠ Note the limit of the claim: the *verdict* is order-independent; the *substituted content* still comes from
`last_nodes`, which is emission-ordered. That is measured equal on the held frame above, not proven in general.

**7.2 The torn test is a strict SUPERSET of the old absolute one — keep both disjuncts.**
`torn = (n < 2 && prev >= 3) || n * TORN_FACTOR < min(prev, next)`. The old absolute disjunct is not dead
weight: in a run of *consecutive* torn rows the relative test's neighbours are themselves torn, so `min(prev,
next)` collapses and only the absolute test still fires. Dropping it regressed 8–13 rows per tape on the four
gate tapes when first tried. The superset shape is also what makes the change one-directional: no row that was
held before can stop being held, which is what kept the re-baseline reviewable.
`TORN_FACTOR = 2` is a stated margin (the row must hold less than half the size its neighbours agree on), not a
fit; `TORN_SCAN = 8` is the engine's own GGPO rollback horizon. Mirrored verbatim in `tape_to_seq.py`.

**7.3 `resolve_palrow_slots` lives in rr-render ONLY — do not port it to the oracle.**
The staged palette blocks are not always in fighter-slot order (prod tape `..._59618234`: every P1 fighter's
block sat at the odd index and vice versa, so each fighter wore the other side's character's palette). The
resolver re-derives the mapping by byte-equality against `PLxx_lut.json` ROM banks. `tape_to_seq.py` has no
equivalent **by decision**: a second copy of new, non-trivial logic would have to be kept in step forever, to
remove one confusing failure message. No gate tape triggers it (checked against all 21 palrows tapes in
`replay-kit/tapes-kept`, 2026-09-04). `gate_l1.sh` prints the emitter's own `palrow_note` if it ever does, with
instructions to re-run the rs side with `--no-palrow-resolve` before touching anything.

**7.4 The L3 artefacts are a MATCHED VINTAGE — regenerate the gold `.seq`, the pack and the rips together.**
On 2026-09-04 `gold_13_1500.seq` and `packs/59613662/` were found to both predate commit `a42d9de` (the HUD
portrait/name plate now come from each fighter's own character DAT). The pack had no `portraits/` directory, so
the tape path reproduced the *old* pages and matched the *old* gold: **L3 passed 60/60 while validating a
pre-fix asset vintage against itself.** A freshly generated seq failed 0/60 at the same window; the diff was
1200 draws, all `tex[0]`, all 4096 B = 32×32 portrait pages. Both were re-baselined (old gold archived as
`gold_13_1500.seq.pre20260904`). This is the RE-METHOD **M4** failure mode — a gate that cannot fail is worse
than one that does, because it is reported as success. Before trusting an L3 pass, check that the pack and the
gold were built after the newest change to the assets they carry.
