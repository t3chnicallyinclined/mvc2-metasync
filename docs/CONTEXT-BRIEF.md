# MetaSync — Context Brief & Forward Roadmap

> **Purpose:** single authoritative handoff so context survives compaction. Written 2026-08-17.
> Supersedes the scattered plan docs as the *index* — the detail docs it points at are still valid.
> When you pick this up: read this top-to-bottom, then jump to **§7 Next actions** and start pushing.

---

## 1. What MetaSync is

Companion system for the Steam **MARVEL vs CAPCOM Fighting Collection** (MvC2, appid `2634890`).
Reads live game memory, applies palette skins, reports match results, powers a leaderboard/tournament
web app. Three surfaces, one release train:

| Surface | Repo (worktree) | What it is | Version source |
|---|---|---|---|
| **Tray agent** | `mvc-live-skins-tray/tray-agent` (branch `tray-agent`) | Rust headless tray (`tray-icon`+`tao`/`muda`), reads memory, applies skins, reports matches, **self-updates**. The forward client. | `Cargo.toml` |
| **PWA** | `metasync-rewrite/app` (branch `rewrite/portable-web-agent`) | SvelteKit 5 (runes), adapter-static SPA, live at **nobd.net/app**. Read/social: Ranks, Match, Tournament, Regions, Library, Profiles. | `app/package.json` + `app/src/lib/config.ts` `APP_VERSION` |
| **Tauri app** (retiring) | `mvc-live-skins` (branch `release/v0.2.6`) | The legacy desktop app. Being replaced by tray+PWA. Still the shipping client until the 0.3.0 cutover. | `src-tauri/tauri.conf.json` + `Cargo.toml` |
| **Server** | `metasync-srv/skinsync` (deploy staging `/opt/skinsync-src`) | Rust `tiny_http` single-thread, nginx `/skinsync/` proxy. **Multi-session repo** — always diff before deploy. | — |

**All four are aligned at `0.2.6`.** Keep them locked in step (`metasync-rewrite/scripts/check-versions.mjs`
fails CI on drift).

---

## 2. Current shipped state (0.2.6 — LIVE)

Released for **Windows + Linux**. Highlights:

- **Ranked-vs-lobby fix** (the headline of 0.2.6). Root cause: `read_my_lobby().in_lobby` is *ownership*,
  not *mode* — ranked matches ran through the lobby path and got mislabeled. **Fix = the `d0328`
  discriminator** (see §4). Live-validated both directions.
- **Softer head-to-head copy**: removed "nemesis/victim" → "Most losses against" / "Most wins against".
- **Tray self-update pipeline** — validated live 0.2.5→0.2.6. Own flat `agent-latest.json` manifest,
  minisign self-replace, `--updated` restart, applies only when no game running. **The base64 `.sig` gotcha
  is fixed** (see §4).
- **Enriched server match feed** (`GET /skinsync/matches/feed?limit=&mode=`): `{now_playing, results}` with
  winner/loser names, ratings, ranks, teams, mode, elo, combo/ocv/perfect/comeback flags, session_id,
  verified, ts.
- **Standardized arena banners** in the PWA Match tab: `MatchBanner` (single-row, MatchRow vocabulary,
  result|live variants, stubbed Spectate on live), `PlayerTag` (badge+name+rating), `SessionModal`
  (set score + game-by-game, reserves a `live` prop). Mode filter (defaults ranked) + pagination (5/page,
  last 20). Commit `82b5dad`, deployed to nobd.net/app.
- **Off-box backup**: nightly cron 04:17 UTC → Cloudflare R2 `r2:mvc2-dataset/metasync-backups`.

Tips of trees: rewrite `82b5dad`, tray `f647a75`, tauri `468fa9c`.

---

## 3. Architecture map

### Storage (two-plane — decision: KEEP JSON, single VPS = no multi-instance)
- `matches.json` — append-only SSOT, **5000-game RING** (⚠ latent bug: see §6).
- `records.json` — derived cache, ELO replay on boot.
- **SurrealDB** — read-mirror only (never source of truth).
- **Redis** (7.0.15) — pub/sub + capped Streams bus + AOF.
- **TigerBeetle** — money ledger (feature `tb`).

### Realtime bus
Redis pub/sub → **push-gateway** SSE crate (`:7251`, `/stream/{channel}` + `/tourney/{id}/stream`,
XRANGE gap-fill) → nginx `/skinsync/rt/` → PWA `getChannel('matches')`. Channels: `leaderboard`,
`presence`, `matches`, tournament channels.

### Deploy
- **Server**: diff local `skinsync/src` vs VPS `/opt/skinsync-src` FIRST (multi-session!), scp, build on VPS
  (`cargo ~/.cargo/bin`, feature `tb`), atomic-mv binary swap. nginx full-prefix `/skinsync/`.
  Env `/etc/skinsync.env`.
- **PWA**: `cd app && BASE_PATH=/app npm run build` (⚠ `MSYS_NO_PATHCONV=1`), tar-over-ssh to
  `/var/www/metasync-app/app`, nginx `^~ /app/`.
- **Release (updater)**: minisign key `~/.mvc-updater/signing.key`; pubkey `E98EE59FD430E668` /
  `RWRo5jDUn+WO6ZTvJokalltgwzdBSQ+VdX7MRNZB7iI9rrQhPXH48FL1`. Manifests → `nobd.net/skinsync/update/`:
  - **Tauri app** → `latest.json` (nested Tauri manifest).
  - **Tray agent** → `agent-latest.json` (FLAT: version/url/sig/notes) + planned `agent-latest-linux.json`.
  - GitHub releases repo `t3chnicallyinclined/mvc2-metasync`.
  - ⚠ **Edit changelog/index.html strings via the Edit tool, never shell heredocs** (a mangled heredoc
    shipped a crash-on-launch build once). See `mvc-live-skins/docs/RELEASE.md`.
- **Linux builds**: Beelink `Tris@192.168.1.183`, key `~/.ssh/maplecast_automation`, distrobox `tauri44`.

---

## 4. Load-bearing facts (don't re-derive these)

- **`d0328` mode discriminator**: `session = *(exe+0xacd3a8)`; `session+0xd0328` = **1 ranked / 2
  custom-versus / 4 custom-spectator** (role-independent). This is THE ranked/custom signal. Ranked results
  report via Capcom MtNetwork `@MtNetRanking::Score`, NOT Steam UserStats. `read_my_lobby().in_lobby` =
  ownership, not mode. (Memory: `mvc-ranked-custom-discriminator`.)
- **Tray minisign `.sig` is base64-encoded** (`cargo tauri signer` convention) → must base64-decode to the
  `untrusted comment:` text before `minisign_verify::Signature::decode`. Fixed in `updater.rs verify_signature`.
- **Tray manifest is FLAT**, not the Tauri nested manifest — that's why the tray once read "Up to date
  (v0.2.5)" (it couldn't parse the nested form). Tray has its own `agent-latest.json`.
- **`safe_to_apply()` = `crate::mem::find_game_pid().is_none()`** — never swap the binary mid-game.
- **Rank scheme mismatch**: server `elo::rank_tier` returns a *different* ladder ("Silver"…) than the client
  Marvel ladder (Iron→Gold→Vibranium→Adamantium→Herald→Infinity→Galactus, `$lib/ranks` `rankOf`). **Client
  owns the badge** — always derive rank client-side from rating via `rankOf`. (Reconcile = §7 item.)
- Lobby CSteamID / join-link RE, per-set win tally, side-parity (EVEN=P1/ODD=P2 via pointer-follow) — all in
  memory files `mvc-lobby-*`, `mvc-live-skins-side-calibration`.

---

## 5. In-flight follow-ups (the "finish the follow-ups" list)

Ordered. Each has its exact next step so you can resume cold.

### A. Phase B — live session data (needs a **0.2.7 reader** release) — *IN PROGRESS, do this first*
Goal: now-playing cards show the running set score live; SessionModal live-updates.
- **Reader** (`tray-agent/src/reader.rs`): `report_live_match` currently sends `{opp, my_chars, opp_chars}`.
  Extend it to also send `session_id` + running set score (`p1`/`p2` wins) + lobby `join_link`. A sibling
  fn at ~1747 already assembles `{opp, session_id, p1, p2, ...}` — lift that shape into the live report.
  `read_my_lobby()` (reader.rs:611) already returns `join_link`.
- **Server** (`skinsync/src/routes.rs handle_match_live` ~910): parse the new fields → store on `ActiveMatch`
  (`models.rs:334` — add `session_id`, `p1`, `p2`, `join_link`) → expose in `now_playing`
  (`app.rs matches_feed_snapshot`).
- **PWA**: `MatchBanner` live variant renders the live set score; `SessionModal` uses its reserved `live`
  prop to poll `/skinsync/session?id=` (or subscribe to the matches channel) while open.
- **Ship**: 0.2.7 tray release → auto-updates via the now-working pipeline.

### B. Wire the **Spectate** button (currently stubbed on the live banner)
- Depends on A shipping `join_link`. Build `steam://joinlobby/2634890/<lobbyid>/<owner>` from the reported
  link; only enabled for lobby/tournament matches with a shareable lobby (ranked has none).

### C. Reconcile server `rank_tier` with the client Marvel ladder (cosmetic)
- Either make `elo::rank_tier` emit the Marvel names, or strip rank from server payloads and let the client
  derive everything via `rankOf`. Client already does the right thing today — this only matters if any
  server-rendered surface shows a rank string.

---

## 6. Known debt / latent bugs (not urgent, don't forget)

- ⚠ **`matches.json` 5000-game ring** — once lifetime matches cross 5k, ring eviction corrupts lifetime
  stats (ELO replay reads a truncated history). **Fix before 5k**: migrate append-only store to JSONL
  (unbounded, streamed) so nothing is evicted. Currently well under 5k.
- **`backfill_steam_profiles`** does a ~4s SYNC HTTP call on the single request thread (`app.rs:853`) →
  head-of-line blocks other requests during backfill. Move off-thread. Deferred.
- **28 mislabeled games** (ranked recorded as lobby pre-fix) left as-is (safe default). Can flip specific
  known-ranked sets if the user identifies them.

---

## 7. Next actions (start here)

1. **Phase B reader** — extend `report_live_match` (session_id + set score + join_link). §5.A.
2. **Server `handle_match_live` + `ActiveMatch`** — accept/store/expose those. §5.A.
3. **PWA live set score + SessionModal live poll**. §5.A.
4. **Cut 0.2.7 tray release** (Windows first; auto-update validates). §5.A.
5. **Spectate wiring** once join_link flows. §5.B.
6. **Rank reconcile** (cosmetic sweep). §5.C.
7. **Bazzite/Linux tray cutover → 0.3.0** (the big one): per-platform tray manifest (cfg-gate
   `UPDATE_MANIFEST` → `agent-latest-linux.json`), sign/publish Linux tray binary, bootstrap+test on
   Bazzite, installer/migration to retire the Tauri app. Detail: `docs/LINUX-PORT-WORKSTREAM.md`.
8. **Debt sweep** when convenient: JSONL ring migration (§6), off-thread backfill (§6).

## 8. Detail docs (the map's territory)
- `docs/WHATS-NEXT.md` — PWA forward plan + Phase 3 command protocol (skin-apply push).
- `docs/PHASE3-LOWLATENCY-ARCH.md` — tray agent design + low-latency skin push.
- `docs/LINUX-PORT-WORKSTREAM.md` — the 0.3.0 Linux cutover.
- `docs/TOURNAMENT-REALTIME-ARCH.md`, `docs/ROADMAP-METASYNC.md` — tournament platform.
- `mvc-live-skins/docs/RELEASE.md` — the release runbook (⚠ heredoc warning).
- Memory: `mvc-ranked-custom-discriminator`, `metasync-tray-update-pipeline`, `metasync-storage-and-backup`,
  `mvc-portable-rewrite`, `mvc-tournament-realtime`.
