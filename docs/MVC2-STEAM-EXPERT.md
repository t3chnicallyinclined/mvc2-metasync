# MvC2 Steam Build — Reverse-Engineering Expert Context

Authoritative reference for reading live game state out of the **Steam MARVEL vs CAPCOM Fighting
Collection** (app 2634890) — the memory model, what's stable vs volatile, how it differs from the
Dreamcast ROM, and the plan to get always-fresh, correct data with no scan-induced lag.

Companion sources on disk:
- `marvelous2/` (cloned at `c:\Users\trist\projects\maplecast-flycast\marvelous2` and `refs/marvelous2`) —
  full SH4 disassembly of MvC2 **NTSC-U Dreamcast**. Authoritative **guest-space** layout.
- `maplecast-flycast/` — the OPEN flycast our King-of-Marvel browser build uses. Shows how flycast maps
  Dreamcast RAM into host memory and how `maplecast_gamestate.cpp` reads the DC state. The Steam build is a
  *closed* flycast-derivative — use this to know which host-side global to look for.
- Ghidra 12.1.2 + GhidraMCP at `C:\g\ghidra_12.1.2_PUBLIC`; exe copy `C:\g\mvc.exe` (image base
  `0x140000000`); project `C:\g\ghidraproj\mvc`. GhidraMCP is a GUI CodeBrowser plugin — the Ghidra window
  must be open on the `mvc` program for the MCP to reach it.

---

## 1. What the Steam build actually is

MvC2 on Steam is the **original Dreamcast/NAOMI game code running inside a flycast-derived emulator**. The
Windows process `MarvelVsCapcomFightingCollection.exe` is the *emulator (host)*; the *game* is emulated
inside it. This means there are **two memory spaces**, and conflating them is the root of every bug so far:

| | Host space | Guest space (emulated Dreamcast) |
|---|---|---|
| Whose memory | flycast (the .exe) | MvC2's own SH4 code |
| Base | `exe_base` (ASLR-randomized per launch) | DC `0x8C000000`–`0x8D000000` (16 MB main RAM) |
| Lives here | input `kcode`, the guest-RAM pointer, netplay/Steam session | fighter structs, health, char_id, match state |
| Addressing | `exe_base + fixed_offset` (stable offsets) | DC addresses fixed by the game code |

**The bridge:** `host_addr = guest_ram_host_base + (dc_addr − 0x8C000000)`. `guest_ram_host_base` is a flycast
allocation; a **flycast global holds a stable pointer to it**. Find that pointer once → every DC game address
becomes a fixed, live read.

---

## 2. Stable vs volatile — why signature-scanning keeps failing

**Stable (anchors we can trust every launch):**
- `exe_base + fixed_offset` → flycast host globals. **Proven:** local input `kcode[0]` @ `exe_base + 0xac6f58`
  (active-HIGH, neutral 0; side-agnostic — tracks the local player regardless of P1/P2).
- flycast's **guest-RAM base pointer** (a static global at a fixed exe offset) — **TO FIND**. This is the master key.
- DC addresses are fixed in guest space (set by the MvC2 code).

**Volatile (do NOT rely on absolute host addresses):**
- ASLR randomizes the module base each launch.
- flycast allocates guest RAM + working/rendering buffers dynamically — different every run, and **rollback
  netcode keeps many savestate copies** of the fighter data.
- Our current "reversed struct" (0x738 stride working buffer) is one of those volatile copies. Scanning for a
  *signature* finds **any** matching buffer — including a **frozen rollback/post-match copy**. That is exactly
  the W/L bug: a frozen buffer with P2 permanently at 0 → phantom P1 "wins" every cycle.

**Takeaway:** follow the game's **own pointer** to the structure it's actively using (always the live one)
instead of scanning for a look-alike. Pointer-following also eliminates the ~1 GB scans that cause frame
hitches — a targeted read of a few addresses is microseconds and never pauses the game.

---

## 3. marvelous2 — authoritative GUEST-space layout (Dreamcast NTSC-U)

Use for **what to look for and the relative layout**, not as literal offsets on Steam (see §5 caveat).

- Fighter array `player_start` @ **DC 0x8C268340**, stride **0x5A4**, order `[P1C1,P2C1,P1C2,P2C2,P1C3,P2C3]`.
  `char_id` @ `+1` (1..58), `health` @ `+0x420` (0..144, `HP_FULL`=144).
- Globals page ~`0x8C2896xx`: `in_match` @ `0x289624` {0,1}; `match_sub` @ `0x289621`; `round` @ `0x28962B`;
  `timer` @ `0x289630`; `stage` @ `0x289638` (0..0x14); `Battle State` @ `0x2895F0`; meter P1/P2 @
  `0x289646/48`; combo P1/P2 @ `0x289670/72`.
- `frame_counter` @ **0x8C3496B0** (advances every emulated frame — best liveness signal).
- Char-select: `Charsel_Input` @ `0x8C28C474`; char-select data @ `0x8C28C490`.

### 3a. CONFIRMED flycast memory model (from `maplecast-flycast/core/hw/mem/addrspace.cpp`)

- `u8* ram_base;` is the **master global** — flycast reserves the whole guest address space in one block and
  `ram_base` points at its base.
- Main DC RAM: `mem_b.setRegion(&ram_base[0x0C000000], RAM_SIZE)` → **guest main RAM = `ram_base + 0x0C000000`**
  (DC Area-3 physical base 0x0C000000, 16 MB, mirrored to 0x10000000).
- Therefore a DC virtual address maps to host as: `host = ram_base + (dc_addr & 0x1FFFFFFF)`. For the game's
  cached view `0x8Cxxxxxx`: `host = ram_base + 0x0C000000 + (dc − 0x8C000000)`.
- **This build looks near-IDENTITY** (`ram_base ≈ 0`): the app already calls host `0x0C000000` "the
  identity-mapped guest ROM" and reads the fighter working-buffers/DatPals at host `0x10000000–0x14000000`
  (which is exactly the 0x10000000 RAM mirror region). If `ram_base == 0`, then **DC `0x8C268340` → host
  `0x0C268340`**, fixed, no pointer chase.
- **FASTEST validation (needs the game running, ideally in a match):** probe host `0x0C000000 + (dc − 0x8C000000)`
  for a few marvelous2 addresses and see if they read plausibly + animate. Note: dcfind already showed the
  marvelous2 *layout* (0x5A4 / char_id+1 / health+0x420) does not live-match on this build — so once the base
  is confirmed, the fighter/health/in_match **offsets must be re-derived for this build** (event correlation),
  using marvelous2 only for semantics + relative layout.
- If NOT identity: find the `ram_base` global in Ghidra (a `u8*` written by `virtmem::init`, read by every SH4
  mem helper as `*(T*)(ram_base + (addr & mask))`), then read it at runtime for the base.

### 3b. RUNTIME probe findings (`scratchpad/rambase`, game at a MENU)

Committed guest-memory regions (this launch, PID varies):
- **`0x085e0000 .. 0x095e0000` — 16 MB** RW (DC-main-RAM sized; read all-zero at menu).
- **`0x095e0000 .. 0x295e0000` — 512 MB** RW = the whole guest address-space reservation → **`ram_base ≈ 0x095e0000`**
  this launch (ASLR'd — not constant). The app's working buffers (host `0x10000000–0x14000000`) sit *inside*
  this 512 MB block.
- Structured non-zero guest data reads at **`ram_base` (0x095e0000)+**, NOT at `ram_base+0x0C000000`.

**marvelous2 DC offsets DO NOT map** at any candidate base (`0x155e0000`, `0x085e0000`, `0x095e0000`): in_match/
stage/fighters all read garbage or zero, and the `0x3496B0` "frame counter" was static. Combined with §5, this
is decisive: **the Steam build's guest layout is materially different from the DC NTSC-U ROM — marvelous2 is a
semantic reference only, not an offset map.** The fighter/health/state offsets for THIS build must be found by
runtime correlation.

**Caveat:** the probe ran with the game at a MENU (no live match → no fighters, frame counter not advancing),
so it can only locate the reservation, not the live match struct. Next probe must run **in a live match**.

**Next concrete step (needs a LIVE match):** differential / pattern search inside `ram_base+` —
1. We already know the current roster char_ids from the app's working-buffer scan; search the guest RAM for a
   6-value char_id pattern to locate the Steam fighter array + its stride.
2. Find health = the per-fighter field in `0..=144` that DROPS when that fighter takes damage (diff-scan across
   a known hit). Confirm BOTH sides update (the whole point — P2 must not read 0).
3. Find in_match / match-result the same way (toggles entering/leaving a match).
Then anchor via `ram_base` (found by the 512 MB-reservation fingerprint, or a Ghidra static pointer) and read
those offsets directly — live, both-sides, no scan.

### 3c. Authoritative LOCAL SIDE (from `maplecast-flycast/core/network/ggpo.cpp`)

- **`static int localPlayerNum;`** — flycast's netplay stores the local player's number: **0 = P1, 1 = P2**. This
  is THE authoritative local side (the thing our input-correlation `inputdec` only *guesses* — and got wrong:
  it locked P2 while the user was P1, which swaps the panel characters AND inverts recorded W/L).
- `kcode[]` is indexed **by player**: `state.kcode = kcode[player]`. The local pad's real input lands in
  `kcode[localPlayerNum]`; on this build the app reads `kcode[0]` @ `exe+0xac6f58` and sees the local input
  regardless of side (so kcode[0] alone does NOT reveal the side — `localPlayerNum` does).

**Reality:** the Steam exe is import-obfuscated + stripped; Ghidra shows **no xrefs to `kcode` (0x140ac6f58)**,
so statically extracting `localPlayerNum` is a slow, uncertain hunt.

**Tractable AUTHORITATIVE runtime method (not a churn heuristic):** the local player's emulated per-player
input equals `kcode[0]` **exactly** every frame; the remote player's input comes from the network (differs).
So while the user presses buttons, find the guest per-player input slot that **exactly matches** decoded
`kcode[0]` — its side = the local side. Deterministic (exact equality, not correlation). This replaces the
`inputdec` (which used marvelous2 Input_DEC offsets that don't map on this build). If that proves flaky, fall
back to finding `localPlayerNum`/`localPort` in Ghidra by the GGPO input-collection loop (`kcode[player]`).

## 4. maplecast-flycast — host-side reference

`maplecast_gamestate.cpp` reads those DC addresses and broadcasts them. It proves the **DC field map** and,
more importantly, shows **how flycast reaches guest RAM from host** (the `mem_b` main-RAM array / `_vmem`
address space). The Steam build has the analogous global; find it in Ghidra by the same shape.

---

## 5. Steam build DIFFERENCES from the DC ROM (confirmed empirically)

The Steam Fighting Collection is **not** byte-identical to the NTSC-U Dreamcast ROM — likely a NAOMI/arcade or
re-release build. Evidence and consequences:
- `dcfind` scanned committed memory for the exact marvelous2 layout (6 fighters @ 0x5A4 / char_id+1 /
  health+0x420) and got **1844 coincidental hits, 0 with animating fighters** → the literal DC offsets do
  **not** map, or the guest-RAM base wasn't anchored. The `frame_counter` @ 0x3496B0 did not advance for any
  candidate; meter/combo read garbage.
- Our empirically-found Steam **working struct** has stride **0x738** (≠ DC 0x5A4), with `char_id`/`color`/
  `health`/`datpal` at Steam-specific offsets — a *different* structure than marvelous2's char struct (it
  carries `DatPal`, a render pointer). This is a working/render buffer, not the authoritative game struct.

**Method that follows from this:** use marvelous2 for the **semantics and relative layout** (there IS a
6-fighter interleaved array; there IS a health field; `in_match`/`stage`/`timer` cluster together), then, once
we have the **guest-RAM anchor**, locate the **actual offsets for this build** empirically by correlating with
live events (take damage → find the field that drops; enter/leave match → find the flag that toggles).

---

## 6. Known-good vs known-broken reads today (all cross-process RPM)

**Working:**
- Roster / picks — `CHAR_SIGS` scan of the working-buffer window `0x10000000`–`0x14000000`. Reliable.
- Local side (P1/P2) — input correlation (`kcode` + XInput), `inputdec` locks it deterministically.
- Live Paint — direct `WriteProcessMemory` into each fighter's DatPal, with a read-back safety gate.

**Broken / unreliable (the current focus):**
- **Both-sides live health** — the located buffer is a frozen/volatile copy; **P2 reads 0 permanently**.
  Root cause of the W/L misattribution. (gs-42 added `saw_both` + a liveness-preferring `find_array` as
  stopgaps, but the real fix is the pointer anchor.)
- **Opponent SteamID** — whole-memory scan for high-dword `0x01100001` is noisy; co-located "names" are memory
  junk (`googleapis.com`, `"…you while waiting for opponent"`). gs-42 rejects obvious junk, but the identity
  needs a real source (flycast netplay/Steam session global, or the in-process Steam API).
- Match state / round / meter / combo — DC offsets don't map (see §5).

---

## 7. THE PLAN (pointer-path RE)

**Goal:** stable, always-live reads with zero scanning → correct both-sides health, real match state, real
opponent, no frame hitches.

1. **Find flycast's guest-RAM base pointer** (Ghidra, `mvc.exe`, image base `0x140000000`).
   - Anchor off the known `kcode` global (`exe_base + 0xac6f58`) — flycast's input state. The RAM base pointer
     is a sibling flycast global; find xrefs from the SH4 memory-access helpers.
   - Or: find a function that reads/writes DC RAM (bounds-checks against 16 MB / masks with `0x1FFFFFF`) and
     backtrack the base operand to its static global.
2. **Validate the anchor** at runtime: `guest_ram_host_base + (candidate_fighter_dc − 0x8C000000)` should land
   on the live fighter array whose **both** sides' health animate. Confirm against a known live match.
3. **Re-derive this build's DC offsets empirically** using marvelous2 semantics (§3) as the map: locate
   health (both sides), `in_match`, match/round state, char-select — by event correlation, not assumption.
4. **Rewrite the reader** around the stable pointer path: resolve the guest-RAM base (one pointer read per
   launch), then read fixed DC offsets each frame. Delete the ~1 GB scans.
5. **Opponent identity:** find the peer SteamID in flycast's netplay/Steam session (a host global via Ghidra),
   or fall back to the in-process Steam API. Replace the noisy whole-memory scan.

**Verification harness:** a small probe that, given the guest-RAM base, prints both sides' health + `in_match`
live during a match and confirms they animate (the `saw_both` / frame-counter liveness idea, but anchored).

---

## 7a. FULL-SESSION CAPTURE PLAN — screen state machine (~10-game ranked set)

Goal: identify EVERY screen from memory so the app tracks a whole ranked set live (picks → fight → result →
rematch → repeat). The master unknown is a **"screen/mode state"** value — a small guest field that's stable
within a screen and steps at each transition. Find it and the whole session becomes a clean state machine.

### The loop (one ranked set = up to ~10 games)
```
MATCHMAKING → CHAR-SELECT → VS/LOAD → FIGHT → KO/round-end → RESULTS(+rematch prompt)
   → [both rematch] → CHAR-SELECT (loop)        [MvC2 rematch keeps the same teams or returns to select]
   → [decline / set over] → back to LOBBY → (new opponent | exit)
```

### Per-screen: what we can already see, the discriminator to FIND, and the data to capture
| Screen | Already-capturable signal | Discriminator to find | Data to capture |
|---|---|---|---|
| **Matchmaking / lobby** | no fighters loaded (n=0) | mode=lobby; session peer appears | opponent SteamID (session struct), your side (`localPlayerNum`) |
| **Character select** | char_ids populate; roster partial | mode=select + a charsel-active flag | both teams' picks as they lock; assist types; who's still picking |
| **VS / load** | teams fully locked; brief | mode=vs (transient); stage set | final 3v3 teams, stage id |
| **Fight** | `in_match`≈1; health animates | battle-state = fighting | health×6 (live, both sides), timer, meter, combo, active point char |
| **KO / round end** | a whole team → 0 hp | battle-state = KO; winner flag | winner side, + how: OCV / perfect / comeback / clutch (timer) |
| **Results / rematch** | fighters frozen; prompt | mode=results + rematch-choice flags | winner, round wins, running set score, each player's rematch choice |
| **Session end / next** | back to lobby; peer clears/changes | mode=lobby; peer id change | final set record; next opponent id (new set) |

### What we must FIND (all anchored to `ram_base` + the fighter/session structs)
1. **Screen/mode state** — the top-level sequence variable (title→select→vs→fight→results→continue). Likely a
   small byte in the guest globals page. marvelous2 hints: `Battle State` @ DC 0x2895F0, `match_sub` @ 0x289621
   — but Steam offsets differ, so locate empirically.
2. **Charsel-active + per-cursor pick state** — for live picks during select.
3. **Winner / round-wins** — authoritative result (replaces the health-KO heuristic).
4. **Rematch-choice flags** — to know when the set continues vs ends.
5. (From §3b/3c work) `localPlayerNum` (side) and the **session peer SteamID** (opponent).

### Method — differential + continuous log
- **Differential:** at each distinct screen, take several snapshots of the guest globals region. A screen-state
  field is **constant within a screen, different across screens, and small**. Diff select-vs-fight-vs-results to
  surface candidates; confirm each follows the expected transition order across a full set.
- **Continuous session log** (`sessionlog` probe, see §8): sample every ~200 ms through a full 10-game ranked
  set — record the screen-state candidates + char_ids + health×6 + side + opponent. One set produces the whole
  timeline; I analyze it offline to lock the state machine and every per-screen offset, no guessing.

### How it feeds the app
- A real **screen label** in the UI (lobby / char-select / fight / results), updated live.
- **Live picks** on the char-select screen (both teams as they lock).
- **Authoritative per-game result** (winner/round-wins) → correct W/L + rich stats, no health-KO heuristic.
- **Session record**: opponent → each game's teams + result → running set score → rematch/continue, for the
  whole ~10-game set.

## 8. Tooling

- Ghidra 12.1.2 + GhidraMCP (GUI must be open on `mvc`). `mvc.exe` @ `C:\g\mvc.exe`, image base `0x140000000`
  (import-obfuscated: `EXT_FUN_` hashed imports, stripped — no netcode strings; work from xrefs, not strings).
- marvelous2 disassembly (guest semantics); maplecast-flycast source (host mapping reference).
- Cheat Engine — for runtime diff-scan (find a live health address) + pointer-scan (validate a stable path),
  as an independent cross-check on the Ghidra-found anchor.
- App reader lives in `mvc-live-skins/src-tauri/src/sync.rs`; scan/probe scratch tools under the session
  scratchpad (`dcfind`, etc.).

## 9. Security / operating rules (carry over)

- Game memory: **read-only RPM** except Live Paint's cosmetic palette `WriteProcessMemory` (user-approved,
  local process only). No writes to game logic/state.
- Never run downloaded executables/trainers; only read `.ct`/data. Ghidra/JDK from official sources are fine.
- SurrealDB root cred is prod infra — never shipped to clients. nobd.net changes are additive-only.

---

## 10. Stat Field Catalog

Complete inventory of every capturable fighting-game statistic in MvC2, cross-referenced from the
**marvelous2 SH4 disassembly** (`refs/marvelous2/pl_mem.asm`, `work.asm`, `bank03/04/05.asm`) and the
**maplecast-flycast** reader (`core/network/maplecast_gamestate.{cpp,h}`) + its SurrealDB collector
(`web/collector/src/main.rs`).

> **CRITICAL CAVEAT (repeat of §5):** these are **Dreamcast NTSC-U guest offsets**. dcfind proved the
> Steam build's guest layout does **not** map literally (stride, `char_id+1`, `health+0x420` don't
> live-match). So this catalog is a **field list + relative layout + semantics + derivation logic** — the
> map for LOCATING each field on the Steam build by **differential capture**, not a literal offset table.
> Each row is tagged **[STRUCT]** (per-fighter — find by diffing one fighter struct across events, e.g.
> take damage → the field that drops) or **[GLOBAL]** (find by diffing the globals page across screens).

### 10a. Per-fighter struct fields
Array `player_start` @ **DC 0x8C268340**, stride **0x5A4**, order `[P1C1, P2C1, P1C2, P2C2, P1C3, P2C3]`
(P1/P2 interleaved; slots 0/2/4 = P1's point/assist1/assist2, slots 1/3/5 = P2's). All offsets are
struct-relative → all **[STRUCT]** (findable by diffing a single fighter struct across a known event).

| Field | Which player | Offset | Type | Semantics |
|---|---|---|---|---|
| active | per-fighter | +0x000 | u8 | Slot in use / drawn. 0 = empty/not-loaded. Point-char liveness gate. |
| **char_id** | per-fighter | +0x001 | u8 | Character 0..0x3A (Ryu=0 … Servbot=0x3A; full table below). PalMod/roster order. |
| unnamed_state | per-fighter | +0x005 | u8 | Minor state byte. |
| Special_Move_State | per-fighter | +0x006 | u8 | Special-move phase. 6 = a distinct super/DHC phase (bank05 loc_8c05317e). |
| mash_timer | per-fighter | +0x01C | s16 | Mash-move window (Sent dash, mashers). |
| mash_counter | per-fighter | +0x01E | s16 | Mash tally (Ruby balls, Tron drill, Psylocke psyblade). |
| pl_palid_match (color) | per-fighter | +0x025 | u8 | Color/costume chosen this match (button pick). |
| **x_pos** | per-fighter | +0x034 | f32 | World/stage X (absolute). |
| **y_pos** | per-fighter | +0x038 | f32 | World/stage Y. |
| **char_pal_effect** | per-fighter | +0x040 | u16 | Hit-flash / super-glow palette tint. **Nonzero = took a hit / is flashing this frame** (free per-hit pulse — high value for combo/damage timing). |
| sprite_scale x/y/z | per-fighter | +0x050/54/58 | f32 | Dynamic zoom (supers). |
| **x_velocity** | per-fighter | +0x05C | f32 | X velocity. |
| **y_velocity** | per-fighter | +0x060 | f32 | Y velocity (jump/fall). |
| screen_x / screen_y | per-fighter | +0x0E0 / +0x0E4 | f32 | Screen-space position (for HUD/overlay). |
| xflip_copy_2 (facing) | per-fighter | +0x110 | u8 | Facing copy the wire currently ships. |
| xflip_copy | per-fighter | +0x130 | u8 | Facing copy 2. |
| **anim_timer (frame_count)** | per-fighter | +0x142 | s16 | Animation frame/timer counter. |
| **sprite_id** | per-fighter | +0x144 | u16 | Current sprite/cell being drawn. |
| anim_flags | per-fighter | +0x14A | u8 | Bitflags: 0x20 no special/super cancel & no assist; 0x40 recovery; 0x80 opponent can proximity-block. |
| anim_id / anim_group | per-fighter | +0x158 | u8 | Animation group id. |
| Dat_Pal ptr | per-fighter | +0x164 | ptr | Live ARGB4444 palette pointer (Live-Paint target). |
| attack_data_index | per-fighter | +0x1A1 | u8 | Index into attack data. |
| sp_move_strength | per-fighter | +0x1A3 | u8 | LP/MP/HP strength of active special. |
| hitbox_group_index | per-fighter | +0x1C0 | u8 | Active hitbox group. |
| **action/move state (unk_01d0)** | per-fighter | +0x1D0 | u16 | "What animation/move to play" — the **action/move-state id** (maplecast `animation_state`). |
| xflip (authoritative) | per-fighter | +0x1D2 | u8 | **Authoritative** facing/left-right flip. |
| walk_dir (unk_01d3) | per-fighter | +0x1D3 | u8 | 0 walk-fwd, 1 walk-back, 0xFF not walking. |
| special_move_jump_limiter | per-fighter | +0x1D4 | u8 | !=0 blocks jump specials. |
| airdash_counter | per-fighter | +0x1D5 | u8 | Airdashes used. |
| normal_jump_action_counter | per-fighter | +0x1D6 | u8 | Basis of the unfly glitch. |
| double_jump_counter | per-fighter | +0x1D9 | u8 | Double jumps used. |
| **undizzy / undizzy_reset_timer** | per-fighter | +0x1E1 | u8 | Dizzy/combo-scaling accumulator; counts down to 0. |
| chain_strength | per-fighter | +0x1E8 | u8 | Chain/magic-series strength. |
| **sp_move_id** | per-fighter | +0x1E9 | u8 | Current special-move id (maplecast `special_move_id`). |
| throw_immunity | per-fighter | +0x1EB | u8 | Wakeup throw-invuln timer (counts down). |
| attack_immunity | per-fighter | +0x1ED | u8 | Tag-in / invuln timer (counts down). |
| disable_special_move_counter | per-fighter | +0x1F2 | u8 | >0 blocks special/super/airdash/tag. |
| disable_all_move_counter | per-fighter | +0x1F3 | u8 | >0 blocks all moves (fly-screen dash). |
| **stance** | per-fighter | +0x1F9 | u8 | 0 stand, 1 crouch, 2 jump, 3 OTG-stun. |
| superjump_state | per-fighter | +0x1FC | u8 | 0 none, 1 rising, 2 falling. |
| corner_touching | per-fighter | +0x1FD | u8 | 0 none, 1 right corner, 2 left corner. |
| limb_choice | per-fighter | +0x1FE | u8 | 0 punch, 1 kick. |
| **in_air_normal (airborne)** | per-fighter | +0x1FF | u8 | 0 ground, 1 normal jump, 2 super jump. |
| Buff_Speed | per-fighter | +0x200 | u8 | Speedup buff (Storm/Magneto etc.). |
| Flight_Flag | per-fighter | +0x201 | u8 | Flight active. |
| Buff_HyperArmor | per-fighter | +0x202 | u8 | Hyper-armor active. |
| Buff_Damage / Buff_Defense | per-fighter | +0x205 / +0x206 | u8 | Damage/defense buffs. |
| **EnemyPointer** | per-fighter | +0x20C | ptr | **Pointer to the opponent's currently-active (point) char struct.** Pairs the two live point chars; identifies who is fighting whom. |
| has_blocked_this_jump | per-fighter | +0x210 | u8 | 0/1; guard-break driver. |
| flying_screen_camera_follows | per-fighter | +0x235 | u8 | 1 = camera locked to this char (FS dummy). |
| **air_hitstun_counter** | per-fighter | +0x239 | u8 | **Air hitstun** counter. |
| airthrow_protection_counter | per-fighter | +0x23A | u8 | >=2 → can't be airthrown. |
| dhc_move_id | per-fighter | +0x258 | u8 | Active DHC move id. |
| assist_call_state (unk259) | per-fighter | +0x259 | u8 | 0 idle; set to 1 on assist call; set to #chars during team super; decrements as assists leave. **Assist/partner activity flag.** |
| damage_calc_scratch (unk270) | per-fighter | +0x270 | u16/u8 | Used in damage calc / scaling (bank05 Damage_Calc reads +0x270). |
| **hitstun_flag (unk275)** | per-fighter | +0x275 | u8 | **0xFF while in hitstun** — the clean per-fighter "is being combo'd" bit. |
| **x_opponent_distance** | per-fighter | +0x298 | f32 | Horizontal distance to opponent — footsies/spacing analytics. |
| snapout_disable_timer | per-fighter | +0x2A0 | s16 | Snapback lockout. |
| damage_calc_0411 | per-fighter | +0x411 | u8 | Damage-calc scratch. |
| **health** | per-fighter | +0x420 | s16 | Current HP, 0..**144** (HP_FULL=144). Read as u8 on the Steam working-buffer. |
| **red_health (recoverable)** | per-fighter | +0x424 | s16 | Red/recoverable health (tag-recovery pool). |
| **assist_type** | per-fighter | +0x4C9 | u8 | Assist type (α/β/γ) chosen at select. |
| is_cpu | per-fighter | +0x525 | u8 | !=0 → CPU-controlled (filter training/arcade). |
| pal_id | per-fighter | +0x52D | u8 | Palette/costume id (maplecast `palette`). |
| **num_wins** | **P1C1 & P2C1 only** | +0x540 | u8 | **Authoritative round/game wins for that side** (win-star display, bank03 loc_8c031660). |
| **num_lose** | **P1C1 & P2C1 only** | +0x541 | u8 | Round losses for that side. |
| **num_draw** | **P1C1 & P2C1 only** | +0x542 | u8 | Round draws. |
| handicap_level | P1C1 & P2C1 | +0x543 | u8 | Handicap setting. |

**is-point-character flag:** no single boolean — derive it. The point char is the slot whose `active`
(+0x000) is set AND that the opponent's `EnemyPointer` (+0x20C) references. Slots 0/1 are the default
point chars; on a tag the game swaps which slot is live. On Steam, find by: the slot whose health is
being decremented / whose `hitstun_flag` toggles / that `EnemyPointer` on the other side points to.

### 10b. Global "battle-globals" struct (the screen state machine lives here)
**Key finding:** the whole page from **DC 0x8C2895F0** is ONE contiguous battle-globals struct
(confirmed: routines index it as `base + fixed_offset`, and it is also reached via a **pointer stored at
0x8C2896B0** which many routines dereference — e.g. Damage_Calc bank05:16689). Meter, combo, timer,
in_match, stage all sit inside it. This contiguity is exactly what makes it findable by **diffing the
globals page across screen transitions**. All **[GLOBAL]**.

| Field | Which | DC address | (= 0x2895F0 +) | Type | Semantics |
|---|---|---|---|---|---|
| **Battle State (SCREEN)** | global | **0x8C2895F0** | +0x00 | u8 | **THE screen/mode discriminator.** Steps through the screen sequence. **bank05 loc_8c054540 gates active-fight logic with `if (0x05 >= [0x8C2895F0]) return`** → values **≤5 = pre-fight / intro / non-active**, **≥6 = active fight**. This is the master "which screen am I on" value to lock on the Steam build. |
| per-side battle sub-arrays | per-player | 0x8C28963A+ | +0x4A, +0x74, +0x88 | u8[] | HUD/meter-flash bookkeeping indexed by the fighter's side byte (plmem+0x2). Confirms the struct carries per-P1/P2 sub-fields. |
| turbo/frameskip value | global | 0x8C289620 | +0x30 | u8 | Frameskip timer (Turbo1=4, Turbo2=2, FreeSelect=6/4) — speed setting. |
| match_sub (frameskip ctr) | global | 0x8C289621 | +0x31 | u8 | Frameskip counter / match sub-state (maplecast `match_sub`). |
| round_counter | global | 0x8C28962B | +0x3B | u8 | Round/sub-timer (maplecast `round_ctr`). |
| **in_match** | global | 0x8C289624 | +0x34 | u8 | 1 while a real match is running, 0 otherwise. Primary record gate. |
| **game timer** | global | 0x8C289630 | +0x40 | u8 | Round countdown (99→0). +0x41 (0x8C289631) = frame sub-timer. |
| **stage_id** | global | 0x8C289638 | +0x48 | u8 | Stage 0..0x14 (Air Ship … River Raft; table in `work.asm`). |
| **P1 meter fill** | player 1 | 0x8C289646 | +0x56 | u16 | Super/hyper meter fill toward next bar. |
| **P2 meter fill** | player 2 | 0x8C289648 | +0x58 | u16 | " |
| **P1 meter level** | player 1 | 0x8C28964A | +0x5A | u8 | Stored super bars (0..5). |
| **P2 meter level** | player 2 | 0x8C28964B | +0x5B | u8 | " |
| **P1 combo counter** | player 1 | 0x8C289670 | +0x80 | u16 | Current combo hit-count credited to P1 (ambiguity: "P1 landing" vs "on P1" — disambiguate on Steam by which one rises when P1 lands hits). |
| **P2 combo counter** | player 2 | 0x8C289672 | +0x82 | u16 | " |

Meter/combo DC addresses are from the maplecast reader (verified from trainers/cheats); the disasm
accesses them as `0x8C2895F0 + offset`, so on Steam they move **together with** the battle-state base —
find the base, the rest fall out at the same relative offsets.

### 10c. Other globals (outside the 0x2895F0 page)
| Field | Which | DC address | Type | Semantics | Tag |
|---|---|---|---|---|---|
| **frame_counter** | global | 0x8C3496B0 | u32 | Advances every emulated frame — best liveness signal + the clock for time-based stats. | [GLOBAL] |
| GameGlobalPointer | global | 0x8C26823C | ptr | → GameGlobalStart (0x8C268240) game/session struct (win mgmt, game mode). | [GLOBAL] |
| Game mode | global | 0x8C26828C | u8 | Arcade / vs / training mode. | [GLOBAL] |
| Char unlocks / Color unlocks / Stage unlocks | global | 0x8C268270 / 0x78 / 0x8C268291 | bits | Unlock flags. | [GLOBAL] |
| STG_ID (alt) | global | 0x8C26A95C | u8 | Stage id (secondary copy). | [GLOBAL] |
| fight_tick | global | 0x8C268250 | u8 | Fight-engine logic counter. | [GLOBAL] |
| camera_x / camera_y | global | 0x8C1F9CD8 / 0x8C1F9CDC | f32 | Camera position. | [GLOBAL] |
| stage_anim_timer | global | 0x8C1F9D80 | u8 | Monotonic stage-anim timer. | [GLOBAL] |
| Charsel_Input | global | 0x8C28C474 | — | Char-select cursor input (select screen). | [GLOBAL] |
| char-select data | global | 0x8C28C490 | — | Char-select cursor/pick state (live picks on the select screen). | [GLOBAL] |

### 10d. Character-ID table (char_id @ struct +0x001)
`0`Ryu `1`Zangief `2`Guile `3`Morrigan `4`Anakaris `5`Strider `6`Cyclops `7`Wolverine `8`Psylocke
`9`Iceman `A`Rogue `B`CapAmerica `C`Spiderman `D`Hulk `E`Venom `F`DrDoom `10`Tron `11`Jill `12`Hayato
`13`Ruby `14`SonSon `15`Amingo `16`Marrow `17`Cable `18-1A`Abyss(1/2/3) `1B`ChunLi `1C`Megaman `1D`Roll
`1E`Akuma `1F`BBHood `20`Felicia `21`Charlie `22`Sakura `23`Dan `24`Cammy `25`Dhalsim `26`Dict/Bison
`27`Ken `28`Gambit `29`Juggernaut `2A`Storm `2B`Sabretooth `2C`Magneto `2D`Shuma `2E`WarMachine
`2F`SilverSamurai `30`OmegaRed `31`Spiral `32`Colossus `33`Ironman `34`Sentinel `35`Blackheart
`36`Thanos `37`Jin `38`CapCom `39`BoneWolv `3A`Servbot. (⚠ this is the ROM/PalMod roster order.)

### 10e. DERIVING advanced fighting-game stats
The collector (`web/collector/src/main.rs`, `MatchTracker`) already proves most of these from the sampled
fields — the logic transfers verbatim once the Steam offsets are located. Sample the fields each frame
(gate on `in_match`), track running max/deltas, and evaluate at the KO/`in_match→0` edge.

| Stat | Derivation |
|---|---|
| **Biggest single combo (hits)** | `max` of the per-player combo counter (0x289670/72) sampled through the match. Combo end = counter returns to 0. |
| **Biggest combo (damage)** | Latch victim `health` (+0x420) at the frame the combo counter goes 0→N; on combo end take `hp_start − hp_end`. Cross-check with `char_pal_effect`(+0x40)/`hitstun_flag`(+0x275) pulses to bound the window. |
| **Most damage in shortest time (DPS)** | `(Σ health lost by a team) / ((frame_end − frame_start)/60)` using `frame_counter` (0x3496B0) as the clock. Peak over any sliding window = best burst. |
| **Fastest KO** | `frame_counter` at match start vs. at the frame a whole team's 3 healths first hit 0 (or `in_match`→0). `/60` = seconds. |
| **Longest combo** | Same as biggest-combo-hits (max combo counter). |
| **Comeback margin** | Winner ended with `chars_alive==1` while loser `==0`, and winner's total remaining HP is low (sum of 3 healths). Bigger deficit-erased = bigger comeback. |
| **Meter efficiency** | Meter spent = Σ downward steps of meter level (0x28964A/4B) → bars used; divide damage dealt by bars used = damage-per-bar. |
| **Perfect (0 damage)** | Winner's 3 healths at KO all == their initial 144 (unchanged). |
| **OCV / all-3-alive win** | Winner has all three healths > 0 at the KO edge (`chars_alive == 3`). |
| **First hit / first blood** | First side whose any health drops below its initial value; also flagged frame-precise by the first `char_pal_effect`/`hitstun_flag` pulse. |
| **Avg match length** | Mean of `(KO_frame − start_frame)/60` across matches. |
| **Clutch win** | `game timer` (0x289630) < ~10 at the KO edge. |
| **Timeout vs KO** | If loser still had HP > 0 when `in_match`→0 (and timer hit 0) → timeout; else KO. |
| **Characters / teams used** | `char_id` (+0x001) at all 6 slots at match start → the two 3-char teams; sort for a team key. |
| **Set score (round wins)** | Read `num_wins`/`num_lose` (+0x540/541) from the **P1C1 & P2C1** structs — authoritative, replaces the health-KO win heuristic entirely. |

### 10f. Steam-build location strategy (per §5)
- **[GLOBAL] fields** (Battle State, in_match, timer, stage, round_ctr, meter×4, combo×2, frame_counter,
  match_sub): find the **battle-globals base** by snapshotting the guest globals page across screen
  transitions (select→vs→fight→results) and diffing — Battle State is *constant within a screen, small,
  and steps at each transition*; frame_counter is the one that *increments every frame*; in_match is the
  one that *toggles entering/leaving a match*. Once the base is anchored, every other global sits at the
  same relative offset shown above.
- **[STRUCT] fields** (char_id, health, red_health, positions, velocities, facing, sprite_id, action
  state, stance, hitstun, buffs, assist_type, palette, num_wins): find the **fighter array + stride** by
  the 6-value char_id pattern, then locate each field by event-correlation — `health` = the per-fighter
  value in 0..144 that DROPS on a known hit (confirm **both** sides move); `hitstun_flag` = the byte that
  reads 0xFF only while being combo'd; `char_pal_effect` = the field that pulses on each hit.
- **Highest-value fields beyond the requested list:** (1) **num_wins/num_lose @ +0x540/541 in P1C1/P2C1** —
  the real set score; (2) **Battle State @ 0x8C2895F0** with the ≤5 / ≥6 active-fight threshold — the
  screen discriminator; (3) **EnemyPointer @ +0x20C** — direct pointer pairing the two live point chars;
  (4) **char_pal_effect @ +0x40** — free per-hit flash pulse for frame-precise combo/damage timing;
  (5) **hitstun_flag @ +0x275** (0xFF in hitstun) — clean "is being combo'd" bit; (6) **x_opponent_distance
  @ +0x298** — spacing/footsies analytics; (7) **is_cpu @ +0x525** — filter CPU/training frames.
