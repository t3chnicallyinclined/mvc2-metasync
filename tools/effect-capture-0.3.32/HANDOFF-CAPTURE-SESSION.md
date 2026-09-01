# HANDOFF — maplecast-flycast live-capture session (Path-A → 99%)

**You are a fresh Claude session started in `C:\Users\trist\projects\maplecast-flycast` (NON-isolated).**
Your job is TWO read-only live captures that this project's fenced worktree (`mvc-live-skins-quarters`)
cannot run. The tape render is Path A: a real Steam match STATE (tape) rendered on our own WebGPU using
extracted game assets. Two asset gaps remain, both provable dead-ends offline, both fixable only with a
live DC/flycast capture (same game code → identical pixels).

## FIRST — load context (do this before touching anything)
1. Read `C:\Users\trist\projects\mvc-live-skins-quarters\docs\RENDER-ACCURACY-PROGRAM.md` — the SSOT
   decision log. Focus on the **2026-08-31 / 2026-09-01** entries (HUD top-band-only capture; effect-cell
   offline dead-end; the Path-A ceiling).
2. Read the sibling runbooks in this folder: `bakes-RUNBOOK.md` (cell-bake mechanics — authoritative),
   `BUILD-RUNBOOK.md`, `README.md`.
3. Your MEMORY.md already carries the relevant findings: `mvc-render-composite-model`,
   `mvc-hud-list0b-live-re`, `rr-sprite-render-pipeline`, `mvc2-dc-steam-block-map`. Consult the
   `mvc2-sprite-render-expert` / `mvc2-sh4-re-expert` agents for any RE detail — never guess.

## THE TAPE / ROSTER (match 59607511, the one the user is judging)
`p1=[52,42,6]  p2=[42,44,50]  costume=[3,1,5,1,5,1]`. Super-casters with garbled effect cells on THIS tape
(offline-decode counts, per the render-side gate `scratchpad/gate_effect_cells.py` in the worktree):

| char id | PL | cells needing bake |
|---|---|---|
| 42 Storm | PL2A | **217** (near-total — capture all her effect poses) |
| 44 Magneto | PL2C | **65** |
| 52 Sentinel | PL34 | **25** |
| 6 Colossus | PL06 | 4 (sels 0x50–0x53) |

## CAPTURE A — full-band HUD (fixes the timer badge / LEVEL gauges / labels / name plates)
WHY: the deployed `web/tapecanvas/hud/hud_quads.json` is a **top-band-only** TA snapshot (y 44–112). The
∞/TIME badge, bottom LEVEL/hyper gauges, decorative labels, and per-tape name sprites are drawn in the same
pvr2 HUD pass but were NOT in that snapshot; their pixels are behind the LZSS scratch wall so they can't be
built offline. FIX: a **full-band (BAND_H=480)** HUD TA capture mid-match.
- Tool: `tools/render-replica-poc/hudq_capture.mjs` (+ `render_hudq.mjs`); prior top-band dumps under
  `tools/render-replica-poc/_hud_cap_def` are the template. Confirm the exact invocation from those tools.
- IN-MATCH conditions the capture needs on screen (ask the user to drive): a **running countdown timer**,
  a **built super meter** (LEVEL ≥1), and an **active combo**. (∞ badge only appears in TRAINING — this tape
  is ranked, so TIME is a countdown; if the user also wants the training ∞ badge, do a second capture in
  training.)
- OUTPUT → overwrite `C:\Users\trist\projects\mvc-live-skins-quarters\web\tapecanvas\hud\hud_quads.json`
  (full-band) plus any new sprite/vram/pal the full band needs. Then bump the `?v=` in
  `web/tapecanvas/renderer/hud-client.mjs` load so the browser drops the cached top-band file.

## CAPTURE B — per-char effect-cell PARTDUMP bakes (fixes the garbled Storm/Magneto/Sentinel/Colossus supers)
Follow `bakes-RUNBOOK.md` exactly. Summary:
- `MAPLECAST_PARTDUMP=128 build-headless/flycast <rom>`; user throws **every** super/effect of 42/44/52/6,
  varying poses so all garbled cells above get captured (PARTDUMP only sees the current frame's parts).
- `python3 tools/rip_gfx2_assembly.py --char PL2A --gfx1 …PL2A_DAT…GFX_DATA_00.BIN --gfx2 …_01.BIN
  --pal …PALETTE_DATA.BIN --realparts /dev/shm --out web/test-atlas/chars` — repeat for PL2C, PL34, PL06.
- OUTPUT lands in `maplecast-flycast/web/test-atlas/chars/PL{2A,2C,34,06}_parts.png` + `_asm.json` +
  `_parts.json` — the SAME dir the tape render reads (`ATLAS_DIR` in the worktree harnesses). ROM-derived →
  scp-only, NEVER commit.

## VERIFY (the sign-off — deterministic, not eyeballing)
- Cells: the DIFF v7 tint gate in `maplecast-flycast/web/webgpu-test.html` on a frozen super frame
  (`bakes-RUNBOOK.md` "Pixel gate"). Real pixels ⇒ tint collapses to near-zero delta vs the live decode.
- HUD: re-render the worktree composite `web/tapecanvas/_verify_hud_composite.mjs` at a mid-match row and
  confirm the timer badge + LEVEL gauges + real name text now appear at their captured positions.
- The USER (Tris) is the final judge of the browser render — hand him the play_state URL to confirm.

## WHEN DONE
Append a dated result entry to `docs/RENDER-ACCURACY-PROGRAM.md` (what captured, what rendered, what
remains). The reader-side work (0.3.33 confirmed-capture + the 68 ownerless effects) is a SEPARATE
`RetroReceipts-agent` session — not this one.
