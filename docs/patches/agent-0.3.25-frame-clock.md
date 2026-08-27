# agent 0.3.25 — the frame clock

**Status 2026-08-27: VERIFIED, NOT LANDED.** The diff beside this file (`agent-0.3.25-frame-clock.diff`)
was generated mechanically (`diff -u` against the real file, not hand-written) and **compile-checked
clean** — `cargo check` on a staged copy of the crate, exit 0, no new warnings. It is not applied
because the session that wrote it was worktree-locked to `mvc-live-skins-quarters` and cannot write
to the agent repo.

## Apply

```
git -C "C:\Users\trist\projects\RetroReceipts-agent" apply "C:\Users\trist\projects\mvc-live-skins-quarters\docs\patches\agent-0.3.25-frame-clock.diff"
```

Then confirm it still builds:

```
cargo check --manifest-path "C:\Users\trist\projects\RetroReceipts-agent\agent\Cargo.toml"
```

## What it fixes

The battle capture loop located its frame counter with `hunt_frame_counter` — a ±8 MB heuristic scan
for "a u32 that ticks monotonically" — instead of `blk + BLK_FRAME_OFF` (`0x3CC8`), a constant already
declared at `reader.rs:128` and already used correctly by the anchor, by `gs_record_select`, and by
`start_sim_frame` **in the same file**.

**The scan could never select the right answer.** It rejects any candidate that ever *decreases*:

```rust
if delta < 0 || delta > 6 { continue 'off; }
```

`blk+0x3CC8` mirrors GGPO's `_framecount`, which `Sync::LoadFrame` assigns **backward** on every
rollback (bounded by `MAX_PREDICTION_FRAMES = 8`). We measured deltas of `-1/-3/-4` in `select_in`,
which reads that exact address. So the one always-correct address is the one the filter is guaranteed
to discard — and the bias grows with rollback rate, meaning it fails hardest on precisely the laggy
matches most worth keeping.

Measured across 10,812 capture pairs in one trace log, same machine, same build:

| counter used | captures | rows/sec |
|---|---|---|
| `blk+0x3cc8` (correct) | 37 | **60.03 – 60.45** |
| `blk+0x4db0` | 1 | 5.29 |
| `blk+0x3c8c` | 1 | 0.51 |

`blk+0x4db0` = `blk + 0x3DB8 + 2*0x738 + 0x188` — **slot 2's `H_SPRITE_ID`**. Two live ranked matches
and a full FT3 were clocked off a benched character's animation, retaining 0.84% and 8.8% of frames.

⚠ **This is not a 0.3.24 regression.** `hunt_frame_counter` is legacy (its own comment references a
v0.1.10 fix). It is latent and connection-dependent: the hunt samples 12 times over ~264 ms at match
load, so on a clean connection no rollback lands in the window, the real counter looks monotonic, and
it gets picked. Do not bisect for it.

⚠ **`frame_gaps` cannot detect this.** It is computed as `span - count`, so any wrong word that
happens to step by 1 reports `frame_gaps: 0` and looks perfect. The detector is the clock check in
`replay-kit/tapev2_validate.py` (rule 6): frames per wall-clock second must be ~60.

## Also in the diff

- **`hunt_frame_counter` deleted**, with a tombstone comment where it lived. Besides being wrong it
  re-ran every ~3.3 s indefinitely, reading up to 192 MB per attempt, while sitting at menus.
- **Rollback delta.** `rollbacks` shipped the *cumulative-since-launch* `G+0x76C` read, because the
  field was zeroed at match start and then overwritten with the raw value at END — no baseline was
  ever subtracted. It made one 851-frame capture appear to have ~2 rollbacks per frame. Now baselined
  at START (`rb0`) and subtracted at END.
- **Break reason logged.** Five distinct exits (`frozen-base`, `team-wiped`, `counter-stalled`,
  `array-invalid`, `share-off`) were indistinguishable in the log; diagnosing one bad capture took an
  hour of forensics. `recording END` now carries `why=` and `rollbacks=`.

## Not fixed here

The tape upload is gated on a server-returned `match_key`, and in a **hosted-node (arcade) lobby** the
agent reports the *host bot* as its opponent — so the pair never resolves, no usable key comes back,
and the tape is dropped. That is a separate defect with its own consequence: wagers do not auto-settle
and must be settled by hand through `POST /skinsync/arcade/host/report`. See the arcade lane.
