# Review of WORKSTREAM-CLIENT-REPLAY.md (DRAFT v1) — Steam D3D11 / capture side

*Reviewer: steam-d3d11-capture-expert, 2026-09-03. Scope: the render facts the draft rests on, checked against
the docs/graph it cites and against the capture gold on disk (`d3dcap/replay/seq_5331_5630.seq`,
`seq_8931_9230.seq`: 600 consecutive in-match frames, 380,326 scene draws, 11 pipeline states each).
Ghidra (bridge :8080, `mvc_dump.bin`) was used only where the docs left a claim open; every such read is
marked. Tags: CONFIRMED (both sides read / reproduced by a gate), INFERRED (fingerprint or gate only),
UNKNOWN (not located). Nothing here was committed; no ROM-derived bytes are quoted.*

**Note on timing.** Three artefacts the draft calls "pending" landed while this review was written:
`docs/TRANSLUCENT-SORT-GHIDRA.md` (02:10), `docs/PALETTE-SOURCE-GHIDRA.md` (02:13), seeds
`108_palette_source.surql` / `109_translucent_sort.surql`, and agent **0.3.40** (`d9187dc`, `palrows`). The
draft's §1 row 9, §5 RE-C1/RE-C2 and §10.3 are already out of date against them; the corrections below
use the newer state. Seed numbers 38 and 39 now **collide** with the maplecast lane's
`38_per_part_depth_zinvW.surql` / `39_camera_zoom_audit.surql` — rename before `apply_seed.py`
(`RE-METHOD.md` "every result goes into the graph as a versioned seed").

---

## 1. §1 claims, row by row

| # | Row | Verdict | Evidence / correction |
|---|---|---|---|
| 1 | Sprites (System B): walker fields → GFX assembly; rotation; scale-walker; tiled flips. *100% pixel gate on 30 captures incl. supers; walker 47/47 bit-exact* | **CONFIRMED, scoped** | 47/47 is frame 4445 (10 fields × 47 nodes, `EMU-GATE.md` §4 table); 4505/5168/7279 add 6/5/4 nodes. **Omitted:** on cell-override frames 5227/5232 the emulated walker gets scale/angle/hotspot WRONG on every node with `+0x191 != 0` because it reads the owner's animation-cell table in the DC-RAM host image (`EMU-GATE.md` lines 22, 143-144, §5). The tape survives this only because it ships the walker's OUTPUTS — which requires the agent's clock-edge sample to land AFTER the walk. That phase is unmeasured (`PARTS-LIST0C-GHIDRA.md` §5 last paragraph). See §2 item M12. The "30 captures" are the training-stage guided bursts (`RENDER-STATUS` row 1); hit sparks (RE-C3) remain open on real matches. |
| 2 | Camera: P from fov + y-offset, V = LookAt(eye, target, roll). *16/16 bit-identical; 0 violations over 1436 frames* | **CONFIRMED, scoped** | 16/16: `EMU-GATE.md` line 218 (`FUN_14061d7e0` vs CB `7793F141`). "0 violations / 1436 frames" is the **state-0 sufficiency check on stage 0x0B only** (`WORLD-CAMERA-GHIDRA.md` lines 9, 30: "sufficient while `blk+0x6908 == 0`"). Scene-CB rows 4-6 are INFERRED (line 158-165; row 6's `(c, 1/c)` far constants are "use the two constants"). "Stage-independent" is CONFIRMED by code read (P/V read only `blk+0x6914..0x698C`), not by a second stage's capture — all 1436 gate frames are one stage. |
| 3 | Stage deck: POL model 0 at identity + world CB, HOST decode, deck colour 0x6CA8, blackout 0x3D50. *mechanism read in FUN_140620960; floor on the ground line ±1 px; 16/16 bank pages* | mechanism **CONFIRMED**; "±1 px" **OVERSTATED**; "16/16" **misattributed** | Mechanism: `STAGE-DRAW-GHIDRA.md` §0, function-map rows `FUN_140620960` ↔ `loc_8c030858/cc0/cfc` (confirmed both read). **"±1 px" is not a numeric gate in any doc** — `STAGE-DRAW-GHIDRA.md` line 223 gives a vertex-count gate; the ±1 px is the RENDER-STATUS eyeball note ("lands on the ground line to 1 px"). Cite it as an observation, not a proof. "16/16 bank pages byte-exact" is the whole-library count (`TEXTURE-BANKS-GHIDRA.md` §5: effects 9, HUD 2, stage-0B **1**, plus 4 re-keyed); the stage deck's own evidence is **one page on one stage**. `rip_stage.py`'s TEX decode is falsified 0/11 (same doc) — the draft knows this (§8), fine. |
| 4 | World objects: tape nodes + NL polygon groups, Steam strip winding, TCW = base + texIndex. *99.6% vertex identity; 16/16 pages* | **CONFIRMED, with a residual the row hides** | Winding gate is **442/454**: the 12 misses are bit-6 5-vertex strips (`0x72`, `0xF2`) whose captured VB order is `(v0, v2, v1, v4, v3)` and "the consumer that reorders them is not identified (UNKNOWN)" (`TSP-RENDER-STATE-GHIDRA.md` §5). 99.6% is quoted from `RENDER-STATUS` (worldgeo_gate); not re-run here. |
| 5 | Render state from PCW/ISP/TSP + group word. *824/824 (blend 820/824)* | **CONFIRMED for world draws (kinds 0-3); INFERRED D3D tables; sprite path absent** | (a) Every "D3D (…)" column is INFERRED single-valued from the gate — the state-object creation was searched for and **not found** (`TSP-RENDER-STATE-GHIDRA.md` §2.5, §7.3). (b) Never captured: blend presets 0x16/0x19/0x22/7/0, sampler words 0x40000/0x50000 (TSP flip bits → "presumably MIRROR"), depth presets 1/3/5/10/0xB. (c) The law covers **only** `FUN_1408482a0` (kinds 0-3). Sprite draws (kind 0xC) are not in it; their law is established below (§2 M3) and is different: constant blend, sampler from a per-record flag. (d) Vertex colour is 647/776 (§4). (e) The 4 blend misses are the `+0x90` alpha multiplier, shipped since 0.3.39 (`reader.rs:1389-1393`) but **not re-gated** — the draft still quotes 820/824. |
| 6 | HUD projection: `FUN_14061d5b0` block, angle 0x4000, V = I. *171/177* | **CONFIRMED** | `camera_block.json` 'hud' note; `EMU-GATE.md` line 220 (16/16 vs CB `04E19F4C`, 339 draws). The 6 "misses" are identity-matrix joins ambiguous with list 6, not failures. The SH4 pair `loc_8c02e334` is fingerprint-"high" only (`steam_sh4_map.csv:138`) — irrelevant to rendering, since the Steam side is emulated bit-exact. |
| 7 | Combo counter (list 0xC): node → static part list → HUD-bank models; page 0xC92+count−1. *24/24, 82/82* | **CONFIRMED — but not carriable** | `PARTS-LIST0C-GHIDRA.md` §7. The 44-B `pnodes` record the doc specifies (§5, diff for `reader.rs`) is in **neither 0.3.39 nor the 0.3.40 working tree** (`grep pnodes reader.rs` → 0 hits). The harvest filter `obj != 0 \|\| model != 0` (`reader.rs:1414`) drops every list-12 node by construction. The draft's Workstream A does not list it. |
| 8 | Flush order: "category 1 (Z-write) first in submission order, then category 3 sorted by the walker depth key (`FUN_140843320`)". *2.4e-7 on 2/3 frames; one frame 118 vs 122 open; ordergate (uncommitted), seed 39 pending* | mechanism **CONFIRMED**; the row's wording is **WRONG in four places** | From `TRANSLUCENT-SORT-GHIDRA.md` (now on disk) and `sort_gate.py`: (i) the Z-write phase is **categories 0 AND 1** (PCW list type 0 → cat 0, type 1 → cat 1), not "category 1"; (ii) `FUN_140843320` is the key for **world/HUD records** (w of the record centre through W·V·P·Screen); the **sprite** key is the walker depth `D = node+0x12C + 0.001·k` (`FUN_1408436a0` case 0xC, read in Ghidra today: `fVar18 = entry+0xC; entry+0xC = FUN_1408432e0(D); cat = (entry+0x30 != 0) ? 3 : 0`) — the row conflates them; (iii) the gate is `sort_gate.py`, not `ordergate.py` (`ordergate.py` tests intra-assembly record order with the sid known); (iv) **"118 vs 122" is not an open model gap**: the 4505 pack and the 4505 state dump are different moments (dump 118 sprite records, pack 122; `TRANSLUCENT-SORT-GHIDRA.md` §2 table) — a capture-alignment artefact. "Key rises" is **0 on 3/3 packs**; vertex-z reproduction 133/133 and 96/96. RE-C2 as written ("per-part depth increment") chases a non-defect; the fix is a synchronous capture (shim walker hook, `"at":"walk"`, pairs N↔N). |

**What §1 does not contain and must:** the sprite-path state law (M3), the per-frame preamble that
actually clears the frame (M2), the palette source (M7 — `PALETTE-SOURCE-GHIDRA.md` supersedes the RE-C1
question), and the post chain (M1).

---

## 2. Steam-side RE items the draft misses (what the capture gold shows that tape + arc cannot yet reproduce)

Each item: capture fact → what the tape/emitter does today → Ghidra task → gate.

### M1. The post chain. "Pixel-exact" in the draft means the PRE-BLOOM scene RT, and the user never sees that.
* Capture: 760-873 of ~890 draws go to the `2048x1024 B8G8R8A8` scene RT at viewport `(384,32,1280,960)`; then a
  9-pass chain to the `1280x768` backbuffer (`RENDER-ACCURACY-PROGRAM.md:1197-1198`; per-frame clears of two
  `1280x768` and one `640x384` fmt-28 intermediates are in every frame's `clears`, e.g. frame 5481). One draw in
  the chain uses `D3D11_TEXTURE_ADDRESS_BORDER` (`state.mjs` sampler comment; `pack_replay.py` refuses it). The
  chain applies bloom + SMAA (config.ini `SMAA`, `RENDER-ACCURACY-PROGRAM.md:951`) and a **1280x960 → 1280x768
  vertical resample**. `pack_replay.py` drops every draw whose RT is not the scene RT; `classify_shaders.py` has
  classified only the 6 PS / 4 VS of the scene (`shader-map.json`).
* Today: nothing in the draft renders past the scene RT. Every "byte-exact" gate is against `scene_*.bmp`.
* Task (host renderer `R = DAT_140acd3a8`, not game code — no SH4 pair exists): extend `pack_replay.py` to keep
  the post-chain draws (RT ≠ scene RT) with their CBs; classify the remaining captured shader bytecode; port.
  WebGPU has no BORDER address mode → that pass needs shader-side border emulation.
* Gate: replayed backbuffer vs `hkPresent`'s `shot_*.bmp` (`dllmain.cpp:1444-1469`) byte-exact, three points of a
  burst. **Decision for Tris before E3:** either the page states "pre-bloom scene RT" and the release gate diffs
  that, or M1 is on the critical path. The draft's §7.3 release gate is silently the former.

### M2. The frame is cleared by DRAWS, and the background colour is a `blk` function the tape does not carry.
* Capture (every frame of both sequences): draws 2-4 are three full-screen NDC quads at z = 1.0:
  (i) untextured, blend OFF, `DepthFunc ALWAYS`, depth write ON, stencil REPLACE ref 0 — `FUN_140843eb0`'s quad
  (Ghidra, read today: colour `ctx+0x1f8248/4c/50 | 0xff000000`, texId `0xffff`, `FUN_140048370(0x4000, …, 0x1c, 4, …)`);
  (ii) a **1x1 fmt-28 page** (the `04000000_ad9513` texture of UNKNOWN origin, `TEXTURE-BANKS-GHIDRA.md` §8.5),
  normal blend, LESS_EQUAL, write ON; (iii) `ps = null`, colour mask 0, ALWAYS, write ON (a depth-only pass).
  So the ledger's "the scene RT is never cleared" is true of `ClearRenderTargetView` and false of the frame: colour,
  depth and stencil are fully rewritten every frame. (Good news for scrubbing: no cross-frame RT state.)
* Today: `tape_to_seq.py:1264` emits `ClearRenderTargetView [0,0,0,0]` and no depth/stencil reset draw. Equivalent
  only when the background is black — false on blackout frames (`blk+0x3D50 != 0` skips deck and lists 5/6, so the
  background IS the picture).
* Ghidra (done today, CONFIRMED): the colour words are written by `FUN_1408450e0(r,g,b)` (only two writers of
  `ctx+0x1f8248..50`: `0x1408450a7..c1` and `0x1408450e7..101`). Its match-time caller is `FUN_1406101b0`
  (xref `0x140610470`): mode `blk+0x6CB4 ∈ {0,1,2,3}` selects among three packed RGB byte-triples at
  `blk+0x6CB8`, `blk+0x6CBC`, `blk+0x6CC0`, each channel multiplied by the deck floats `blk+0x6CA8/AC/B0`
  (in-match path: `FUN_140619960() == 0` and `DAT_142edf628+0x96 == 0`), else `blk+0x6CF0` raw. The other
  setter `FUN_1408450a0` is called from a `caseD_0` at `0x140611cb8` (menu/loading; function not resolved by the
  bridge). The 1x1 page's creator: UNKNOWN.
* Tape: rows carry `deck[3]` and `blackout` but **not** `0x6CB4`, `0x6CB8..0x6CC2`, `0x6CF0` (20 B). Add them, or
  gate that they are per-stage constants.
* Gate: per captured frame, the preamble quad's colour word (vertex bytes +16 of draw 2, stride-28 layout) ==
  derived from the same frame's `blk` dump (`capgate/state`), 1436/1436; plus the 1x1 page's texel × vertex colour
  explains the RT value in an uncovered pixel.

### M3. The sprite-path render state — never written down; the tape's `blend` byte contradicts it.
* Capture: **94,976 indexed (pp_Palette) draws across 600 frames — including the 3-meter triple super — and every
  one is** `(SRC_ALPHA, INV_SRC_ALPHA)`, depth write OFF, LESS_EQUAL, cull NONE, both samplers POINT+CLAMP. **Zero
  additive sprite draws.** Every `(SRC_ALPHA, ONE)` draw (9,135 in seq 5331-5630) is a `vs_world` polygon draw
  from lists 7/8 with the record's own TSP.
* Ghidra (read today, CONFIRMED): `FUN_1408458b0` (sprite consumer) issues **no blend command**; the flush's cmd 1
  is `BLEND_PRESET[slot+0x1a]`, `slot+0x1a = ctx+0x1f8274` (`FUN_1408436a0` tail), and `ctx+0x1f8274` has exactly
  **one writer in the whole disassembly cache**: `0x140844ad8: MOV [RAX+0x1f8274], 0x45` (`FUN_140844a10` init) →
  preset 0x32 → the same D3D object as (SRC_ALPHA, INV_SRC_ALPHA). Sampler: `FUN_140844320(entry.flags >> 12 & 1, 1)`
  = point/linear from bit 12 of the per-record flag word, address CLAMP. IgnoreTexA = `(0x45 & 0xf0) == 0x10` = false.
  Depth: cat 3 (`entry+0x30 = blk+0x32BDC != 0`), s19 0 → preset 2. Vertex z = `FUN_1408432e0(D)` on all four verts.
  Per-record flags also drive: bits 0-3 pixel snapping (`floorf`), bit 4 = flip U (`u = 1-u`), bit 5 clear = flip V,
  bits 11/17 → `FUN_140842c80` (UV scroll), `puVar4[10]` = rotation angle applied in the consumer with `cosf/sinf`.
* Tape: `nodes.blend` (`reader.rs:1343,1956-1960`) is a **port of the DC-lane heuristic** (`is_effect` value-test
  → 0x11) — it is not read from the engine and the Steam capture refutes it for the sprite path. `mvc-render-composite-model`'s
  "runtime blend global 0x8C2AA4C4" has no Steam counterpart on this path (the writer census above). For a
  Steam-exact render `blend` is redundant; additive effects come from `anodes` TSP words.
* Task: `FUN_1406129f0` — the node fields that set entry flag bits 4/5/12 (which node field is "filter"?); scoped to
  one decompile. Gate: a kind-0xC law in `tsp_state.py` and `tsp_gate.py` over the 4 packs, 100% on blend/sampler/depth.

### M4. The 12 bit-6 strips.
* Capture: 12 of 454 world draws (`0x72`/`0xF2` groups) have VB order `(v0, v2, v1, v4, v3)`; every state field passes.
* Task: `FUN_1408482a0`'s `gflags & 0x40` branch (or the topology argument of `FUN_140048370`). Gate: winding 454/454.

### M5. The never-captured presets are bounded by draw KIND — and can be resolved without a match ever using them.
* From `FUN_1408436a0` (read today): cat 2 (→ depth preset 10) only for kinds **4/5** (consumer `FUN_140848ce0`);
  s19 for kinds **0xD..0x12** comes from `ctx+0x1f8278` (→ preset 5 when 5); preset 1 is the flush default for
  cat 0/1 and cat 3+s19 1, and is **always overridden** by the kind-0..3 consumer (`ctx+0x1f8520 == 1`) and never
  reached by kind 0xC (cat 3, s19 0 → 2) — so preset 1 never reaches D3D in a match; 0xB: issuer UNKNOWN.
  Blend 0x16/0x19/0x22/7/0 need TSP src/dst pairs no match record carries; mirror samplers need TSP bits 17/18.
* Task A (instrument, not argument — `RENDER-ACCURACY-PROGRAM` method rule 4): hook
  `CreateBlendState/CreateDepthStencilState/CreateSamplerState/CreateRasterizerState` in `d3dcap` (it already injects
  at `CREATE_SUSPENDED`, before any creation), log every desc with its returned pointer; at first Present read the
  executor's tables (`FUN_140070940`: blend `R2+0x358+(hash&0xfff)*16`, DSS `R2+0x1e88/0x1e98/0x1ec8/0x1f08/0x3678/0x3688/0x3698`,
  RS `R2+0x1f58/0x1f68/0x2038`, samplers `[R2+0x20]+0x1780..0x3300`) and join by pointer. Every INFERRED row of
  `tsp_state.HOST` becomes CONFIRMED in one launch, including the codes no match exercises.
* Task B (Ghidra): callers of `FUN_1408436a0` with kinds 4/5/0xD-0x12/0x17/0x18 reachable from `FUN_140620960`; if
  none, those presets are out of scope by construction.
* Gate: every code in `tsp_state.HOST` maps to a captured desc; `tsp_gate.py --hist` never `AMBIGUOUS`.

### M6. The alpha-modulated blend override (carried, not yet gated).
* `anodes.alpha` (`node+0x90`) ships since 0.3.39. The gate still reads 820/824. The second half of the rule — a
  kind-1 node with alpha < 1 moves from cat 0 (Z-write phase) to cat 3 with s19 = 1 and gets **sorted** — is in
  `TRANSLUCENT-SORT-GHIDRA.md` §1 and `tape_to_seq.py`'s `_cat` ("PCW list type + kind + alpha"). Gate: `tsp_gate`
  blend 824/824 and `sort_gate` 3/3 on a 0.3.39+ tape. No Ghidra.

### M7. Palette LUT: format, source, and the one-frame lag.
* CONFIRMED (`PALETTE-SOURCE-GHIDRA.md` §0, gate 494/518): the draw binds `t1` = the **bank's** own 256x1
  R8G8B8A8 texture (`dev+0xd8500 + (bank + flip*0x40)*8`), each channel = nibble × 17; bank = slot base
  `DAT_140a6d188[slot]` + record sub-row (`rec.flags >> 4`), fixed at sheet registration `FUN_140612180`; colours
  from the staging lines `blk+0x1040 + bank*0x38` (+0x18, 16 × u16 ARGB4444; flag +8). Index values are 0..15
  (`rr-pathb-steam-capture` M6), so only entries 0..15 of the page matter. The tape's `pal` = `DatPal+0` = costume 0
  row 0 — wrong for every non-default colour (`reader.rs:133-136`); **0.3.40 `palrows`** (148 B/frame: 48 rows +
  48 flags) supersedes it. RE-C1's question ("where `FUN_1406129f0` gets the bound palette page") is the wrong
  question — that routine carries no palette.
* Residual: the **LUT lag** — 24/144 draws on frame 4505 bound a texture still holding the previous bank content
  (`PALETTE-SOURCE-GHIDRA.md` §1.1). Mechanism INFERRED (`FUN_140048970`'s per-flip memcmp + Map).
* Task: read `FUN_140048970` (sole caller `FUN_140843eb0`) for the exact refresh condition. Gate: `palette_gate.py`
  518/518. Answer to draft §10.3: **per (slot, row) texture, updated when the staging flag fires** — 48 small
  textures, not per node and not per slot.

### M8. Portrait patching (RE-C4) — writers CONFIRMED, derivation INFERRED.
* Read today: `FUN_1406162e0(fighter)`: `FUN_140611e90(*(fighter+0x1f8) + [4], host 0x0CE60000)`; `FUN_1408458a0(0)`;
  `FUN_140845830(0xC99, host 0x0CE60000)`. `FUN_140616330(fighter)`: same with `+[8]` and slot
  `0xCA6 + (*(fighter+0x230) >> 1)`. `FUN_14060d560`: per-slot 0x800-B copies into `0xC9A..0xCA5`
  (`TEXTURE-BANKS-GHIDRA.md` §6). The INFERRED link is `*(fighter+0x1f8)` = the character DAT (AFS `209 + cid`).
* Task: the writer of `fighter+0x1f8` (expected beside the `FUN_14060dcf0(209+cid)` load). Gate: 29 captured
  `0xC9A..0xCA5` pages byte-exact from AFS `209 + cid`; `fighter+0x230` (= fighter slot) explains `0xCA6..0xCA8`.

### M9. Effects / HUD banks — mostly closed; one match-time UNKNOWN.
* HUD `0xC90..0xC98` and effects `0xC50..0xC68` rip byte-exact from AFS 835/836 and 799/800 (`TEXTURE-BANKS-GHIDRA.md`
  §5). The `mvc-hud-list0b-live-re` memory's "UI bank live-dump only" is superseded. Open: "case 0x18 rebases the
  effects TEX to 0x0CDA0000 — who copies pixels there and whether it runs in a match: UNKNOWN" (§8.1).
* Task: callers of `FUN_14060c370` case 0x18. Gate: every effects page bound in a full-match capture matches the
  arc rip (today 9/9 distinct captured pages).

### M10. Harvest limits in the agent (not Ghidra; gates only).
* `ANODES_CAP_PER_FRAME = 96` (`reader.rs:1400`) against 77 HUD nodes on one frame plus hail/effects; `AOBJ_MAX_RECS = 8`,
  `AOBJ_MAX_BYTES = 4096` (`reader.rs:1398-1399`) truncate any polygon-list object with more than 8 records;
  `harvest_anodes` reads `0x180` bytes per node so `+0x1B8` and beyond are invisible. Gate: `tape_audit.py` counts of
  capped frames and truncated objects on the 0.3.39/0.3.40 tapes (must be 0).

### M11. `node+0x150`.
* `EMU-GATE.md` gates it as a walker output on every frame; `TAPE-V3-SPEC.md` §10.1 does not list it; the tape does
  not carry it. UNKNOWN meaning. Task: find its reader in `FUN_1406129f0` / the entry build. Gate: if read → add
  the field; if unread → drop it from the gate list.

### M12. The sampling phase of the AGENT (the biggest unknown for "tape == capture").
* Every 100% sprite gate used the SHIM's post-walk dumps (`"at":"walk"`, N↔N). The agent samples at the clock edge
  (`rr-tape-v4-agent`). Whether that lands before or after `FUN_140620f10` (and before/after the list-12 callback
  pass that rewrites `+0x50.x` and `+0x228`) is a live measurement nobody has made (`PARTS-LIST0C-GHIDRA.md` §5).
* Gate (no Ghidra): run agent + shim on one session; per frame number, diff the agent's node fields
  (`fsx/fsy/depth/angle/hotx/hoty/face/zx/zy`) against the shim's walker dump. Constant one-frame lag = the edge
  lands before the walk; then the emitter must use frame N+1's fields or the reader must move its sample.

### M13. Scripted camera (RE-C5) — no Ghidra needed for rendering.
* Keyframes are exe-static (`PTR_DAT_140a6e460/488/438`, `WORLD-CAMERA-GHIDRA.md` line 197) and the rows already
  carry the RESULT (`look/fov/yoff/roll` when `cam_state == 1`). The renderer is closed-form from the rows; Ghidra is
  needed only if v6 wants to drop those rows in favour of `(script id blk+0x6910, phase 0x690f, frame)`.

### M14. Stencil — closed by construction for the scene pass, UNKNOWN for the post chain.
* Every Z-write draw: `StencilEnable 1, func ALWAYS, pass REPLACE, ref 0, read mask 0, write mask 255`; the preamble
  quad (i) does the same over the full screen; every other draw has stencil off. The stencil buffer is therefore 0
  everywhere after every frame and no scene fragment can depend on it. Whether the post chain's own draws read or
  write stencil is UNKNOWN (they are not in any pack) — part of M1.

---

## 3. Minimum per-frame state per draw class vs the agent schema

Checked against `reader.rs` at `d9187dc` (0.3.40) with the 0.3.39 rows (`GS_SCHEMA`, `reader.rs:1200`), `nodes`
(stride 54, `:1906`, `:2590`), `anodes` (stride 100, `:1393`, `:2588`), `aobjs` (`:2589`), `pals` (`:2642`), `palrows`
(0.3.40, `:2632`).

| Draw class (Steam kind / consumer) | Minimum per-frame inputs | In the tape | Redundant | Missing |
|---|---|---|---|---|
| **Sprites** (kind 0xC, `FUN_1408458b0`; pp_Palette R8 tiles and the direct-RGBA 32x32 sprite tiles) | list order; `sid`; `fsx/fsy` (+0x124/8); `depth` (+0x12C); `zx/zy`; `angle`; `hotx/hoty`; `face`; `drawn`; `layer/sort/cat`; `gfx1/gfx2` (asset key); `slot/owner`; palette **row per part** (bank = slot base + `rec.flags>>4`); LayerZ table (constant) | `nodes` ✓; `palrows` + `pals` ✓ (0.3.40) | `pal` (DatPal+0, wrong); `blend` (M3: Steam constant 0x45); `objs` (v2 32-B wire, superseded by `nodes`); `flash/glow` for rendering (the flash rows are in `palrows`; keep for receipts); rows `sx/sy/zx/zy/sid/layer/drawn/atimer[6]` duplicate the fighters' `nodes` records (kind 0) | per-record filter bit (entry flag bit 12 — INFERRED constant point; M3); `+0x150` (M11); phase guarantee (M12) |
| **World polygon-list nodes** (kinds 0-3, lists 5-8 quads, 0xB/0xD HUD) | `list`; `flags` +0xF0; matrix +0xA8; colour +0x94; alpha +0x90; object = {TCW, shape hash, UV cell, record colour floats, TSP} (v6) or interned bytes (v5); per-group cull word; `last_cull` (derivable from order) | `anodes` ✓ (100 B); `aobjs` ✓ | matrix for camera-static list-5 props (RE-A1, derivable); 64 B/node/frame is the size lever, correctly identified | none per node; but the object cap (M10) and the 12 bit-6 strips (M4) |
| **3D models** (list 8 / list 5 with `+0xE8`) | model identity + matrix | `anodes.model` = **host pointer** (u64) | — | a **stable model key** (index into `PTR_DAT_142edf588` / bank + model index); the pointer is ASLR/heap-relative and is only resolvable by the emitter's join today. RE-A1 should produce it. |
| **Deck** (direct draw, `FUN_140849c10(model0)`) | stage id; identity W; `deck[3]` (0x6CA8..); `blackout` (0x3D50); render mode `blk+0x6CE4` (INFERRED constant 0) | rows ✓ (`stage_id`, `deck`, `blackout`) | — | `0x6CE4` only if it ever changes in a match (gate it) |
| **Frame preamble** (`FUN_140843eb0` quad + 1x1 quad + depth-only quad) | background colour = f(`0x6CB4`, `0x6CB8..0x6CC2`, `0x6CA8..`, `0x6CF0`); the 1x1 page colour | nothing | — | **20 B of rows** (M2) + the 1x1 page's origin (UNKNOWN) |
| **Combo counter / round text** (list 0xC, `FUN_140653a70`) | `pnodes` 44 B: slot, drawn, state, list1/list2 RVA, pos, x2, 16 digits | **nothing** (harvest filter drops them) | — | the whole record (`PARTS-LIST0C-GHIDRA.md` §5 diff) |
| **Camera** (`FUN_14061d7e0/6a0/5b0`) | eye (0x6914..), target (0x695C..), fov (0x6974), y-off (0x6988), roll (0x698C), `cam_state` (0x6908); near `ctx+0x1f82b0` = 1.0 (constant) | rows ✓ (0.3.39) | `ground` (not a render input); `zoom` duplicates eye.z | none |
| **Palette** | 48 staged rows + flags per frame; LUT refresh rule | `palrows` ✓ | `pal` | the lag rule (M7) if pixel-exactness on flash frames is required |
| **Post chain** | none per frame (constants + config) | n/a | — | the chain itself (M1) |
| **Receipt-only rows** (`hp/px/py/vx/vy/red_hp/hitstun/act/combo/meter/timer/round_no/seat_in/kcode`) | not render inputs | ✓ | keep for the receipt; the renderer ignores them | — |

Wire consequences for §3 (Workstream A): drop `objs`, `pal`, `blend`, the six per-fighter duplicate columns; add
`pnodes` (44 B × ≤8), the 20 background bytes, a stable model key; keep `palrows`. The draft's "< 1 MB per match"
target is unaffected by the additions (a few hundred bytes per frame at most).

---

## 4. Risks for a WebGPU port of the replayer, with the capture facts behind each

| Area | Capture fact (600 frames unless stated) | WebGPU consequence / risk |
|---|---|---|
| RT / depth formats | scene RT fmt 87 (`B8G8R8A8_UNORM`) 2048x1024, viewport `(384,32,1280,960)`; DSV fmt 44 (`R24G8_TYPELESS` → `D24_UNORM_S8_UINT`); no `_SRGB` anywhere; backbuffer fmt 28 1280x768 | `bgra8unorm` + `depth24plus-stencil8`, both core. A stencil-bearing format requires `stencilLoadOp/StoreOp` on the pass even if unused (`state.mjs` `toDepthStencil` note). Keep the canvas out of the compare path (`getPreferredCanvasFormat` may be sRGB-ish on some browsers). 8 MB colour + 8 MB depth per RT on a phone: acceptable, but the post chain (M1) adds two 1280x768 and one 640x384 intermediates. |
| Blend states | exactly 3: `(SRC_ALPHA, INV_SRC_ALPHA)`, `(SRC_ALPHA, ONE)`, disabled; alpha channel always `(ONE, ZERO)`; `AlphaToCoverage 0`; write mask 15 except the depth-only preamble draw (0); no `BLEND_FACTOR` | All core. **Destination alpha is REPLACED**, and `verify_alpha.py`'s coverage gate depends on it — keep the alpha blend exactly `(one, zero)`. A `colorWriteMask 0` pipeline is needed for the depth-only quad. Any preset outside the three (M5) will THROW in `state.mjs` by design — keep that behaviour in the port. |
| Depth | `LESS_EQUAL` (scene) and `ALWAYS` (preamble) only; forward z; depth reset by a full-screen ALWAYS+write quad, not `ClearDSV`; `DepthBias 0`, `DepthClip 1` everywhere; sprites carry per-quad z from `FUN_1408432e0(D)` (~0.98 band, 1.79e-7 steps) | Two compare functions. **Do not clear depth to 1.0 and skip the quads** unless the background colour is reproduced (M2). The 1.79e-7 z steps live inside `depth24plus` precision at z ≈ 0.98 (24-bit ulp ≈ 6e-8) — but only just; `depth32float` would be safer for the sprite band and is equally core. Never `reverse-z` (`pvr2-renderer.mjs` trap). |
| Stencil | Z-write draws: enabled, `ALWAYS/REPLACE`, ref 0, read mask 0, write mask 255; others off | Reproduce verbatim (cheap) or omit (proven no effect in the scene pass, M14). Post chain: UNKNOWN. |
| Cull / winding | cull NONE / FRONT / BACK all used; `FrontCounterClockwise = 1` on every `vs_world` state and **0 on the preamble states** | `frontFace` is per pipeline and must be part of the key (it is in `pipelineKey`, `state.mjs`). The measured "0 px either winding" fact is a diagnostic, not a licence to hard-code. |
| Rasterizer flags | `MultisampleEnable 1` on the `vs_world` states, `0` on flat; `AntialiasedLine 0`; scissor never enabled; RT `SampleDesc 1` | D3D11's `MultisampleEnable` on a non-MSAA target only changes line rasterisation; no triangle effect. Nothing to port. Keep `sampleCount 1`. |
| Samplers | 4 distinct: `{point, linear} × {clamp, wrap}`; `ComparisonFunc = 1 (NEVER)` in the desc but no comparison filter bit; `MaxLOD = FLT_MAX`; `MipLODBias 0`; every texture `mips 1`; **one BORDER sampler, post chain only** | Do not set `compare` (turns the binding into a comparison sampler). Clamp `lodMaxClamp` to a finite value. Mirror modes (TSP flips) never seen — `mirror-repeat` exists in WebGPU if they appear. BORDER has no WebGPU equivalent → the post pass needs a shader clamp+select. |
| Texture formats / counts | fmt 28 (`rgba8unorm`) and 61 (`r8unorm`) only; 55-339 distinct textures bound per frame, dominated by 32x32 R8 tiles (~115/frame) and 256x1 palettes (~5/frame); largest 256x256 | The tape path binds atlases + 48 palette rows instead, far fewer objects. R8 tiles/atlases MUST be uploaded via `writeTexture`, `mipLevelCount 1` (a generated mip averages palette INDICES). Per-draw bind groups ~840/frame: use dynamic uniform offsets (already the `sprite.wgsl` design: 4 CBs in one 256-B-aligned block). Limits (`maxSampledTexturesPerShaderStage ≥ 16`, `maxTextureDimension2D ≥ 8192`) are not approached. |
| Index / vertex limits | game draws are non-indexed strips/lists (the packer converts strips → lists; `TSP-RENDER-STATE-GHIDRA.md` §5: Steam expands strips on the CPU and draws triangle LISTS); ~840 draws × ≤ 6 verts per frame; sequence VB 178 KB/frame; strides 40 (`vs_world`/sprites) and 28 (flat quads: `POSITION float4 + NORMAL float3`, il `2b125802…`) | 16-bit indices are ample **per frame** (< 65k verts) but not across a merged buffer (the 300-frame pool sits at a 38 MB offset) — allocate per frame or use `uint32`. Two vertex layouts → two pipeline families; the 40-B layout's `NORMAL float2` at +16 is uninitialised NaN and must be absent from the layout. Vertex-buffer offsets are BYTES (trap 1). |
| Shaders / interpolation | 4 PS families = flycast DX11 macro tuples (`ShadInstr 3`, `IgnoreTexA`, fog, `Palette`); DXBC `linear` = perspective-correct; alpha test `ge fAlphaRef(0), a → discard` in every PS | WGSL default interpolation is right; `@interpolate(linear)` would be WRONG. Keep the `discard` on `a <= 0`: it decides depth AND alpha writes for Z-write draws. Fog: `fFogDensity 0` in every frame measured — keep the term (bit-exact no-op), it is config-conditional. |
| Vertex-shader pairing | `vs_flat` (positions already NDC, no CBs) pairs with the palette PS and the HUD PS; `vs_world` with the stage PSs; IgnoreTexA PS appears on both VSs | Fragment/vertex varying signatures must match per pairing (`sprite.wgsl` `fs_flat_opaque`); pipeline key must include the VS variant. |
| Output geometry | scene 1280x960 inside a 2048x1024 RT, presented at 1280x768 (a 0.8 vertical resample inside the post chain) | Without M1 the browser shows 1280x960 4:3 pixels that are NOT what Steam shows on screen. Decide the target (pre-bloom RT vs backbuffer) explicitly. |
| Frame independence | colour/depth/stencil fully rewritten each frame by the preamble draws | Seeking to an arbitrary frame needs no history — provided M2's background colour is reproduced. |

---

## 5. Corrected §9 order of work

Draft: `A1 → B1–B3 → B4–B5 → B6–B7 → D1 → E2 → A2–A3 → C-items`.

Proposed (gates first, oracle before ports, decisions before release):

0. **G0 — tape == capture phase gate (M12).** One session, agent + shim together; per-frame diff of the agent's
   node fields against the shim's walker dump. Every 100% gate so far is shim-vs-capture; none is tape-vs-capture.
   Cheapest possible test of the whole premise of the workstream.
1. **Oracle hygiene (Python `tape_to_seq.py`, before any port):** preamble quads with the M2 colour rule; consume
   `palrows`; `pnodes` (needs the agent change — A4 below); re-run `tsp_gate` (824/824 with `+0x90`) and
   `sort_gate` (3/3) on a 0.3.39+ tape; kind-0xC law (M3). Only then is "byte-equal draw lists vs Python" a gate
   worth building the Rust emitter against.
2. **A4 (agent, small):** `pnodes`; background words `blk+0x6CB4/0x6CB8..0x6CC2/0x6CF0`; stable model key; drop
   `objs`/`pal`/`blend`/duplicate columns. Then **A1** (keys) as drafted, gated on 1.
3. **M5-A instrument** (state-object creation hook + executor table join) before B3 freezes the `HOST` table —
   one launch converts every INFERRED D3D column to CONFIRMED.
4. **B1–B7** as drafted, with M3 (sprite law) and M2 (preamble) in B3/B6.
5. **M1 decision (Tris):** pre-bloom scene RT as the product, or port the post chain. E3's release gate must name
   which. If the chain is ported: extend `pack_replay.py` to keep post-RT draws, classify their shaders, gate vs
   `shot_*.bmp`.
6. **D1, E2** as drafted.
7. **C-items, re-scoped:** C1 → "LUT lag rule + drop `pal`" (source question closed by `PALETTE-SOURCE-GHIDRA.md`);
   C2 → "synchronous capture for 4505-class frames" (not a model fix); C4 (portraits) as is, with the `fighter+0x1f8`
   writer as the one Ghidra read; C3 (hit sparks); C5 (scripted camera: closed-form from rows, no Ghidra);
   C6 last. Add M4 (bit-6 strips), M9 (effects case 0x18), M11 (`+0x150`).
8. **A2–A3 (size)** last, as drafted — the tape is already 40-80x under the draw stream (`rr-pathb-steam-capture`
   delivery table); size is not the risk.

---

## 6. Answers to §10 (the parts in this lane)

* **§10.2 memory:** the 145 MB / 300-frame figure is the capture `.seq` model (per-frame VBs + 55-339 textures per
  frame). The tape path has none of that; the budget is atlases + 2 RTs + intermediates (~40 MB on a phone with M1).
* **§10.3 palette LUT per draw:** per (slot, row) bank texture, refreshed when the staging flag fires (`palrows`
  carries both); not per node, not per slot (M7).
* **§10.4:** the `.seq` replayer's state tables (`state.mjs`) should be kept as the translation layer precisely
  because they throw on anything outside the measured set — a silent substitution is the failure mode Path B paid
  for twice.

## 7. Address index for this review (Ghidra reads made today, all CONFIRMED by decompile unless marked)

`FUN_1408436a0` queue append (kind switch; case 0xC sprite key/cat; slot `+0x1a = ctx+0x1f8274`) ·
`FUN_1408458b0` sprite consumer (no blend cmd; `FUN_140844320(flags>>12&1, 1)`; flags bits 0-5/11/17; rotation) ·
`FUN_140843eb0` frame flush (background quad, texId 0xffff, colour `ctx+0x1f8248..50 | 0xff000000`) ·
`FUN_1408450e0` / `FUN_1408450a0` background-colour setters (sole writers of `ctx+0x1f8248..50`) ·
`FUN_1406101b0` match-time background rule (`blk+0x6CB4`, `0x6CB8/BC/C0`, `0x6CA8..B0`, `0x6CF0`) ·
`0x140844ad8` the only writer of `ctx+0x1f8274` (= 0x45) ·
`FUN_1406162e0` / `FUN_140616330` portrait re-uploads (slots 0xC99, 0xCA6+) ·
caller `0x140611cb8` (`caseD_0`, function unresolved by the bridge — UNKNOWN which menu routine).
