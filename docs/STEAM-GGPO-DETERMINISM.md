# STEAM GGPO DETERMINISM — the match IS the input stream

**Status: PROVEN END-TO-END ON THE LIVE GAME, 2026-08-26.** Everything here was measured against a
running MARVEL vs CAPCOM Fighting Collection, not inferred. Where something is inferred it says so.

This document **supersedes** several facts in `RetroReceipts-agent/docs/STEAM-REPLAY-ANSWERS.md`,
`STEAM-REPLAY-PLAN.md` and `STEAM-REPLAY-HANDOFF.md`. Corrections are in §6 — read that before
trusting an older page.

---

## 1. The headline

MvC Fighting Collection ships **verbatim GGPO rollback netcode**. Its spectate path is
`ggpo_start_spectating` (`FUN_1401199d0`): a spectator receives **INPUTS ONLY**, runs the identical
local simulation, and gets **no initial-state transfer at all** — it joins at frame 0 and derives
character select, stage and everything else by simulating the same input stream.

Because it is rollback, the engine must register the region it saves/restores. It registers
**exactly one**:

> ## `blk[0 .. 0x33B18)` — 211,736 bytes — IS the complete deterministic simulation state.

Registration: `FUN_140118290` sets `DAT_142d10950 = 1` (one region), `DAT_142d107d0 = G[0x1b0]`,
`DAT_142d108d0 = G[0x1b8]`. The memset+register is `FUN_140608690` @ `0x1406086a7`.
**VERIFIED LIVE:** the size field at `0x140AC6EF8` reads exactly `0x33B18`.

**What GGPO actually proves.** GGPO rewinds and re-simulates constantly during every online match.
Anything that CHANGES during a match and lives outside the registered region would not be restored
on rollback, and peers would desync within MAX_PREDICTION_FRAMES. Online matches complete.
Therefore:

> `blk` contains every piece of state that **changes** during a match.

### ⚠⚠ THE LIMIT OF THAT PROOF — corrected 2026-08-26, read before relying on this page
**Rollback-sufficiency is not replay-sufficiency.** State that is set once *before* a match and only
*read* during it never needs restoring, so rollback works perfectly without it — and the proof above
says nothing about it. The stronger claim, "`blk` is the complete deterministic simulation state",
does **not** follow from GGPO and is **not yet proven**. An earlier version of this page and the
0.3.24 release note both asserted it as certified. They were wrong to.

What has been checked since:
- ✅ **Settings and unlocks are INSIDE.** `FUN_140608690` (match init) copies difficulty/damage/time
  options into `blk+0x3C40…0x3D07` and builds a 56-bit roster/unlock mask at `blk+0x3CE8/0x3CEC`
  (observed `0xf8ffffff / 0x07ffffff` = exactly 56 bits = the MvC2 roster) — so the anchor carries
  them. ⚠ Which also means **an anchor is per-account identifiable**.
- ✅ **Stage selection is INSIDE** — the DC layout carries `STG_ID` twice, mapping to `blk+0x6D3C`
  and `blk+0x32530`.
- ❓ **THE RNG IS THE OPEN COUNTER-EXAMPLE.** On DC/NAOMI — the same game code — the sim RNG is an
  LCG at `0x8C16BC2C`, `s = s*0x41C64E6D + 0x3039`, seeded `srand(1)`, with **54 call sites** across
  the character-program and effect banks, sitting **~1 MB outside** the block that became `blk`. If
  the x86-64 recompile left it as a static, it is not rolled back and not carried by an anchor.
  `replay-kit/verify.py rng` settles this in about a minute: an LCG is uniquely identifiable from
  two samples, because only the real generator satisfies `x1 == x0·A^k + B_k`.
  The "two replays were bit-identical" evidence does **not** cover this — both ran back to back in
  one process, and damage calculation consumes zero RNG, so a short tape passes either way.
- ❓ **A second block exists.** `FUN_140608690` also allocates `blk2 = blk + 0x33B18`, size `0x33B20`,
  registered at `G+0x1c0`/`G+0x1c8` — **not** in the rollback list, therefore never restored.
  `verify.py blk2` reports whether it mutates during play (mutating ⟹ derived output, safe).

### ⚠ AND THE REGISTRATION IS A FORK
`FUN_140118290` branches on `G+0x48`: **`< 3` registers 10–18 regions** (that is the emulated-CPS
path the collection's CPS2 titles use); **`>= 3` registers the single `G+0x1b0`/`G+0x1b8` pair**.
Live value on MvC2 is **11**. Everything on this page depends on being on the `>= 3` arm — assert it,
never assume it. (This is also the answer to how the collection's *other* games work: differently.)

⚠ `0x33B18` is the **same size the agent already reads every frame**. We have been capturing the
complete deterministic state all along and discarding all but a few fields.

---

## 2. What was demonstrated (live, in this order)

1. **Save state.** Snapshot `blk` (0.2 ms) → play 59 s including a character TAG → write it back
   (4.8 ms) → the sim jumped back and the state matched the snapshot exactly. No crash.
2. **Load straight to character select.** Snapshot at char select → start a match → restore →
   back at character select; picks and the match then proceeded normally.
3. **Input replay + determinism.** Restore a snapshot, feed the recorded input stream, and the
   match reproduces. **Two replays from one tape produced BIT-IDENTICAL end states** — same end
   frame (21559), hp 16, position (1245.0, 140.884) to three decimals, sprite id 512.

### The mode discriminator
`blk+0x3CB8[2]` — **1 = character select, 2 = in battle**. Observed: `[2,1,1,3,0]` char select,
`[2,1,2,3,2]` in battle. The mode lives *inside* the blob, which is why restoring a char-select
snapshot pulls the sim out of a live fight.

### ⚠ The shell does NOT restore with the sim
`blk` is the **simulation**. The MT Framework UI/shell state is outside it. Restoring a
character-select snapshot leaves that screen rendering garbled until the shell re-syncs (it
self-heals on confirm). Cosmetic, but users see it. In-match restores render correctly because the
in-match renderer is driven from the draw list inside `blk`.

---

## 2b. ⭐ CHARACTER-SELECT DETECTION — solved, two memory reads

We tried this many ways over months (menu scripting, `ydotool` key automation, the MENUNAV recipe,
screen scraping). **None of that is needed.** Both the screen and the cursor are plain reads.

### Which screen are we on
```
mode = blk + 0x3CB8   (5 bytes)
    byte[2] == 1  -> CHARACTER SELECT      observed [2,1,1,3,0]
    byte[2] == 2  -> IN BATTLE             observed [2,1,2,3,2]
```
Byte 2 is the discriminator. Verified repeatedly across many launches and both directions of the
transition. Watching for the 2→1 edge gives a reliable "character select just opened" event.

### Which character the cursor is on
> **`blk + 0x3DB8 + i*0x738 + 0x6C0`** — the fighter slot's CID field.
> **The character-select cursor writes its selection straight into the fighter slot.**

Found by differential capture: park P1 on one character, capture `blk`; move to another, capture
again, diff. Exactly two words changed meaningfully —
```
blk+0x04478  0x..003a -> 0x..0034     ( = blk+0x3DB8+0x6C0, slot 0 CID )
blk+0x03db8  0x..3a01 -> 0x..3401
```
`0x3a` = 58 = **Servbot**, `0x34` = 52 = **Sentinel** — the exact two characters selected.
Slots are the usual interleave (even = P1 team, odd = P2 team), so P1's cursor is slot 0
(`blk+0x4478`) and P2's is slot 1 (`blk+0x4BB0`).

The remaining ~62 differing words are floats (`0x3f800000` = 1.0f) in `blk+0x1e000..0x2a000` — the
rotating character preview models. Presentation only; safe to ignore or carry.

### Why this matters beyond replay
- **Host node / auto-host:** detect the screen and read the picks without driving menus or scraping
  pixels. Supersedes input automation for *observing* state (still needed to *drive* the shell).
- **Money matches / wagers:** read both teams the moment they lock in, BEFORE the fight starts —
  team verification and wager locking no longer depend on a client report.
- **Match identity:** teams are readable from a `blk` snapshot alone (`H+0x6C0` per slot), which is
  how `.rr4` tapes carry their team list with no side-channel metadata.

### ⚠ Char-select state is PORTABLE; battle state is NOT
A character-select `blk` snapshot restores cleanly into a DIFFERENT process (PROVEN: captured at
`blk=0x15ce1000`, restored at `0x180e1000` — a 36 MB delta — 804 intra-blk + 243 arena pointers
relocated, self-check passed, game continued at 60 fps, and the cursor snapped to the saved
character). The identical procedure with a BATTLE state killed the process twice: a battle state
holds 557 pointers into the decompressed per-character asset image, and relocation fixes their
addresses but not the fact that the bytes there belong to whichever characters that session loaded.
At character select no characters are loaded, so there is nothing to dangle.
⟹ **Anchor every portable savestate at character select.**

## 3. The input chain — MEASURED

While playing (146 distinct positions over 8 s), input appears at three places:

```
G+0x218 (RAW pad, 24-bit)  →  12-entry bit table @ 0x140A4F780  →  blk+0x3C66+i*0x14 (sim)
                                                                →  cl+0x4fc (per-fighter)
```

| address | role |
|---|---|
| `0x140AC6F58 + 4k` (`G+0x218`) | **raw pad, seat k** — THE authoritative word |
| `0x140AC6F68 + 4k` (`G+0x228`) | previous frame |
| `0x140AC6F98 + 4k` (`G+0x258`) | GGPO player k → **seat index** (−1 = unmapped) |
| `blk+0x3C66 + i*0x14` | sim-side (translated); +2 prev, +4 just-pressed, +6 just-released |
| `cl+0x4fc` | per-fighter decoded — **what the agent records today** |

Observed value sets differ between `G+0x218` and the downstream copies, confirming the translation
table sits between them. Only the played seat is non-zero; MvC2 uses **2 seats** (the 4-seat
scaffolding is generic collection code).

> ⚠⚠ **AGENT CHANGE REQUIRED.** `reader.rs:110` labels `KCODE_OFF = 0xac6f58` as
> *"flycast kcode[0] (the LOCAL pad)"*. **It is not a pad — it is `G+0x218`, GGPO SEAT 0's input.**
> Which seat is local comes from `G+0x258`, which we never read. **This is the root cause of the
> documented side-swap.** Record `G+0x218 + seat*4` plus the seat map; add `G+0x76C` (rollback
> count, `0x140AC74AC`) as a tape-quality signal.

### Injecting inputs (offline)
In offline/training the GGPO tick never runs; `FUN_140039de0` reads the pad and stores over
`G+0x218` every frame, ~0x74 bytes before the sim reads it. NOP the two 6-byte stores, then
**restore them**:

```
0x14003A33B:  89 81 18 02 00 00   MOV [RCX+0x218], EAX   (seat 0)
0x14003A35F:  89 81 1C 02 00 00   MOV [RCX+0x21C], EAX   (seat 1)
```
Do **not** touch the `prev = cur` shuffle before each store — the engine keeps just-pressed /
just-released correct from whatever we write.

---

## 4. The `.rrtape` archival format

```
magic  b"RRTAPE01"
u32 + JSON header   {ver, start_frame, frames, teams, ts, note}
u32 + zlib(blk[0..0x33B18))     complete deterministic state
u32 + zlib(per frame: u32 frame, u32 seat0, u32 seat1)
```
Character ids are read out of the snapshot itself (`H+0x6C0`) — no side-channel metadata.

**MEASURED: a 10-second match = 18,569 bytes.** State 211,736 → 17,129; inputs **2.1 B/frame**
compressed. A five-minute match ≈ 55 KB — *smaller* than the lossy GSTA state tape it replaces,
with 100% fidelity including assists, projectiles, effects, stage and HUD.

**Harness needs NO DLL injection.** `RPM/WPM + VirtualProtectEx + SuspendThread` covers snapshot,
restore, input drive and stepping. Do **not** call the game's own `save_game_state` /
`load_game_state` — they touch globals with no locking and would race GGPO and the sim.

### Faster-than-realtime is shipping code
`G+0x798` (`0x140AC74D8`) = frames-to-run; `G+0x770` suppresses rendering on catch-up frames.
`FUN_140039de0` already loops on it. A re-simulation node just sets the counter.

---

## 5. Architecture consequences

- **Agents become input recorders.** ~2 B/frame on the wire plus one snapshot.
- **One host node re-simulates** and every frame of state exists in its memory — everything the
  state tape cannot capture, for free, because it is the real engine.
- **The input stream is the receipt.** A disputed money match is re-simulated and checked, instead
  of trusting a client report.
- **No GGPO session is needed to replay.** We never call a GGPO function; all of the above ran in
  training mode, offline, rollback count 0, seat map zero. GGPO is the *proof* that `blk` is
  complete, not the machinery.
- **No spectate, no lobby, no P2P, no host.** A node just needs MvC2 booted so `blk` exists; the
  tape overwrites the mode.

### ⚠ OPEN: cross-process portability
Everything proven is **within one process**. The blob holds **absolute pointers** — `FUN_140628020`
writes six self-pointers at `blk+0x32500+8k`, each `blk + 0x3DB8 + n*0x738`. **Measured live the
permutation was `{4,2,0,3,1,5}` — it is the LIVE TEAM/TAG ORDER and changes during a match**, so the
self-check is "all six are valid slot bases forming a permutation of 0..5", NOT a fixed order.

The saving grace: `arena = *(u64*)0x140AC6D40` is a single **256 MiB** allocation and everything is
carved from it — `blk = arena + ((shell_rng() & 0x3F) + 0xC0) * 0x100000`, asset image
`arena + 0x8400000`. **VERIFIED LIVE:** arena `0x97e1000`, blk−arena `0xd400000` = 212 MB, asset
image in-arena. So one delta relocates everything. **Pin `blk`** by writing the xorshift128 state at
`0x142E12AB0` (static, WPM-able pre-boot) before the allocation.
**Closing experiment:** run twice with the same forced RNG draw, diff the snapshots; every
8-aligned u64 differing by exactly `arena₂ − arena₁` is a pointer. That yields an exact pointer map.

---

## 6. CORRECTIONS — do not trust the old pages on these

| Doc | Claim | Reality |
|---|---|---|
| `STEAM-REPLAY-ANSWERS.md:119`, `STEAM-REPLAY-PLAN.md:142`, `STEAM-REPLAY-HANDOFF.md:13` | draw list at `blk+0x300D0` "✅CONFIRMED" | **WRONG.** Probed live: `0x300D0` yields ZERO valid entries. It is **`blk+0x2f4d0`**, counts at **`blk+0x324d0`**; `handle(L,i) = u64 @ blk+0x2f4d0 + L*0x300 + i*8`. Layers encode DRAW PRIORITY (two drawn fighters observed in layers 5 and 6). |
| `STEAM-REPLAY-ANSWERS.md:124` | count array `blk+0x330D0` "INFERRED and CONFLICTED — collides with battle-globals at `blk+0x32500`" | **RESOLVED.** Counts are **u8**, 16 bytes at `blk+0x324D0..0x324DF`. No collision: `0x324E0` begins the next struct and `0x32500` is the self-pointer table. The apparent collision came from assuming u32 counts. |
| `reader.rs:110`, `:1195` | `KCODE_OFF` is "flycast kcode[0] (the LOCAL pad)" | **WRONG.** It is `G+0x218` = GGPO **seat 0** post-synchronisation input. Root cause of the side-swap. |
| general | input recorded at `cl+0x4fc` is authoritative | **Two stages downstream and lossy.** Use `G+0x218 + seat*4`. |
| `mvc-arcade-autohost-re` menu scripting (ydotool), replay-theater "MENUNAV recipe" | menus must be driven by input automation | **Superseded for state setup.** A snapshot restores any mode directly, including character select. Input automation is still needed for things outside `blk` (the shell/UI). |

`STEAM-REPLAY-ANSWERS.md` §0 (the 0x16C object-base fix) and the CPS quad-scale findings remain
valid — see `rr-sprite-render-pipeline` in agent memory.
