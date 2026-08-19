# 🪙 QUARTER MATCH — the per-match wager surface (Match tab)

Design spec for casual (non-tournament) per-match quarter wagers, per the LOCKED economy design in
`docs/TIGERBEETLE-LEDGER.md` §Flows: both players stake into a per-match escrow; the server settles on
the memory-read result — winner takes pot minus a flat 1-quarter fee **to a neutral host only** (a
playing host earns no fee); no-result within ~30 min TTL auto-refunds both. Closed-loop play money:
**the machine holds the pot** — players trust the referee that read the KO, not each other.

Authorities: `docs/DESIGN-SYSTEM.md` (the bible) · `docs/TIGERBEETLE-LEDGER.md` (economy, LOCKED) ·
`docs/UI-REDESIGN-SPEC.md` (Match "ONE SCOREBOARD" context). Mockup:
`scratchpad/design-mock/quarter-match.html` (offer-placement variants + the decided flow).

⚠ **Line refs verified 2026-08-19 against the gs-215 tree — web/index.html is under active edit and
numbers drift (they moved ~8 lines during this very review). Every ref below carries its anchor
string; re-grep the anchor before editing, trust the anchor over the number.**

---

## 0. Verified code map (what this design builds on)

| Anchor (grep this) | Line @gs-215 | What it is | Guarded? / tick behavior |
|---|---|---|---|
| `<section class="link" id="link">` | 1309 | THE scoreboard (gs-107 Player Plates) | plates re-rendered by setOpp/refreshMe — **no one-shot DOM edits inside** |
| `id="scoreChip"` | 1316 | set-score hero in `.score-center` | **innerHTML rebuilt wholesale every stateTick** (400–600ms) when a score exists |
| `const sc=st.score\|\|{p1:0,p2:0}, scEl=$('#scoreChip')` | 2889 | the scoreChip rebuild block inside `stateTick` (:2788) | pot echo must be a template read here, never a separate write |
| `curSessionId = sid` | 2893 | session id sampled **only inside the score-present gate** | ⚠ fights the design — see §8.1 |
| `id="matchupStrip"` | 1338 | slim matchup row under the scoreboard | the wager rail inserts **between :1309 and :1338** |
| `function setOpp(meta, waitMsg)` | 2530 | opponent identity renderer | called from the 4s syncTick AND pollTick — rebuilds `#p2name/#p2sid/#oppState` |
| `async function syncTick()` | 2515 | 4s network tick (interval set at :2567) | `pollResultChecks()` piggybacks here — `wgrPoll()` does the same |
| `async function stateTick()` | 2788 | 400–600ms game-state tick (via `pollTick` :3396) | source of `st.session_id`, `st.score`, `inMatch` |
| `let sessRecon=null` | 1987 | server-recorded set score, 5s poll | precedent for reconcile-after caching |
| `// /peers, not a non-empty skins list, is the has-app signal` | 2013 | `oppMeta` ⇒ opponent runs the app | the wager eligibility gate reads this |
| `function reportLiveMatch()` | 3451 | client → server live-pair report | the server already knows who is fighting whom |
| `rtSubscribe('matches')` | 5121 | `matches` SSE channel, **subscribed app-wide at boot** | wager deltas ride this channel (additive types) |
| `function rtApplyDelta(p)` | 5344 | bus router (leaderboard/presence/matches) | add nothing here — route stays 3 channels |
| `function rtMatchesApply(d)` | 5426 | matches-channel applier | ⚠ `:5432` early-returns unknown types — wager branch goes ABOVE it (§8.3) |
| `async function coinsRefresh()` / `coinsPaint` | 3529/3533 | MY_COINS cache → `#coinChip` (:1756, Tournament top bar) | ⚠ only refreshed on Tournament entry — see §8.2 |
| `id="tfStake"` | 3672 | 🪙 1/2/4/8 stake denominations (tournament create) | wager stakes reuse the same denominations |
| `'you have 🪙 '+MY_COINS` | 4125 | the gate sub-line balance echo | the ONLY approved balance-echo pattern (§5) |
| `function toast(html)` | 2052 | 2.4s transient toast | attention ping only — never a state home |
| `id="rcBanner"` | 1228 | THE amber row (hard rule 2: amber = rcBanner only) | incoming offers may NOT be a banner |
| `const rcInflight=new Set()` | 5917 | double-submit guard for contest/confirm | `wgrInflight` mirrors it |
| `id="legacySinks"` | 1374 | unguarded-write parking | untouched — this feature is 100% additive, zero existing ids move |
| `function tnyHostState(t, m, me)` | 4033 | tournament in-match state | the client half of the tourney guard (§4, rule 6) |

---

## 1. The one real decision: where the offer lives

Three placements were mocked (see the mockup, Section A). Everything else is one decided direction.

### Variant A — THE MARQUEE RAIL ⭐ recommended
A dedicated slim strip (`#wagerRail`) between the scoreboard (`#link` :1309) and `#matchupStrip`
(:1338) — borrowing the `.matchup.slim` chassis. It is the **single home for all wager states**:
offer affordance → my pending offer → the opponent's accept moment → locked pot → settle flash →
refund note. Collapsed (display:none) whenever there is nothing to say.

- **Pros**: one home for a 6-state flow (one fact, one home); zero coupling to the plates or the
  scoreChip rebuild (its renderer owns it end-to-end); the gold budget stays clean (§4); the metaphor
  is literal — your quarter sits on the marquee, under the scoreboard, exactly where a quarter sits
  on a cab. Fully additive: no existing element moves, no legacy sink needed.
- **Cons**: one more row of vertical real estate while active (~36px); reads slightly less
  "attached" to the score than an in-scoreboard control. Mitigated by the pot echo in the scoreChip
  (§3.4) — the *fact* is scoreboard-integrated even though the *controls* are not.

### Variant B — center-stack cut (rejected)
A `🪙 QUARTER UP` cut inside the scoreboard's `.center`, under the modebar.
- Pros: at the exact point of confrontation; no new row.
- Cons: the center column is the tightest real estate on the page (score hero + VS + modebar); a
  6-state flow crammed into it grows the plates' height and crowds the ONE SCOREBOARD that gs-107
  just cleaned up; pending/locked/settled states still need somewhere bigger to live — the state
  home fragments.

### Variant C — opponent-plate corner chip (rejected)
A small 🪙 tab riding the opponent plate's accent edge ("stake a match vs JFRESH").
- Pros: challenge-at-the-person reads great socially.
- Cons: plates are identity homes (design bible: identity appears once; plates stay tier/skin-
  colored) — a control on a plate breaks plate purity; `setOpp` (:2530) rebuilds that plate's text
  on the 4s tick so the chip needs re-application logic inside setOpp (a new fill-site in the most
  churn-prone renderer in the app); the mirrored RTL plate layout doubles the CSS.

**Decision: Variant A.** The opponent's accept moment is the SAME rail rendering its `incoming`
state (symmetry: both players look at one place), plus a `toast()` ping for attention when the
offer lands (and only a ping — the rail is the home). The amber `#rcBanner` row is constitutionally
reserved (hard rule 2) and is not used.

---

## 2. Consent flow — the state machine

Both players must consent; **no quarters move until both have**. The offer itself is a server
record, not a ledger event. Acceptance executes both stakes as ONE linked TigerBeetle pair (both
land or neither — insufficient funds on either side fails the accept cleanly, zero-sided, never
one-sided).

```
                     tap 🪙 QUARTER UP (pick stake 1/2/4/8)
   idle ──────────────────────────────────────────► offered ──(60s TTL)──► expired ─► idle
    ▲  eligible = syncOn && opp-has-app(oppMeta)       │
    │    && live session && not a tournament match     │ cancel (initiator)
    │    && MY_COINS ≥ stake                           ▼
    │                                                idle
    │
   incoming (opponent offered me) ──── MATCH ────► locked ── match_result ─► settled(win|loss)
    │         │                     (linked stake     │       (bound by        │ shows ≤10s, then
    │         │ DECLINE / 60s TTL    pair executes)   │        match_key)      ▼ idle (+ RUN IT BACK
    │         ▼                                       │ no result ~30min TTL     = one-tap re-offer,
    │       declined ─► idle                          │ (DC / set abandoned)     same stake)
    │                                                 ▼
    └─────────────────────────────────────────── refunded ─► idle
```

Rules:
1. **One open wager per pair per session** (server-enforced; the client hides the affordance while
   any wager for this session is non-idle).
2. **The wager covers exactly ONE game**: the first `match_result` recorded for this pair after
   `locked_ts` settles it (that result's `match_key` is stamped into the wager — this is the
   `mescrow:<match_key>` binding from the ledger doc; the escrow account is minted at accept, keyed
   by the server-minted `wager_id`, and aliased to the match_key at settle).
3. **Offer TTL 60s** (arcade pacing — an unanswered quarter comes off the marquee). Expiry and
   decline move zero quarters. **Locked TTL ~30 min** → auto-refund both (per the ledger doc).
4. **Neutral-host fee**: `fee = 1` iff a neutral (non-playing) host exists for this session, else 0.
   Server-determined (it knows the lobby host + the fighting pair); delivered in `wager_locked` /
   `wager_settled` payloads. The UI states net math explicitly *before* accept ("winner takes 🪙 3 ·
   house 🪙 1 → DVDKAZ").
5. **Cancel** is initiator-only and only in `offered`. After `locked`, nobody can back out — the
   machine holds the pot (that is the product).
6. **Tournament guard**: wagers are casual-set only. Server refuses `wager/offer` when the pair
   matches a live tournament match (authoritative); the client also hides the affordance when
   `tnyHostState` (:4033) reports the user seated/in-match in a running event (cosmetic fast-path).

---

## 3. UI spec per state (Variant A rail)

New element, inserted between `#link` (:1309) and `#matchupStrip` (:1338):

```html
<div id="wagerRail" class="wgr" style="display:none">
  <span class="rail-lbl">🪙 quarter match</span>
  <span class="wgr-line" id="wgrLine"></span>
  <span class="wgr-acts" id="wgrActs"></span>
</div>
```

Chassis: `.matchup.slim` recipe (flex · panel bg · 1px `--line` · radius `--r` · padding 8px 14px ·
min-height 36px). All inner content is written by ONE renderer, `wgrRender()`, from the cached
`WGR` object — never one-shot (§7). Rail label per the bible: 10px/700/caps/.16em `--faint`.

| State | `#wgrLine` copy | `#wgrActs` | Accent |
|---|---|---|---|
| `idle` (eligible) | `Put quarters on this set — winner takes the pot.` (dim) | ghost cut `🪙 QUARTER UP ▸` → expands inline stake cuts `1 · 2 · 4 · 8` (denominations mirror `#tfStake` :3672; default 2) + sub-echo `you have 🪙 12` (:4125 pattern) | none |
| `offered` (mine) | `🪙 2 on the marquee — waiting for JFRESH to match… 0:47` | ghost `CANCEL` | none; countdown is `--dim` tabular |
| `incoming` | `JFRESH puts up 🪙 2 — match it and the machine holds 🪙 4.` (+ ` · winner takes 🪙 3, house 🪙 1 → DVDKAZ` when fee applies) | **gold cut `MATCH 🪙 2`** + ghost `DECLINE` + sub-echo `you have 🪙 12` | gold cut = the page's one primary action in this moment |
| `locked` | `🪙 4 in the machine — next game decides it.` (+ fee line when applicable) | none | 3px gold left edge (≤20px sliver rule) |
| `settled — win` | `🪙 +4 — purse claimed` 15px/900 italic (podium language) + sub `balance 🪙 16` | ghost `🪙 RUN IT BACK` (one-tap re-offer, same stake) | ≤900ms gold flash on entry, then static gold text; wrapped in `prefers-reduced-motion: no-preference` |
| `settled — loss` | `purse lost — 🪙 2 to JFRESH` (dim, quiet — no red theatrics) | ghost `🪙 RUN IT BACK` | none |
| `refunded` | `🪙 2 returned — no result recorded.` | none (auto-clears ~10s) | none |
| `declined` / `expired` | `offer declined — no quarters moved.` / `offer expired — no quarters moved.` (dim, ~6s then idle) | none | none |

Toast pings (attention only, 2.4s, `toast()` :2052 — the rail is always the state home):
- offer lands while user may be on another tab: `🪙 JFRESH wants to run it for quarters — Match tab`
- refund: `🪙 2 returned — no result recorded for the wagered game`
- settle (win): `🪙 +4 — purse claimed`

### 3.4 The pot on the scoreboard (tick-rebuild-safe by construction)
While `locked`/`settled`, the scoreChip template (:2889 block) appends one segment, read from the
`WGR` cache **inside the same template string** it already rebuilds every tick:

```
set 2 – 1 · game 4/10 · #d4f2 · 🪙 4
```

i.e. in the `sess` composition: `` + (WGR.state==='locked' ? ` · <span title="the machine holds the
pot">🪙 ${WGR.pot}</span>` : '') ``. Because the chip is rebuilt wholesale on every stateTick, a
separate DOM write would die within 600ms — the template read is the only correct integration. The
pot glyph inherits the chip's dim styling (the gold numerals stay the score's — gold budget intact).

---

## 4. Gold budget & vocabulary audit (Match page)

- Gold already spent on: score numerals (`#scoreChip.score-big b` CSS :129), `#oppRecord` scoreline,
  `#sessLink`. Therefore: the `QUARTER UP` affordance is **ghost, never gold** (it is an invitation,
  not the page's primary action). Gold appears in the rail only (a) on the `MATCH 🪙 N` cut while an
  incoming offer is live — at that moment it IS the page's one primary action — and (b) the ≤900ms
  settle flash + settled-win line.
- Cuts use the SF6 parallelogram recipe (skewX(-12deg), children counter-skewed; active = molten
  `linear-gradient(180deg,#ffe084,#c98f0e)` + `--gold-ink` + italic).
- No new pills, no new banner, no watermark. Icons: the 🪙 emoji is approved brand-emoji copy
  (matches gs-214's shipped usage across tournament surfaces); no new stroke icon needed.
- `prefers-reduced-motion`: flash falls back to a static gold line; the offered-state countdown
  never pulses.

---

## 5. Balance awareness — one home per fact

`#coinChip` (:1756, Tournament top bar) remains THE home of the balance. The Match tab **never**
grows a second chip. At decision moments the rail echoes the balance as contextual sub-copy — the
exact shipped pattern of the gate sub-line (`'you have 🪙 '+MY_COINS`, :4125) — in `idle`-expanded
and `incoming` states only. `coinsRefresh()` (:3529) is invoked on: affordance becoming eligible,
`wager_locked`, `wager_settled`, `wager_refunded` (see §8.2). Future (owner decision, NOT this
build): if quarters end up load-bearing on 2+ tabs, promote `#coinChip` into the arena bar's utility
cluster — one home, globally visible.

---

## 6. API delta (spec only — no server code; skinsync is owned elsewhere right now)

All endpoints authed exactly like `contest_match`/`confirm_match` (steamid + the existing auth rule);
Tauri proxy commands mirror the `coins`/`contest_match` pattern: `wager_offer`, `wager_respond`,
`wager_cancel`, `wager_state`.

### Endpoints
```
POST /skinsync/wager/offer
  { steamid, opp, session_id, stake }            stake ∈ {1,2,4,8}
  → { ok, wager_id, expires_ms }
  409 open wager already exists for this pair/session · 402 balance < stake (soft check)
  · 403 not a live pair (server cross-checks its live-match report, :3451 feed)
  · 409 tournament match live for this pair (rule 6)

POST /skinsync/wager/respond
  { steamid, wager_id, accept: true|false }
  accept → executes the LINKED stake pair (player→escrow ×2, TIGERBEETLE-LEDGER §Flows;
           transfer ids sha256("stake:<wager_id>:<steamid>")[..16] — idempotent, retry-safe)
  → { ok, state: "locked"|"declined", pot?, stake?, fee?, host? }
  402 either balance short at accept time (offer expires, zero moved) · 410 offer expired

POST /skinsync/wager/cancel
  { steamid, wager_id }                          initiator-only, offered-state only
  → { ok }

GET /skinsync/wager/state?steamid=&session_id=
  → { ok, wager: null | { wager_id, state, stake, pot, fee, host?, offered_by,
        players:[a,b], expires_ms?, settled?: { match_key, winner, payout } } }
  The poll fallback + reconnect seed — rides the 4s syncTick like pollResultChecks (:2515).
```

Settlement and refund are **server-internal** (no client endpoint): the result recorder settles the
first `match_key` recorded for the locked pair after `locked_ts` via the linked payout pair
(escrow→winner `pot−fee` + escrow→host `fee` when a neutral host exists — both land or neither);
the TTL sweeper (~30 min) voids and refunds both stakes. Exactly the LOCKED §Flows design.

### SSE deltas — ride the existing app-wide `matches` channel (:5121), additive `type`s
Old clients ignore unknown types (see §8.3 for where the new branch must go).

```
{ type:"wager_offer",    wager_id, session_id, players:[a,b], offered_by, stake,
  names:{sid:name}, fee_preview, host?, expires_ms, ts }
{ type:"wager_locked",   wager_id, session_id, players, stake, pot, fee, host?, ts }
{ type:"wager_settled",  wager_id, session_id, match_key, winner, payout, fee, host?, ts }
{ type:"wager_refunded", wager_id, session_id, players, stake,
  reason:"expired"|"declined"|"cancelled"|"no_result", ts }
```

Clients filter by `players` containing me → drive `WGR`. Spectator garnish (optional, gs-219):
`wager_locked` lets Now-Playing rows (:5499) wear a `🪙 4` pot chip; `wager_settled` lets the Live
Results row carry it. Note: the channel is network-public — so is the quarter on a real cab's
marquee, and it is closed-loop play money; if the owner ever wants private offers, the push-gateway's
generic `/stream/{channel}` supports a per-session channel — flagged, not built.

---

## 7. Tick-safety contract (how the client state works)

One cached object, one renderer — the sessRecon/`_oppRep` doctrine:

```js
// gs-216 — the ONLY wager state in the app. Every surface reads this; nothing writes DOM ad hoc.
let WGR = { state:'idle', wagerId:null, sessionId:'', opp:'', stake:0, pot:0, fee:0, host:null,
            offeredBy:'', expiresMs:0, settled:null, _seenOffer:'' };
const wgrInflight = new Set();   // mirrors rcInflight (:5917) — blocks double offer/respond/cancel
```

- `wgrRender()` repaints `#wagerRail` wholly from `WGR`. Callers: SSE deltas, `wgrPoll()` (4s,
  piggybacked in `syncTick` :2515 beside `pollResultChecks`), eligibility changes (end of
  `setOpp` :2530 — the rail is OUTSIDE the plates, so setOpp's rebuilds never touch it), and the
  countdown (a cheap 1s interval alive only in `offered`/`incoming`).
- The scoreChip pot echo is a **template read of `WGR`** inside the :2889 rebuild — never a write
  from wager code into the chip (§3.4).
- Session change detection: `WGR.sessionId` re-captured every `stateTick` from `st.session_id`
  (hoisted — see §8.1); a change while not `locked` resets `WGR` to idle. A change while `locked`
  does NOT clear it — the server TTL owns locked outcomes (the set ending early = refund path).
- SSE dedupe: offers keyed by `wager_id` (`_seenOffer` guards re-toasting on reconnect replays);
  all transitions are idempotent state assignments, safe under XRANGE gap-fill replay.

---

## 8. Current code that fights the design (fix list, all in gs-216)

1. **`curSessionId` is sampled only inside the score-present gate** (`curSessionId = sid` :2893,
   inside `if(sc.p1||sc.p2||(sessRecon&&sessRecon.count))`). Before the first KO there is NO session
   id in any JS global — and pre-game is exactly the offer moment. Fix: hoist a per-tick capture in
   `stateTick` (`WGR.sessionId = st.session_id||''`). Verify the backend fills `st.session_id`
   pre-first-game (the netplay pairing exists at loading/select — `st.in_session` :2800); if it
   lands later, key the offer by the opponent pair (`oppIdentity.steamid`) and let the server bind
   by pair — the API already supports it (it validates the live pair server-side anyway).
2. **`coinsRefresh()` only rides Tournament-tab entry** (:3506) and tourney actions (:4666) —
   `MY_COINS` is null/stale on Match, so the balance echo and the `MY_COINS ≥ stake` eligibility
   check would lie. Fix: call `coinsRefresh()` when the affordance becomes eligible + on every
   wager transition (offer/lock/settle/refund).
3. **`rtMatchesApply` early-returns unknown types** (:5432
   `if(d.type!=='match_result'||…) return;`) — safe for shipped clients (wager deltas are silently
   ignored = graceful degrade), but the new `wager_*` branch must be inserted ABOVE that line (after
   the `match_start`/`match_end` branches), not after it.
4. **The amber row is constitutionally reserved** (`#rcBanner` :1228; DESIGN-SYSTEM hard rule 2) —
   the incoming offer must not be a banner. This design keeps it in the rail + a toast ping.
5. **Gold is already spent on the score numerals** (CSS :129) — the offer affordance must stay
   ghost; only the `incoming` MATCH cut and the settle flash may be gold (§4).
6. **No global "this is a tournament match" signal on the Match tab** — `tnyHostState` (:4033)
   knows, but only inside Tournament state. The server guard is authoritative (§6 409); the client
   check is a fast-path cosmetic.
7. **`setOpp` churns the opponent plate on the 4s tick** (:2530) — any wager UI inside a plate would
   need a new fill-site in the app's most churn-prone renderer. Variant A avoids plates entirely;
   do not relocate the rail into a plate later without re-reading this section.

---

## 9. Build steps (priority order; bump one gs-N per shipped step)

| Step | Tag | Scope |
|---|---|---|
| 1 | **gs-216** | `WGR` cache + `wgrInflight` + `#wagerRail` element (between :1309 and :1338) + `wgrRender()` all-states + eligibility (syncOn ∧ oppMeta ∧ session ∧ ¬tourney ∧ MY_COINS≥stake) + `wgrPoll()` on the 4s syncTick + `wager_offer/respond/cancel/state` invokes + SSE branch in `rtMatchesApply` (above :5432) + toast pings + §8.1 session-id hoist + §8.2 coinsRefresh calls. Ship gate: `node src-tauri/stage-frontend.mjs` prints "parse cleanly". |
| 2 | **gs-217** | Pot echo in the scoreChip template (:2889 block) — one template-string addition reading `WGR` (§3.4). |
| 3 | **gs-218** | Settle/refund moments: ≤900ms gold flash (reduced-motion guarded), podium-language settle lines, refund note + toast, `RUN IT BACK` re-offer cut, 10s auto-clear to idle. |
| 4 | **gs-219** (polish) | Spectator garnish: `🪙 pot` chip on Now-Playing rows (:5499) + Live Results rows from `wager_locked`/`wager_settled` payloads. Skippable without harm. |

Server work (not this repo's designer, spec §6): the four endpoints, the settle binding in the
result recorder, the TTL sweeper, the four `matches`-channel delta types — all on the LOCKED
TigerBeetle flows (linked pairs, sha256 idempotent transfer ids, `tigerbeetle-expert` owns review).
