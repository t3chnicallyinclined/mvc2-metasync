# 🕹 NOBD ARCADE — the house hosts you (workstream)

**The vision (owner):** nobody creates lobbies. When a quarter match locks (and later, when a bracket
match goes live), the **nobd_arcade** bot account creates the lobby itself — right settings (FT2 default,
size, passcode), both players get a launch link, the house spectates and can kick. The gs-217 fixes
(both-side links, FT2 sets, banner balance) ride THIS release — do not ship them alone.

**The one hard gate (⚠ everything else is buildable now):** does the game cleanly join and run a set in
a lobby whose OWNER is a headless SteamAPI process? Prior RE (memory `mvc-headless-steam-vps`): the bot
creates real lobbies, P2P transport works, but a JOINER waited on the HOST's first game packet in the
direct-match flow. In lobby mode fights are member↔member (owner-independent, proven with a real-game
owner). Unproven: headless owner + two real members. **GATE-1 = a 20-minute live probe with the owner**
(bot lobby up → owner clicks link → does the game enter, see the lobby, start a set?). If it fails:
fallback A = bot feeds the type-5 first packet (wire notes in memory), fallback B = real game under Wine
as the owner. Design everything so the lobby PROVIDER is swappable.

## Architecture (locked for this workstream)
```
skinsync (nobd VPS)                    arcade-host daemon (OVH 15.204.141.58, nobd_arcade Steam login)
  wager lock ──HTTP POST──────────────►  /lobby/create {ft, size, passcode?, tag}
  { … }  ◄──────────────────────────────  {ok, lobby_id, owner_steamid}
  attach lobby to wager → both rails get steam://joinlobby/2634890/<lobby>/<owner>
  settle (FT2 via memory-read referee) → house fee: winner takes pot−1, nobd_arcade +1 (code 8 match-fee
    — the neutral-host fee design activates for the first time; fee ONLY when the bot hosted)
  /lobby/kick {lobby_id, steamid} · /lobby/close {lobby_id} · GET /health
```
- Transport: plain HTTP between the two VPSs, `X-Arcade-Key` shared secret (env both sides), 2s timeout,
  **fail-open**: bot unreachable ⇒ today's challenger-hosted flow (warn + heartbeat) — game night survives.
- Redis's role: skinsync already publishes `wager_locked` on the bus; the daemon does NOT subscribe
  cross-VPS — the synchronous create-at-lock call is the contract (simpler, and the lobby id must be in
  the lock response anyway). Redis stays what it is: the client push bus.
- TigerBeetle: no schema change — `match-fee` (code 8) transfers to nobd_arcade's SteamID account; the
  bot's quarters accumulate like any player's (Station Hero economics later).
- Client: gs-217 already renders both-side links from `lobby_id`/`lobby_owner` — bot-hosted wagers light
  up with ZERO client change; only copy ("the arcade is hosting — jump in") is a nice-to-have.

## Phases
| # | What | Owner | Gate |
|---|---|---|---|
| 1 | Inventory the headless-bot code (find local copies + OVH state), stand the daemon skeleton up to the HTTP contract above | steam-RE agent | — |
| 2 | skinsync: `arcade.rs` client (create/kick/close, key, timeout, fail-open) + wager-lock hook + settle house-fee when bot-hosted + `arcade_hosted` flag in row() | ledger/server agent | tests green |
| 3 | **GATE-1 live probe** (owner + bot lobby) | owner + main session | ⚠ HUMAN |
| 4 | Tournament stationed-mode: bot as an auto-enrolled host station | after gate | GATE-1 pass |
| 5 | Release: merge nobd-arcade → main, ship (carries gs-217) | main session | GATE-1 pass |

## Conventions
- Worktree `mvc-live-skins-arcade` [branch nobd-arcade, tip = gs-217]. skinsync/ copy inside is the
  server tree for THIS lane. One writer per file — the two agents own disjoint trees (daemon repo vs
  skinsync/); the main session owns web/index.html.
- Secrets: the arcade key goes in /etc/skinsync.env + the daemon's env — never in either repo.
- nobd_arcade's SteamID = the daemon reports it (`owner_steamid`) — never hardcode it client-side.
