# MvC Skin Suite — SurrealDB Backend (on KoM infra) — Blueprint

**Goal:** stand up the Skin Suite's **own SteamID-keyed match database on the existing KoM SurrealDB *server*** — reusing its infra (hosting, creds, ops), **NOT** merging into KoM's board or king.html. We borrow the proven KoM `schema.surql` *structure* (player/match/team_stats/char_stats/h2h/badges/ELO) but as **our own namespace+database**, giving the Skin Suite a rich stats/leaderboard backend. A player's stats are recorded **even if they never run the app** (credited via the netplay-derived opponent SteamID), with **dedup** when both players do run it.

**Decisions locked:** identity = **SteamID canonical, our DB is SteamID-native**; infra = **KoM Surreal server, separate ns/db from KoM**; sequencing = design now, execute next.

---

## 1. Identity — SteamID-native, our own DB (no KoM coupling)

- **Separate namespace + database** on the same Surreal server, e.g. `ns=maplecast db=skinsuite` (KoM's own ns/db + `player` table untouched — no shared identity, no king.html coupling).
- `player` record id = the **SteamID64** string → `player:⟨76561197999665347⟩`. `username` = Steam persona (display). **No KoM username/account reconciliation** — our DB is SteamID-native from the first row (that's the whole simplification vs unifying into KoM).
- The Skin Suite already resolves **self** (registry) and **opponent** (netplay pairing) SteamIDs deterministically — both are canonical ids here.

**Schema:** copy the KoM `schema.surql` table *structure* (player/team_stats/char_stats/h2h/match/played/badge/earned) into a new `skinsync/schema.surql`, re-keyed to **steamid** (record ids + unique indexes on steamid instead of username). Same rich fields (ELO, streaks, combos, ocv/perfect/comeback, team_stats, badges) — just our own instance.

---

## 2. Ingest — one server endpoint, dedup by deterministic match_key

The Skin Suite must **never** hold the SurrealDB **root** cred (per project rule: `root:nobd_arcade_2026` server-side only; `nobd_view_2026` is the client-safe read cred). So the app POSTs to a **server ingest endpoint** that holds root and writes to SurrealDB.

**Reuse the skinsync server** (already deployed, already the app's `/result` target) — add `/skinsync/ingest` (or extend `/result`) that, instead of the JSON file, runs a SurrealQL transaction against the KoM DB.

**Payload (already produced by the app today):**
`{ reporter, winner, loser, winner_name, loser_name, winner_team[], loser_team[], biggest_combo, meters_used, ocv, perfect, comeback }`

**Deterministic `match_key`** (dedup id): `sha1(min(a,b) + "_" + max(a,b) + "_" + winner + "_" + floor(ts/30000))` → `match:⟨key⟩`. Same game reported by both players ⇒ same id.

**Transaction (idempotent):**
```
BEGIN;
-- 1. dedup: create the match once; on second report just record the reporter + verify.
LET $m = (SELECT verified, reporters FROM match:$key);
IF $m = NONE {
    CREATE match:$key SET winner=$winner, loser=$loser, p1_chars=$winner_team, p2_chars=$loser_team,
        p1_max_combo=$biggest_combo, p1_meter_used=$meters_used,
        was_ocv=$ocv, was_perfect=$perfect, was_comeback=$comeback,
        reporters=[$reporter], verified=false, ended_at=time::now();
    -- 2. aggregates apply EXACTLY ONCE (guarded by match existence) → crediting BOTH players,
    --    including a non-app opponent, from this single report.
    -- upsert players (create if missing), bump W/L/streak/best_combo/ocv/perfect/comeback,
    -- upsert team_stats[winner][team_key], char_stats, h2h[pair]. (helper fns below.)
    ... apply_result($winner,$loser,$winner_team,$loser_team,$biggest_combo,...) ...
} ELSE IF !array::contains($m.reporters, $reporter) {
    UPDATE match:$key SET reporters += $reporter,
        verified = (array::contains(reporters,$winner) AND array::contains(reporters,$loser));
    -- NO re-aggregation → dedup. Just flips verified when both sides have confirmed.
};
COMMIT;
```

- **Non-app opponent:** first (only) report still runs `apply_result`, so the opponent's `player` + `team_stats` + `h2h` accrue. `verified=false` (provisional).
- **Both have the app:** second report hits the `ELSE IF` → merges reporters, sets `verified=true`, **no double count**.
- **Reporter must be a participant** (already enforced): reject if `reporter ∉ {winner,loser}`.

---

## 3. Verified vs provisional (anti-fraud preserved)

- `match.verified = true` only when **both** participants reported the same outcome (the consensus you asked for).
- **Global leaderboard / ranked ELO** counts **verified** matches only.
- **A player's own profile** shows all their matches (provisional marked) → you always see your own set data, even vs non-app opponents.
- ELO `rating` update: apply only on `verified` (so provisional can't inflate rank); provisional still populates counting stats (wins/combos/teams) for personal view.

---

## 4. Aggregation — reuse KoM tables (already defined)

`apply_result` upserts, all keyed by steamid:
- `player`: `wins`/`losses`, `streak`/`best_streak`, `best_combo=math::max`, `ocvs`/`perfects`/`comebacks`, `total_matches`, `unique_teams`.
- `team_stats:⟨steamid⟩_⟨team_key⟩`: `games++`, `wins++` (winner). team_key = sorted char ids (matches the app's key).
- `char_stats:⟨steamid⟩_⟨char_id⟩`: per character.
- `h2h:⟨sorted steamid pair⟩`: pair W/L.
- `played` relation `player→match` (slot/won/chars) for graph queries.
- **badges**: after the update, evaluate thresholds (combo/streak/perfect/ocv/comeback/diversity/loyalty/rating) → `earned` edges. (KoM badge defs already seeded.)

---

## 5. Migration (one-time)

`skinsync/records.json` + `matches.json` → SurrealDB import script:
- Each records.json player → `player:⟨steamid⟩` (map existing fields; teams map already present).
- Each matches.json entry → `match:⟨synthetic_key⟩` (verified per its flags) + `apply_result` (or import pre-aggregated to avoid recompute drift). Keep the JSON as a backup; cut over reads after verifying parity.

---

## 6. App + GUI repoint

- **App:** `report_result_server` → POST to `/skinsync/ingest` (payload unchanged — we already send teams/combo/meter). Keep the local `records.json` H2H as an offline fallback.
- **Skin Suite GUI (`web/index.html`):** the existing `leaderboard` + `profile` backend commands (server read-proxy `/skinsync/board`, `/skinsync/profile`) → point them at OUR Surreal ns/db. Ranks tab + click-a-name profile then render the rich stats (ELO/rank/badges/team-comp) from our own tables.
- **No king.html / KoM-board coupling** — this is the Skin Suite's own board on shared infra.

---

## 7. Security checklist

- Root cred (`nobd_arcade_2026`) **only** in the server ingest endpoint (VPS env), never in the app or client JS.
- Viewer cred (`nobd_view_2026`) is the only cred that can reach a client, read-only.
- Ingest validates: `reporter ∈ {winner,loser}`, SteamID format, outcome-conflict rejection (already in `/result`), rate-limit.
- Provisional (unverified) rows can't move ranked ELO → solo-report fraud can't climb the ladder.

---

## 8. Cutover order (execute-next checklist)

1. `web/schema_v2_steamid.surql` — steamid re-key + `apply_result`/badge helper fns; import to KoM DB (backup first).
2. Add `/skinsync/ingest` to `skinsync/server.js` (dual-write: JSON **and** Surreal during bake-in).
3. Migrate `records.json`/`matches.json` → Surreal; verify parity vs the JSON board.
4. Point the Skin Suite `leaderboard`/`profile` reads at Surreal (viewer cred / read-proxy).
5. Repoint the app's push to `/ingest`; confirm a live game lands as a `match` + updates `player`/`team_stats`.
6. Retire the JSON path once parity holds. Skin Suite runs on its own Surreal-backed board (KoM infra, separate data).

---

**Net:** the app already emits the right data and resolves both SteamIDs deterministically; KoM's `schema.surql` already proves the table design. Our lift = **a SteamID-keyed copy of that schema in our own ns/db + one idempotent ingest endpoint + a migration** — everything (rich stats, non-app opponents, dedup) falls out of the deterministic `match_key`, on KoM's infra but as our own board.
