# RETRO RECEIPTS — THE REPLAY SYSTEM (gold standard, 2026-09-03)

Single source of truth for how a MvC2 match on the Steam "MARVEL vs. CAPCOM Fighting Collection" becomes a replay a
browser redraws from the game's own assets, and how the same match is proven reproducible from inputs alone. Every
number below is measured on this date; where it is a projection it says so. Older checkpoints
(`RENDER-STATUS-2026-09-03.md`, `WORKSTREAM-CLIENT-REPLAY.md`) remain as history; this document supersedes them as the
entry point. The receipt runner's plan is `WORKSTREAM-RECEIPT-RUNNER.md`.

## 0. What exists, in one screen

| layer | component | state |
|---|---|---|
| capture | tray agent **0.3.48** (`RetroReceipts-agent/agent`, Rust) reads the game's memory at every frame edge and writes **THE TAPE** | running; local tape copy for offline matches; ~10 % of one core in a match |
| record | tape v5 = gzip JSON envelope with binary sections; **battle-frame anchor** (0.3.47) | 1.8–13 MB/min gz (median ≈ 5); anchor 12.6 KB gz |
| emit | **rr-render** crate (Rust; native `emit_seq` and wasm `WebFeed`) turns tape rows + the user's arc assets into FrameRecords | 14.1 ms/frame native; byte-exact vs the Python oracle |
| render | WebGPU player (`d3dcap/replay/*.mjs`), inside the PWA as `ReplayEmbed` | 60 fps in the LIVE tab; direct seeks hash-equal to sequential; internal resolution 2×–4× |
| prove | Path B D3D11 capture shim + gates (L1 draws, L3 pixels, seek, capture) | 300 frames 0.011–0.018 % pixels differing vs the game; L3 60/60 byte-exact |
| simulate | determinism contract + whole-frame p-code emulation + **receipt gate** | first real receipt: **300/300 frames exact** from anchor + inputs (offline match) |
| knowledge | `re_kb` graph (SurrealDB), function map Steam↔SH4, 113 seed files | schema refuses "confirmed" without cited evidence |
| product | PWA **LIVE** tab with in-page replay (`RetroReceipts-agent/pwa`) | built, gated (check/build/smoke/L3), deployed via the gated pipeline |

## 1. The tape: what the agent records and how it flows

**Where it comes from.** The agent finds the game process, locates the GGPO-saved state block `blk` (0x33B18 bytes; the
fighter structs start at `blk+0x3DB8`, stride 0x738) and the frame clock `blk+0x3CC8`. It polls the clock every 0.5 ms
(8 ms sleep right after a tick) and reads the frame the moment the clock ticks, so every row is sampled at the same
phase (v4 edge-synced sampling). A torn draw list is re-read (0.3.46: two reads 0.5 ms apart must agree).

**What one frame row holds** (`schema` string in the tape, tape v5, 0.3.45+): frame, both pad words, kcode, per slot
(6): hp, x, y, meter, combo dealt/received, vx, vy, red hp, facing, hitstun, drawn, sprite id, anim timer, screen x/y,
zoom x/y, flash, glow, layer; timer, round, zoom, camera state/look/fov/y-offset/roll, deck colour, blackout, frame
background mode/colours/fade/gate bytes. ≈100 B/frame after compression.

**Per-frame binary sections** (each gzip+base64 inside the envelope):
- `nodes` — the sprite draw list "as drawn" by the game's own walker (`FUN_140620f10`): kind, slot, category, sort,
  screen coords, scale, depth, angle, hotspot, facing, palette bank, owner (stride 54 B).
- `anodes` — world nodes (stage props, effects, HUD polygons): list id, flags, 4×4 matrix, colour, object index, model
  pointer (stride 100 B, ≈60–80 nodes/frame).
- `aobjs` — the polygon-list objects those nodes reference, interned by content hash (NaomiLib records: PCW/ISP/TSP/TCW
  headers + 32 B vertices). Static props are interned once; **animated props re-intern every pose** (measured: 200 of
  1260 dwords change per frame on a 5 KB mesh) — this is the whole spread between a 3 MB and a 14 MB tape.
- `objs` — System-B effect objects (hit sparks etc.), `palrows` — the engine-resolved palette rows `blk+0x13C0`
  (148 B/frame), `pals` — DatPal palettes, `confirmed_in` — GGPO's confirmed input ring (online matches only),
  `calib`, `select_in`.
- **anchors**: `anchor` (character-select blk, 2.5 KB gz) and, since 0.3.47, `battle_anchor` = one clock-edge read of
  `[blk 0x33B18][game_state page 0x1000 @exe+0xAC6D40][exe page 0x400 @exe+0x2EDF300][ctx texture-slot table 0x319C
  @ctx+0x1E0030]` = 229,556 B → **12.6 KB gz**, plus `battle_anchor_blk/ctx/dcram/frame`.
- identity: `reporter/winner/loser` SteamID64, `p1_team/p2_team` (0.3.48: char ids at match start), `costume[6]`,
  `stage_id`, `side`, `local_pn`, `seat_map`, `ts`, `match_key`/`session_id`/`match_index`. **Names are never
  transmitted** (Tris directive 2026-08-25); the server resolves them.

**Flow.** recording START at the first battle frame → rows + sections every frame → recording END (team wiped /
counter stalled / frozen base) → **0.3.48 local copy** `%LOCALAPPDATA%\RetroReceipts\gs-cache-local\` (never uploaded,
newest 8) → on a win-report the server returns a match key and the tape is spooled to `gs-cache\` → the designated
uploader (smaller SteamID) POSTs `/rr/gamestate` between matches (base64 of the gz inside JSON; 413-parked 6 h if the
server body limit rejects it — **lane 1 must raise `GS_MAX_BODY`**, see `HANDOFF-LANE1-GS-MAX-BODY.md`).

**Sizes, measured on nine tapes (2026-09-03):**

| tape | stage | length | gz | rate |
|---|---|---|---|---|
| 59613970 | 16 | 106 s | 3.2 MB | 1.8 MB/min |
| 59614009 | 3 | 51 s | 1.7 MB | 2.0 MB/min |
| 59614014 | 3 | 108 s | 8.7 MB | 4.8 MB/min |
| 59613987 | 16 | 112 s | 11.1 MB | 5.9 MB/min |
| 59613991 | 16 | 47 s | 10.3 MB | 13.0 MB/min |
| local stage 9 (0.3.48) | 9 | 87 s | 2.1 MB | 1.4 MB/min |

A 2–3 minute match is 10–18 MB at the typical rate, 4 MB best, 39 MB worst. On the wire today ×1.33 (base64).
Levers measured: raw body + Content-Encoding (−25 %), zstd -19 instead of gzip (1.5–1.85×; xz 1.7–2.3×), delta-intern
animated prop poses (≈5× on that section), reference-encode static world nodes (58 % identical frame to frame; modest).

## 2. The simulation: why a match is reproducible from inputs

Read from the native x86-64 recompile in Ghidra and gated in a p-code emulator (`docs/DETERMINISM-CONTRACT.md`,
`FRAME-READSET.md`, `EMU-GATE.md`, `RECEIPT-RUNNER-*.md`):

- The GGPO tick `FUN_140118950` wraps the whole frame `FUN_140607d60`, including the render pass and the sprite walker.
- Its inputs are two pad words (`game_state+0x218/+0x21C`). It reads only `blk`, one game_state page, one exe data page
  and the renderer's texture-slot table; the RNG is 2 bytes at `blk+0x32BD4` inside the saved block; no time, rand,
  thread or Steam call is on the tick path; FMA vs non-FMA is bit-exact; 12 B of uninitialised stack have no effect.
- Whole-frame emulation gate: 0 of 211,736 state bytes differ after a live frame.
- The frame writes **nothing persistent outside `blk`**: over 237 live frames the 32 MB DC-RAM image changed by 12,939 B in
  13 ranges, all regenerated scratch (tile table, animated props written absolutely from phase counters that live in
  `blk`, effect UVs, HUD header bytes).
- Character images rebuild from the user's arc by the slot recipe (11 AFS files per slot, 66/66 byte-exact); loaded
  polygon banks carry load-time patches the runner replays.
- **Receipt gate (first real receipt, 2026-09-03):** agent 0.3.48 offline tape, stage 9, 5,222 frames, 0 rollbacks →
  `anchor_to_run.py` + `pl_rebuild.py` + `receipt_gate.py --frames 300 --input-shift 1` → **clock 300/300, x 300/300,
  y 300/300, health 300/300.** Row N's inputs are the ones that produced frame N. A post-match dump has PL slot 1
  overwritten by the results screen, so character images come from the arc, never from a post-match dump.
- **Receipt size:** anchor 12.6 KB gz + 4 B/frame = ≈43 KB of inputs for a 3-minute match. Projection: 50–100× smaller
  than the geometry tape. The native runner that turns a receipt into a tape (and then pixels) is designed with gates
  0–5 in `WORKSTREAM-RECEIPT-RUNNER.md`; gate 0 passed, gates 1–5 not built. **Do not claim pixel-perfect from inputs
  end to end yet.**

## 3. The renderer: tape → pixels

- **Assets** come from the user's own arc (BYOR): character sprites (PL idx/asm/lut + GFX bins), stage POL geometry and
  textures (host-decoded pages, `rip_texbank.py` — folded into `pack_assets.py` for new stages), HUD/effects banks, the
  camera block, frozen pipeline templates. A pack is ≈21–23 MB per match and never leaves the user's machine or the dev
  box; `packs/`, `wasm/` and every `.seq/.pack/.bin/.png` derived from the game are gitignored.
- **Emitter** (`rr-render`): sprite path (parts assembly, palette LUT, rotation, flips, 640-space placement as the walker
  drew it) + world path (NaomiLib polygon groups, render-state law from PCW/ISP/TSP, translucent sort key = w of the mesh
  centre through W·V·P, frame background from `blk+0x6CB4`, deck = arc model 0 at identity) + closed-form world camera.
  Gates: W1 12,621/12,621 sprite draws exact vs Python; W2 90,673/90,673 full draws exact.
- **FrameRecord v1** (`feed.rs`): first-use-only tables (pipeline states, textures, constant buffers), VB, IB, 60-B draw
  structs; ≈700 KB/frame today (the static deck VB is re-sent each frame — next lever). Records must be consumed in
  feed order; the worker fills gaps on a seek (seek gate 3/3 hash-equal).
- **Player**: WebGPU, scene RT 2048×1024 with the game viewport 1280×960 (Steam's own 2× internal resolution — the
  Collection draws 640(k+1)×480(k+1) centred in a window-height-keyed RT, `STEAM-GRAPHICS-OPTIONS-GHIDRA.md`).
  `res=2|3|4` multiplies RT + viewports (vertices are NDC); `filter=box` averages every texel into a 640×480 canvas
  (Steam point-samples; box is our supersampling extra). Speed: native emitter 14.1 ms/frame; in-app 60 fps.
- **In the PWA** (`ReplayEmbed.svelte`): compact 640-px card inline, fullscreen with plates in the pillar bands, transport,
  keyboard, orientation lock, states loading/pending/expired/unsupported; metadata (names, ranks, date, stage) resolved
  server-side at replay time; cloud skins per `/rr/loadout` (chrome-top now; inside the picture once the emitter takes a
  skins option).

## 4. Gates you can run (all absolute, all repeatable)

```
cd C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\replay && python serve.py
node C:\Users\trist\projects\RetroReceipts-agent\rr-render\tools\gate_seek.mjs "http://localhost:8099/player.html?tape=packs/local_stage9/tape.json.gz&pack=packs/local_stage9&start=600&count=120&auto=1" 60 100 119
node C:\Users\trist\projects\RetroReceipts-agent\rr-render\tools\gate_l3.mjs --seq gold_13_1500.seq --tape packs/59613662/tape.json.gz --pack packs/59613662 --start 1500 --count 60
cd C:\Users\trist\projects\RetroReceipts-agent\rr-render && RR_PROF=1 .\target\release\emit_seq.exe <pack>\tape.json.gz --pack <pack> --start 600 --count 120 --feed-bench
cd C:\Users\trist\projects\mvc-live-skins-quarters && python d3dcap\replay\receipt_gate.py --run d3dcap\ttd\runs\receipt-20260903-stage9-anchor --tape "%LOCALAPPDATA%\RetroReceipts\gs-cache-local\local_1788462750766_stage9_76561197999665347.json.gz" --frames 60
cd C:\Users\trist\projects\RetroReceipts-agent\pwa && node scripts\smoke-replay.mjs --l3 http://localhost:8099
```

## 5. Services from agent to pixel (runtime), and the consolidation target

Today: agent → server API (:7250) → tape store on disk → static web → browser (wasm worker + WebGPU); live results ride
Redis pub/sub + the SSE gateway (:7251). Dev-only: Python oracle emitter, standalone player, `serve.py`, the pack script.
**Two product rules (Tris, 2026-09-03):** (1) replays are for signed-in users — the PWA resolver refuses a tape without an
account (`source.ts`, shipped), and the future public tape read must be authed; (2) **host/lobby nodes render**: the
arcade host machines own the game, so they can derive asset packs and run the emitter (later the receipt runner) as
their work and serve rendered results to signed-in viewers, which is how phones and non-owners get replays without any
ROM-derived bytes leaving a machine that owns the game.
Target: three components — agent (capture + local asset derivation, the pack step moves into `rr-render` and runs on the
user's machine), server (store + bus + the public tape read), PWA (emit + render). The receipt runner later replaces the
geometry tape inside the agent/emitter without changing the count.

## 6. Rules that made this possible

The RE method (`RE-METHOD.md`): port SH4 annotations by function matching; seed with unique constants and propagate
along the call graph; translate globals through the block map before comparing; tag CONFIRMED vs INFERRED and store
pairs as graph edges. Never guess (cite Ghidra, a file:line, a dump, or say UNKNOWN). Render only the game's real
assets. BYOR. No time estimates. Full absolute commands for live steps.
