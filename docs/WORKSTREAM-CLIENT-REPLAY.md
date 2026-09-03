# WORKSTREAM — Client-side replay: the server streams the tape, the browser renders the match

*Status: **v2, 2026-09-03** — v1 draft corrected by the two expert reviews (`WORKSTREAM-CLIENT-REPLAY.review-re.md`,
`WORKSTREAM-CLIENT-REPLAY.review-render.md`), by the three derivations that closed during review (RE-C1 palette,
RE-C2 flush order, RE-C6 whole-frame emulation; full result blocks in the v1 history, commits 40d5f01..1743085, and
in their docs), and by two owner decisions taken 2026-09-03 (§3). Every rule cites its doc / graph seed
(`maplecast-flycast/tools/re_kb/100..109_*.surql`) and its gate. Method: `RE-METHOD.md`. Checkpoint:
`RENDER-STATUS-2026-09-03.md`.*

## 0. Goal, non-goals, and the two tape forms

**Goal.** A RETRO RECEIPTS user opens a match page on any device and watches the match re-rendered from the tape:
the server streams the compressed tape, the client decodes it in a WebAssembly worker and draws every frame on
WebGPU. No game, no emulator, no video.

**Two tape forms, two jobs (settled by RE-C6, `FRAME-READSET.md`, seed 106):**
- **Receipt** = one state-block snapshot (+ game_state page, `0x142edf300` page, ctx slot table) + **two input words
  per frame** (`game_state+0x218/+0x21C`). The GGPO tick `FUN_140118950` calls `FUN_140607d60` = the WHOLE frame
  (sim + dispatch + walker + submit); emulated on the live images it regenerates every render input byte-exact
  (chain gate 50/50 walker fields, 0/211,736 block bytes differ, SHA-identical on repeat). This is the
  dispute/verification record and the port's oracle. It needs the exe image + arc banks + the six loaded character
  images (static per match), so it is replayed on a server, not in a phone.
- **Playback tape** = the state tape the agent records today (v5 + 0.3.40 `palrows`), rendered without executing
  game code. This workstream builds the playback path; the receipt form is Workstream F.

**Non-goals.** Flycast re-simulation for playback (DC pixels). Skins for other titles.

## 1. What is proven, with the reviewers' scoping

| Layer | Rule | Proof (scoped) | Source |
|---|---|---|---|
| Sprites (System B) | walker fields → GFX1/GFX2 assembly from PL rips; rotation (u16 angle about the hotspot); scale-walker logical size; tiled flips about the logical box | 100% pixel gate on 30 training captures incl. supers; walker emulated 47/47 fields (one frame), 50/50 on the chain frame. ⚠ cell-override frames need the walker's post-walk OUTPUTS → the agent's sampling phase is load-bearing (M12) | `TAPE-V3-SPEC.md` §10, `EMU-GATE.md`, `FRAME-READSET.md` |
| Camera | P from fov (0x6974) + y-offset (0x6988); V = LookAt(0x6914, 0x695C, roll 0x698C) | P/V 16/16 bit-identical to the bound CB; state-0 invariants checked on stage 0x0B only; CB rows 4–6 INFERRED | `WORLD-CAMERA-GHIDRA.md`, seed 100 |
| Stage deck | POL model 0 at identity + world CB; textures = TEX file, HOST decode; deck colour 0x6CA8; blackout 0x3D50 | mechanism read in `FUN_140620960`; deck-vs-ground line is an eyeball note (no numeric gate); bank pages 16/16 byte-exact over the library, 1 page on 1 stage for the deck itself | `STAGE-DRAW-GHIDRA.md`, `TEXTURE-BANKS-GHIDRA.md`, seed 102 |
| World objects | tape nodes + NL polygon groups (Steam winding) | 99.6% vertex identity vs arc; winding 442/454 — the 12 bit-6 strips are UNKNOWN | `TSP-RENDER-STATE-GHIDRA.md` §3 |
| Render state (world) | blend/sampler/depth/cull/ps from PCW/ISP/TSP + group word; colour R,G,B,A; bit 0 of x/v cleared | 824/824 (blend 820/824) — every D3D desc column is INFERRED from captures (creation never found); presets 1/3/5/10/0xB, blend 0x16/0x19/0x22/7/0, mirror samplers never seen (M5) | seed 103, `PARTS-LIST0C-GHIDRA.md` §2 |
| Render state (sprites) | ONE blend `(SRC_ALPHA, INV_SRC_ALPHA)`; `FUN_1408458b0` issues no blend command; `ctx+0x1f8274` has one writer (0x45) | 94,976 captured palette draws, 100%, zero additive → the tape's `nodes.blend` byte is a DC-lane heuristic, REFUTED for Steam; additive effects come from `anodes` TSP words (M3) | review-re §2 |
| HUD projection | HUD lists use `FUN_14061d5b0`'s block (angle 0x4000, V=I) | 171/177 gold list-11 draws | `camera_block.json` 'hud' |
| Combo counter (list 0xC) | node → static part list → HUD-bank models; page 0xC92+count−1 | 24/24 CBWorld, 82/82 geometry/pages; NOT carried by any agent yet (`pnodes` absent, M10) | `PARTS-LIST0C-GHIDRA.md`, seed 107 |
| Flush order | cats 0 AND 1 (Z-write) in submission order, then cat 3 qsorted DESC by the key: world = w of the NL mesh centre through W·V·P (`FUN_140843320`); sprites = walker depth `+0x12C` + 0.001·record index; ties by sequence | `sort_gate.py`: 0 key rises on 4445/4505/7279; sprite z 133/133, 96/96 ≤2.4e-7 (the "118 vs 122" was a capture-alignment artefact, not a model gap) | `TRANSLUCENT-SORT-GHIDRA.md`, seed 109 |
| Palette | bound LUT = staged rows `blk+0x1040+bank*0x38` (bank = slot base + rec.flags>>4), filled from `DatPal + variant(node+0x39)*0x100`; `pal` was costume 0 row 0 | `palette_gate.py` 494/518 LUT pages byte-exact (24 = a 1-frame LUT lag, M7); agent 0.3.40 ships `palrows` (148 B/frame) | `PALETTE-SOURCE-GHIDRA.md`, seed 108 |
| Frame clear / background | the frame is CLEARED BY DRAWS: three full-screen quads (`FUN_140843eb0`); colour = `FUN_1406101b0` from `blk+0x6CB4/0x6CB8..0x6CC0/0x6CF0` | on every captured frame; the emitter clears to 0 and the 20 background bytes are NOT in the tape (M2) | review-re §2 |
| Post chain | scene RT 2048×1024 → 9 passes bloom/SMAA → 1280×768 backbuffer + 0.8 vertical resample; one BORDER sampler | every pixel gate so far is PRE-bloom; the user sees post (M1) | review-re §2 |

## 2. Architecture

```
agent (Rust)  --playback tape v5/v6 (gz)-->  server (store + range stream)  -->  browser (desktop, WebGPU)
                                                     │                          WASM worker: decode → binary frame feed
                                                     │                          WebGPU replayer (replay.mjs + sprite.wgsl)
                                                     │                          asset store (IndexedDB): per D0
                                                     └--server-side emit-->  pub/sub (Redis / NATS) --> phone (WebGPU, frames only)   [M-interim]
agent  --receipt (snapshot + input words)-->  server (store)  -->  server-side emulation (disputes, oracle)   [Workstream F]
```

- **`rr-render` crate** (agent workspace, per `CARTRIDGE-ARCHITECTURE.md`): tape codec shared with the agent's
  encoder; emitter = port of `tape_to_seq.py main()` + `Atlas` + `tsp_state.py` (35 functions → 9 modules,
  review-render §1); rippers (4 asset modules); WGSL. Targets wasm32 (browser worker) + native (server emitter for
  M-interim and Workstream F; wgpu host = `native-client-tdw`). One code path serves desktop, phone and server.
- **Survives verbatim** in the browser: `replay.mjs`, `state.mjs`, `resources.mjs`, `sprite.wgsl`, the ring/blit half
  of `player.mjs`. `loadSequence` (RRSQ JSON, 730 KB/frame measured) is replaced by a binary frame feed. Retired
  from the replay path: `sprite-client.mjs`, `sprite-gpu.mjs`, `pvr2-renderer.mjs` (DC reversed-Z), `tape-adapter.mjs`,
  `stage-client.mjs`, `hud-*.mjs`. `WorldTemplate` / captured-state lookups become frozen constants (W3 closes them).
- **Python is the oracle**: draw-list equality per draw (`rr-render emit-seq` + `seq_diff.py`), then the capture
  gates on Rust output, then pixel readback byte-exact vs Python.

## 3. Owner decisions (taken 2026-09-03) and the one still open

- **D0 — assets, DECIDED for the test cohort:** ship the asset pack with the test build; users own the game
  (Tris, 2026-09-03). Pack = arc-derived pages/models/sprites (~8 MB per match; all 59 characters = 49.8 MB index
  + 2.1 MB LUT; stages 38 MB; effects/HUD/parts 0.5 MB), served like any other static asset, cached in IndexedDB
  keyed by pack version. The client-side ripper (D1) stays the long-run BYOR path and the gate that the pack is
  byte-equal to what a user's own arc would produce. Licensing for a public release remains an owner decision.
- **M-interim — phone playback by server-side emission, DECIDED:** until the WASM emitter exists, the server runs
  the native emitter and streams per-frame draw commands to the phone over a pub/sub queue (Redis pub/sub + the
  SSE gateway :7251 already exist, `mvc-tournament-realtime`; NATS runs in `forgily-data`); the phone runs only the
  WebGPU replayer against the shipped asset pack. Budget: today's JSON frame is 730 KB; the binary feed with a
  static deck buffer and per-character index atlases is ~200 KB/frame (review-render §3) = 12 MB/s at 60 fps —
  too much for a queue; with keyed draws (objects/sprites by id, buffers built client-side from the pack) a frame
  is 20–50 KB = 1–3 MB/s, fine on wifi, marginal on cellular, so M-interim streams the KEYED form and the phone
  builds buffers from the pack. Gate: streamed frames == local emit, per draw. Ordering/backpressure: one
  subject per match, frames sequence-numbered, the client renders at the tape's frame clock and drops nothing
  (buffer ahead ≥ 1 s); a stalled subscriber re-syncs from the last keyframe (a full frame every 60).
- **D-post — what "pixel-exact" means at release (M1), OPEN:** pre-bloom scene RT (what every gate measures) vs the
  post-processed backbuffer (9-pass chain incl. a BORDER sampler WebGPU lacks). Recommendation: ship pre-bloom as
  v1; the post chain is a later, separately gated layer.

## 4. Workstreams (order corrected by both reviews)

### W0 — Tape-vs-capture gate (FIRST; M12/M10)
Every 100% gate so far is shim-vs-capture; none is tape-vs-capture. One agent+shim session on a real stage diffs the
TAPE's node fields per frame against the same frame's capture dump: proves the agent's sampling phase (cell-override
frames need post-walk outputs) and the harvest caps (96 nodes / 8 records). Gate: fields equal every frame; misses named.

### W1 — Sprites in the browser first (B1 → B5 → B6')
1. Tape decoder (v4/v5/v6) in Rust, record definitions shared with the agent.
2. Sprite assembly port (the gated rules) → binary frame feed → the surviving replayer. First pixels on the target.
Gate: draw-list equality vs Python on 4445/4505/7279 (⚠ `frame_5168.pack` does not exist), then the 30-capture pixel
gate on Rust output.

### W2 — World + state (B2 → B3 → B4 → B7)
NL groups + winding + bit-0 mask; render-state law; closed-form camera (drops `camera_block.json`); flush order.
Corrections from review-re: the sprite blend is the single normal blend (drop `nodes.blend`); the frame background is
DRAWN (three quads; colour from the 20 `blk+0x6CB4..` bytes → tape field in W5).
Gate: `tsp_gate` / `worldgeo_gate` / `sort_gate` / `palette_gate` on Rust output.

### W3 — Never-captured D3D state (M5) — one launch, no match
Hook `Create{Blend,DepthStencil,Sampler,Rasterizer}State` in `d3dcap`, join against the executor's tables
(`R2+0x358…` / `0x1e88…` / `0x1f58…` / `[R2+0x20]+0x1780…`). Turns every INFERRED desc column CONFIRMED and freezes
the constants the crate ships. Gate: every preset / blend / sampler code has a read desc.

### W4 — Assets (D0 pack → D1 rippers)
Build the pack from the existing rippers (`rip_texbank`, `rip_stage` geometry with host-decoded textures,
`rip_parts`, the PL GFX rip; character DAT = arc entry 209+cid, CONFIRMED); static deck buffer + one index atlas per
character (~200 KB/frame, ~60 textures constant, 16-frame ring instead of 300). Then the WASM rippers (D1) as the
BYOR path. Gate: pack pages/models byte-equal the Python rippers (sha per page, vertex sets).

### W5 — Tape v6 wire (A1 AFTER the pack; then A2–A3)
Keys instead of object bytes (the client resolves them against the pack); static props from the initialiser tables
(RE-A1); HUD by parameters (RE-A2); `pnodes` (44 B, `PARTS-LIST0C-GHIDRA.md` §5); the 20 background bytes;
`node+0x150` (M11); drop `objs`, `pal`, `blend` and the six duplicate fighter columns (review-re §3). Target < 1
MB/match. Gate: v6 re-emits the v5 draw list identically. The keyed frame format of W5 is also M-interim's wire.

### W6 — Delivery
E1 server: tape range endpoint (lane 1 contract only: `GET /rr/tape/<id>` with Range, gzip as stored) + the
M-interim emitter/publisher. E2 PWA route `/replay/<match>` (desktop: worker + WebGPU; phone: subscriber + WebGPU).
E3 release gate = headless render-check of 3 gold frames, byte-exact vs stored PNGs, pre-bloom per D-post.

### Workstream F — Receipt lane (server-side)
Agent records snapshot + input words (0.3.24 anchor + `seat_in` exist; align to `game_state+0x218/+0x21C`);
`emu_gate.py frame` replays a disputed match server-side; PL image loader table UNKNOWN → dump-once until derived.
Gate: regenerated draw list == the playback tape's draw list for the same frames.

## 5. Residual RE items

| id | item | status / gate |
|---|---|---|
| RE-C1 palette | CLOSED (seed 108; agent 0.3.40) | LUT lag 1 vs 2 frames open (M7) |
| RE-C2 flush order | CLOSED (seed 109) | `ctx+0x1f828c` pass-index writer UNKNOWN |
| RE-C3 hit sparks | object bank key fixed (full gfx1 pointer, 56617e6); verify on the stage-13 clip | — |
| RE-C4 portraits | writers CONFIRMED by decompile, DAT link INFERRED (M8) | rule + 29-page gate pending |
| RE-C5 scripted camera | fields carried; renderer pending | emulated P/V on a scripted frame == bound CB |
| RE-C6 read set | CLOSED (seed 106) | PL loader table UNKNOWN; 8 exe bytes UNKNOWN |
| M2 background colour | Ghidra done (`FUN_1406101b0`); tape field + emitter pending | captured clear colour == derived |
| M9 effects rebase case 0x18 | UNKNOWN in-match | — |
| M14 stencil in the post chain | UNKNOWN | with D-post |

## 6. Dead ends (do not reopen)
TTD / whole-process recording · MAME/dcrecomp NAOMI · `rip_stage.py` texture decode · inputs-only flycast playback ·
`nodes.blend` as a Steam blend source · "118 vs 122" as a sort defect · per-frame blk delta encoding (7.9 → 7.1 MB).

## 7. Gate ladder for the port (review-render §4)
L0 decoder dump equality → L1 draw-list equality per draw vs Python (`seq_diff.py`) → L2 capture gates on Rust
output → L3 pixel readback byte-exact vs Python, 0.011–0.018% vs Steam → L4 pack/rip shas → L5 streamed frames ==
local emit (M-interim).
