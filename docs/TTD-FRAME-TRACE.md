# TTD frame trace — per-frame READ SET of the live Steam MvC2 process (2026-09-02)

RE METHOD step this serves: **2 (propagate along the call graph) and 3 (translate globals before comparing
reference sets)**. A Microsoft Time-Travel-Debugging trace of a few seconds of OFFLINE play gives, per engine
frame, the exact set of Steam functions executed and every `blk[]` offset each of them read/wrote — the
dynamic READ SET that the static crawl (`docs/STEAM-SH4-FUNCTION-MAP.md`) can only approximate. It is also
the input the offline p-code harness (`d3dcap/replay/emu_gate.py`, other lane) needs to run whole frames.

Everything here is in `d3dcap/ttd/`. All outputs land in `d3dcap/ttd/runs/<timestamp>/` which is **gitignored**
(traces and memory images are game-derived and multi-GB; BYOR).

## 0. Facts this depends on (CONFIRMED unless marked)

| fact | value | evidence |
|---|---|---|
| process | `MarvelVsCapcomFightingCollection.exe` (`C:\Program Files (x86)\Steam\steamapps\common\MARVEL vs. CAPCOM Fighting Collection\`) | live `Get-Process` 2026-09-02; `d3dcap/session-guided.ps1:35` |
| live image base | `0x140000000` == Ghidra base (no relocation observed) — scripts still resolve RVA against the live base | live `MainModule.BaseAddress` 2026-09-02 |
| `blk` | `*(exe+0x2EDF560)` == `*(*(exe+0xACD3A0)+0x1B0)`, size `*(+0x1B8)=0x33B18`; live `0x17FD1000` (heap) | `docs/STEAM-CODE-MAP.md` game_state table; live read 2026-09-02 |
| frame clock | `blk+0x3CC8` u32, +1 per game frame; idle in menus | `docs/TAPE-V3-SPEC.md:43`; live read (6728, static while idle) |
| memory model | `base=*PTR_DAT_140acd3a0`; `ctx=*(exe+0x2EF0AB0)=base+0x8000000`; `ctx[1]=base+0x8400000` = DC work-RAM image (DC `X` at `ctx[1]+(X-0x0C000000)`); `ctx[2]=blk` | `docs/STAGE-DRAW-GHIDRA.md` s2; live: dcram `0x11BD1000`, blk = base+`0xE8<<20` closes |
| render dispatcher / sprite walker | `FUN_140620960` / `FUN_140620f10` (once per frame) | `docs/STEAM-SH4-FUNCTION-MAP.md` s3 |
| GGPO callbacks | struct built at `RSP+0x30` in `FUN_140118ae0`: begin=`FUN_1400365e0`, save=`FUN_140119380`, load=`FUN_140118fa0`, log=`FUN_1400365e0`, free=`LAB_140118f90`, **advance_frame=`FUN_140118f00`**, on_event=`FUN_140119010` | Ghidra disasm `0x140118aff..0x140118b77` + decompiles, 2026-09-02 (this lane) |
| **the sim tick** | `FUN_140118950(&DAT_142d10b90, inputs[4], flags)` — called by the advance_frame callback between `ggpo_synchronize_input` (`FUN_140119a60`, size 0x10) and `ggpo_advance_frame` (`FUN_1401198d0`) | decompile of `FUN_140118f00` |
| GGPO save region | `0x100004` bytes from `0x142D10B90` after a gather (`FUN_1401188c0`); `blk` is a registered sub-region, not the buffer itself | decompile of `FUN_140119380`; live `DAT_142d10b90 != blk` |
| **TTD `-attach` BLOCKED by ntdll hooks (CONFIRMED owner = the exe)** | in the live game 16 ntdll exports start with `E9` (JMP) instead of the syscall stub `4C 8B D1 B8`; TTD fails `GetNtdllAPIAddresses() failed for NtResumeThread` (runs `20260903-000941`, `20260903-001536`). `LdrLoadDll` hook -> `gameoverlayrenderer64.dll+0xad1a0` (overlay). The 15 `Nt*` hooks -> one private RWX page of push-ret stubs whose **64 return targets all lie in the exe's own RWX section** (VA `0x03092000`, chars `0xE0000040`, targets `exe+0x311ddf0..+0x3124720`, handler prologue `55 48 89 E5 ...`) = the packed retail exe's runtime/protection layer. Overlay-off cannot clear `NtResumeThread` (INFERRED; falsify with `preflight.py` after an overlay-off relaunch). Remedy = `record.ps1 -Launch` (TTD starts the exe on a clean ntdll). | `preflight.py` 16-byte RPM compare on pids 72816/63992/56376; JMP/push-ret follow + PE section table read live; `*.out` logs; seed finding `steam_overlay_hooks_block_ttd` |
| offline main-loop caller of the tick | **UNKNOWN** — the trace names it (`ret_rva` of the `FUN_140118950` call in `calls_f<k>.jsonl`) | — |

## 1. Tooling (installed 2026-09-02 via winget, no elevation needed for the install)

| tool | where | note |
|---|---|---|
| TTD recorder | `winget install --id Microsoft.TimeTravelDebugging --exact` -> `%LOCALAPPDATA%\Microsoft\WindowsApps\ttd.exe` (1.11.611.0) | `ttd.exe -accepteula -help` verified. **Recording requires admin**: non-elevated attach fails `0x80070005 "Administrative privileges are required"` (verified). |
| WinDbg + cdb + TTD replay | `winget install --id Microsoft.WinDbg --exact` -> `%LOCALAPPDATA%\Microsoft\WindowsApps\{WinDbgX.exe,cdbX64.exe}`; package dir `C:\Program Files\WindowsApps\Microsoft.WinDbg_1.2606.22001.0_x64__8wekyb3d8bbwe\amd64\{cdb.exe,ttd\TTDReplay.dll,winext\JsProvider.dll}` | `cdb version 10.0.29617.1000`; `.scriptload extract.js` verified on a live notepad target. |
| Python | 3.13 (`python` on PATH, fallback `C:\Python313\python.exe`) | stdlib only (ctypes, json, csv, urllib) |

Not used (documented alternatives): the TTD Replay C++ API / airbus-cert `ttd-bindings` (would remove the
cdb+JS hop, needs a native build); `dx -r2` text output parsing (fallback if JsProvider misbehaves).

## 2. ▶ READY — recording (the user does this)

**Primary path (the only one that can work on this title, see section 0): `-Launch`.** Quit the game first; TTD starts
the exe itself (SteamAppId 2634890, Steam must be running, same direct-launch recipe as `d3dcap/launch_suspended.ps1`),
records into a ring buffer (last `-RingMB 8192` MB), the game runs ~10x slower through the menus; get into an
**OFFLINE** match (Versus or Training), and when you are fighting press ENTER in the elevated window: it snapshots
(`pre/`) and stops. One UAC prompt.

```
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\record.ps1 -Launch
```

Attach path (kept for the case where `preflight.py` ever passes, e.g. a future exe build without the syscall hooks):
be in an **OFFLINE** match (Versus or Training), fight actively so the frame clock advances. Never online:
TTD slows the game roughly 10x and GGPO would desync. The script refuses if `*(exe+0x2E10B98)` (GGPO session)
is non-zero. Expect one **UAC prompt** (TTD needs admin).

```
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\record.ps1 -Seconds 3
```

**Pre-flight (automatic, before the UAC prompt):** `record.ps1` runs `preflight.py` on the target and REFUSES (exit 3,
nothing attached) if `ntdll!NtResumeThread` or any other export TTD needs starts with `E9`, if `gameoverlayrenderer64.dll`
is loaded, if TTD DLLs are already in the process, if a debugger is attached, or if ACG is on. Remedy printed by the
check:

1. Steam > Library > right-click *MARVEL vs. CAPCOM Fighting Collection* > Properties > General > untick
   **"Enable the Steam Overlay while in-game"** (or globally: Steam > Settings > In Game > same switch).
2. Quit the game completely, relaunch from Steam, enter an OFFLINE match.
3. Verify (must list no overlay module and exit 0):
```
powershell -NoProfile -Command "(Get-Process MarvelVsCapcomFightingCollection).Modules | Where-Object { $_.ModuleName -match 'overlay' } | Select-Object ModuleName,FileName"
python C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\preflight.py
```
4. `preflight.py` reports `NtResumeThread` = `E9` even though the hook handlers live in the exe (section 0): then the
   attach path is dead by construction and `-Launch` is the path. (The Live Recorder API from our shim is the further
   fallback if `-launch` were ever refused; not built.)

What it does (`record.ps1`): pre-flight -> resolves the pid -> **pre-snapshot** (`dump_live.py`: `pre\meta.json blk.bin blk2.bin
game_state.bin ctx.bin dcram.bin exe_image.bin`, read-only, 0.5 s) -> `ttd.exe -accepteula -noUI -out <run> -module
MarvelVsCapcomFightingCollection.exe -attach <pid>` -> waits for the `.run` to appear -> sleeps `-Seconds` -> `ttd.exe -stop <pid>`
-> **post-snapshot** -> prints the trace path. Options: `-AllModules` (record every thread/module, bigger),
`-NoDump`, `-TargetPid N`, `-Seconds N`. 3 s of game time under a 10x slowdown is ~30 s wall; the game resumes at
full speed after `-stop`.

Why the live snapshots: a TTD trace only contains bytes the recorded instructions touched; untouched pages
replay as unknown. `extract.py` merges the trace's known pages over `pre\` to produce whole images.

## 3. Extraction (headless replay)

```
python C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\extract.py --run C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\runs\<ts> --frames 3 --first-frame 1
```

Runs `cdbX64.exe -z <trace.run> -c ".scriptload extract.js; dx @$scriptContents.run(\"<cfg.json>\"); q"`. First open
builds the `.idx` index (minutes for a multi-GB trace). Stages, all logged to `extract\extract_log.txt`:

1. `probe.json` — modules in the trace, trace lifetime, the property names the TTD Memory/Calls objects expose
   (API-drift diagnostic), one sample of each.
2. `frames.json` — frame boundaries: every **write to `blk+0x3CC8`** (`TTD.Memory(clock, clock+4, "w")`) with
   position `seq:steps`, writing IP and the value written. Frame `k` = `[boundary_k, boundary_k+1)`.
   `--boundary walker|dispatcher|tick|advance_frame|rva:0x...` switches to "each call to that function".
   NOTE: the clock write is *inside* the tick, so a clock-bounded frame = tail of tick k + render k + head of
   tick k+1. Use `--boundary tick` (calls to `FUN_140118950`) for a tick-aligned frame once the trace confirms
   it is reached offline.
3. `calls_f<k>.jsonl` — every call into the tracked function set inside the window, ordered by position:
   `{t, te, fn, rva, sym, ret, ret_rva, tid}` (`t`/`te` = call start/end `seq:steps`; `ret_rva` = the caller's return
   site, module-relative; `rva` is `null` when the IP is outside the module). **Calls are queried by NUMERIC ADDRESS
   only** (`host.currentSession.TTD.Calls(host.Int64, ...)`, chunks of `--calls-chunk 64`); the game exe has no
   symbols and a symbol pattern raises "No symbols found". Symbol targets (`funcs_sym`, synthetic mode only) are
   resolved once via `host.getModuleSymbolAddress` (exports suffice; `kernel32!Sleep` resolves to 0 = forwarder, so it
   is skipped). Order of targets: the 4 anchors first (`0x620960` dispatcher, `0x620F10` walker, `0x118950` sim tick,
   `0x118F00` advance_frame cb) so the per-frame gate exists even if the remaining chunks are slow, then the 10,794
   game-range functions from `d3dcap/replay/re_map/steam_funcs.jsonl` (`--all-funcs` for all 29,678).
4. `blk_f<k>.jsonl` — every read/write inside `[blk, blk+0x33B18)` aggregated per `(ip, offset, size, rw)`:
   `{off, size, rw, ip, rva, n, first, value}`.
5. `dcram_f<k>.jsonl` — reads of the DC-RAM host image (`--dcram-mb 16` default) per `(ip, 4 KB page)` with the
   exact min/max address touched; `--dcram-detail` keeps exact addresses.
6. `dump_f<k>_{blk,ctx,dcram,game_state}.bin` — memory **at the first window boundary** (`SeekTo` + page-wise
   `readMemoryValues`; unknown pages listed in `dump_f<k>.json`). `extract.py` then writes `runs\<ts>\{blk,ctx,dcram}.bin`
   = trace pages with holes filled from `pre\` (`*.merge.json` says which). These are the emu-harness inputs. In `-Launch` mode `pre/` is the snapshot taken right before `-stop` (there is no process before launch); it is still a valid hole-filler because a page the trace does not know was never written during the recording, so it is byte-identical at the boundary and at the snapshot.

Post-processing (offline, no server): RVA -> `FUN_14xxxxxxx` by body containment, SH4 pair + tier from
`docs/steam_sh4_map.csv`; per frame `frame_<k>.json`; `summary.csv` (frame,fn,name,sh4,role,ncalls,blk_reads,
blk_writes,dcram_reads); `readset.csv` (fn,name,sh4,off,size,rw,count,frames).

Scale guard: 3 s at 60 fps = ~180 frames; the game issues on the order of 10^5 calls and 10^5–10^6 blk accesses
per frame, and every event crossing into JavaScript costs. Default window = 3 frames. `--frames N` widens it;
`--max-events` caps a runaway scan. Measure on the first real trace before widening.

## 4. Graph join + seed

```
python C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\join_kb.py --run C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\runs\<ts> --frame 1
python C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\join_kb.py --run ... --frame 1 --apply     # backup + apply_seed.py
```

Joins `frame_<k>.json` with `steam_routine ->recompiles-> routine` (re_kb :8001), writes
`extract\readset_f<k>.md` (function | SH4 pair (conf) | role | calls | blk reads | blk writes | DC-RAM pages) and the seed
`maplecast-flycast/tools/re_kb/35_ttd_frame_readset.surql`: `source:ttd_trace_<ts>`, `finding:ttd_f<k>_frame_<ts>`
(executed functions in first-call order), one `finding:ttd_readset_<FUN>` per function that touched blk/DC-RAM
(`status='confirmed'` — dynamic evidence), `about`/`cites` edges with explicit ids, and
`steam_routine.ttd_blk_reads/ttd_blk_writes/ttd_frames` (kept separate from the static crawl fields). The seed also
carries the GGPO callback pairs found while building this (section 0). `--apply` takes the README backup
(`re_kb_data/_exports/`) then runs `apply_seed.py` per statement.

## 5. Synthetic proof (no game needed) — what has and has not been proven

```
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\synthetic_test.ps1 -Seconds 2
```

`synthetic_target.py` mimics the game's shape (a fake `blk` with a u32 clock at `+0x3CC8` ticking every 16 ms, a
fake DC-RAM buffer it reads, `ntdll!NtDelayExecution` calls per tick); the driver records it (UAC), then runs
`extract.py --synthetic`. Expected: `frames.json` with ~120 boundaries whose `value` increments by 1, `blk_f<k>.jsonl`
containing the `+0x100` write and `+0x3CC8` write, `dcram_f<k>.jsonl` with the `+0x200` read, `calls_f<k>.jsonl`
with one `NtDelayExecution` per frame.

Status 2026-09-03: **PROVEN end to end on a real trace** (`runs/synthetic-20260903-000729`, `python01.run` 56 MB,
2 s): attach/stop cycle; 119 clock-write boundaries, `value` +1 each, one writer IP; `blk_f5..7.jsonl` = the `+0x3cc8`
write, the `+0x100` write and the `+0x3cc8` read with correct values; `dcram_f5..7.jsonl` 3 records/frame; all three
boundary dumps written with 0 unknown pages (binary `WriteBytes` path); **`calls_f5..7.jsonl` = exactly 4 ordered calls
per frame** (`NtCreateTimer2 -> NtSetTimerEx -> NtWaitForMultipleObjects -> NtClose`, one each, with start/end
positions and return addresses). Two bugs were found and fixed by this run: (1) `Calls` by symbol string fails on
anything without symbols -> numeric addresses only; (2) module lookup by substring picked `python3.DLL` over
`python.exe` -> exact basename match first. Python 3.13 `time.sleep` does NOT call `NtDelayExecution` (measured:
`NtCreateTimer2/NtSetTimerEx/NtWaitForMultipleObjects`), so the synthetic target list was corrected. The static part
of the seed (GGPO callback pairs, section 0) was applied to the live graph 2026-09-02 after backup
`re_kb_data/_exports/re_kb_20260902-235523.surql` (16 statements, 0 failed).

Re-extraction on an existing trace (no new recording), the exact command used:

```
python C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\extract.py --run C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\runs\synthetic-20260903-000729 --synthetic C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\runs\synthetic-20260903-000729\synthetic_cfg.json --frames 3 --first-frame 5
```

For the real run drop `--synthetic` (the game cfg is built from `pre\meta.json`):

```
python C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\extract.py --run C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\runs\<ts> --frames 3 --first-frame 1
```
`--skip-replay` re-runs only the post-processing on an existing `extract\`. Still UNPROVEN until the real trace:
throughput of the 10,794-target `Calls` scan and of the blk/DC-RAM `Memory` scans at game event volumes (the synthetic
trace has ~360 events; the game has 10^5-10^6 per frame).

## 6. Output schema (per frame, `extract\frame_<k>.json`)

```
{ "frame": k, "t0": "seq:steps", "t1": "seq:steps", "clock_value": <u32 written at boundary>, "boundary": "clock",
  "calls": [ {"t","te","fn":"0x14......","rva","ret","ret_rva","tid","name":"FUN_...","sh4":"loc_8c......","sh4_conf":"confirmed|high|medium|low","role","inlined"} ... ],   // ordered by t
  "blk":   [ {"off":"0x3cc8","size":4,"rw":"r|w","ip","rva","n":count,"first":"seq:steps","value":"0x..","fn","name","sh4"} ... ],
  "dcram": [ {"ip","rva","lo","hi","page","dc_lo":"0x0c......","dc_hi","size","rw":"r","n","first","fn","name","sh4"} ... ] }
```

## 7. Falsification tests to run on the first real trace (before trusting anything)

1. `frames.json`: boundary `value`s must increase by exactly 1 per boundary and all boundary IPs must be the same
   instruction (one writer of the clock). Two writers or gaps => the clock is not the frame boundary we think.
2. `calls_f<k>.jsonl` must contain exactly one `FUN_140620f10` (walker) and one `FUN_140620960` (dispatcher) per
   frame. Zero => the render ran on a thread the `-module` filter dropped (rerun with `-AllModules`).
3. `FUN_140118950` (tick) must appear once per frame with a non-GGPO `ret_rva` (offline). Absent => the offline
   loop uses a different tick entry; find the writer IP of the clock in `frames.json` and walk up from it.
4. `blk_f<k>.jsonl` must show `FUN_140620f10` reading `0x3f78, 0x6928, 0x6d08, 0x324d0` (the static crawl's
   `blk_reads` for it — `steam_routine:FUN_140620f10` in re_kb). Missing => the RVA->function mapping or the blk base is wrong.
5. `blk.bin` from the trace vs `pre\blk.bin`: differences must be confined to offsets that appear as writes in
   `blk_f<j>.jsonl` for j < k. Anything else => a writer outside the recorded module(s).
