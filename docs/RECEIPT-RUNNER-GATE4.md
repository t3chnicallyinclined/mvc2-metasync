# RECEIPT-RUNNER-GATE4 — H1 falsified, classes E/L/X proven unread, and a receipt run on a stage with no dump (2026-09-04)

Owner lane: SUPERGUN ENGINE. Workstream: `docs/WORKSTREAM-RECEIPT-RUNNER.md` §4 step 4. Prerequisites: Gate 1/2/3
(`docs/RECEIPT-RUNNER-GATE1.md`, `-GATE2.md`, `-GATE3.md`) and Gate N1 (`docs/RECEIPT-RUNNER-GATE-N1.md`).
Deliverables: `d3dcap/receipt/h1_gate.py`, `d3dcap/receipt/dcram_build.py` (`--stage`, `--fill`, `--poison-e`),
seed `maplecast-flycast/tools/re_kb/123_receipt_runner_gate4.surql`.

## RE METHOD (locked; `docs/RE-METHOD.md`)

1. Port the SH4 annotations to the Steam binary by function matching.
2. Seed with unique constants, then propagate along the call graph.
3. Translate globals through the block map before comparing reference sets.
4. Tag CONFIRMED versus INFERRED, and store the pairs as edges in the knowledge graph.

Step this document is at: **4**. Step 3 is again what turned a result into a finding: the H1 verdict only became
correct once the perturbed bytes were followed through the **harvest** rather than through `ctx_out`, which is blind
to them. Tags: **CONFIRMED** = reproduced by a byte gate; **INFERRED** = read in the disassembly; **UNKNOWN** = not
located. No time estimates. BYOR: all outputs under `%TEMP%`.

## 0. Results

| # | question | answer |
|---|---|---|
| 1 | H1: "a drawn node's destination object is always write-before-read within the frame" | **FALSIFIED** — 14 of 16 objects are never rewritten at all; the 2 that are, are only *partially* rewritten |
| 2 | Are DC-RAM classes E (`+0x145000`), L (leftovers) and X (non-battle banks) read? | **PROVEN unread** by perturbation — 6.9 MB of poison difference, 300/300 byte-identical blk |
| 3 | Does the stage-0x10 ISP/TSP fix-up (never executed before) work? | **Yes** — 16 bytes, models **1..8**, 2 records each, exactly the two decompiled branches |
| 4 | Can a receipt run on a stage for which **no memory dump exists**? | **Yes** — Carnival (stage 3), 300 ticks, from battle anchor + the user's arc alone |
| 5 | Does the Gate N1 8-byte ctx window widen on another stage? | **It is not universal at all**: on Carnival `blk` **alone** passes. Ship the superset — see §4 |

## 1. H1 is falsified (and it does not matter, for a reason worth stating precisely)

`docs/RECEIPT-RUNNER-RE.md` §1.5 declared the H1 test unrunnable: *"a real-stage dump with list-5 props (none exists
yet — the only live dumps are stage 0x0B)"*. **That is stale.** The stage-9 receipt run built for Gate 0/1/2 has
five list-5 prop nodes, two of them animated in place every frame. H1 was therefore testable offline, today, with no
capture.

`d3dcap/receipt/h1_gate.py` scrambles the **vertex payload** of every record of every destination object at
`*(node+0xA0)` for the System-A nodes of the chosen lists — bytes `rec+0x50 .. rec+0x50+rec[0x4C]`, leaving the
0x50-byte record headers intact so the NaomiLib iterator can still walk. 16 objects, 26,072 bytes, lists 5/6/7.

### Arm 1 — the simulation

**blk is byte-identical on 61 of 61 ticks.** `gs_out` and `exe_dat_out` equal. The sim never reads these objects, so
the anchor does not need them. CONFIRMED.

### Arm 2 — is each object actually regenerated?

Reconstructing DC-RAM at tick 60 by replaying the `--harvest-dump` page deltas and asking how much of each scrambled
payload is still `0xA5`:

| class | count | objects |
|---|---|---|
| **STATIC** — read every frame, never rewritten | **14** | effects quads `0x0D000FC8`, `0x0D0021..0x0D0025`, `0x0D00B708/B8F8/BB00`, `0x0D019E88`; stage deck `0x0D84F5D8` (14,864 B), `0x0D8534F8` (8,480 B), `0x0D8556A8` |
| **PARTIAL** — only the animated vertex fields rewritten | **2** | `0x0D853158` TCW 0xC12 (244 of 352 B still poisoned), `0x0D855800` TCW 0xC1C (312 of 408 B still poisoned) |
| **fully regenerated** | **0** | — |

So H1 is false twice over: most objects are never written in the frame at all, and even the animated ones inherit
every vertex field their callback does not touch.

### Why `ctx_out` is the wrong criterion (a trap worth recording)

`ctx_out` compared EQUAL between the clean and scrambled runs, which would have read as "H1 holds". It does not: the
submitted geometry goes to the host staging buffer at `*(game_state+0x208)`, **past** the DC-RAM image, which
`rr_runner` does not dump (`FRAME-READSET` §3.5). The perturbation demonstrably *does* reach the renderer's input —
the harvested tape changes (54,585 → 43,206 B gz, `aobjs` 153 → 154). Use the harvest, never `ctx_out`, for this
question.

### The consequence, in two parts

1. **Simulation: unaffected.** The anchor never needed these objects.
2. **Pixels: their prior content IS read every frame** — and that is not a gap, because **Gate 3 rebuilds exactly
   those bytes from the user's arc byte-exactly** (`UNEXPLAINED: NONE`). The arc loader path is therefore
   **load-bearing for pixels**, not merely a convenience. This also supplies the *mechanism* behind Gate 3's
   class-A residual: for the 2 partially-rewritten props, the fields the callback does not touch are inherited
   forever, so pristine arc bytes can never match a live mid-match phase in those fields.

## 2. Classes E, L and X are PROVEN unread (upgrade from "measured unread")

Gate 3 could only say those classes were *not read on the frames measured*. A perturbation settles it. Two
arc-built images of the **same** Carnival anchor, differing **only** in bytes the loader never writes:

| arm | class L + X (every unwritten DC-RAM byte) | class E (six 12,288 B regions at `base+0x145000`) |
|---|---|---|
| A | `0xCD` | `0x00` |
| B | `0x5A` | `0xA5` |

~6.9 MB of difference. 300 ticks with the tape's inputs: **300/300 blk dumps byte-identical**, `gs_out`,
`exe_dat_out`, `ggpo_out` all equal, RNG identical at tick 300. `ctx_out` differs by 102 B — **entirely** in the
`page-table-records` bucket (38 runs from `ctx+0x10D1B8`, stride `0x130`), i.e. the GATE1 §3.5 / GATE-N1
nondeterminism family, below the ~128 B run-to-run floor.

So the twelve kilobytes per PL slot that `FUN_140612180` writes, the leftovers past every loaded file, and the
select/VS/result banks are **provably not on the frame's read path** — on a stage with morph props and a roster
(`[42,34,44,6,50,16]`, assists `[0,0,1,1,1,2]`) that had never been gated. `dcram_build.py --fill` / `--poison-e`
make this a one-command re-run for any future anchor.

Consequence: the Gate 3 §7 "call the game's own loaders" item is **no longer needed to close class E**. It remains
the right end state for fidelity, but it is not blocking.

## 3. Stage 0x10: the fix-up that had never executed

`dcram_build.py --stage 16` builds the River Raft bank (AFS 833/834) from the arc without needing a dump of that
stage. First execution of `FUN_14060d470`'s stage-0x10 branch, and it is exactly what the decompile predicts:

- **16 bytes changed, in models 1..8, two records per model**, one of each branch:
  - `texIndex == 10` → `rec+0x4 |= 0x4000000` (byte `rec+0x7`: `0x83 → 0x87`)
  - `texIndex == 5` → `rec+0x0 &= ~0x2000000` (byte `rec+0x3`: `0x82 → 0x80`)
- **model 0 is NOT touched.** This exercises on real data the Gate 3 §4.2 correction to
  `RECEIPT-RUNNER-DCRAM` §2.3's "models 0..7": the counter starts at `-1` and is tested before its post-increment.

Structural gate on the resulting stage-0x10 image: 26 models, **104 records walked, 0 malformed**, **every record
satisfies `TCW == 0xC10 + texIndex`**, 11 texture records, **0 locs outside the TEX span**.

Still open: the stage-0x10 image has **not** been compared against a live River Raft dump, because none exists
(§6).

## 4. Gate N1 on a second stage: the 8-byte ctx window is NOT universal

Re-running the N1 ladder on the Carnival anchor (depths 0/2/8/30/120, ~200 events each):

| save set | stage 9 | Carnival (stage 3) |
|---|---|---|
| `blk` (what the shipped game persists) | **FAIL** from depth 2 up (node 144 `+0x124`) | **PASS at every depth** |
| `rr` (blk + `ctx+0x1F8230..0x1F8238`) | **PASS** | **PASS** |

**This is the important refinement, and it sharpens rather than weakens Gate N1.** The `blk`-only set is not
"wrong everywhere" — it is wrong *sometimes*, depending on stage/camera/situation. A save set that passes on one
stage and silently corrupts on another is precisely the failure that only shows up online, under load, late. The
shippable conclusion is unchanged and now better supported: **take the superset, `rr` = blk + 8 bytes**, which is
211,760 B and passes on both stages tested.

**Cost figures previously quoted here are WITHDRAWN** — they used the eligibility-weighted amortised ms/frame
column and did not state the tick count. The corrected per-event table, with p99/max, the over-budget count and
the tick count of every run, is `docs/RECEIPT-RUNNER-GATE-N1.md` §1.2. Carnival at depth 120, 300 ticks: worst
single frame **7.46 ms**, 0 of 181 events over the 16.667 ms budget.

The three-arm N1c check (`docs/RECEIPT-RUNNER-GATE-N1.md` §8) has since been run on both stages: arm C — the
shipped 64 KB ctx window — **passes on both**, so the netcode lane's §9.2 save set survives. Arm A fails only on
stage 9, which is the stage-dependence result above.

The N1 control arm re-ran here too: 39 of 40 events show ctx render-scratch nondeterminism, 7,501 B, **100 % in the
`page-table-records` bucket** (no `decoded-texture-pages` this time), 0 fatal mismatches — the exemption rule holds
on a second stage.

## 5. A receipt run on a stage with no memory dump — BYOR-complete, demonstrated

The Carnival anchor came from a **tape** (`local_1788482771252_stage3`, 4,461 rows, agent 0.3.50). No `dump_live`
run of that match exists; its DC-RAM was built **entirely from `game_50.arc`** by `dcram_build.py`. The runner
executed 300 ticks cleanly — self-checks 18/18, clock 2756 → 3056, RNG advancing, 0 traps, tick p50 ~0.065 ms.

That is the Gate 3 claim demonstrated end to end on a stage whose bytes were never captured: **anchor + arc + the
user's own exe image** is sufficient to run the real frame function. (`anchor_to_run.py` still needs a same-boot
dump for `exe_image.bin` and the ctx pointer/matrix words; see §6.)

## 6. What is still open, and the one thing that needs the machine

**River Raft (stage 16 / 0x10) has not been gated live.** A tape with a battle anchor exists
(`local_1788492840709_stage16`, 7,530 frames) but its per-boot addresses (`blk 0x160C1000`) match no `dump_live`
run, and `anchor_to_run.py` requires a same-boot dump for three things the anchor does not carry:

1. `exe_image.bin` — content is boot-independent, but it has to come from somewhere;
2. `ctx[0..0x18]` — the three self pointers (derivable from the anchor's own game_state page);
3. **`ctx+0x1F80A0..0x1F8280`** — the matrix/projection block, including the 8 bytes Gate N1 proved matter.

Item 3 is the real blocker and it is the agent-side item already on the coordinator's list (carry
`ctx+0x1F80A0..0x1F8280`, 480 B, in the battle anchor). Once the agent carries it, **every existing tape with an
anchor becomes runnable without any dump at all** — there are already anchored tapes for stages 0, 1, 2, 3, 7, 10,
15 and 16 in `gs-cache-local`. That is a much larger unlock than River Raft alone.

Until then, the live ask is one match — see the handover note.

| item | tag |
|---|---|
| H1 falsified: 14 static / 2 partial / 0 fully regenerated objects | CONFIRMED (perturbation + delta replay, 61 ticks) |
| The sim never reads destination objects (26 KB scrambled, 0 blk bytes changed) | CONFIRMED |
| `ctx_out` is blind to submitted geometry; use the harvest | CONFIRMED (tape changed, ctx did not) |
| Classes E, L, X are not read | **CONFIRMED by perturbation** (was: measured, Gate 3) |
| Stage-0x10 fix-up: 16 bytes, models 1..8, both branches; model 0 untouched | CONFIRMED on real stage-0x10 arc data |
| Stage-0x10 image is structurally sound (104 records, TCW rule 104/104, locs in range) | CONFIRMED |
| A receipt runs 300 ticks on a stage with no dump, from anchor + arc | CONFIRMED |
| The Gate N1 8-byte ctx requirement is stage/situation-dependent, not universal | CONFIRMED (stage 9 FAIL, stage 3 PASS on `blk`) |
| `rr` = blk + 8 bytes is sufficient on both stages tested | CONFIRMED |
| Stage-0x10 arc image vs a LIVE River Raft dump | **UNKNOWN** — no dump exists (§6) |
| Carnival row/node/tape comparison against its live tape | NOT RUN — that tape is an ONLINE match with **777 rollbacks**, so a row mismatch would confound class R with a loader defect. Needs an offline tape on a prop stage |
| The 15 unclassified stage callback tables (`PTR_PTR_140a6ec20`) | UNKNOWN — unchanged from `RECEIPT-RUNNER-DCRAM` §6 |

## 7. Commands

```
rem H1
python C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\receipt\h1_gate.py --run C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\runs\receipt-20260903-stage9-anchor --inputs %TEMP%\rrcap_runner\gate2_300\inputs.txt --ticks 60 --lists 5 6 7 --mode verts

rem classes E/L/X proven unread: build two poisoned images and diff blk over 300 ticks
python C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\receipt\dcram_build.py <run> --fill cd --poison-e 00 --out A.bin
python C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\receipt\dcram_build.py <run> --fill 5a --poison-e a5 --out B.bin

rem exercise a stage bank with no dump of it (here River Raft)
python C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\receipt\dcram_build.py <any run> --stage 16 --out %TEMP%\rr_dcram_stage10.bin

rem build a runnable receipt from a tape anchor whose boot matches a dump, then run it
python C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\receipt\anchor_to_run.py <tape.json.gz> <dump run> <out run>
python C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\receipt\dcram_build.py <out run> --out <out run>\pre\dcram.bin
```

Seed: `maplecast-flycast/tools/re_kb/123_receipt_runner_gate4.surql`.

---

# GATE 4 addendum — River Raft and Ice River, live (2026-09-04)

Tris captured the pair: `d3dcap/ttd/runs/river_a` (stage **7** Ice River, clock 7490) and `river_b`
(stage **16 / 0x10** River Raft, clock 1692), plus `riverraft_river1` (an earlier dump of the same boot, clock 238).

## A1. The live stage-0x10 gate — the fix-up that had only ever run offline is now CONFIRMED against the game

`dcram_build.py --gate` on **river_b**: **`UNEXPLAINED: NONE`**, and the stage POL does not appear in the residual
list at all. Explicitly, over the whole `0x30000`-byte stage bank:

| arc build | bytes differing from the LIVE image |
|---|---|
| **without** the stage-0x10 ISP/TSP fix-up | **16** |
| **with** the fix-up | **0** |

All **16/16** fix-up bytes match live (`0x83→0x87` on `rec+0x7` for `texIndex 10`, `0x82→0x80` on `rec+0x3` for
`texIndex 5`, models 1..8). `FUN_14060d470`'s stage-0x10 branch is now gated against the game, not just decompiled.

**Ice River (river_a)**: `UNEXPLAINED: NONE` as well. Both live rosters/stages reproduce from the arc exactly.

## A2. Classes E, L, X proven unread on River Raft too

Two arc builds of the river_b anchor differing only in unwritten bytes (`0xCD`/`0x5A`) and the six `+0x145000`
regions (`0x00`/`0xA5`): **300/300 blk dumps byte-identical**, `gs_out`/`exe_dat_out`/`ggpo_out` equal.

## A3. N1c — arm C passes on both. Four stages now.

Depth 8, 300 ticks, rollback after every eligible tick. **Inputs were idle** (no tape matches these boots) — see the
caveat below.

| stage | arm A (`blk`) | arm B (+8 B) | arm C (+64 KB) |
|---|---|---|---|
| 9 | FAIL | PASS | **PASS** |
| 3 Carnival | PASS | PASS | **PASS** |
| 7 Ice River | PASS | PASS | **PASS** |
| 16 River Raft | PASS | PASS | **PASS** |

**Arm C has now passed on four stages; the §9.2 save set still survives.** Arm B has never failed, so the escalate
branch has still not been reached. Arm C cost at depth 8 (event p50/p99/max ms): river_b `0.434/0.937/2.153`,
river_a `0.441/0.896/1.179`; 0 events over the 16.667 ms budget in any arm, `heap_wraps` 0.

⚠ **Caveat:** river_a/river_b were driven with idle inputs, because no tape matches those boots. Idle still exercises
the prop/water animation and the whole render path, but not fighter action. Stage 9 and Carnival were driven with
real recorded inputs.

## A4. Two stages that share a routine table do NOT share a write set

`RECEIPT-RUNNER-DCRAM` §4.2 states that on stage 7 / 0x10 the three water meshes (models 9/11/13) are "rewritten
each frame" by `FUN_140750eb0`. Measured over 300 ticks from these anchors:

| stage | DC-RAM pages written per 300 ticks | stage-POL pages | live stage POL vs pristine arc |
|---|---|---|---|
| 7 Ice River | 5 | **2** (`0x0D854000..0x0D856000`) | 753 B differ in 296 runs |
| 16 River Raft | 2 | **0** | **0 B differ** |

Both have the same list-5 node structure — models 9, 11 and 13 bound and drawn in each. So the claim holds for
stage 7 and **not** for stage 16 from this anchor. **Mechanism OPEN** (phase-dependent gating, a different index
list, or a callback not installed); the fact is CONFIRMED both ways. Practical consequence for the loader: on stage
16 the arc bytes are the final bytes, on stage 7 they are a starting point that the engine overwrites.

## A5. `blk+0x6D04` — the mechanism, and the predicate that makes it safe

**The field is a stage-select CURSOR, not a per-match constant.** `harvest.rs:1183` ("const per match") is wrong in
letter. Writers, from a search of all 23 functions that reference `+0x6d04` in the disassembly cache:

| routine | what it does |
|---|---|
| **`FUN_14062a720`** | **the stage-select cursor.** Reads the pad bitmask at `blk+0x33A68 + side*2`: bit `0x800` decrements, bit `0x400` increments; wraps **mod 0x11** (17 stages); then prints `"STAGE  %02X"` (`s_STAGE____02X_14097e8d0`). Reached from the menu dispatch table at `0x140a6fbb0`. |
| `FUN_14060e190` / `FUN_14060e250` | demo/attract setup (`caseD_4` / `caseD_1`): canned roster from `DAT_14097d618`, then `blk+0x6D04 = G+0x2C & 7` |
| `FUN_14060af70`, `FUN_14062bc80`, `FUN_14073f200` | fixed writes (`0`, `0x11`, `0xB`, …) on non-battle paths |

**The match loader CONSUMES it**: `caseD_5` reads it at `0x14060ed0a`; `FUN_14060c370` case 1 indexes
`DAT_140a6aa80[id]`/`DAT_140a6aa30[id]` to pick the stage POL/TEX AFS entries; `FUN_14060d470` re-reads it
(`CMP byte ptr [RAX + 0x6d04], 0x10`) for the stage-0x10 fix-up. So once a stage bank exists, the byte is
necessarily the stage that bank belongs to.

### The clock-238 observation does not show a mid-match change

`riverraft_river1` (clock 238, byte = 6) has **no stage bank loaded at all** — the POL header at `0x0D82D000` is all
zeros and the TEX bank at `0x0D85D000` is all `0xCD` — and all six fighters are at **HP 0**. It is a pre-load state,
not a battle frame. Also, **`blk` is allocated once per BOOT** (`FUN_140607b50`), so two dumps sharing a `blk`
address share a *boot*, not a *match*; equal allocation is not evidence of one continuous match.

### But there IS a real counter-example, and it is not the one we were looking for

`receipt-20260903-165128`: `blk+0x6D04 = 1`, **all six fighters at HP 144**, and the resident stage bank is
**stage 0**. The 17 stage TEX files are byte-unique (checked), so this is not aliasing. Its mode bytes are
`(1,1,1)` — a **character-select** frame. That is the hazard window: the cursor has moved to the next selection
while the previous match's bank is still resident, and **health reads full**, so a health-only gate can fire there.

### The predicate — and it already exists

Across all 16 dumps on disk:

| frames where `blk+0x3CB8[0..2] == (2,1,2)` | `blk+0x6D04` matches the resident bank |
|---|---|
| **13** | **13 / 13, zero mismatches** |

Both frames whose stage byte disagrees with the resident bank are **non-battle** (`(1,1,1)` select, and `(2,1,1)`
pre-load). **Health alone does not separate them** — the select frame reads HP 144.

That triple is not a new invention: it is already the runner's own C1 self-check ("mode bytes `blk+0x3CB8[0..2]`
== 2,1,2", `RECEIPT-RUNNER-GATE1` §1 step 5). **`blk+0x6D04` is authoritative exactly when the battle-mode predicate
holds.** A second, independent confirmation is available for free if wanted: the resident stage TEX at DC
`0x0D85D000` matches AFS `802 + 2*id` byte-exactly, and `*(u32)(DC 0x0D82D000) == 0` means no bank is loaded at all.

**Not implemented here — the agent is the coordinator's lane.** Reported as mechanism + predicate + counter-example.
Also noted: the comment on `harvest.rs:1183` names `blk+0x6D3C` in prose while `STG_OFF` is `0x6d04`; the constant
is right and the prose is wrong.

---

# GATE 4 addendum B — a located arc-coverage gap: auxiliary banks (2026-09-04)

Reported by the SUPERGUN NETCODE lane: ticking an arc-rebuilt anchor faults at **`0x140848FF4`** inside
**`FUN_140848EE0`** with **`RAX = 0xCDCDCDCD`**.

## B1. The fault, decoded to the instruction

```
140848fe2: MOVSXD RAX, dword ptr [RDI + 0x4c]   ; the record SIZE field
140848fe6: ADD    RDI, 0x50
140848ff1: ADD    RDI, RAX
140848ff4: CMP    dword ptr [RDI], 0x0          ; <-- faults
```

`RAX` is **the record size, not a pointer**. Read as `0xCDCDCDCD` it sign-extends to **−842,150,451**, so
`RDI += 0x50 + RAX` jumps ~800 MB backwards out of every mapping and the terminator test faults. `0xCD` is the host
allocation's fill, so the walk had entered DC-RAM the arc build never populated.

## B2. What it is NOT — the four battle banks are innocent

Checked against the live images: `dcram_build.py` reproduces the effects / HUD / common / stage POL **byte-exactly,
including the `0xCD` past each file's end — the live game leaves `0xCD` there too**. Each bank's last model
terminates on a zero PCW inside the final 8 bytes of its file (e.g. effects ends `... 00000000 1c000000` at
`0x0D025EC8`, 8 bytes before `0x0D025ED0`).

A first structural checker flagged every bank's last model as "record header outside the placed file" on all 17
stages. **Those were false positives**: it demanded a full `0x50`-byte header be in-file before reading the 4-byte
terminator, when the walk only reads the PCW. Recorded because the fix looked plausible and was wrong.

It is also **not class E** (`+0x145000`): that region holds no models.

## B3. What it IS — class X, an auxiliary bank the loader never placed

New tool **`d3dcap/receipt/arc_coverage.py`** routes every System-A node pointer to the region it really lives in
and reports DC-RAM pointers that land outside what the builder places. (`node+0xE8` is **not** a DC-RAM pointer —
`RECEIPT-RUNNER-DCRAM` §4.2: the raft children carry `+0xE8 = parent+0xA8`, i.e. another node's matrix inside
`blk`. Only `+0xA0` can be an arc-coverage gap. A first pass that treated `+0xE8` as DC-RAM produced 27–35 false
"OUTSIDE" hits per anchor.)

On `receipt-20260903-151200-post9`: **5 drawn list-5 nodes** reference `0x0D2BB1A0..0x0D2CE5C8` — the **RESULTS
bank**, one of the class-X regions `RECEIPT-RUNNER-DCRAM` §1.2 lists and `dcram_build.py` never placed.

## B4. The fix — CONFIRMED from the loader, not from a dump match

`FUN_14060c370` **case 10**:

```
G+0xAD == 1 -> POL 0x36A (874)  TEX 0x36B (875)
G+0xAD == 2 -> POL 0x36C (876)  TEX 0x36D (877)
else        -> POL 0x34D (845)  TEX 0x34E (846)
FUN_14060dcf0(POL, 0x0D2BB000); FUN_14060dcf0(TEX, 0x0D2E9000); FUN_14060d770(0x0D2BB000, 0x0D2E9000)
```

An independent archive match against the live post9 image returns AFS **874** at `0x0D2BB000` — code and data agree.

**Placement is DEMAND-DRIVEN**, and that detail matters: `G+0xAD` is only meaningful when case 10 last ran. At a
battle anchor it reads 0 (the default pair) while the bytes resident at `0x0D2BB000` are whatever the previous
results screen left — measured as variant 1 on river_b and stage9. Placing it unconditionally made the image
diverge from live by 73,510 B on anchors that never read it. The builder therefore places it only when the anchor's
own nodes point into it. (Same staleness class as `blk+0x6D04`, §A5.)

| anchor | results bank | `UNEXPLAINED` |
|---|---|---|
| post9 (references it) | placed, AFS 874/875, POL **131 B** / TEX **3,150 B** residual, class B | only `PL3/232` — the documented post-match clobber of PL slot 1 (pos 3) by the results screen, Gate 0 finding (b) |
| stage 9, river_a, river_b, 000941 | not referenced → not placed | **NONE** |

Regression: the arc-built stage-9 image still reproduces the CONFIRMED dump-based run **300/300 blk dumps, 0 differ**.
Coverage sweep over all 16 dumps: **OUTSIDE 0** everywhere except §B5.

## B5. Still open — and this bounds Gate 3 and Gate 4 §2

**`receipt-20260903-165128`** (a character-select frame) has **8 drawn list-5 nodes** referencing
`0x0D6CC068..0x0D6D9C38` — the bank `FUN_14060c370` case 0xD loads at `0x0D6CC000` (POL AFS 851, **INFERRED** from
an archive match). Not placed. Six further aux banks exist at `0x0D25C000`, `0x0D3A2000`, `0x0D4CE000`,
`0x0D720000`, `0x0D7A9000`, `0x0D7CC000` (POL AFS 839 / 847 / 849 / 853 / 855 / 843, all INFERRED by archive
match); they are not placed because `FUN_14060c370` loads them through a shared tail whose **TEX** address this pass
did not trace, and `FUN_14060d770` needs both addresses.

**Gate 4 §2 said classes E, L and X are "proven unread". That claim must be narrowed: it was proven on four BATTLE
anchors. Class X is demonstrably READ on post-match and character-select anchors.** Gate 3's "a receipt runs from
the arc alone" holds for the battle anchors gated; it is not unconditional, and this is the located exception.

Note the poison test could not have caught this by luck: `0x5A5A5A5A` is a *positive* PCW so the walk terminates,
while `0xCDCDCDCD` is negative and crashes — the two arms are not equivalent for a record walk.

## B6. For the netcode lane

Run this on the stage-8 anchor; it names the region in one command, with no rebuild:

```
python C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\receipt\arc_coverage.py <their run dir>
```

Every `OUTSIDE` line is a located gap. If they land in `0x0D6CC000..` it is the case-0xD bank above; if somewhere
else, the address identifies which `FUN_14060c370` case must be added.
