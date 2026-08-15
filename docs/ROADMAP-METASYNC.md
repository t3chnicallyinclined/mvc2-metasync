# MetaSync — Roadmap & Brainstorm (updated 2026-08-15)

Captured live during the pointer-follow session. Foundation is now solid: **everything about a match derives
from one confirmed anchor** (`fighter_array = *(exe+0xac6ef0)+0x3f24`) + the battle-globals struct
(`array+0x2e5dc`: phase, win_result, timer, in_match, round#). See `MVC2-STEAM-EXPERT.md` §DEFINITIVE UPDATE.
That anchor is what makes most of the below feasible.

---

## Status (2026-08-15) — current shipped `0.1.59`

### DONE
- **Server reorg (all 4 phases).** P0: 12 golden tests locking the SSOT→cache derivation + a boot data-loss
  guard (corrupt `matches.json` → abort, never wipe). P1: dead-code removal. P2: replay/verified-ELO dedup
  into `replay_elo_and_verified`, the shifted-offset table (in-struct corrections incl. `OFF_HITSTUN`
  `0x909→+0x1d1`, `combo_recv→+0x1ca`). P3: **`main.rs` split into 13 modules** (behavior-neutral, tests
  green). See `docs/ARCHITECTURE.md` for the module map + `SERVER-DEPLOY-HANDOVER.md` for the new
  multi-file deploy.
- **W/L tape-repair.** Root cause was `OFF_HEALTH 0xb44 > stride 0x738` (read the next slot's health → every
  win logged as a loss); fixed to `0x40c` in 0.1.35. The corruption was NOT a uniform inversion, so records
  were re-derived from the actual **KO recordings**: kept 162 tape-verified matches, dropped 152 without a
  usable tape. TRIS NOBDOG = 20-34. This supersedes §5's "largely done in 0.1.43".
- **Regions / represent (§3).** `/regions` endpoint + country/city filters on leaderboard + tierlist;
  `locations.json` (opt-in per-player country/region/city) + `cities.json` (~69k-city `/cities` search); US
  "scene" regions + country flags. Shipped 0.1.54–0.1.56.
- **SSOT + `disp_name`.** `matches.json` is the single source of truth; `records.json` is a pure cache
  rebuilt on boot; `App::disp_name` is the one display-name resolver; identity is **SteamID everywhere**.
- **Updater fix.** Updater now checks **nobd first** (was GitHub-first → CDN detection lag). Every release
  must ship to **both** endpoints — nobd `/opt/skinsync/update/` AND `gh release create`; missing either
  stalls the updater.

### IN PROGRESS / NEXT
- **Chip damage → `0.1.60`.** True chip via the hitstun-block rule (`CHIP = Σ max(0, prev_hp − hp)` over
  frames where `hitstun(+0x1d1)==0`; a real hit sets `+0x1d1=0xFF`). The offset table is in; the chip
  *feature* is **pending one live block-test** on the Steam build to confirm `+0x1d1`'s 0xFF/0 behavior
  (`scratchpad/chip_watch.py`).
- **Client reorg P3 (deferred).** Split the client `sync.rs` into submodules the way the server was — not
  yet started.
- **Git sync.** `main` is behind the working tree — push the reorg + repairs (parent handles git).

---

## 1. Public web presence on nobd.net (leaderboards + stats + sign-in)

Goal: the leaderboard/stats that live in the desktop app become **viewable on the web** at nobd.net, users can
**sign in**, and every stat page is **shareable**.

- **Read-only web mirror first.** The server already stores records as JSON (skinsync). Expose read-only
  leaderboard + per-player + per-match pages under `nobd.net/metasync/…`. No app needed to *view*.
- **Sign-in = Steam OpenID (OAuth-like).** Steam's OpenID 2.0 is the natural fit — the identity is already a
  SteamID64, so login just proves ownership of the SteamID the desktop app reports. No new account system.
  (Steam Web API key server-side; client redirect to `steamcommunity.com/openid`.) Later: link the desktop
  app's local identity to the signed-in web session so a player "claims" their records.
- **Shareable stat pages.** Every page (`/p/<steamid>`, `/m/<matchid>`, `/lb/<board>`) gets:
  - a clean short link + copy-link button,
  - Open Graph / Twitter-card meta (title, record, rank, a rendered preview image) so a paste into
    Discord/Twitter/etc. auto-embeds — this is most of "shareable to different platforms" for free,
  - an optional PNG "stat card" render (server-side or canvas) for image-first platforms.
- Ties into the existing KOM/SurrealDB unification thinking (`KOM-SURREALDB-UNIFICATION.md`) — but the JSON
  server is fine to start; don't block the web mirror on a DB migration.

## 2. Match context — ranked vs casual/lobby (+ badges)

We currently record every match the same. We should **know the match type** and label it.

- **RE task:** find the flag that distinguishes **ranked matchmaking** from a **lobby/casual/friend** match.
  Likely near the netplay-session struct we already locate (the co-located SteamID pair) or a session-config
  global. Method: capture memory in a ranked match vs a lobby match, diff for a stable byte that differs. With
  the live-dump Ghidra pass, the matchmaking code will name it outright.
- **Product:** a **RANKED badge** on records that were ranked; casual/lobby marked separately. Split the stats
  (ranked ladder vs casual) so the competitive ladder isn't polluted by lobby warmups.
- Server: add `match_type: "ranked" | "casual" | "lobby"` to the record; leaderboards filter on it.

## 3. Regional representation & regional stats — ✅ SHIPPED (0.1.54–0.1.56)

> Delivered: `/regions` + country/city filters, `locations.json` + `cities.json`/`/cities`, US "scene"
> regions, country flags, opt-in self-declared represent field. The forward ideas below (map/heat view,
> web `/region/<x>` pages, shareable "Best in <city>" cards) remain open.

Let players **represent a region/city** and build community/rivalry stats around it.

- **Profile field** at the top by the user profile: pick **region / city** you represent (free-form or a
  curated list; store an ISO region + optional city string). Self-declared (no geolocation needed for v1).
- **Stats we can then compute:** wins by region/city, **"best in region"**, region-vs-region aggregate,
  city ladders, a map/heat view later. Cheap to add now — it's just a tag on the player + rollups server-side.
- Pairs naturally with the web pages (§1): `/region/<x>` leaderboard, shareable "Best in <city>" cards.
- Privacy: region/city is **opt-in and self-declared**, never inferred from IP.

## 4. Frame-perfect replays (brainstorm)

The live pointer changes what's possible: we can read the **complete per-frame state** (every fighter's
position, animation state, health, meter, facing, palette) *and* inputs, deterministically. Two ways to build
replays — we should do the simpler one for the prototype and keep the door open to the "real" one.

### A. State-replay (recommended for the prototype)
Record the **visual state every frame**; play it back by drawing sprites. No engine, no ROM needed at playback.
- **Capture** (per frame, off the anchor / in-process hook — cheaper than RPM at 60fps): for each of the 6
  fighters — `char_id`, animation-state id + frame counter, `pos_x/pos_y`, facing, current palette/skin, health,
  plus HUD globals (timer, meter, combo, round#, win_result). We can read all of this *now*.
- **Store**: append per-frame records → a `.replay` blob, **delta-encoded** (most fields change slowly) +
  gzip. Ballpark: ~30–60 B/frame raw × 60 fps → a few MB/match raw, compresses to hundreds of KB. Fine.
- **Playback**: the lightweight 2D sprite renderer we already built (`webgputest.html`) draws each fighter's
  sprite at the recorded position/frame, with the recorded palette. **Frame-perfect because we recorded actual
  frames** — no re-simulation, no desync risk. Effects don't need to be 100% for the prototype (skip
  hit-sparks/screen shake; just bodies + positions + HUD).
- **The one real dependency**: mapping `(char_id, anim_state, frame) → sprite atlas frame`. We already decode
  sprites (Skin Studio / `rom-reader`) and have the per-char move/animation tables from the mvc2-ai work
  (zachd/anotak). So the mapping is mostly in hand — this is the piece to nail for a clean prototype.

### B. Input-replay (the "real"/tiny version, later)
Record **initial state + per-frame inputs** and **re-simulate in the engine** (deterministic — proven by the
maplecast `.mctele` determinism work). Data is tiny (a few bytes/frame). But playback needs the *engine*
(flycast+DC ROM, or the recompiled core) → in-browser that's heavy + hits BYOR (can't ship the ROM). Keep this
for a native/desktop "verified replay" or the AI pipeline, not the web prototype.

### Reuse what exists
- **Capture format**: the mvc2-ai `.mctele` exporter already captures full-state + inputs, determinism-proven —
  the capture side is largely solved; adapt it to MetaSync's live-pointer read.
- **Renderer**: `webgputest.html` lightweight sprite renderer runs in the browser today.
- **Sprites/palettes**: Skin Studio's NAOMI sprite+palette decode; skins already flow through MetaSync.

### Open questions
- Capture cadence: in-process hook @60 fps vs RPM sampling — hook is cheaper and avoids frame drops.
- Where replays live: attach to the match record on the server; a `/m/<id>` page plays it in-browser (§1).
- Trust: state-replays are "recordings" (could be edited); input-replays are verifiable by re-sim — flag which
  is which if replays ever feed rankings/highlights.

## 5. W/L + session/game-count accuracy (Wave 2 — off the battle-globals)

> **Inverted W/L is FIXED** (offset `0xb44→0x40c`, 0.1.35) and the historical records were tape-repaired
> (see Status → DONE). The **set-score miscount** below (Wave 2) is still open.

**Known bug:** the set score can be WRONG at the start of a set — e.g. the FIRST game already shows `0-1` /
`1-0` as if a game was already played. Root: the app infers the game count/score from health-KO edges and
carries session state across matches, so a stale/miscounted game slips in. The battle-globals fix this with
ground truth:
- **`round_counter` (`array+0x2e617`)** = game index within the set → count games directly, stop inferring.
- **`win_result` (`array+0x2e61a`)**, latched at KO (read on the `phase→≥5` edge) = the per-game winner → build
  the set score from actual results, not health guesses.
- **Clean session reset**: a genuinely new set = a NEW netplay pair (SteamID pair) AND `round_counter` back to
  0 / `in_match` cycling — reset the score *then*, never on a transient opponent flicker (the old carryover
  cause). Also pin `lpn→side` with one clean ranked read through the pointer.

Wave 2 = replace health-inference W/L + heuristic game counting with `(win_result + round_counter)` gated on
`phase`/`in_match`. This is the fix for both the inverted W/L (largely done in 0.1.43) and this miscount.

## 6. Tournament mode (the flagship)

**The unlock:** in a lobby, the **host is spectating** — their client renders every match, so the fighter array
+ both players' SteamIDs + `win_result` are all in the *host's* memory. So **only the host/TO runs MetaSync**;
players just need Steam + the game. The host's spectator view becomes the data source for the whole bracket,
live stats, and stream overlay. This is the lowest-friction tournament tooling possible.

### Flow (target)
1. TO creates a tournament on nobd.net (bracket + seeds). Players sign in with **Steam OpenID** (§1) → their
   SteamID is registered to their bracket slot.
2. TO opens MetaSync and hosts the in-game lobby.
3. App reads the **current Steam lobby id** → the bracket page shows a **one-click join link** for the next
   match's two players (`steam://joinlobby/2634890/<lobbyid>/<hostSteamID64>`). They click → they're in the
   host's lobby.
4. TO (or auto) starts the match; **host spectates**. App captures players (by SteamID), chars, `win_result`,
   score → **auto-reports the result and advances the bracket**. No manual score entry.
5. **Live overlay**: an OBS browser-source reads the current match (names, chars, health, meter, set score,
   ranked badge) from the server → on stream / on the venue screen. Plus regional tags (§3) for hype.

### Can we automate the links? (the key question)
Likely **yes**, and it's the crux of "players just click links":
- **Join URL** is the standard `steam://joinlobby/<appid>/<lobbyid>/<owner_steamid>`. Clicking it makes Steam
  launch/focus the game and join the lobby — *if the game registers Steam lobby-join* (the Fighting Collection
  supports Steam "Join Game" from the friends list, which uses exactly this path → very likely works). **Test:
  read a live lobby id, hand-build the URL, click it from another account.**
- **Reading the lobby id**: when the host creates a lobby, Steam assigns a 64-bit lobby id. It lives in the
  Steam client + almost certainly in the game's netplay/session memory near the SteamID pair we already locate.
  **RE task**: find the current lobby id (diff "no lobby" vs "hosting a lobby"); with the live-dump Ghidra pass,
  the `ISteamMatchmaking`/lobby-create call names it.
- With those two, the bracket page can mint + post the join link automatically; players click, land in the
  lobby. The game's *internal* "who fights whom / ready up" is still the game UI — but the web can **coordinate
  it** (tell each pair when it's their turn, detect via SteamIDs when the right two are in, detect match end via
  `win_result`), so the TO's clicking is minimal.

### RE / build tasks
- **Verify spectator capture**: confirm the pointer + SteamID pair + `win_result` all read correctly while
  *spectating* (not playing). Very likely (host renders it), but must confirm — this is the whole premise.
- **Lobby id read** (above) → join-link generation.
- **Player identity in a lobby**: read all SteamIDs present in the lobby (not just a 2-player pair) so the app
  knows who's in the venue; map to bracket slots.
- **Bracket engine** on nobd.net (create/seed/advance) + **result webhook** from the host app.
- **OBS overlay** page (browser source) reading the live match + bracket from the server.
- **Ranked/casual/lobby detection** (§2) doubles as "is this a tournament lobby match."

### Open questions
- Lobby capacity (how many can sit in one MvC2 lobby at once?) — determines whether one lobby is the whole
  venue or players rotate through. Either works; the app tracks who's in via SteamIDs.
- Does `steam://joinlobby` reliably drop a clicker straight into the *specific* lobby, or into a join prompt?
  (Test.) Fallback: Steam friend-invite is always available manually.
- Nothing here touches game files or memory-writes — it's reading our own client + standard Steam invite links.

---

## Cross-cutting
- **One source of truth**: all of the above hangs off the match anchor + battle-globals + the netplay pair.
  Keep deriving from pointers, not scans (the lesson of this whole session).
- **Privacy**: region/city opt-in; the public repo (`metasync`) stays clean of any AI/training/data-mining
  framing (that lives in the private mvc2-ai side).
- **Sequencing**: web read-mirror + share links (fast win) → ranked/casual flag (small RE) → regional tags
  (cheap) → replays (the big one; state-replay prototype first).
