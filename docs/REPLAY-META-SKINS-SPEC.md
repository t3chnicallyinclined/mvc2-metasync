# REPLAY METADATA + CLOUD SKINS ON REPLAYS — spec (2026-09-03)

Tris: "inject to the tape some meta data about the match, like the users names, a retroreceipts (nobd.net/ranks) [rank],
time and date of match, and the users skin based on users cloud skin selection — they get to choose how people see
their skins on replays."

## 1. What the tape already carries (agent `reader.rs`, tape v5, verified on `local_1788462750766_stage9`)

| field | value | source |
|---|---|---|
| `ts` | match end, Unix ms | agent |
| `match_key`, `session_id`, `match_index` | server-issued key (online) / `local_<ts>_stage<id>` (offline, 0.3.48) | agent / server |
| `reporter`, `winner`, `loser` | SteamID64 strings | agent (⚠ NAMES ARE NEVER TRANSMITTED — Tris directive 2026-08-25; the server resolves names) |
| `p1_team`, `p2_team` | char ids (0.3.48: from `team_ids` at match start) | agent |
| `costume[6]` | stock colour id per slot (H+0x6C1) | agent |
| `stage_id`, `side`, `local_pn`, `seat_map` | | agent |
| `battle_anchor*` (0.3.47) | receipt anchor | agent |

So the tape needs NO new identity fields: the two SteamIDs + `ts` + teams + costumes are enough to look everything else up.
Names, aliases, ranks and skins are SERVER-SIDE, resolved AT REPLAY TIME — which is also what "they choose how people see
their skins" requires: a skin changed after the match must apply to old replays too, so it cannot be baked into the tape.

## 2. Replay metadata (overlay chrome, not baked into pixels)

The player (dev `player.html` today, the PWA `ReplayEmbed` per `docs/LIVE-TAB-SPEC.md`) fetches, for the tape's two ids:

- names / aliases / rank badge + link `https://nobd.net/ranks` — the same data the SetReceipt / share page already renders for a
  match (PWA `MatchReceipt.svelte`, `PlayerPlate.svelte`; endpoint = whatever they call — UNKNOWN here, lane 1 owns it; do not
  invent a new one).
- date/time = tape `ts` (client local time), stage name from `stage_id` (the arc's stage table), FT/score from the session.

Rule (feedback-render-only-game-assets): the overlay is HTML chrome around/over the 640×480 picture, never drawn into the
scene; during playback it fades out, so the receipt picture stays the game's own pixels.

## 3. Cloud skins on replays (the render-time palette swap)

Contract that already exists (memory `rr-custom-skins-everywhere`, server lane, VERIFIED shape):
- `GET /rr/loadout?steamid=<sid>` → `{ok, steamid, loadout:[{cid, colors:[u32×16 0xRRGGBB]}]}`; absent → `loadout:[]`.
- `GET /rr/loadout?steamids=a,b` (≤25) → `{ok, loadouts:{sid:[…]}}`, players without a loadout omitted (= stock).

How the renderer applies it: sprites are palette-indexed; the tape carries the engine-resolved palette rows per slot
(`palrows`, 0.3.40+: 6×8 rows of 16 colours, `blk+0x13C0`) and `pals`. A cloud skin for character `cid` is 16 colours =
ONE bank row. Apply = replace the STOCK bank-0 row of that character's palette with the loadout colours before the LUT
upload (rr-render `sprites.rs`/`feed.rs` builds the LUT; the browser `resources.mjs` uploads it). Rows the game itself
modifies at runtime (hit flash, glow, super darken = the other 7 rows / palrows variants) stay the game's own, so effects
remain exact; only the base costume colours change — the same rule the PWA's `lib/palette.ts` remap uses for stills.

Which player's choice wins: each player's OWN loadout applies to THEIR side (the viewer does not choose). Stock when absent.

Implementation (mine, d3dcap/replay + rr-render):
1. `WebFeed::new(..., opts_json)` gains `skins: {sid: [{cid, colors}]}` → feed substitutes row 0 of the matching character's
   palette when building the LUT (per slot via `p1_team`/`p2_team` + `reporter`/`winner`/`loser` side mapping).
2. `player.html?skins=1` fetches `/rr/loadout?steamids=<p1>,<p2>` and passes it through; the PWA embed does the same from
   its store (already normalised int→hex there; the feed takes ints).
3. Gate: with an EMPTY loadout the scene sha is unchanged (regression, `gate_l3.mjs`/`gate_seek.mjs`); with a loadout, only
   pixels of that character's base palette indices change (count them: the diff must be ⊆ that sprite's index set).

## 4. Internal resolution (same request, same session)

The captured scene RT is 2048×1024 with the game viewport at (384,32)+1280×960 — i.e. the renderer already draws at 2×;
the blit to the 640×480 canvas samples NEAREST and discards 3 of every 4 samples. Step 1 = box-filter the downscale
(true supersampling at the same cost). Step 2 = `scale=k` option: RT and viewport ×k/2; vertex positions are in NDC on both
the sprite and world paths (`sprite.wgsl` 121–149) so nothing else changes; per-draw viewport/scissor rects scale with it.
Steam's own option mechanism is being read from Ghidra (`docs/STEAM-GRAPHICS-OPTIONS-GHIDRA.md`, in progress) so the filter
and scaling match the Collection's.

## 5. Ownership

- Agent/tape: nothing new (0.3.48 already carries the ids/teams/costumes/ts).
- Renderer + dev player: me (this doc §3–4).
- Server: lane 1 — no new endpoint required for skins; names/rank endpoint = the existing receipt data.
- PWA: `ReplayEmbed` + LIVE tab per `docs/LIVE-TAB-SPEC.md` (design in progress).
