# WORKSTREAM-CLIENT-REPLAY — render-pipeline / sprite-client review (2026-09-03)

*Reviewer: mvc2-sprite-render-expert. Scope: the `rr-render` port of the Python emitter, the asset plan, the
per-frame client budget, the gate plan. Everything below was measured against files on disk today; each claim is
tagged **CONFIRMED** (read in code / measured) or **INFERRED** (derived; says what would confirm it) or **UNKNOWN**.
Nothing was committed. The draft (`WORKSTREAM-CLIENT-REPLAY.md`) is not edited.*

RE METHOD restated: the emitter port is not an RE task — every rule it ports is already CONFIRMED and gated
(`RE-METHOD.md` "already settled" table). Where this review touches an unsettled rule it names the gate, not a
new derivation. Step of the method for this document: none (consumption of settled results).

---

## 0. Verdict in five lines

1. The **port target is `tape_to_seq.py main()` plus `tsp_state.py` and the `Atlas` class**, not the vendored
   `web/tapecanvas/renderer/sprite-client.mjs`. The JS emitter (`buildEmitterDrawList`) is a third,
   knob-driven fork of the placement law and is superseded by the 100 %-gated Python (`v3gate.py`). Retire it
   from the replay path together with `sprite-gpu.mjs`, `tape-adapter.mjs`, `stage-client.mjs`, `hud-*.mjs`.
2. **`replay.mjs`, `state.mjs`, `resources.mjs`, `sprite.wgsl` and the blit/ring half of `player.mjs` survive**
   as the WebGPU player; only `loadSequence` (RRSQ + 730 KB/frame of JSON) is replaced by a binary frame feed.
3. The **asset plan has a hole the draft does not state: a phone has no `game_50.arc`.** D1 (client-side rip) is a
   desktop-once step; mobile needs an asset *distribution* decision before E2 can ship on the target device.
4. Per frame today (stage-13 seq, measured): **393 draws avg / 476 max, 547 KB VB, 55 KB IB, 100 KB uniforms**.
   85 % of the VB is the static stage deck re-emitted every frame; 1,628 of 1,665 textures are per-part R8 tiles.
   Two structural changes (static deck buffer, one index atlas per character) take the per-frame payload to
   ~100–200 KB and the texture set to a constant ~60 textures — that is the mobile budget.
5. Gate order: decoder equality → draw-list equality vs Python (exact, per draw) → the existing capture gates run
   on Rust output through the same Python gate scripts → pixel readback. All tools exist; two adapters are new.

---

## 1. Module map — Python function → Rust/WASM home → JS it replaces or reuses

### 1.1 The Python functions being ported (listed after reading the files)

`d3dcap/replay/tape_to_seq.py` (1,270 lines): `sha8`, `nl_triangles`, `nl_groups`, `decode_anodes`, `scene_block`
(+ the fitted `camera_block.json` model), `scene_VP`, `sort_key_record`, `sprite_vertex_z`, `order_draws`,
`WorldTemplate.__init__`, `WorldTemplate.select`, `load_pack_rrpk`, `Atlas.__init__`, `Atlas.row_of`,
`Atlas.flag_of`, `Atlas.get`, `Atlas.part_bitmap`, `Atlas.palette`, `template`, `main` and its closures
`intern`, `next_sub`, `emit_stage`, `emit_world`, `pal_for_row`, plus three inline blocks of `main` that have no
function name: the **v3/v4 node + palette decode**, the **owner/bank resolution** (`bank_slot`,
`unknown_slots`), and the **sprite quad loop** (LAYERZ order → per-record placement → vertex/index/draw emit) and
the **frame head + RRSQ writer**.
`d3dcap/replay/tsp_state.py` (138 lines): `codes`, `state_key`, `captured`, `predict`; tables `BLEND_PRESET`, `HOST`.
`d3dcap/replay/v3gate.py` (366 lines): `rawcells`, `gfx1dims`, `atlas`, `paint_rotated`, `emit_frame`, `main`.
`emit_frame` is the *gate painter* (index raster vs Steam's quads); its sprite rules are the same rules
`tape_to_seq` emits as quads: LAYERZ sort, rotation gate, owner→cid, `floor()` of the 640-space origin,
`hf = flags & 0x8000`, `vf = flags & 0x4000`, scale-walker logical clip (`sid & 0x8000`), tiled flip anchoring
about the logical box, `rot180`, general rotation about the hotspot in 640-space.

Count: **35 emitter functions/blocks → 9 Rust modules**; the ripper side (§2.4) is another ~30 functions → 4 modules.

### 1.2 The map

| Python (file → function) | Rust home in `rr-render` | Replaces (JS) | Reuses (JS) | Status |
|---|---|---|---|---|
| `tape_to_seq.main` node/pal decode (`nodes_enc` stride 44/50/54, `pals` 32 B ARGB4444) | `tape::nodes` — record struct shared with the agent (`RetroReceipts-agent/agent/src/reader.rs` `NODES_STRIDE = 54`, the `nodes_enc` string at the tape writer is the authoritative layout) | `tape-adapter.mjs decodeNodesBytes / decodePals` | — | CONFIRMED layout (reader.rs writer + Python reader agree, both read) |
| `decode_anodes` (anodes stride 96/100, aobjs interned NL objects, 0x50 record headers) | `tape::world` | `tape-adapter.mjs decodeANodes / decodeAObjs` | — | CONFIRMED |
| `main` row/schema handling (`schema` string, `eyeX/eyeY/zoom/cam_state/deck/blackout/stage_id`) | `tape::rows` (binary form needed — the JSON rows are 6.8 MB per match today) | `tape-adapter.mjs bindSchema` | — | CONFIRMED columns; binary encoding is NEW |
| `nl_groups` / `nl_triangles` (polygon groups, Steam strip winding, ref-vertex mode) | `nl::groups` | none (the vendored `stage-client.mjs _build` is a different, ModNao-shaped decode) | — | CONFIRMED (worldgeo_gate 99.6 %) |
| `tsp_state.codes / predict / HOST` | `state::tsp` (pure fn, table-driven) | none | `state.mjs toBlendState/toSampler/toDepthStencil/toPrimitive` consume the same D3D enums → **unchanged** | CONFIRMED (824/824) |
| `WorldTemplate.__init__/select`, `template()` (state objects lifted from `capgate/frame_4445.pack`, `frame_2574.pack`) | **no port.** Replace with `state::webgpu`: the full state tuple as constants keyed by `tsp_state.state_key`. The template also supplies `bfactor, smask, vp, scissor, il, stride, psFog, vs/ps hashes` and the PS constant buffers (fog, alpha ref) — these must be enumerated from the two template packs once and frozen as constants | — | `replay.mjs variantFor / _pipeline` keyed on the same fields | INFERRED constant; gate = `WorldTemplate.select` stats show 0 "patched fallback" on the gold frames after the constants are frozen |
| `scene_block` (fitted 108-float model) + `scene_VP` | `scene::camera` — the **closed form** (`WORLD-CAMERA-GHIDRA.md`: P from fov/y-offset, V = LookAt(eye,target,roll); HUD block angle 0x4000, V = I) | `stage-client.mjs setCamB/_projectB` (Option-B camera) | — | CONFIRMED closed form 16/16 bit-identical; the Python still ships the fitted model → the port must beat the oracle here (see §4.2) |
| `sort_key_record`, `sprite_vertex_z`, `order_draws` | `order::flush` (two-phase: cat 0/1 submission order, cat 3 by (−key, seq)) | `sprite-gpu.mjs render` z-ranking (Z_LO..Z_HI rank), `pvr2-renderer.mjs` reversed-Z | — | CONFIRMED comparator; frame 4505 118-vs-122 open (RE-C2) |
| `Atlas.__init__` (idx pixels, parts rects, assemblies, LUT banks, per-record rows/flags from raw GFX2, logical dims from raw GFX1 header) | `sprite::atlas` — read **raw GFX1/GFX2/PAL** directly (GFX2 = 26–66 KB per char vs `_asm.json` 0.25–1.2 MB; the deployed `_asm.json` drops the flags word and carries storage dims, so the Python already goes back to the ROM files for both) | `sprite-client.mjs loadAsmChar` (`_parts.json`+`_asm.json`) | — | CONFIRMED (Atlas reads `dasm_PLDAT/.../GFX_DATA_00/01.BIN` today) |
| `Atlas.part_bitmap` (vertical flip of every packed part; logical top-left clip) | `sprite::atlas::part` | `sprite-client.mjs` emitFlipY knob | — | CONFIRMED (scene_5630) |
| `Atlas.palette` (costume → row block 8·c; row within block per record) + `pal_for_row` | `sprite::palette` (256×1 RGBA page per (char, row)) | `sprite-gpu.mjs setSkin/setCharLUT` | `sprite.wgsl fs_character` (idx → `tPal`) | CONFIRMED rows; per-slot bank (RE-C1) open |
| `main` sprite loop: LAYERZ order, owner/bank resolve, `floor(sx)*3/5`, placement (bit-15 vs tiled), flips, rot180, general rotation in 640-space, per-record depth `D = depth + 0.001·ri`, UV winding for mirror, vertex pack (stride 40) | `sprite::emit` | `sprite-client.mjs buildEmitterDrawList / buildAssemblyDrawList / _emitEffectQuad` (833 lines, `window._asmCfg` knobs, `-(dx+w)` mirror — differs from the gated `-dx` law) | — | CONFIRMED 100 % on 30 captures (v3gate); rotation general path: memory `mvc-rotation-path-180` says 100 % on the rocket capture, the code comment in `tape_to_seq` still says "NOT pixel-gated" → INFERRED until `rotgate.py` is re-run on `cap_sent-rocket` |
| `v3gate.emit_frame` / `paint_rotated` | **no port** — stays the Python gate (index raster vs Steam quads). Rust output is gated *through* it (§4) | — | — | gate tool |
| `emit_stage` (arc deck model 0 at identity, deck colour, blackout) | `world::deck` — **static VB uploaded once per stage**, drawn every frame (the Python re-appends 11,877 vertices per frame) | `stage-client.mjs` | `sprite.wgsl vs_world/fs_stage_*` | CONFIRMED mechanism; the once-per-stage buffer is INFERRED equivalent (same bytes, same draws) — gate = draw-list equality after normalising `firstIndex` |
| `emit_world` (lists 5/6/12/13, 7/8/9, 11: CBWorld from node matrix, per-list scene block, per-record colour packing R,G,B,A with node/alpha multipliers, kind 0/2/3, bit-13 cull inheritance, category/sort key) | `world::emit` | `hud-client.mjs`, `hud-pvr2.mjs` (procedural bars/digits over a DC VRAM slab `hud/hud_vram.bin` — not the game's real HUD, per `mvc-hud-list0b-live-re`) | `sprite.wgsl fs_hud / fs_stage_texalpha` | CONFIRMED |
| `intern` + frame head + RRSQ writer | `frame::build` → **binary frame record** (`vb`, `ib`, `draws[]` as fixed-width structs, texture keys as u32 ids) — the RRSQ JSON head is 218.6 MB for 300 frames (730 KB/frame) and is not a worker→main format | `player.mjs loadSequence` (and the `tables` rehydration from `pack_sequence.py`) | `player.mjs SequencePlayer.ensure/prepareAhead/evict/draw` (blit + ring), `replay.mjs Replayer.prepare/use/render`, `resources.mjs createResources/vertexLayoutFor`, `state.mjs`, `sprite.wgsl` | NEW format; the consumers are CONFIRMED working |
| `sha8` | `util::sha8` (only for asset/content keys) | — | — | trivial |

**What survives verbatim (CONFIRMED by reading):** `d3dcap/replay/sprite.wgsl` (the literal port of the four
Steam shaders; header forbids routing through `pvr2-renderer.mjs`), `replay.mjs` (pipeline cache keyed by
`pipelineKey` + il/stride, bind-group cache, per-draw dynamic uniform offset, `readback`), `state.mjs` (D3D
enum → WebGPU), `resources.mjs` (shared texture map, 256 B uniform stride, `vertexLayoutFor` from the captured
input layout — this layout must become a constant in the frame format), `player.mjs` minus `loadSequence`.

**What does NOT survive (and why):**
- `web/tapecanvas/renderer/sprite-client.mjs` (2,837 lines; diverged from `maplecast-flycast/web/webgpu/sprite-client.mjs`, 2,613 lines — two forks, neither the oracle). Its `buildEmitterDrawList` carries live-tuning knobs (`tileScale`, `faceInv`, `emitFlipY`, `_asmCfg`) that the Python law does not need, and mirrors as `-(dx+w)` where the captures say `-dx`.
- `sprite-gpu.mjs` (`SpriteGPU.render`: RGB nearest-match recolour + LUT path, run batching, rank-based depth) — a second renderer with different depth semantics (`depth32float` + GREATER rank) from the gold path (`depth24plus-stencil8`, forward Z from `FUN_1408432e0`).
- `pvr2-renderer.mjs` — DC TA semantics (reversed-Z, log depth); correct for the flycast lanes, wrong for Steam's stream (`sprite.wgsl` header, CONFIRMED).
- `tape-adapter.mjs` — feeds the `SpriteClient` slot shape; v2 columns; de-jitter and hitstun-edge flash heuristics (both explicitly INTERIM in the file).
- `stage-client.mjs` (Option-B camera, `DECK_Z_BY_FILE`), `hud-client.mjs`, `hud-pvr2.mjs` (DC-VRAM HUD slab + font overlay — violates "render only the game's real assets" once list-11 nodes render).
- `frame-decoder.mjs`, `fzstd.mjs`, `ta-parser.mjs`, `texture-manager.mjs`, `post-process.mjs`, `shaders.mjs` — DC wire only.

One idea from `sprite-gpu.mjs` is worth carrying: **one index texture per character** (`setIndexedAtlas`) instead of
the seq's per-part R8 textures (1,628 distinct in 300 frames). With POINT sampling and texel-aligned rects the
fetched texels are identical (INFERRED; gate = pixel readback equality against the per-part build, §4.4).

---

## 2. Asset plan

### 2.1 What the emitter reads today (CONFIRMED from `tape_to_seq.py` constants and `Atlas`)

| Asset | Path today | Consumed by | Measured size |
|---|---|---|---|
| Character index pixels | `maplecast-flycast/web/test-atlas/chars/PLxx_idx.png` | `Atlas.__init__` (R channel) | 59 chars, 49.8 MB total, avg 844 KB (PL00PAK is a duplicate of PL00) |
| Part rects + assemblies | `PLxx_asm.json` (`parts`, `assemblies`) | `Atlas` | 36.6 MB total, avg 621 KB — JSON bloat of a 26–66 KB GFX2 table |
| Palette banks | `PLxx_lut.json` | `Atlas.palette` | 2.1 MB total, avg 36 KB |
| Raw GFX2 (flags word, per-record rows), raw GFX1 header (logical dims) | `dasm_PLDAT/Output/PLxx_DAT/*GFX_DATA_01.BIN`, `*GFX_DATA_00.BIN` | `Atlas.__init__`, `v3gate.rawcells/gfx1dims` | GFX2 4.1 MB / 60 chars; GFX1 46.9 MB / 60 chars; PALETTE 0.2 MB |
| Also on disk, NOT consumed by the emitter | `PLxx_parts.png` 63.5 MB, `PLxx_parts.json` 8.9 MB, `PLxx_preview.png` 7.5 MB | `sprite-client.mjs loadAsmChar` only | drop |
| Stage geometry | `maplecast-flycast/atlas/stages/STGxx.json` (model-0 meshes, `tris` as JSON) | `emit_stage` | 18 files, 1.2–1.8 MB each; STG0D model 0 = 106 meshes, 3,959 tris, 11,877 verts |
| Stage textures | `d3dcap/replay/tcw_pages/stage_XX/` (HOST decode, `rip_texbank.py --bank stage`) — falls back to `STGxx_tNN.png` (the WRONG `rip_stage.py` decode) | `emit_stage`, `emit_world` | stage_05 12 pages 677 KB; stage_0D 8 pages 772 KB; stage_0F 13 pages 888 KB; stage_02 17 pages 832 KB. Only 4 of 19 stages are host-ripped |
| Effects bank 0xC50 | `tcw_pages/arc_rip/` (26 pages, 473 KB) | `emit_world` (lists 7/8/9) | from AFS 799 (152 KB POL) + 800 (366 KB TEX) |
| HUD bank 0xC90 pages | `tcw_pages/hud_rip/` (14 pages, 67 KB) | `emit_world` (list 11) | from AFS 835 (89 KB) + 836 (120 KB) |
| HUD-bank part models (combo counter, list 0xC) | `tcw_pages/parts/` (132 model JSONs, 966 KB) | `parts_gate.py`; **not yet in `tape_to_seq`** (RE-C3 / open tweak 3) | — |
| Capture-derived pages (portraits 0xC99..0xCA8, the one-off TCWs) | `tcw_pages/*.png` + `index.json` (73 entries, 77 PNGs, 612 KB; whole library 5.4 MB) | `WorldTemplate.pages` | capture-only until RE-C4 |
| Common bank 0x810 | not ripped | UNKNOWN whether any tape node binds it (`tape_audit.py` G would say) | AFS 837 (121 KB) + 838 (1,464 KB) |
| Captured D3D state templates | `frame_2574.pack`, `capgate/frame_4445.pack` | `template`, `WorldTemplate` | ROM/capture-derived; must become constants (§1.2) |

### 2.2 Where it all is in the Steam archive (CONFIRMED by byte search this session)

`game_50.arc` = 65.0 MB on disk → one zlib entry → 112.6 MB IBIS/AFS image, 890 entries (`rip_texbank.load_afs`,
0.5 s in Python).
- **Character DAT = AFS entry `209 + cid`** (memory `rr-sprite-render-pipeline`; verified again here: PL00 = entry
  209 (506 KB), PL17 = 232 (1,072 KB), PL32 = 259 (1,198 KB); entry header `u32@0 = 0x20` GFX1, `@4` GFX2, `@8`
  PALETTE; the DC `GFX_DATA_00/01/PALETTE` bytes are found verbatim at those offsets). 60 entries = **54.7 MB**.
- Stages: POL `801 + 2·id` (89–189 KB), TEX `802 + 2·id` (1.0–1.6 MB); all 19 = 31.5 MB.
- Effects 799/800, HUD 835/836, common 837/838 (as in `rip_texbank.BANKS`).

So every asset class the render model consumes is arc-derivable **except** the capture-derived pages (portraits,
RE-C4) and the list-0xC part draws are arc-derived but not yet emitted.

### 2.3 Per-match client asset budget (derived from the sizes above)

| Class | Raw arc bytes | Decoded client form | Notes |
|---|---|---|---|
| 6 characters | ~5.5 MB (6 × 0.4–1.2 MB DAT) | 6 index atlases: PLxx_idx.png 0.45–1.06 MB each, or raw 4bpp ≈ half of that; GFX2 26–66 KB; PAL 1.8–7.9 KB | 3 MB–6 MB |
| 1 stage | 0.17 MB POL + 1.0–1.6 MB TEX | geometry as binary vertex arrays (STG0D: 11,877 × 40 B = 464 KB) + 8–17 RGBA pages (0.7–0.9 MB PNG; raw RGBA 2–4 MB) | ≤ 5 MB raw |
| Effects bank | 0.5 MB | 26 pages, 473 KB PNG | constant |
| HUD bank | 0.2 MB | 14 pages 67 KB + 132 part models (JSON 966 KB → binary ≈ 150 KB) | constant |
| Capture pages | — | 612 KB | until RE-C4 |
| **Per match** | **~8 MB read from the arc** | **~6–12 MB resident (raw RGBA)** | well under the ~100 MB texture ceiling in §10.2 |

### 2.4 Client-side ripper feasibility in WASM

The Python rippers and what a Rust port needs:

| Ripper | Functions to port | Feasibility | Gate |
|---|---|---|---|
| `rip_texbank.py` | `load_afs`, `afs_entry`, `tex_records`, `_twiddle_index_table`, `detwiddle16`, `expand_vq`, `to_rgba_host`, `decode_host`, `rip_bank` | pure byte code; inflate via `miniz_oxide`/`flate2` | sha per page vs `rip_texbank.py --out` `index.json` (16/16 byte-exact vs captures already) |
| `rip_stage.py` (`maplecast-flycast/tools/`) geometry only | `scan_texture_headers`, `scan_model`, `vertex_addressing_mode`, `wrap_flags`, `_load_matrices` — **not** `decode_texture` (wrong; use texbank) | pure byte code | vertex set vs `STGxx.json` `tris` (and `worldgeo_gate.py` 99.6 %) |
| `rip_parts.py` | `load_pol`, `model_offsets`, `records`, `rip_model` (+ `nl_groups`) | pure byte code; the static part LISTS come from the exe dump (`--lists`, `MVC_DUMP`) → ship `partlists.json` as data, not rip it on the client | `parts_gate.py 4445 4447 4474 7441` (82/82) |
| `tools/rip_gfx2_assembly.py read_cells` | 8-byte record walk, cumulative pen (`px += dx; py -= dy`) | trivial | assemblies == `PLxx_asm.json` |
| GFX1 pixels | `mvc2-skin-studio/tools/extract_gfx1_atlas.py decodeA` + full-dims PAL4 detwiddle | **CONFIRMED offline-decodable**: that tool is bit-exact vs 6 live captures and 1,533 Ryu sels; `rr-sprite-render-pipeline` memory: Steam's `FUN_140614210` is the same decoder. ⚠ `rip_gfx2_assembly.py`'s header still says the offline LZSS is a "CONFIRMED DEAD END" — that note is stale (it was a decoder bug, per the extract tool's header) | `_idx.png` byte-equal per char; M6 (captured 32×32 pages match `PLxx_idx.png` 1.000) closes the loop to Steam |

Memory cost in a worker: inflating the whole 112.6 MB image plus the 65 MB source is ~180 MB — too much for a
mid phone (INFERRED). Two mitigations, both cheap: (a) streaming inflate that keeps only the AFS TOC (at +0x40)
and the requested entries; (b) do the rip **once on the desktop** (the agent already has the arc path) and put the
results in the user's account store. Which brings the real gap:

**⚠ R1 — the phone has no `game_50.arc`.** The draft's D1 ("user picks the arc file once") only works on the
machine that owns the game. For "any device (phone included)" the assets must arrive from either (i) the user's
own upload (agent rips → server stores under the user's SteamID, BYOR preserved, ~8 MB per stage/roster
combination or ~90 MB for the full library) or (ii) the licensed pack of §6.2. This decision gates E2 on mobile
and belongs before D1 in the order (§5).

### 2.5 IndexedDB cache layout (proposal; no IndexedDB code exists in the repo today — grep confirmed)

DB `rr-assets`, versioned by `ripperVersion` (the Rust crate version) and keyed by `arcSha` (sha256 of the 65 MB
arc, or of the server pack):

| store | key | value | size/entry |
|---|---|---|---|
| `meta` | `arcSha` | `{ ripperVersion, buildId, rippedAt, entriesSha[] }` | bytes |
| `char` | `${arcSha}/${cid}` | `{ gfx2: Uint8Array (26–66 KB), pal: Uint8Array (1.8–7.9 KB), gfx1hdr: Uint16Array (lw,lh,sw,sh per sel), idx: { w, h, data: Uint8Array R8 }, rects: Uint32Array(sel → x,y,w,h) }` | 0.5–1.2 MB |
| `stage` | `${arcSha}/${stageId}` | `{ deck: { vb: Float32/Uint8 interleaved stride 40, meshes[]: { first, count, texIndex, pcw, isp, tsp, centre, radius } }, pages: [{ tcw, w, h, rgba }] }` | 3–5 MB |
| `bank` | `${arcSha}/arc|hud|common` | `{ pages[], models[] (parts) }` | 0.2–1 MB |
| `page` | `${tcwKey}` | capture-derived pages (portraits) — from the server, not the arc | 612 KB total |
| `tape` | `${matchId}` | the fetched tape (binary) for offline replay | 1–4 MB |

Store raw `Uint8Array`s (structured-clone, no base64). Evict by LRU on `char`/`stage` above ~150 MB. The decoded
RGBA pages can be re-derived from the raw TEX bytes, so cache the TEX entry (1.6 MB) rather than the 2–4 MB
RGBA if space matters.

---

## 3. Per-frame data flow and budgets

### 3.1 Numbers from the current player (CONFIRMED by parsing the seq headers this session)

`tape_v5_59613662_stage13.seq` (Tris's "gold standard" render; 300 frames, `tape_to_seq.py` output):

| metric | value |
|---|---|
| draws / frame | min 321, **avg 393**, max 476 (118,017 total) |
| composition (frame 2843, 429 draws) | 321 `vs_world|opaque` (11,898 indices ≈ the STG0D model-0 deck, 11,877 verts) · 73 `vs_world|texalpha` (2,277 indices: props, effects, HUD) · 35 `vs_flat|indexed` (sprites, 210 indices) |
| vertex buffer / frame | **547 KB avg**, 574 KB max (stride 40) — ~464 KB of it is the deck |
| index buffer / frame | 55 KB avg |
| per-draw uniforms | 256 B × 393 = **100 KB** (`resources.mjs UNIFORM_STRIDE`) |
| frame head JSON | 218.6 MB / 300 = **730 KB/frame** (the RRSQ head; not a wire format) |
| distinct textures over 300 frames | 1,665 = 1,628 R8 part tiles + 37 RGBA pages, 6.5 MB |
| textures referenced per frame | avg 68, max 111 |
| constant buffers | 5,999 distinct (one CBWorld per world node per frame + scene blocks) |
| GPU window (`SequencePlayer.prepareAll`) | 300 frames ≈ 210 MB at these sizes (the file comment says 145 MB for a lighter seq) |

Hail super capture for comparison (`cap_storm-hail.seq`, Steam's own draws): 553 avg / **783 max** draws, VB 164 KB
avg. Sprite-only tape (`tape_v4_59612784_storm.seq`): 53 avg draws, VB 8 KB.

### 3.2 Pipeline and budget (mid-range phone)

```
server ──binary tape (range)──▶ worker: decode frame N (nodes 54 B × ~10, anodes 100 B × ~80, rows)
                                        ▶ rr-render::emit(frame) → FrameRecord {vb, ib, draws[], cb[]}
                                        ── postMessage(transfer ArrayBuffer) ──▶ main thread
main: Replayer.prepare(frame)  (createBuffer ×3 + writeBuffer; ~0.2–0.7 MB today, ~0.15–0.25 MB after 3.3)
      ring of ≤16 prepared frames (player.mjs prepareAhead/evict — cap `maxPrepared` at 16, not 300)
      Replayer.render(): ~400 × {setPipeline, setVertexBuffer(voff), setBindGroup×2, viewport, drawIndexed}
      blit 2048×1024 scene RT viewport → canvas (player.mjs BLIT_WGSL)
```

| stage | today | target | basis |
|---|---|---|---|
| decode + emit (worker) | Python: seconds/frame | Rust/WASM: ≤ 2 ms/frame for ~100 nodes + 35 sprite records × ~20 parts (INFERRED; measure) | pure arithmetic, no allocation after warm-up |
| worker → main | n/a | 1 transferable ArrayBuffer/frame, 150–700 KB | zero-copy transfer |
| GPU buffers / frame | 700 KB | **~200 KB** (deck static; sprites + props + HUD only; uniforms 160 B stride via one storage buffer instead of 256 B dynamic-offset uniform = 63 KB) | §3.3 |
| textures resident | 6.5 MB + per-frame uploads of new part tiles | **constant ~60 textures, ~10 MB**: 6 char index atlases + 1 palette page per (char,row) + stage pages + effects + HUD | §2.3 |
| draw calls | 393 avg / 476 max (783 on a hail super) | same count; pipeline cache ~30 (replay.mjs), bind groups cached per (tex pair, sampler) | measured on desktop; **phone: UNKNOWN, must measure** (§10.1 of the draft) |
| scene RT | 2048×1024 BGRA + depth24plus-stencil8 = 16 MB | keep (the viewport crop is the game's own) | player.mjs |
| memory ceiling | 210 MB window | ring 16 × 0.2 MB = 3 MB + textures 10 MB + RT 16 MB | fits the draft's ~100 MB |

WebGPU availability: Chrome/Android yes; iOS — Safari 26 ships WebGPU (INFERRED from the platform announcement;
verify on a device before E2). OffscreenCanvas-in-worker vs main-thread render: keep the render on the main thread
first (the existing `SequencePlayer` is main-thread and proven); move it into the worker only if the postMessage
copy shows up — with transferables it does not copy.

### 3.3 The two changes that make the budget (INFERRED equivalent; each has an exact gate)

1. **Static deck VB.** `emit_stage` re-packs model 0 into every frame's `vb` (Python comment: "vertex/index buffers
   are PER FRAME"). Upload once per stage as its own vertex buffer; the deck draws keep their own `firstIndex`
   space. Gate: draw-list equality after normalising `firstIndex` per buffer; pixel equality.
2. **Character index atlas per char.** Replace `PLxx_p<sel>_<sha>` per-part R8 textures with one `r8unorm` atlas per
   character and per-draw UV rects. `fs_character` samples with `textureSample` on `samp0` = POINT + CLAMP (per the
   capture) — with texel-aligned rects, identical fetches. Gate: pixel equality vs the per-part build on the 300
   stage-13 frames.

### 3.4 What v6 keys change (per `TAPE-V3-SPEC.md` §9.5)

- Wire: the `anodes`/`aobjs` streams (3.1 MB b64 + 0.2–1.2 MB per match, measured on tapes 59613130 / 59613255)
  become 132 B/node/frame of keys + UV cell + record colour; objects come from the client's library. The
  per-frame **draw count does not change**, so §3.1 stands.
- Client: the object library must resolve `(TCW, shape hash)` → polygon groups from the arc rips (99.6 % identity;
  the 0.4 % fill quads stay content-hashed and ship once). That resolution is exactly D1's output — v6 cannot be
  consumed before D1 exists (see §5).
- A2/A3 (static props from the initialiser tables, HUD by parameters) move matrix composition into the emitter:
  ≤ ~100 4×4 multiplies per frame — negligible.
- Sprites unchanged (nodes stride 54, ~0.4 MB/match).

---

## 4. Gate plan for the port

Principle (draft §2): the Python is the oracle; every gate that exists today becomes a test of the Rust output.
The Python gates consume `.pack`/`.seq`-shaped files (`emitter_gate.load_pack`, `EG.indexed_quads`), so the
cheapest adapter is **`rr-render` writes RRSQ/RRPK-shaped output for gating** (`--emit-seq`), and the browser
frame format is a second, binary writer over the same in-memory `FrameRecord`.

### 4.1 Level 0 — decoder equality (exact)

Add `--dump-nodes <out.json>` to `tape_to_seq.py` (emits, per frame, the decoded node tuples, palettes, anodes rows,
aobjs records with `sha8(payload)`), and the same dump from Rust. Compare with `diff`. Tapes:
`replay-kit/tapes-kept/*_59613662_*.json.gz` (stage 13, 0.3.39), `web/tapecanvas/v3/*_59613255_*.json.gz`
(stage 5, 0.3.36), `*_59613130_*.json.gz` (0.3.35), `*_59612784_*.json.gz` (v4, rotation). Gate: zero diff lines.

### 4.2 Level 1 — draw-list equality vs Python on the gold frames (exact, per draw)

```
cd C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\replay
python tape_to_seq.py ..\..\replay-kit\tapes-kept\<...>_59613662_<...>.json.gz --start <S> --count 300 -o gold_13.seq
rr-render emit-seq --tape ..\..\replay-kit\tapes-kept\<...>_59613662_<...>.json.gz --start <S> --count 300 -o rust_13.seq
python seq_diff.py gold_13.seq rust_13.seq        # NEW (~80 lines): per draw compare firstIndex/indexCount/tex keys/
                                                   # state_key/vertex bytes/CB bytes; report first divergence
```
`<S>` = the `--start` that produced `tape_v5_59613662_stage13.seq` (its frame index 100 is clock 2843; the exact
row is UNKNOWN from the file — record it in the gate script, not in prose). Same for the capture-derived tapes:
```
python states_to_tape.py 4329 4508 -o cap_storm-hail_tape.json     # v4 tape from the capgate state dumps
python tape_to_seq.py cap_storm-hail_tape.json -o gold_hail.seq  ;  rr-render emit-seq ... -o rust_hail.seq
```
Exactness rules: the Python uses `np.float32` for `scene_VP`, `sort_key_record`, `sprite_vertex_z` and the depth
key `D`; Rust must use `f32` in the same operation order. Rotation corners use `math.cos/sin` in f64 — allow
1 ulp there only. Two places where the Rust output should *deliberately* differ from today's Python and the gate
must be told: (a) the closed-form camera replaces `camera_block.json` (`tape_to_seq` still ships the fitted model;
gate the Rust scene block against the captured CB rows 7–10/15–18 with `emu_gate.py camera 4445` semantics, i.e.
bit-identical), (b) static deck buffer (§3.3.1) — compare after `firstIndex` normalisation.

Gold frames named in the draft: `capgate/frame_4445.pack`, `frame_4505.pack`, `frame_7279.pack` exist;
**`frame_5168.pack` is not in `capgate/`** (UNKNOWN location — 330 packs and 2,875 state files are there; grep
found no 5168). `ordergate/frame_8940..9090.pack` (16 packs) are the sprite-order set.

### 4.3 Level 2 — the existing capture gates, run on Rust output

These are the deterministic gates already listed in `RENDER-STATUS-2026-09-03.md`; they need the Rust emitter to
expose the same intermediate (an index raster, a draw list, a page set). Run them unchanged on the Python first
(baseline), then on Rust:

| gate | command (from `d3dcap/replay`) | what it proves for the port |
|---|---|---|
| sprites, index-level, 100 % | `python v3gate.py ordergate/frame_*.pack --rot180 --rot-general --png out` | Rust `sprite::emit` raster == Steam quads (add `--emitter rust` that reads the Rust draw list instead of `emit_frame`) |
| per-body draw order | `python ordergate.py ordergate/frame_*.pack` | reverse-record order |
| rotation per quad | `python rotgate.py ordergate/frame_8980.pack` (+ the `cap_sent-rocket` packs) | general-rotation path; also settles the stale "NOT pixel-gated" comment |
| emitter vs pixels, no state | `python emitter_gate.py frame_5630.pack --png gate_5630.png` | placement law |
| render state | `python tsp_gate.py --hist <tape> capgate/frame_4445.pack capgate/frame_4505.pack capgate/frame_7279.pack` | `state::tsp` 824/824 |
| world geometry | `python worldgeo_gate.py capgate/frame_4445.pack` | `nl::groups` |
| list-0xC parts | `python parts_gate.py 4445 4447 4474 7441` | `assets::parts` + (when emitted) `world::parts` |
| palette source | `python palette_gate.py 4445 4505 5168 7279` | `sprite::palette` (RE-C1 residual) |
| translucent order | `python sort_gate.py <tape> capgate/frame_4445.pack` | `order::flush` |
| texture banks | `python rip_texbank.py --bank arc --gate` / `--bank hud --gate` / `--bank stage --stage 05 --gate` | `assets::texbank` shas |
| walker / camera emulation | `python emu_gate.py camera 4445` / `walker 4445` | reference values for `scene::camera` |
| tape completeness | `python tape_audit.py <tape.json.gz> --library tcw_pages/index.json` | inputs the Rust decoder must accept |

### 4.4 Level 3 — pixels

1. Rust seq vs Python seq through the same player: `python serve.py` then
   `node capture_video.mjs rust_13.seq rust_13.mp4` is for eyes; the gate is `Replayer.readback` on both seqs per
   frame (a ~60-line `diff_seq.mjs` on the model of `d3dcap/replay/diff.mjs`) — **byte-exact** when Level 1 passes.
2. Against Steam: the existing per-frame diff vs `capgate/scene_<f>_2048x1024_f87.bmp` (`verify_frame.py` /
   `diff.mjs`; baseline 0.011–0.018 % differing, zero missing coverage). Same number expected; a worse number is a
   port bug, a better one is a measurement (`record_attempt(outcome='masks_only')`).
3. After §3.3: per-part textures vs character atlas, static deck vs per-frame deck — pixel-equal on all 300 frames.

### 4.5 Level 4 — asset rip equality (WASM)

Per class: sha256 of every page/model/atlas from the Rust ripper == the Python's (`rip_texbank --out` index.json
`sha`; `rip_parts` JSON; `PLxx_idx.png` pixels; `PLxx_asm.json` assemblies). Then `rip_texbank.py --gate` semantics
against `tcw_pages/index.json` (16/16 today) run on the Rust pages.

### 4.6 Level 5 — release (draft E3)

Headless render-check: 3 gold frames from a fixture tape → PNG byte-exact vs stored. Note the fixture tape and
stored PNGs are ROM-derived (pixels) — keep them out of the public repo (BYOR rule in `RE-METHOD.md`).

---

## 5. Risks, and a corrected §9 order

### 5.1 Risks (numbered for the draft)

- **R1 — no arc on the phone** (§2.4). Blocks E2 on mobile until an asset-distribution decision (D0) is taken.
- **R2 — captured D3D state templates baked into every seq.** `template()` / `WorldTemplate` copy ~15 fields from two
  ROM-derived packs. The port must freeze them as constants and prove `WorldTemplate.select` would report 0
  "patched fallback"/"partial" on the gold frames with the frozen set (the stats counter exists).
- **R3 — RRSQ is not a wire or worker format** (730 KB/frame JSON). §4.6 of the draft says "the player's frame
  format" as if it existed; a binary `FrameRecord` is new work (small, but on the critical path for B6).
- **R4 — float determinism** (numpy f32 vs Rust f32/WASM) in sort keys; one ulp flips a cat-3 order between
  near-equal keys. Level 1 catches it; keep op order identical rather than "close".
- **R5 — v6 before the client library exists.** A1 first (draft order) produces tapes the consumer cannot resolve
  until D1 delivers the object library. Keep v5 as the port's input (§9.5: "v5 stays valid").
- **R6 — 300-frame GPU window** (`prepareAll`, 145–210 MB) on mobile — cap the ring at 16 frames.
- **R7 — oracle drift.** The Python still changes (RE-C1..C6). Every Python change must re-run Level 1; otherwise
  the Rust silently diverges from the oracle. Pin the Python commit hash in the gate script's output.
- **R8 — three sprite emitters in the tree** (Python, vendored JS, maplecast JS) with different mirror laws.
  Retire the two JS ones from the replay path explicitly, or someone will "fix" the Rust to match them.
- **R9 — stale comments contradicting proven results**: `rip_gfx2_assembly.py` ("offline LZSS dead end") vs
  `extract_gfx1_atlas.py` (bit-exact); `tape_to_seq.py` ("general rotation NOT pixel-gated") vs memory
  `mvc-rotation-path-180` (100 %). Re-run `rotgate.py` on the rocket packs and fix both comments; the port
  should follow the gated result, not the comment.
- **R10 — list-0xC parts and portraits are not in the Python emitter yet** (open tweaks 3/4). The port matches the
  Python as-is; these land later on both sides with `parts_gate.py` and the 29 portrait pages as gates.
- **R11 — stages beyond 02/05/0D/0F have no host-decoded pages** on disk; the fallback `STGxx_tNN.png` is the wrong
  decode (`rip_stage.py`). D1's texbank port covers all 19 by construction; until then, gold renders are limited to
  those four stages.
- **R12 — WebGPU on iOS** — INFERRED available (Safari 26); confirm on a device before promising "phone included".

### 5.2 Corrected order (disagreeing with draft §9 on where A1 and D1 sit)

Draft: `A1 → B1–B3 → B4–B5 → B6–B7 → D1 → E2 → A2–A3 → C`.

Proposed:

```
B1  decoder (v4/v5), Level-0 gate                       — exact, tiny, unblocks everything
B5  sprites (sprite::atlas/palette/emit)                — the 100 %-gated surface; v3gate/ordergate/rotgate run today
B6' binary FrameRecord + player feed (replace loadSequence; ring cap 16) — desktop pixels early, on existing rips
B2–B3 world objects + render state (nl::groups, state::tsp, world::emit, deck static)
B4  closed-form camera (beats the fitted block; emu_gate camera as the reference)
B7  two-phase flush (order::flush; RE-C2 stays open on both sides)
D0  asset-distribution decision (Tris): desktop-rip + user upload vs licensed pack   ← gates mobile, not desktop
D1  rippers in Rust (texbank, stage geometry, parts, GFX1/GFX2/PAL), IndexedDB cache, Level-4 gates
A1  v6 keys — only now can the client resolve them (R5); gate: v6 tape re-emits the v5 draw list
E2  page (desktop first; mobile after D0 + R12)
A2–A3 size levers; C-items as they close (each re-runs Level 1)
```

Rationale: the draft puts the wire change (A1) before a consumer exists and the asset library (D1) after the page.
Sprites first because that is the only layer with a 100 % pixel gate and the smallest code; the frame format
early because nothing is visible without it; D0 before D1 because D1's shape (where the rip runs) depends on it.

---

## 6. File index (absolute paths used for this review)

- Emitter / oracle: `C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\replay\tape_to_seq.py`, `tsp_state.py`, `v3gate.py`, `blkstate.py`, `asm_ident.py`, `states_to_tape.py`
- Player: `d3dcap\replay\player.mjs`, `replay.mjs`, `resources.mjs`, `state.mjs`, `sprite.wgsl`, `player.html`, `serve.py`, `capture_video.mjs`, `diff.mjs`; format writers `pack_sequence.py`, `pack_replay.py`
- Gates: `d3dcap\replay\{emitter_gate,ordergate,rotgate,sort_gate,tsp_gate,worldgeo_gate,parts_gate,palette_gate,emu_gate,tape_audit}.py`; data `capgate\` (817 MB), `ordergate\` (79 MB)
- Rippers: `d3dcap\replay\rip_texbank.py`, `rip_parts.py`; `C:\Users\trist\projects\maplecast-flycast\tools\rip_stage.py`, `tools\rip_gfx2_assembly.py`; `C:\Users\trist\projects\mvc2-skin-studio\tools\extract_gfx1_atlas.py`
- Assets measured: `C:\Users\trist\projects\maplecast-flycast\web\test-atlas\chars` (165 MB), `atlas\stages` (38 MB), `dasm_PLDAT\Output` (103 MB), `d3dcap\replay\tcw_pages` (5.4 MB); arc `C:\Program Files (x86)\Steam\steamapps\common\MARVEL vs. CAPCOM Fighting Collection\nativeDX11x64\arc\pc\game_50.arc` (65 MB)
- Vendored renderer under review: `C:\Users\trist\projects\mvc-live-skins-quarters\web\tapecanvas\renderer\{sprite-client,sprite-gpu,pvr2-renderer,stage-client,hud-client,hud-pvr2}.mjs`, `web\tapecanvas\tape-adapter.mjs`, `gpu.html`, `play_state.html`
- Agent writer (record layouts): `C:\Users\trist\projects\RetroReceipts-agent\agent\src\reader.rs` (`NODES_STRIDE`, `nodes_enc`/`anodes_enc`/`aobjs_enc` strings); crate split `RetroReceipts-agent\docs\CARTRIDGE-ARCHITECTURE.md` §2.1 (no `rr-render` crate exists yet; `agent/` is a single `rr-agent` package today)
