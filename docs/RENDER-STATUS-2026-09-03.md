# Render program — status 2026-09-03 ("gold standard" checkpoint)

Tris on the stage-13 tape render (`tape_v5_59613662_stage13.seq`, agent 0.3.39): **"this is a gold standard,
this looks good, just a few tweaks."** This file records what that render is made of, what is proven, what is
still derived-but-ungated, and the open tweaks. Method: `docs/RE-METHOD.md` (locked). Knowledge: `re_kb`.

## What the render is (tape → pixels, no game, no emulator at playback)

| Layer | Source | Proof |
|---|---|---|
| Fighters, projectiles, effects sprites (System B) | tape nodes (sid, scale, angle, hotspot, facing, pal, owner) + ROM sprite rips (GFX1/GFX2 assembly) | 100% pixel gate on 30 training-stage captures incl. supers; walker emulated 47/47 fields bit-exact (`EMU-GATE.md`) |
| Camera | closed form from blk+0x6914/0x695C/0x6974/0x6988/0x698C; tape eye/zoom; state byte blk+0x6908 | P/V 16/16 bit-identical to the bound CB (emulated); fit error 0.012 (`WORLD-CAMERA-GHIDRA.md`) |
| Stage deck | arc `STGxx` POL model 0 at identity + world CB; textures = TEX file via `rip_texbank.py --bank stage` (HOST decode); deck colour blk+0x6CA8; blackout gate blk+0x3D50 | direct-draw mechanism read in `FUN_140620960`; deck floor lands on the ground line to 1 px; textures byte-exact vs captured pages (16/16 bank-derivable) |
| Stage props, effects geometry, HUD geometry (System A) | tape world nodes (matrix, flags, colour, alpha) + interned NL polygon-list objects, decoded as polygon groups with Steam's strip winding | 99.6% vertex identity vs arc meshes; render state 824/824 (blend 820/824) (`TSP-RENDER-STATE-GHIDRA.md`) |
| Effects / HUD textures | `rip_texbank.py --bank arc|hud` from `game_50.arc` AFS entries 799/800, 835/836; TCW = base + texIndex | 16/16 captured pages byte-exact; 73-page library |
| HUD projection | HUD scene block = `FUN_14061d5b0` (angle 0x4000, V=I), bytes from gold CB 04E19F4C | 171/177 gold list-11 draws bind it |
| Vertex colour | record alpha @0x2C, RGB @0x30 × node/deck multipliers, packed R,G,B,A | gold HUD bars ff0000ff / ffff00ff |

Agent 0.3.40 (`rr-agent-v7.exe`, running): tape v5, nodes stride 54 (+angle/hotspot/owner_off), anodes stride 100
(+alpha), rows +cam_state/look/fov/yoff/roll/deck/blackout, +`palrows` (0.3.40). Consumers: `tape_to_seq.py`, `tape_audit.py`.

**Tape size (0.3.39):** stage 13 match 6,272 frames (1.7 min) = 3.16 MB gz; stage 5 match 4,904 frames = 4.26 MB gz
→ **1.8–3.1 MB per minute**, 70–90% of it the world-node stream (`anodes` 3–4 MB b64 per match). The v6 wire
(`TAPE-V3-SPEC.md` §9.5, keys instead of object bytes) is the size lever; not built.

## Open tweaks (each has an owner agent + a numeric gate; none needs a capture)
1. ~~Translucent ordering~~ **CLOSED 2026-09-03**: cat 0/1 by submission, cat 3 qsorted DESC by the record key (`TRANSLUCENT-SORT-GHIDRA.md`, seed 39); `sort_gate.py` 0 key rises on 3 frames; emitter `order_draws` live (`--legacy-order` keeps the old path).
2. **Mirror-match palette — DERIVED 2026-09-03** (`PALETTE-SOURCE-GHIDRA.md`, seed 38): the bound LUT = the engine's
   STAGING LINES `blk+0x1040 + bank*0x38` (bank = slot base {0x10..0x38} + record row), filled from
   `DatPal + (node+0x39 variant)*0x100`; the tape's `pal` is costume 0 row 0. Gate `palette_gate.py` 494/518 LUT pages
   byte-exact (24 = a 1-frame LUT lag). Tape delta: `palrows` = one 0x540-B read at blk+0x13C0 per frame — **agent 0.3.40 built + running** (`rr-agent-v7.exe`); consumer done (`tape_to_seq.py --pal-lag`); audit C8.
3. **Hit sparks** — list 0xC turned out to be the COMBO COUNTER (`PARTS-LIST0C-GHIDRA.md`, gated 24/24, 82/82; harvest
   delta = 44-B `pnodes`). Sparks are System-B objects (cat 3, sids 1002..1006 in the OWNER's sprite set); they drew
   with the wrong character's rip because the bank key `& 0xFFFF` collapsed all fighters (fixed 56617e6). Verify on
   the re-rendered stage-13 clip.
4. ~~Portraits~~ **CLOSED 2026-09-04** (`PORTRAIT-PAGES-GHIDRA.md`, seed 116): TCW **0xC9A..0xCA5** are twelve
   PER-CHARACTER slots the engine rewrites at every match load (`FUN_14060d560`) from each fighter's own DAT
   (AFS `3+cid`, 16-bit LZSS `FUN_140611e90`): portrait = 0xC9A + `{0,3,1,4,2,5}[slot]` from DAT page
   `{1,0,3,0}[assist[slot]]`, name plate = 0xCA0 + same k from page 2. Gate `rip_portraits.py --gate` **29/29**
   captured library pages reproduced byte-exact. Resolving them from the capture-derived TCW library instead was
   drawing the CAPTURE's roster (Sentinel/Storm/Magneto) on every tape — the "wrong character's portrait, health
   bars don't follow tags" bug. Live in `rr-render/src/world.rs hud_portrait_pages` + `tape_to_seq.py`; pages ship
   in the asset pack as `portraits/`. **Still open:** TCW 0xC99 / 0xCA6..0xCA8 (same file, sub-blobs 1 and 2) are
   ripped but unbound — the slot is global and re-uploaded on a character switch.
5. Whole-frame read set from the p-code emulator on the mid-match images (`d3dcap/ttd/runs/20260903-000941/pre`).
6. Scripted camera (blk+0x6908 == 1) rendering from look/fov/yoff/roll — fields carried, renderer not yet.

## Dead ends (recorded, do not retry)
- TTD/WinDbg time-travel recording: attach blocked by the exe's own runtime layer hooking NtResumeThread; launch mode
  never finishes loading. `rr-ttd-frame-trace` memory.
- `rip_stage.py`'s texture decode (transposed twiddle, wrong 565/1555 expansion) — geometry fine, textures not.

## Gates & tools
`tape_audit.py` (A–H per tape) · `tsp_gate.py` · `worldgeo_gate.py` · `emu_gate.py` · `rip_texbank.py --gate` ·
`v3gate.py`/`rotgate.py`/`emitter_gate.py` (sprites) · player http://localhost:8099/player.html?seq=<seq>.

## Plan of record (2026-09-03, after expert review)
`docs/WORKSTREAM-CLIENT-REPLAY.md` v2: the server streams the tape, the browser renders; receipt form (snapshot + 2 input words/frame, server-side emulation) vs playback tape; D0 decided (ship the asset pack to the test cohort — users own the game); M-interim decided (phone = server-side emit streamed over Redis/NATS pub/sub, keyed frames, WebGPU replayer only); order W0 tape-vs-capture gate → W1 sprites first → W2 world/state → W3 D3D descs via a Create*State hook → W4 pack → W5 v6 wire → W6 delivery; F receipt lane. Reviews: `WORKSTREAM-CLIENT-REPLAY.review-re.md`, `.review-render.md`.

**2026-09-03 ~03:20 — 'part of the background missing' ROOT CAUSE:** the agent's per-object caps (`AOBJ_MAX_BYTES` 4 KB / `AOBJ_MAX_RECS` 8) truncated every stage prop with more than ~6 meshes (stage 16: models 1..8 of 5..18 meshes shipped 2..7 records). Not the blackout (that was a second, real, dispatcher behaviour: gate != 0 skips deck AND list 5). Fixes: agent **0.3.41** (`rr-agent-v8.exe`, caps 128 KB / 128 records; objects intern once per match) + emitter `complete_prop()` (a list-5 object whose first record is an arc model's first mesh gets the model's remaining meshes appended — repairs every older tape).

**2026-09-03 ~04:20 — SHIP READINESS PASS.** Agent **0.3.45** (`rr-agent-v19.exe`) = 0.3.39 fields + palrows (0.3.40) + object caps 128 KB (0.3.41) + 413 parking (0.3.42) + block snapshot/throttles/pid cache (0.3.43–44) + frame-background inputs (0.3.45). **CPU with the game open at char select: 140% → ~10% of one core** (gamestate 3%, reader ~7% once the roster is stable; 25% for the first 5 s of a roster change). In-match figure still to be measured. **BLOCKER for shipping: server `GS_MAX_BODY` 8 MB rejects every v5 tape (413) — lane 1.** Also open: torn frames ~1%, W0 tape-vs-capture gate (needs one guided capture with the agent running), portraits 0xC99, combo counter `pnodes`. Frame background: three preamble quads now drawn from the rule (FRAME-BACKGROUND-GHIDRA.md; per-stage table for old tapes).
