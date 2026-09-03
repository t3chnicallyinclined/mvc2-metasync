# RECEIPT-RUNNER-RE — the thin native wrapper that replays a battle-frame receipt without the shell (2026-09-03)

Owner lane: senior-re-generalist (process + rigor). Deliverable of the "final architecture" planning task: a falsifiable
workstream for a **thin native runner** that maps the user's own unpacked Steam MvC2 image, restores the agent's
battle-frame anchor, ticks the game's frame function once per recorded input pair, and exposes `blk` + `ctx` + DC-RAM
to the existing emitter so the runner's TAPE equals the live agent's TAPE frame by frame. No Steam, no window, no D3D.

## RE METHOD (locked; docs/RE-METHOD.md)

1. **Port the SH4 annotations to the Steam binary by function matching.**
2. **Seed with unique constants, then propagate along the call graph.**
3. **Translate globals through the block map before comparing reference sets.**
4. **Tag CONFIRMED versus INFERRED, and store the pairs as edges in the knowledge graph.**

Step this document is at: **4** for the frame/read-set work it builds on (seeds 104/106/111), **2→4** for the new
material below (the DC-RAM writers were found by seeding on the constant `0x150000` and by walking the node callbacks
from the live block, then classified; every new pair/offset goes into the seed sketched in section 9).

Tags: **CONFIRMED** = read on both sides or reproduced by a numeric gate on real bytes; **INFERRED** = decompile- or
gate-consistent only; **UNKNOWN** = not located. Every address is Ghidra (`mvc_dump.bin`, bridge :8080) or a file:line
in this repo; every measurement below was taken on `d3dcap/ttd/runs/20260903-000941/{pre,post}` (offline training
match, stage 0x0B, roster cids 42/52/44/23/52/53, clock 2239 → 2476) unless stated. No time estimates anywhere.

Dead ends that stay dead (do not reopen): TTD/WinDbg time-travel on this title (`docs/TTD-FRAME-TRACE.md` s0: the exe's
runtime layer hooks `NtResumeThread`); driving the char-select shell by replaying cursor inputs (`docs/RECEIPT-PLAYER-G.md`);
a blk-only anchor (same doc, AV at `0x1406083be`).

---

## 0. Answer in one page

| question | answer | tag |
|---|---|---|
| Does the frame WRITE DC-RAM outside `blk` other than the tile buffer? | **Yes, in place into the arc-loaded bank objects** — and every such write is a **regeneration**, not carried state: (1) animation callbacks copy each vertex from a pristine *source* model to the drawn *destination* object (`FUN_1406196e0` sets two cursors; `FUN_140619510/530` read the SOURCE; `FUN_140619680/6a0` write the DESTINATION), computing position/UV from phase counters that live **in blk** (`node+0x30`, `node+0x32`); (2) the combo counter patches the TCW of the SHARED HUD model header immediately before each draw (`FUN_14060d8d0`, `docs/PARTS-LIST0C-GHIDRA.md:90,113`); (3) the tile buffer `0x0CE60000..` is rebuilt every frame (`FUN_140614210`). Measured: 237 frames change **12,939 B of the 32 MB image in 13 ranges**; outside the tile buffer that is **50 B of u/v floats in the effects POL and 10 TCW low bytes in the HUD POL**. PL slot images: **0 bytes** changed. | CONFIRMED (diff + decompile), section 1 |
| So which of (a)/(b) in the task? | **(a)**: meshes are regenerated from blk state + static arc content. The static content is the *user's AFS entry* plus a **deterministic load-time rebase** (pointer/TCW rewrite by `FUN_14060d770` / `FUN_140844dc0`, TSP bit clears by `FUN_140619800` in the stage initialisers) — measured 0.9–2.5 KB per POL bank, 0 B per TEX bank. One residual hypothesis **H1** remains to be gated (section 1.5): "a node is never drawn in a frame whose callback did not run earlier in the same frame". If H1 held false for some node class, the anchor would additionally have to carry that object's bytes. | (a) CONFIRMED for the traced classes; H1 INFERRED (call order) |
| What must the runner load? | **(i) from the anchor:** `blk` 0x33B18, `game_state` page, exe page `0x142edf300..0x700`, ctx slot table (= agent 0.3.47 payload, `reader.rs:1529`), **plus** the arena base `gs+0x000`, blk pointer `gs+0x1B0`, staging `gs+0x208` (already inside the gs page). **(ii) from the user's arc via the game's own loader path:** all banks (`FUN_14060c070` boot list, `FUN_14060c370` case 1 stage, cases 5/9 match) through `FUN_14060dcf0(entry, dcaddr)` which memcpy's from the **in-memory AFS image at `ctx[0]`** — no file I/O; the six PL images = AFS `209+cid` (CONFIRMED byte-exact six of six, twice) + the loader tail (builder INFERRED: the async queue `FUN_14060d980 → FUN_14060dd40`, the only function carrying `0x150000`). **(iii) reconstructed each frame by the game code itself:** tile buffer, `*(gs+0x208)` staging, ctx TA records/pages, `0x142eed950` scratch, `game_state+0x4F4..0x5EC`. | section 1.6 |
| Tick entry | `FUN_140118950(&DAT_142d10b90, inputs[4], 0)` with seat map forced to `{0,1,-1,-1}` (contract C2), one call per frame. Equivalent direct path = the offline loop's sequence (section 3.2, decompile of `FUN_140039de0`). | CONFIRMED (both gated) |
| Master gate | runner TAPE == live TAPE, per frame, per column, on an **offline rollback-0 match recorded by agent 0.3.47**; tool = `tape_vs_dump_gate.py` with the runner's per-frame images standing in for the shim dumps (section 3.4). Online matches: the runner replays the CONFIRMED ring inputs and can only be gated against tape rows that were not rolled back (section 5.6). | gate named; not yet run |
| Go / no-go on "cause proven" | The team has PROVEN (numerically, on one host/one roster/one stage) that the frame is deterministic and what it reads. It has **not** yet proven a receipt end to end: no tape and same-match dump pair exists (`docs/DETERMINISM-CONTRACT.md` s6c). Shortest path in section 8. | — |

---

## 1. The DC-RAM write set of the frame — measured, classified, mechanised

### 1.1 Pre→post diff of the 32 MB DC-RAM image (237 frames)

Script: scratchpad `dcram_diff.py` (numpy byte compare, ranges coalesced at a 256-B gap). 12,939 bytes differ.

| DC range | span | differing | region (`emu_frame.DC_REGIONS`) | writer | class |
|---|---|---|---|---|---|
| `0x0CE6000A..0x0CE641A1` | 16,791 | 12,879 | Texture_Decompress_Buffer | `FUN_140614210` ← `FUN_140612430` (tick) | rebuilt every frame (FRAME-READSET s4.5); prior content irrelevant (`dcram_tiletab_prev` perturbation: zero-filled → blk/ctx/staging identical, DETERMINISM-CONTRACT s1.1) |
| `0x0D00C620..0x0D00C687` | 103 | 30 | effects bank 0xC50 POL (AFS 799) | `FUN_140625920` (list-6 node callback; nodes `blk+0x10DD8/0x112D8/0x11558`, objects DC `0x0D00B708/0x0D00BB00/0x0D00B8F8`) | **u,v floats of TA vertices** rewritten (1.2) |
| `0x0D00D3E8..0x0D00D44F` | 103 | 20 | same | same | same |
| ten single bytes `0x0D082E6C … 0x0D0892FC` | 1 each | 10 | HUD bank 0xC90 POL (AFS 835) | `FUN_14060d8d0` header patch from the combo counter `FUN_140653a70` | **TCW low byte** `0xC92..0xC95` = `0xC92 + count − 1` (PARTS-LIST0C s3) |

Nothing else in 32 MB moved: not the six PL slots (`0x0C420000..0x0CC00000`), not the stage POL/TEX, not the TEX banks.

Decoded bytes (scratchpad `dcram_sites.py`): the effects sites are 32-B vertices `x,y,z,nx,ny,nz,u,v` — e.g. the vertex at
`0x0D00C608` is `(6.617, −6.617, −0.108, 0, 0, 1.0, u, v)` with `u 0.245→0.995`, `v 0.255→0.005`; the HUD sites are the
TCW word of a record header (`ISP 0x83000000, TSP 0x2009A45B, TCW 0x00000C95 → 0x00000C93`).

### 1.2 The writers, read in Ghidra (CONFIRMED)

**The object-record iterator API** (all tiny; decompiled 2026-09-03):

| routine | body | meaning |
|---|---|---|
| `FUN_1406196e0(src, dst)` | `DAT_142eee568/570 = src+0x18; DAT_142eee578/580 = dst+0x18; DAT_142eee588 = 0` | open two cursors: SOURCE model, DESTINATION object |
| `FUN_140619580()` | walks 0x50-B record headers and 0x20-B vertices (count = `hdr+4`, ×3 unless flag 0x10), advancing BOTH cursors in lock-step; returns −1 at end | next vertex |
| `FUN_140619510(out12)` | `*out = *DAT_142eee568` (12 B) | **read SOURCE** position x,y,z |
| `FUN_140619530(&u,&v)` | `u = *(SRC+0x18); v = *(SRC+0x1C)` | **read SOURCE** u,v |
| `FUN_140619680(in12)` | `*DST = in (12 B); *DST |= 1` | **write DESTINATION** position, set bit-0 marker on x |
| `FUN_1406196a0(&u,&v)` | `*(DST+0x18)=u; *(DST+0x1C)=v; *(DST+0x1C) |= 1` | **write DESTINATION** u,v, set bit-0 marker on v |
| `FUN_140845150(a)` | `DAT_142ef0ac0[a]` | sin table by u16 angle |

The bit-0 markers are what `FUN_1408482a0` clears when it consumes a vertex (`PARTS-LIST0C-GHIDRA.md:40,104`): the
consumer clears them in its own copy in ctx, not in DC-RAM (the record is copied by `FUN_1408436a0`; DETERMINISM s3.4
lists no dcram write by the render half).

**`FUN_140625920`** (capstone on `pre/exe_image.bin`, undefined in Ghidra): `[node+0x170] = G+0x98` (the blackout byte —
these list-6 quads draw only during a super blackout), a state machine on `[node+0x37]`, counter `[node+0x32]++` with wrap
at 0xA0 or 0x28, then `FUN_1406196e0(bankTable[[node+0x36]], [node+0xA0])` and, per vertex until `FUN_140619580` returns
non-zero: `v_dst = const − counter×step + v_src` via `FUN_140619530` → `FUN_1406196a0`. **Source = a bank model, destination
= the node's object; every input is either static arc content or a blk field.** It also allocates child list-6 nodes
(`FUN_14061dbe0(0,6,1)`, `+0xA0 = *(DAT_142edf560+0x528)`, `+0xF0 = 0x821`) and writes `0xC71C4000` into `obj+0x30`.

**`LAB_14064cb20`** (the animation callback of stage-5 prop 1, set by `FUN_14064ccd0`; capstone): `[node+0x30]++` wrap 0x168
(360), `[node+0x32]++` wrap 0x7D0 (2000); `FUN_1406196e0(PTR_DAT_142edf588[2], [node+0xA0])` — **source = stage POL model 2,
destination = model 1 (the drawn one)**; per vertex: `y_dst = sin(angle(counter+30·k))×k1 − k2` (absolute, via `FUN_140845150`),
`u_dst = u_src + counter×k3`. This is the "smooth per-frame vertex delta" of the animated props: **a function of two u16
phase counters in blk and the pristine sibling model**. It runs when `[node+4] == 0`.

**`FUN_140654790`** (training backdrop list-6 callback): writes only node fields (`+0x50/+0x54/+0x58/+0x6C/+0x74/+0x90`)
from the owner fighter; no DC-RAM write.

**`FUN_140619800(model)`** (called by every stage initialiser on the destination model): clears bits `0x18000` of the TSP
word (`rec+8`) of every record — a **load-time** mutation of the bank bytes.

**Where the callbacks run:** `FUN_14061e520(L)` = `for node in list L: (*(node+0x18))(node)`; its 15 call sites are in
`FUN_1406283a0` (lists 3,4,2,5,6,10,7,8,9 in that order), called from `FUN_14060e3f0` (← `FUN_140611090`) and
`caseD_7` of the match state machine. `FUN_140611090` itself is reached only through a dispatch-table entry
(`DATA 0x140a6bf58`; sibling `FUN_140611040` at `0x140a6bf38`), so its parent is not read. What IS established: the pass executes
inside the tick (FRAME-READSET s3.6 lists `FUN_14061e520/560` with 178/5 blk accesses), and `FUN_14061e560` builds the sorted handle
array `blk+0x2F4D0` that the sprite walker consumes (STAGE-DRAW s1) — so it runs **before** the walker. **INFERRED** that it precedes
the whole render half (`FUN_14060b960`); the trace order test in 1.5 settles it.

### 1.3 Load-time state of the banks vs the pristine AFS entries (measured, scratchpad `bank_vs_afs.py`)

`rip_texbank.load_afs()` on the user's `game_50.arc` (ARC v7 → zlib → IBIS → AFS at +0x40, 890 entries) vs `pre/dcram.bin`:

| region | AFS entry | size | bytes differing at clock 2239 | what differs |
|---|---|---|---|---|
| effects POL `0x0D000000` | 799 | 0x25ED0 | 1,237 in 224 ranges (post: 1,287 = +50 from 1.1) | model-table offsets → DC addresses; record TCW `0x4C` → `0x00000C5E` (= 0xC50 + texIndex) |
| effects TEX `0x0D026000` | 800 | 0x5B800 | **0** | — |
| HUD POL `0x0D082000` | 835 | 0x164E8 | 862 | same rebase; TCW `0x08` → `0xC92..0xC95` (incl. the header patch residue) |
| HUD TEX `0x0D099000` | 836 | 0x1E000 | **0** | — |
| common POL `0x0D0C6000` | 837 | 0x1E5A8 | 2,505 | rebase; TCW → `0x810 + idx` |
| common TEX `0x0D0E5000` | 838 | 0x16E000 | **0** | — |
| stage POL `0x0D82D000` | 823 (801+2·0x0B) | 0x27AB0 | 951 | rebase; TCW → `0xC11..0xC14` |
| stage TEX `0x0D85D000` | 824 | 0x104000 | **0** | — |
| PL slots 0..5 (`0x0C420000 + pos·0x150000`, pos order 0,2,4,1,3,5) | 209+cid | 0x10C100..0x1274A0 | **0** (all six) | tail beyond the entry not compared here |

The rebase is the game's own `FUN_14060d770(POL, TEX)` (`docs/TEXTURE-BANKS-GHIDRA.md:40`: "`delta = *POL − POL − 0x10`;
every model-table entry −= delta; every TEX record loc −= firstLoc − TEX") plus `FUN_140844dc0` ("every model record
`TCW = base + texIndex`", same doc line 13). Consequence: **a runner that memcpy's pristine AFS bytes would be wrong by these
bytes; a runner that calls the game's loader path gets them for free.** The `FUN_140619800` TSP clears and the header-patch
residue are produced by the stage initialisers / the combo counter, which also run inside the frame function.

### 1.4 `game_state` and `ctx` over the same 237 frames (scratchpad `dcram_sites.py`)

* `game_state`: 56 B differ — pads `+0x218/+0x228`, frame stamp `+0x768`, `+0x7B0`, `+0x8D4/+0x914/+0x944`, **`+0x968` (0 → 0x1E)**,
  `+0x978/+0x984/+0x994`, `+0x9A8..+0x9E0`, `+0xAA4..+0xAE0`, `+0xB20`, `+0xBA4..+0xBD0`. FRAME-READSET s3.3 lists `+0x964/+0x968`
  as tick READS; Ghidra (`xrefs_to 0x140ac76a8`): written by `FUN_140639200` (`= 0x1E`, in-tick, matched high to `loc_8c059914`),
  decremented by `FUN_140634600` (in-tick via `FUN_140634920` ← `FUN_140619840`, gated `gs+0x520`) and by `FUN_14010d0b0`
  (← `FUN_1400fb840`, reached only through data references `0x140a5ba98/0x140a5bae8` — front-end table; INFERRED shell-side).
  Consumers write HUD text (`DAT_140cd6358[..] = 0x8f`). **Classification: a 30-frame HUD countdown pair, carried in the gs page
  the anchor already holds; no sim effect identified (INFERRED).** Falsification: `determinism_gate.py perturb` on `gs+0x968`
  → blk hash must not move. The gs words the tick reads and that stayed constant here (`+0x878..0x88C`, `+0x8C8`) are
  training/debug option words (`FUN_140634600` writes `entity+0x291 = 0x50` when `gs+0x888 != 0`): constant per match, carried.
* `ctx`: 30,123 B differ — TA record areas `+0x30..`, `+0x30030..`, texture pages `+0x100030..0x10EBD1` (render output, rebuilt),
  slot table `+0x1E0030..0x1E31AD` (carried by the anchor; render-only per `ctx_slotflags0`), composite `+0x1F8230..0x1F8268`
  (render), and **`+0x200073..0x20040C` (669 B) — not in the tick's or dispatcher's read/write set on the traced frame; owner UNKNOWN.**
  Test: trace an effect-heavy real-stage frame and assert no read in `ctx+0x200000..0x201000`.
* `blk`: 7,785 B (already characterised, DETERMINISM-CONTRACT s1.2).

### 1.5 Hypothesis H1 and its falsification (the one thing that could make the anchor incomplete)

**H1:** every list node drawn by `FUN_140620cd0` in frame N had its `+0x18` callback executed earlier in frame N (the callback pass
`FUN_1406283a0` runs in the sim half, the draw in the render half), so the destination object is always write-before-read
within the frame and its previous content never matters.

Evidence for: call structure (1.2); on the traced frame the tick wrote no bank bytes and the drawn list-6 nodes' callback
(`FUN_140654790`) does not touch objects — consistent. Evidence against: none yet; not measured on a stage with props.

**Test (deterministic, no game):** `emu_gate.py frame --target tick` on a **real-stage dump with list-5 props** (none exists yet —
the only live dumps are stage 0x0B). From the trace, for every dcram write outside the tile buffer take its address range;
assert that no READ of that range by the render half (`FUN_140848ee0` / `FUN_1408436a0`) precedes the first write in the same
tick. Then perturb: zero the destination objects of all drawn list-5/6/7 nodes before the tick → ctx TA pages must be identical.
If either fails, the anchor must carry those objects (a per-node delta of `+0xA0` object bytes, ~200 B/record) — a bounded,
render-only addition, never a sim input (the sim never reads them: FRAME-READSET s3.2 readers are all render/submit).

### 1.6 What the runner loads — the final list

| source | content | evidence |
|---|---|---|
| **(i) anchor** (agent 0.3.47, `reader.rs:1529-1530, 2246-2263`) | `blk[0..0x33B18)`; `game_state` page (`exe+0xAC6D40`, 0x1000: arena base `+0`, frame fn `+0x10`, blk ptr/size `+0x1B0/+0x1B8`, staging `+0x208`, pads `+0x218..`, seat map `+0x258..`, picks `+0x758`, gates `+0x520/+0x80C/+0x828`, HUD words `+0x878..`, countdowns `+0x964/+0x968`); exe page `0x142edf300..0x700` (blk/G pointers `+0x260/+0x280`, bank model tables `+0x288..0x2A0`, HUD state `+0x243/+0x246`, entity head `+0x328 = blk+0x324E0`, stage models `+0x330..0x367`); ctx slot table `ctx+0x1E0030..0x1E31CC` | DETERMINISM-CONTRACT s1.1b, s7 C1/C7 |
| **(ii) user's arc via the game's own loader** | boot banks (`FUN_14060c070`: AFS 799/800 → `0x0D000000/0x0D026000`, 0x343/0x344 → `0x0D082000/0x0D099000`, 0x345/0x346 → `0x0D0C6000/0x0D0E5000`, 0x347/0x348, 0x349/0x34A, 0x34B/0x34C, 0x34F/0x350, 0x351/0x352, 0x353/0x354, …), stage POL/TEX (`FUN_14060c370` case 1: `DAT_140a6aa80[stage]`/`DAT_140a6aa30[stage]` → `0x0D82D000/0x0D85D000`, stage = `blk+0x6D04`), match banks (case 5: AFS 0x95 → `0x0CC00000`, 0x345/0x346, tile list 0x97/0x98 → `0x0CE60000`), the six PL images (AFS `209+cid`, `receipt_gate.check_pl_images`) + tail (1.7). All through `FUN_14060dcf0(entry, dcaddr)`: `memcpy(dcram + (dcaddr−0x0C000000), ctx[0] + u32[ctx[0]+8+8·entry], u32[ctx[0]+0xC+8·entry])` — the Sega AFS directory (`rip_texbank.py:71-75`) read from the **in-memory image at `ctx[0]`** | decompiles 2026-09-03; `docs/STEAM-SH4-FUNCTION-MAP.md:38` (`FUN_14060c370 ↔ loc_8c032be0` CONFIRMED) |
| **(iii) reconstructed by the frame itself** | tile buffer `0x0CE60000..`, staging `*(gs+0x208)`, ctx TA records + pages, `0x142eed950` scratch, render-table bookkeeping `DAT_142ec4370..`, `game_state+0x4F4..0x5EC` (`FUN_140607e90`), LayerZ (`FUN_14060a1f0`) | FRAME-READSET s3.3-3.5, s4 |

Note on (ii): the alternative "carry the bank deltas in the anchor" is not needed if H1 holds, and would ship ROM-derived
bytes (the rebased records) — BYOR forbids it. The loader path keeps every game byte on the user's side.

### 1.7 The PL tail — the remaining UNKNOWN, now with a located candidate (INFERRED)

Seeding on the slot stride `0x150000` in `re_map/cache/steam_disasm.jsonl` yields exactly one function:
**`FUN_14060dd40`** (callers `FUN_14060d980 @0x14060da80/0x14060da94`). Decompile: an asynchronous load-queue stepper over
request records `{state +0x1D, ring idx +0x1E/+0x1F, type +0x1C, dcaddr +0x08, entry +0x0C}` from tables `DAT_142ec6de0` /
`DAT_142ec6900` (`{flags u8, entry u16 @+2, dcaddr u32 @+4}`); flagged (0x80) requests push `{DAT_140a6abb8[entry], size 0x150000,
DAT_140a6abb8[dcaddr…]}` into the ring `DAT_142ec6d80` (the per-slot 0x150000-B image jobs); state 1 does the AFS memcpy
(same expression as `FUN_14060dcf0`) and then pushes a **post-process record** `{type, DAT_140a69dfc[type], dcaddr}` into
`DAT_142ec6d00` — the tail builder is whatever consumes that ring (UNKNOWN; next hop = xrefs to `DAT_142ec6d00`).
Falsification of "the tail is a pure function of the AFS bytes": run `FUN_14060d980` in the p-code harness on a zeroed slot with
`ctx[0]` = the AFS image until the queues drain; compare the produced `0x150000` region with the live slot over the bytes the
frame reads (DETERMINISM s4: 0 differ between two live loads of cid 52 on those bytes). Until then the runner uses the
**dump-once-per-character tail** (agent-side export of `+0x130000..0x150000` per cid — user's own bytes, stays with the user).

---

## 2. The live process's memory model the runner must recreate (CONFIRMED from `pre/game_state.bin`, `pre/ctx.bin`, meta.json)

```
arena  = *(game_state+0)            = 0x077C1000   (one VirtualAlloc'd block; FUN_140607b50, STAGE-DRAW-GHIDRA s2)
ctx[0] = arena                      = 0x077C1000   AFS image (the loader reads its directory here)
ctx    = arena + 0x8000000          = 0x0F7C1000   NaomiLib host context (0x400000)
ctx[3] = arena + 0x8200000          = 0x0F9C1000
dcram  = ctx[1] = arena + 0x8400000 = 0x0FBC1000   32 MB DC work-RAM image (DC X at dcram + X − 0x0C000000)
staging= *(gs+0x208) = dcram + 32MB = 0x11BC1000   host texture staging (write-only per frame)
blk    = ctx[2] = *(gs+0x1B0) = arena + ((rand&0x3F)+0xC0)<<20 = 0x146C1000 here (FUN_14003ad20, per boot)
exe    = 0x140000000 (no relocation; position-dependent image, contract C1)
```

Design consequence: the runner **reserves the whole 256 MiB arena at the anchor's `gs+0` address** and places every region at
its live offset → **Δ = 0 for every pointer** (blk self-pointers, `ctx+0x1f81b0`, `DAT_142edf628`, bank tables, the 557 asset
pointers) — exactly the configuration the p-code harness runs and has gated (FRAME-READSET s2: "nothing relocated"). Relocation
by Δ (DETERMINISM s1.1b items 1 and 3) is the fallback only if the reservation fails.
Gate: `VirtualAlloc(arena, 0x10000000, MEM_RESERVE|MEM_COMMIT)` returns the requested address in a fresh runner process; the runner
must be linked at a base other than `0x140000000` (the default x64 EXE base) or the image cannot be mapped.

---

## 3. The runner ("thin wrapper") — steps, each with a falsifiable gate and the tool that runs it

### 3.1 Loader

| item | design | evidence | gate / tool |
|---|---|---|---|
| **image source** | the agent's one-time export of the user's **unpacked live image** (68,059,136 B = `SizeOfImage 0x40E8000`, same bytes as `mvc_dump.bin`), never the on-disk exe (packed; unpacks only under Steam) | WORKSTREAM-CLIENT-REPLAY.md G2/G3 "BYOR"; memory rr-sprite-render-pipeline | SHA of the export == SHA of `pre/exe_image.bin` for the same build; `build_id` (PE timestamp+size) keyed |
| **mapping** | `VirtualAlloc(0x140000000, 0x40E8000)` + copy; protections: section table of the dumped header is the PACKER's (10 sections, code `0x1000` RX `0x60000020`, `.rdata` `0x8DB000`, data `0xA31000` RW `0xC0000040`, RWX runtime `0x3092000` / `0x3D6C000`); simplest correct choice = the live page protections the agent records at export (dump_live records `unreadable_pages` only today) or RWX for the whole image as the harness effectively does | `pe_arena.py` on `pre/exe_image.bin` | the tick runs to `RET` natively; `STMXCSR == 0x1F80` at entry (C3) |
| **relocations** | none: `basereloc` directory size 0; image is position-dependent | PE header read | — |
| **imports** | the dumped header's import directory (RVA `0x03D6F0B4`, 0x4C8) is the packer's, not the game's; the game's IAT lives in `.rdata` and holds the **dumping process's** kernel32/ntdll addresses (`0x1408DB240 → 0x7FFC8C25DC60`, `0x1408DB140 → 0x7FFC8C29A7D0`, `0x1408DB238 → 0x7FFC8A9D2DA0`, `0x1408DB218 → 0x7FFC8A9D8040`). The tick touches **6 imports, all in the UCRT `sprintf` path**: `GetLastError, FlsGetValue, RtlAllocateHeap, FlsSetValue, HeapFree, SetLastError` (4× each per frame) | DETERMINISM-CONTRACT s2; `emu_frame.py:CRT_SLOTS` (4 slots CONFIRMED by capstone on the live image; the `GetLastError/FlsGetValue/SetLastError` slots come from the trace's kind-3 records) | **Do not resolve; replace** (contract C6, proven in the harness): point the 6 slots at runner functions — `FlsGetValue/FlsSetValue` = a real per-thread slot (so the CRT reuses its ptd instead of leaking 0x3C8 B twice per frame), `RtlAllocateHeap(_, 8, n)` = zeroed alloc ignoring the handle (the CRT's `_crtheap` global still holds the dumping process's heap handle), `HeapFree → 1`, `Get/SetLastError` = pass-through. Gate: exactly 24 external calls per frame through these 6 slots (`extcount`), no call through any other slot (guard: fill every other IAT qword with a trap that logs and aborts) |
| **TLS / SEH** | TLS directory (RVA `0x3D6F000`) belongs to the packer; the game's UCRT uses FLS (above), and the TEB reads seen in the harness (`0x18, 0x28, 0xA0, 0x20A, 0x1380..0x15C0`) are satisfied by any real thread's TEB. Exception directory (`0x3D70A18`) is the packer's; the tick raises nothing (no throw on path, `__security_check_cookie` value-independent). Register the image with `RtlAddFunctionTable` only for crash diagnostics | DETERMINISM s2, s4; EMU-GATE s2 | a deliberate `int3` inside the tick unwinds to the runner's handler (diagnostic), nothing more |
| **CRT dispatch flag** | `DAT_142eefbd8` may stay at the exported value (1) — FMA3 path bit-identical to SSE2 (C3) | DETERMINISM s3 | `determinism_gate.py native` on the target host: 0 differing |
| **exe globals holding process-specific pointers** (must be set, not copied) | in the carried page: `DAT_142edf560 = blk`, `DAT_142edf580 = blk+0x3CB8`, `DAT_142edf588/590/598` (dcram), `DAT_142edf628 = blk+0x324E0`, `0x142edf630..0x667` (dcram). Outside it: `DAT_142ef0ab0 = ctx`, `DAT_142ef0ab8` (current matrix pointer, ctx), `DAT_142ebc010` → the 64-entry debug ring at `+0x346AC..0x34AB0` on a heap object (`FUN_14006b5d0`; no effect on blk) → point it at a runner-allocated zeroed 0x40000-B buffer; `DAT_142e10b98` (GGPO session) = 0; `game_state+0` arena, `+0x1B0` blk, `+0x208` staging; `ctx+0x0/+0x8/+0x10/+0x18`, `ctx+0x1f81b0 = blk`. With Δ=0 all of these already hold the right values in the anchor/export — the runner only has to **assert** them (C1 checks) | DETERMINISM s1.1, s7 C1; this doc s2 | `hidden_state.py`-style pass over the first tick's trace: every pointer read from the exe that leaves the image must land in arena or image |
| **ctx at entry** | balanced NaomiLib state (C4): `ctx+0x1f80a4 = 1`, `+0x1f81b0 = blk`, `+0x1f81b8/bc = 0x40`, slots 0–2 identity, `+0x1f82b0 = 1.0`, slot table from the anchor. Since the anchor is taken at a clock edge (agent 0.3.47 reads all four regions and re-checks the clock, `reader.rs:2245-2265`), and the frame is a fixed point on that state, restoring the anchor's slot table and running `FUN_140846a40(blk, 0x40)` + `near = 1.0` as EMU-GATE does reproduces C4 | EMU-GATE s2; DETERMINISM `ctx_matrix` perturbation | 0 bytes of `ctx+0x1f80a4..0x1f8600` differ after one tick |
| **DC-RAM fill** | allocate 32 MB, fill `0xCD` (the game's own fill, STAGE-DRAW s2), map the user's AFS at `ctx[0]`, then **call the game's loaders**: `FUN_14060c070()` (boot banks), `FUN_14060c370(1)` with `blk+0x6D04` already restored (stage), the case-5 match loads, and the PL path (1.7) or the per-cid tail cache; the stage initialisers `FUN_140620200` (→ `PTR_PTR_140a6ec20[stage]`) allocate list-5 nodes **into blk** — do NOT run them after restoring the anchor (the anchor's blk already holds those nodes); run only the loaders that write dcram/ctx. Order and exact subset = the match-start case `switchD_14060e183::caseD_5` (STAGE-DRAW s2) minus its blk writes — this split is the loader's one piece of non-trivial RE (INFERRED today) | 1.3, 1.6; `docs/TEXTURE-BANKS-GHIDRA.md` seed 102 | **byte gate:** runner dcram vs `pre/dcram.bin` over every bank region and PL entry: 0 differing bytes except the regenerated classes of 1.1 (u/v of destination objects, header-patch residue) and the tile buffer; `rip_texbank.py --gate` 16/16 pages |
| **anchor apply** | copy the four regions to their live addresses (Δ=0), then C1 self-checks: `*(gs+0x1B0) == *(0x142edf560)`, size `0x33B18`, `*(ctx+8) == dcram`, `*(0x142edf628) == blk+0x324E0`, the six `blk+0x32500+8k` form a permutation of `blk+0x3DB8+n·0x738` (`receipt_player.inl` self-check logic, lines 200-212, reusable verbatim), mode bytes `blk+0x3CB8[0..2] = 2,1,2` | DETERMINISM C1; RECEIPT-PLAYER-G | all asserts pass or the runner refuses |

### 3.2 Tick loop

* **Entry:** `FUN_140118950(&DAT_142d10b90, inputs[4], 0)`, inputs `= {seat0, seat1, 0, 0}` 24-bit words, seat map forced to
  `{0, 1, −1, −1}` (C2; an offline anchor carries `{0,0,0,0}` — this dump does: `gs+0x258.. = [0,0,0,0]` — which routes only
  `inputs[3]` to seat 0). The wrapper does `DAT_142d10b90++`, `gs+0x798 = 1`, `prev = cur` on the four pads, `pad[seat(k)] =
  inputs[k] & 0xFFFFFF`, then `(*(gs+0x10))()` = `FUN_140607d60`. CONFIRMED (FRAME-READSET s1; `receipt_gate.py` self-test 20/20;
  negative test 360 blk bytes differ when one bit is flipped with the map set).
* **Equivalent direct path** (decompile of the offline loop `FUN_140039de0`, verbatim): `gs+0x798 = 1; do { gs+0x770 = (gs+0x798 > 1);
  gs+0x228 = gs+0x218; gs+0x218 = in0; gs+0x22C = gs+0x21C; gs+0x21C = in1; gs+0x230 = gs+0x220; gs+0x220 = in2; gs+0x234 = gs+0x224;
  gs+0x224 = in3; (*(gs+0x10))(); gs+0x768++; gs+0x798--; gs+0x770 = 0; } while (gs+0x780 == 0)`. The shell does **nothing else**
  between ticks that the frame consumes: the hidden-state inventory found only the pad words as carried inputs (DETERMINISM s1.1);
  the clock `blk+0x3CC8` is advanced by the frame itself (+1 per call, 20/20); round/set transitions are inside the frame (the G run
  walked char-select → battle on the hook alone). `gs+0x770` (render suppression on catch-up ticks) and `gs+0x780` (pause) are
  shell flags the runner leaves at 0.
* **Inputs source:** the tape's **`confirmed_in`** triples `(frame, seat0, seat1)` (`reader.rs:1931 harvest_confirmed_in`, GGPO ring
  `session → Sync+0x9F0 → queues+0x190`, stride 0xE44), not `seat_in` (`G+0x218`, the PREDICTED latch — memory rr-ggpo-input-ring).
  For an offline match the two coincide. The tape's `start_sim_frame` = the anchor's `blk+0x3CC8` (`reader.rs:2210-2214`), so
  `inputs(frame) = confirmed_in[anchor_clock + k]` for tick k; the first tick consumes the words of the frame it PRODUCES (C2).
* **End:** the agent ends a recording when one team is wiped (`gs_team_wiped`, `reader.rs:1666`) held > 600 ms (`reader.rs:2302,
  2450`) or the clock freezes; the runner runs exactly `len(confirmed_in)` ticks and stops — there is no in-game end signal it must
  detect (the mode byte stays 2 through KO/results: memory rr-ggpo-determinism).
* **Speed:** no vsync, no `gs+0x798` patch; the harness measured 459,681 instructions per idle tick — native speed is the whole
  point; do not promise a number.
* Gate: `blk+0x3CC8` +1 per call; after N ticks the runner's `blk` equals the harness's N-tick dump byte-for-byte (the harness IS
  the oracle for the runner: same images, same inputs, `emu_gate.py frame --target tick` repeated N times — `determinism_gate.py
  multitick --ticks N` already writes those dumps).

### 3.3 Output: exposing `blk` + `ctx` + DC-RAM to the emitter

The agent's harvest reads, per frame, from the live process (`reader.rs`): the row (`GS_SCHEMA`, line 1239: fighters `blk+0x3DB8+i·0x738`,
camera `0x6908..0x699C`, deck `0x6CA8`, blackout `0x3D50`, background window `0x6CB4..0x6CF4`, seat words `G+0x218`), `nodes` (the
draw-list handles `blk+0x2F4D0..` → pool nodes, 54-B records), `anodes/aobjs` (`harvest_anodes`, line 1456: lists `blk+0x2EDE8+L·8`,
node matrix `+0xA8`, colour `+0x94`, flags `+0xF0`, alpha `+0x90`, the object bytes at `*(node+0xA0)` in DC-RAM interned by hash,
`+0xE8` parent matrix), `palrows` (`blk+0x13C0`, 0x540 B), `bg`, and the receipt anchor. All of it is a pure read of `blk` and DC-RAM
(objects) — nothing from ctx. The runner therefore exposes the three host pointers and the emitter is the **same harvest code
over a memory view instead of `ReadProcessMemory`** (port verbatim — memory feedback-port-proven-code-asis). The offline Python
twin already exists: `blkstate.py` (`nodes`, `anodes`, `pnodes`, `cbworld`), used by `tape_vs_dump_gate.py`.

Sampling phase: the agent samples while `blk+0x3CC8 == c` between ticks (edge-synced since 0.3.34, torn-read retry since 0.3.46);
nothing touches `blk` between two ticks (`receipt_player.inl` header comment; the dispatcher runs inside the tick), so the
runner's post-tick state for clock c is what a clean live row c holds. Live rows can still be torn (v4 measured 3.9% of moving-fighter
rows one frame stale, `reader.rs` comment near line 2280) — the gate must classify a mismatch as "torn live row" when the live
row equals the runner's row c−1 on the differing fields.

### 3.4 THE MASTER GATE: runner tape == live tape

Definition: for an **offline, rollback-0 match recorded by agent 0.3.47** (so the tape carries `battle_anchor` and `confirmed_in`),
build the runner's v5 tape from its per-frame memory and compare every column of every frame with the live tape.

Tools: `d3dcap/replay/tape_vs_dump_gate.py` compares a tape against per-frame shim dumps (`state_<f>.json` + blk delta chain) on
sprite draw list, world-node counts and `palrows`. Extension (new file, same lane): `runner_tape_gate.py` = the same comparison
where the "dump side" is the runner's per-frame `(blk, dcram, ctx)` images (or its emitted tape), plus the row columns
`receipt_gate.py` already checks (`px/py/hp` f32/u16 bit-exact) and the remaining `GS_SCHEMA` columns. Report per column:
equal / differing / first differing frame / torn-row count. **PASS = 100% equal on every column after torn live rows are
excluded, 0 unexplained mismatches.**

Prerequisite data (does not exist yet, DETERMINISM s6c): one match with the 0.3.47 agent running AND `dump_live.py pre` taken at the
battle start (for the dcram/ctx that the anchor does not carry — until the loader path of 3.1 is gated, the runner takes dcram from
the dump). ▶ READY recipe for the owner: start agent 0.3.47, enter an offline Versus match, run `python
C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\dump_live.py` at the first battle frame, play the match to a KO, keep both artefacts.

### 3.5 What is reusable as-is

`receipt_player.inl` (hook point, injection order, self-check, interlock) — proven live; `receipt_gate.py` (anchor → tick → px/py/hp
per frame vs tape, self-test PASS 20/20, negative test diverges); `determinism_gate.py` (perturb / multitick / native / dispatch);
`emu_gate.py frame` + `emu_frame.py` + `EmuGate.java` (the oracle for the native runner: same images, same inputs, byte-exact
expectation); `blkstate.py` (offline harvest twin); `rip_texbank.py` (AFS access, bank page gate 16/16).

---

## 4. Where a match starts and ends for the runner

* **One anchor per match.** The agent takes the battle anchor at recording START (`reader.rs:2244` "0.3.47: battle-frame receipt
  anchor"), i.e. once per match, at the first frame where both teams are alive and the mode is battle. Character select is
  **outside `blk`** (the MT-Framework shell; RECEIPT-PLAYER-G "the shell does NOT restore with the sim") so the run cannot carry
  through char select on inputs alone — CONFIRMED by the G falsification (wrong team `[19,23,20,22,21,6]` locked, then AV).
  Therefore: **runner job = one match = one anchor + its `confirmed_in`**; a set is N independent jobs. The frame counter also
  resets on every mode entry (memory rr-ggpo-determinism), so frames never compose across matches anyway.
* **Between matches inside the frame function:** the match-start case reloads stage/PL banks through `FUN_14060c370` from `ctx[0]`
  — with the AFS mapped, a runner that DID run across matches would reload correctly; but the char-select inputs still do not
  reach the shell, so this is moot. Do not build it.
* **Start frame:** the anchor's `blk+0x3CC8` (`battle_anchor_frame`), which equals the tape's `start_sim_frame`; row `frame == anchor`
  must exist (`receipt_gate.py` asserts it).
* **End frame:** last `confirmed_in` frame; the tape's last row.

---

## 5. Failure modes and how each is falsified

| # | failure mode | status | falsification / mitigation |
|---|---|---|---|
| 5.1 | FMA vs SSE2 CRT divergence | **closed**: no game code uses FMA/x87; the four FMA-capable CRT routines are bit-identical on both paths (native oracle, 155k + 3×65,536 + 5,064 points; `dispatch` UD2 proof) | `determinism_gate.py native` on every new host; C3 |
| 5.2 | uninitialised stack | **closed** for the traced frame: 12 B read-before-write, `0xCC` fill changes nothing | re-run `stack_cc` on the first real-stage / hit-heavy frame |
| 5.3 | heap addresses baked into the image | `DAT_142ebc010` debug ring (no effect, but WRITTEN 16 B/frame → AV in a new process if left as is); the UCRT `_crtheap` handle (bypassed by the slot replacement); `DAT_142edf628` (in-block now) | first native tick under a guard page policy: every write outside image/arena/runner buffers faults and names the site |
| 5.4 | timing-dependent paths | **closed**: 0 `RDTSC/CPUID/RDRAND/SYSCALL` executed; no time import; single thread, no waits (C9) | `hidden_state.py` asm scan on any new build |
| 5.5 | reads of the shell / Steam / D3D | **closed for the tick**: 6 imports, all sprintf; `gs+0x520/+0x828/+0x80C` gates carried in the page; `DAT_142e10b98 = 0` | the IAT trap of 3.1 (any other import = abort with the slot address) |
| 5.6 | **rollback smear (online tapes)** | open by construction: the live tape's rows include predicted frames later rolled back; the runner replays the CONFIRMED timeline. `seat_in` (`G+0x218`) is the predicted latch; `confirmed_in` is the ring | gate online tapes only on rows the live process never rolled back (tape `rollbacks` per match; per-frame rollback attribution is UNKNOWN today — would need the GGPO `load_game_state` frame numbers, `gs+0x76C` counter only) ; master gate is defined on rollback-0 matches first |
| 5.7 | torn live rows | measured 3.9% (v4), reduced by 0.3.46 torn-read retry | classify (row c == runner row c−1 on the differing fields) and exclude; count must be reported |
| 5.8 | PL tail not a pure function of the character | UNKNOWN for two boots (DETERMINISM s4) | dump the same character on two boots, diff the tail over a whole-match read set; per-cid tail cache meanwhile |
| 5.9 | H1 false (stale destination object drawn) | not yet gated (1.5) | the emu trace order test on a real-stage dump |
| 5.10 | `gs+0x964/0x968` written by the shell (`FUN_14010d0b0`) during a live match → runner lags | INFERRED render-only | `perturb gs+0x968` → blk identical |
| 5.11 | ctx `+0x200073..0x20040C` (669 B) mutated by something outside the tick | owner UNKNOWN; not read by the tick on the traced frame | trace an effect-heavy frame; assert no read |
| 5.12 | arena reservation at the anchor address fails | design fallback = Δ relocation (804 intra-blk + 243 arena + 557 asset pointers on measured blocks) | `VirtualAlloc` return value; relocation self-check permutation |
| 5.13 | packer's runtime layer expected at run time (the RWX section `0x3092000` hosts the syscall-hook handlers) | the tick never enters `≥0x1408d6c50` except CRT math (DETERMINISM s3.1) | executed-function set of the first native ticks ⊆ the harness's 634 functions |
| 5.14 | the exported image is from a different build than the AFS / anchor | `build_id` in the tape | refuse on mismatch |

---

## 6. CONFIRMED / INFERRED / UNKNOWN

| item | tag | evidence |
|---|---|---|
| Frame function `FUN_140607d60` = whole frame; `FUN_140118950` wrapper; pads `gs+0x218..0x224`; seat map `gs+0x258..` | CONFIRMED | FRAME-READSET s1, receipt_player.inl live |
| Frame deterministic on the live images; clock +1; 20 ticks match the live clock | CONFIRMED | FRAME-READSET gates i/iii, DETERMINISM s1.2 |
| Sim-relevant per-frame state lives entirely in `blk`; RNG `blk+0x32BD4/5` | CONFIRMED | DETERMINISM s0/s1.4 |
| Carry list: blk + gs page + exe page `0x142edf300..0x700` + ctx slot table; entity head `DAT_142edf628 = blk+0x324E0` | CONFIRMED | DETERMINISM s1.1b, G crash |
| DC-RAM writes outside `blk` over 237 frames = tile buffer + 60 B of bank-object u/v + TCW bytes | CONFIRMED (measured) | this doc 1.1 |
| Animated meshes regenerated from a pristine source model + blk phase counters (absolute writes) | CONFIRMED (decompile of the iterator API + two callbacks) | 1.2 |
| Callback pass executes inside the tick and before the sprite walker; before the whole render half | CONFIRMED (trace) / INFERRED (table dispatch `0x140a6bf58`, parent not read) | 1.2 |
| H1: drawn ⇒ callback ran this frame | INFERRED | 1.5 test |
| Bank bytes = AFS entry + `FUN_14060d770`/`FUN_140844dc0` rebase (+ init clears); TEX banks unchanged | CONFIRMED (measured vs the user's arc) | 1.3 |
| `FUN_14060dcf0` reads the AFS directory from the in-memory image at `ctx[0]` | CONFIRMED (decompile) + INFERRED that `ctx[0]` is exactly the IBIS+0x40 AFS image (the directory arithmetic matches `rip_texbank.py:71-75`; the arena head was not dumped) | 1.6 |
| Arena layout (ctx/dcram/staging/blk offsets from `gs+0`) | CONFIRMED | s2 |
| Image PE directories are the packer's; IAT holds process-specific addresses; 6 imports on path | CONFIRMED | 3.1 |
| PL image = AFS `209+cid` byte-exact; tail static per character for the read bytes | CONFIRMED (six of six; two loads of cid 52) | DETERMINISM s4, s6c |
| PL loader = queue `FUN_14060d980 → FUN_14060dd40` (0x150000) ; tail builder = consumer of `DAT_142ec6d00` | INFERRED / UNKNOWN | 1.7 |
| `gs+0x964/0x968` = 30-frame HUD countdowns (in-tick + shell writers), no sim effect | INFERRED | 1.4 |
| ctx `+0x200073..` owner | UNKNOWN | 1.4 |
| Per-frame rollback attribution for online tapes | UNKNOWN | 5.6 |
| Whether the loader subset "case-5 minus blk writes" is cleanly separable | INFERRED | 3.1 DC-RAM fill |

---

## 7. What the team has PROVEN vs what it has not (the go/no-go)

PROVEN (numeric gates on real bytes): determinism of the frame; the read set; the contract C1–C9 on one host/roster/stage; the
anchor's crash cause (`DAT_142edf628`); that the mechanism of tick hooking and seat-word injection works live; that the DC-RAM
write set outside `blk` is regeneration (this doc). NOT PROVEN: a receipt replayed end to end against a same-match tape (no data
pair); a real-stage (props) frame in the harness; the PL tail builder; behaviour on a second host. **Go** on building the loader and
tick loop (every step has a byte gate and an existing oracle); **no-go** on claiming "receipt replays are pixel-exact" until
section 8 step 3 passes.

## 8. Shortest path to the first end-to-end gate (receipt in → runner → tape out == live tape)

1. **Data pair** (owner, live): one offline Versus match with agent 0.3.47 + `dump_live.py` pre images at the first battle frame
   (3.4 ▶ READY recipe). Gate 0: `receipt_gate.py --run <dump> --tape <tape> --frames 60` PASS on clock/px/py/hp — the p-code
   harness proves the anchor+inputs premise on real data before any native code exists.
2. **Native runner MVP, Δ=0, images from the dump** (not yet the agent anchor): map image, reserve arena, copy `blk/ctx/dcram/gs`
   from `pre/`, replace the 6 IAT slots, set `DAT_142ebc010`, force the seat map, tick N. Gate 1: runner `blk` after k ticks ==
   `determinism_gate.py multitick` dump k, byte-exact, k = 1..20 (idle inputs), then with the tape's inputs vs Gate 0's per-frame
   px/py/hp.
3. **Emitter over the runner's memory** (harvest port) → v5 tape. Gate 2 (master): `runner_tape_gate.py` 100% per column after
   torn-row exclusion.
4. **Replace the dump's dcram/ctx by the loader path** (3.1 DC-RAM fill) with the anchor from the tape. Gate 3: dcram byte gate of
   3.1 + Gate 2 again. Only now is the runner "anchor + arc + image", i.e. BYOR-complete.
5. **Real stage with props**: repeat 1–4 on a stage ≠ 0x0B; run the H1 test (1.5) first.

## 9. re_kb seeds to add (not applied here)

File: `maplecast-flycast/tools/re_kb/112_receipt_runner_dcram_writeset.surql` — idempotent UPSERT/RELATE, evidence strings verbatim.

Contents sketch:
```
-- sources
UPSERT source:dcram_diff_20260903_000941 SET kind='measurement', ref='d3dcap/ttd/runs/20260903-000941 pre vs post dcram/ctx/game_state', strength='bytes';
UPSERT source:ghidra_2026_09_03_runner SET kind='ghidra', ref='mvc_dump.bin via :8080 bridge + capstone on pre/exe_image.bin', strength='code';
-- routines (roles) — CONFIRMED by decompile
UPSERT steam_routine:FUN_1406196e0 SET role='object-record iterator: open SOURCE model / DESTINATION object cursors (DAT_142eee568..590)';
UPSERT steam_routine:FUN_140619580 SET role='iterator: advance both cursors one vertex (0x50 hdr, 0x20 vertex; count hdr+4, x3 unless flag 0x10)';
UPSERT steam_routine:FUN_140619510 SET role='iterator: read SOURCE vertex xyz';
UPSERT steam_routine:FUN_140619530 SET role='iterator: read SOURCE vertex u,v';
UPSERT steam_routine:FUN_140619680 SET role='iterator: write DESTINATION vertex xyz, set bit0 marker on x';
UPSERT steam_routine:FUN_1406196a0 SET role='iterator: write DESTINATION vertex u,v, set bit0 marker on v';
UPSERT steam_routine:FUN_140845150 SET role='sin table lookup DAT_142ef0ac0[u16 angle]';
UPSERT steam_routine:FUN_140619800 SET role='load-time: clear TSP bits 0x18000 on every record of a model';
UPSERT steam_routine:FUN_14061e520 SET role='list callback pass: for node in blk+0x2EDE8+L*8: (*(node+0x18))(node)';
UPSERT steam_routine:FUN_1406283a0 SET role='per-frame callback pass over lists 3,4,2,5,6,10,7,8,9 (sim half; callers FUN_14060e3f0, caseD_7)';
UPSERT steam_routine:FUN_14060dcf0 SET role='AFS entry -> DC RAM copy from the in-memory AFS image at ctx[0] (dir at ctx[0]+8+8*entry)';
UPSERT steam_routine:FUN_14060dd40 SET role='async load-queue stepper (0x150000 PL slot jobs; post-process records into DAT_142ec6d00)';
UPSERT steam_routine:FUN_14060d980 SET role='load-queue pump (calls FUN_14060dd40 x2)';
UPSERT steam_routine:FUN_140634600 SET role='HUD/option pass: gs+0x964/0x968 countdown decrement, entity+0x291=0x50 when gs+0x888';
UPSERT steam_routine:FUN_140639200 SET role='sets gs+0x964|0x968 = 0x1E (HUD countdown)';
-- undefined callbacks as routines (capstone-read)
UPSERT steam_routine:LAB_140625920 SET addr=0x140625920, role='list-6 blackout-quad callback: +0x170=G+0x98; UV scroll dst.v = c - counter*step + src.v via iterator API';
UPSERT steam_routine:LAB_14064cb20 SET addr=0x14064cb20, role='stage-5 prop-1 animation: phase +0x30 (wrap 360) / +0x32 (wrap 2000); y = sin(phase)*k - c; u = src.u + phase*k (src = stage POL model 2, dst = model 1)';
UPSERT steam_routine:LAB_140654790 SET addr=0x140654790, role='training list-6 backdrop callback: node fields only from owner fighter';
-- globals
UPSERT global:gs_0x964 SET addr=0x140ac76a4, name='game_state+0x964 HUD countdown seat0';
UPSERT global:gs_0x968 SET addr=0x140ac76a8, name='game_state+0x968 HUD countdown seat1';
UPSERT global:gs_0x000 SET addr=0x140ac6d40, name='game_state+0 = arena base (ctx = +0x8000000, dcram = +0x8400000, staging = +0xA400000)';
UPSERT global:DAT_142ebc010 SET name='heap object with 64-entry debug ring at +0x346AC (FUN_14006b5d0); runner must re-point';
-- findings
UPSERT finding:dcram_writeset_regenerated SET status='confirmed', text='237 frames change 12,939 B of DC-RAM: tile buffer + 50 B u/v (effects POL) + 10 TCW bytes (HUD POL); all writers regenerate from blk phase + pristine source model; PL slots 0 B';
UPSERT finding:bank_load_rebase_measured SET status='confirmed', text='live POL banks differ from AFS by 0.9-2.5 KB (pointer/TCW rebase FUN_14060d770/FUN_140844dc0); TEX banks 0 B';
UPSERT finding:h1_drawn_implies_callback_ran SET status='inferred', text='callback pass FUN_1406283a0 precedes the render half; stale destination objects never drawn — gate on a real-stage dump';
UPSERT finding:pl_loader_candidate SET status='inferred', text='FUN_14060dd40 is the only function with 0x150000; tail builder = consumer of DAT_142ec6d00 (UNKNOWN)';
-- edges (writes / reads / calls / about / cites)
RELATE steam_routine:LAB_140625920->calls->steam_routine:FUN_1406196e0; ... (FUN_140619530, FUN_1406196a0, FUN_140619580, FUN_14061dbe0, FUN_140619800)
RELATE steam_routine:LAB_14064cb20->calls->steam_routine:FUN_1406196e0; ... (FUN_140619510, FUN_140619680, FUN_140619530, FUN_1406196a0, FUN_140845150)
RELATE steam_routine:FUN_1406283a0->calls->steam_routine:FUN_14061e520 SET sites=15;
RELATE steam_routine:FUN_140634600->writes->global:gs_0x964; RELATE steam_routine:FUN_140639200->writes->global:gs_0x968; RELATE steam_routine:FUN_14010d0b0->writes->global:gs_0x964 SET note='shell-side (INFERRED)';
RELATE finding:dcram_writeset_regenerated->cites->source:dcram_diff_20260903_000941; RELATE finding:dcram_writeset_regenerated->cites->source:ghidra_2026_09_03_runner;
RELATE finding:dcram_writeset_regenerated->about->steam_routine:LAB_140625920; ... (LAB_14064cb20, FUN_14060d8d0)
```
Apply only after the documented backup (`re_kb_data/_exports/`), with `PYTHONIOENCODING=utf-8 python tools/re_kb/apply_seed.py`.
Do not run `07_dedup_edges.surql`.

## 10. Address index (new in this doc)

`FUN_1406196e0/140619580/140619510/140619530/140619680/1406196a0` iterator API (cursors `DAT_142eee568..590`) · `FUN_140845150`
sin table · `FUN_140619800` TSP clear · `FUN_14061e520` callback pass · `FUN_1406283a0` per-frame pass (← `FUN_14060e3f0`
← `FUN_140611090`; ← `caseD_7`) · `LAB_140625920` / `LAB_140625900` / `LAB_140654790` / `LAB_14064cb20` callbacks ·
`FUN_14064ccd0` stage-5 prop-1 init (`PTR_DAT_142edf588[1]`, flags 0x801) · `PTR_PTR_140a6ec20` / `PTR_DAT_140a6ecb0` stage tables
(`0x140A6E9D0` / `0x140A6EB00` for stage 5) · `FUN_14060dcf0` AFS copy · `FUN_14060c070` boot banks · `FUN_14060c370` bank loader
· `FUN_14060d770` / `FUN_140844dc0` rebase · `FUN_14060dd40` ← `FUN_14060d980` PL queue (`DAT_142ec6de0/6900/6d80/6d00`,
`DAT_140a6abb8`, `DAT_140a69dfc`) · `FUN_140634600` / `FUN_140639200` / `FUN_14010d0b0` ← `FUN_1400fb840` (`gs+0x964/0x968`) ·
`FUN_140039de0` offline loop (`gs+0x770/0x780/0x798/0x768`) · `DAT_142ebc010` debug-ring object · IAT slots `0x1408DB240/140/238/218`
· PE dirs of the dumped image: import `0x03D6F0B4`, exception `0x03D70A18`, TLS `0x03D6F000`, basereloc none · arena `gs+0 = 0x077C1000`.

Scratch scripts (session scratchpad, not in the repo): `dcram_diff.py`, `dcram_sites.py`, `anodes_sites.py`, `bank_vs_afs.py`,
`stage_tab.py`, `xdis.py`, `pe_arena.py`. Their outputs are quoted above; re-running them on the same images reproduces every number.
