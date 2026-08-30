# agent-0.3.29-reader — EFFECTS/SATELLITES capture fix + self-describing tape

**Base lineage:** staged 0.3.28 reader (`try-0.3.28/replay-capture`). The `.diff` is a single reader.rs
unified diff, LF-normalized. Apply from the agent project root:

```
git apply --ignore-whitespace docs/patches/agent-0.3.29-reader.diff
#   or:  patch -p1 --ignore-whitespace < docs/patches/agent-0.3.29-reader.diff
```

Round-trip verified: applying the diff to a fresh 0.3.28 base reproduces the built reader **byte-identical**
(LF). `cargo test` on the result is **green** (see below).

Two changes are applied directly (not in the `.diff`, both trivial):
- `Cargo.toml`: `version 0.3.28 → 0.3.29` + a 0.3.29 changelog note.
- Python consumers (below).

---

## What this fixes (Phase-2 verdict)

Whole-tape scan of 0.3.28 `objs`: **0/23742** nodes resolved into the effect bank, **owner=255** on every
node, **scale a constant 426.625**. Three node offsets were wrong. `fxprobe.py` (2 live runs: Storm
projectile + triple super) RE'd the fix. Root cause: the render cluster maps **DC→Steam at a CONFIRMED +0x44
delta** (5 anchors already in the reader: screen 0xE0→0x124, screen_y 0xE4→0x128, drawgate 0x12C→0x170,
sid 0x144→0x188, hitflash 0x12E→0x172).

| field | 0.3.28 (wrong) | 0.3.29 (fixed) | status |
|---|---|---|---|
| owner | u64 @ H+0x9c / H+0xc4 (→ always 255) | **u64 @ H+0x28** == owning fighter H-base `blk+0x3DB8+i*0x738` | **CONFIRMED** live (48/52 & 40/40; misses = ownerless super-flash → 0xFF) |
| gfx | u64 @ H+0x1A8 (never resolved) | **gfx1 = u32 @ H+0x1A0 (Dat_GFX1)** + **gfx2 = u32 @ H+0x1A4 (Dat_GFX2)** | **CONFIRMED** (+0x44 delta; H+0x1A8 was δ0x4C = DC+0x164 = Dat_Pal, a palette handle — why it never resolved). Which handle the atlas keys on = render-expert's offline call; both shipped |
| scale | H+0x130/0x134 read back **÷16** | H+0x130/0x134, **encode ×4096 / decode ÷4096** | **CONFIRMED** the field was never wrong: 1.6667×4096=6826; 6826÷16=426.625 exactly. Decode ÷4096 → 1.6667 (the CpsX/CpsY magnifier) |

The `blk+0x6CE8` / `[0x0CED0000]` value-test is **dropped** — that model dir keys only **3D-class** effects
(cat 5-13, NaomiLib), none of which were captured. Sprite-class (cat 1-4) render like a body via the
`(GFX2, sel=sid)` part-assembly, so the bank handle + sid is the key. (`blk+0x6CE8` read `0x1` live — dead.)

---

## The 7 changes

1. **Effect offsets** — new consts `H_OBJ_OWNER=0x28`, `H_GFX1=0x1a0`, `H_GFX2=0x1a4`; deleted `H_OWNER_A/B`
   and `H_GFX1_PTR`. `harvest_objs`: owner = scan H+0x28 (u64) == a fighter H-base else 0xFF; ships
   `gfx1=le32(0x1a0)` + `gfx2=le32(0x1a4)`; per-node read grown `0x1b0 → 0x1C0`.
2. **Scale decode** — encode stays `×4096` (Rust `harvest_objs` + `extract_render.py qscale`); decode is now
   documented and numerically pinned to `÷4096`. `zx_q=6826 → ÷4096 = 1.6665` verified; `÷16 = 426.625`
   reproduces the bug value exactly.
3. **p2_meter_fill** — new `GsRow.p2_mfill = rpm_u16(base + MET_FILL + 2)`. Fixes the single-shared meter gap.
   (+~2 B/frame in the JSON frames array.)
4. **round_no** — new `GsRow.round_no = rpm_u8(base + OFF_ROUND)`. (+~1 B/frame.) Both APPENDED to `GS_SCHEMA`
   and the frame array — every existing positional column index is unchanged.
5. **Envelope tie-points** — `fighter_bases` (six `blk+0x3DB8+i*0x738` from `battle_blk`) + `ggpo_sim_tie`
   `{sim_frame = start_sim_frame (blk+0x3CC8), ggpo_frame = Sync::_last_confirmed_frame}` read at battle start
   (best-effort; `-1` if the GGPO session isn't up).
6. **objs CALIBRATION BLOB** — first `CALIB_MAX_FRAMES=16` effect-frames, each drawn node's raw prefix
   `H+0x00..0x1C0` (448 B; cat = prefix[0x03]). Self-describing insurance: gfx/scale/owner re-derive OFFLINE
   from any uploaded match, and survive a build shifting an offset. Collected on the normal capture path only
   (skipped on rollback re-reads).
7. **Version** → 0.3.29 (Cargo.toml) + changelog.

`objs` record grew **16 → 20 B** (gfx1+gfx2 replace the single gfx); `objs_enc` now says `gfx1(...)` so
consumers auto-detect the 20-B format.

---

## Guardrail: `cargo test` (verbatim)

```
   Compiling rr-agent v0.3.29 (...\scratchpad\agentcheck)
    Finished `test` profile [unoptimized + debuginfo] target(s) in 41.32s
     Running unittests src\main.rs (...\rr_agent-f08413206a299efd.exe)

running 4 tests
test reader::gs_stats_tests::attribution_sides_chip_ko ... ok
test tray::icon_tests::print_is_legible_weight ... ok
test reader::name_scrape_tests::interior_replacement_char_rejected_edges_trimmed ... ok
test tray::icon_tests::icon_is_full_bleed_at_every_size ... ok

test result: ok. 4 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s
```

The stats-test `row()` constructor was made exhaustive (it had been missing the 0.3.25/0.3.28 fields, which is
the E0063 trap the guardrail warned about) and now also carries `p2_mfill`/`round_no`.

## Numeric verification (obj record round-trip)

```
decoded node: [733, 118, 433, 6826, 0, 4, 0, 5, 6951, 17476]
zx_q=6826  ->  /4096=1.6665 (correct)   /16=426.625 (the bogus '426.625')
PASS: 20B record + gfx1/gfx2 + scale /4096 round-trip all verified
```

## Python consumers (touched)

- `replay-kit/tape_to_gpujson.py` — 20-B record with `gfx1,gfx2` (co-updated in parallel by the render expert;
  header comment aligned here). Passes `objs_enc`/`fxBankMap` through to the adapter.
- `scratchpad/proof/extract_render.py` — 20-B record parse (`<HhhHBBBBII`) + a scale round-trip self-check
  print (`zx_q → ÷4096`, warns that `÷16` is the bogus 426.625). Both compile clean.

The actual `÷16 → ÷4096` decode swap on the render side lives in `tape-adapter.mjs` (mvc2-sprite-render-expert);
the on-wire `zx_q` stays u16 ×4096 and is now documented as such everywhere it is produced.

---

## Per-match size delta (target ~2-4 KB gz)

- **calib blob** — ~**2 KB gz** measured for 16 effect-frames × ~6.5 nodes (42 KB raw; node prefixes are
  mostly-zero → compress ~20×). Dominant new term.
- **per-frame p2_meter_fill + round_no** — 3 B/frame raw as JSON ints; small repeated numbers gz ≈ 0.3-0.7 KB
  over a full match.
- **objs +4 B/node** (gfx1+gfx2) — sparse effect nodes, gz ≈ 0.1-0.3 KB.
- **envelope** (fighter_bases + ggpo_sim_tie + battle_blk) — ~150 B → ~0.1 KB gz.

**Total ≈ 2.5-3.5 KB gz/match** — within target. Tapes stay ≈52-54 KB. (Exact number pins on a real uploaded
0.3.29 tape; the calib blob varies with how many effect frames a match produces.)

## Falsification gate (do NOT declare a false win)

After 0.3.29, ≥1 effect node per super/projectile frame must resolve to a real key AND land within a few px of
the engine spark in the `SHOT_EVERY=1` frozen-frame diff. If it still resolves 0, the key premise is wrong →
escalate to static RE (marvelous2), not another live guess. (docs/OWNED-RENDER-BUILD-SPEC.md §"Falsification
test for 0.3.29 effects".)
