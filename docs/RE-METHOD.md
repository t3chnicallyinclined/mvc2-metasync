# RE METHOD — the one way we reverse-engineer Steam MvC2 (locked 2026-09-03)

Steam MvC2 is a **static recompilation** of the Dreamcast SH4 game. The reference binary is the
annotated `marvelous2` SH4 disassembly (`maplecast-flycast/_marv_re/build/bank*.asm`); the target
binary is the Steam x86-64 executable in Ghidra (`C:\Users\trist\ghidra_projects\mvc_dump.bin`,
HTTP bridge on localhost:8080). The original data files sit at their Dreamcast addresses inside a host
copy of DC RAM (`host = *(*(0x142ef0ab0)+8) + (X - 0x0C000000)`). The mutable state block `blk`
maps onto DC work RAM through the piecewise block map (`d3dcap/replay/re_map/blkmap.py`).

## The four sentences (say them at the start of every RE task, and say which step you are at)

1. **Port the SH4 annotations to the Steam binary by function matching.**
2. **Seed with unique constants, then propagate along the call graph.**
3. **Translate globals through the block map before comparing reference sets.**
4. **Tag confirmed versus inferred, and store the pairs as edges in the knowledge graph.**

## Vocabulary

- **Function fingerprinting** — constants, float literals, global references, strings, callees.
  Never instruction bytes or register choices; those do not survive recompilation.
- **Semantic anchor / unique-constant match** — one constant, one function on each side
  (812.357, 0xC10, 0x0D82D000, 0x0F4A …). Near-certain; these are the seeds.
- **Call-graph propagation** — callers and callees of a confirmed pair are compared next.
- **Global reference translation** — DC addresses → `blk` offsets through the block map, then compare
  the sets a function touches.
- **CONFIRMED** = both sides decompiled/read and agree. **INFERRED** = fingerprint or graph only.
  An inferred pair is a hypothesis with evidence attached, never a fact.
- **Program knowledge base** — the `re_kb` SurrealDB graph (http://127.0.0.1:8001, ns `re`, db `kb`):
  `steam_routine -recompiles-> routine`, `reads`/`writes` → `global`, `calls`, `finding -about->`,
  `-cites-> source`. Seeds live in `maplecast-flycast/tools/re_kb/NN_*.surql` and rebuild the graph.

## Rules

- **Query before deriving.** `SELECT` the graph and read `docs/STEAM-SH4-FUNCTION-MAP.md` /
  `docs/steam_sh4_map.csv` before any decompile, live probe, or new tape field.
- **Derive before capturing.** A capture is a GATE for a derived rule, never the source of the rule.
- **Every claim carries an address and evidence.** Say UNKNOWN rather than guess.
- **Every result goes into the graph** as a versioned seed (`tools/re_kb/NN_*.surql`, idempotent
  UPSERT/RELATE), applied with `PYTHONIOENCODING=utf-8 python tools/re_kb/apply_seed.py <seed>` from the
  maplecast-flycast root after the documented backup. A doc alone is not a result.
- **Gates are deterministic and numeric** (vertex sets, byte-exact pages, max-abs matrix error,
  pixel diff). "Looks right" is not a gate.
- Do not re-run `tools/re_kb/07_dedup_edges.surql` (it strips confidence/evidence from edges).
- BYOR: never commit ROM-derived bytes (rips, pages, tapes, blk dumps).

## What the method has already settled (do not re-derive)

| Topic | Where |
|---|---|
| 510 Steam↔SH4 pairs, 35 confirmed; 10,803 Steam nodes | `docs/STEAM-SH4-FUNCTION-MAP.md`, seed `101_steam_function_map.surql` |
| Stage deck = direct draw of POL model 0, identity W, world CB; props = list-5 nodes; TCW = 0xC10 + texIndex | `docs/STAGE-DRAW-GHIDRA.md` |
| World camera closed form, stage-independent; no CPU vertex transform on any path | `docs/WORLD-CAMERA-GHIDRA.md`, seed `100_world_camera.surql` |
| Sprite walker / submit read set (System B) | `docs/TAPE-V3-SPEC.md` §10 |
| Texture banks: TCW = base + texIndex (0xC10 stage / 0xC50 effects / 0xC90 HUD), files = AFS entries inside game_50.arc, HOST decode (`rip_texbank.py`); 16/16 bank-derivable captured pages byte-exact; `rip_stage.py`'s texture decode is WRONG (transposed twiddle, 565/1555 expansion) | `docs/TEXTURE-BANKS-GHIDRA.md`, seed `102_texture_banks.surql` |
| Render state law: blend/sampler/depth/cull/ps from PCW/ISP/TSP + polygon-group word (`FUN_1408482a0`), Steam strip winding, vertex colour multipliers; gate 824/824 (blend 820/824: `node+0x90` alpha mult not in tape) | `docs/TSP-RENDER-STATE-GHIDRA.md`, seed `103_tsp_render_state.surql`, `tsp_state.py` / `tsp_gate.py` |
| HUD lists 0xB/0xD project through the HUD scene block (`FUN_14061d5b0`: angle 0x4000, V=I; gold CB 04E19F4C, 171/177 list-11 draws) | `d3dcap/replay/camera_block.json` 'hud' |
| World/deck vertex colour is packed R,G,B,A (gold HUD bars ff0000ff / ffff00ff) | `tape_to_seq.py` world pass |
| Translucent draw order: Z-write categories 0/1 in submission order, then category 3 qsorted (MSVC CRT `FUN_140817f80`, comparator `LAB_1408434d0`: f32 key DESC, tie = sequence ASC) by `FUN_140843320` = w of the record centre (`rec+0x10`) through W×V×P (radius<0 forces −r); sprite key = walker depth `node+0x12C` + 0.001/record, vertex z = `FUN_1408432e0(D)`; gate 0 key rises / 559 cat-3 draws, sprite z 133/133 + 96/96 at float32 rounding | `docs/TRANSLUCENT-SORT-GHIDRA.md`, seed `109_translucent_sort.surql`, `d3dcap/replay/sort_gate.py` |
| Emulation gate: camera routines and sprite walker reproduce captured bytes bit-exact (Ghidra p-code on captured `blk`); matrix stack storage = `blk+0..0x1000`; cell overrides need the DC-RAM image | `docs/EMU-GATE.md`, seed `104_emu_gate.surql`, harness `d3dcap/replay/emu_gate.py` |
| Whole-frame read set: `FUN_140118950` → `FUN_140607d60` (= `*(game_state+0x10)`, sim + render dispatch + walker + submit) emulated on the live dump images, deterministic (2 runs byte-identical), clock +1, tick → dispatcher re-run 50/50 walker fields / 0 blk bytes differ; pad words live at `game_state+0x218..0x224` (exe), LayerZ reset = `FUN_14060a1f0` per frame; per-frame reads: blk 10 KB, dcram 22.5 KB (PL slots + banks + the 0x0CE60000 table the frame rebuilds), exe 2.4 KB, ctx 1.9 KB; minimum tape = one `blk` snapshot (+ game_state/0x142edf300 pages + ctx slot table) + 2 seat words per frame; PL loader table still UNKNOWN | `docs/FRAME-READSET.md`, seed `106_frame_readset.surql`, `emu_gate.py frame` / `emu_frame.py` |
| Palette source: a draw binds the LUT of its texture-slot bank (`FUN_140845e20`, bank = slot base 0x10+8*slot + rec.flags>>4 from `FUN_140612180`), whose colours are the engine-STAGED rows `blk+0x1040+bank*0x38` (`FUN_1406146d0` = `loc_8c035162`; row 0 = `FUN_140614130` = `loc_8c035000` = DatPal + (node+0x39)*0x100), uploaded per frame by `FUN_140613390` to host PALETTE_RAM `dev+0xd8d04`, textured by `FUN_140048970`; DatPal `cl+0x4C`/`node+0x1B8` is the costume BLOCK base (tape `pal` = costume 0 row 0 = wrong); mirror colour = `node+0x39` (DC `char+0x25`); gates 494/518 draws + 46/48 rows; tape fix = TAPE v5 `palrows` (blk+0x13C0+slot*0x1C0, 8 x 0x38) | `docs/PALETTE-SOURCE-GHIDRA.md`, seed `108_palette_source.surql`, gate `d3dcap/replay/palette_gate.py` |
| Frame background: the scene RT is cleared by THREE DRAWS (host clear quad `FUN_14033c5c0(0x3f)` at the executor entry, the engine quad `FUN_140843eb0` (format 0x4000 → 40-B layout, colour bytes 0/2 swapped, texId 0xffff = 1×1 white), depth+stencil quad `FUN_14033c5c0(0x30)` at pass begin); colour = `FUN_1406101b0` == `loc_8c02dc4c`: stage words `blk+0x6CB8..` × deck `blk+0x6CA8..` per byte (int trunc), fade word `0x6CE4` → `0x6CF0` raw, blackout (entity+0x96 == G+0x98, && entity+6) → black; mode `0x6CB4` 0..3 → (A,A,A)/(A,B,A)/(A,A,B)/(A,B,C); stage table `DAT_14097db20` (3/0xC mode 2); gate 9/9 quads byte-exact, 2/2 scene-RT pixels (all stage 0x0B = black; colour path decompile-only) | `docs/FRAME-BACKGROUND-GHIDRA.md`, seed `110_frame_background.surql`, `bg_rule.py` / `bg_gate.py`, tape 0.3.42 columns `bg_mode,bg_col[3],fade_mode,fade_col,bg_gate[6]` |
| List 0xC = the COMBO COUNTER / rating / round text (not hit sparks): `FUN_140653a70` <-> `loc_8C0F215E`; node -> exe-static part list (`+0x110`) -> HUD-bank model (`PTR_DAT_142edf598[idx]`, AFS 835), page = `0xC92 + count - 1` via the header patch; CBWorld = composed T/S chain, V = I, no CPU vertex transform; consumer clears bit 0 of x and v; harvest drops these nodes by construction -> 44-B `pnodes` record; gate 5 frames: CBWorld 24/24, vertices 82/82, pages 82/82 | `docs/PARTS-LIST0C-GHIDRA.md`, seed `107_list0c_parts.surql`, `d3dcap/replay/parts_gate.py`, `rip_parts.py`, `blkstate.pnodes` |

## Agents bound to this method

senior-re-generalist · mvc2-sh4-re-expert · naomi-re-expert · steam-d3d11-capture-expert ·
flycast-internals-expert · mvc2-sprite-render-expert (each carries an "RE METHOD" block pointing here).
