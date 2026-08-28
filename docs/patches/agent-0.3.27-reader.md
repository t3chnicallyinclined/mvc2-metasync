# agent 0.3.24 → 0.3.27 — the COMPLETE tape train (VERIFIED, must land before any release)

⚠ **The real `RetroReceipts-agent` repo is at 0.3.24 and has NONE of the tape work.** A release cut
without this diff ships a tape with **no render columns, no confirmed inputs, and no effects** — i.e. it
undoes everything. `agent-0.3.27-reader.diff` is the full `agent/src/reader.rs` change 0.3.24 → 0.3.27,
generated mechanically (`diff -u`), **verified to apply cleanly and reproduce the staged 0.3.27 reader
byte-for-byte** (`patch` + `diff -q`, 2026-08-28). Built + `cargo check` clean; live-recorded (tape
59596263, effects column 9,789 nodes verified on the server).

## Apply
```
git -C "C:\Users\trist\projects\RetroReceipts-agent" apply "C:\Users\trist\projects\mvc-live-skins-quarters\docs\patches\agent-0.3.27-reader.diff"
```
(or `patch agent/src/reader.rs < ...agent-0.3.27-reader.diff`). Then bump the crate version:
```
# RetroReceipts-agent/agent/Cargo.toml: version = "0.3.24" -> "0.3.27"
```
with a changelog note: `0.3.27 = render columns (sx/sy/zx/zy) + stage_id + confirmed_in (GGPO confirmed
input ring) + objs (object-pool effects via the draw list). All APPENDED — positional consumers unaffected.`
Then `cargo build --release`.

## What it contains (all APPEND-ONLY — old consumers unaffected)
1. **0.3.25 frame-clock fix** — battle loop uses `blk+0x3CC8`, deletes `hunt_frame_counter`.
2. **Render columns** — `sx[6],sy[6],zx[6],zy[6]` = the engine's own screen coords (`H+0x124/128`) +
   per-object render scale (`H+0x130/134`). Removes world→screen reconstruction.
3. **`stage_id`** (envelope) — `blk+0x6D3C`.
4. **`confirmed_in`** — GGPO's CONFIRMED per-frame inputs from the InputQueue ring (pure-forward .flyr stream).
5. **`objs`** (0.3.27) — per-frame OBJECT POOL (projectiles/assists/supers/hit-sparks) via the engine draw
   list (`blk+0x2f4d0`), read through the fighter H-offsets, active-only, in layer order.

## Completeness status (per docs/TAPE-CAPTURE-MANIFEST.md)
- **0.3.27 is the verified-complete tape for character + effects rendering.** Big improvement over 0.3.24.
- **0.3.28 (in progress, NOT in this diff):** confirmed-position capture (the shake fix), costume/palette
  (`H+0x6C1`), hit-flash (`H+0x172`), per-fighter layer, effect binding-key (`node+0x15C`+dirBase — one
  offset still pending sh4-re confirmation). Those add columns → a SECOND migration if shipped separately.
- **Decision for the release:** ship 0.3.27 now (character + effects tape) and fast-follow 0.3.28, OR hold
  the release for 0.3.28 = one FINAL migration. Do NOT ship 0.3.24.
