# MvC MetaSync — Tournament Platform Build Spec

**Status:** design locked, pre-build. Companion to [`DISTRIBUTED-TOURNAMENT-SPECTATOR-TAPE.md`](./DISTRIBUTED-TOURNAMENT-SPECTATOR-TAPE.md) (the RE + spectator-tape doc). This doc is the *product/engineering* spec: data model, server endpoints, TO + player screens, and the phased roadmap.

Sources for the competitive-platform patterns below: start.gg **[SGG]**, Challonge **[CHL]**, Battlefy **[BF]**, plus FGC Discord-bot norms (Dragora, TournaBot). Tags mark where a specific pattern comes from.

---

## 0. The one idea that matters

**start.gg / Challonge / Battlefy are blind to the game.** They draw a bracket, then depend on players to *manually self-report* scores, copy lobby codes around by hand, and argue disputes into a chat that a moderator has to babysit. Every painful part of running an online bracket is a symptom of the platform not being able to see the match.

**MetaSync reads the game's memory.** We already validated, live, that we can detect:
- the Steam **lobby** and **who is in it** (owner-adjacency fingerprint),
- **match start / end** (`session+0x1cd`),
- **who won** (`match_block sc+0xbc/+0xbd` win-tally), and
- generate a **one-click `steam://joinlobby/...` link** so nobody copies a code.

So MetaSync is not a start.gg clone. It's **the bracket platform that runs itself** — auto-seeded by real ELO, auto-assigns players to open lobbies, and **auto-reports results with no disputes** because the host machine *watched the match happen*. That is the entire pitch, and the [auto-report wire](#phase-3--auto-report-the-differentiator) is the highest-value thing we build.

---

## 1. Locked decisions

| Decision | Choice | Notes |
|---|---|---|
| Bracket format | **Double elimination** (default), single-elim optional | FGC standard; winners + losers + grand finals w/ **bracket reset** [SGG][CHL] |
| Who registers / how | **App users (Steam identity) + public web at launch** | App reads SteamID from memory; web needs a **Steam OpenID sign-in** (new) |
| Entry fee | **Free for now** | Model the field now; when paid, **must use PayPal — Stripe bans games-of-skill/tournaments** (start.gg was forced off Stripe Nov 2023) |
| First build | **This design doc**, then Phase 1 skeleton | |
| Game | MvC2 only (single title) | Simpler than start.gg's Tournament→Event tree; keep the model extensible |

---

## 2. Reuse map — what we already have vs. build new

The governing rule (per repeated user direction): **do not duplicate what the app already sources.** The tournament layer is thin glue over existing systems.

**Reuse verbatim (server: `skinsync/src/`):**
- **Identity & auth** — `/skinsync/register` mints a **token bound to a SteamID**; `auth_steamid()` enforces "act only as your own bound SteamID." → one-click, Steam-verified registration with zero new account system. (`routes.rs`, `auth.rs`)
- **Player name / avatar / country** — `resolve_names()` / `name_entry()` / `disp_name()` (Steam Web API, cache-first). (`routes.rs`, `mirror.rs`)
- **ELO / rank / W-L / teams / recent / head-to-head** — `profile`, `playerstats`, `matchup`, `leaderboard`. → seeding-by-ELO and h2h previews are *free*. (`stats.rs`)
- **Match recording + integrity** — `/result` (provisional→consensus), `/contest`, `/confirm`, `/admin/resolve`, and **tape correction** in `handle_gamestate` (`derive_true_winner`, `tier3_autoconfirm`). A tournament game flows through this **same** pipeline (with a session/tournament id) so it also counts toward global ELO and is tape-verifiable. (`routes.rs`, `reconcile.rs`, `contest.rs`)
- **Persistence** — `save_json` / `app.persist()` JSON store, optional SurrealDB read mirror. (`app.rs`)
- **Frontend source of truth** — `invoke('profile'|'matchup'|'leaderboard')`, `openProfile()`, `avatarImg()`, `flagEmoji()`, `teamNames()` (already wired into the Tournament tab).

**Build new:**
- `skinsync/src/tourney.rs` — Tournament / Registration / Bracket / HostNode records + the double-elim engine + `/skinsync/tourney/*` routes.
- **Steam OpenID sign-in** (`auth.rs`) — a web browser can't read the SteamID from game memory; `GET /skinsync/auth/steam/login` → Steam → `/return` verifies and mints the **same** token.
- **Tournament tab → TO mode** and the **public web mirror** (Phase 4).
- **Typed notifications** (match-ready / on-deck / check-in / etc.).

---

## 3. Data model

All records persisted as JSON alongside the existing stores. Player-derived fields (name/avatar/cc/ELO/rank) are **never copied in** — they resolve live from the reuse map.

### Tournament (container)
```
id             slug, e.g. "nobd-showdown-2026-08"
name           display name
to_steamid     creator = the TO (ownership key for admin actions)
co_tos         [steamid]            additional admins / helper TOs
game           "mvc2"
banner_url     cover image (uploaded asset)
logo_url       optional
rules_md       markdown rules (players confirm-read at registration [FGC norm])
format         "double" | "single"
best_of        { pools, winners, losers, grands }   e.g. FT2/FT2/FT3/FT3 — per-round, distinct W/L/GF [SGG]
entry_fee_cents 0 (free for now)
region         { online:true, cc, country, region, city }   drives browse-by-region
starts_ms, reg_open_ms, reg_close_ms, checkin_open_ms, checkin_close_ms
cap            max entrants (waitlist beyond)     [SGG registration cap]
waitlist       bool
custom_fields  [{ key, label, type, required, cap }]  → char/team declaration, seeding survey, Discord handle [SGG][CHL]
stream_url     main-stream Twitch (Phase 4: WebGPU broadcast)
discord_url    optional required-join server [SGG]
status         draft | open | checkin | seeding | running | done | cancelled
created_ms
```

### Registration (one per entrant)
```
tournament_id, steamid
seed           assigned integer (1 = top)
seed_source    "elo" | "manual" | "random"
team           [cid,cid,cid]        optional declared team (custom field)
custom         { key: value }       other custom-field answers
checked_in     bool, checkin_ms
status         registered | waitlisted | checked_in | dropped | dq
registered_ms
```
Display name / avatar / cc / ELO come from `profile`/`resolve_names` at render time.

### Match (double-elim node)
```
id, tournament_id
bracket        "W" | "L" | "GF"          winners / losers / grand-finals
round, slot
p1, p2         steamid | null            null until fed by a source edge
src_p1, src_p2 { match_id, take: "winner"|"loser" }   how this slot is filled (drives auto-advance)
best_of
winner         steamid | null
score          e.g. "2-1"
lobby_id       assigned host lobby (station analog)
on_stream      bool                      routes it to the main-stream lobby [SGG stream queue]
called_ms      when players were summoned [SGG "mark as called"]
state          pending | ready | live | reported | confirmed | done
report_source  "auto" | "manual" | "to"
match_key      link to the recorded MatchLog (stats + tape)
```
Grand-finals reset: if the losers-side player wins GF once, spawn `GF2` (winner must win twice) [SGG][CHL].

### HostNode / Lobby (the "stations" of an online event)
```
tournament_id
host_steamid, host_name, machine_label
lobby_id       Steam lobby CSteamID (live, from memory)
join_link      steam://joinlobby/2634890/<lobby>/<owner>
kind           "stream" | "helper"       exactly one stream node; rest are TO helpers
status         open | busy
current_match_id
stream_url     per-node override (else tournament.stream_url)
last_seen_ms   heartbeat from the host daemon
```

---

## 4. Server endpoints (`/skinsync/tourney/*`)

**Public reads (discovery + viewing):**
- `GET  /tourney/list?status=&cc=&city=&from=&to=&online=` — browse feed [SGG facet filters]
- `GET  /tourney/get?id=` — tournament + registrations + lobbies
- `GET  /tourney/bracket?id=` — bracket only (live, poll for updates; highlight in-progress [CHL])

**Player (auth = SteamID token):**
- `POST /tourney/register {id, team?, custom?}` — one-click; waitlists past cap
- `POST /tourney/unregister {id}` — self-drop before lock
- `POST /tourney/checkin {id}` — during the check-in window

**TO (auth = `to_steamid` or in `co_tos`):**
- `POST /tourney/create {…}` · `POST /tourney/update {id,…}`
- `POST /tourney/seed {id, method:"elo"|"manual"|"random", order?}` — ELO seed reads existing `records` [SGG]
- `POST /tourney/start {id}` — finalize seeds → generate the double-elim bracket
- `POST /tourney/checkin/finalize {id, mode:"remove"|"dq"}` — [SGG Finalize; CHL moves no-shows to bottom seeds]
- `POST /tourney/host/add {id, host_steamid, kind, stream_url?}` — enroll a helper host machine
- `POST /tourney/match/assign {id, match_id, lobby_id}` — assign a set to a lobby (TV-icon analog [SGG])
- `POST /tourney/match/stream {id, match_id, on_stream}` — put a set on the main stream
- `POST /tourney/match/call {id, match_id}` — notify both players + push their join link
- `POST /tourney/match/report {id, match_id, winner_steamid, score?}` — override/manual; advances bracket
- `POST /tourney/match/reset {id, match_id}` — undo a reported set [CHL reopen]
- `POST /tourney/dq {id, steamid}` — DQ / no-show

**Host daemon (auth = host token; must be the assigned host of the lobby):**
- `POST /tourney/lobby/report {id, lobby_id, members:[steamid,steamid], winner_steamid, win_tally}` — **the auto-report** (§Phase 3): maps the lobby's current match → advances.
- `POST /tourney/lobby/state {id, lobby_id, members, status}` — heartbeat that powers the **live lobby pool** in the tab.

**Web Steam sign-in (new):**
- `GET  /auth/steam/login` → redirect to Steam OpenID
- `GET  /auth/steam/return` → verify assertion → mint a SteamID-bound token (same `tokens` table)

**Auth note:** TO-only actions check `caller == to_steamid || co_tos.contains(caller)` (per-tournament ownership) — *not* the global `SKINSYNC_ADMIN_KEY` (that stays operator-only). Dispute overrides can still escalate to the operator via existing `/admin/resolve`.

---

## 5. TO workflow + admin control panel

The full control set a TO needs, grounded in start.gg / Challonge / Battlefy, in order of use:

**Create (the registration form):** name · banner + logo · rules (markdown) · **format (double/single)** · **best-of per round** (distinct W / L / GF) · region + city (or online) · registration open/close · check-in window · attendee cap + waitlist · entry fee (0) · **custom fields** (character/team, seeding survey, Discord) · required-Discord toggle · **clone-from-previous** to prefill recurring weeklies [BF][CHL][SGG].

**Registration management:** view/approve entrants · waitlist overflow · add a late entrant (even onto the bracket [SGG]) · remove/DQ.

**Check-in:** open window · players confirm from any tournament surface · **Finalize** with an explicit **remove-and-rebalance vs DQ** choice [SGG] · FGC-grade **auto-DQ timers** (7 min WR1/2, 5 min later & losers [FGC guidance], TO-configurable).

**Seeding:** **auto-by-ELO (default — we own the ELO)** · manual drag-reorder · random · region/crew separation (keep top seeds apart, avoid R1 rematches [SGG snaking]) · lock · re-seed.

**Hosts & stream:** enroll **helper TO host machines** into the pool · designate the **one main-stream lobby** · paste the **stream URL** (Twitch now, WebGPU later) · assign a specific match to a specific lobby.

**Running matches (the live console — one dashboard, per-set actions):** see everything **live / ready / waiting** at a glance · **call players** (push join link) · **mark on-stream** (routes to the stream lobby) · **advance winner** (auto from memory, manual override) · **reset/undo** a set · **DQ / no-show** · pause/hold · **Broadcaster mode** for streamed sets — TO reports, players don't, avoiding race conditions [SGG].

**Finish:** confirm champion · publish standings · (results already fed global ELO via the shared pipeline).

In-app: the Tournament tab shows **TO mode** automatically when the signed-in SteamID is the `to_steamid` / a co-TO.

---

## 6. Player workflow

**1. Discover** [SGG facet filters + follow-an-organizer feed]:
- Browse upcoming by **game / region / city / date / online-vs-offline / free-vs-paid**.
- Follow a TO/series → personalized "upcoming" feed + notify on their next event (FGC lives on recurring weeklies).

**2. Register** — one click for a signed-in user (identity + name already known); the only per-event friction is **custom fields** (declare team, seeding self-rating, Discord handle) [SGG][CHL]. Confirm-read the rules [FGC norm]. Editable until lock; self-drop before the deadline.

**3. Check-in** — a window before start; miss it → auto-DQ. Status shown on **every** surface + a persistent "action needed" badge [BF].

**4. Play — the online match loop** (start.gg's proven "Tasks checklist" shape, but we automate the middle):
- **Check in → (we auto-assign the lobby) → the app shows "▶ Join your match" (one click, SteamID-gated) → play → result auto-detected.**
- MetaSync collapses start.gg's manual "exchange connect codes in chat" + "report score + opponent confirms" into **join-link + memory-detected winner**. Manual report + a "request moderator" path remain as fallback.

**5. Watch** — non-players don't spectate in-game; the main-stream card links the **TO's stream** (Twitch → later WebGPU). Only the two players in a lobby get the Join button.

**6. Bracket + notifications** — zoomable live bracket with in-progress highlighting; **layered, typed** alerts (below).

---

## 7. Auto-report — the differentiator (see Phase 3)

```
   ┌ host machine (TO node) running MvC2 + host daemon ┐
   │  reads live memory:                                │
   │   • lobby members  → the two SteamIDs in this set  │
   │   • session+0x1cd  → match start / end             │
   │   • sc+0xbc/+0xbd  → win-tally → winner            │
   └───────────────┬───────────────────────────────────┘
                   │  POST /tourney/lobby/report {lobby, members, winner}
                   ▼
        server maps lobby → current match → sets winner
                   │  advances winner (W), drops loser to losers (L)
                   ▼
        bracket updates live in every viewer's tab
        + the game is recorded through the SAME /result pipeline
          (counts toward global ELO; tape-verifiable; contestable)
```
**No manual score entry. No self-report disputes.** The host *watched the match*. Manual report (`/tourney/match/report`) and the existing contest/override machinery stay as the fallback for edge cases (crash, DQ, off-node sets).

---

## 8. Notifications (layered + typed)

Players miss single-channel alerts, so deliver redundantly and **type** each one [SGG push-every-stage; BF critical-action badge; TopDeck round-call/seating types; Dragora/TournaBot DMs]:

| Type | Trigger | Channels |
|---|---|---|
| `checkin_open` | check-in window opens | in-app badge, push, (Discord) |
| `match_ready` | your set is assigned a lobby | in-app, push, Discord DM, **deep-link to Join** |
| `on_deck` | you're next after the current set | in-app, push |
| `report_confirm` | opponent/you must confirm a result (fallback path) | in-app |
| `dispute` | a set you're in is contested | in-app → TO |
| `to_announcement` | TO broadcast | in-app, Discord |

Delivery reuses the existing polling surface (like `/notifications`); a **Discord webhook/bot** integration is the FGC-standard "you're up" ping and should land in Phase 4.

---

## 9. Phased roadmap

### Phase 1 — Skeleton (make it real & persisted)
- `tourney.rs`: Tournament/Registration records + `create/update/list/get/register/unregister`.
- **Steam OpenID sign-in** for web parity.
- **Double-elim bracket engine** (winners+losers+GF w/ reset) + `seed` (ELO default) + `start`.
- Tournament tab: **Browse list** (by region/date) · **Create form** (banner/rules/format/region/cap/custom fields) · **one-click Register** · seeded **double-elim bracket** render (extend current single-elim renderer). Player data stays sourced from `profile`/`matchup` (already done).
- *Exit:* a TO can create a tournament, players browse by region and register, and a real ELO-seeded double-elim bracket generates — persisted across restarts.

### Phase 2 — TO admin control panel
- Check-in (open/finalize/auto-DQ) · seeding UI (drag/random/region-protect) · host enrollment + main-stream designation + stream URL · live run-console (call / assign / on-stream / advance / override / reset / DQ) · Broadcaster mode.
- *Exit:* a TO can run an entire bracket by hand, end to end, from the tab.

### Phase 3 — Auto-report (the magic)
- Host daemon: read the two in-lobby SteamIDs + win-tally → `POST /tourney/lobby/report` → bracket advances with **no manual entry**; same daemon heartbeats `/tourney/lobby/state` to power the **live lobby pool**.
- Game recorded through the shared `/result` + tape pipeline (global ELO + verifiable).
- *Exit:* a match ends in-game and the bracket advances itself, live, in every viewer's tab.

### Phase 4 — Reach & broadcast
- Public **web mirror** (browse/register/bracket for non-app users).
- **Typed notifications** + **Discord bot** ("you're up" DMs, result sync).
- **Authoritative spectator tape** (.mctele sampler on Steam offsets) → **WebGPU broadcast** (see the RE doc) — the platform streams/replays matches itself.

---

## 10. Open decisions (not blocking Phase 1)

- **Banner hosting** — store uploaded images where? (server static dir vs. object storage). Small now; decide before web mirror.
- **Multi-event tournaments** (singles + side events under one container) — start.gg's Tournament→Event tree. Deferred; MvC2 is single-game, model stays extensible.
- **Pools → top-cut** for large fields — deferred to after double-elim is solid.
- **Region-locking / connection quality** for online sets — surface RTT (we RE'd the QoS tag) as a warning; policy TBD.
- **Paid entry** — PayPal only (games-of-skill); revisit when there's demand.
- **Anti-cheat** — we have the **tape** instead of screenshot uploads; higher-stakes events can still require POV stream.
