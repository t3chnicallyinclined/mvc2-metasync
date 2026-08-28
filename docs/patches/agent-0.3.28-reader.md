# agent 0.3.24 → 0.3.28 — the FINAL COMPLETE tape (the ONE migration for the release)

**This is the diff the held release should ship** (option B: one final migration). `agent-0.3.28-reader.diff`
is the full `agent/src/reader.rs` change 0.3.24 → 0.3.28, **verified to apply cleanly and reproduce the staged
0.3.28 reader byte-for-byte** (`patch` + `diff -q`, 2026-08-28). `cargo check` clean; supersedes the 0.3.27 diff.

## Apply
```
git -C "C:\Users\trist\projects\RetroReceipts-agent" apply "C:\Users\trist\projects\mvc-live-skins-quarters\docs\patches\agent-0.3.28-reader.diff"
```
Then `RetroReceipts-agent/agent/Cargo.toml`: `version = "0.3.24" -> "0.3.28"` (changelog note in the staged
Cargo.toml). Then `cargo build --release`.

**Base branch:** the diff base is `replay-capture-0.3.24` (2026-08-27, the tape lane's branch — it carries
`seat_in`/`anchor`/`select_in`/`gs_record_select` as context). **0.3.28 is a strict SUPERSET of 0.3.24**,
built on it. Apply on the tape/replay lane's branch, NOT on `origin/main` (which is 0.3.23, tape-work-unmerged
— cutting a release from main is what would ship an empty tape).

⚠ **Headers are repo-relative (`a/`,`b/`)** — regenerated 2026-08-28 after projects-45 caught that the first
artifact had absolute scratchpad paths and `git apply` failed with "No such file or directory". `git apply`
(default `-p1`) now applies clean.

⚠ **Run `cargo test`, not just `cargo check`.** `check` never builds the test cfg. `GsRow` gained 8 fields
(`sx/sy/zx/zy`, `flash/glow/layer/timer`); a stats-test row constructor must be kept EXHAUSTIVE or `cargo test`
fails E0063. projects-45 fixed the constructor on `try-0.3.28`; both check + test are clean there.

⚠ **NO LIVE VALIDATION yet.** 0.3.28 adds ~323 insertions of new columns. Gate before merge/ship:
`replay-kit/TAPECHECK.cmd` + one match, coverage must read ~100% (that number is what proves the
frame-counter/confirmed-position work).

## What it contains (all APPEND-ONLY — old positional consumers unaffected)
Everything in 0.3.27 (render columns + stage_id + confirmed_in + objs/effects) PLUS the reconciled-audit
completeness set (`docs/TAPE-CAPTURE-MANIFEST.md`, "0.3.28 FINAL"):
1. **Confirmed-position re-read** — rollback tight re-read (bounded/guarded) → reduces the GGPO-prediction
   shake. ⚠ Best-effort by design: an external poller can't catch a re-sim burst that completes between
   polls; pixel-exact positions need confirmed-input re-simulation. The visible shake is also softened by the
   renderer's EMA (king.html path).
2. **Per-fighter columns** (frames schema): `flash[6]` (H+0x172 hit-flash), `glow[6]` (H+0x5C char_pal_effect
   super-glow), `layer[6]` (draw-list layer), `timer` (round timer).
3. **Costume** (envelope): `costume[6]` (H+0x6C1, static per match).
4. **Object-pool additions** (`objs` record): `gfx` (low32 of H+0x1A8 = effect-atlas binding key — the real
   effect-texture selector; sid is NOT it) + `owner` now resolved by scanning H+0x9C/H+0xC4 vs the fighter
   bases + `cat` drives blend client-side.

## Still OPEN (capture-now / resolve-later — NO further re-record needed)
- Effect texture INDEX from `gfx` (needs a Ghidra pass on the Steam effect loader OR a one-time directory
  probe; effects render OFF until then). The binding pointer is now captured.
- Owner offset (self-resolves via the H+0x9C/H+0xC4 scan already shipped).
- Confirmed-position residual (a live probe certifies "exact"; the shake reduction ships regardless).

## Size
~+10% over 0.3.27 (low-entropy additions) — ~120 B/frame gz, ~0.8 MB/match, **~8 MB / 10 matches** gz.
