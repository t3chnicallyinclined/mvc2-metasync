# RECEIPT-RUNNER-GATE3 — the loader path replaces the memory dump: DC-RAM is rebuilt from the user's own arc (2026-09-04)

Owner lane: SUPERGUN ENGINE. Workstream: `docs/WORKSTREAM-RECEIPT-RUNNER.md` §4 step 3; design of record
`docs/RECEIPT-RUNNER-DCRAM.md` §2 (region map, PL slot recipe, load-time patches). Prerequisites: Gate 1
(`docs/RECEIPT-RUNNER-GATE1.md`), Gate 2 (`docs/RECEIPT-RUNNER-GATE2.md`). Deliverables:
`d3dcap/receipt/dcram_build.py`, seed `maplecast-flycast/tools/re_kb/118_receipt_runner_gate3.surql`.

## RE METHOD (locked; `docs/RE-METHOD.md`)

1. Port the SH4 annotations to the Steam binary by function matching.
2. Seed with unique constants, then propagate along the call graph.
3. Translate globals through the block map before comparing reference sets.
4. Tag CONFIRMED versus INFERRED, and store the pairs as edges in the knowledge graph.

Step this document is at: **4**. Steps 1–3 were done by decompiling the seven loader routines below through the
Ghidra `:8080` bridge on `mvc_dump.bin` (seeded on `0x0C420000`, `0x00150000`, `0xC10`, `0xC50`, `0xC90`, `0x810`
and the per-slot address tables), and by reading roster / stage / assist out of the anchor's `blk` through the
block map (`blk+0x3DB8 + s*0x738`). Tags: **CONFIRMED** = reproduced by a byte gate on real images; **INFERRED** =
read in the disassembly, gate-consistent; **UNKNOWN** = not located. No time estimates anywhere. BYOR: the tool
reads the user's own `game_50.arc`; every output is game-derived and gitignored.

## 0. Result

**GATE 3: PASS.** The runner no longer needs the captured 32 MB `pre/dcram.bin`. It builds the DC-RAM battle image
from the user's own `game_50.arc` plus the anchor's `blk`, and the frame function cannot tell the difference.

### G3.1 — arc-built image vs the live dump (offline byte gate)

`python d3dcap/receipt/dcram_build.py <run> --gate` classifies every differing byte. **Zero bytes that the loader
places differ**, on two independent dumps with different stages, different rosters, and a duplicated character:

| dump | roster (slot order) / stage | loader-placed bytes differing |
|---|---|---|
| `d3dcap/ttd/runs/receipt-20260903-stage9-anchor` | [42,23,52,12,44,46], stage 9 | **0** (`UNEXPLAINED: NONE`) |
| `d3dcap/ttd/runs/20260903-000941` | [42,52,44,23,52,53], stage 0x0B (cid 52 twice, assist 0 and 2) | **0** (`UNEXPLAINED: NONE`) |

Covered by that zero: 6 PL slots × 11 AFS files each, the four banks' POL **and** TEX with relocation and TCW
assignment applied, and the twelve HUD portrait / name-plate pages.

Everything that still differs falls into five named classes (stage-9 figures):

| class | bytes | what |
|---|---|---|
| **B** | 1,708 | bank POL: per-frame vertex/UV rewrites, the at-draw HUD TCW low byte, and the spawn-time model patches of §3 (effects 197 · HUD 73 · common 1,366 · stage 72) |
| **E** | 39,261 | the six `base+0x145000` engine-written PL regions (`fighter+0x1F0`; writer `FUN_140612180`) |
| **L** | 393,281 | leftovers past the end of each file the loader placed (the previous character / previous scene) |
| **R** | 21,347 | the tile buffer `0x0CE60000..0x0CE65000`, rebuilt by the tick itself |
| **X** | 6,462,704 | banks that are not on the battle read set at all (select / VS / result / ending / staging) |

### G3.2 — the runner over the arc-built image (the sim gate)

`rr_runner.exe` on the arc-built `dcram.bin`, everything else unchanged, compared against the CONFIRMED Gate-2
dumps (`%TEMP%\rrcap_runner\gate2_300`, themselves byte-exact against the p-code oracle):

| run | ticks | blk | gs_out | ctx_out | exe_dat_out | ggpo_out |
|---|---|---|---|---|---|---|
| stage-9 receipt, clock 1716→2016 | 300 | **300/300 byte-identical** | equal | equal | equal | equal |
| `20260903-000941`, stage 0x0B, idle | 20 | **20/20 byte-identical** | equal | 128 B (see §5) | equal | — |

Classes B, E, L, R and X were **absent** from the image in both runs. So none of them is on the sim read path for
these two stage/roster pairs.

### G3.3 — Gate 2 re-run over the arc-built image (the tape gate)

`runner_tape_gate.py --run <arc run> --live packs/local_stage9/tape.json.gz --ticks 300`:

| image | result | classes |
|---|---|---|
| captured dump (baseline, re-run today) | **PASS** | P 14, A 1281, F 1, 0 unexplained |
| arc-built + the 1,708 class-B bytes carried | **PASS** | P 14, A 1281, F 1, 0 unexplained — and the runner tape is **byte-identical** to the baseline's (every top-level key equal, `anchor`/`anodes`/`aobjs` included) |
| arc-built, nothing carried | FAIL | only `anodes.obj` / `aobjs` / `aobjs_n` differ (442 + 344 unexplained); every other key equal |

**The Gate-2 baseline had to be re-run.** `rr-tape.exe` was rebuilt on 2026-09-04 by another lane and the object
cache now interns one object per phase (`aobjs` 124 → 597). Gate 2's published `A 620` is therefore not comparable
with today's numbers; the like-for-like figure is **A 1281 on both arms**. Always re-run the baseline with the
same `rr-tape.exe` binary as the arm under test.

## 1. What the builder replays (all CONFIRMED, decompiled 2026-09-04)

| routine | what it does to DC-RAM |
|---|---|
| `FUN_14060dcf0` | AFS entry to DC address memcpy. No file I/O: the archive image lives at `ctx[0]`. |
| `FUN_14060d100` (== SH4 `loc_8c031fa0`) | PL slot loader: 10 AFS files at `0x0C420000 + pos*0x150000` per `RECEIPT-RUNNER-DCRAM` §2.1 |
| `FUN_14060c370` case 6 (== `loc_8c032cbe`) | the 32 KB per-character tail (AFS `3+cid`, cids 25/26 to 27) at `+0x148000` |
| `FUN_14060d770` (== `loc_8c0322d4`) | POL relocation, §2 |
| `FUN_14060d8f0` | builds the **host** bank struct from a relocated POL. **Writes no DC-RAM** (see §4) |
| `FUN_140844dc0` (== `loc_8C122FD0`) | TCW assign: the only DC-RAM write is `rec+0xC = *(ctx+0x1e0098) + rec+0x20` |
| `FUN_14060d470` | stage bank register (base `0xC10`) + the stage-0x10 ISP/TSP fix-up |
| `FUN_14060d560` (== `loc_8c032696`) | HUD bank (base `0xC90`) + the twelve portrait / name-plate pages |
| `FUN_14060d080` / case 5 | effects bank (base `0xC50`) / common bank (base `0x810`) |

Slot map: `DAT_140a6ab80 = {0,3,1,4,2,5}` read as **slot -> pos**. (Its inverse `{0,2,4,1,3,5}` is what
`pl_rebuild.py` iterates as **pos -> slot**; both are correct, they are not the same table. Getting this backwards
mis-places four of the six slots and is the one mistake this gate made and caught.)

## 2. `FUN_14060d770` — the relocation, read in full (CONFIRMED)

```
p     = host(polDC)                      // int* over the copied POL file
n     = p[1]                             // model count
delta = p[0] - polDC - 0x10              // NEGATIVE of the bank delta
p[2] -= delta                            // texHdrs pointer
p[0] -= delta                            // model table pointer
tbl   = p[0]
for i in 0..n:  tbl[i] -= delta          // (unrolled 16 dwords per iteration in the decompile)
th    = p[2]
first = *(u32*)(th + 8)                  // the FIRST record's loc, captured ONCE
while *(u16*)th != 0:                    // terminator = width == 0
    *(u32*)(th + 8) -= (first - texDC)
    th += 16
```

Measured deltas on the live image (each is `dst + 0x10 - POL[0]`): stage `+0x98D000` (`0x0CEA0010 -> 0x0D82D010`),
effects `+0x130000` (`0x0CED0010 -> 0x0D000010`), HUD `+0x202000` (`0x0CE80010 -> 0x0D082010`), common `+0x246000`
(`0x0CE80010 -> 0x0D0C6010`). This corrects `RECEIPT-RUNNER-DCRAM` §2.2's `delta = *POL - POL - 0x10` phrasing: the
value is subtracted, and the `- 0x10` matters (POL[0] is `dst+0x10`, not `dst`).

Record walk, used by `FUN_140844dc0` and by the NaomiLib iterator alike: first record = `model+0x18`;
`next = rec + 0x50 + *(i32*)(rec+0x4C)`; terminator = the signed word at `rec+0` is `>= 0`;
`rec+0x0` PCW, `rec+0x4` ISP, `rec+0x8` TSP, `rec+0xC` TCW, `rec+0x20` texIndex, `rec+0x4C` payload size,
vertices at `rec+0x50` stride `0x20`.

## 3. The 1,708 class-B bytes: two spawn-time mechanisms and a lot of dead stale data (CONFIRMED)

Every differing bank-POL byte was mapped to `(model index, record index, offset-in-record)` and then matched
against the anchor's own pool-node lists (`blkstate.anodes()` over `blk`, `+0xA0` object / `+0xE8` model):

| residual | models | mechanism | bound to a live node in the anchor? |
|---|---|---|---|
| `rec+0x8 &= 0xFFFE7FFF` (clears `0x18000`) | effects 71, 73, 74 | **`FUN_140619800`** | **yes** — exactly the list-6 nodes |
| `rec+0x8` OR `0x2000` | effects 20 | **`FUN_140660f40`** | **yes** — exactly the list-7 node |
| vertex `x/y/z/nx/ny/u/v` floats | effects 77, 79, 80, 85, 86, 165, 167; common bank; HUD 67–78, 116–119 | per-frame in-place rewrites (`FUN_140797690` UV, HUD bar colours) | mixed |
| `rec+0xC` low byte `0x92 -> 0x93/0x94/0x95` (31 sites) | HUD 0–39 | at-draw combo-counter patch `FUN_140653a70` | — |
| vertex `x/z/ny/u` and `y/nx/v` | stage POL at `0x0D853158` (TCW `0xC12`) and `0x0D855800` (TCW `0xC1C`) | list-5 prop callbacks, regenerated every frame | yes |

`FUN_140619800` has ~20 callers, all effect/prop **node-init** routines — it fires at node spawn, not at bank
load, and its effect **persists** in DC-RAM. That is why a load-time arc build cannot produce it: the anchor is
mid-match and those nodes spawned before it. Residuals on models that are **not** bound to any live node are the
leftovers of dead effects and are overwritten before use.

Consequence for the tape (§0 G3.3): the harvest interns each world object the first time it sees it, at **tick 0**,
before the frame's callbacks have run. With an arc image that first sighting is the pristine arc bytes — never a
real phase. This is the *same* class-A artefact that already makes every live tape carry stale animated-prop
vertices (`RECEIPT-RUNNER-GATE2` §3.2); it is not a loader defect. Two ways out, both outside this gate:
pose props from keys (Track R), or do not intern tick 0 in the runner path.

## 4. Corrections to the documents of record

1. **`RECEIPT-RUNNER-DCRAM` §2.3, "`FUN_140619720` on HUD models 0..3"** — not a patch. `FUN_140619720(model, dst)`
   *copies out* the first `0x10` bytes of every record into the caller's array (`dst += 0x10` per record); it writes
   **zero** DC-RAM bytes. It is a save of the record headers, INFERRED to exist so the at-draw TCW patch can be undone.
2. **`RECEIPT-RUNNER-DCRAM` §2.3, "stage 0x10 models 0..7"** — actually **models 1..8**. `FUN_14060d470`'s counter
   starts at `-1` and is tested (`uVar3 < 8`, unsigned) *before* its post-increment, so model 0 is skipped.
3. **Slot map** — see §1. `DAT_140a6ab80` is slot -> pos; `pl_rebuild.py` iterates the inverse.
4. **`PORTRAIT-PAGES-GHIDRA`** — the character-DAT portrait rule now has a **raw-byte gate against live game
   memory**, not only the capture-derived library: all twelve `0xC9A..0xCA5` pages (12 x `0x800` B) are byte-exact
   on both dumps. Cross-check: the same `(cid, assist)` yields the same live page in a different slot on the other
   dump, and cid 52 appearing twice with assist 0 and assist 2 picks pages 1 and 3 correctly.
5. **`RECEIPT-RUNNER-DCRAM` §2.2 relocation formula** — see §2.

## 5. Falsification arm: the `ctx_out` residual is the RUNNER's, not the build's (CONFIRMED)

The training-stage arm showed `ctx_out` differing by 128 B = 32 dwords at stride `0x130` in
`ctx+0x107864..0x108EF4`, while every `blk` dump, `gs_out` and `exe_dat_out` were byte-identical. Carrying classes
S, E and R made no difference; carrying the **entire live DC-RAM** made no difference. Two runs of the runner on
the *same captured dump image* differ by the same 128 B. So this is run-dependent host state — the same family as
`RECEIPT-RUNNER-GATE1` §3.5 (ctx page-table records `memcpy`-d from a stack buffer whose `+0x6C/+0x114` fields hold
leftovers), never read by the tick per `FRAME-READSET` §3.4. **Exclude this range from any ctx byte gate.** It is
intermittent: on the stage-9 300-tick receipt run `ctx_out` was byte-equal between the two arms.

## 6. Bonus: ctx reduces from 4 MB to ~5.2 KB (CONFIRMED, 300-tick gated)

The runner needs only three pieces of the 4 MB NaomiLib context; everything else may be **zero**:

| range | bytes | what |
|---|---|---|
| `ctx+0x00..0x18` | 24 | the three self pointers: `[0]` AFS image, `[1]` DC-RAM base, `[2]` blk — all reconstructible |
| `ctx+0x1E0030..0x1E31CC` | 0x319C | the texture-slot table — **the battle anchor already carries exactly this** |
| `ctx+0x1F80A0..0x1F81C0` | 288 | NaomiLib matrix-stack state: mode `+0x1F80A4`, current index `+0x1F80A8`, two 4x4 matrices, storage pointer `= blk` at `+0x1F81B0`, capacity `0x40/0x40` at `+0x1F81B8/BC` |

Gated on the 300-tick stage-9 receipt: keeping `ctx+0x1F8000..0x1F9000` -> blk **300/300**; keeping only
`0x1F80A0..0x1F81C0` -> **300/300**; keeping only `0x1F80A0..0x1F8100` **or** only `0x1F8100..0x1F81C0` -> **FAILS at
tick 1** (first difference `blk+0x3EDC` = fighter 0's walker field `+0x124`). So the whole 288 B is required.
That 288 B is the one field that would make the anchor ctx-free. **Agent-lane item — not changed here.**

## 7. The intended end state: call the game's own loaders

`dcram_build.py` is a faithful Python re-implementation, and it gates clean. The correct long-term shape is to
have `rr_runner.exe` call the game's own `FUN_14060c370(1)/(2)/case 6/(4)`, `FUN_14060d100(f,s)` and
`FUN_140612180(f,s)` with `ctx[0]` pointed at the inflated arc, per the standing rule to port proven code verbatim
rather than re-implement it (`RECEIPT-RUNNER-DCRAM` §2.3 already gives the call order, and warns to run **none** of
`FUN_14061e170` pool init / `FUN_14061c6e0` camera / `FUN_140620200` stage props on an anchored `blk`). That path
**closes class E for free**, because `FUN_140612180` is the writer of the `+0x145000` region. It is the intended
end state, not a nice-to-have; it is simply not urgent while the Python build gates at zero.

## 8. CONFIRMED / INFERRED / UNKNOWN after Gate 3

| item | tag |
|---|---|
| Every byte the loader places is reproducible from `game_50.arc` + the anchor's `blk` | CONFIRMED (two dumps, `UNEXPLAINED: NONE`) |
| The arc-built image ticks byte-identically to the captured image: blk 300/300 + 20/20, gs/exe/ggpo equal | CONFIRMED |
| The arc-built runner tape == the dump-based runner tape, byte for byte, with the 1,708 class-B bytes carried | CONFIRMED |
| The class-B bytes are (a) two spawn-time model patches on models bound to live nodes and (b) stale/at-draw data on models that are not | CONFIRMED |
| The portrait / name-plate rule against live DC-RAM bytes | CONFIRMED |
| `ctx` minimal set = `0x00..0x18` + slot table + `0x1F80A0..0x1F81C0` | CONFIRMED (300 ticks, both halves individually falsified) |
| The 128 B `ctx_out` residual is runner nondeterminism, not the build | CONFIRMED (two runs, same image) |
| Class **E** (`+0x145000`, 12 KB x 6) is not read | **measured** on two stage/roster pairs (300 + 20 ticks), **NOT proven** for all stages. It is a deterministic function of `(cid, Dat_GFX2)`; `FUN_140612180` writes it **and `blk+0x32BF4`**, so replaying it on an anchored `blk` is not free |
| Classes **L** and **X** are never read | INFERRED from `FRAME-READSET` §3.2 + the 320 ticks of G3.2 |
| Stages other than 9 and 0x0B | UNKNOWN — untested. Carnival (3/0xC) morph and River Raft (7/0x10) are untried, and the stage-0x10 ISP/TSP fix-up path in `dcram_build.py` has **never executed** |
| Online (rollback > 0) and HUD-heavy (> 96 node) pairs | UNKNOWN — inherited from Gate 2 |
| `FUN_140660f40`'s caller | UNKNOWN (the site is CONFIRMED, the spawn path is not traced) |

## 9. Commands

```
rem build the image and classify every difference against the live dump
python C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\receipt\dcram_build.py C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\runs\receipt-20260903-stage9-anchor --gate --out %TEMP%\rr_dcram_arc.bin

rem the sim gate: build into a run dir whose other files come from the anchor, then tick and diff blk
python C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\receipt\dcram_build.py <run> --carry-s --out <rundir>\pre\dcram.bin
C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\receipt\runner\rr_runner.exe --pre <rundir>\pre --out %TEMP%\rr_gate3\arm1 --ticks 300 --inputs %TEMP%\rrcap_runner\gate2_300\inputs.txt

rem the tape gate (ALWAYS re-run the baseline with the same rr-tape.exe)
python C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\receipt\runner\runner_tape_gate.py --run <rundir> --live C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\replay\packs\local_stage9\tape.json.gz --ticks 300 --only-diffs
```

## 10. Address index (new or corrected in this document)

`FUN_14060d770` POL relocation (`delta = POL[0] - dst - 0x10`, subtracted) · `FUN_14060d8f0` host bank struct
(`bank[0x160]` count, `bank[0x161]` texHdrs; no DC-RAM write) · `FUN_140844dc0` TCW assign (`rec+0xC` only) ·
`FUN_14060d470` stage bank + stage-0x10 fix-up on models **1..8** · `FUN_140619720` record-header **save**, not a
patch · `FUN_140619800` `rec+0x8 &= 0xFFFE7FFF` at node spawn · `FUN_140660f40` `rec+0x8` OR `0x2000` at node spawn ·
`FUN_140612180` writer of `fighter+0x1F0` (`base+0x145000`) and of `blk+0x32BF4` · `DAT_140a6ab80 = {0,3,1,4,2,5}`
slot -> pos · `DAT_140a6aac8 = {0,3,1,4,2,5}` slot -> HUD record k · `DAT_140a6aac4 = {1,0,3,0}` assist -> page ·
`DAT_140a75240[cid]` cell count read by `FUN_140612180` · ctx `+0x1E0098` bank base · ctx `+0x1F80A0..0x1F81C0`
matrix-stack state · ctx `+0x107864..0x108EF4` run-dependent page-table records (exclude from gates).

Seed: `maplecast-flycast/tools/re_kb/118_receipt_runner_gate3.surql`
(backup `re_kb_data/_exports/re_kb_20260904-145853_pre118.surql`; 46 statements, 0 failed).
