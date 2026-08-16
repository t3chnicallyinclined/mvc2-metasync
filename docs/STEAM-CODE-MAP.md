# MvC2 Steam — Code Map (Ghidra ↔ DC RE)

Ties the fully-analyzed Steam x86-64 dump (Ghidra: live memory dump, unpacked, base `0x140000000`, complete
analysis) to the DC/NAOMI knowledge base. **Living document** — grown by xref'ing confirmed anchors and matching
against the DC catalog. Companion: `MVC2-STEAM-EXPERT.md` (memory model + confirmed offsets),
`STEAM-FIGHTER-STRUCT-MAP.md` (fighter fields).

Method note: the dump is a raw binary (no PE imports/symbols) → all functions are `FUN_<addr>`; we navigate by
**xref an address → read the code**. DC per-fighter offsets do NOT linearly map to Steam (struct reorganized);
but the battle-globals struct + the match-block layout DO carry the DC layout (confirmed via the meter).

---

## The two master structs

### `game_state` — `PTR_DAT_140acd3a0` (pointer @ exe+0xacd3a0)
The main per-match battle/game state. `game_state` itself is an exe-fixed global (`0x140ac6d40`). Confirmed fields:
| off | meaning | evidence |
|---|---|---|
| `+0x8` | ⭐ **SCREEN-STATE id** — the master scene machine. **`5` = in a MATCH SESSION (char-select THROUGH the fight)** — confirmed live at BOTH char-select (fighters alive=0) and mid-fight. So `+0x8` alone does NOT separate char-select from the fight; **fighters-loaded** does (char-select = scene 5 + no live fighter array). The dispatcher `FUN_14004b600` gates match-init on `== 5`. Other values = menu/results/rematch (mapping TBD). Use: `scene==5` = FPS-guard "in a match" + (with fighters==0) the char-select signal. | `FUN_14004b600`, live read |
| `+0x10 / +0x18 / +0x20 / +0x28` | **current screen's callback pointers** (update/render). Match scene sets `+0x10 = FUN_140607d60`. Changes per screen ⇒ 2nd way to ID the screen. | `FUN_140607b50` |
| `+0x758` | ⭐ **char-select LOCKED picks** (your 3-char team, contiguous; `0xffffffff`=unlocked). `+0x6b4` = interleaved 6-slot (even=P1/odd=P2). | live (gs-100) |
| `+0x1b0` | **match-block base** (= `DAT_142edf560`) | set in `FUN_140608690` |
| `+0x1b8` | match-block size = `0x33b18` | set in `FUN_140608690`; read by savestate `FUN_140118290` |
| `+0x1c0` / `+0x1c8` | 2nd block ptr (`DAT_142edf568`, base+`0x33b18`) + size `0x33b20` | `FUN_140608690` |
| `+0x290/294/298/29c/2a4/2a8/2ac` | char-select / player-setup inputs (teams, count, flags) | `FUN_140608690`, `FUN_140037370` |
| `+0x4f0` | (netplay) result of `FUN_14004b130` | `FUN_140037370` |
| `+0x7b4/7b8/7bc/7c8/7f8` | netplay mode flags (spectator? / player-count branches) | `FUN_140037370` |
| `+0x82c` | **SIDE-SWAP flag** — routes each player to even(P1)/odd(P2) slots | `FUN_140037370` |
| `+0x850..0x8d0` | per-player netplay data (delay, rollback params, ports) | `FUN_140037370` |
| `+0x2cc/0x2d0` | input delays (`= n*0xc+7`) | `FUN_140037370` |

### `session` / netplay — `DAT_140acd3a8` (@ exe+0xacd3a8)
The netplay/GGPO session struct (sits right after `game_state`). Confirmed fields:
| off | meaning | evidence |
|---|---|---|
| `+0x1ac` | **local player index** (→ `game_state+0x7c/0x78`) | `FUN_140037370` |
| `+0x1b0` | (paired value → `game_state+0x80`) | `FUN_140037370` |
| `+0x1b8` | **local-vs-netplay flag** (`< 0` = offline/local) | `FUN_140037370` |
| `+0xd0320/0328/037c` | match/mode config (values 1/3/4 branch spectator & player-count) | `FUN_140037370` |
| `+0xd04b0` | input/rollback source object (passed to all the `FUN_14003f…` accessors) | `FUN_140037370` |
| `+0xd04b8` | netplay-state object (ports @ +0x174/178, timing @ +0x38/50/54/58/5c) | `FUN_140037370` |
| `+0xd034b` | ready/gate byte | `FUN_140037370` |

`localPlayerNum @ exe+0xac7230` and `kcode @ exe+0xac6f58` are separate flat globals mirrored from these.

---

## Match block (the thing the pointer-follow lands in)
Fresh **heap alloc, `0x33b18` bytes, zeroed** each match (→ relocates every match; confirmed `FUN_140608690`).
Base stored at `game_state+0x1b0` AND flat globals `DAT_142edf560`(=exe+0x2edf560) / `exe+0xac6ef0`.
| block off | contents | note |
|---|---|---|
| `+0x3c40` | round flag (`== iVar2==2`) | `FUN_140608690` |
| `+0x3cb8` | round-state sub-block (= `DAT_142edf580` = exe+0x2edf580) | fighter array is `+0x26c` past this |
| **`+0x3f24`** | **fighter array** (STRIDE 0x738, 6 slots, EVEN=P1/ODD=P2) | THE anchor |
| `+0x32500` | **battle-globals** (= array+0x2e5dc): ⚠ base+0 is a POINTER (not phase). CONFIRMED: timer +0x40, meter +0x5a/7c. win_result +0x3e (verified once). in_match +0x34 / round +0x3b SUSPECT | meter+timer-confirmed; leading fields are pointers |

---

## ⚠ Live W/L reliability (operational — the recurring bug)
The leaderboard's win/loss has been wrong repeatedly; two DISTINCT bugs, one fixed, one still leaking:
- **Bug A (FIXED 0.1.35): health >stride.** `OFF_HEALTH 0xb44 > STRIDE 0x738` read the next slot → every win logged
  as a loss, uniformly. Fixed to `+0x40c`.
- **Bug B (FIXED 0.1.60–0.1.62): side-parity inversion at BOTH determination sites.** Caught 2026-08-15 via
  "Ducvader" (P1, lpn=0) — won ~8 games per their OWN tapes, every one recorded as a loss. ⚠ The initial
  "one-stride shifted rollback copy" hypothesis was WRONG: on 0.1.59 the reader is pointer-follow only
  (`*(exe+0xac6ef0)+0x3f24`), shift-immune. Two independent SIDE bugs: **(1) CLIENT** — the live verdict used
  `effective_side` (= manual_side | local_side); a stale manual toggle or un-debounced lpn latch flipped the
  whole set. FIX (0.1.62): verdict reads RAW `local_pn` at the KO frame, never the override. **(2) SERVER** —
  `reconcile.rs::derive_true_winner` had `reporter_is_even = local_pn == 1`, BACKWARDS (truth: lpn 0=P1/even), so
  it inverted the winner of EVERY tape-uploaded match. FIX (0.1.60): `== 0`. The tell is the producer/consumer
  contract — the client WRITES lpn with 0=P1 (`sync.rs:2550`), so every consumer must read 0=P1. After both
  fixes, all 245 tapes were re-derived + the board rebuilt (250 matches, JFRESH 20-0 / Duc 8-1 ✓).
- **Authoritative winner signals** (the eventual "1–2 pointers" replacement for the health-KO+side machine):
  `win_result` @ `array+0x2e61a` (0=P1/even won, 1=P2/odd, 0xFF=draw, LATCHED at KO — read but currently only a
  client FALLBACK) + `localPlayerNum` @ `exe+0xac7230` → `i_won = (win_result == localPlayerNum)`, gated phase≥5.
  Also `num_wins` (DC +0x540) = in-set win counter (capped 99). NOTE: only that streak exists, **NOT a stored set
  score** (an earlier "score @ array+0x580" RE lead read 0-0 through game-ends and was WRONG).
- **Human backstop ("Result Check", planned):** because no automated signal is 100%, a post-match confirm/contest
  flow lets a user correct W/L (`attested=true`); the tape arbitrates only when two players disagree.

---

## Lobby / tournament-mode (live-validated 2026-08-16, hosted FT10; `session = *(exe+0xacd3a8)`)
- **In-lobby / online:** `session+0x1b8` (int32) ≥0 = net session (<0 = offline/local). **Mode:** `session+0xd0320`
  (1 = hosted-versus). **Player-count:** `session+0xd0328` (==4 = spectator config). **Role:** `spectator =
  (0xd0320==1 && 0xd0328==4)`. `session+0x50` = local persona name (host/self identity). `session+0x1cd` 0→1 at
  standby→match. ⚠ `session+0x1ac` (raw, was 5) is NOT the side — use `localPlayerNum @ exe+0xac7230` (0=P1/1=P2,
  SAME pointer in lobby as ranked; confirmed 0 for the P1 host).
- **⭐ SET SCORE (per-set win tally; HUD "WINS %2d", FUN_140627c50):** `sc = *(exe+0x2edf628)`; byte `sc+0xbc` =
  P1 wins, `sc+0xbd` = P2 wins. Side-correct: `my_wins = (localPlayerNum==0 ? *(sc+0xbc) : *(sc+0xbd))`. This IS
  the game's own set score (the earlier "score @ array+0x580" lead was WRONG). **FT-target (FT10) is NOT stored —
  social convention;** the UI applies the "first to N" cutoff.
- **Host/players/spectators — SteamIDs:** heap `MemberInfo` record (volatile per launch → SCAN for the SteamID
  pair): our SID `rec+0x3c` name `+0x70`; opp SID `rec+0x184` name `+0x1c0`; slot ints (1/2) `+0x260`; local IP
  `+0x294`. Host currently INFERRED (session identity + first-in-record) — no explicit lobby-owner byte pinned
  (2nd pass: the ISteamMatchmaking lobby object). ⚠ a clean stride-0x20 4-member array w/ pings+ready = the
  lobby-BROWSER / friends-in-lobbies list, NOT your match.
- **Host-picked settings (specials-allowed / stage / version / timer): NOT in game memory** — Steam lobby metadata
  via `SetLobbyData` on the un-pinned lobby object (2nd pass). (`app_name`/`app_version` strings = Coyote telemetry,
  a red herring.)
- **🐛 skin-sync-in-lobbies bug:** `find_opponent_netplay` (client sync.rs) only recognizes the RANKED pairing
  geometry (the 0x170 gap) → in a lobby the opp SteamID is in the `MemberInfo` record above (≈0x148 gap) → detector
  returns nothing → `/peers` empty → no sync. FIX: add a lobby-opponent path that scans the MemberInfo SteamID pair.

## Functions confirmed so far
| Steam | role | DC analog | notes |
|---|---|---|---|
| `FUN_140608690` | **match-block allocator/init** | round setup | allocs+zeroes 0x33b18 block, stores base; calls sub-inits `FUN_14060b550/c070/af70/b9f0`; builds round-state sub-block @ +0x3cb8 |
| `FUN_140037370` | **netplay round-init** (writes `localPlayerNum`) | netplay/GGPO session start | side-swap flag `+0x82c`; local-vs-net branch `session+0x1b8<0`; fills per-player data via `FUN_14003f…` accessors |
| `FUN_140118290` | **rollback savestate buffer init** | savestate/rollback | zeroes 1MB buffer, reads block base+size → why ~14 savestate copies of the array exist |
| `FUN_140118950` | kcode reader/writer (input) | input | (to confirm) |
| `FUN_14060b550` | **match render/video init** (called by allocator) | video setup | framebuffers + tex-DMA (0xcf00000/0xce0a000/0xce1d000), 6-slot render setup, `DAT_142edf2xx` render state |
| `FUN_140800aa0` | memset (0-fill) | — | util |

| `FUN_140607e90` | **battle-globals savestate/rollback sync** | rollback | block-copies `block+0x325e0`/`+0x327d8` (battle-globals region) into game_state save slots; walks entity list `DAT_142edf628` (stride 0x18, type byte @+1: 1=fighter/0x22=proj) |
| `FUN_14060af70` | match sub-init (block user) | — | reads block base; TBD |

## New Steam landmarks
- **`DAT_142edf628`** — entity/object list (stride `0x18`; `[+0x20]`=struct ptr, `+1`=type: 1=fighter, 0x22=projectile). The engine's active-object table.
- **`block+0x325e0` / `+0x327d8`** — battle-globals sub-regions that get savestated (near battle_globals base `block+0x32500`).

---

## DC TARGET CATALOG (the "what to find" list, w/ Steam recognition signatures)

### Two mapping laws (both cross-confirmed)
- **LAW 1 — battle-globals struct is PARTLY byte-faithful DC→Steam (⚠ CORRECTED 2026-08-14).** The DC page at `0x8C2895F0` maps to `fighter_array+0x2e5dc`, but **only from ~the meter onward is it byte-faithful** — the LEADING fields are POINTERS on Steam, not the DC scalar layout. Live-dump proof: base+0 (`array+0x2e5dc`, the supposed `phase`) reads `28 5c 35 17 00 00 00 00` = a heap pointer `0x17355c28`, NOT phase 0..9. CONFIRMED offsets: meter bars +0x5A / fine +0x7C (read 0..5 live) and timer +0x40 (read 99). SUSPECT (DC-derived, not re-proven): in_match+0x34, round+0x3B. **win_result +0x3E verified ONCE** (0 = even/P1 won at a real KO). **⇒ do NOT trust `phase@+0`; do NOT gate logic on it.** The W/L KO gate is health ("not both-teams-alive"), win_result is a fallback. Re-verify any DC battle-global before use.
- **LAW 2 — fighter struct is NON-LINEAR** (stride 0x5A4→0x738; offsets don't share a transform). Use DC only for semantics + neighbor-adjacency (pos_y=pos_x+4, red_hp=hp+4, y_vel=x_vel+4); find one landmark per sub-block empirically, walk neighbors.

### Subsystem priority + signatures
1. **Battle-globals** (`array+0x2e5dc`) — ✅ have it. phase +0x00, in_match +0x34, round +0x3B, win_result +0x3E, timer +0x40, stage +0x48, meter bars +0x5A/5B, meter fine +0x7C, combo +0x80/82. Also DC reachable via a pointer @ `0x8C2896B0` (look for a Steam global pointing at `block+0x32500`).
2. **Phase gate** — DC `bank05 loc_8c054540`: `cmp/ge 5` on phase, early-return ⇒ **active fight = phase < 5** (≥5 = KO/win/results). Steam sig: fn reading `battle_globals+0` , `cmp ...,5`/`jge` guarding a health-subtract path.
3. **Round-end recorder (THE Wave-2 target)** — DC `bank03 loc_8c03e142→34c`. Reads `win_result`; three-way branch on **0/1/0xFF**; picks winner = `player_start + win_result×STRIDE`; increments winner `+0x540`(num_wins)/loser `+0x541`(num_lose), draw both `+0x542`; each capped at **`0x63`(99)**. **Steam sig: a fn using immediates `0x738` (winner index) + `0x63` (cap) + a `0xFF` compare (draw), reading `win_result`, incrementing two adjacent per-fighter bytes.** ⚠ MCP can't search constants — find via a Ghidra Python script (search `0x738`&`0x63` co-occurrence) or a live KO-diff of slot 0/1. Win-star HUD (DC `loc_8c031660`) reads the same counters = a 2nd target.
4. **Fighter struct** — CONFIRMED Steam landmarks: char_id +0x554, health +0x40c (⚠not 0xb44), red_hp +0x410, color +0x6, combo_dealt +0x1ca, **hitstun +0x1d1** (u8; 0xFF=real hit, 0=neutral/block), pos_x/y +0x61c/620, x/y_vel +0x644/648, facing +0x720, DatPal +0x4c, assist +0x4e9, input +0x4fc. TBD (walk neighbors): EnemyPointer (DC+0x20C), undizzy (DC+0x1E1), stance (DC+0x1F9), sprite_id/anim_timer (DC+0x144/142), num_wins (DC+0x540, remapped — the in-set win counter, capped 99). ✅ **hitstun +0x1d1 / combo +0x1ca CONFIRMED 2026-08-15** — the old `0x909`/`0x902` were the NEXT slot (both >stride 0x738; slot i's 0x909 == slot i+1's 0x1d1). **CHIP** = Σ max(0, prev_hp−hp) over frames where hitstun==0 (block), filtering >8 single-frame drops (throws). ⚠ +0x1d1's 0xFF/0 on Steam still needs one live block-test confirm.
5. **Netplay/side** — `FUN_140037370` (localPlayerNum writer, side-swap `game_state+0x82c`), session `DAT_140acd3a8`, `localPlayerNum exe+0xac7230`, `kcode exe+0xac6f58`. Opponent SteamID is HOST-side (hi-dword 0x01100001).
6. **Input** — bit constants (both builds): R=0x400 L=0x800 D=0x1000 U=0x2000 LP=0x200 LK=0x40 HP=0x100 HK=0x20 A1=0x80 A2=0x10 START=0x8000. Per-fighter input Steam +0x4fc. Sig: fn writing 2 u16 masks using these immediates.
7. **Char-select** — ✅ **SOLVED 2026-08-14 (gs-100).** The LOCKED picks live in `game_state` (= `*(exe+0xacd3a0)`, an exe-fixed global e.g. `0x140ac6d40`): **`game_state+0x758`** = stride-4 char_id list (`0xffffffff` = slot not yet locked), and **`game_state+0x6b4`** = stride-8 `[char_id, assist_type]` pairs. Confirmed LIVE: Iron Man `0x33` + Sentinel `0x34` appeared the instant they were locked; the cursor HOVER is a grid coord and writes NOTHING here (only locks do) → detection fires per-lock. `sync.rs read_char_picks()` reads +0x758. ⚠ verified with the LOCAL team only (training); the OPPONENT's picks offset in ranked is UNMAPPED (needs a 2-player capture). DC analog: `Charsel_Input 0x8C28C474`, base `0x8C28C410`. (`exe+0x9d1b16` was HarfBuzz — dead.)
8. **Palette/skins** — Steam DatPal = `slot+0x4c` (working-buffer ptr in 0x10000000..0x14200000); paint = WPM 32-byte ARGB4444 row. Char palette-sig anchor via `char_sigs.json`. Code rarely needed (the ptr + sig-scan suffice).

### char_id enum: 0=Ryu … 0x17=Cable 0x2A=Storm 0x2C=Magneto 0x32=Colossus 0x34=Sentinel … 0x3A=Servbot (full table `pl_mem.asm` / `char_sigs.json`).

### DC source files: `marvelous2/{pl_mem,work,bank03,bank04,bank05}.asm` (bank03 L33812-34362 = win-record; L3248 = win-star HUD; L26943+ = char-select; bank05 L11111 = phase gate). Steam-empirical: `sync.rs`, `char_sigs.json`, `MVC2-STEAM-EXPERT.md`, `STEAM-FIGHTER-STRUCT-MAP.md`.

---

## Original TBD checklist (superseded by the catalog above)
- [ ] Fighter update loop (stride 0x738) → confirm fighter-struct field offsets.
- [ ] **Win-record code** (DC bank03 `loc_8c03e142`→`34c`): reads `win_result @ block+0x3253e`, increments num_wins.
- [ ] Char-select: roster grid, cursor(row/col), locked-picks array (⚠ `exe+0x9d1b16` was HarfBuzz, false lead).
- [ ] Palette/DatPal upload (skins).
- [ ] Match-init sub-inits `FUN_14060b550/c070/af70/b9f0` (fighter-array / battle-globals setup).
- [x] Steam lobby: `ISteamMatchmaking` create/join, lobby id, join-links — ✅ **SOLVED + JOIN PROVEN 2026-08-15** (see below).

---

## LOBBY / P2P / JOIN-LINKS (✅ solved + live-validated + join proven, 2026-08-15)

Full RE + memory: `[[mvc-lobby-p2p-re]]`, `[[mvc-lobby-tournament-re]]`. appid **2634890**.

### Steam interface singleton
Resolver `FUN_14003ee40` builds a "Steam context" object (the object *is* the interface array), fetched everywhere via `(*DAT_1408db898)(&PTR_FUN_140a34d90)`. Sub-interfaces at fixed byte offsets: `+0x08` User019, `+0x10` Friends015, `+0x18` Utils009, **`+0x20` Matchmaking009 (lobbies)**, `+0x28` UserStats, **`+0x40` Networking005 (P2P)**, `+0x48` RemoteStorage, `+0x58` HTTP, `+0x68` UGC. Matchmaking vtable (canonical order confirmed): +0x68 CreateLobby, +0x70 JoinLobby, +0x80 InviteUserToLobby, +0xA0 SetLobbyData, +0x108 SetLobbyType, +0x110 SetLobbyJoinable, +0x118 GetLobbyOwner. `+connect_lobby <id>` parser = `FUN_14012f3a0`; host state machine = `FUN_14013af30`; P2P mesh dispatcher (10 msg types) = `FUN_14013d520`; P2P bring-up = `FUN_14016e8c0`; per-peer QoS/RTT = `FUN_14015c0f0`.

### Lobby CSteamID extraction — use the FINGERPRINT, not the static offset
⚠ Static offsets (`*(exe+0x2eb36a0)+0x410` etc.) read **0** live — DO NOT use them.
✅ **WORKING (proven twice live): owner-adjacency fingerprint.** Scan committed PRIVATE heap for a **LOBBY-type CSteamID immediately followed 8 bytes later by our own USER SteamID** = the (lobby_id, owner) record; OUR lobby = the pair whose owner == our SteamID, taking the active slot (highest freq / addr `~0x2bbcXXXX`). Correctly separated a fresh lobby from a stale one on the 2nd run.
- **Lobby CSteamID format:** universe=1, type=8(chat), instance `0x60000` (lobby|MMS) → `0x18600004XXXXXXX`. Detector: `(v>>56)&0xFF==1 && (v>>52)&0xF==8 && ((v>>32)&0xFFFFF)&0x60000`.
- **User CSteamID:** `(v>>56)&0xFF==1 && (v>>52)&0xF==1 && (v>>32)&0xFFFFF==1`.
- **Member list:** distinct USER CSteamIDs clustered within ~±0x800..0x4000 of the lobby-id occurrences = members (host + joiners); resolve names via Steam `GetPlayerSummaries`. Live: read exactly host + link-joiner, no noise.
- **Room code** (short join code, e.g. `BK1V59`) is in memory as ASCII (readable, more shareable than the URL; encoding-from-id not derived).

### Join link — ✅ PROVEN END-TO-END
`steam://joinlobby/2634890/<lobbyID>/<ownerID>`. Pasted in a browser on a 2nd Steam account → launched Marvel Collections → **joined the host's lobby** (joiner cTrl_ 76561198969997427 landed in TRIS's lobby). The game only handles `+connect_lobby <id>` (via `FUN_14012f3a0`); **WE build the link** from the extracted id. `InviteUserToLobby` (mm vt+0x80) is the game's programmatic invite path.

### SetLobbyData keys (host writes, `FUN_1401391e0` reads)
`OwnerId`(%016llX), host-name, `SlotPublicMax/Open`, `SlotPrivateMax/Open`, `SearchKeyNum`/`SearchKey%d`, **`BinaryData`+`BinarySize`** (128-byte opaque **match-settings blob** → lobby-info+0x50). **FT10 is NOT a key** (social convention).

### DECISIVE: P2P is player-to-player, host-INDEPENDENT
Fight traffic runs member↔member over ISteamNetworking005 keyed on each player's CSteamID (`SendP2PPacket(memberID,…)`), NOT relayed through the owner; matchmaking is only discovery/metadata. ⟹ owner can spectate while two members fight. Owner IS the mesh **coordinator** (slot assign / ready-sync / match-start live in `FUN_14013af30`), so a present-but-spectating owner works today; **fully-headless** (no game running the coordinator) needs Steam owner-**migration** after the owner leaves — code polls `GetLobbyOwner` each tick (hints tolerated) but UNPROVEN.

### Tournament-coordination status
✅ Buildable now (game running): app reads own lobby id + members (fingerprint) → Share-lobby (link + room code) → server pairs players + distributes join links → bracket via the set-score tally (`*(exe+0x2edf628)+0xbc/0xbd`). ⏳ OPEN experiments: (1) headless lobby CREATOR = a Steamworks program as appid 2634890 calling CreateLobby+SetLobbyJoinable, no game — can a real client join it? (2) owner-migration (host leaves → match survives?) = fully-headless. (3) auto game-START = find the ready-flags + match-start trigger in memory and write them (skip the manual lobby/ready flow).
