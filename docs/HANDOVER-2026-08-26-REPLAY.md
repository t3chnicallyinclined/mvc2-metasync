# HANDOVER — 2026-08-26 — the replay session

Read this before touching replays, tapes, the agent's capture path, or the sprite renderer.
**The headline: MvC2 Steam ships verbatim GGPO rollback, and we proved end-to-end that a match can
be saved, restored, and replayed exactly — from ~50 KB of data, on any PC that owns the game.**

---

## 0. TL;DR of what changed

| before this session | after |
|---|---|
| Replays = a lossy 188 KB state tape, rendered by our own sprite canvas | A match is an **input stream + a character-select savestate**, re-simulated by the real engine |
| Assists / projectiles / effects / stage / HUD were **unreachable** | All of it comes free — it's the real game running |
| "Can we replay a match?" was an open research question | **Proven working**, bit-identical, twice |
| Menu automation (ydotool/MENUNAV) needed to reach a screen | A **memory write** puts the game on any screen, including character select |
| Tape processing speed unknown | **373× realtime** — a 5-minute match re-simulates in **0.8 s** |
| Character select detection: months of failed approaches | **Two memory reads** |

---

## 1. THE CORE DISCOVERY — GGPO

**MARVEL vs CAPCOM Fighting Collection ships verbatim GGPO rollback netcode.** Spectate is
`ggpo_start_spectating` (`FUN_1401199d0`): a spectator receives **INPUTS ONLY** and runs the same
local simulation. There is **no initial-state transfer at all**.

Because it is rollback, the engine must register the region it saves/restores. It registers
**exactly one**:

> ### `blk[0 .. 0x33B18)` — 211,736 bytes — IS the complete deterministic simulation state.

**This is a proof, not an inference.** GGPO rewinds constantly during every online match; anything
sim-relevant outside that region would desync peers within `MAX_PREDICTION_FRAMES`. Online matches
complete. **VERIFIED LIVE:** the size field at `0x140AC6EF8` reads exactly `0x33B18`.

⚠ **That is the same `0x33B18` the agent already reads every frame.** We have been capturing the
complete deterministic state all along and discarding all but a few fields.

### Proven live, in this order
1. **Save state** — snapshot (0.2 ms), play 59 s including a character TAG, write back (4.8 ms) →
   sim jumped back, state matched exactly, no crash.
2. **Load straight to character select** — snapshot at char select, start a match, restore → back at
   character select; picks and match then proceeded normally.
3. **Input replay + determinism** — two replays from one tape produced **BIT-IDENTICAL** end states:
   same end frame 21559, hp 16, position (1245.0, 140.884) to 3dp, sprite id 512.
4. **Cross-process portability** — a *character-select* state captured in one process restored into
   another with `blk` moved 36 MB; 804 + 243 pointers relocated; self-check passed; game continued
   at 60 fps; **the cursor snapped to the saved character**.
5. **373× fast-forward** — 22,403 sim frames/sec, clean return to 60 fps.

---

## 2. KEY ADDRESSES (all verified live)

```
blk               = *(u64*)(EXE + 0xAC6EF0)      EXE = 0x140000000
blk size field    =  (u32*)(EXE + 0xAC6EF8)      == 0x33B18  (the GGPO region)
arena             = *(u64*)(EXE + 0xAC6D40)      single 256 MiB alloc; blk is carved from it
frame counter     = blk + 0x3CC8
mode              = blk + 0x3CB8   byte[2]: 1 = CHARACTER SELECT, 2 = IN BATTLE
fighters          = blk + 0x3DB8 + i*0x738       even = P1 team, odd = P2
   cid            = H + 0x6C0        <- ALSO the character-select cursor
   draw gate      = H + 0x170
   hp / red       = H + 0x578 / 0x57C
   world x/y      = H + 0x50 / 0x54
   screen x/y     = H + 0x124 / 0x128   (renderer OUTPUT, foot-anchored)
   draw scale     = H + 0x130 / 0x134   (== CpsXScale 5/3, CpsYScale 15/7)
   sprite id      = H + 0x188  (& 0x7FFF)
slot ptr table    = blk + 0x32500 + 8k   six absolute self-pointers = blk+0x3DB8+n*0x738
draw list         = blk + 0x2f4d0 + L*0x300 + i*8   (16 layers, counts u8 at blk+0x324d0)
inputs RAW        = EXE + 0xAC6F58 + seat*4        (G+0x218, 24-bit)
inputs prev       = EXE + 0xAC6F68 + seat*4
seat map          = EXE + 0xAC6F98 + k*4           (G+0x258, -1 = unmapped)
rollback count    = EXE + 0xAC74AC                 (G+0x76C)
frames-to-run     = EXE + 0xAC74D8                 (G+0x798)  <- the fast-forward
skip render       = EXE + 0xAC74B0                 (G+0x770)
shell RNG state   = 0x142E12AB0                    (xorshift128, static, WPM-able pre-boot)
input store sites = 0x14003A33B / 0x14003A35F      (NOP these 6-byte stores to inject offline)
```

### ⚠ CORRECTIONS to existing project docs — the old pages are WRONG
| doc | claim | reality |
|---|---|---|
| `STEAM-REPLAY-ANSWERS.md:119`, `STEAM-REPLAY-PLAN.md:142`, `STEAM-REPLAY-HANDOFF.md:13` | draw list at `blk+0x300D0` "✅CONFIRMED" | **Zero valid entries.** It is `blk+0x2f4d0`, counts u8 at `blk+0x324d0` |
| `STEAM-REPLAY-ANSWERS.md:124` | count array "CONFLICTED, collides with 0x32500" | **Resolved** — counts are u8 (16 B), no collision |
| `reader.rs:110` | `KCODE_OFF` = "flycast kcode[0] (the LOCAL pad)" | It is **G+0x218 = GGPO seat 0's input**. Root cause of the side-swap |
| general | `cl+0x4fc` input is authoritative | **Two stages downstream and lossy.** Chain: `G+0x218` → bit table `0x140A4F780` → `blk+0x3C66+i*0x14` → `cl+0x4fc` |
| `mvc-arcade-autohost-re`, replay-theater MENUNAV | menus must be driven by input automation | **Superseded for state setup** — a savestate restores any screen. Automation still needed to DRIVE the shell (see §5) |

---

## 3. ⚠⚠ THE RULE THAT COST US THREE CRASHES

> **CHARACTER-SELECT state is PORTABLE. BATTLE state is NOT.**

A battle state holds **557 pointers into the decompressed per-character asset image**
(`arena+0x8400000`). Relocation fixes their *addresses* but not the fact that the bytes there belong
to whichever characters that session loaded. Restoring one cross-process **killed the game twice**.

At character select **no characters are loaded**, so nothing dangles. Same relocation code, opposite
outcome. **Anchor every portable savestate at character select.**

### Relocation (needed because blk moves every launch; the arena has been stable)
```
p in [old_blk,  old_blk+0x33B18)  -> += (new_blk  - old_blk)
p in [old_arena,old_arena+256MiB) -> += (new_arena- old_arena)
```
Typical counts: ~804 intra-blk, ~243–557 arena, ~272 exe (delta 0).
**Self-check before writing:** `blk+0x32500+8k` must be the six fighter bases — in **ANY order**,
because that table is the live team/tag order and changes during a match. Not a fixed permutation.

---

## 4. CHARACTER-SELECT DETECTION — solved, two reads

Months of attempts (menu scripting, ydotool, MENUNAV, screen scraping) are superseded for
*observing* state:

```
which screen   : blk+0x3CB8 byte[2]   1 = char select, 2 = in battle
which character: blk + 0x3DB8 + i*0x738 + 0x6C0     <- the cursor writes into the fighter slot
                 P1 = blk+0x4478, P2 = blk+0x4BB0
```
Found by differential capture: park cursor → snapshot → move → snapshot → diff. `0x3a`(58, Servbot)
→ `0x34`(52, Sentinel), exactly the picks.

**Why it matters beyond replay:** read **both teams the moment they lock in, before the fight
starts** — team verification and wager locking stop depending on a client report. Directly
strengthens the money-match trust layer (currently consensus-gate + client reports).

---

## 5. ⚠ THE SHELL / SIM SPLIT — a real boundary, not a bug

`blk` is the **simulation**. The MT Framework **shell** (menus, UI textures, character portraits)
lives OUTSIDE it and cannot be restored.

Consequence: restoring a char-select state **from another screen** works for the sim (mode flips,
match replays correctly) but the select screen renders **grey/garbled** — the shell never ran its
own "enter character select" code, so the portrait textures were never loaded. It self-heals on
confirm.

Tried and **did not work**: forcing the palette dirty flags at `blk+0x1048+row*0x38`. The grid
geometry draws and the portraits are *absent*, so it is not a palette problem. Removed rather than
ship an unproven write.

**If you need the select screen to look right, the shell must navigate there itself** — which is
where the existing ydotool/MENUNAV work still earns its keep. Not for reading state; for driving the
UI so it loads its own assets.

---

## 6. THROUGHPUT — 373× realtime

```
baseline           :     60.0 sim frames/sec
frames-to-run = 8  : 22,403.7 sim frames/sec      (G+0x798, G+0x770 suppresses render)
after restoring 1  :     60.0 sim frames/sec      (clean recovery)

3-min match (10,800 frames) -> 0.5 s   ~7,470 tapes/hour/instance
5-min match (18,000 frames) -> 0.8 s   ~4,480 tapes/hour/instance
```
**Throughput is licence-bound, not compute-bound** — one Steam licence out-processes any realistic
match volume. NOT yet verified: whether per-frame input injection keeps up at 22k fps (arithmetic
says yes — ~44k RPM/WPM ops ≈ 110 ms/sec — but that is arithmetic, not a measurement). Fallback:
`frames-to-run=2..4` is still 90–190×.

**Do NOT build an emulator.** If more concurrency is ever needed, try the cheap thing first:
**swap the state pointer inside one process** (`swapsim.py`, written but UNTESTED). The engine holds
blk in three places that must move together:
`0x140AC6EF0` (G+0x1b0), `0x142EDF560` (render cache), `0x142EDF580` (= blk+0x3CB8).

---

## 7. FILES — everything new or changed

### Working tooling — `mvc-live-skins-quarters/replay-kit/`
| file | what |
|---|---|
| `savestate.py` | snap/restore/info. SuspendThread + RPM/WPM; verifies the frame counter didn't move (torn-read guard) |
| `inputrec.py` | rec/play/probe. Sanity-checks the 12 patch bytes before NOPing, always restores in `finally` |
| `rrtape4.py` | **THE CURRENT FORMAT.** char-select savestate + inputs, relocation, self-check, frame-locked feed, fast-forward past char select |
| `REC4.cmd` / `PLAY4.cmd` | user-run record/play. PLAY4 works from ANY screen |
| `restore_blk.py` | restore a raw `.blk` capture with relocation — the test that proved char-select portability |
| `bootdet.py` | capture/diff `blk` across boots; classifies differences as relocated-pointer vs real |
| `volatile_set.py`, `merge_cursor.py` | compute the volatile byte set (832 B boot-volatile → 1,344 B with cursor) |
| `ffspeed.py` | measures the fast-forward rate |
| `swapsim.py` | **UNTESTED** — run a tape in a shadow buffer inside the same process |
| `rrtape.py`, `rrtape3.py` | superseded (v2 snapshot = crashes cross-process; v3 patch-only = can't restore cursor) |
| `boot1/2/3`, `curA/curB` `.blk` + `.meta.json` | the captures those measurements came from |
| `m115708.rr4` | a working 20 s v4 tape (13 KB) |

### Docs — `mvc-live-skins-quarters/docs/`
- **`STEAM-GGPO-DETERMINISM.md`** — the authoritative findings page. §2b character-select detection,
  §6 corrections table. **Needs copying into `RetroReceipts-agent/docs/`.**
- **`AGENT-REPLAY-CAPTURE-SPEC.md`** — exact agent change, with line anchors
- **`patches/agent-0.3.24-replay-capture.patch`** — applies with `git apply`; 6 hunks
- `HANDOVER-2026-08-26-REPLAY.md` — this file

### Memory (`~/.claude/projects/c--Users-trist-projects/memory/`)
- **`rr-ggpo-determinism.md`** — NEW, the big one
- **`rr-sprite-render-pipeline.md`** — NEW, sprite_id→pixels, CPS scale, draw list, Ghidra gotchas
- `MEMORY.md` — compacted (was near the read limit) + both new entries indexed

### Server
- 2,216 historical tapes repaired (11,060,195 frames) — `.repaired.json.gz` beside originals,
  non-destructive. The 0x16C off-by-one shifted px/py/vx/vy/facing to the wrong character.
- `replay2.html` deployed at `play.nobd.net/replay-canvas/replay2.html` — WebGL2 indexed-colour
  sprite renderer (see §8)

---

## 8. THE SPRITE RENDERER (the session's first half)

Settled against the raw TA capture (`maplecast-flycast/_ryu_capture/probe_body_uv.json`):
```
screen_w = native_w * 1.6666666   (CpsXScale = 640/384)
screen_h = native_h * 2.1428570   (CpsYScale = 480/224)
```
⚠ **CPS scale applies to ART ONLY, never to positions** — world coords already carry it.
⚠ `H+0x130/0x134` ARE the final magnifiers. **Do not normalise them to 1.0** — that was the bug that
rendered everyone at half height.
⚠ Sprite anchors in the bake are **assumed** (`dx=-w/2, dy=-h`), not measured. True anchors are a
foot point in GFX2 pen space; error up to ±112 native px. **PL2A (Storm) is the only character with
real anchors** (oracle-derived) — proof the fix works.
⚠ Indexed atlas bake (`bake_i8.py`) is bit-identical for 5 characters but **fails for most** —
characters whose atlas uses colours beyond `pal128` (banks 0–7). Mean character has 108.6 banks.
Use the existing `rgb_to_indexed.py` (bank+index in separate channels) instead.

**Given §1, this path now only matters for browsers that do NOT have the game.** For anything with
the game, re-simulation is strictly better.

---

## 9. CURRENT STATE / WHAT'S NEXT

### Works today
- Save/restore, load-to-any-screen, input replay, determinism, 373× fast-forward
- `REC4.cmd` / `PLAY4.cmd` end to end on Windows

### Blocked / not done
1. **The agent change is NOT applied.** The patch exists but this session was worktree-isolated to
   `mvc-live-skins-quarters` and could not write to `RetroReceipts-agent`. **The envelope hunk
   references `gs.seat_map`, `gs.rollbacks`, `gs.anchor_b64`, `gs.anchor_blk`, `gs.anchor_arena`,
   `gs.anchor_frame`, `gs.build_id` — those fields do NOT exist on `GsCapture` yet. It will not
   compile until they are added and populated** (logic in the spec §3). Start a session rooted in
   `RetroReceipts-agent` to finish it.
2. **No full-match tape exists.** Everything tested is ≤20 s. A 3–5 minute match with rounds, tag-ins
   and a KO has never been recorded or re-simulated.
3. **Linux/Bazzite port not started.** The box is up and running MvC2 under Proton (`AppId=2634890`,
   reachable at `Tris@192.168.1.183`, key `~/.ssh/maplecast_automation`). Reading ports easily
   (`process_vm_readv`); **writing the NOP patch needs an executable page → ptrace + `/proc/pid/mem`,
   not `process_vm_writev`.** That is real work.
4. **Injection at 22k fps unverified** (see §6).
5. **Per-user anchor variance unmeasured.** Three cold boots on ONE machine differ by only 832 B, but
   two different accounts (different character unlocks, options) have never been compared. This
   decides whether a canonical base + delta is 3 KB or 30 KB per tape.

### The architecture to build toward
```
agent (inputs + char-select anchor, ~50 KB)
   -> host node re-simulates at 373x (0.8 s / match)
      -> full per-frame state in memory: assists, effects, stage, HUD, damage
         -> stats/receipts live  +  a rich state tape for browsers that lack the game
```
The input stream is also the **verification receipt** — a disputed money match is re-simulated and
checked instead of trusting a client report.

### Prior art to copy (do not reinvent)
Fightcade's MvC2 runs on **Flycast Dojo** (`flycast-dojo-ref/` is already checked out). Their
`.flyr` v3 stores the savestate **BY REFERENCE** (MD5 + git commit SHA), never embedded, fetched
from a versioned store. Old replays keep working via a **server-supplied per-match version number**
that re-gates emulator behaviour, plus shipping a frozen older binary for pre-2021 replays.
**Copy that versioning model** — determinism holds for identical builds ONLY, and Steam auto-updates.

---

## 10. HOW TO WORK ON THIS

- **Measure, don't theorise.** This session burned hours on four confident wrong explanations
  (camera zoom, sprite anchor, flight mode, sibling block). Every one died to a measurement that
  took minutes. If you catch yourself explaining a symptom, go measure it instead.
- **Verify against ground truth, not self-consistency.** An early "100% confirmed" test only checked
  the data against itself. Compare renders to real screenshots; compare replays to recorded outcomes.
- **The user runs the game.** Give a command they run on their own timing (`REC4.cmd`), don't start a
  timed capture and hope they're ready. That friction wasted several cycles.
- Ghidra: the retail `mvc.exe` is **Enigma-packed** — useless statically. Use
  `C:\Users\trist\ghidra_projects\dumpproj` → `mvc_dump.bin` (runtime dump at 0x140000000).
  MCP dies if port 8080 is taken; the plugin only binds when a CodeBrowser tool opens.
