# RECEIPT-RUNNER-GATE-N1 — rollback-state sufficiency for the receipt runner, and what rollback actually costs (2026-09-04)

Owner lane: SUPERGUN ENGINE (requested by the SUPERGUN NETCODE lane, for whom this was the blocking gate).
Prerequisites: `docs/RECEIPT-RUNNER-GATE1.md` (the native runner), `docs/RECEIPT-RUNNER-GATE3.md` (the arc loader).
Deliverables: `d3dcap/receipt/runner/rr_runner.cpp` (`--rollback` / `--rb-set` / `--rb-verify` / `--rb-ctx-extra` /
`--rb-events` / `--rb-on-mismatch`), `d3dcap/receipt/runner/gate_n1.py`, seed
`maplecast-flycast/tools/re_kb/121_receipt_runner_gate_n1.surql`.

## RE METHOD (locked; `docs/RE-METHOD.md`)

1. Port the SH4 annotations to the Steam binary by function matching.
2. Seed with unique constants, then propagate along the call graph.
3. Translate globals through the block map before comparing reference sets.
4. Tag CONFIRMED versus INFERRED, and store the pairs as edges in the knowledge graph.

Step this document is at: **4**. Step 3 is what turned the failure into a finding: the diverging byte was translated
through `d3dcap/replay/re_map/blkmap.py` (`blk+0x1D6FC` = DC `0x8C27B034` = object-pool node 144 field `+0x124`)
before anything was concluded from it. Tags: **CONFIRMED** = reproduced by a byte gate; **INFERRED** = read in the
disassembly, gate-consistent; **UNKNOWN** = not located. No time estimates. BYOR: all outputs under `%TEMP%\rr_n1`.

## 0. Why this gate exists

The shipped MvC2 netcode persists only `blk` in its GGPO save/load callbacks, and pays **4 frames = 66.7 ms of
unconditional input delay to avoid ~0.42 ms of resimulation CPU**. That trade is rational for a ~10 ms/frame engine
and absurd for our ~0.08 ms one — *provided rollback is actually sound for our runner*, which had never been tested.
Our process touches host state the shipped game never has to think about: the lazily committed device-object page
`*(0x140acd3a8)` whose PALETTE_RAM the tick writes (GATE1 §3.4), and the ctx page-table records (GATE1 §3.5,
proven run-dependent in GATE3 §5).

A save measurement composed after the fact with a tick measurement is **not** a rollback measurement, and it says
nothing at all about sufficiency. `--rollback N` does both in one interleaved loop: every tick the chosen save set
goes into a ring of `N+1` slots; after tick `k >= N` the slot from tick `k-N` is restored, the same `N` inputs are
re-ticked, and **every** candidate region is byte-compared against the straight-line state at the same clock.

## 1. Result

### 1.1 Sufficiency — the shipped `blk`-only set is NOT enough; `blk` + 8 bytes is

| save set | contents | bytes | depths 0/2/4/8/16/30/60/120 |
|---|---|---|---|
| `blk` | blk + the GGPO counter (what the shipped game persists) | 211,752 | **FAIL** from depth 2 up |
| **`rr`** | **blk + GGPO counter + `ctx+0x1F8230..0x1F8238`** | **211,760** | **PASS at every depth** |

Run: `d3dcap/ttd/runs/receipt-20260903-stage9-anchor`, 200 real receipt ticks from clock 1716, ~200 rollback events
per depth (one after every eligible tick — the worst case, not a sample).

*PASS* means byte-identical on **blk, blk2, the game_state page, the exe page `0x142edf300`, the whole 32 MB DC-RAM
image, and every lazily committed host page including the device object.* The `blk` arm fails on 1–3 events per
depth, always at the same place: `blk+0x1D6FC` = **object-pool node 144, field `+0x124`** — a sprite-walker
placement field (the same field GATE2 §3.3 saw the walker write more than once per node).

### 1.2 Cost — per EVENT, not an eligibility-weighted average (N1b, restated 2026-09-04)

**The earlier "amortised ms/frame" column is withdrawn.** It divided the total rollback work by *all* ticks,
including the first `N` that carried no rollback, so it was **eligibility-weighted**: it understated the cost by
`(ticks-N)/ticks`, was undefined for a run of `<= N` ticks, and read 4.5 ms/event at 200 ticks vs 3.0 at 300 for the
same depth-120 data. A frame budget is a **deadline, not an average**, so the table below reports the per-EVENT cost
with **p99 and max**, the **count of events exceeding 16.667 ms**, and the **tick count of every run**.

- `event` = save + restore + resim (the rollback overhead on the frame that rolled back)
- `frame` = event + the straight-line tick of that same frame — the total work that frame must fit in the budget

Save set `rr`; **300 ticks** per run; a rollback after **every** eligible tick (the pathological worst case, not a
sample); `--heap-mb 1024` so `heap_wraps = 0` (see the note below).

| depth | events / ticks | ring | stage 9 event p50 / p99 / max | stage 9 **frame p99 / max** | Carnival event p50 / p99 / max | Carnival **frame p99 / max** | over budget |
|---|---|---|---|---|---|---|---|
| 0 | 300/300 | 207 KB | 0.012 / 0.105 / 0.140 | 0.354 / 0.457 | 0.045 / 0.180 / 0.208 | 0.314 / 0.546 | 0 / 0 |
| 2 | 299/300 | 620 KB | 0.124 / 0.376 / 0.404 | 0.630 / 1.106 | 0.115 / 0.294 / 0.462 | 0.504 / 0.528 | 0 / 0 |
| 4 | 297/300 | 1.0 MB | 0.190 / 0.640 / 0.753 | 0.817 / 0.899 | 0.233 / 0.572 / 1.080 | 0.652 / 1.155 | 0 / 0 |
| 8 | 293/300 | 1.8 MB | 0.375 / 0.863 / 0.989 | 1.068 / 1.094 | 0.388 / 0.727 / 0.897 | 0.787 / 0.958 | 0 / 0 |
| 16 | 285/300 | 3.4 MB | 0.747 / 1.501 / 1.628 | 1.600 / 1.730 | 0.731 / 1.369 / 1.567 | 1.465 / 1.687 | 0 / 0 |
| 30 | 271/300 | 6.3 MB | 1.312 / 2.695 / 3.152 | 2.792 / 3.220 | 1.025 / 1.770 / 1.965 | 1.874 / 2.022 | 0 / 0 |
| 60 | 241/300 | 12.3 MB | 2.557 / 5.304 / 5.850 | 5.368 / 5.926 | 2.059 / 3.342 / 3.808 | 3.561 / 3.857 | 0 / 0 |
| 120 | 181/300 | 24.4 MB | 5.191 / 9.207 / 9.463 | **9.239 / 9.511** | 4.479 / 7.149 / 7.429 | **7.191 / 7.463** | 0 / 0 |

All figures in ms. **0 events exceeded the 16.667 ms budget at any depth on either stage.** Worst single frame
measured anywhere: **9.51 ms at depth 120 on stage 9** (57 % of budget).

**Per-stage spread is real and runs in both directions**: at depth 120 the worst frame is 9.51 ms on stage 9 and
7.46 ms on Carnival, a 27 % difference; at depth 30 Carnival is the cheaper by 37 %. Cost is therefore a function of
**stage content**, not an engine constant, and a single-stage table cannot size a speculation cap on its own.

For a **cap of 32**, interpolating the depth-30 row: worst-case frame ~3.2 ms (stage 9) and ~2.0 ms (Carnival), i.e.
~19 % of budget on the worse of the two stages measured, with a rollback on *every* frame — far more pessimistic
than GGPO would ever produce.

#### An instrumentation artefact this table used to contain, and how it was caught

The first emission showed **1 event over budget at depth 120 (max 18.31 ms)** and an 11.78 ms outlier at depth 60.
Both were the runner's own bump heap **wrapping**: a resim consumes it `depth+1` times faster, and a wrap
`memset`s up to 64 MiB *inside one tick*. `summary.json` records `heap_wraps`, which read exactly 1 at both of those
depths and 0 everywhere else — the outliers were mine, not the engine's. `--heap-mb` now sizes the heap, both driver
scripts pass 1024, and every row above has `heap_wraps = 0`. **Any future timing run must check `heap_wraps` before
the numbers are quoted.**

## 2. The control that makes the verdict trustworthy (run FIRST, every time)

`--rollback 1 --rb-set full --rb-verify all`: restore **everything** (blk, blk2, game_state page, exe page, the whole
4 MB ctx, the whole 32 MB DC-RAM, the GGPO counter) and re-execute **one** tick with the same input word.

Result: blk, blk2, game_state and exe come back byte-identical on every event — but **ctx does not**: 39 of 40 events
differ, 5,796 B, entirely inside two buckets:

| ctx bucket | bytes | what |
|---|---|---|
| `+0x100030..0x108FC0` decoded texture pages | 124 | `FUN_140800620/640` memcpy destination |
| `+0x108FC0..0x1E0030` page-table records | 5,672 | GATE1 §3.5: records `memcpy`-d from a stack buffer |

Nothing was left un-restored that could carry that difference, so it is **nondeterminism in the tick itself**, not
missing rollback state — the GATE1 §3.5 uninitialised-stack family, now reproduced inside one process with
everything else held identical, and the same family as GATE3 §5's 128 B `ctx_out` residual between two runs.
Neither range is on the frame's ctx read set (`FRAME-READSET` §3.4).

`rr_runner` therefore classifies ctx differences by bucket (`ctxBucketNondet`) and never fails on those two, while
**any other ctx bucket differing is a real failure** — especially the texture-slot table, which the tick reads as
well as writes and would therefore be genuine rollback state. The control is re-run by `gate_n1.py` on every
invocation so the exemption is re-derived rather than assumed.

## 3. How the 8 bytes were found (bisection, not guesswork)

Save-set ladder at depth 8, 200 ticks, verifying blk/blk2/gs/exe:

| save set | includes | verdict |
|---|---|---|
| `blk` | blk + ggpo | FAIL `blk+0x1D6FC` |
| `blkctx` | + ctx slot table + ctx matrix state | FAIL, same byte |
| `sim` | + blk2 + gs page + exe page | FAIL, same byte |
| `simdc` | `sim` + **all 32 MB of DC-RAM** | **FAIL, same byte** |
| `simtile` | `sim` + the `0x0CE60000` tile buffer | FAIL, same byte |
| `simctx` | `sim` + **the whole 4 MB ctx** (no DC-RAM) | **PASS** |
| `full` | everything | PASS |

So the missing state is in **ctx**, and **not** in DC-RAM. Bisecting ctx with `--rb-ctx-extra` (hex `LO-HI` ranges,
added to the save set without a rebuild):

```
1F8000-1F9000 PASS   0-30000 FAIL   30000-32000 FAIL   100000-110000 FAIL   1E0000-1E4000 FAIL   1F0000-200000 PASS
1F8000-1F8400 PASS   1F8400-1F8800 FAIL   1F81C0-1F8280 PASS   1F81C0-1F8200 FAIL   1F8200-1F8240 PASS
1F8220-1F8240 PASS   1F8230-1F8238 PASS   1F8230-1F8234 FAIL   1F8234-1F8238 FAIL
```

`ctx+0x1F8230..0x1F8238` — 8 bytes, two f32, **both required**. And `blk` + those 8 bytes alone passes: neither
blk2, nor the game_state page, nor the exe page, nor the ctx slot table is needed.

### What the 8 bytes are

**INFERRED.** They sit inside the NaomiLib projection/viewport block that `FUN_140846a40` initialises wholesale
(`MOVUPS xmmword ptr [RAX + 0x1f8230], XMM1` at `0x140846BF7`; callers `FUN_14060b550`, `caseD_9`, `caseD_0`).
No literal `0x1f8230`/`0x1f8234` displacement occurs anywhere in the 10,803-function disassembly cache
(`d3dcap/replay/re_map/cache/steam_disasm.jsonl`), so the per-frame access is **indexed** and the reader is
**UNKNOWN**. Neighbours, for orientation, from the anchor's ctx: `+0x1F8200` and `+0x1F8214` = `±812.357` (the
world-camera focal length), `+0x1F8220` = `-320.0`, `+0x1F8224` = `-338.4` (the ground offset), `+0x1F8230` =
`497DDC8E` ≈ 1,039,822, `+0x1F8234` = `48ABE972` ≈ 351,667.

This corrects `FRAME-READSET` §3.4, which was derived from a single training-stage idle frame and lists the ctx
reads as `ctx+0x8`, the slot table and the matrix slots: a frame also depends on `ctx+0x1F8230..0x1F8238`.

## 4. What this settles for the netcode design

- **Rollback is sound for the receipt runner**, with a save set of **211,760 B** — `blk` plus eight bytes.
- **DC-RAM does not need rolling back** (all 32 MB come back identical), and neither does the host device page
  `*(0x140acd3a8)` — the GATE1 §3.4 worry is closed by measurement, not by argument.
- **The ctx render scratch is nondeterministic even without rollback**, so it can never be part of a rollback
  correctness criterion; it is regenerated every frame and is not read.
- The cost table in §1.2 is the input to the delay decision. Nothing here says what frame delay to ship — that is
  the netcode lane's call — only what rollback costs and that it is correct.

## 5. Implementation notes (`rr_runner.cpp`)

- The GGPO counter at `0x142d10b90` (0x10 B) is restored in **every** tier. `FUN_140118950` bumps it once per call,
  so without restoring it a resim would differ by `N` on pure wrapper bookkeeping (contract C2, GATE1 §3.6). This is
  logged at start-up so the choice is never silent.
- The bump heap now **wraps and re-zeroes** instead of dying: a resim consumes it `N+1` times faster. Handing back a
  re-zeroed chunk is equivalent (the CRT asks `HEAP_ZERO_MEMORY`, and GATE1 proved 300 ticks byte-exact with a
  monotonically advancing pointer). Wraps are counted; each pollutes exactly one tick sample. At 64 MiB and ~5.1 KB
  per tick a wrap needs ~13,000 ticks, so none occurred in this gate (`heap_wraps: 0`).
- `--rb-on-mismatch reset` (default) restores the reference after a failing event so later events stay independent.
- Timing arms use `--rb-verify off`; the 36 MB of verification copying in `--rb-verify all` makes timings meaningless
  and those numbers are discarded. `gate_n1.py` runs both arms per depth for exactly this reason.

## 6. CONFIRMED / INFERRED / UNKNOWN

| item | tag |
|---|---|
| `blk`-only rollback is insufficient; the divergence is `blk+0x1D6FC` = pool node 144 `+0x124` | CONFIRMED (~200 events per depth, 7 depths) |
| `blk` + GGPO counter + `ctx+0x1F8230..0x1F8238` is sufficient | CONFIRMED (PASS at depths 0/2/4/8/16/30/60/120) |
| Both dwords of those 8 bytes are required | CONFIRMED (each 4-byte half fails alone) |
| DC-RAM and the lazily committed host pages need not be rolled back | CONFIRMED (`simdc` FAIL / `simctx` PASS is the falsification arm) |
| Two ctx render-scratch buckets are nondeterministic per tick, not rollback state | CONFIRMED (depth 1, `--rb-set full` control) |
| The identity of the two f32 at `ctx+0x1F8230` | INFERRED (projection/viewport block, `FUN_140846a40` writes them) |
| The per-frame READER of `ctx+0x1F8230..0x1F8238` | **UNKNOWN** — indexed access; not found by literal-displacement search |
| Behaviour on an ONLINE match, on other stages, or with a HUD-heavy frame | UNKNOWN — one stage-9 offline receipt only |
| Whether the 8 bytes are stage- or camera-dependent (i.e. whether a bigger ctx window is needed elsewhere) | UNKNOWN — re-run §3's ladder on a Gate 4 stage |

## 7. Commands

```
rem the whole gate: control arm + both save sets across the depth matrix
python C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\receipt\runner\gate_n1.py --run C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\runs\receipt-20260903-stage9-anchor --inputs %TEMP%\rrcap_runner\gate2_300\inputs.txt --ticks 200 --sets rr blk --json %TEMP%\rr_n1\gate_n1.json

rem one arm by hand
C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\receipt\runner\rr_runner.exe --pre <run>\pre --out %TEMP%\rr_n1\x --ticks 200 --dump-every 0 --no-dump-end --inputs <inputs.txt> --rollback 8 --rb-set rr --rb-verify all

rem bisect a failure inside ctx without rebuilding
... --rb-set sim --rb-verify small --rb-ctx-extra 1F8230-1F8238
```

Seed: `maplecast-flycast/tools/re_kb/121_receipt_runner_gate_n1.surql` (applied 2026-09-04, 27 statements, 0 failed;
replay verified idempotent; backup `re_kb_data/_exports/re_kb_20260904-*_pre121.surql`).

## 8. GATE N1c — is the SHIPPED window sufficient on this stage? (added 2026-09-04)

Designed by the SUPERGUN NETCODE lane, who consume the result. The design question is not "what is the minimum on
stage X" but "does the window we intend to ship survive stage X". That is **three arms at one depth**, not a
bisection — `d3dcap/receipt/runner/gate_n1c.py`, depth 8, 300 ticks, a rollback after every eligible tick:

| arm | save set | meaning of a FAIL |
|---|---|---|
| **A** | `blk` + GGPO counter (the shipped game's own set) | this stage needs ctx state at all |
| **B** | A + the proven 8 B `ctx+0x1F8230..0x1F8238` | the minimum is stage-dependent **in its content**, not merely in its necessity |
| **C** | A + the shipped 64 KB window `ctx[0x1F0000..0x200000)` | **the §9.2 save set is FALSIFIED** and deep speculation dies in its current form |

**Falsification condition, stated so it cannot be fudged: the save set survives iff arm C passes on EVERY stage
tested. One arm-C failure kills it.** Escalate to the full ladder only where **B fails and C passes** — the sole
case where a new minimum is informative.

### Results

| stage | arm A | arm B | arm C | escalate? |
|---|---|---|---|---|
| 9 (offline receipt) | **FAIL** (tick 61, `blk+0x1D6FC` = pool node 144 `+0x124`) | PASS | **PASS** | no |
| 3 Carnival (arc-built, no dump) | PASS | PASS | **PASS** | no |

**Arm C has passed on every stage tested. The §9.2 save set survives so far.** Arm B never failed, so the "new
minimum" branch has not been reached. Arm A's split (FAIL on 9, PASS on 3) is the §4 stage-dependence result.

Cost at depth 8, 300 ticks, 293 events (event p50 / p99 / max, ms):

| stage | arm A | arm B | arm C (ring 2.4 MB) |
|---|---|---|---|
| 9 | 0.480 / 1.239 / 1.734 | 0.488 / 1.227 / 1.370 | 0.514 / 1.672 / 1.896 |
| Carnival | 0.348 / 0.678 / 1.015 | 0.401 / 0.755 / 0.894 | 0.341 / 0.678 / 0.725 |

0 events over the 16.667 ms budget in any arm. The 64 KB window costs ~0.5 MB more ring per slot and, at depth 8,
no measurable per-event penalty beyond noise.

**Run this on every stage from now on**, including River Raft when the live dump arrives:

```
python C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\receipt\runner\gate_n1c.py --run <run dir> --inputs <inputs.txt> --depth 8 --ticks 300 --label <stage> --json <out.json>
```

## 9. A rule that generalises beyond this gate

`ctx_out` equality is **not** a proxy for pixel equality: submitted geometry lands in the host staging buffer at
`*(game_state+0x208)`, past the DC-RAM image, which nothing dumps (`FRAME-READSET` §3.5; demonstrated in
`RECEIPT-RUNNER-GATE4.md` §1, where 26 KB of scrambled drawn geometry left `ctx_out` byte-EQUAL while the harvested
tape changed). **A save-set hash proves SIM agreement, never PIXEL agreement. No SUPERGUN result may be reported as
"frames match" on the strength of one.**

A consequence for the netcode lane's resync design, from `RECEIPT-RUNNER-GATE4.md` §1: the static geometry objects
are read for pixels every frame and are **not** in any save set, so a state transfer cannot reconstitute a
renderable peer — **the receiver must already hold them from its own arc.**
