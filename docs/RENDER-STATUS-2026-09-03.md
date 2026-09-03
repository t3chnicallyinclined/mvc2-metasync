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

Agent 0.3.39 (`rr-agent-v6.exe`, running): tape v5, nodes stride 54 (+angle/hotspot/owner_off), anodes stride 100
(+alpha), rows +cam_state/look/fov/yoff/roll/deck/blackout. Consumers: `tape_to_seq.py`, `tape_audit.py`.

**Tape size (0.3.39):** stage 13 match 6,272 frames (1.7 min) = 3.16 MB gz; stage 5 match 4,904 frames = 4.26 MB gz
→ **1.8–3.1 MB per minute**, 70–90% of it the world-node stream (`anodes` 3–4 MB b64 per match). The v6 wire
(`TAPE-V3-SPEC.md` §9.5, keys instead of object bytes) is the size lever; not built.

## Open tweaks (each has an owner agent + a numeric gate; none needs a capture)
1. ~~Translucent ordering~~ **CLOSED 2026-09-03**: cat 0/1 by submission, cat 3 qsorted DESC by the record key (`TRANSLUCENT-SORT-GHIDRA.md`, seed 39); `sort_gate.py` 0 key rises on 3 frames; emitter `order_draws` live (`--legacy-order` keeps the old path).
2. **Mirror-match palette** — both Magnetos render with the same palette; the tape ships DatPal (cl+0x4C), not the
   per-slot bank the submit binds. Gate: rebuild captured palette pages byte-exact.
3. **Hit sparks** — list 0xC per-fighter 3D parts (walker `FUN_140653a70`), dropped by the harvest filter
   (`obj||model`); geometry in the 0xC90 bank POL. Gate: reproduce the 25 gold view-space draws of frame 4445.
4. **Portraits** — TCW 0xC99..0xCA8 patched at runtime from character DATs (INFERRED); capture-derived for now.
5. Whole-frame read set from the p-code emulator on the mid-match images (`d3dcap/ttd/runs/20260903-000941/pre`).
6. Scripted camera (blk+0x6908 == 1) rendering from look/fov/yoff/roll — fields carried, renderer not yet.

## Dead ends (recorded, do not retry)
- TTD/WinDbg time-travel recording: attach blocked by the exe's own runtime layer hooking NtResumeThread; launch mode
  never finishes loading. `rr-ttd-frame-trace` memory.
- `rip_stage.py`'s texture decode (transposed twiddle, wrong 565/1555 expansion) — geometry fine, textures not.

## Gates & tools
`tape_audit.py` (A–H per tape) · `tsp_gate.py` · `worldgeo_gate.py` · `emu_gate.py` · `rip_texbank.py --gate` ·
`v3gate.py`/`rotgate.py`/`emitter_gate.py` (sprites) · player http://localhost:8099/player.html?seq=<seq>.
