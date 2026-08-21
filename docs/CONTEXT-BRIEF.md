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

## 2x. 0.2.9 — SHIPPED (Phase 3 web skin picker, the tray-only unlock), 2026-08-20

The web is now the skin picker; the tray applies. This is what makes tray-only viable (the last real reason
the Tauri desktop UI existed).
- **Server** (`skinsync`): new dedicated **loadout store** — `loadouts.json` = `steamid → Vec<CharSkin{cid,
  colors}>` in the **agent-native palette shape** (16 × 0xRRGGBB), so web-writes and tray-reads match with no
  parsing. `GET/POST/DELETE /skinsync/loadout` (all bound to the caller's token SteamID). `set_char_skin`
  upserts + persists + publishes to a private **`cmd.<steamid>`** channel (scaffolding for the SSE push).
- **Agent** (0.2.9): `reader::fetch_loadout` (auth GET) + a `loadout-sync` poll thread mirror the loadout into
  the painter's in-memory map, **merged OVER local `skins.json` (web wins per char)**. Palette-only → the
  `paint_live` path; **zero per-tick file I/O**. Applies on the next match within ~6s.
- **Web** (`/app/skins`, linked from Settings → Skins): a per-character **16-swatch palette editor** (portrait
  grid → editor → Save/Reset). Stock palettes bundled from `idle_frames bank0` (`$lib/stockPalettes.ts`).
- **Deliberately v1**: agent **polls** (no SSE yet) so it needed no `cmd.*` authz or SSE client. Enrichments:
  (a) live SSE push over `cmd.<steamid>` **with push-gateway authz** (only your bearer may subscribe to your
  own channel — the security-sensitive bit); (b) a **community skin-library browser** (needs the skin catalog
  — palettes + names — ported to the server, like the portraits were).

## 2y. 0.2.8+ follow-up — SHIPPED (real character portraits + teams on the feed), 2026-08-20

PWA + server redeploy (no version bump — folded into the 0.2.8 the user is testing; no tray change).
- **Picked characters** now render on the versus screen (`MyMatch`) as **real idle portraits** — Point
  starred, orange/blue plate tint — with an abbreviation-tile fallback.
- **Portrait pipeline** (`scripts/render-char-portraits.py`): batch-renders 59 idle portraits from the
  desktop repo's `idle_frames.json` (idle frame `px` = base64 → w×h palette indices, coloured through the
  16-colour `bank0`) → lossless webp **~2 KB each (108 KB total)** → `app/static/chars/<id>.webp`. **ROM-
  derived → git-ignored**; shipped via the PWA deploy only, served at `/app/chars/<id>.webp`. Rerun the
  script to regenerate. (The web can't touch the ROM — this is the "host sprites, point at them" approach.)
- **Teams now ride the live feed**: `now_playing` carries `chars` per SteamID (`app.rs` — `ActiveMatch.chars`
  already stored), so MyMatch reads teams straight off the feed and dropped a fetch (3 → 2: opp profile +
  matchup). More optimized + live.

## 2z. 0.2.8 — SHIPPED (versus screen + Regions-in-Ranks + autostart default), 2026-08-20

Live across server (no change — reused existing endpoints) + PWA + Windows tray (Tauri frozen 0.2.6).
- **Live versus scoreboard** (`app/src/lib/components/MyMatch.svelte`, mounted top of the Match tab): the
  signed-in user's current game as a Tauri-parity versus hero — skewed orange/blue plates (avatar, flag,
  rank badge + ELO, current team), gold VS, live set score, IN MATCH pulse, and a matchup-intel strip
  (win% · H2H · best team vs them · their kryptonite). Presence + live score from the `nowPlaying` feed;
  teams from `profile.current_match`; intel from `/skinsync/matchup`. **All server data already existed** —
  pure PWA work.
- **Regions off the primary nav → folded into Ranks** as a 🌍 board mode (a sibling of the scope control;
  swaps in the city-ladder board via the regions store + RegionRow). Tab bar 5→4. `/regions` stays a
  deep-link. `nav.ts` + `TabBar.svelte` grid + `ranks/+page.svelte`.
- **Start-with-Windows now defaults ON and self-heals** (`tray-agent`): replaced the first-run-only gate
  (which could never re-enable for installs whose first run predated it) with a choice model — while the
  user has never toggled it, every launch re-asserts the Run key (also repairs a stale path after a
  move/auto-update); an explicit OFF is honored forever. `prefs.rs` (`autostart_choice`) + `main.rs` + `tray.rs`.
- Shipped same pattern as 0.2.7: PWA atomic-swap deploy; tray non-latest GH `v0.2.8` + `agent-latest.json`
  → 0.2.8; served exe sha256 == signed. v0.2.6 still "latest" (frozen app protected).

## 2a. 0.2.7 — SHIPPED (Phase B + Spectate), 2026-08-20

Live across server + PWA + Windows tray (Tauri app frozen at 0.2.6). What shipped:
- **Phase B live set score**: reader reports `session_id` + caller-relative `my_wins`/`opp_wins` + a
  `steam://joinlobby` link on `/match/live`; server stores them on `ActiveMatch` (per-SteamID `wins` that
  converge), exposes them in `now_playing`, and fires a `match_live` bus delta on score change; PWA shows a
  live score pill on Now Playing cards.
- **Working Spectate**: the live banner's Spectate is a real join link for custom/tournament lobbies (empty
  → disabled for ranked). Live cards open the **SessionModal**, which silently re-polls the set every 5s.
- **Deploy specifics that worked**: server built on VPS **`--features tb`** (plain build silently drops the
  money ledger — always include it); PWA must be **rebuilt after a version bump** before deploy (first pass
  shipped a stale 0.2.6 bundle); tray release = non-latest GitHub `v0.2.7` (keeps v0.2.6 "latest" so the
  frozen Tauri app's GitHub fallback still serves 0.2.6) + `agent-latest.json` → 0.2.7. Served exe sha256
  verified == signed exe.

## 2. Prior shipped state (0.2.6 — LIVE)

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
**✅ A (Phase B) and B (Spectate) SHIPPED in 0.2.7 — see §2a. Remaining: C (rank reconcile) + §7.7 (0.3.0).**

### A. Phase B — live session data (needs a **0.2.7 reader** release) — ✅ DONE (0.2.7)
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

## 6. Known debt / latent bugs

- ✅ **`matches.json` eviction** — FIXED (2026-08-20). `record_result` no longer drains the oldest matches;
  the log is the append-only SSOT replayed into records.json, so eviction eroded lifetime stats.
  `MATCHES_CAP` is now a soft warn only. (If persist()'s full-file rewrite ever gets large — many tens of
  thousands of matches — migrate to a JSONL/event-sourced store; the `verified` flip makes pure append-only
  need event-sourcing, which is why we removed the cap rather than switching format now.)
- ✅ **`backfill_steam_profiles` off-thread** — FIXED (2026-08-20). Misses enqueue to a detached resolver
  thread; results land in an inbox drained at the top of `handle()` (in-flight set dedupes). No more ~4s
  request-thread stall — cache-miss names resolve on the next lookup.
- ✅ **Rank reconcile** — NO-OP: server `elo::rank_tier` and client `$lib/ranks RANK_TIERS` already match
  exactly (Iron→…→Galactus, 5-game Civilian gate). The old "Silver mismatch" note was stale.
- **28 mislabeled games** (ranked recorded as lobby pre-fix) left as-is (safe default). Can flip specific
  known-ranked sets if the user identifies them.

---

## 7. Next actions (start here)

1. ✅ **Phase B reader** — DONE (0.2.7). §5.A / §2a.
2. ✅ **Server `handle_match_live` + `ActiveMatch`** — DONE (0.2.7).
3. ✅ **PWA live set score + SessionModal live poll** — DONE (0.2.7).
4. ✅ **Cut 0.2.7 tray release** — DONE (non-latest GitHub v0.2.7 + agent-latest.json). Auto-update pending
   the user's next tray check (they were on 0.2.6).
5. ✅ **Spectate wiring** — DONE (0.2.7); real join link on lobby/tourney live cards.
6. ✅ **Rank reconcile** — NO-OP (schemes already match). §6.
7. ✅ **Follow-up debt** — matches eviction + off-thread backfill DONE. §6.
8. ✅ **Phase 3 web skin picker** — v1 DONE (0.2.9). §2x. This unlocks tray-only.
9. **Phase 3 enrichments** (optional, before/after cutover): SSE live-push over `cmd.<steamid>` + push-gateway
   authz; community skin-library browser (catalog port).
10. **Bazzite/Linux tray cutover → 0.3.0** (the big one, NEXT MAJOR): per-platform tray manifest (cfg-gate
    `UPDATE_MANIFEST` → `agent-latest-linux.json`), sign/publish Linux tray binary, bootstrap+test on
    Bazzite, installer/migration to retire the Tauri app. Detail: `docs/LINUX-PORT-WORKSTREAM.md`.
    **With Phase 3 shipped, the tray now has full skin management without the Tauri UI — cutover is unblocked.**

**Live-test 0.2.7 (do with the user):** open the tray menu → it should offer "Update to 0.2.7" (game closed
to apply). After update, in a live match the web app's Now Playing card should show the running score; a
custom-lobby match should show a working Spectate button + a live-refreshing SessionModal.

## 8. Detail docs (the map's territory)
- `docs/WHATS-NEXT.md` — PWA forward plan + Phase 3 command protocol (skin-apply push).
- `docs/PHASE3-LOWLATENCY-ARCH.md` — tray agent design + low-latency skin push.
- `docs/LINUX-PORT-WORKSTREAM.md` — the 0.3.0 Linux cutover.
- `docs/TOURNAMENT-REALTIME-ARCH.md`, `docs/ROADMAP-METASYNC.md` — tournament platform.
- `mvc-live-skins/docs/RELEASE.md` — the release runbook (⚠ heredoc warning).
- Memory: `mvc-ranked-custom-discriminator`, `metasync-tray-update-pipeline`, `metasync-storage-and-backup`,
  `mvc-portable-rewrite`, `mvc-tournament-realtime`.
