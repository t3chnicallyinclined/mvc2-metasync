# THE STAGE part 2 — EVO TIER (verified spec)

**Status:** design-lead spec, verified line-by-line against `web/index.html` at the **gs-206 snapshot**
(entrant typeahead landed; ~5,888 lines). ⚠ The main session is actively writing this file — **every line
ref below is paired with a grep-able symbol; re-grep the symbol before editing, never trust the number.**
Mockup: `scratchpad/design-mock/stage-evo.html` (session scratchpad). Companion docs:
`DESIGN-SYSTEM.md` (authority), `UI-REDESIGN-SPEC.md` §The Stage + §Seasons, `TOURNAMENT-PLATFORM.md`.

**Owner brief honored:** typeahead base is gs-206 (shipped — this spec only polishes it); gs-203 hero
(lifecycle rail, story line, arena-corner bracket, score cells) and gs-204 tab merge are BUILT ON, not
redone; economy framing is LOCKED — free now, PayPal-only when paid, permanence = "carved in stone"
archival proof, **never** NFT/crypto-speculation language; entry stake is a coming-soon surface, not a flow.

---

## 0. Adjudications (the decisions, one line each)

| Decision | Call | Why |
|---|---|---|
| Where the perks surface lives | **Repurpose the no-op `#tnyTeamBar`** (skeleton :1676, no-op renderer `tnyRenderTeamBar` :3898) as THE GATE — a slim arena band under the hero, rendered only when `pre && !myReg` | Zero new skeleton ids; the renderer already receives `(t, me, myReg)` — exactly the state the gate needs; it re-renders on every SSE repaint so it is tick-safe by construction; it vanishes forever once you register (no residue, no crowding) |
| Who owns the register action | **The gate owns it; the hero register half-line dies in the same edit** (:3636) | The hero currently shows TWO gold CTAs for a TO pre-bracket (`Register (play too)` + `Start bracket ▶` :3636–:3639) — already over gold budget. After this: Register = gate, Check-in/Drop/Start = hero, You're-up = ticker, Result = podium. One moment, one home. |
| Pot surface | **Variant B — Champion's Purse** (see §2) with the browse-card chip as its compact echo | Meaningful at $0, EVO-native register, upgrades in place when stakes land |
| Create form | **Sectioned, preset-driven rebuild of `renderCreate`** (:3526) | It is a one-shot render (not tick-rebuilt) — the lowest-risk surface in the tab; forms don't need theatre, they need grouping |
| Seeding controls | **Move Admin's seeding row into the Players view** (TO, pre-bracket) | The seed inputs are already there (`.tny-seedin` per-row); the seed-all actions being one tab away is a two-home split of one job |
| Champion moment | **Podium stage renders into the existing `#tnyChamp` container** (fill :3690) | The container is cleared in renderDetail's UNGUARDED reset block (:3608–:3609) — same id in, same id out, nothing to unhook |
| On-chain language | "Carved in stone" / "etched into the season archive" / "archival proof" — a reserved ⛓ slot on the podium for when the seasons anchor ships | FGC is NFT-hostile; the UI-REDESIGN-SPEC §Seasons attestation design already locks this framing |

---

## 1. REGISTRATION EXPERIENCE — "THE GATE"

### What entering unlocks (the six perks — every one maps to a shipped system, so the sell is honest)

| Perk chip (10px rail-caps + icon) | Backed by (verified) |
|---|---|
| `SEEDED BY YOUR ELO` | `tourney_seed {method:'elo'}` — tnyAction :4363+ |
| `YOUR RANK ON THE BRACKET` | gs-109 mini-plates: `rankOf`/`RK_PLATE` accents in `tnyMatchEl` :4213 |
| `SETS REPORT THEMSELVES` | auto-report daemon `tnyAutoReport` (fail-safe, exactly-once) |
| `CARVED INTO THE RECORD` | shared `/result` pipeline → global ELO + season archive (Beta Season ends 2026-09-06) |
| `HEAD-TO-HEAD INTEL` | tale of the tape in `tnyOpenMatch` :4261 (profiles + matchup, cached) |
| `"YOU'RE UP" CALLOUTS` | `tnyRenderAlert` :3874 — beep + join link the moment your lobby is live |

### Structure (annotated, real ids)

```html
<!-- emitted by the REPURPOSED tnyRenderTeamBar(t, me, myReg) into #tnyTeamBar (:1676).
     Renders ONLY when (t.status==='open'||'checkin') && !myReg && me. Else innerHTML=''. -->
<div class="tny-entergate">                      <!-- NEW class — ⚠ .tny-gate (:908) is TAKEN (stationed-host gate) -->
  <div class="teg-rail">ENTERING UNLOCKS</div>   <!-- rail label: 10px/700/caps/.16em faint -->
  <div class="teg-chips">                        <!-- 6 chips, one line, wrap at <900px -->
    <span class="teg-chip">⚡ SEEDED BY YOUR ELO</span> … ×6
  </div>
  <div class="teg-cta">
    <button class="tny-btn gold teg-go" data-act="register">REGISTER — FREE ENTRY ▸</button>
    <span class="teg-sub">champion takes the purse</span>   <!-- ties to §2B; 10.5px faint -->
  </div>
</div>
```

- **Surface**: arena band ~68px — red wash from the left corner, blue from the right (≈6% alpha),
  2px skewed gold seam on the bottom edge. **No ghost watermark** (too short to carry one legibly;
  the hero banner above already owns the page's ghost).
- The gold cut is the page's ONE primary action in the pre-registration state (D1 makes this true).
- `data-act="register"` — the existing dispatcher (`tnyAction` :4363) handles it unchanged.
- TO variant: same gate with the button label `REGISTER — PLAY TOO ▸` (replaces the :3636 special-case).
- Checked-in / registered: gate renders nothing — the hero CTA machine (:3637) owns the next moment.
- Reduced motion: the gate is static (no pulse, no sweep).

---

## 2. PRIZE / POT SURFACE — three framings, one recommendation

Data reality (verified): `entry_fee_cents` already flows through the list payload — `tnyCard` reads it
(`t.entry_fee_cents ? '' : '<span class="tny-free">FREE</span>'`). Pot math = `fee × active entrants`,
both client-side. **Zero new server fields for v1.**

### Variant A — POT PLATE (pot-forward)
A skewed plate in the hero right column: 26px tabular numeral (`$120`), rail label `THE POT`, sub-line
`$10 × 12 · WINNER TAKES ALL`. Free state: `$0 — FREE ENTRY`.
**Tradeoffs:** maximum stakes-hype and instant read for money-motivated entrants; but at $0 (today,
every event) it is a dead numeral — an empty flex that makes free events look like failed monetization;
it adds a second numeric hero to a page whose story line already carries the live numbers (violates the
one-numeric-hero rule); and money-first framing sitting next to a permanence/on-chain line is exactly
the gambling-adjacent read the FGC punishes.

### Variant B — CHAMPION'S PURSE (prestige-forward) ⭐ RECOMMENDED
One slim line fused to the hero's bottom edge, directly above the story line: rail label
`CHAMPION'S PURSE` + contents.
- **Today (free):** `Permanent record · Season etching · The #1 seed next time — FREE ENTRY`
- **Staked (later):** `$120 — $10 entry × 12 · winner takes the pot` (the math IS shown, as the sub-clause)
**Tradeoffs:** softer conversion trigger for grinders who only chase money (the numeral is not 26px);
costs one ~26px hero row.
**Why it wins:** (1) it is meaningful at $0 — the purse today is *real* (permanence + season etch), so the
surface ships honest instead of placeholder; (2) EVO-native register — the champion *lifts a purse*, the
event is not a slot machine; (3) it upgrades in place when PayPal stakes land — same line, richer contents,
no relayout and no reframing moment; (4) it composes with §5 — the podium repeats the line as
`PURSE CLAIMED`, closing the narrative loop. A only beats B when the pot is huge — which is exactly when
B's line also leads with the number.

### Variant C — MINIMAL CHIP
Upgrade the existing `.tny-free` browse-card pill: `FREE` (green, today) → `◈ $10 · POT $120` (gold-edged).
**Tradeoffs:** zero layout cost, quiet, honest; but no narrative surface — "coin up, winner takes it" has
nowhere to live, and at stake-time a 10px pill cannot carry the pot math buyers need.

### Ruling
**B on the event page + C as its echo on browse cards** (mirrors the masthead-plate/meCard hero-and-whisper
precedent — one full surface, one compact echo, zero other duplicates). A is rejected. The staked states
ship dark behind a `POT_ENABLED=false` const until PayPal lands — the create form's locked field (§3) is
the only place "coming soon" is ever said; the event page states only what IS.

---

## 3. EVENT CREATION FORM — start.gg grade

Audit of `renderCreate` (:3526, verified): one flat column; ids `tfName tfFormat tfOnline tfCc tfCity
tfStarts tfFtW tfFtL tfFtG tfCap tfBannerPrev tfBannerLbl tfBannerFile tfHostMode tfStream tfRules tfErr`;
submit path `tnyCreateSubmit` builds `{name, format, online, cc, city, starts_ms, ft_winners, ft_losers,
ft_grands, cap, banner_url, stream_url, rules_md, host_mode}`. Missing vs start.gg: grouping, ruleset
presets, check-in window, entry fee surface, discord, event identity (accent).

### New structure (keep EVERY existing tf- id — the submit reader keys on them)

```
RAIL: THE BASICS
  tfName (full width) · tfFormat · tfOnline · tfCc+tfCity · tfStarts
RAIL: FORMAT & RULES
  NEW preset cuts row (SF6 cuts, one active):
    [MVC2 STANDARD ⭐]  FT2/FT2/FT3 + MVC2_RULES     (default — current behavior)
    [QUICK WEEKLY]      FT1/FT1/FT2 + MVC2_RULES
    [MARATHON]          FT3/FT3/FT5 + MVC2_RULES
    [CUSTOM]            unlock manual editing (any manual edit of tfFtW/L/G or tfRules flips to CUSTOM)
  tfFtW · tfFtL · tfFtG (kept, filled by presets) · tfRules (kept, incl. the reset-template button)
RAIL: ENTRY
  tfCap (kept; cap>0 shows "beyond cap = automatic waitlist" microcopy)
  NEW tfStake — DISABLED input: "◈ Entry stake — FREE ($0)" + lock glyph + microcopy:
    "Staked entry is coming: PayPal entry, pot = stake × entrants, the champion takes it.
     Events are free until then."           ← the ONLY coming-soon copy in the tab
RAIL: PRESENTATION
  banner picker (kept: tfBannerPrev/tfBannerLbl/tfBannerFile, tnyBannerChosen pipeline untouched)
  NEW tfAccent — 6 swatches: Gold (default) · Crimson --p1 · Cobalt --p2 · Vibranium #b98cff ·
    Adamantium #9fd4ef · Emerald --good. Stored as `accent` on the create body (additive server field;
    client defaults gold when absent — degrades gracefully against an older server).
  NEW tfDiscord (discord_url — the model + admin-links handler :3801 already support it; create just
    never asked)
  tfStream · tfHostMode (kept)
SUBMIT ROW (kept: back / create-submit / tfErr)
```

- Two-column `frow` grouping at ≥900px; section rails use the 10px/700/caps/.16em recipe (the current
  `.tny-form label` is 11px/.05em — retune to match the app's rail recipe, one CSS edit).
- **Accent discipline:** the accent appears ONLY in ≤20px slivers — browse-card 3px edge, hero seam tint,
  hero title underline. Player plates stay tier/skin-colored, always.
- Check-in window automation (auto-open N min before start) needs server support — **deferred**, manual
  open/close (:3799) remains the mechanism; do not fake it in the form.

---

## 4. ORGANIZER ADD-PLAYER + SEEDING (polish on gs-206 — the base is SHIPPED, don't re-spec it)

Verified base: `#tnyAddQ` emit :3714 (state on `TNY._addq`/`TNY._addFocus` — SSE-rebuild-safe),
pool `tnyPoolFetch` :3730 (wins+rating top-50 union, 60s cache), dropdown `tnyAddDrop` :3743
(avatar/flag/name/badge/W–L rows, prefix-first sort, SteamID64 fallback row), keyboard nav :3761–:3767,
dispatcher `add-entrant` accepts `data-sid` (:4393 region).

Polish only (all inside the existing renderers — this section is SSE/tick-rebuilt):
1. **Rating cell** in dropdown rows: dim tabular ELO between badge and W–L (seeding context is the whole
   point of the TO search). One token in the :3754 row template.
2. **Hint footer** as the dropdown's last row, 10px faint: `↵ add · ↑↓ move · esc close · paste a
   SteamID64 for someone new` (replaces nothing; the no-match copy :3756 stays).
3. **Added-row flash**: stamp `TNY._flashSid` in the add-entrant handler; `tnyEntrantsHtml` (:3811) adds
   `.added` (900ms gold inset, the `.scored` pattern :715) to that row, then clears the stamp. Reduced
   motion: none.
4. **Pool-warming row**: while `tnyPoolFetch` is in flight on first open, show one faint row
   `searching the network…` (prevents the "typed 2 chars, nothing happened" dead beat).
5. **SEEDING TOOLBAR** (the M2 move): TO + pre-bracket, emitted at the top of the entrants section
   (inside the same tnyTry :3713 — never a one-shot DOM edit):
   `rail "SEEDING" · [⚡ SEED BY ELO] [🎲 SHUFFLE] · note "edit numbers inline — seeds lock at Start"`.
   Same `data-act="seed"` / `"seed-random"` — dispatcher untouched. Admin's seeding row (:3798) DIES in
   the same edit (one home). Admin keeps check-in / links / danger zone.

---

## 5. CHAMPION MOMENT — the podium stage + permanence

Renders into **`#tnyChamp`** (same condition as today's one-liner: `t.bracket && t.bracket.champion`,
fill :3690). The one-line `.tny-champ-banner` emit + its CSS (:1044) die.

```
┌─ .tny-podium — arena surface ~200px ────────────────────────────────────────┐
│  gold corner washes both sides · ghost italic CHAMPION ≤5% · skewed gold    │
│  seams top + bottom                                                          │
│   ┌ 2nd plate 82% ┐   ┌═ CHAMPION MEGA-PLATE ═┐   ┌ 3rd plate 82% ┐          │
│   │ silver 3px edge│  │ avatar 72 · name 24/900│  │ bronze 3px edge│         │
│   │ ghost "2"      │  │ italic · badge + flag  │  │ ghost "3"      │         │
│   │ GF loser       │  │ 5–1 · Seed 3 · def.    │  │ losers-final   │         │
│   └────────────────┘  │ Duc in Grand Finals    │  │ loser          │         │
│                        └───────────────────────┘  └────────────────┘         │
│  PURSE CLAIMED · Permanent record · Season etching            [⧉ COPY RESULT]│
│  🪨 CARVED IN STONE — this result is part of the permanent record ·          │
│     Beta Season · archived at season's end   [reserved ⛓ slot — see below]  │
└──────────────────────────────────────────────────────────────────────────────┘
```

- **Placement derivation** (all client-side from `t.bracket.matches`): 2nd = GF loser; 3rd = loser of the
  losers final; champion record from the standings reducer (:3785 pattern). No new data.
- **The permanence line** ties to UI-REDESIGN-SPEC §Seasons: when the season-end on-chain attestation
  ships, the reserved slot renders `⛓ etched — verify` linking tx + season file. Language is LOCKED:
  "carved in stone / etched / archival proof" — **never** NFT / crypto / mint in any user-facing string.
- **⧉ COPY RESULT** ghost cut → clipboard text block (event · top 3 · W–L · date) — reuse the tnyJoin
  clipboard fallback pattern (:4045 region). The shareable seed for future card pages.
- The lifecycle rail's CHAMPION stop (:3650 region) already carries the name — it stays (the whisper);
  the podium is the hero. Standings `.champ` row (:3789) stays.
- Reduced motion: no confetti anywhere, ever — the gold IS the celebration (per Stage v1 spec).

---

## 6. DELETE / MERGE (explicit)

| # | Action | Target (symbol :line @ gs-206 snapshot) |
|---|---|---|
| D1 | **DELETE** the hero register half-line | renderDetail :3636 `if(pre && !myReg) cta+=…register…` — the gate (M1) takes the action, SAME increment |
| D2 | **DELETE** the champion one-liner emit | :3690 — replace the `.tny-champ-banner` innerHTML with the podium emit; keep the else-branch clear |
| D3 | **DELETE** `.tny-champ-banner` CSS | :1044 (dies with D2) |
| M1 | **REPURPOSE** `#tnyTeamBar` | skeleton :1676 + no-op renderer :3898 → THE GATE (§1). The renderer's comment block (:3895) is rewritten, not the call site (:3693 `tnyTry('teambar',…)` untouched) |
| M2 | **MOVE** Admin seeding row → Players entrants header | source :3798 (`tny-admsec` Seeding), destination inside the entrants tnyTry :3713; `data-act` names unchanged |
| M3 | **MERGE** browse `FREE` pill → purse-aware chip | `tnyCard` :3516 emit + `.tny-free` CSS (:678 region) |
| K1 | **KEEP — DO NOT DELETE** `#tnyEntrantsLab` / `#tnyBracketLab` | hidden, but renderDetail's reset block writes them **UNGUARDED** (:3608 `tId('tnyEntrantsLab').style.display='none'` — outside any tnyTry). Deleting the elements throws before any section renders. Remove only in a cleanup that edits :3608 in the same change |
| K2 | **KEEP** the hero rules `<details>` (:3685) | Stage v1 wants it in a modal — that belongs to the Stage v1 build, not this pass; don't double-touch |
| K3 | **KEEP** `.tny-gate` (:908) + `tnyRenderGate` (:3903) untouched | stationed-host gate; the new class is `.tny-entergate` to avoid the collision |

---

## 7. JS FILL-SITE MAP (guarded vs unguarded — verified)

| Id / surface | Fill site (symbol :line) | Guarded? | Disposition |
|---|---|---|---|
| `#tnyTeamBar` | `tnyRenderTeamBar` :3898 | ✅ `if(el)` | Repurposed → gate emit; called via `tnyTry('teambar',…)` :3693, isolated |
| hero CTA string | renderDetail :3636–:3639 | n/a (string build) | :3636 half-line deleted (D1); :3637 checkin/drop, :3638 watch, :3639 start untouched |
| `#tnyChamp` | :3690 `tId('tnyChamp').innerHTML=` | ⚠ UNGUARDED (both branches) + cleared in reset :3609 | Keep the id; swap the emitted markup only (§5) |
| reset block | renderDetail :3606–:3609 | ⚠ UNGUARDED chain (`tnyEntrantsLab`,`tnyEntrants`,`tnyBracketLab`,`tnyBracket`,`tnyChamp`,`tnyEmpty`) | The reason for K1 — any skeleton deletion must edit this line in the same change |
| `#tnyEntrants` | entrants tnyTry :3713–:3718 | tnyTry-isolated | Gate for M2 toolbar + typeahead polish — ALL markup emitted here (SSE-rebuilt; gs-206's `TNY._addq`/`_addFocus` restore pattern :3717–:3718 is the template) |
| `#tnyAddQ`/`#tnyAddD` | :3714 emit, `tnyAddDrop` :3743, listeners :3759–:3768 | state on `TNY` | Polish only (§4 items 1–4) |
| `#tnyCreate` | `renderCreate` :3526 | one-shot (NOT tick-rebuilt) | Safe to fully restructure (§3) |
| `#tnyAlert` | `tnyRenderAlert` :3874 | ✅ `if(!el) return` | Untouched — the you're-up machine (six states + beep stamp) is port-proven code |
| `#tnySub` | renderDetail :3710 tabs array | n/a | Untouched |
| browse cards | `tnyCard` :3516 via `tnyRenderList` :3503 | n/a | M3 chip only |
| dispatcher | `tnyAction` :4363 (`register` :4375 region, `seed`/`seed-random`, `add-entrant` :4393) | try/catch + busy flag | New surfaces reuse existing `data-act`s; only `tfStake`(disabled) and `tfAccent`/`tfDiscord` (submit body keys) are new |
| `tnyCreateSubmit` | :3562 region | n/a | Adds `accent`, `discord_url` keys to body (server additive) |

Tick/SSE discipline (inherited, non-negotiable): every new surface here is emitted inside renderDetail's
tnyTry sections or renderCreate — **no one-shot DOM edits**; transient UI state (preset selection, accent
pick, flash stamps) lives on `TNY.*`, the gs-206 pattern.

---

## 8. BUILD PLAN — priority-ordered gs-N increments (each ships alone, ship gate after every one)

Ship gate per CLAUDE.md: Edit tool only → bump gs-N → `node src-tauri/stage-frontend.mjs` ("parse
cleanly") → extract scripts + `node --check` → live-verify on a real event.

| # | Increment | Size | Contents |
|---|---|---|---|
| gs-207 | **THE GATE** | ~1.5h | M1 + D1: repurpose tnyRenderTeamBar → `.tny-entergate` emit (6 perk chips, gold REGISTER cut, TO "play too" variant); delete the :3636 register half-line; scoped CSS. Verify: register from the gate on a test event, gate disappears after, hero CTA machine unaffected, SSE repaint keeps the gate. |
| gs-208 | **CHAMPION'S PURSE (B) + browse chip (M3)** | ~1h | Hero purse line above the story line (free state only; staked state behind `POT_ENABLED=false`); `.tny-free` → purse-aware chip. |
| gs-209 | **CREATE FORM** | ~2.5h | §3: section rails, preset cuts (TNY._preset state), tfStake locked field, tfAccent swatches, tfDiscord; submit body + server accepts `accent`/`discord_url` on create (additive, ~15-line server change; client degrades to gold if absent). |
| gs-210 | **TO POLISH** | ~1.5h | §4 items 1–5 incl. M2 (seeding toolbar into Players; Admin seeding row dies). Verify with a live add + seed + SSE repaint mid-typing (the _addq restore). |
| gs-211 | **PODIUM STAGE** | ~2h | §5 + D2/D3: podium plates, placement derivation, permanence line (reserved ⛓ slot), ⧉ copy result. Verify on a completed test event + an event with no losers final (3-man bracket → 3rd plate omitted). |
| gs-212 | **ACCENT SLIVERS + AUDIT** | ~1h | Accent tint on browse-card edge / hero seam / title underline (≤20px slivers only); reduced-motion pass over gate/podium; gold-budget audit of the event page end state. |

Total ~9.5h across 6 independently shippable releases. **Deliberately NOT doing:** hero rules modal, tab
kill / bar-slice, sticky VS ticker, command strip (all Stage v1 items — don't double-touch); pools/waves;
any live payment flow; player-claimable NFTs (never); a second control row anywhere.

---

## 9. THINGS IN THE CURRENT CODE THAT FIGHT THE DESIGN (found while verifying)

1. **The unguarded reset chain** — renderDetail :3606–:3609 writes six ids with no null guards *outside*
   tnyTry. It is the single biggest constraint on restructuring the detail skeleton (forces K1).
2. **Two gold CTAs pre-bracket for the TO** — :3636 + :3639 render `Register (play too)` and
   `Start bracket ▶` side by side, violating the one-primary-action rule today. D1 resolves it.
3. **Rail-label drift** — `.tny-section-lab` :550 is the correct 10px/.16em recipe, but `.tny-etr.head`
   :877 uses .08em, `.tny-od-round` :973 region uses .05em, and `.tny-form label` uses 11px/.05em. The
   create-form rebuild (gs-209) retunes its own labels; the rest is the Stage v1 alias rule's job.
4. **`.tny-gate` name is taken** (:908, stationed-host gate) — the registration gate must ship as
   `.tny-entergate` or the two collide (the `.board` incident pattern).
5. **`tny-btn gold` is over-distributed** — Add (typeahead), Enroll this PC, Manage ▸, and the hero CTAs
   are all molten. The event page's gold budget only works after D1/M1 concentrate registration gold in
   one place; a later Stage v1 pass should demote Manage/Enroll to outline cuts.
6. **`#tnyChamp` fill is unguarded on both branches** (:3690) — fine while the element stays, but it is
   also in the reset chain; the podium must reuse the exact container id.
7. **The whole detail view is innerHTML-rebuilt on every SSE delta** — any naive "insert a perks div
   after load" approach dies within seconds. Everything must go through the renderers (the gs-206
   `TNY._addq` focus-restore dance is the canonical example of the cost — and the template to copy).
