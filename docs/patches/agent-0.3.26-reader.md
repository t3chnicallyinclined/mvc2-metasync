# agent 0.3.24 → 0.3.26 — the full reader train (VERIFIED, NOT LANDED)

`agent-0.3.26-reader.diff` is the complete `agent/src/reader.rs` change from stock 0.3.24 to 0.3.26,
generated mechanically (`diff -u`) and **`cargo check` clean** on a staged crate copy. Not applied
because this session is worktree-locked out of `RetroReceipts-agent`.

## Apply
```
git -C "C:\Users\trist\projects\RetroReceipts-agent" apply "C:\Users\trist\projects\mvc-live-skins-quarters\docs\patches\agent-0.3.26-reader.diff"
```
Then bump the crate version and rebuild:
```
# in RetroReceipts-agent/agent/Cargo.toml: version = "0.3.24" -> "0.3.26"
cargo build --release --manifest-path "C:\Users\trist\projects\RetroReceipts-agent\agent\Cargo.toml"
```

## What it contains (four changes, all additive / append-only)
1. **0.3.25 clock fix** — battle loop uses `blk + BLK_FRAME_OFF` (0x3CC8), deletes `hunt_frame_counter`
   (which structurally could never select the real counter). + rollback DELTA (not lifetime) + break-reason
   logging. See `agent-0.3.25-frame-clock.md`.
2. **Render columns** — appended `sx[6],sy[6],zx[6],zy[6]`: the engine's OWN screen coords (`H+0x124/0x128`)
   + per-object scale (`H+0x130/0x134`), read from the existing object window (no extra RPM). Validated live
   (probe_render_cols.py: engine sx/sy == reconstruction to 0.23px median, and correct where reconstruction
   breaks). Removes all world→screen reconstruction on the consumer side.
3. **`stage_id`** (envelope) — `blk+0x6D3C`; the renderer pulls stage art from the Collection arc.
4. **`confirmed_in`** (0.3.26, envelope) — GGPO's CONFIRMED per-frame inputs harvested from the InputQueue
   ring (`*0x142E10B98 → Sync+0x9F0 → queues+0x190 → _inputs[f%128]`), gated on the confirmed watermark,
   write-once, keyed by GGPO frame. This is the pure-forward `.flyr` replay stream — proven bit-exact vs the
   Steam sim — whereas `seat_in` in `frames` is the PREDICTED latch (smeared under rollback). See
   `CONFIRMED-TAPE-AND-FLYR-REPLAY.md`.

## Why it matters
- (1) fixes a live defect gutting every laggy-match tape.
- (2)(3) complete the character-render tape (Path 1 browser renderer draws exactly, no reconstruction).
- (4) is the fix that unlocks the pixel-perfect flycast path (record confirmed inputs → convert to `.flyr`
  → dojo pure-forward replay), and independently fixes the "smeared opponent" in every tape.

All append-only → the fleet migrates ONCE; old consumers are unaffected.
