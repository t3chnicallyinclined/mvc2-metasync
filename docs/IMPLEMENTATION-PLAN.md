# MetaSync — Implementation Plan

Synthesized 2026-08-14 from two research passes (FGC tournament/bracket best-practices; Steam OpenID/Web-API/
lobby-links) + this session's RE. Companion docs: `ROADMAP-METASYNC.md` (vision), `MVC2-STEAM-EXPERT.md`
(memory model + anchor).

## Guiding principles
1. **One source of truth = pointers, not scans.** Everything derives from the confirmed match anchor
   (`fighter_array = *(exe+0xac6ef0)+0x3f24`) + the battle-globals struct (`array+0x2e5dc`). This session's whole
   lesson: inference (health guessing, sig-scanning) caused every bug; ground-truth reads fix them.
2. **MetaSync's moat = automatic result capture.** From ONE host's spectator client we get
   `{winnerSteamId, both SteamIDs, both 3-char teams, per-game}` with **zero human typing**. No bracket platform
   can do this. Design every feature to exploit it.
3. **Strictly read-only.** OpenID + Web API + generating invite links are officially fine. Reading our own
   client's memory is a gray area (VAC targets *modification*; read-only ≠ blessed). **MetaSync writes nothing to
   game memory.** (⚠ the sibling skins app *does* write palettes = materially higher risk — conscious call.)
   Action item: confirm whether MvC FC runs VAC.

---

## Phase 0 — Foundation (mostly done)
- ✅ Pointer anchor + battle-globals mapped (`win_result @ array+0x2e61a`, `phase @ +0x2e5dc` active<5,
  `in_match @ +0x2e610`, `timer @ +0x2e61c`, `round_counter @ +0x2e617`).
- ✅ **0.1.43** pointer-follow W/L fix shipped (kills the alignment flip).
- ⏳ **Wave 2** (next code work): replace health-inference W/L + heuristic game-counting with
  `win_result` + `round_counter`, gated on `phase`/`in_match`. Fixes both the residual inverted W/L AND the
  "set opens 0-1/1-0" miscount. Clean session reset only on a NEW netplay pair. Nail `lpn→side` with one clean
  ranked read through the pointer.

---

## Phase 1 — Public web + Steam identity (fastest value)

### 1a. Read-only web mirror (nobd.net/metasync)
Leaderboards + per-player + per-match pages served from the existing JSON store. No app needed to *view*. Don't
block on a DB migration (KOM/SurrealDB can come later).

### 1b. Steam OpenID sign-in — **officially supported, build it**
Flow (server-side):
1. Redirect user (GET) to `https://steamcommunity.com/openid/login` with `openid.ns=…/auth/2.0`,
   `openid.mode=checkid_setup`, `openid.return_to=<callback>`, `openid.realm=<site>`,
   `openid.identity`=`openid.claimed_id`=`…/identifier_select`.
2. User authenticates on Steam's page (we never see the password); Steam redirects back with `openid.mode=id_res`
   and `openid.claimed_id = https://steamcommunity.com/openid/id/<STEAMID64>`.
3. **Verify (mandatory):** POST all `openid.*` params back to the same endpoint with `openid.mode=check_authentication`;
   require `is_valid:true`. Then regex the SteamID64 out of `claimed_id`.
4. ⚠ **Security:** hardcode the `steamcommunity.com` host + validate the claimed_id host — generic OpenID libs are
   spoofable. Use a Steam-specific validator.
- **Web API key** (`steamcommunity.com/dev/apikey`) kept **server-side, confidential** (ToU). Used only for 1c.

### 1c. Profile hydration via Web API
- `ISteamUser/GetPlayerSummaries` → `personaname`, `avatarfull`, `personastate`, and **`gameid==2634890`
  (in MvC FC right now)**. Batch ≤100 IDs, cache hard (100k calls/day, ~1 rps). Pull only for opted-in users;
  publish a privacy policy (ToU requirement).
- `ISteamUser/GetFriendList` (401 if private) — optional, for "challenge a friend."

### 1d. Shareable stat pages
Every page (`/p/<steamid>`, `/m/<matchid>`, `/lb/<board>`, later `/t/<tourney>`): short link + copy button +
**Open Graph / Twitter-card meta** (title, record, rank, a rendered preview) so a paste into Discord/Twitter
auto-embeds. Optional server/canvas PNG "stat card." That's most of "shareable to any platform" for free.

---

## Phase 2 — Match context + profiles
- **Ranked vs casual/lobby detection** → **RANKED badge** + split ladders. RE task: find the match-type flag
  (diff a ranked match vs a lobby; the live-dump Ghidra pass will name the matchmaking call). Record gets
  `match_type: ranked|casual|lobby`.
- **Regional reps**: profile picks region/city (opt-in, self-declared, never IP-inferred). Enables wins-by-region,
  "best in region," region-vs-region, `/region/<x>` boards + shareable "Best in <city>" cards.

---

## Phase 3 — Tournament mode (flagship)

### The premise (verify first)
Host **spectates** → their client renders every match → the anchor + SteamID pair + `win_result` are all in the
host's memory. **Only the TO runs MetaSync.** ⚠ **RE task #1: confirm the pointer + SteamID pair + `win_result`
read correctly while *spectating*** (almost certainly yes; it's the whole basis — verify before building).

### Data model (adapted from start.gg's proven hierarchy + Challonge progression + MetaSync auto-detect)
```
Tournament ─∞ Event ─∞ Phase ─∞ Pool ─∞ Set ─∞ Game
Tournament ─∞ HostSession ─∞ DetectionEvent ──(matchedSetId)→ Set
Event ─∞ Entrant ∞─ PlayerProfile      (Entrant = point-in-time snapshot; Profile = global identity)
Set.winnerNextSetId / loserNextSetId → Set   (progression DAG; auto-advance + cascade-reset)
```
Key entities/fields:
- **Tournament** `{id, name, hostUserId, status(draft|reg|checkin|running|final), settings{defaultBestOf=3,
  finalsBestOf=5, checkInWindowMins, dqGraceMins, seedingMode}}`.
- **Event / Phase / Pool** — kept for parity/future scale; a small event is one Event → one Phase(double_elim) →
  one Pool.
- **Entrant** `{id, eventId, playerProfileId, displayTag(snapshot), seed, checkInState(not|checked_in|dq),
  losses(0|1|2), status, standingPlace}`.
- **PlayerProfile** (the identity linkage) `{id, primarySteamId, knownSteamIds[](alts), displayName, eloRating,
  regionTag, discordId?}` — auto-detection resolves detected SteamIDs against this; existing ELO attaches here.
- **Set** `{id, poolId, round(−=losers), identifier(WF|LF|GF|GFR), bestOf, slot1EntrantId, slot2EntrantId,
  expectedSteamIds[2], winnerEntrantId, scoreSlot1/2, state(pending|ready|called|in_progress|awaiting_confirm|
  completed|dq), winnerNextSetId/Slot, loserNextSetId/Slot, calledAt, completedAt}`.
- **Game** (auto-filled) `{id, setId, gameNum, winnerEntrantId, slot1CharacterIds[3], slot2CharacterIds[3],
  assistTypes?, detectionId}`.
- **HostSession** (MetaSync-specific linchpin) `{id, tournamentId, hostSteamId, lobbyId, state(idle|armed|detecting),
  armedSetId, spectatorClientVersion, lastHeartbeatAt}`.
- **DetectionEvent** (append-only audit) `{id, hostSessionId, capturedAt, steamIdP1, steamIdP2, charsP1[3],
  charsP2[3], gameWinnerSteamId, confidence, matchedSetId?, resolution(auto|review|discarded), discardReason?}`.
- **Standing** `{eventId, entrantId, place, eloDelta}`; **Station**/**Stream** (single lobby = one station).

**Why:** Entrant-snapshot vs global Profile = start.gg's hard lesson (tag changes / alts never corrupt history).
`armedSetId` + `expectedSteamIds` = the linchpin that maps a detected game to the right slot with zero TO input
AND rejects casual/wrong-player games. Progression pointers make auto-advance a pointer-write and correction a
**cascade-reset** (Challonge pattern). DetectionEvent = a review queue + dispute audit trail.

### Format: double-elimination (FGC standard)
- Two losses = out. WB losers "drop" to LB (cross-placed to avoid instant rematch). Sets best-of-3; WF/LF/GF
  best-of-5.
- **Grand Finals reset**: GF = WB champ (0L) vs LB champ (1L). WB wins set 1 → done. LB wins set 1 → both at 1
  loss → **GF-reset set (`GFR`)** decides it. Model the GFR as auto-created off the GF's progression pointers so
  report-time needs no special-case.
- **Byes** = (next power of 2) − N, given to top seeds. **Seed by ELO** (MetaSync already computes it), TO can
  drag-override. Snake seeding only when a large field splits into pools.

### The auto-driven flow (near-zero TO clicking)
Single host lobby = one serial station. After seeding, the happy path is click-free:
1. **Setup (once):** TO creates tournament (double-elim default); entrants register + **link SteamID→Profile**
   (the one identity step). Returning players already linked with ELO.
2. **Check-in + seed:** open window; optionally auto-check-in anyone MetaSync sees join the host lobby. Auto-seed
   by ELO; assign byes; generate bracket + progression pointers; publish.
3. **Run:** MetaSync picks the next `ready` set → `called`, **arms HostSession** (`armedSetId`,
   `expectedSteamIds`), pings both players to load in.
4. Players play. Spectator client emits **DetectionEvents**; MetaSync counts a game ONLY if its two SteamIDs ==
   the armed set's `expectedSteamIds` (auto-ignores casuals/warm-ups/wrong players). Appends **Game** rows
   (winner + both teams). At the best-of threshold → `awaiting_confirm` (brief timeout / losers leave) →
   `completed`.
5. **Auto-advance:** write winner/loser into `winnerNext`/`loserNext`; sets with both slots filled become `ready`;
   auto-arm the next. Update ELO on Profiles. **No TO click in steps 3–5.**
6. **Exceptions (only human touchpoints):** ambiguous/low-confidence detection (alt SteamID, conflicting events)
   → review queue (learned alts append to `knownSteamIds`); no matching detection within DQ grace → flag → TO
   taps DQ; wrong result → TO edits winner → **cascade-reset** downstream → re-arm.
7. **Finalize:** GF/GFR done → compute Standings from elimination order + ELO deltas; publish; export (start.gg
   `gameData` is already fully populated with characters + per-game scores, so we can even push to start.gg for
   cross-listed events).

### Join-link automation (⚠ test-gated)
- We CAN read the **lobby id + owner SteamID** from our own client's memory and build
  `steam://joinlobby/2634890/<lobbyid>/<owner>`. The Steam plumbing is guaranteed (game open → callback; closed →
  launches with `+connect_lobby`).
- ⚠ **The gate we cannot control:** whether MvC FC's own Steamworks code *handles* the join (responds to
  `GameLobbyJoinRequested_t` / parses `+connect_lobby` → `JoinLobby`). Also **lobby type** — friends-only lobbies
  reject non-friend clickers even with a valid link; and the joiner must own appid 2634890.
- **Decisive 5-min test BEFORE committing this:** host an online room → Steam overlay → right-click host's
  **"Join Game" → "Copy link address."** If you get a `steam://joinlobby/2634890/…` link, the game registers a
  Steam lobby (green light). Compare its ids to what we scrape from memory. Click from a 2nd account (game closed,
  then open) + a **non-friend** account. If no link appears → fall back to **in-game room codes** surfaced on the
  bracket page (players matchmake manually; results still auto-detected). *The auto-detection tournament works
  either way; the click-to-join is the cherry on top.*

### OBS overlay
Browser-source page reading the live match + bracket from the server: names/avatars, both teams (with skins),
health/meter, set score, ranked badge, region reps, "up next." Drives stream + venue screen.

---

## Phase 4 — Replays
- **State-replay (prototype):** capture per-frame visual state off the anchor (per fighter: char_id, anim-state +
  frame, pos, facing, palette; + HUD globals) via the in-process hook @60fps → delta-encoded + gzip `.replay`
  (hundreds of KB/match). Play back in the lightweight `webgputest.html` sprite renderer — no engine/ROM needed;
  frame-perfect (recorded frames); effects optional for v1. The one real dependency: map `(char, anim_state,
  frame) → sprite atlas frame` (we have Skin Studio decode + the mvc2-ai move tables).
- **Input-replay (later):** record inputs + re-sim in the engine (tiny, verifiable) — for desktop/AI, not web
  (BYOR + heavy).
- Reuse: `.mctele` capture (determinism-proven), `webgputest.html` renderer, Skin Studio sprites.

---

## RE task backlog (memory work, all off the anchor)
1. **Verify spectator capture** (Phase 3 premise) — anchor + SteamID pair + `win_result` while spectating.
2. **Lobby id + owner** in memory → join links (Ghidra: `ISteamMatchmaking::CreateLobby`).
3. **Ranked/casual/lobby flag** (Phase 2 badge).
4. **All SteamIDs in a lobby** (not just the 2-player pair) → who's in the venue → bracket-slot mapping.
5. **Char-select selection + grid** (skin pre-load; grid decoder `exe+0x9d1b16` found; cursor struct located;
   needs the live-dump Ghidra xref for the logical selection + stable addressing).
6. **Netplay-session pointer** (opponent identity off a pointer, kills the SteamID scan + stale-opponent bug).

All of 2–6 are far easier once the **live-dump Ghidra** pass is analyzed (the on-disk exe is packed/encrypted).

---

## Build order (recommended)
1. **Wave 2** (ground-truth W/L + game-count) — finishes the core correctness; small code change, big payoff.
2. **Phase 1** web mirror + OpenID + share cards — fast, high-visibility, unblocks "claim your stats."
3. **Run the two cheap TESTS**: (a) VAC on MvC FC? (b) the `steam://joinlobby` copy-link test. These de-risk
   Phase 2/3 before building.
4. **Phase 2** ranked badge + regional reps (small).
5. **Phase 3** tournament mode — data model + auto-detect (HostSession/DetectionEvent) first (works with manual
   room codes), then layer join-link automation IF the test passed, then the OBS overlay.
6. **Phase 4** replays (state-replay prototype).

## Open questions / tests to run
- VAC active on 2634890? (governs external-memory-read risk posture)
- `steam://joinlobby` supported by MvC FC? (copy-link test) — gates click-to-join, not the tournament itself.
- Lobby type MvC FC uses (public vs friends-only) + max lobby capacity (one lobby as venue vs rotation).
- Does spectating expose both players' full state cleanly? (Phase 3 premise verification.)
