# WORKSTREAM — Client-side replay: the server streams the tape, the browser renders the match

*Status: DRAFT v1, 2026-09-03, assembled from the settled derivations (every rule below cites its doc / graph
seed and its gate). Expert review pass pending (Steam RE: senior-re-generalist, steam-d3d11-capture-expert;
render: mvc2-sprite-render-expert, flycast-internals-expert; SH4 side: mvc2-sh4-re-expert). Method:
`docs/RE-METHOD.md`. Checkpoint: `docs/RENDER-STATUS-2026-09-03.md`.*

## 0. Goal and non-goals

**Goal.** A RETRO RECEIPTS user opens a match page on any device (phone included) and watches the match
re-rendered pixel-exact from the tape alone: the server streams the compressed tape (today 2–5 MB/min, target
< 1 MB/match), the client decodes it in a WebAssembly worker and draws every frame on WebGPU. No game, no
emulator, no video, no server-side rendering.

**Non-goals.** Re-simulating the game from inputs (that is the flycast lane; see §8). Skins for other titles.
Serving ROM-derived assets from our infrastructure without a licensing decision (§6).

## 1. What is proven today (the render model the client must reproduce)

| Layer | Rule | Proof | Source |
|---|---|---|---|
| Sprites (System B) | walker fields → GFX1/GFX2 assembly from PLxx rips; rotation u16 angle about hotspot; scale-walker logical size; tiled flips about the logical box | 100% pixel gate on 30 captures incl. supers; walker emulated 47/47 fields bit-exact | `TAPE-V3-SPEC.md` §10, `EMU-GATE.md`, memory mvc-rotation-path-180 / mvc-tiled-flip-logical-box |
| Camera | P from fov (blk+0x6974, 65536/360) + y-offset (0x6988); V = LookAt(eye 0x6914, target 0x695C, roll 0x698C); stage-independent | P/V 16/16 bit-identical to bound CB; 0 violations over 1436 frames | `WORLD-CAMERA-GHIDRA.md`, seed 24 |
| Stage deck | arc `STGxx` POL model 0 at identity + world CB; textures = TEX file, HOST decode; deck colour blk+0x6CA8; blackout blk+0x3D50 | mechanism read in FUN_140620960; floor on the ground line ±1 px; 16/16 bank pages byte-exact | `STAGE-DRAW-GHIDRA.md`, `TEXTURE-BANKS-GHIDRA.md`, seed 31 |
| World objects (props, effects, HUD) | tape nodes (matrix, flags, colour, alpha) + NL polygon groups (Steam strip winding); TCW = base + texIndex (0xC10 stage / 0xC50 effects / 0xC90 HUD) | 99.6% vertex identity vs arc; 16/16 pages | same + `TSP-RENDER-STATE-GHIDRA.md` |
| Render state | blend/sampler/depth/cull/ps from PCW/ISP/TSP + group word (FUN_1408482a0); vertex colour R,G,B,A; bit 0 of x and v words cleared | 824/824 (blend 820/824) | seed 32; `PARTS-LIST0C-GHIDRA.md` §2 |
| HUD projection | HUD lists use FUN_14061d5b0's block (angle 0x4000, V=I) | 171/177 gold list-11 draws | `camera_block.json` 'hud' |
| Combo counter (list 0xC) | node → static part list → HUD-bank models; page 0xC92+count−1 | 24/24 CBWorld, 82/82 geometry/pages | `PARTS-LIST0C-GHIDRA.md`, seed 37 |
| Flush order | cat 0/1 (Z-write) in submission order, then cat 3 qsorted DESC by the record key = w of the NL mesh centre through W·V·P (sprites: walker depth D + 0.001·record index), ties by sequence | `sort_gate.py`: 0 key rises on 4445/4505/7279; sprite z 133/133 and 96/96 at ≤2.4e-7 | `TRANSLUCENT-SORT-GHIDRA.md`, seed 39 |

## 2. Architecture

```
agent (Rust, in-match)  --tape v6 (gz, ~<1 MB/match)-->  server (store + stream)  --HTTP range / SSE-->  browser
                                                                                        │
                                                          WASM worker: tape decode → per-frame draw list
                                                                                        │ (transferables)
                                                          main thread / OffscreenCanvas: WebGPU replayer
                                                                                        │
                                                          asset cache (IndexedDB): rips from the user's arc
```

- **One Rust crate, `rr-render`**, in the agent workspace (per `CARTRIDGE-ARCHITECTURE.md` crate split): tape codec
  (shared with the agent's encoder), emitter (the port of `tape_to_seq.py`), asset rippers (ports of
  `rip_texbank.py`, `rip_stage.py` geometry, `rip_parts.py`, the PLxx GFX rip), WGSL shaders. Targets:
  `wasm32-unknown-unknown` (browser worker) and native (CLI video / server gate). The native-client port plan
  (`maplecast-flycast/native-client-tdw/PORT-PLAN.md`, M0 done) is the wgpu host for the native target.
- **The Python emitter is the oracle.** Every gate built today becomes a test: the Rust emitter's draw list for a
  gold frame must equal the Python's byte-for-byte (`tsp_gate`, `worldgeo_gate`, `parts_gate`, sprite gates).
- **Player** = the existing WebGPU replayer (`d3dcap/replay/player.mjs`/`sequence` format) fed from the worker
  instead of a `.seq` file; the vendored tape renderer (`web/tapecanvas/`, 3 files) supplies the sprite path.
- **Page** = a route in the SvelteKit PWA (`nobd.net/app`, `mvc-portable-rewrite`), mobile-first.

## 3. Workstream A — Tape v6 wire (agent lane)

Owner: this session (RetroReceipts-agent). Spec: `TAPE-V3-SPEC.md` §9.5 (extend).
1. **Objects by key, not bytes.** Interned NL objects → `{bank, model/mesh index}` (arc-derivable, 99.6% identity;
   the remaining 0.4% fill quads keyed by content hash as today). Saves ~2 MB/match.
2. **Static props without per-frame matrices.** Ghidra item (RE-A1): read the per-stage initialiser tables
   (`PTR_PTR_140a6ec20[stage]` / `PTR_DAT_140a6ecb0[stage]`, `STAGE-DRAW-GHIDRA.md`) and the parent-matrix
   composition (`FUN_140620740`) to classify list-5 nodes as camera-static (derive placement from the table +
   camera) vs animated (ship). Gate: recomposed matrices == tape matrices bit-exact on the 0.3.39 tapes.
3. **HUD by parameters.** List-11 nodes: bar lengths / meter fills / timer digits as scalars, static quads from the
   HUD bank (Ghidra item RE-A2: which fields the HUD builder reads; gate: reconstructed node matrices == tape).
4. **Sprites unchanged** (nodes stride 54, 0.4 MB/match) + palettes (§5 fix).
5. **Rows**: keep camera, deck colour, blackout, cam_state (+ look/fov/yoff/roll only when cam_state == 1).
6. Delta/RLE per frame is NOT worth it (measured: 7.9 → 7.1 MB); the per-node encoding is.
Target: < 1 MB per match. Gate: the v6 tape re-emits a draw list identical to the v5 tape's on every frame.

## 4. Workstream B — `rr-render` crate (emitter port)

Owner: render experts + this session.
1. Tape decoder (v4/v5/v6) — shares the agent's record definitions.
2. NL polygon groups (`nl_groups`), strip winding, vertex bit-0 mask.
3. Render-state law (`tsp_state.codes`) + the captured state table (`HOST`).
4. Scene blocks: closed-form camera (§1) — replaces the fitted `camera_block.json`.
5. Sprite assembly: port of the gated Python (`v3gate` rules: logical dims, tiled flips, rotation, scale-walker).
6. Draw-list output = the player's frame format (buffers + draws), built once per frame in the worker.
7. Ordering: two-phase flush with the derived key (§1, seed 39 when closed).
Gate: byte-equal draw lists vs Python on the gold frames (4445/4505/5168/7279 + the stage-13 tape clip); then the
existing pixel gates against captures.

## 5. Workstream C — remaining render residuals (Steam RE, Ghidra)

| id | item | owner | gate |
|---|---|---|---|
| RE-C1 | Mirror-match palette: where `FUN_1406129f0` gets the bound palette page (per-slot bank vs DatPal cl+0x4C); alternate-colour selector | steam-d3d11-capture-expert | rebuild captured LUT pages byte-exact (frames 4445/4505/5168/7279) |
| RE-C2 | Translucent sort: close the 118-vs-122 count mismatch on frame 4505 (per-part depth increment); reproduce gold order on 4 frames | senior-re-generalist | exact draw order 4/4 frames |
| RE-C3 | Hit sparks: verify the gfx1 full-pointer fix on the stage-13 tape; if sparks still miss, resolve cat-3 sids 1002..1006 against the owner's rip | mvc2-sprite-render-expert | sparks drawn on hit frames; sid coverage 100% |
| RE-C4 | Portraits TCW 0xC99..0xCA8 patched from character DATs at load (`FUN_14060d560`/`FUN_1406162e0`/`FUN_140616330`) → offline rule | senior-re-generalist | 29 captured portrait pages byte-exact |
| RE-C5 | Scripted camera (blk+0x6908 == 1): render from look/fov/yoff/roll; keyframe tables | steam-d3d11-capture-expert | emulated P/V on a scripted frame == bound CB |
| RE-C6 | Whole-frame emulation read set (tick + dispatcher on the dump_live images) → the formal minimum tape | senior-re-generalist | determinism; walker 47/47; writes ⊂ pre→post diff |

## 6. Workstream D — assets (BYOR)

1. Client-side rippers in WASM: `game_50.arc` → AFS → stage POL/TEX, effects, HUD/common banks, PLxx sprite
   data (the same rules as `rip_texbank.py` / `rip_stage.py` / `rip_parts.py` / the GFX rip). User picks the arc
   file once (File System Access API); results cached in IndexedDB keyed by arc hash.
2. Decision (owner: Tris): licensed asset pack from our store vs client-side rip only. Until decided, rips stay
   local and gitignored; the workstream builds the client-side path.
3. Gate: client-ripped pages/models byte-equal to the Python rippers' output (sha per page, vertex sets).

## 7. Workstream E — delivery

1. Server: tape store + range/streaming endpoint (lane 1 owns the server; contract only: `GET /rr/tape/<id>`
   with Range, gzip as stored). No server-side render.
2. PWA route `/replay/<match>`: worker + WebGPU canvas, scrubber, 60 fps pacing off the wall clock (the player
   already does this), fallback message where WebGPU is absent.
3. Release gate: the PWA pipeline's headless render-check renders 3 gold frames from a fixture tape and diffs
   against the stored PNGs (byte-exact, as the capture gates).

## 8. Explicitly out of scope / dead ends (do not reopen)

- TTD / whole-process recording (exe protection layer hooks NtResumeThread; launch never loads).
- MAME/dcrecomp NAOMI render (5-expert no-go).
- `rip_stage.py` texture decode (wrong twiddle/expansion — use the host decode).
- Inputs-only re-simulation for playback (flycast lane; renders DC pixels, not Steam's).

## 9. Order of work and gates (no dates)

A1 (keys) → B1–B3 (decode + objects + state, oracle-gated) → B4–B5 (camera + sprites) → B6–B7 (player feed +
order) → D1 (client rippers) → E2 (page) → A2–A3 (size) → C-items as they close. Every step has a numeric gate
listed above; nothing ships on "looks right".

## 10. Open questions for the expert review

1. Worker/main-thread split: OffscreenCanvas WebGPU in the worker vs transferable buffers to the main thread —
   measure on a mid phone.
2. Memory budget per frame on mobile (today's desktop player windows 300 frames at ~145 MB — too much; v6 keys
   make per-frame buffers small, but shared textures must stay under ~100 MB).
3. Palette LUT per draw (RE-C1) — whether it can be a per-slot texture updated per frame or must be per node.
4. Which pieces of the vendored tape renderer survive (sprite path) vs come from the `.seq` replayer.

### RE-C1 result (palette LUT per draw, 2026-09-03) — `docs/PALETTE-SOURCE-GHIDRA.md`, seed `38_palette_source.surql`

* **Answer to 10.3:** a per-SLOT texture set updated per frame, not per node. Every character draw binds the LUT of
  its texture-slot bank (`FUN_140845e20`, slot table `ctx+0x1e00a0+idx*0x18` +4); the bank is fixed at sheet
  registration (`FUN_140612180`: `0x10 + 8*slot + rec.flags>>4`), so a fighter uses at most 8 banks and each bank's
  colours are the engine-staged line `blk+0x1040+bank*0x38` (+0x18, 16 x u16 ARGB4444; +8 flag) — filled by
  `FUN_1406146d0` (= `loc_8c035162`), uploaded per frame by `FUN_140613390`, textured by `FUN_140048970`
  (per-bank 256x1 R8G8B8A8, nibble*17). CONFIRMED both binaries.
* **Why mirrors render alike today:** the tape's `pal` is `*(node+0x1B8)+0` = DatPal `cl+0x4C` = costume 0 row 0 of
  the character block; the fighter's real costume is `node+0x39` (DC `char+0x25`) x 0x100 into that block, then
  runtime rewrites. TTD gate: `DatPal+0 != rendered row 0` for 5/5 non-default-colour fighters.
* **Gates:** capgate `palette_gate.py` — LUT page == staged line byte-exact 4445 **240/240**, 7279 **134/134**,
  4505 **120/144** (24 = one texture still holding the previous bank-0x23 content: the bound LUT lags a mid-frame
  palette change by >= 1 frame, INFERRED double-buffer), 5168 has no pack; total **494/518**. TTD same-moment:
  staged rows == `DatPal + var*0x100 + k*0x20` **46/48** (misses = Storm's runtime aura rows).
* **Tape delta (TAPE v5 `palrows`, agent lane, diff in the doc s4.1):** per frame one 0x540-B read at
  `blk+0x13C0` (6 slots x 8 rows x 0x38), interned through `pals`: `[u32 frame][48 x u16 pal idx][48 x u8 flag]`.
  Consumer `tape_to_seq.py` applied (palette code only): uses `palrows[frame][slot*8 + row_of(sid,ri)]` when the key
  exists, old tapes unchanged; `--pal-lag N` for the lag once gated.
* **Open:** exact LUT lag (needs consecutive-frame packs with a palette change); the character-select writer of
  `+0x52D` (forced-alternate rule) on Steam; live dim state is only visible in host PALETTE_RAM `dev+0xd8d04`.

### RE-C2 result -- translucent draw order (2026-09-03)

**Proven (Ghidra, CONFIRMED):** Steam flushes categories 0/1 (Z-write) in submission order and qsorts category 3
(`FUN_140842e30` -> MSVC CRT `qsort` `FUN_140817f80`, comparator `LAB_1408434d0`: f32 key at slot+0x14
DESCENDING, ties by the submission sequence at slot+0 ASCENDING -- a total order). World/HUD key
(`FUN_140843320`) = w of `[centre(rec+0x10..0x18) 1] x W x V x P` (radius `rec+0x1C` < 0 forces key = -radius; the
`cfg+0x48 == 8` / r > 7000 -> 10000 branch is inactive per the gate). Sprite key = the walker depth `node+0x12C`
(= zoom*0.1 + LayerZ[layer] `blk+0x6D08`) + 0.001 per record (`FUN_1406129f0`), taken BEFORE `FUN_1408432e0`
turns it into the quad's vertex z = max(0, (P32 - D*P22)/D). Doc: `docs/TRANSLUCENT-SORT-GHIDRA.md`; seed
`maplecast-flycast/tools/re_kb/39_translucent_sort.surql` (applied, 36 stmts, 0 failed, backup
`re_kb_data/_exports/re_kb_20260903-020911.surql`).

**Gate (`d3dcap/replay/sort_gate.py`, stage-11 tape 59613506 + capgate packs/dumps):** 4445: 269 cat-3 draws,
252 keyed, 0 key rises, sprite vertex z 133/133 from the state dump (max |dz| 2.4e-7); 4505: 150 / 133 keyed,
0 rises (sprite keys from the engine's captured z -- no dump in 4490..4520 holds that pack's 122-record sprite
set); 7279: 140 / 107 keyed, 0 rises, 96/96 sprite z (1.8e-7). Distinct-entry ties out of submission order:
3 on 4445 (node identity unresolved for obj-139 records under a composed W), 0 elsewhere. 5168: no pack.

**Emitter (`tape_to_seq.py`, `--legacy-order` keeps the old path):** records/rip meshes carry centre+radius
(`decode_anodes`, `rip_stage.py` STG0B/STG0D regenerated), every draw tagged (cat, key, submission), `order_draws`
= cat 0/1 by submission then cat 3 by (-key, submission), sprite z from the real key, bit-13 draws inherit the
previous flushed cull. Re-emitted `tape_v5_59613662_stage13.seq` (--start 1500 --count 300): 300 frames,
118,017 draws, cat 0 70,949 / cat 3 47,068, registered in `sequences.json` (405.8 MB). Audit: 0 sprite draws
Z-write ON; the 12,170 Z-write-ON draws inside the sorted phase are list-7/8 flag-bit-5 nodes with alpha
0.5..0.98 (cat 3, s19 = 1, preset 4 -- Steam's own rule), verified against the tape's node flags/alpha.

**Open:** writer of the queue pass index `ctx+0x1f828c`; meaning of `cfg+0x48`; exact D of the HUD digit quads
(<= 2, z clamps to 0; order among them = submission); node identity of composed-W list-7 children for tie audits.

### RE-C6 result (2026-09-03, senior-re-generalist) — whole-frame emulation read set → the formal minimum tape

Full text: `docs/FRAME-READSET.md`; seed `maplecast-flycast/tools/re_kb/36_frame_readset.surql`; harness
`d3dcap/replay/emu_gate.py frame` (+ `emu_frame.py`, EmuGate.java `trace/extstub/heap` commands). Input = the live
`dump_live.py` images of run `20260903-000941` (offline match, clock 2239, roster 12A/34/12C/117/134/135, stage byte 11).

Gates (numeric): **determinism** — tick and dispatcher each run twice, trace stream + all dumps SHA-256 identical.
**Tick** `FUN_140118950` (459,681 instr.): `blk+0x3CC8` 2239→2240; 120 blk bytes changed, 116 inside the pre→post diff
(post = 237 frames later, 7,785 B), the 4 outside are one-byte anim countdowns. **Walker outputs**: tick → (reset
LayerZ/G+0x24) → `FUN_140620960` again = **50/50 node fields identical, 0/211,736 blk bytes differ, quads 125=125**
(this state has 5 drawn nodes; the 47/47 figure was frame 4445 of another capture — its roster does not match these
images, so the capgate consecutive-frame gate is NOT runnable; first divergence slot 0 char id 0x134 vs 0x12A).
Not emulated: nothing — after giving the UCRT a bump allocator (`RtlAllocateHeap`) and `FlsSetValue → 1` the frame
runs to RET; 6 imports hit, 0 unimplemented instructions.

Structure (CONFIRMED): `FUN_140118950` = counter++ / `game_state+0x798=1` / pad shuffle, then `*(game_state+0x10)` =
`FUN_140607d60` = the WHOLE frame (sim `FUN_140608a00` + render table loop `FUN_14060b960` → dispatcher → walker →
submit). Pad words are `game_state+0x218/+0x21C` (exe 0x140AC6F58/5C), not `blk`. The per-frame LayerZ reset is
`FUN_14060a1f0` (every frame from `FUN_140609d60`) — closes EMU-GATE's open item.

Per-frame READ SET: blk 10,004 B (input array, G, fighter fields, pool nodes, camera/stage, lists, battle state, plus
`blk+0x1000..0x3C66` = 0x38-B records outside the block map, DC UNKNOWN); dcram 22,545 B (PL slot 0/1 GFX/cell/pal
tables, effects/HUD/stage banks, and the 0x0CE60000 tile table the frame itself rebuilds — 11,488 B written by
`FUN_140614210`); exe 2,445 B (400 constants + 478 mutable, of which 8 B at `0x142edf318..546` UNKNOWN); ctx 1,871 B
(texture-slot table + matrix state). WRITE SET: blk 6,692 B, ctx 43 KB (TA records + texture pages), the host
texture-staging buffer `*(game_state+0x208)` (64 KB memset, never read back).

Minimum tape (Tris's framing holds): ONE `blk` snapshot (+ the `game_state` page, the `0x142edf300` page, the ctx slot
table) and **2 seat words per frame** regenerate every render input (node fields, LayerZ, tile table, TA records)
byte-exact and deterministically; per-frame blk diffs are redundant. From outside the tape: the exe image, the
arc-derived DC-RAM data (effects/HUD/stage banks by AFS entry — loaders CONFIRMED; the six per-character PL images at
`0x0C420000 + k·0x150000`, order 0,2,4,1,3,5 — loader table UNKNOWN, dump-once workaround). Next gates: an effect-heavy
frame and a second roster; the PL loader; the 8 UNKNOWN bytes.
