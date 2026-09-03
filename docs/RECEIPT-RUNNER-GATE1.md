# RECEIPT-RUNNER-GATE1 — the native runner ticks the real frame function and matches the p-code oracle byte for byte (2026-09-03)

Owner lane: senior-re-generalist. Workstream: `docs/WORKSTREAM-RECEIPT-RUNNER.md` s4 step 1; design of record
`docs/RECEIPT-RUNNER-RE.md` s2–s3. Deliverable: `d3dcap/receipt/runner/` (`rr_runner.cpp`, `build.bat`, `runner_gate.py`).

## RE METHOD (locked; `docs/RE-METHOD.md`)

1. Port the SH4 annotations to the Steam binary by function matching.
2. Seed with unique constants, then propagate along the call graph.
3. Translate globals through the block map before comparing reference sets.
4. Tag CONFIRMED versus INFERRED, and store the pairs as edges in the knowledge graph.

Step this document is at: **4**. Every address the runner uses is a CONFIRMED pair/global from `FRAME-READSET.md`,
`DETERMINISM-CONTRACT.md` and `RECEIPT-RUNNER-RE.md`; the three corrections found here (s3) were derived from the harness's
own trace records plus same-boot export resolution, not from a fresh top-down trace, and are stored in
`maplecast-flycast/tools/re_kb/114_receipt_runner_gate1.surql`. Tags: **CONFIRMED** = reproduced by a byte gate on real
images; **INFERRED** = read in the disassembly, gate-consistent; **UNKNOWN** = not located. No time estimates anywhere.

## 0. Result

| gate | inputs | ticks | blk byte-exact vs the p-code harness | clock | per tick (ms, p50 / max) |
|---|---|---|---|---|---|
| idle | both seat words 0 | 20 | **20/20** (0 of 211,736 B differ on every tick) | 1716 → 1736, 20/20 | 0.078 / 0.291 |
| tape | the stage-9 receipt's seat words (from the oracle job) | 60 | **60/60** | 1716 → 1776, 60/60 | 0.071 / 0.230 |
| tape | same, 300 ticks | 300 | **300/300** | 1716 → 2016, 300/300 | 0.072 / 0.398 |

After the 300 ticks the runner's `game_state` page, the exe page `0x142edf300..0x600`, the sprintf scratch
`0x142eed900..` and the GGPO counter are also identical to the harness's (0 B differ). The p-code harness takes 3–7 s per
tick; the native runner takes **0.04–0.40 ms** (mean 0.08 ms), i.e. ~200× inside the 16.67 ms real-time budget. This is
the number Tris asked for: the frame function itself is not the cost of a playable runner; the render/emit path will be.

**Gate 1: PASS.** Falsification runs (one variable each, same oracle): `--gs file` (the tape anchor's game_state page
instead of the exe-embedded one) 300/300; `--fma 1` (FMA3 CRT path) 300/300; `--prot rwx` 20/20; `--crt real` **trapped
at tick 1** (s3.3 — a falsified design assumption, recorded); `--lazy off` **fatal at tick 1 with the exact site** (s3.4).

Tape rows (px/py/hp/clock per frame): the tape file `local_1788462750766_stage9_76561197999665347.json.gz` is **no longer
at** `%LOCALAPPDATA%\RetroReceipts\gs-cache-local\` (the folder now holds only later stage-0 tapes; `gs-cache` holds
online tapes without anchors) — UNKNOWN where it went. The column therefore rests on transitivity: `receipt_gate.py`
PASSED 300/300 on clock/px/py/hp against that tape using **exactly the dumps** the runner reproduces byte for byte
(`WORKSTREAM-RECEIPT-RUNNER.md` s4 step 0). `runner_gate.py --tape <file>` runs the column directly when the file is back.

## 1. What the runner does (`d3dcap/receipt/runner/rr_runner.cpp`)

| step | what | evidence / gate |
|---|---|---|
| 0 | reads `meta.json` + `game_state.bin`; arena = `*(game_state+0)`; asserts `ctx == arena+0x8000000`, `dcram == arena+0x8400000`, blk inside the 256 MiB arena; asserts the runner's own image is outside both ranges (normal `/DYNAMICBASE /HIGHENTROPYVA` exe, lands at `0x7ff6..`) | RECEIPT-RUNNER-RE s2 |
| 1 | `VirtualAlloc` the arena at the anchor's address (`0x07FC1000` here) and the image at `0x140000000`, RESERVE+COMMIT; **fails loudly** listing every busy region if the exact base is not returned. ⚠ the arena base is not 64 KiB-aligned (it is an offset into a larger game allocation), so the request is rounded to allocation granularity and the rounded base is what is checked | first run failed exactly here until rounded; both reservations succeed in a fresh process |
| 2 | loads `exe_image.bin` (68,059,136 B), `blk.bin`, `blk2.bin`, `ctx.bin`, `dcram.bin` at their live addresses. `--gs exe` (default) keeps the game_state page embedded in the image = what the harness maps (`emu_frame.frame_job` maps only `exe_image.bin`); `--gs file` overlays `game_state.bin` (the anchor's page) | s2 falsification: both 300/300 |
| 3 | IAT `0x1408db000..0x1408db880` (257 slots): replaces 5, traps 252 (per-slot thunk `mov ecx,id; jmp rr_trap` → prints slot, resolved name, return address, tick; exit 6). UCRT lazy-resolver cache `0x142eefca0`: re-encodes entries 5/6 to runner functions, traps 3/15/20/22. Names come from same-boot export resolution of the dumped values (kernel32/ntdll/KERNELBASE bases are per boot; on another boot the names read "unresolved" and the runner still works — the replacement is by slot address) | s3; `iat_map.txt` in every output dir |
| 4 | `DAT_142ebc010` → zeroed 256 KiB runner buffer (debug ring); `DAT_142eefbd8` → 0 (`--fma`); seat map `game_state+0x258.. = {0,1,-1,-1}` | DETERMINISM C2/C3, RE s3.1 |
| 5 | page protections from the (packer's) section table: code `RX`, `.rdata` `R`, `.data` `RW`, the two runtime sections `RWX` (`--prot rwx` = whole image RWX); C1 self-checks (18 asserts: gs+0/+0x10/+0x1B0/+0x1B8/+0x208, `DAT_142edf560/580/628`, `DAT_142ef0ab0`, `DAT_142e10b98 == 0`, `ctx[0..2]`, `ctx+0x1f81b0`, `ctx+0x1f80a4 == 1`, self-pointer permutation, mode bytes 2/1/2, clock == meta) — refuses to tick on any FAIL | all 18 OK on this run |
| 6–7 | on a 16 MiB-stack thread (single thread, C9): asserts `MXCSR == 0x1F80` (C3), then per tick `inputs = {w0 & 0xFFFFFF, w1 & 0xFFFFFF, 0, 0}`, `FUN_140118950(&DAT_142d10b90, inputs, 0)`, QPC timing, clock check (+1), `blk_tNNN.bin` dump; at the end `gs_out/ctx_out/exe_dat_out/exe_str_out/ggpo_out.bin` (same names as the harness) and `summary.json` (timings, external-call counts, lazily committed pages) | s0 |

Replacement semantics = exactly the harness's (`EmuGate` `extstub on` + `emu_frame.CRT_SLOTS`): `RtlAllocateHeap` → 16-aligned
chunk of a zeroed 64 MiB bump heap (never freed; the CRT asks `HEAP_ZERO_MEMORY`), `RtlReAllocateHeap` → new chunk (never
called), `HeapFree` → 1, `GetLastError` → 0, `SetLastError` → no-op, `FlsGetValue` → 0, `FlsSetValue` → 0. Measured per
tick: 4× each (8× on the first tick), 1,558,480 B allocated over 300 ticks (0x3C8-byte ptd × 4 per tick + the first-tick
extras) — the leak the design predicted; harmless at 5 KB/frame for Gate 1, addressed only by a CRT-free path (s3.3).

## 2. Gate script (`d3dcap/receipt/runner/runner_gate.py`)

```
cd C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\receipt\runner
python runner_gate.py --run C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\runs\receipt-20260903-stage9-anchor --mode all --ticks 60 300 --json %TEMP%\rrcap_runner\gate1_final.json
python runner_gate.py --run <run> --mode idle20 --runner-args "--crt real" --suffix _crtreal      # one-variable variants
```

Oracles (all in `%TEMP%\rrcap_emu`, game-derived, never in git): idle = `determinism_gate.py multitick --ticks 20 --tag
multitick_stage9_20` (new `--tag` so runs stop clobbering each other); tape = `receipt_gate.py --frames 60|300` dumps
`receipt_receipt-20260903-stage9-anchor_1716_{60,300}.blk_tNNN.bin`. The tape mode takes its inputs **from the oracle's
job file** (`set4 30000000/30000004` before every `run`), so the byte-exact comparison is fully defined without the tape;
`--tape` adds the px/py/hp/clock-vs-rows column through `receipt_gate.compare`. On a mismatch the script prints the first
differing byte, `emu_frame.Labeler` names its structure (fighter/node/G/… with the DC-mapped offset), and the diff ranges.
Builds the runner via `build.bat` (MSVC 2022 BuildTools, same toolchain as `d3dcap/build.bat`) if `rr_runner.exe` is missing.

## 3. Findings (each changes a document of record; all in seed 114)

### 3.1 IAT slot `0x1408db218` is `kernel32!TlsSetValue`, not `FlsSetValue` (CONFIRMED)
Same-boot export resolution of the dumped IAT values: `0x1408db240` ntdll!RtlAllocateHeap, `0x1408db140` ntdll!RtlReAllocateHeap,
`0x1408db238` kernel32!HeapFree, `0x1408db2d8` kernel32!GetLastError, `0x1408db510` kernel32!SetLastError, **`0x1408db218`
kernel32!TlsSetValue**. The harness's `extret` on that slot never fired (the trace's 24 kind-3 records use four IAT slots
and two non-IAT targets). `emu_frame.CRT_SLOTS` is annotated accordingly; no harness result changes.

### 3.2 The tick's `FlsGetValue`/`FlsSetValue` go through the UCRT lazy resolver, not the IAT (CONFIRMED)
`FUN_140820798` = `try_get_function`: cache `0x142eefca0 + id*8`, entry = `rol(ptr, cookie & 0x3f) ^ cookie`
(`__security_cookie 0x140ab12d8`), decoded `-1` = unavailable; id 5 FlsGetValue (thunk `FUN_140820b80`, `call rdi` at
`0x140820bbe`), id 6 FlsSetValue (thunk `FUN_140820bd8`, `call rsi` at `0x140820c21`). Live entries in the image: 3 FlsAlloc,
5, 6, 15 GetSystemTimePreciseAsFileTime, 20 InitializeCriticalSectionEx, 22 LCMapStringEx (all KERNELBASE). A loader must
rewrite entries 5 and 6 (the runner re-encodes its own functions; round trip asserted). Under the harness both returned
RAX = 0, so `FlsSetValue` "failed" and the CRT freed its fresh ptd — that is where the 4× `HeapFree` per frame comes from.

### 3.3 A working FLS grows the import set: RECEIPT-RUNNER-RE s3.1 "real per-thread slot" is falsified as designed (CONFIRMED)
`--crt real` (FlsGetValue returns the stored ptd, FlsSetValue stores and returns 1): tick 1 traps on
`ntdll!RtlEnterCriticalSection` (IAT `0x1408db190`, from RVA `0x81e478`) — the CRT continues its ptd/locale initialisation.
The C6 import set is six only under the stub semantics. The runner default is `--crt stub`; the leak is the price.

### 3.4 On a real-match frame the tick writes a host-heap object of the dumping process (CONFIRMED) — the s5.3 failure mode, met
First native tick, `--lazy off`: `EXCEPTION 0xc0000005 at RIP 0x14004d460 (RVA 0x4d460) tick 1 — WRITE 0x2a2b5154, outside
every mapped image; RBX 0x2a2b5158 RDI 0x2e60 RSI 0x6f R9 0x10; stack: … 0x14061268a`. Decode: `0x2a2b5154 − *(0x140acd3a8)
(= 0x2a1dc010) = 0xD9144 = 0xD8D04 + 0x440` → the host PALETTE_RAM upload (`PALETTE-SOURCE-GHIDRA`: `FUN_140613390` uploads
the staged palette rows to `dev+0xd8d04`); the loop at `0x14004d400` is a PAL4 → 32-bit nibble expansion (`×0x11`), reached
from `FUN_1408456a0` ← `0x140612685` (texture-slot fill after the `FUN_140845fa0` slot search). The traced training-stage
idle frame never touched this object (its only out-of-image accesses are the debug ring `*(DAT_142ebc010)`), the stage-9
anchor frame does on tick 1. `emu_frame.EXE_GLOBALS` labels `0x140acd3a8` "session ptr" — INFERRED wrong; it is the NaomiLib
host device object (size UNKNOWN; other `.data` pointers into the same page: `0x140ad3b30`, `0x140bd3bb8`).

Runner behaviour (default `--lazy on`): a vectored handler zero-commits the 64 KiB page on first touch and **logs it with the
touching PC** — the harness's sparse-memory model made explicit; every such page is listed at the end with the `.data`
globals that point into it. Over 300 ticks exactly **one** page was committed. Because the tick only WRITES it (the
harness's `uninit` list for the 300-tick receipt has no read there), a zero page is sufficient for a byte-exact blk; for a
pixel path (Gate 5) the loader must provide the real object — a task for the flycast-internals lane.

### 3.5 Beyond blk: 86 dwords of the ctx texture-page table differ after 300 ticks (CONFIRMED mechanism; render-side)
`ctx_out` runner vs harness: 344 B in 86 four-byte fields at stride 0x130 (records `+0x6C`, idle run also `+0x114`) in
`ctx+0x10DE24..0x114DB4`, beyond the `pages` part the determinism gate hashes; harness 0, runner a stale value (run-dependent
for idle, `0x69749048` in all three tape runs), the live image floats (`1.0`, `−1.0`, `0.66`…). Stage-9 traced tick: the
records are `memcpy`-d (`0x14080062e`, 95 × 0x130 B) from a **stack buffer** (`0x313fed40..0x313feebf`) whose fields
`+0x6C/+0x114` hold whatever earlier code left there — zero in the zero-filled harness, leftovers natively and live. These
fields are never read by the tick (0 reads in both traced ticks). This is DETERMINISM s5.2's "re-run on a real-stage frame"
item: uninitialised stack DOES reach ctx (render-side page-table records) on this frame, and does NOT reach blk. Everything
the determinism gate hashes (`ta1/ta2/pages/slots/matrix`) is identical.

### 3.6 `determinism_gate.py multitick` ticked runs 2..N with stale registers (CONFIRMED, fixed)
`EmuGate run` only sets RIP/RSP; the job set `RCX/RDX/R8` once, so runs 2..20 called the tick with the previous run's
leftover RCX (the GGPO counter ended at 1 after 20 runs: `multitick_*.ggpo_out.bin = 01`) and read `inputs` from wherever
RDX pointed (sparse zero memory = idle by accident). blk dumps were still correct — the counter is wrapper-only (C2) —
which is why the idle gate passed 20/20 against them. `cmd_multitick` now re-sets the three registers before every run.
`receipt_gate.build_job` always did (counter 300 after 300 ticks, equal to the runner's).

## 4. What is CONFIRMED / INFERRED / UNKNOWN after Gate 1

| item | tag |
|---|---|
| The native tick on the dump images reproduces the harness blk byte for byte (idle 20, receipt 60 + 300) | CONFIRMED |
| Δ=0 arena at `game_state+0` + image at `0x140000000` is reservable in a fresh normal process | CONFIRMED (this host) |
| The C6 import set = 5 IAT slots + 2 UCRT-cached pointers; 252 + 4 traps, 0 hits over 380 ticks | CONFIRMED |
| Section-table protections (RX/R/RW/RWX) suffice; RWX not needed | CONFIRMED |
| The 23 differing bytes of the anchor's game_state page are sim-irrelevant | CONFIRMED (300 ticks) |
| FMA3 vs SSE2 CRT path: identical blk over 300 ticks | CONFIRMED (C3 on the whole tick) |
| Real FLS → RtlEnterCriticalSection; stub semantics are the contract | CONFIRMED |
| `*(0x140acd3a8)` = host device object, PALETTE_RAM at +0xD8D04, write-only from the tick | INFERRED (offset arithmetic + PALETTE-SOURCE) / write-only CONFIRMED on 300 ticks |
| ctx page-table fields +0x6C/+0x114 = stale stack, never read | CONFIRMED on the two traced ticks; consumer on a pixel path UNKNOWN |
| Runner == live game on a second boot (IAT names unresolved, arena address free) | UNKNOWN — the runner is designed for it (replacement by slot address, lazy pages), not yet run |
| Tape-row column (px/py/hp) on the runner's own dumps | transitively CONFIRMED (byte-identical dumps passed 300/300); direct run pending the tape file |

## 5. What remains for Gate 2 — the harvest over runner memory → v5 tape

Gate 2 (`WORKSTREAM-RECEIPT-RUNNER.md` s4 step 2): the agent's harvest (`reader.rs`: rows `GS_SCHEMA`, `nodes`, `anodes/aobjs`,
`palrows`, `bg`) run over the runner's memory instead of `ReadProcessMemory`, emitting a v5 tape; master gate
`runner_tape_gate.py` = 100 % per column vs the live agent tape after the six live-only noise classes are excluded
(RENDER s2.3–2.4). Concretely:

1. **Expose memory.** The runner already holds blk/blk2/ctx/dcram/game_state at the live addresses; add a `--serve` mode
   (named shared memory or a sidecar process reading via `ReadProcessMemory` on the runner's own pid — the latter reuses
   `reader.rs` verbatim, memory feedback-port-proven-code-asis) and a per-tick barrier (`blk+0x3CC8` edge) so the harvest
   samples a settled frame. Nothing between ticks touches blk (RE s3.3), so torn rows vanish by construction.
2. **Pointer normalisation.** `anodes.model` / `nodes.gfx1` are host-absolute (into dcram); with Δ=0 they equal the live
   values, so the live tape and the runner tape agree without translation on this data pair; keep the DC-address
   normalisation for the general case (RENDER s2.3).
3. **Objects the harvest reads outside blk/dcram.** None per RE s3.3 (`palrows` = `blk+0x13C0`, objects at `*(node+0xA0)` in
   dcram). The ctx page-table residual (s3.5) and the host device object (s3.4) are not harvested — irrelevant for Gate 2,
   relevant for Gate 5.
4. **The tape file.** Gate 2 needs the live tape of the same match as the reference; locate or re-record
   (`local_1788462750766_stage9…` is missing from the cache — UNKNOWN; the agent's `KEEP_TAPES` flag exists but is dated
   before that match).
5. **Oracle for Gate 2** = `tape_vs_dump_gate.py` logic over runner dumps (`states_to_tape.py` extended for `palrows` and
   dcram objects) vs the live tape, per column, torn-row classification reported.
6. Carry-overs from this gate into Gate 3 (loader from the arc): rewrite UCRT cache entries 5/6 (s3.2), provide the device
   object (s3.4) or keep the lazy page for sim-only use, and the per-boot arena/link-base reservation check.

## 6. Commands

```
rem build
C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\receipt\runner\build.bat
rem 300 receipt ticks, dumps + summary in %TEMP%\rrcap_runner\tape300
C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\receipt\runner\rr_runner.exe --pre C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\runs\receipt-20260903-stage9-anchor\pre --out %TEMP%\rrcap_runner\tape300 --ticks 300 --inputs %TEMP%\rrcap_runner\tape300\inputs.txt
rem the gate (idle 20 + tape 60 + tape 300)
python C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\receipt\runner\runner_gate.py --run C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\runs\receipt-20260903-stage9-anchor --mode all --ticks 60 300
rem regenerate the oracles (Ghidra headless; one at a time)
python C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\replay\determinism_gate.py multitick --run <run> --ticks 20 --tag multitick_stage9_20
python C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\replay\receipt_gate.py --run <run> --tape <tape.json.gz> --frames 300
```

## 7. Address index (new in this doc)

`FUN_140820798` try_get_function (cache `0x142eefca0`, module cache `0x142eefc00`, cookie `0x140ab12d8`) · `FUN_140820b80` /
`FUN_140820bd8` Fls thunks (`0x140820bbe` / `0x140820c21` cached calls) · IAT `0x1408db000..0x1408db880`: `0x1408db140`
RtlReAllocateHeap, `0x1408db190` RtlEnterCriticalSection, `0x1408db218` TlsSetValue, `0x1408db238` HeapFree, `0x1408db240`
RtlAllocateHeap, `0x1408db2d8` GetLastError, `0x1408db510` SetLastError · `0x140acd3a8` host device object (PALETTE_RAM
+0xD8D04) · `FUN_14004d400` PAL4 expansion loop (write site `0x14004d460`) ← `FUN_1408456a0` ← `0x140612685` · `0x14080062e`
memcpy into the ctx page table (records 0x130 B from a stack buffer) · arena `0x07FC1000` (this boot), blk `0x15AC1000`.

Seed: `maplecast-flycast/tools/re_kb/114_receipt_runner_gate1.surql` (backup `re_kb_data/_exports/re_kb_20260903-184246_pre114.surql`).
