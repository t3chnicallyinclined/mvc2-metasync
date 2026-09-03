# WORKSTREAM — THE RECEIPT RUNNER (final architecture: pixels from a battle-frame anchor + inputs)

Status: PLAN, 2026-09-03. Merged from the three expert documents, which remain the evidence of record:

- `docs/RECEIPT-RUNNER-RE.md` — the runner itself (loader, tick, memory model, gates, failure modes, go/no-go). Senior RE.
- `docs/RECEIPT-RUNNER-DCRAM.md` — the DC-RAM image for a battle frame: region map, PL slot recipe, load-time patches, stage animation drivers. SH4 lane.
- `docs/RECEIPT-RUNNER-RENDER.md` — runner memory → tape → pixels through what exists; residuals; phone stream. Render lane.

Every claim below is tagged as in those documents. Nothing here is new evidence; where the three disagree or leave a gap, this document says UNKNOWN and names the test.

## RE METHOD (locked; `docs/RE-METHOD.md`)

1. Port the SH4 annotations to the Steam binary by function matching.
2. Seed with unique constants, then propagate along the call graph.
3. Translate globals through the block map before comparing reference sets.
4. Tag CONFIRMED versus INFERRED, and store the pairs as edges in the knowledge graph.

Restate these four sentences to every agent that touches this workstream.

## 0. The architecture in one paragraph

The Steam executable is the native x86-64 recompilation of the Dreamcast game. Its frame function (`FUN_140607d60`, wrapped by the GGPO tick `FUN_140118950`) reads only the 0x33B18-byte state block, one `game_state` page, one exe data page and the renderer context's texture-slot table, and takes two pad words as its only inputs (`DETERMINISM-CONTRACT.md` C1–C9; `FRAME-READSET.md`). The render pass, including the sprite walker that produces "as drawn" state, is inside that frame function (RENDER §1.1, CONFIRMED by the whole-frame trace). Therefore a match is fully described by a **receipt** = the battle-frame anchor recorded by agent 0.3.47 + 4 bytes of confirmed inputs per frame, and a **runner** that maps the user's own exe image and arc, restores the anchor, ticks the frame function with the inputs, and exposes its memory to the tape emitter and then to `rr-render`. Storage per 3-minute match: ~43 KB of inputs + the anchor (RE §0).

## 1. What is already built and reused as-is

| Piece | Where | State |
|---|---|---|
| Whole-frame p-code emulation + read set | `re_map/ghidra_emu/EmuGate.java`, `d3dcap/replay/emu_gate.py`, `emu_frame.py`, `docs/EMU-GATE.md`, `docs/FRAME-READSET.md` | CONFIRMED: 0/211,736 bytes differ over the chain gate; per-tick blk dumps at `%TEMP%\rrcap_emu\<tag>.blk_tNN.bin` |
| Determinism contract | `docs/DETERMINISM-CONTRACT.md`, `determinism_gate.py` | CONFIRMED: RNG blk+0x32BD4, no time/rand/thread on the tick path, FMA bit-exact, 20 ticks exact |
| Battle-frame anchor | agent 0.3.47 `reader.rs` ("battle anchor"): blk + gs page (exe+0xAC6D40) + exe page (exe+0x2EDF300, 0x400) + ctx slot table (ctx+0x1E0030, 0x319C), one clock edge | BUILT, running; first real tape pending a match |
| Native receipt player | `d3dcap/receipt_player.inl`, `d3dcap/receipt/replay_receipt.py`, `docs/RECEIPT-PLAYER-G.md` | tick hook, seat-word injection, relocation WORK; failed only on the char-select anchor |
| Live images | `d3dcap/ttd/runs/20260903-000941/pre|post` (blk, ctx, dcram 32 MB, game_state, exe image) | the emulation inputs and the basis of every measurement below |
| Tape harvest | agent `harvest.rs` (rows, nodes, anodes/aobjs, palrows, bg, record builder) behind `MemSource` (`read_at`); `mem::Proc` live, `runner::RunnerView` over the runner's per-tick images; `rr-tape.exe` emits | **BUILT (Gate 2)**: one implementation for the live agent and the runner |
| Renderer | `rr-render` crate (L1 24,574/24,574 and 90,673/90,673 exact vs Python; L3 60/60 byte-exact in the browser), `tape_to_seq.py` oracle, `states_to_tape.py` (v4 tape from block dumps) | unchanged for a runner tape |
| Gates | `receipt_gate.py` (selftest 20/20), `tape_vs_dump_gate.py`, `determinism_gate.py multitick`, `gate_l3.mjs`, capture gates vs Path B gold | extend, do not rewrite |
| Function map / KB | `docs/STEAM-SH4-FUNCTION-MAP.md`, `re_kb` seeds 100–111 | +112/113 from this workstream |

## 2. Settled questions (the evidence that makes the plan possible)

**Q1. Does the frame write per-frame state outside blk?** No. Pre→post over 237 frames, 32 MB DC-RAM: 12,939 B differ in 13 ranges — the tile buffer at `0x0CE60000` (rebuilt per frame), 50 B of effect-vertex u/v, 10 TCW low bytes in HUD record headers (combo counter header patch, `FUN_14060d8d0`). PL slots: 0 B; stage POL: 0 B (RE §1.1, DCRAM §1.1, CONFIRMED). Mechanism: callbacks use the NaomiLib two-cursor iterator (`FUN_1406196e0`, read `FUN_140619510/530`, write `FUN_140619680/6a0`) — SOURCE = pristine model, DESTINATION = drawn model, phase in **blk** (`node+0x30/+0x32`) — absolute regeneration, never read-modify-write (RE §1.2, CONFIRMED). ⇒ carry list `DETERMINISM-CONTRACT.md` §1.1b stands.

**Q2. Can the DC-RAM image be rebuilt from the user's arc?** Yes, through the game's own loader. `FUN_14060dcf0` copies AFS entries from the in-memory AFS image at `ctx[0]` (no file I/O). PL slot recipe (`FUN_14060d100` = SH4 `loc_8c031fa0`, CONFIRMED): each slot `0x0C420000 + pos*0x150000` holds 11 AFS files — `209+cid` at +0, then `268/327/386/445/504/563/681/622/740 + cid` at `+0x130000/0x13C000/0x13D000/0x13E000/0x140000/0x141000/0x142000/0x143000/0x144000`, and the 32 KB `3+cid` tail at `+0x148000`; **gate 66/66 byte-exact** on all six slots of the live image (DCRAM §2.1). Banks: stage Δ +0x98D000, effects +0x130000, HUD +0x202000 (DCRAM §1.2). Live POL banks differ from pristine entries by 0.9–2.5 KB each because of load-time patches the runner must replay: `FUN_14060d770` pointer relocation, `FUN_140844dc0` TCW assignment, `FUN_140619800` TSP clears, stage-0x10 ISP/TSP, `FUN_140619720` on HUD models 0..3, `FUN_140660f40` flag OR on effects model 20 (DCRAM §2.3, RE §1.3). TEX banks: 0 B difference.

**Q3. Stage animation — could the renderer pose props from keys even without the runner?** Yes in principle: driver state = node shorts `+0x30/+0x32/+0x34`, ints `+0xF4/F8/FC`, parent `+0x60`, the sin table and exe tables — **no frame counter**. Carnival: `FUN_14064a840`=`loc_8c10eb3e` phase clock → `FUN_14064a4a0`=`loc_8c10ec26` keyframe lerp from a table inside the stage POL. River Raft: `FUN_14064e8b0`/`FUN_140751220`/water `FUN_140750eb0` rewrite x+colour of models 9/11/13 from pristine 10/12/14 (DCRAM §4, CONFIRMED both read). 15 other stage tables unclassified. This is the Track R "keys not bytes" lever measured earlier (animated prop meshes = the whole 3 MB → 14 MB tape spread).

**Q4. What does the shell do between ticks that the frame relies on?** Only the pad shuffle (RE §3.2, decompiled). Inputs come from `confirmed_in`, not `seat_in`. Seat map forced `{0,1,-1,-1}`.

**Q5. Where does a match start and end for the runner?** One anchor per match; character select is outside blk (the G falsification stands) (RE §4).

## 3. The runner — design decisions (RE §2–3)

- **Δ = 0 memory layout.** One 256 MiB arena reserved at the anchor's own addresses (`gs+0 = 0x077C1000`; `ctx = +0x8000000`, `dcram = +0x8400000`, staging `+0xA400000`, `blk = +0xCF00000` per-boot random). No pointer relocation — the p-code harness's proven configuration. The runner must NOT be linked at `0x140000000`.
- **Image.** The agent-exported unpacked image (retail exe is packed). PE directories are the packer's: no relocs, packer import dir. The tick path touches 6 UCRT imports (all sprintf-family, contract C6): replace them with runner functions; trap every other IAT slot.
- **Tick.** `FUN_140118950`. Set `DAT_142ebc010` (debug ring; heap pointer the tick WRITES — AV in a fresh process otherwise). `gs+0x964/0x968` HUD countdowns (setter in-tick `FUN_140639200`, decrementer shell-side `FUN_14010d0b0`) ride in the gs page; render-only INFERRED, perturbation test named.
- **Output.** blk + ctx + DC-RAM + gs page exposed to the harvest; `anodes.model` and `nodes.gfx1` are host-absolute pointers → normalise to DC addresses before comparing (RENDER §2.3).
- **Master gate.** `runner_tape_gate.py` (extension of `tape_vs_dump_gate.py`): runner tape == live agent tape per column, after excluding the six live-only noise classes (sampling phase, torn rows, rollback last-write-wins, caps, host-pointer fields, LUT lag) (RENDER §2.3–2.4).

## 4. Build order — each step has a numeric gate and an existing oracle (RE §8, RENDER §6.2)

0. **Data pair** — ✅ **GATE 0 PASSED 2026-09-03 (first real receipt):** offline Versus, stage 9, roster [42,23,52,12,44,46], agent 0.3.48
   tape `local_1788462750766_stage9` (5,222 frames, 0 rollbacks, battle anchor 12,607 B gz) → `anchor_to_run.py` + `pl_rebuild.py`
   → `receipt_gate.py --frames 60 --input-shift 1`: **clock 60/60, px 60/60, py 60/60, hp 60/60**. Three facts learned:
   (a) row N's `seat_in` are the inputs that PRODUCED frame N (shift 0 gave px 38/60 with a tick-2 divergence; shift 1 exact);
   (b) a post-match dump has PL slot 1 (pos 3) overwritten from byte 0 by the results screen (187,803 B) — PL images must come
   from the arc recipe (55/55 files byte-exact) or a mid-match dump; (c) the agent's trace log truncates on restart (watcher bases).
   Original step (kept for the record): (owner: live session): one offline Versus match with agent 0.3.47 recording, `dump_live.py` pre images at the first battle frame. Gate 0 = `receipt_gate.py --run <dump> --tape <tape> --frames 60` PASS on clock/px/py/hp. Proves anchor+inputs on real data before any native code. **This is the blocker today.**
1. **Native runner MVP, Δ=0, images from the dump.** Map image, reserve arena, copy blk/ctx/dcram/gs from `pre/`, replace the 6 IAT slots, set `DAT_142ebc010`, force the seat map, tick N. Gate 1 = runner blk after k ticks == `determinism_gate.py multitick` dump k, byte-exact, k = 1..20 idle, then with the tape's inputs vs Gate 0's per-frame px/py/hp.
   ✅ **GATE 1 PASSED 2026-09-03** (`docs/RECEIPT-RUNNER-GATE1.md`, `d3dcap/receipt/runner/`): native `rr_runner.exe` == p-code oracle byte-exact on blk, idle 20/20, receipt inputs 60/60 and 300/300 (clock 1716→2016); **0.04–0.40 ms per tick** (p50 0.08 ms; budget 16.7 ms). Corrections carried: the Fls* calls are UCRT-cached pointers (`0x142eefca0[5]/[6]`), IAT `0x1408db218` is TlsSetValue; a real FLS grows the import set (RtlEnterCriticalSection) — stub semantics are the contract; on a real-match frame the tick writes the host device object `*(0x140acd3a8)` (PALETTE_RAM) — lazily zero-backed and logged; 86 ctx page-table dwords are stale-stack copies (render-side, never read). Seed 114.
2. **Emitter over runner memory** → v5 tape (harvest port behind the `read_at` seam; `states_to_tape.py` extended to read `palrows` from blk+0x13C0 and objects from dcram). Gate 2 (master) = `runner_tape_gate.py` 100 % per column after torn-row exclusion.
   ✅ **GATE 2 PASSED 2026-09-03** (`docs/RECEIPT-RUNNER-GATE2.md`): the agent's harvest is now a library (`RetroReceipts-agent/agent/src/harvest.rs`,
   `MemSource` seam under `read_at`; the live agent and `rr-tape.exe` share one implementation) run over `rr_runner.exe --harvest-dump`
   (per tick blk + gs page + exe page + the changed DC-RAM pages). Stage-9 offline tape, 301 frames: **0 unexplained differences**;
   rows/nodes/anodes/palrows/envelope exact except 14 class-P values (two provably mid-walk live frames), 3 objects of class **A**
   (new: the 0.3.44 object cache ships first-sighting vertices for animated props on BOTH sides) and the C2-forced seat map.
   Render: sprite draws 2114/2114, `--no-world` browser A/B 60/60 byte-equal, full-frame browser A/B 60/60 once the 3 class-A byte
   strings are swapped (299/301 over the window; the 2 residual frames are the two class-P mid-walk live frames). Measured stage-9 DC-RAM write set: 952 pages / 3.9 MB over 300 ticks (tile buffer + 2 animated stage-POL
   pages + effects u/v). Seed 115.
3. **Loader path replaces the dump** (DC-RAM fill from the user's arc + the §2.3 patches; anchor from the tape). Gate 3 = dcram byte gate + Gate 2 again. Only now is the runner "anchor + arc + image" = BYOR-complete.
4. **Real stage with props** (all live dumps so far are training stage 0x0B): run the H1 ordering test first (RE §1.5: "a node is never drawn in a frame whose callback did not run first" — dispatch table `0x140a6bf58`), then repeat 0–3.
5. **Pixels.** `rr-render emit_seq` → L1 → `player.html` readback vs the Path B scene bitmap of the SAME match (5-rung ladder: sim → state → tape → draw list → scene RT; alignment by the sidecar `clock`) (RENDER §3.2). Precondition: a receipt and a Path B capture of the same match — does not exist yet.

## 5. Client shapes (RENDER §5)

- **Native host (Windows/Linux, BYOR):** receipt in, runner + emitter + `rr-render` local. The user's exe image and arc never leave their machine.
- **Phone / browser (M-interim):** a server-side runner (the match participants' images cannot be used server-side without their consent — product decision) emits FrameRecords over Redis/NATS. Measured today 719 KB/frame with the static deck re-emitted; strip the deck → ~100 KB (INFERRED from measured VB 547 / IB 55 / deck 464 KB sections); keyed frames → 20–50 KB (estimate); or send the tape (0.5–0.9 KB/frame gz + 21 MB pack) and run the wasm emitter on the device (27.8 ms/frame desktop measured; phone UNKNOWN). Byte-exact gate: per-frame sha256 of FrameRecord (both sides emit from frame 0) + `gate_l3.mjs` scene-RT sha (order-independent; the gate for join-at-keyframe).
- **Host/lobby nodes as runners (Tris, 2026-09-03):** the arcade host machines own the game; they can run the emitter today and
  the receipt runner later as their work, serving rendered frames to signed-in viewers (phones, non-owners) — the BYOR-clean
  answer to the M-interim question. Replays require sign-in (PWA resolver gates on auth; server tape read must be authed).
- **Browser-native frame function** (lift x86-64 → wasm): UNPROVEN; not on the path until Gate 3 passes.

## 6. Residuals the runner makes easier (RENDER §4)

Portraits (pages already in the post-load DC-RAM image at HUD TEX base + loc; writers `FUN_14060d560`/`FUN_1406162e0`/`FUN_140616330`, INFERRED arithmetic); combo counter (`blkstate.pnodes` reads blk directly, rule gated 24/24 and 82/82; emitter port outstanding — `pnodes` absent from both `reader.rs` and `tape_to_seq.py`); scripted camera (P/V bytes at `ctx+0x1f816c/0x1f812c` post-tick); HUD list-0xB coverage (no 96-node cap); torn frames (gone). Neutral: LUT lag, post chain / bloom decision.

## 7. Ledger

| Item | Tag |
|---|---|
| Frame function read set; render pass inside the frame; 0-byte emulation gate | CONFIRMED |
| DC-RAM write set = regenerated scratch only; anchor carry list complete | CONFIRMED (237 frames, training stage) |
| PL slot recipe, 11 files, 66/66 byte-exact | CONFIRMED |
| Loader path from the in-memory AFS image; the load-time patch list | CONFIRMED / patches partly INFERRED (DCRAM §2.3) |
| Stage animation drivers (Carnival, River Raft) | CONFIRMED both read; 15 stages unclassified |
| Δ=0 arena layout | CONFIRMED (harness) |
| `gs+0x964/0x968` render-only; `game_state+0x770` not read by the tick | INFERRED |
| H1 callback-before-draw ordering on real stages | INFERRED — test named |
| ctx `+0x200073..0x20040C` (669 B) changes, no owner in the read set | UNKNOWN — test named |
| `FUN_140619960()` dispatcher mode byte | UNKNOWN |
| Every polygon-list object on a HUD/effect-heavy frame inside blk/dcram/ctx (trace was a 5-node idle frame) | UNKNOWN |
| `+0x1F0` 12 KB PL region writer (`FUN_140612180`) | INFERRED |
| Tail builder consumer of `DAT_142ec6d00` | UNKNOWN |
| Receipt → sim state, 60 frames of a real offline match (Gate 0) | CONFIRMED 60/60 |
| Pixel-exact receipt end to end | NOT PROVEN — Gates 1–5 |

## 8. Knowledge graph

Seeds from this workstream: `maplecast-flycast/tools/re_kb/112_runner_dcram_writeset.surql` (RE §9) and `113_runner_dcram_map.surql` (DCRAM §8), applied with `PYTHONIOENCODING=utf-8 python tools/re_kb/apply_seed.py <seed>` after the documented backup. Corrections carried (DCRAM §5): `FUN_14060dd40`→`loc_8c0275f6` (not `loc_8c042d0c`); `FUN_140620200`→`loc_8c108430`; `FUN_1408435d0↔loc_8c03552a` conflicts with TEXTURE-BANKS (LZSS pairs with `FUN_140614210`, INFERRED); flycast-lane "GFX2 self-modify" not observed on Steam on this frame (OPEN, needs a Storm trace).

## 9. Relationship to Track R (full replays from geometry tapes)

Track R ships now and keeps shipping; the runner converges with it at the tape: a runner tape is a v5 tape, so every Track R consumer (rr-render, player, PWA, stream) is unchanged. Track R's remaining size lever (animated prop poses, §2 Q3) is the same RE the runner needs, done once.

## 10. Rules for this workstream

Never guess — cite Ghidra, a file:line, a dump, or say UNKNOWN. No time estimates. BYOR: no ROM/exe/arc bytes in any repo; outputs derived from them are gitignored. Do not propose TTD/WinDbg time-travel for this title. Full absolute commands for every live step; live tests as "▶ READY, do X then tell me".
