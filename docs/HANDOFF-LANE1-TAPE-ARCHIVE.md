# HAND-OFF → LANE 1 (RetroReceipts-server): tape archive in R2 + the public tape read (2026-09-03)

Tris: "we can store the tapes/matches in an R2 bucket and users can pull the tape for a match based on match id /
session id"; "make it obvious that replays are available … anywhere a match is shown … or 'request replay' from our
archives"; "the whole point of the webapp is that users need to sign in to see the replays".

The PWA (`RetroReceipts-agent/pwa/src/lib/replay/source.ts`) is being built against the contract below and degrades
gracefully while it 404s. Nothing here needs a tape-format change; the agent already uploads everything required.
Companion: `HANDOFF-LANE1-GS-MAX-BODY.md` (the 8 MB body limit still rejects every v5 tape — first thing to fix).

## 1. Storage

- **Hot:** the existing gs tape dir (`GS_DIR`, 30k files / 6 GB caps in `config.rs`). Keep the newest N (product decision:
  the LIVE tab copy says "the last 100 live results keep a replay"; make N a config value, default 100 per… whatever
  unit lane 1 prefers — global is fine to start).
- **Archive:** R2 bucket (the nightly backup bucket already exists — memory `metasync-storage-and-backup`; use a
  prefix, not a new bucket): `tapes/<session_id>/<match_key>.json.gz` + a sidecar `tapes/<session_id>/<match_key>.meta.json`
  with `{match_key, session_id, match_index, reporter, winner, loser, p1_team, p2_team, stage_id, ts, frames, bytes,
  agent_ver, tape_ver, sha256}` (all of these are top-level fields of the uploaded envelope; copy them verbatim).
- **Eviction from hot = move to archive** (never delete): on every hot eviction, write the object + sidecar to R2 first,
  then unlink. Backfill: one pass over the current hot dir.
- **Paid save** (Tris): a flag in the sidecar `saved_by:[steamid…]` that exempts the tape from any future archive
  pruning; the PWA already shows the "Save this tape" button disabled with "coming soon" — wire it to
  `POST /rr/tape/save {key}` when the coin price is decided.

## 2. Endpoints (all under the existing `/rr/*` router; **all authed** — the Steam OpenID session cookie/token the PWA already sends)

| method | path | body / query | response |
|---|---|---|---|
| GET | `/rr/tape?key=<match_key>` (also accept `session=<session_id>` → list) | | `{ok, state:'ready'|'pending'|'archived'|'none', tape_url?, frames?, ts?, session_id?, match_index?, bytes?}` |
| POST | `/rr/tape/request` | `{key}` | `{ok, state:'pending'}` — pulls the object from R2 into hot (async job; idempotent; rate-limit per user) |
| GET | `/rr/tape/<match_key>.json.gz` | | the tape bytes, `Content-Type: application/gzip`, `Cache-Control: private, max-age=86400`, ETag = sha256; **authed**; 404 while not hot |
| POST | `/rr/tape/save` | `{key}` | (later) marks `saved_by` |

`state` rules: `ready` = hot file exists; `pending` = a request is in flight OR the match ended < 3 min ago with no upload
yet; `archived` = sidecar exists in R2, not hot; `none` = never received. The result payload of `/rr/session` /
live-results rows should also carry `replay: state` (contract C1 in `LIVE-TAB-SPEC.md` §11) so lists render the
affordance without one probe per row.

## 3. Bus

When a tape lands in hot (upload or archive pull), publish on the existing Redis/SSE bus the event the LIVE tab already
listens to for results, with `{type:'tape', key, state:'ready'}`, so the ⏳ flips to ▶ without polling.

## 4. Sizes and limits

Tapes today: 1.7–13.8 MB gz per match (2–3 min ≈ 10–18 MB). Wire is ×1.33 until the upload accepts a raw body with
`Content-Encoding: gzip` (agent-side change ready to ship the day the server accepts it). The tape read must stream
(no in-memory base64), and the request endpoint must not block the single request thread (spawn the R2 pull).

## 5. Not in this hand-off

Asset packs (character/stage art) are ROM-derived and are never stored server-side; the PWA sources them locally (and,
per Tris, host/lobby nodes that own the game will derive/serve them). Replay metadata (names, ranks) is resolved by the
PWA from existing endpoints; cloud skins from `/rr/loadout?steamids=`.

## 6. Two more payload fields the replay UI needs (found while wiring it, 2026-09-03)

- **`side` + `reporter` on the live `match_result` payload and on `/rr/session` games.** The PWA must know which SteamID sat
  in seat P1 to put each player's OWN cloud skin on their side of the picture; `match_key` is a sorted pair + winner + hex,
  so P1/P2 cannot be derived from it. The agent already reports `side` (gs-92) with every result — echo it, plus `reporter`.
  Until then LIVE rows and session games replay with stock palettes (the resolver lights up automatically once present).
- **Bracket matches need a set reference** (`session_id` or `match_key` on `BracketMatch`) before a tournament match row can
  carry a replay affordance.
