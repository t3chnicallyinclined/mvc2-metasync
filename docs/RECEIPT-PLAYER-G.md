# RECEIPT-PLAYER-G — Workstream G (Track H): the receipt, played in the real game (2026-09-03)

Goal (WORKSTREAM-CLIENT-REPLAY.md §3b Track H, item G): drive ONE real Steam MvC2 process on this box with the
capture shim, load a tape's character-select anchor, feed the recorded inputs each frame, and have the game itself
walk from character select into the fight and replay the recorded match — then gate the regenerated fighters
against the tape's rows. First proof at real time (the game's own loop); faster-than-real-time is a stretch.

RE METHOD note (docs/RE-METHOD.md): this is a live GATE for the receipt architecture. Every address below is
cited from Ghidra (mvc_dump.bin, :8080) or FRAME-READSET.md; CONFIRMED = read on both sides / reproduced live.

## Result in one line

**The mechanism works and the receipt-as-recorded does not.** The shim's frame-tick hook, the anchor
restore+relocation, the per-tick seat-word injection, the command channel and the gate are all built and proven
live. But driving tape **59613666**'s char-select anchor forward through a running process **selected the wrong
characters and crashed the game at the character-select→battle transition** — a `c0000005` access violation at
`0x1406083be`, inside the battle-globals / entity-list sync (`FUN_140607e90` region), reading the exe-global
entity list `DAT_142edf628` (`0x142edf628`). **0 of 4904 tape rows matched.** This is the falsification the plan
asked for, and it is located to the byte.

## What was built

```
d3dcap/receipt_player.inl          shim addition: FrameTick hook (FUN_140607d60) + %TEMP%\rrcap\CMD command channel
                                   #include'd from dllmain.cpp after the walker hook; installTickHook() beside the
                                   walker hook; rcPoll() in the arm loop. Capture behaviour is untouched.
d3dcap/receipt/replay_receipt.py   the driver: decode tape -> relocate anchor -> command the shim -> gate vs the rows
d3dcap/receipt/gamekeys.py         focus / key-tap / screenshot helper to reach MvC2 char-select (front-end is outside blk)
```

### The hook point — FUN_140607d60, the frame entry (CONFIRMED)
`FUN_140607d60` is the whole frame (sim + render dispatch + walker + submit), reachable only through
`*(game_state+0x10)`, which `FUN_140607b50` sets **once** (`0x140607bef`, disasm `MOV [PTR_DAT_140acd3a0+0x10] = FUN_140607d60`)
and nothing rewrites. Its two callers store the pad words at `game_state+0x218/+0x21C` (`0x140AC6F58/5C`)
immediately before the indirect call: the offline loop `FUN_140039de0` (`0x14003a33b/0x14003a35f`, then `CALL [RAX+0x10]`
at `0x14003a3ac`) and the GGPO wrapper `FUN_140118950` (`pad[seat(k)] = inputs[k]&0xffffff`, then the same call).
So a detour at FUN_140607d60's **entry** lands after the pad store and before the sim translates it
(`FUN_140048630` reads `game_state+0x218+seat*4`); overwriting the two seat words there needs **no code patch**
(the old NOP of the two stores in `replay-kit/inputrec.py` is unnecessary), and the `prev=cur` shuffle that
precedes the store keeps just-pressed/just-released correct. The anchor is written at the same entry, on the game
thread, so the copy cannot tear (the render dispatcher runs inside the tick — nothing else touches blk between ticks).

### The command channel (file-based; the shim polls it in its worker loop)
`%TEMP%\rrcap\CMD` (one line) → `CMD.ack`; live status in `receipt_status.json` every 250 ms. Verbs:
`anchor <blk_hex> <arena_hex> <force> <path>` · `inputs <path>` · `start <log>` · `stop` · `speed <n>` · `status` · `reset`.
Every write-into-game verb is **refused if a GGPO session is live** (`*0x142E10B98 != 0`). The anchor verb also
re-checks the self-check (six self-pointers at `blk+0x32500` are all-zero on a fresh block or a permutation of the
six slot bases) against THIS process's blk before writing.

### Faster-than-real-time (built, not exercised here)
`speed <n>` patches the frames-to-run immediate at `0x14003A2D6` (`MOV [RDX+0x798], imm32`, default 1) that
`FUN_140039de0` drains per vsync (STEAM-GGPO-DETERMINISM §4). Not used in this run (real time first).

## The gate run (tape 59613666: ranked, stage 5, teams p1 [52,44,8] p2 [42,44,50], 4904 rows 1035..5938)

Launched a fresh game via `launch_suspended.ps1` (D3DCAP_MANUAL=1), drove the front-end with `gamekeys.py` to
**Versus Mode** character select (scene 5, mode `[2,1,1,3,0]`, blk resolved, ticking, offline). Then
`replay_receipt.py --tape 59613666 --ignore-arena`:

| step | result |
|---|---|
| anchor decode | 211,736 B, fnv `ed29ac411dfb0cdf` == tape `anchor_hash` ✓, clock 3, mode `[2,1,1,0,0]` |
| relocate | blk `0x13ac1000` → `0x178c1000` (Δ `+0x3e00000`): **257 intra-blk pointers**; the 2 "arena-range" words are the constant `0x10000000`, not pointers (`--ignore-arena`); arena moved `+0x400000` |
| self-check | fresh block (six self-pointers zero) ✓ |
| anchor apply | **OK, applied at a tick**; live clock reset 3024→3, mode → `[2,1,1,0,0]`, game kept ticking |
| inputs | 5934 entries fed, clocks 2..5935 (select_in → clocks 2..690, confirmed_in → 907..5935, gaps 688..906 zero-filled) |
| char select | shell advanced `[2,1,1,1,x]`→`[2,1,1,3,0]`→`[2,1,1,4,x]`; **locked cids `[19,23,20,22,21,6]` — NOT the tape's `[52,44,8]/[42,44,50]`** |
| battle transition | mode reached `[2,1,2,0,0]` at clock 691, then **CRASH** ~66 frames later (`c0000005` at `0x1406083be`) |
| gate | **0 / 4904 rows exact; 4835 missing** (battle never produced a comparable frame) |

720 tick records logged (`fed 714`), anchor flag on the record at clock 3. The last flushed record is clock 653;
the crash lost the ~37 unflushed records after it (1 MB buffer, flush every 60).

## Why it failed — two located reasons, both OUTSIDE blk

1. **The character-select SHELL is not in blk, so the input replay drove the wrong cursor.** The anchor is
   captured at `anchor_frame 3` (before any pick is locked; cids `0..5` placeholder), so the tape's `select_in`
   stream is what must lock the characters. But the MT-Framework front-end / cursor grid lives outside blk
   (STEAM-GGPO-DETERMINISM §2 "the shell does NOT restore with the sim"). Restoring the anchor into a process
   already sitting in its OWN Versus char-select left the shell showing the Versus grid; feeding the online
   char-select inputs walked THAT grid and locked `[19,23,20,22,21,6]`, not the tape's team. Character-select
   navigation through the live shell is not a function of blk + seat words.

2. **Match-init/save-slot-sync walks an exe-global entity list that the receipt does not carry.** The faulting
   instruction (Ghidra):
   ```
   1406083b0  MOV  RAX, [0x142edf628]            ; DAT_142edf628 = the entity list (stride 0x18, type byte @+1; STEAM-CODE-MAP FUN_140607e90)
   1406083b9  MOV  R9,  [RBX + RAX + 0x20]        ; R9 = entity[+0x20]  (a per-entity pointer)
   1406083be  MOVZX R11D, byte [R9 + 0x1]         ; <-- c0000005: R9 is invalid
   ```
   `DAT_142edf628` is an **exe-global pointer to a heap object** (FRAME-READSET.md `ENTITY_PTR_OFF 0x2edf628`;
   `FUN_140607e90` = "battle-globals save-slot sync … walks entity list `DAT_142edf628`"). The receipt carries
   **only `blk[0..0x33B18)`**. It carries neither this entity list, nor the exe `game_state` page, nor the ctx
   slot table — exactly the three extra inputs FRAME-READSET §5 later identified as required
   ("one blk snapshot **plus** the two exe pages … **and** the ctx slot table"). When the shell started a match,
   match-init built a state whose entity linkage was inconsistent with the rewound blk, and the per-frame
   save-slot sync dereferenced a stale `entity[+0x20]` and died.

**This is the same class as the battle-state non-portability the earlier work already found** ("a battle state
holds 557 pointers into the decompressed per-character asset image", rrtape4.py): the receipt is portable enough
to *sit at* character select (proven: anchor applied, game ran) but not to be *driven through the shell into a
match*, because the transition consumes state that lives outside the rollback region and is not relocatable.

## What the loader (G2) must replicate / change

1. **Do not depend on the game's char-select shell.** The anchor must either (a) be re-recorded at the **first
   battle frame** (mode `[2,1,2,…]`), with the fighters and the entity list already built and consistent, or
   (b) carry the picks such that the loader sets them directly (`game_state+0x758` locked picks, STEAM-CODE-MAP)
   and lets match-init build from a coherent blk — never navigate the shell by replaying cursor inputs.
2. **Carry the full read set FRAME-READSET §5 names, not just blk:** blk + the exe `game_state` page
   (`0x140AC6D40+0x1000`) + the `0x142EDF300+0x300` page + the ctx slot table. Without them, `DAT_142edf628`
   and the render-table globals point at the wrong process's heap.
3. **Relocate the entity list too, or rebuild it.** `DAT_142edf628` and the 557 asset pointers are heap-absolute;
   the current relocation only fixes intra-blk and arena-range 8-aligned words. A battle-frame receipt needs its
   heap objects carried and relocated (or the loader must call the game's own loaders to rebuild them from the arc,
   which is the "PL loader table UNKNOWN" open item).
4. **The tick hook and injection point are correct and reusable as-is** (FUN_140607d60 entry, seat words at
   `game_state+0x218/+0x21C`). The failure is entirely in what the receipt CARRIES, not in how it is driven.

## What is proven (reusable regardless of the above)

- The frame-tick hook fires every frame and does not destabilise the game (thousands of clean ticks before/after
  the anchor).
- Seat-word injection at the tick entry reaches the sim (714/720 ticks fed; the char-select shell responded to it).
- Anchor write + relocation + self-check into a *different* process is stable at character select (clock reset,
  mode change, continued ticking) — reconfirms the 0.3.24 finding.
- The safety interlock (refuse on live GGPO session) and the offline preconditions hold.
- The gate (`replay_receipt.py` → `gate.json`) attributes the failure to the exact frame and field.

## Exact commands the owner would run

```powershell
# 1. build the shim (game must be closed — it holds d3dcap.dll)
cd C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap
.\build.bat

# 2. launch the game with the shim inside it (manual arm: capture stays idle)
$env:D3DCAP_MANUAL = '1'
powershell -NoProfile -ExecutionPolicy Bypass -File .\launch_suspended.ps1

# 3. reach OFFLINE character select (Versus or Training). Front-end helper (or do it by hand):
cd .\receipt
python gamekeys.py tap enter           # title -> main menu (waits ~10 s between screens by hand)
python gamekeys.py tap enter           # Offline Play -> Select Game (cursor defaults to MvC2)
python gamekeys.py tap enter           # Start Game -> Select Mode
python gamekeys.py tap left enter      # Versus Mode -> character select
python gamekeys.py state               # expect scene 5, mode [2,1,1,...], blk != 0

# 4. replay the receipt and gate (tape 59613666's arena moved but its arena-range words are constants)
python replay_receipt.py --tape 59613666 --ignore-arena
#   --prepare-only   decode+relocate only (no writes)   |   --speed N   faster-than-real-time
#   --gate-only <dir>  re-score an existing receipt_<id>\ticks.bin
```

Artifacts (all game-derived, kept in %TEMP%, never committed):
`%TEMP%\rrcap\receipt_59613666\{anchor_reloc.bin, inputs.bin, prepare.json, ticks.bin, gate.json}`,
`%TEMP%\rrcap\d3dcap.log` (`[receipt] …` and `[mh] FrameTick …`), `%TEMP%\rrcap\receipt_status.json`.

## Falsification value

The plan (WORKSTREAM §3b, Workstream G) asserted the receipt is playable because "the character-select anchor
restores into a DIFFERENT game process … and the game keeps running at 60 fps (0.3.24)". That is true for
*sitting at* character select. This run shows it is **not sufficient to play the match**: driven forward through
the shell it locks the wrong team and crashes in match-init on the entity list `DAT_142edf628`. The receipt as
recorded by agent 0.3.24–0.3.39 (anchor = blk only) is **incomplete** for Track H; it needs the exe pages + ctx
slot table (FRAME-READSET §5) and either a battle-frame anchor with a relocated heap or a shell-free pick-set
path. Convergence test D3 (is the command list a function of blk alone) is therefore **also** open for the tick:
the tick is not a function of blk alone — it reads `DAT_142edf628` and the exe globals every frame.
