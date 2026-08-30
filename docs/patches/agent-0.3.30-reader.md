# agent-0.3.30-reader — 3D-CLASS effect capture (additive on 0.3.29, self-describing)

**Base lineage:** the 0.3.29 reader (`docs/patches/agent-0.3.29-reader.diff` applied to the staged 0.3.28
base). The `.diff` here is a single reader.rs unified diff, LF-normalized, **append-only on 0.3.29** — it
touches nothing 0.3.29 ships (the `objs`/`calib` sprite-class path is byte-for-byte unchanged). Apply from
the agent project root:

```
git apply --ignore-whitespace docs/patches/agent-0.3.30-reader.diff
#   or:  patch -p1 --ignore-whitespace < docs/patches/agent-0.3.30-reader.diff
```

One change is applied directly (not in the `.diff`, trivial): `Cargo.toml` `version 0.3.29 → 0.3.30` +
a 0.3.30 changelog note.

**Round-trip verified:** applying the `.diff` to a fresh 0.3.29 base reproduces the built 0.3.30 reader
**byte-identical** (LF-normalized). `cargo test` on the result is **green** (below).

> This is a **FUTURE additive capture**. It rides the held legacy-final tape, or gets trimmed if the oracle
> proves the 3D key out. It does **NOT** touch projects-3f's shipping 0.3.29 (`objs`/`calib`/envelope are
> unchanged; the two new fields are appended and ignored by every existing consumer).

---

## What this adds (and why 0.3.29 could not see it)

MvC2 has **two render machines**. 0.3.29's `harvest_objs` walks only the **2D slot table**
(`blk+0x2f4d0`, marvelous2 `loc_8c0308c2`) — and a whole-tape scan confirmed it captures **0 cat 5-13
nodes**. The impact-hit sparks — **cat8 rings, cat7 victim-anchored sparks, and the bank10
`loc_8c100968` list-7 sparks** — render on the **SECOND (3D / NaomiLib) machine** whose walker
`loc_8c030410` (bank03:447) walks **list HEADS** (DC `0x8C287A5C[idx]`, `node.next @ +0x0C`, gate
`u8(node+0x12C)!=0 && *(node+0x84)!=0`), **never** the slot table. This is the "separate list walk"
`docs/OWNED-RENDER-BUILD-SPEC.md §4` deferred, and the `blk+0x6CE8`/`0x0CED` value-test 0.3.29 dropped
(it keys ONLY these 3D-class effects). Source: `re_kb finding:3d_draw_emit_map` /
`tools/re_kb/64_3d_machine_draw_path.surql`.

## The RAW-PREFIX self-describing approach (per Tris's directive — exactly how the 0.3.29 calib blob works)

Two Steam facts are **INFERRED, not confirmed**, and this release does **NOT** guess them live:

1. **The Steam list-head table offset is AMBIGUOUS.** DC `0x8C287A5C` maps to Steam **blk+0x23E3C**
   (via Δ`0x8C263C20`) **OR** **blk+0x2F14C** (via Δ`0x8C258910`) — two *overlapping*
   `mvc2-dc-steam-block-map` ranges both claim it. Stride is `4` on DC (u32) but likely `8` on Steam
   (native ptr). → **`head3d`** dumps `0x80` raw bytes at **both** candidate offsets, ONCE at battle
   start. Offline: whichever window holds words that resolve to real list-head pointers pins the true
   offset + stride.
2. **The 3D-node field offsets may be +0x44-shifted on Steam** (like the render cluster's confirmed
   +0x44 delta). The offsets to pin (DC, `finding:3d_draw_emit_map`): MVP matrix `+0x88` (16 floats),
   model `+0x84`, flags `+0xCC`, alpha `+0x74`, color `+0x78/7C/80`, owner `+0x28`, cat `+0x03`, list
   `+0x24`. → **`calib3d`** dumps each drawn 3D-node's **raw `H+0x00..0x1C0` (448 B) prefix** — the same
   448-B window and wire shape as the 0.3.29 `calib` blob. `0x1C0` covers every offset above **AND** its
   +0x44-shifted position (the unit test asserts this). Every field derives OFFLINE from the raw prefix,
   **no new live probe**.

## The 6 changes (all APPEND-ONLY)

1. **Constants** (`CALIB3D_*`): `MAX_FRAMES=8` (half the objs-calib budget), `MAX_ATTEMPTS=240` (runaway
   bound), `PREFIX_LEN=0x1c0`, `MAX_NODES=24`/frame, `MAX_HOPS=32`/list, `LIST_LO/HI=5/13`,
   `HEAD_STRIDE=8` (INFERRED), `HEAD_DUMP=0x80`, `HEAD_CANDS=[0x23e3c, 0x2f14c]`.
2. **`harvest_3d(h, blk, out)`** — the NaomiLib list walk: for each candidate head table × list `5..=13`,
   read the head (u64), walk `node.next @ +0x0C` up to `MAX_HOPS` with cycle/dedup guard, and capture the
   448-B prefix of nodes where `cat ∈ [5,13]` **and** a model pointer is sane at `+0x84` **or** `+0xC8`
   (both the DC and +0x44 candidate). **Read-only RPM; every guessed-pointer read fails safe (`read_at`→
   `None`).** Capped at `MAX_NODES` prefixes/call.
3. **`dump_3d_heads(h, blk)`** — the one-shot `head3d` envelope dump.
4. **`GsCapture`/`GsSnapshot`** — three appended fields: `calib3d`, `head3d`, `calib3d_seen`; cleared at
   match start; `head3d` filled where `battle_blk` is captured.
5. **Per-frame path** — the bounded walk runs only while `calib3d.len() < MAX_FRAMES && calib3d_seen <
   MAX_ATTEMPTS`; RPM reads before the lock; keeps only frames that yielded a 3D-node ("first N frames
   *containing* drawn 3D-class nodes"). Skipped on rollback re-reads (mirrors the 0.3.29 calib gate).
6. **Tape emit** — two appended JSON fields `calib3d`/`calib3d_frames`/`calib3d_enc` (per-frame
   `[u32 frame, u16 count, count × 448B prefix]`) and `head3d`/`head3d_enc` (per-candidate
   `[u32 blk_off, u16 len, len bytes]`). `GS_SCHEMA` and every existing column index are untouched.

## Bound (the 333Hz poller add is negligible)

The walk runs on at most **240 attempted frames** total, then never again; per attempted frame it does
`≤2 head tables × 9 lists × 32 hops` reads worst-case, but a head that fails the pointer-sanity check
short-circuits with **1** read (the common case when the offset is wrong), and it stops the instant
`MAX_NODES` prefixes are captured. `head3d` is a single 2-region dump at battle start. No allocation on
the steady-state path once the 8-frame budget fills. Compare to the 0.3.29 object calib (16 frames × up
to 64 reads) — same order, bounded harder.

## Guardrail: `cargo test` (verbatim)

```
   Compiling rr-agent v0.3.30 (...\scratchpad\agentcheck)
    Finished `test` profile [unoptimized + debuginfo] target(s) in 9.65s
     Running unittests src\main.rs (...\rr_agent-fa77b3e8283eb46f.exe)

running 5 tests
test reader::gs_stats_tests::attribution_sides_chip_ko ... ok
test reader::gs_stats_tests::calib3d_prefix_covers_offsets_and_frames_roundtrip ... ok
test reader::name_scrape_tests::interior_replacement_char_rejected_edges_trimmed ... ok
test tray::icon_tests::print_is_legible_weight ... ok
test tray::icon_tests::icon_is_full_bleed_at_every_size ... ok

test result: ok. 5 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s
```

The stats-test `row()` constructor is **untouched and stays exhaustive** — 0.3.30 adds no `GsRow` field
(so the E0063 trap the guardrail warns about does not apply here). The new
`calib3d_prefix_covers_offsets_and_frames_roundtrip` test asserts (a) every 3D-node offset AND its +0x44
shift fits inside the 448-B prefix, and (b) the `calib3d` framing round-trips.

## Per-match size delta (measured, gz)

| case | raw | gz |
|---|---|---|
| **nothing captured** (likely until the offset is pinned offline) — `calib3d` empty + `head3d` (2×134 B) | ~0.3 KB | **~0.05 KB** |
| **full capture** — 8 frames × 6 nodes × 448 B + `head3d` | ~22 KB | **~0.6 KB** |

**Total ≈ 0.05–0.6 KB gz/match** (typically well under 0.3 KB — the 448-B prefixes are mostly-zero and
compress ~70×). Tapes stay ≈52–54 KB. Negligible vs the 0.3.29 target of 2–4 KB gz/match.

## Falsification gate (do NOT declare a false win)

`calib3d_frames = 0` on every uploaded 0.3.30 tape is a **NULL result**, not proof — the most likely
cause is that neither candidate head-table offset (`0x23E3C`/`0x2F14C`) nor the stride guess is right.
When that holds, **`head3d` is the payoff**: it dumps both candidate regions raw so the true Steam
list-head offset + stride pins OFFLINE (identify the words that resolve to list-head pointers into blk).
Once pinned, either (a) correct `CALIB3D_HEAD_CANDS`/`CALIB3D_HEAD_STRIDE` and re-ship, or (b) trim this
release entirely if the sprite-render oracle proves the 3D key out another way. Do **not** escalate to a
live probe — this whole release is designed so the enumeration self-describes from a normal uploaded match.
