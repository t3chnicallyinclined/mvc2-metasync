# MetaSync UI Redesign — design-team specs (2026-08-18)

Produced by a 3-designer panel + synthesis (Match) and a 4-surface panel + unification lead (app-wide).
Line refs were verified against web/index.html on 2026-08-18 (gs-106 era) — re-verify before editing.
Mockup canvas artifact: "MetaSync Redesign". Status: OWNER DECIDED 2026-08-18 — GO. VS-center = **Option D "Player Plates"** (SF6 player-card style:
64px Steam avatars on skewX(-8deg) plates, accent gradient sampled from each player's EQUIPPED SKIN palette
(fallback: rank-tier colors), oversized 62px gradient VS + ghost watermark, score above, state pill below;
Live Sync toggle MOVES OUT of the scoreboard into the header cSync chip, which already toggles sync).
The plate/avatar/skin-color "touch" extends APP-WIDE: Ranks podium = player plates, region drill hero =
plated, tournament tale-of-the-tape = plates. Future feature (roadmap, not this redesign): Card Editor —
user-picked plate gradient/frame + EARNED titles (tournament wins, tier milestones), stored additively in
the server profile, synced to opponents like skins. NO arbitrary image upload (moderation/coherence).
Mockups: "MetaSync Redesign" canvas, Option D artboard.

---

All claims verified against the live file. Line-ref corrections found: `refreshMe` (the unguarded `p1sid`/`youHd*` writes) is at **2104**, the flag fill is `refreshMeBadge` at **4382–4384** (guarded), opponent rank fills at **4388–4397** (guarded), `applySideLayout` at **2804–2814** — and it turns out layout is **fixed** (You always left; the `order` writes are null-safe and it *blanks* `.side` textContent, so the rail label must be a new element). Also `oppState` writes at **2054/2061 are unguarded** — that element cannot be deleted without a sink. The merged spec accounts for all of this.

---

# MATCH TAB — FINAL MERGED SPEC: "ONE SCOREBOARD"

File: `c:/Users/trist/projects/mvc-live-skins/web/index.html` (single file; all line refs verified 2026-08-18 against the current source). Build rules per CLAUDE.md: Edit tool only, bump `gs-N`, `node src-tauri/stage-frontend.mjs`, `node --check` extracted scripts, live-verify in a real match.

## Adjudications (where the three specs conflicted)

1. **Keep `#link` as THE SCOREBOARD; strip identity from team cards** (D1+D2) — over D3's delete-the-VS-panel: `#link` carries the `.synced` visual system (2073, CSS 103/106/111) and the wire "alive" animation for free; D3's version re-plumbs all of that into cards for no information gain.
2. **Score hero = restyle `#scoreChip` in place** (D1) — over D2's `sbScore/sbMe/sbThem` rewrite: one-line innerHTML tweak + CSS gets 90% of the broadcast look with ~5% of the JS risk.
3. **No `#vsMark`** (cut from D1): the `.wire` VS (967) already provides the standing VS mark and its flow animation is the sync-alive signal — a second big VS is the exact redundancy we're deleting.
4. **`#gsChip` demotion = CSS `!important` gate on `body.debug`** (D2) — over D1's JS gate at 2295: the `!important` beats the inline `style.display=''` the fill sets, so it's zero JS edits.
5. **Team cards keep a SLIM rail with `#oppState`** (D2) — over D1's headerless cards: the `oppState` writes at 2054/2061 are **unguarded**, and "Synced / Facing · no app / Scanning" is the *skin-sync verdict for the card it sits on* — a different fact from `#p2sid`'s identity status. One fact per home is preserved: identity status → scoreboard sub-line; skin verdict → card rail. `#youState` (pure `modePill` duplicate, fill guarded at 2239) is deleted.
6. **`#matchupStrip` = standalone slim row between scoreboard and board** (D1+D3 majority) — over D2's footer-inside-`#link`: same scan order, zero grid-placement risk.
7. **Beta sentence → merged into `#rcBanner`** (D1+D2); D3's "put it on the Ranks tab" survives as a one-line nice-to-have addition to `.lb-sub` (it genuinely belongs there too, and it's free).
8. **D3's engagement layer is cut to three CSS-only wins** (dashed empty avatar, gold sync-off CTA border, hit-confirm tile pop) — the locker renderer, ghost slots, dynamic empty-state copy, and `steam://run` launcher are real features, not this redesign, and they blow the one-day budget.
9. **Side-flip worry is moot**: `applySideLayout` (2804) pins You-left/Opp-right permanently and its writes are null-safe. Only trap: it blanks `.side` textContent (2813) — so the new rail labels use a NEW class, or delete the `.side` divs (safe: `t()` is null-guarded).

## 1. DELETE / MERGE (explicit)

| # | Action | Target (verified lines) |
|---|---|---|
| D1 | **DELETE** the in-tab beta-note div | 986–988. Append to `#rcBanner`'s `.rc-msg` (906): *"Stats are still being tuned — leaderboards may reset during beta."* Compact rcBanner CSS (431–437): `padding:7px 12px; font-size:11.5px`. Max one amber row, ever. |
| D2 | **DELETE** `.vsglyph` | 1003 (element) + 118 (CSS). Keep the `.seam` div + its `::before` skew line (117). |
| D3 | **DELETE** `#youState` | 998. Fill at 2239 is `if(ys)`-guarded — zero risk. |
| D4 | **DELETE** the two `.side` divs | 996, 1007. `applySideLayout` 2813 `t()` is null-safe. |
| D5 | **DELETE (visual)** `#p1sid` | Element STAYS (unguarded write at 2104), CSS `#p1sid{display:none}`. SteamID → `title` on `#p1name` (nice-to-have edit in refreshMe 2104). |
| D6 | **REPURPOSE** `#p2sid` as opponent status sub-line | Edits at **2046** and **2052** only: replace the `$('#p2sid').textContent=…steamid` half-statements with status copy — 2046 (has app): `'app connected — skins syncing'`; 2052 (identified, no app): `syncOn?'no app — local skins only':''`. 2060 already writes status ("identifying… / looking for opponent / not synced") — untouched. Restyle non-mono, 11px `--dim` italic. |
| D7 | **DEMOTE** `#gsChip` | CSS: `#gsChip{display:none!important}` + `body.debug #gsChip{display:inline-flex!important}`. Fills 2295/2304 untouched. Nice-to-have: triple-click on `#modePill` toggles `body.debug` + `localStorage.msDebug`. |
| M1 | **MERGE** team-card identity → hidden `#legacySinks` | `youHdName/youHdSid` (unguarded 2104), `oppHdName/oppHdSid` (unguarded 2046/2051/2059; guarded 4384/4397). Park in a hidden div now; strip the writes in the cleanup step, then delete the sink. |
| M2 | **DELETE elements** `#youRank` (997) / `#oppRank` (1008) | Fills at 2193/2211/2226 are all guarded — safe immediately; delete the fill lines at cleanup. `#p1rank`/`#p2rank` are the one rank home per player. |
| M3 | **MOVE** `#oppRecord` into scoreboard right node | Fill 2093–2103 is guarded (`if(!el)return`) — pure relocation. |
| M4 | **MOVE** `#scoreChip` out of `.modebar` into new `.score-center` at top of `.center` | Fill 2358–2370 keeps working; ONE line edit at 2368 to wrap the opponent numeral: ``scEl.innerHTML=`set <b>${me}</b> – <b class="them">${them}</b>${sess}` `` |
| M5 | **MOVE** `#matchupStrip` (1017–1027) between `#link` and `.board`; add `.slim` | All inner ids untouched (fills 2208–2228). |
| M6 | **KEEP hidden, untouched** | `#sideSwap/#sideTxt/#sideAuto/#paintToggle` (unguarded writes at 2321/2326/2348/2382/2390, 4279 — cheap insurance, already invisible). |
| M7 | **KEEP** `#mirrorTag` in the your-team rail | Fill 1818 guarded. It's a skin-layer fact → belongs on the skin card, not the scoreboard. |
| M8 | **DROP** my flag prefix from `#p1name` (nice-to-have) | One token at **4383**: `p1n.innerHTML=esc(mySteam.name)` (flag already lives in the header identity card). Opponent keeps theirs — only home. |

## 2. NEW STRUCTURE (annotated sketch, real ids — replaces lines 960–1027 region)

```html
<section class="panel on" id="p-match">

  <!-- ═══ SCOREBOARD — id="link" kept: .synced toggle (2073) + mobile CSS (203) target it ═══ -->
  <section class="link scoreboard" id="link">

    <div class="node p1">
      <div class="por" id="p1por"></div>                      <!-- KEEP · 48px now -->
      <div class="who">
        <div class="sidetag">You</div>                        <!-- was "Your side" -->
        <div class="nm" id="p1name">You</div>                 <!-- KEEP · 16px/800 · title=SteamID (nice-to-have) -->
        <div class="rk" id="p1rank" style="...keep inline flex..."></div>  <!-- KEEP · THE user rank on-tab -->
        <div class="sid mono" id="p1sid">—</div>              <!-- KEEP element, CSS-hidden (unguarded fill 2104) -->
      </div>
    </div>

    <div class="center">
      <div class="score-center">
        <span class="gs-chip score-big" id="scoreChip" style="display:none"></span> <!-- MOVED · restyled hero -->
      </div>
      <div class="wire"><i></i><b>VS</b></div>                <!-- KEEP · the one VS + sync-alive animation -->
      <div class="toggle" id="syncToggle" role="switch" ...>  <!-- KEEP verbatim, incl. labels -->
      <div class="modebar">
        <span class="mode-pill" id="modePill">...<span id="modeTxt">detecting…</span></span> <!-- KEEP · carries "· P1" -->
        <span class="side-swap auto" id="sideSwap" style="display:none">...</span>           <!-- KEEP hidden -->
        <button class="side-swap" id="paintToggle" style="display:none">...</button>         <!-- KEEP hidden -->
        <span class="gs-chip" id="gsChip" style="display:none"></span>                       <!-- KEEP · body.debug-gated -->
      </div>
    </div>

    <div class="node p2">
      <div class="who">
        <div class="sidetag">Opponent</div>
        <div class="nm" id="p2name">—</div>                   <!-- KEEP · flag prefix stays (only home) -->
        <div class="rk" id="p2rank" style="...keep..."></div> <!-- KEEP · THE opponent rank -->
        <div class="sid mono" id="oppRecord"></div>           <!-- MOVED · "YOU 3 – 1 THEM", gold -->
        <div class="sub" id="p2sid">not synced</div>          <!-- REPURPOSED · status only, never a SteamID -->
      </div>
      <div class="por" id="p2por"></div>                      <!-- KEEP · dashed when empty -->
    </div>
  </section>

  <!-- (beta-note DELETED — merged into #rcBanner) -->

  <!-- ═══ MATCHUP — one slim row, above the fold ═══ -->
  <div id="matchupStrip" class="matchup slim" style="display:none">
    ...existing inner markup: muPct / muFill / muH2h / muBest / muKryp — ids untouched...
  </div>

  <!-- ═══ TEAM BOARD — slim rails, zero identity ═══ -->
  <main class="board">
    <section class="team you" id="teamYou">
      <div class="team-hd slim">
        <span class="rail-lbl">Your team</span>               <!-- NEW class (applySideLayout blanks .side!) -->
        <span id="mirrorTag" class="mirror-tag" style="display:none">🪞 mirror · your side</span> <!-- KEEP -->
      </div>
      <div class="cards" id="youCards"></div>                 <!-- KEEP -->
    </section>

    <div class="seam"></div>                                  <!-- vsglyph DELETED, skew line stays -->

    <section class="team opp" id="teamOpp">
      <div class="team-hd slim">
        <span class="rail-lbl">Opponent</span>
        <div class="state wait" id="oppState">Sync off</div>  <!-- KEEP · the skin-sync verdict (unguarded fills 2054/2061) -->
      </div>
      <div class="cards" id="oppCards"></div>                 <!-- KEEP -->
      <div class="opp-lock-note" id="oppLockNote" style="display:none">...</div>
      <div class="empty" id="oppEmpty">...</div>              <!-- KEEP -->
    </section>
  </main>

  <!-- migration sinks for UNGUARDED writes (2046/2051/2059 opp, 2104 you) — deleted in Step 5 -->
  <div id="legacySinks" hidden>
    <span id="youHdName"></span><span id="youHdSid"></span>
    <span id="oppHdName"></span><span id="oppHdSid"></span>
  </div>

  <div class="dock" style="display:none">...</div>
  <div class="banner" id="banner"></div>
</section>
```

## 3. VISUAL TREATMENT (existing tokens only)

- **Scoreboard**: keep `.link` grid/gradient/`::before` side wash (88–90) — already the "red corner / blue corner" read; just `padding:16px 18px`. `.synced` adds `box-shadow: inset 0 1px 0 color-mix(in srgb,var(--good) 30%,transparent)`.
- **Avatars** `.node .por`: 40→**48px**, radius 12. Empty `#p2por`: `border-style:dashed; opacity:.55` ("awaiting opponent" reads intentional).
- **Type scale (5 steps)**: score numerals `#scoreChip b` **26px/900 italic** `tabular-nums`, mine `var(--gold)`, `b.them` `var(--ink)`; the "set/game X/10/#id" text stays 11px `var(--dim)` (CSS: `#scoreChip.score-big{font-size:11px; background:none; border:none; display:flex; align-items:baseline; gap:6px}`). Names `.nm` 15→**16px/800**. Rank rows unchanged (rkInline). `.sidetag`/`.rail-lbl` 10px/700 caps `.16em` `var(--faint)`. Subs (`#p2sid.sub`, `#oppRecord`) 11px.
- **Center stack** (top→bottom): score → wire → sync toggle → modebar; gap 8. When no set: wire VS + pulsing modePill dot carry the center — never empty. Sync-off CTA: `body:not(.synced) — .toggle{border-color:color-mix(in srgb,var(--gold) 45%,var(--line))}` (scope via `#link:not(.synced) .toggle`).
- **Matchup `.slim`**: one ~36px row: `display:flex; align-items:center; gap:14px; padding:8px 14px; margin:10px 0 0; background:var(--panel-2)`; `.mu-pct` 26→**18px**; `.mu-teams` inline right, `.mu-tv` 11.5px ellipsized with full text in `title`. Kill the wrap-to-two-rows behavior of 402–414 for `.slim`.
- **Slim rails** `.team-hd.slim`: `padding:7px 12px; min-height:30px` (was ~46px); keep the side gradients (121–122) and the `.state` pill styles (126–128); delete `.team-hd .side` italic styling usage (class gone).
- **Height budget**: beta-note (~54px) + fat headers (~2×16px) + vsglyph, minus the taller scoreboard ≈ character tiles rise ~120–150px → above the fold at 768px.
- **Mobile** (203): unchanged — `.link`/`.node` selectors survive; add `.score-center{order:-1}` in the stacked layout.

## 4. JS FILL-SITE MAP (every id)

| Id | Fill (verified) | Disposition |
|---|---|---|
| `p1por` `p2por` | 2047/2053/2062/4373/4390 via `setPor` (4312) | KEEP, no edit |
| `p1name` | 2104, 4383 (guarded) | KEEP · nice-to-have: drop `myFlag` at 4383, add SteamID `title` at 2104 |
| `p1rank` | 2194 (guarded) | KEEP — the one user rank on-tab (incl. Civilian fallback) |
| `p1sid` | 2104 (**unguarded**) | KEEP element, CSS-hidden |
| `p2name` | 2046/2052/2060, 4397 (guarded) | KEEP (flag prefix stays) |
| `p2rank` | 4388/4389/4396 (all guarded) | KEEP — the one opponent rank |
| `p2sid` | 2046/2052 (**edit** → status copy), 2060 (already status) | REPURPOSED status sub-line |
| `oppRecord` | 2093–2103 (guarded) | MOVED into scoreboard right node |
| `scoreChip` | 2358–2370 | MOVED to `.score-center`; ONE line edit at 2368 (`<b class="them">`) |
| `modePill/modeTxt` | 2238 | KEEP verbatim (side suffix intact) |
| `gsChip` | 2295/2304 | KEEP; CSS `!important` gate on `body.debug` |
| `syncToggle` | 4270/4278, 2073 | KEEP verbatim |
| `sideSwap/sideTxt/sideAuto/paintToggle` | 2321–2348/2382/2390/4279 (**unguarded**) | KEEP hidden in modebar |
| `mirrorTag` | 1818 (guarded) | KEEP in your-team rail |
| `oppState` | 1657 (guarded), 2054/2061 (**unguarded**) | KEEP in opp rail — the skin-sync verdict |
| `youState` | 2239 (guarded) | DELETE element now, fill line at cleanup |
| `youRank`/`oppRank` | 2193 / 2211+2226 (all guarded) | DELETE elements now, fill lines at cleanup |
| `youHdName/youHdSid` | 2104 (**unguarded**), 4384 (guarded) | → `#legacySinks`; strip writes at cleanup |
| `oppHdName/oppHdSid` | 2046/2051/2059 (**unguarded**), 4397 (guarded) | → `#legacySinks`; strip writes at cleanup |
| `matchupStrip` + `mu*` | 2208–2228 | KEEP ids; position + `.slim` CSS only |
| `oppEmpty/oppLockNote` | existing | KEEP |
| `rcBanner` | 4691/4692/4808 | KEEP mechanism; message text + compact CSS edit |
| `applySideLayout` | 2804–2814 | No edit needed (null-safe; `.side` deletion fine) |

## 5. IMPLEMENTATION STEPS (priority order — each ships alone)

**Must-do (core redesign, ~5–6 h):**
1. **Banner + CSS demotions** (~30 min, biggest win/effort): delete 986–988; extend `#rcBanner` msg (906) + compact its CSS (431–437); add `#p1sid{display:none}` and the `#gsChip` `body.debug` gate; delete `.vsglyph` (1003) + its CSS (118).
2. **Scoreboard restructure** (~2 h): sidetags → "You"/"Opponent"; move `#scoreChip` into `.score-center`; move `#oppRecord` into the p2 `.who`; repurpose `#p2sid` (two half-line edits at 2046/2052 + `.sub` restyle); one-line 2368 edit; 48px avatars; 16px names; center-stack CSS. Bump `gs-N`, restage, `node --check`.
3. **Team rails + sinks** (~1.5 h): slim both `.team-hd`s to `.rail-lbl` + (`mirrorTag` | `oppState`); delete `#youState`, `#youRank`, `#oppRank`, both `.side` divs; add `#legacySinks` with the four unguarded ids. **Verify the 4s tick loop throws nothing with the console open.**
4. **Matchup slim** (~30 min): relocate 1017–1027 above `.board`; `.slim` CSS.
5. **Cleanup release** (~45 min, separate ship): strip dead writes — the `oppHdName/oppHdSid` halves at 2046/2051/2059, the `youHdName/youHdSid` halves at 2104, the guarded lines 4384 (`yh`), 4397 (`oh`), 2239 (`ys`), 2193 (`youRank`), 2211+2226 (`oppRank`) — then delete `#legacySinks`. Live-verify the full state walk: game off → menu → char select → in match (P1 and P2 sessions) → set score → opponent with/without app.

**Nice-to-have (only if the day allows, in this order):**
6. Gold sync-off CTA border + dashed empty `#p2por` + `.synced` top-edge glow (pure CSS).
7. Score pop: `.bump` class + 180ms scale keyframe on score change (2 lines in the 2358 block).
8. Hit-confirm on char-select lock: stamp `.locked-in` on changed tiles in `renderYou`, 450ms gold-ring keyframe + `animationend` cleanup.
9. Rank badge 15→18px (2194, 4396) + drop my flag at 4383 + SteamID `title`s.
10. Triple-click `#modePill` → toggle `body.debug` + `localStorage.msDebug`.
11. Add the "leaderboards reset periodically" sentence to the Ranks tab `.lb-sub` (static HTML, one line).

**Cut entirely** (didn't pay for itself): D2's `sbScore` fill-block rewrite, D1's `#vsMark`, D2's matchup-in-grid footer, D3's `#link` deletion, locker/ghost-slot renderers, dynamic empty-state copy, `steam://run` launcher, shimmer scan animation, team-header click-to-profile wiring.

---

All shared-vocabulary anchors verified against live source this session: `.sidetag` :99, `.lb-row` family :262–271, `#rcBanner` :904–908, `#repNote` :910–913, `rkBadge` :2133 / `rkB` :2140 / `flagEmoji` :4308 / `avatarImg` :4310, tny rail variants :472/:620–621/:742. Namespaces `.bd-*`, `.hof-*`, `.rail-lab`, `.seg` confirmed unused (clean). Findings below are the final spec.

# METASYNC UNIFIED APP SPEC — Final (Design Lead pass)

Scope: `c:/Users/trist/projects/mvc-live-skins/web/index.html` only. Backend untouched. Match tab already shipped and is the style authority.

---

## PART 1 — SHARED COMPONENT VOCABULARY (defined ONCE, in one new CSS block after :271)

The four specs invented overlapping components under four namespaces (`.hof-*`, `.bd-*`/`.reg-*`, `.tny-*` retunes, `.rail-lab`/`.lib-*`). Unified below. **Add-only CSS** — nothing here deletes existing classes, so the foundation block ships with zero visual change until consumers land.

### 1.1 `.rail-lab` — THE slim label rail (adopting Library's name, app-wide)
```css
.rail-lab{font-size:10px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--faint);margin:18px 2px 8px;display:block}
```
Exact clone of `.sidetag` (:99), which stays for the Match tab. Every section header, column rail, bracket-round label, drawer section label uses this — one class, no per-surface variants, **no colored rails ever** (kills `.tny-blabel` colors :620–621; cards carry color, labels don't).
- Ranks: the `HALL OF FAME` rail span, podium/footer labels.
- Regions: replaces `.reg-railtag`, `.reg-sect`, hero stat `<i>` labels.
- Tournament: retune `.tny-section-lab` (:472, currently 11px/.13em/800) to this exact recipe, then CSS-alias the four other rails in one comma rule: `.tny-rlabel,.tny-blabel,.tny-cc-sub,.tny-report-lab,.tny-etr.head{ /* same recipe */ }` — no emitter edits needed for existing markup; rewritten emitters use `rail-lab` directly.
- Library: as specced (it invented the name).

### 1.2 `.board` + `.bd-*` — THE board table (columnar, Valorant-dense)
Resolves the biggest conflict: Ranks specced `.hof-cols/.hof-r`, Regions specced `.bd-head/.bd-row` with *card* rows. **Ruling: one component, `.bd-*` names, Ranks' dense flat-row treatment.** Regions loses its rounded card rows — a region ladder and a player ladder must read as the same object.

```css
.board{background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.board .bd-head,.board .bd-row{display:grid;grid-template-columns:var(--bd-cols);align-items:center;padding:0 15px}
.board .bd-head{position:sticky;top:0;background:var(--panel);border-bottom:1px solid var(--line-soft);height:34px;z-index:1}
.board .bd-head .bd-c{font-size:10px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--faint)}
.board .bd-row{min-height:44px;border-bottom:1px solid var(--line-soft)}
.board .bd-row:last-child{border-bottom:0}
.board .bd-row:hover{background:var(--panel-2)}
.board .bd-row.r1{background:linear-gradient(90deg,var(--gold-soft),transparent)}
.board .bd-row.me{box-shadow:0 0 0 1.5px var(--gold) inset}
.bd-rank{font-weight:800;font-size:14px;color:var(--gold);font-variant-numeric:tabular-nums;text-align:center}
.bd-name{font-weight:700;font-size:13.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.bd-num{font-variant-numeric:tabular-nums;text-align:right;font-size:13px}
.bd-num.dim{color:var(--dim);font-size:12px;font-weight:500}
.bd-sub{font-size:11px;font-weight:500;color:var(--faint);margin-left:6px}
.bd-sort{cursor:pointer} .bd-sort:hover{color:var(--dim)}
.bd-sort.on{color:var(--ink)} .bd-sort.on::after{content:"▾";margin-left:3px}
```
Per-surface column widths via the CSS var, scoped: `#p-ranks .board{--bd-cols:44px minmax(0,1fr) 128px 72px 64px 96px}`, `#p-regions .board{--bd-cols:34px minmax(0,1fr) 64px 96px 56px minmax(110px,150px)}`. Sort-in-header (`.bd-sort`, from Regions' spec, renamed from `.reg-sort`) is part of the component; Ranks simply doesn't use it (server owns its order — correct call, unchanged). `.r1`/`.me` semantics deliberately mirror `.lb-row`'s (:263–264).

### 1.3 `.lb-row` — THE simple player-row (existing :262–271, canonical, never deleted)
Two row components exist on purpose: `.bd-row` = dense columnar *board*; `.lb-row` = self-contained *player card row* for short lists. Canonical structure, documented once:
```
.lb-row [.r1] [.me]
  .lb-rank      → seed / placement / # (gold, tabular-nums)
  .lb-name      → [avatarImg(av,20)] flagEmoji(cc) Name [rkBadge/rkB] [.me-tag]  (+ lb-click/data-sid for profile)
  .lb-wl        → W–L
  .lb-stat OR .pill → right slot
```
Consumers: Regions drill-down players (:4641–4644, **kept verbatim** per the port-proven-code rule, + `.me` class only), Tournament entrants/standings (re-clothed per tourney spec), tourney empty states. Rule: avatar renders only when the payload already carries it — never fetch for a row.

### 1.4 `.seg` — THE segmented mode control
```css
.seg{display:inline-flex;gap:2px;background:var(--panel-2);border:1px solid var(--line);border-radius:9px;padding:2px}
.seg button{font-size:12px;font-weight:700;padding:5px 12px;border:0;background:transparent;color:var(--dim);border-radius:7px;cursor:pointer}
.seg button.on{background:var(--panel);color:var(--ink);box-shadow:0 0 0 1px var(--gold-soft)}
```
Consumers: Ranks `#lbModes` (was `.hof-modes`), Regions `#regTabs` (was `.reg-seg`; id + data-rl + listener :4652 untouched), Library `#libFilter`. Nice-to-have later: `#lbPeriod`, tny subnav. **App-wide convention (from Ranks): hidden controls use `display:none`, never a greyed `.off` state.**

### 1.5 `.pill` — THE state pill
```css
.pill{display:inline-flex;align-items:center;gap:4px;font-size:10px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;padding:2px 8px;border-radius:99px;border:1px solid var(--line);color:var(--dim);white-space:nowrap}
.pill.gold{background:var(--gold);color:var(--gold-ink);border-color:var(--gold)}   /* yours / live-equipped / champion */
.pill.ok{color:#5bd66f;border-color:transparent}                                     /* ✓ in / verified (matches .lb-verified :270) */
.pill.hot{color:var(--p2);border-color:var(--p2-line)}                               /* LIVE match */
```
Consumers: Tournament entrant/standings status (`✓ in`, `Champion` = `.pill.gold`, `Eliminated` = plain), CC state tags; Library tile chips (`LIVE` = `.pill.gold`, `⬇ BAKED` = plain). `.me-tag` (:267) stays as-is — it's the "YOU" marker, not a pill.

### 1.6 `.empty-invite` — THE intentional empty state
```css
.empty-invite{padding:26px 18px;text-align:center;border:1px dashed var(--line);border-radius:12px;color:var(--dim);font-size:12.5px;font-weight:600}
.empty-invite b{color:var(--ink)} .empty-invite .go{color:var(--gold);font-weight:700;cursor:pointer}
```
Standalone or stacked with legacy `.lb-empty` (which stays — tourney empties depend on it, per Ranks spec). Consumers: Ranks open podium slots + gate copy, Regions no-regions CTA + sync-off + relocated `#repNote` (`.reg-cta` becomes `.empty-invite` + `.go` line — keeps the 4385 display toggle by making it a block/flex-column), Tournament pending-bracket box, Library vault-empty + `#libEmpty` search-miss.

### 1.7 Global rules (not classes)
- **Type scale (5 steps)**: 10 rail / 11.5 trust+micro / 13.5 names+body / 15–16 stat cells / 22 page-hero titles. One exception: 26px numeric hero, used exactly once app-wide (Ranks podium #1 number). Tournament hero title 25→22 (:719) conforms.
- **Numerals**: `font-variant-numeric:tabular-nums` on every numeric cell (bd-num, lb-stat has it, `.tny-score` :510 gets it).
- **Gold budget**: gold = yours / first / the one primary action per surface. Amber = `#rcBanner` only; after `#repNote` relocates into Regions, the app is back to exactly one banner. No amber anywhere in the four new surfaces.
- **JS safety**: unguarded `$('#x').onclick=` / `.innerHTML=` writes are deleted in the SAME edit as their element (white-screen risk); every phase ends with script-extraction + `node --check`, gs-N bump, `node src-tauri/stage-frontend.mjs`. Tick-rebuilt surfaces (`#tnyAlert` 1.2s, `renderDetail` SSE/30s poll, `#dGrid`+`#dCur` on every applySkin) accept NO one-shot DOM edits — all markup from render fns. `renderLeaderboard` / `renderRegions` / `renderLibrary` are NOT tick-driven — one-shot-safe.

---

## PART 2 — PER-SURFACE (inherit the surface specs; deltas from unification listed)

### 2.1 RANKS (ships first)
Inherit the Ranks spec in full — delete/merge table §2, structure §3, pinned-YOU §5, fill-map §6 all stand. **Changes (one line each):**
- `.hof-cols`→`.bd-head`, `.hof-r`→`.bd-row`, `.hof-pos`→`.bd-rank`, `.hof-pl`→`.bd-name`, `.hof-wl`/`.hof-pct`→`.bd-num.dim`/`.bd-num`, `.hof-stat`→`.bd-num` at 15px; board shell = `.board` with `--bd-cols` — `.hof-*` survives ONLY for `.hof-wrap/.hof-podium/.hof-pod/.hof-me/.hof-foot/.hof-trust`.
- `.hof-modes`→`.seg` (id `#lbModes` kept); rail label uses `.rail-lab` inside the `.hof-rail` flex row.
- `#lbPeriod` hidden-not-greyed rule is now the app-wide convention (§1.4).
- Empty/gate copy renders in `.empty-invite`; open podium slots use its dashed treatment.
- Everything else (default `lbTab='rating'`, limit 50, tierlist inside the board shell, `#lbList`-owns-everything render, delegate :4595 preserved via `lb-click`) unchanged.

### 2.2 REGIONS
Inherit the Regions spec — deletes §1, structure §2, delegate-order fix + `_regCache` handoff §4, data map §5 all stand. **Changes:**
- **Card rows → dense board**: list rows become flat `.bd-row`s inside one `.board` (44px, separators, hover) — the §3 per-row card treatment (radius 11 / `--card` bg / border) is overruled for board consistency with Ranks.
- `.reg-sort`→`.bd-sort` (component-owned), `.reg-railtag`/`.reg-sect`→`.rail-lab`, `.reg-seg`→`.seg` (`#regTabs` id/data/listener untouched).
- `#repNote` relocation + restyle stands, but as `.empty-invite` + `.go` (not a bespoke `.reg-cta` class); prefer changing :4385 to `display=''` over fighting the flex toggle — one-word edit, verified guarded.
- `.lb-empty.invite`→`.empty-invite`; drill-down hero (`.reg-hero`), back button, and verbatim player rows/teams table stand as specced.

### 2.3 TOURNAMENT
Inherit the Tournament spec — sub-tab audit, dead-UI deletes (`#tnyStatus` triple, `#tnyTeamBar`, `#tnyEntrantsLab/N`, `#tnyBracketLab`, Overview merge, ~70 lines dead CSS), fill-map §4 with its tick warnings all stand. **Changes:**
- Rail retune targets the §1.1 recipe exactly (10px/.16em, not the spec's leftover 11px numbers at :472); alias rule as §1.1.
- Entrants/Standings adopt canonical `.lb-row` structure §1.3 with status in the right slot as `.pill` variants (`✓ in` = `.pill.ok`, Champion = `.pill.gold` + `.r1`, Eliminated = plain) — drops the spec's ad-hoc pill styling.
- Pending-bracket empty state = `.empty-invite` (same copy).
- CC run-strip, gate-fold, you're-up bar, hero 22px, tabular scores: as specced. Subnav→`.seg` is nice-to-have only.

### 2.4 LIBRARY
Inherit the Library spec — applybar/stub purge §2 (with its unguarded-handler discipline), structure §3, drawer risk-weighting, fill-map §5 all stand. **Changes:**
- `.rail-lab` is now the app-wide class (no change to the spec, just no longer Library-private).
- Tile chips: `LIVE` = `.pill.gold`, `⬇ BAKED` = `.pill` (drops bespoke chip CSS); `#libFilter` = `.seg`.
- Vault-empty + `#libEmpty` = `.empty-invite`; `.lib-status` slim row stands as the surface's ONE status element.
- Studio resurfacing (`#dStudioOpen`) stays nice-to-have; Studio DOM/wiring untouched until then.

---

## PART 3 — APP-WIDE BUILD PLAN (one engineer, web/index.html, each phase independently shippable)

Every phase ends with the ship gate: gs-N bump → stage-frontend.mjs → script extraction + `node --check` → click-test listed surfaces. Hours are careful-work estimates.

**PHASE 0 — Foundation CSS + free deletes** · MUST · ~2h
Add the §1 component block (add-only, zero visual change). Ride along the two zero-risk sweeps: Tournament dead-code sweep (tourney step 1: `.tny-meta` triple + writes, `#tnyTeamBar` chain, `#tnyEntrantsLab/N`+`#tnyBracketLab` + writes, ~70 lines dead CSS) and Library stub purge (applybar :1163–1170 + :4835–4837 + :2900, `#btnImportPack` :1139/:4841, `#btnManageLo` :1154/:4840). All deletions verified dead/stub; regression surface ≈ zero. *Ships alone.*

**PHASE 1 — RANKS** · MUST · ~6.5h *(first after Match, per mandate)*
1. Markup swap :1046–1076 per Ranks §3 with §2.1 deltas (0.5h). 2. `#p-ranks` CSS replace :242–261 → `.hof-*` remnants + `--bd-cols`; leave :262–271 (1h). 3. `renderLeaderboard` rewrite: `lbTab='rating'`, limit 50, mode derivation, podium + `.board` rows + win%, trust-✓ kept, tierlist in-shell (2.5h). 4. Pinned YOU cases 1–3 (1h). 5. `#lbSearch` filter (0.75h). 6. Direct-bind Tiers/Suggest, TIER header → `openRankInfo`, footer gate line (0.5h). 7. Ship gate + eyeball Regions/tourney `.lb-*` non-regression (0.25h).

**PHASE 2 — REGIONS** · MUST · ~5.5h
1. Static markup + scoped CSS per §2.2 (chrome/head/relocated `#repNote`; delete `#regSort`/`#regExplain` + CSS :1110–1119) (1.5h — board CSS already exists from Phase 0). 2. `renderRegions` rewrite: `_regCache`, `.bd-row` emitters, Top Player cell, me-detection, `.empty-invite` states (2h). 3. Listeners: `#regHead` delegate, delete :4653, **reorder :4654 (lb-click before reg-click — required before Top Player ships)** (0.5h). 4. `openRegion` rewrite: hide chrome, hero from cache, verbatim player rows + `.me` (1h). 5. Ship gate incl. repNote-gone-from-other-tabs check (0.5h).

**PHASE 3 — TOURNAMENT** · MUST · ~5h
1. Overview merge: delete tab/fn/section, checked-in rail → Entrants, new tabs array + default, drop count badges (1.5h). 2. Gate→CC fold (0.5h). 3. Rail retune + alias rule + kill `.tny-blabel` colors (0.5h). 4. Entrants/Standings → `.lb-row` + `.pill` emit rewrite (:3250–3251, :3221–3222) with `.me` (1.5h). 5. Ship gate **on a live 4-man test event** — bracket + SSE repaint + undo exercised (1h).

**PHASE 4 — LIBRARY** · MUST · ~5h
1. Header rebuild: `.lib-rail` + `.lib-status` slim row (CSS :337–353 rewrite) (1h). 2. Tile-state pass in `renderLibrary`: `bakedSkins` lookup → pills, conditional swatches, `#libCount`, `#libEmpty` (1.5h). 3. `#libFilter` `.seg` + delegate (0.5h). 4. Drawer re-weight: Apply hero, Bake demoted + caption, hint deleted, `#dSaveVault` moved, `#dRecolor` toggle dropped (1.5h). 5. Vault restyle + `updated_ms` sort + empty state (0.5h incl. gate).

**PHASE 5 — NICE-TO-HAVE POOL** (any order, each shippable solo; cut freely)
- Tournament CC cards→rows + overflow line (~1h); bracket dashed-pending + tabular scores + hero 22px (~0.5h); stations-tab conditional + compact error strip (~0.5h).
- Ranks: server `?me=` exact position (~1h incl. 15-line server change); localStorage mode/period persistence (~0.5h); mini tier-ladder strip (~0.5h).
- Regions: localStorage sort/level (~0.25h); sort-direction toggle (~0.5h); pinned your-city row (~0.5h); narrow-width `.bd-top` collapse (~0.25h).
- Library: Studio entry via `#dStudioOpen` (~1h); `#drRomState` ROM caption (~0.5h); vault-in-drawer "yours" group (~1h).
- App-wide: `#lbPeriod` + tny subnav → `.seg` (~0.5h).

**Total must-do: ~24h across 5 shippable releases.** Deliberately NOT doing (adjudicated): per-column client sorting on Ranks, avatars in tierlists, a Regions podium (one hero per page — the drill hero owns it), any gallery/publish UI in Library (no server fields exist), forced avatars in tourney/drill rows (payloads lack them), any backend change except the optional `?me=`.

---

# PHASE 2 SPECS (2026-08-19): the ARENA generation



## RANKINGS — Marvel Ladder masthead

All line-anchored claims are now verified against the live file. Writing the merged spec as my final output.

# MetaSync RANKINGS — Final Merged Spec (Design Lead)

**Ground truth verified in `c:/Users/trist/projects/mvc-live-skins/web/index.html`:** two stacked rows exist today (`header.marquee` :1034 + `.tabbar` :1101); `#lbTabs` lives in the tabbar middle with a More-menu hiding six boards (:1110–1130); board keys are `rating, wins, streak, ocv, perfect, comeback, combo, deficit(Clutch), tierlist` + Regions = 10 destinations; podium renders only on `lbTab==='rating'` (:5025); one fetch `leaderboard{tab,period,limit:50}` with 15s `lbCache` (:5005); pinned-YOU row confirmed to have **no per-stat values from /profile** (`p.stat=0`, :5045); `RANK_TIERS` :2374, `RANK_MIN_GAMES=5` :2385, `RK_PLATE` :2442, `rkProgressHtml` :2466 (placements + next-tier + Galactus states already built); `#meCard` :1042; `libChip`/`romChip` :1132–1133; last-good-keep error path :5047. The leaderboard is still cache/poll — the push bus (0.1.98) is tournaments-only today, so the refresh icon survives for now.

## Conflict resolutions (one line each)

1. **Board navigation → masthead rail** (ARENA + TRACKER) over RANKED IA's Records hub: 2-of-3 convergence, it is literally the owner's stated instinct ("tabs on the first big banner"), and it costs zero extra fetches while the hub taxes every visit with an extra click plus 10 requests and buries the flagship ladder.
2. **From the hub proposal we keep two ideas anyway:** prev/next chevrons + ArrowLeft/Right cycling on the rail (the "flip-through" feel, where it's good), and the SEASON framing line.
3. **Global bar on Rankings → empty contextual slot** (ARENA/TRACKER) over IA's LADDER|RECORDS|REGIONS segment in the bar: board controls in global chrome is the two-control-row pattern the constraint bans.
4. **Your card → LEFT plate of the masthead** (IA + TRACKER) over ARENA's right slab: you-first is the Valorant-tracker lead read, and left mirrors the Match scoreboard's local-player side.
5. **Masthead center → board identity that re-themes per channel** (ARENA/TRACKER) over IA's static "SEASON ZERO" center: the banner repainting per board IS each board's "big banner" moment; the season line survives as the 10px rail label above the title.
6. **Podium per board → generalize the existing `.podium` from the fetch already in hand** (ARENA/TRACKER) over hub podium-cards: same owner wish, zero weight — flip :5025's condition.
7. **Accent discipline → ARENA's three-layer rule** (watermark word / stat number+unit / one accent color in ≤20px slivers; player plates stay tier-colored): prevents rainbow soup, TRACKER's per-board accents adopted as the palette.
8. **Per-board columns → TRACKER's grid table** (drop noise columns, add Games to legitimize counts): an hour of work that makes every board read like it was designed, not templated.
9. **Cutlines → TRACKER's skewed seam styling + ARENA's unclaimed-Galactus line; DROP IA's "+53 → Adamantium" chip on your row** — it duplicates the masthead progress bar; less is more.
10. **Live rail beside the ladder → all three agree; TRACKER's refinement wins** (Ranked channel only; stat boards go full-width — they're destination reads, not dashboards).
11. **Match contextual chip → empty** (ARENA) over TRACKER's promoted mode pill: the scoreboard already owns live state; don't relocate working chrome inside this budget.

---

## (a) Landing composition, top to bottom (1180px content width)

```
┌─ ARENA BAR ── 52px ── one row, replaces marquee + tabbar ────────────────────────┐
│ [M cab 34] ⟦MATCH⟧ ⟦RANKINGS = molten gold cut⟧ ⟦TOURNAMENT⟧ ⟦LIBRARY⟧  ···flex···│
│            (contextual slot: EMPTY on Rankings)  [N playing][sync knob][bell][meCard][theme] │
└──────────────────────────────────────────────────────────────────────────────────┘ 12px gap
┌─ MASTHEAD ── 168px total (128 content + 40 rail) ── .arena surface: ─────────────┐
│  red wash from left · blue wash from right · gold seam skewed at ~40% ·          │
│  ghost italic watermark = ACTIVE BOARD NAME ("RANKED"/"STREAK"/…) ~130px @ 4%    │
│ ┌ YOUR PLATE 340×118, skew(-6), gold ring, ┐   10px rail: SEASON ZERO · OPEN BETA │
│ │ --pa/--pb = your RK_PLATE tier pair      │   30px/900 italic: MARVEL LADDER     │
│ │ [badge 56] VIBRANIUM   1147 ELO (28px)   │   ▁▁ 3px --lb-acc underline          │
│ │ bar: +53 → ADAMANTIUM (rkProgressHtml)   │   12px dim 1-line desc (ex-lbExplain)│
│ │ #8 · 21W–9L · 70% · peak 1284 (11.5px)   │   [All-time|Today|Week|Month] cuts   │
│ └──────────────────────────────────────────┘   (stat boards only, top-right)      │
│ ── RAIL 40px: ‹ ⟦Ranked⟧⟦Wins⟧⟦Streak⟧⟦OCV⟧⟦Perfect⟧⟦Comeback⟧⟦Combo⟧⟦Clutch⟧⟦Tiers⟧⟦Regions⟧ › · [search 170] · tiers-info · suggest · refresh │
└──────────────────────────────────────────────────────────────────────────────────┘ 12px gap
┌─ LADDER 760px ──────────────────────────────────┐ ┌─ LIVE RAIL 380px, sticky ────┐
│ PODIUM ~150px: [#2 236][#1 264 crowned][#3 236] │ │ NOW PLAYING (npFeed)         │
│   existing .pod tier plates, unchanged          │ │ LIVE RESULTS (lrFeed)        │
│ BOARD: bd-head 32px · bd-row 44px × N           │ │  (moved up from page bottom; │
│   #│Player│Tier│Rating│W–L│Win%                 │ │   Ranked channel only)       │
│   ── .bd-cut 24px: ⟦ADAMANTIUM · 1300⟧ seam ──  │ └──────────────────────────────┘
│   … ── ⟦GOLD · 1120⟧ ── …                       │
│ PINNED YOU ROW (existing, gold-ringed)          │
│ 11.5px faint civilian note (existing :5040)     │
└─────────────────────────────────────────────────┘
```
First paint is never blank: the masthead needs no fetch; warm revisits render from `lbCache`. Deleted from today: the standalone period-pill row, the boxed `#lbExplain`, the More-menu, `#lbTabs` in the tabbar, `libChip`/`romChip` from global chrome, the brand tagline. Below 980px: live rail stacks under the board, rail cuts go icon-only, masthead stacks (your plate above the title). The masthead alone (rail hidden) crops as a 1180×128 share card, consistent with the profile-hero/set-card plate language.

## (b) Board navigation model — FINAL

**All 10 boards are channels on the masthead rail** — one row of SF6-cut segments (skewX(-12deg), active = molten gold `linear-gradient(180deg,#ffe084,#c98f0e)` + dark ink, inactive = dim outline) fused to the banner's bottom edge, with chevron cuts at both ends and ArrowLeft/ArrowRight cycling channels. Switching a channel repaints watermark, title, accent, podium, and rows in place (instant on warm cache) — it *feels* like paging, it *is* direct access. Implementation is a move, not a rewrite: relocate the `#lbTabs` div into the masthead, promote the six `#lbMenu` buttons to first-class cuts, delete `lbMoreBtn`; the dispatcher (:5051–5059) survives untouched.

**Every board's podium moment, weightless:** change :5025's condition from `lbTab==='rating'` to all player boards; the top-3 come free from the fetch already in hand. Differentiation is a strict three-layer rule — (1) the ghost watermark + title = the board name, (2) the podium big number = that board's stat with a 10px caps unit sublabel in the board accent (`WINS / BEST STREAK / OCVS / PERFECTS / COMEBACKS / MAX COMBO / CLUTCH WINS`), (3) accent `--lb-acc` used only in ≤20px slivers (unit label, active cut, title underline): Ranked `#e8b93c` · Wins `#4ade80` · Streak `#ff8a3c` · OCV `#ff5555` · Perfect `#9fd4ef` · Comeback `#b98cff` · Combo `#4aa8ff` · Clutch `#34d39a`. Player plates stay tier-colored (`RK_PLATE`) always. Tiers (team table) and Regions render no podium; Tiers podium-metals variant is cut for scope. Period cuts appear on stat boards only (existing rule); search stays a client-side filter that hides the podium.

**Per-board columns** (same payload, tuned emphasis): Ranked keeps `40/1fr/138/92/84/60`; Wins → `# · Player · Tier · Wins ✓verified · Win%`; Streak → `… · Best streak · W–L` (drop Win%, redundant); OCV/Perfect/Comeback → `… · Count · Games` (games = wins+losses client-side, so 1-in-2 can't cosplay as 40-in-400); Combo → `… · Max hits · Games`; Clutch(`deficit`) → `… · Clutch wins · Win%`; Tiers keeps its team table; Regions swaps in the existing `#p-regions` content restyled under the same masthead (title REGIONS, watermark WORLD), its sort pills moving into the board-card header.

## (c) The global arena bar — four states

One 52px row, constant skeleton: `[M cab] [MATCH][RANKINGS][TOURNAMENT][LIBRARY] [flex] [one contextual chip max] [N-playing count · sync knob · result-check bell · meCard · theme]`. Nav = cut parallelograms (counter-skewed labels), active gold, inactive dim outline, **inactive cuts collapse to icon-only under ~1100px**. Right cluster never reflows. Library becomes a real fourth page absorbing `libChip`; `romChip` moves into the Library page header. Rule stated once for every future page: the bar carries navigation + identity + global state; anything page-specific beyond one status chip lives on that page's banner.

| Page | Contextual slot |
|---|---|
| **Match** | empty — the scoreboard's mode pill owns live state |
| **Rankings** | empty — the masthead owns every board control |
| **Tournament** | live-event chip only while registered/hosting/spectating: gold dot + event name + round, click jumps to bracket |
| **Library** | ROM status chip (`romDot` + "ROM: set / not set") |

## (d) YOUR rank card (answering §4) and cutlines (§5) — merged decisions

**Your card = the masthead's left plate** (340×118, skew -6, gold outer ring, `--pa/--pb` = your tier's `RK_PLATE` pair): badge 56px (largest rank rendering in the app), tier name in tier color, ELO 28px italic tabular, `rkProgressHtml` bar verbatim ("+53 → Adamantium"), season line `#8 · 21W–9L · 70% · peak 1284` (position from the cached top-50, "below #50" if absent). It ships on every channel — your rank is the constant, boards rotate behind it. On stat channels the season line swaps to your value **only if you're in that board's top-50 payload**; otherwise "not on this board yet" — never fake a number (/profile has no per-stat values, verified :5045). States: **sync off** → plate becomes the gate ("Go Live to get ranked" cut + knob); **Civilian** → no ELO, placements meter 2/5 (rkProgressHtml already renders it); **Galactus** → crown line, no bar. Clicks: plate → your profile; badge/bar → `openRankInfo()`. `#meCard` in the bar stays as the compact echo — one hero, one whisper, zero other duplicates.

**Cutlines, Ranked board only:** while mapping rows, when `rankOf` tier changes between adjacent players, emit a 24px non-player seam — 1px hairlines in the upper tier's color at ~35% alpha running out from a small skewed center tag `[badge 14px] ADAMANTIUM · 1300` (10px/700/caps rail type; the label names the tier above the line, WoW convention). **The Galactus line renders even when unclaimed** ("GALACTUS · 1500 — unclaimed", magenta, above row 1) — the visibly empty throne is the best ladder bait in the genre. No cutlines on stat boards; search hides them with the podium. Your distance-to-next lives only in the masthead bar — no duplicate chips on rows.

## (e) Priority-ordered build list

**Must-do (~13h):**
1. `.cut` + `.arena` CSS primitives (shared, Match/Tournament inherit later) — 2h
2. Merge marquee + tabbar into one 52px arena bar; Library nav cut; romChip → Library header (**the one risky refactor — keep every existing element id** so `refreshMyRank`/`updateSyncChip`/`refreshMe` writes keep landing) — 3.5h
3. Masthead markup + `paintMasthead(lbTab)` (title/watermark/accent/desc/period cuts) + your-plate fill from the existing profile path — 3h
4. Move `#lbTabs` into the rail, promote the six menu boards, delete More-menu, add chevrons + arrow-key cycling — 1.5h
5. Generalize the podium (:5025 condition + stat big number + unit sublabel) — 1h
6. Two-column ladder layout + move `#npFeed`/`#lrFeed` into the right rail — 1h
7. Cutoff seam rows in the row loop + unclaimed-Galactus line — 1h

**Polish (~4.5h):** per-board column grids (1.5h) · `--lb-acc` accent set (0.5h) · your-plate placement/Galactus/locked states beyond the default (1h) · <980px stacking + icon-only nav collapse (1h) · masthead counts line "45 ranked · 6 playing · Galactus unclaimed" from cache + presence (0.5h).

## (f) Mockup artboards to sell it (canvas)

1. **Rankings landing — Ranked channel** at 1180: bar + masthead (your Vibranium plate, cutlines visible, unclaimed Galactus seam) + podium + two-column ladder with live rail. The money shot.
2. **Stat channel — Streak**: same frame re-themed (watermark "STREAK", orange accent slivers, stat podium, full-width board, period cuts visible) — proves the one-system-many-channels idea in a single glance.
3. **Arena bar states strip**: the four bar variants stacked (Match/Rankings/Tournament-live/Library) showing the constant skeleton + one-chip rule.
4. **Your-plate states sheet**: locked / Civilian placements 2-of-5 / ranked Vibranium / Galactus crown — four plates side by side, the share-crop story.

---
Note: the claude.ai Gmail and Google Calendar MCP connectors require authorization (via claude.ai connector settings) before their tools can be used; they were not needed for this task.

## TOURNAMENT — The Stage

All three proposals verified against `c:/Users/trist/projects/mvc-live-skins/web/index.html` (5,567 lines, gs-114): six sub-tabs :3516–3519, hero :3476–3499 (watermark literally "MvC2" :3478), host state machine :3614–3634, alert :3637–3656 (`TNY._yup` stamp :3653), team-bar no-op :3661, gate :3666–3671, CC :3674–3687, hosts :3690–3718, bracket :3944–3996 (mini-plates + corner JOIN :3990–3993), skeleton :1546–1563, `tnyRepaint` sub-branches :3865–3867, SSE applier :3888–3935, lbTabs-in-tabbar precedent :1110–1130, delete-guard comment :3473. Every load-bearing claim in the three proposals checks out. Final merged spec follows.

---

# MetaSync TOURNAMENT — FINAL SPEC: "THE STAGE" (design-lead merge, v1)

## Conflict adjudications (one line each)

| Conflict | Winner | Why |
|---|---|---|
| Page structure: 2 views + drawer (IA) vs 3 tabs + Admin tab (STAGE) vs 2 tabs + Admin tab (OPS) | **IA: Bracket + Players + Admin DRAWER** | Entrants/Standings are one list at two lifecycle stages; admin is setup/exceptions, not a destination — the drawer keeps the running-event surface pure and the `.drawer` chassis already exists (Studio). |
| Hero heartbeat: lifecycle rail (IA) vs story line + fill bar (OPS/STAGE) | **BOTH, merged** | They answer different questions — rail = *where in the event's life*, story line = *live numbers*; together they replace Overview entirely. |
| Ghost watermark | **Event name** (STAGE/OPS) | The event watermarks its own stage; static "MvC2" is wallpaper. |
| Lobby: filter segs (IA/OPS) vs status rails (STAGE) | **Status rails, status filter dies** | Grouping IS the filter — one less control row; region `<select>` survives (long tail). |
| Done events in lobby | **Compact line-list** (OPS) | Keeps the card grid about what's playable now; champion inline only if the list payload carries it (IA's no-fetch-fan-out guard). |
| You're-up: persistent ticker (IA) vs sticky (STAGE) vs full takeover (OPS) | **Sticky VS-plate ticker now; takeover = polish** | Sticky + plates gets 90% of the drama at 20% of the cost and zero interrupt risk; machine + beep stamp kept verbatim (port-proven-code rule). |
| Bracket card skew | **Cards unskewed, chrome skewed** (STAGE) | Readability at 60+ cards; the plates/pills/cuts carry the language. |
| TO quick actions | **Inline 📣 CALL + 📺 on strip rows** (OPS) added to IA's dense rows | The two highest-frequency ops drop from 2 clicks to 1; everything else stays behind MANAGE ▸. |
| Stations | **Status dots on the strip header; management in the drawer** | Running-event glance ≠ setup plumbing; the gate (:3666) folds in as the strip's top row when hosts are required and absent. |
| Pre-bracket TO surface | **OPS's 1-2-3 SETUP CHECKLIST card** in the CC slot | Seed → Check-in → Start is the critical path; burying it in a drawer would be the one drawer mistake. |
| Spectator lane | **IA's GF-live strip + OPS's read-only "now playing"** unified as non-TO strip states | Same chassis as the CC, one `isTO` branch, zero new data. |

---

## 1. TOURNAMENT LOBBY (no event selected)

Replaces `renderBrowse`/`tnyCard` (:3302–3356). Three bands under one `rail-lab` header row:

- **MARQUEE** (~148px, only when a `running`/`checkin` event exists — or the viewer is registered in one; viewer's event wins ties, then `running` > `checkin`, then entrants): full-width arena surface — banner dimmed under the standard gradient, giant ghost italic event name ~64px @4%, red/blue corner washes, skewed gold seam bottom edge. Left: name 22px/900 + LIVE pill (pulse). Center: live line in rail-caps + gold tabular numerals (`entrants · status`; match counts only if the list payload carries them — **no new endpoint**). Right: ONE gold cut — `ENTER ▸`, or the viewer's personal state ("You're checked in — 8:00 PM", "YOU'RE UP"). Whole surface clickable.
- **UPCOMING & OPEN** — the existing card grid (`auto-fill minmax(300px,1fr)`), cards upgraded: 3px status accent edge (gold=checkin, line=open), status chip as a skewed corner cut on the banner, ghost italic event-initial watermark on banner-less cards, "next thing" footer line (`Starts Fri 8:00 PM · 12/24 in`), ticket-stub date block right (2-line `AUG/22`, tabular). Sort: checkin → open by `starts_ms` → own drafts.
- **RESULTS** — `done` events as single-line rows (name · date · 🏆 champion when payload has it, else "Complete"), capped 12 + "show all".

Controls live in the arena bar's Tournament slice (§7): region `<select>` (restyled to tokens) + `＋ CREATE` gold cut. The `tny-top` title row and the status `<select>` (:3323–3335) die. Create form unchanged — forms don't need theatre.

## 2. EVENT HERO (~230px total)

Rebuilds :3476–3499; keeps the replace-topbar mechanism (:3501) and banner backdrop.

- **Banner (120px):** TO image + scanlines; `.tny-hero-wm` becomes the **event name** (italic 900, ~56–64px, 4–5% white, right-clipped); blue corner wash bottom-left, red bottom-right (~6%); 2px skewed gold seam as the stage lip.
- **Identity strip (~76px):** title 26px/900/italic + **lifecycle rail** replacing the lone status pill — four 10px/700/caps/.16em stops `REG · CHECK-IN · BRACKET · CHAMPION`, current = gold + pulse dot, past = dim-filled, future = hollow; the CHAMPION stop carries the winner's name once set. Meta line as rail-label/value pairs (format/FT/region/date/entrants/Discord). Right: role chip (:3465 survives) + **exactly ONE gold CTA** (enforce the :3468–3472 machine): `REGISTER` → `CHECK IN` → running: a chip mirroring the ticker state (hero never contradicts the ticker) → `VIEW RESULT` (scrolls to podium). Ghost cuts: `Watch`, `Drop`, `RULES` (opens `tnyRulesHtml` in the existing `.tny-modal` — the always-rendered `<details>` :3498 dies). TO pre-bracket keeps `START BRACKET ▶` as a second gold cut — it IS the lifecycle transition.
- **Story line (28px):** state-driven one-liner + thin gold fill bar, repainted in `tnyRepaint`: open `Starts Fri 8 PM · 14 registered`; checkin `9 of 14 checked in ▓▓▓░`; running `⚔ WINNERS SEMIS · 14/31 played · 3 live ▓▓▓▓░` + `LIVE NOW: A vs B ▸` chip (click = bracket + scroll); done `🏆 <name> def. <name>`. All derived from `TNY.data`; the bar creeping forward on SSE deltas is the spectator's pulse.
- `#tnyChamp` strip (:3503, :1550) dies — champion moves to §6. No hero back button — back lives in the bar slice.

## 3. THE BRACKET AS THE STAGE

`tnyRenderBracket`/`tnyMatchEl` rewritten in place; data untouched.

- **Sections = arena corners.** Winners: blue corner wash (~5%) + ghost italic `WINNERS` ~72px @3.5%. Losers below, red wash + ghost `LOSERS`. Grand Final: centered ~300px column, gold washes both corners, ghost `GF`, 1px `color-mix(gold 30%, line)` frame + gold top seam, round label in the molten `.vs-hero` gradient at 20px; `BRACKET RESET` renders beneath only when non-void (filter exists :3947). Colored `.tny-blabel`s die.
- **Broadcast round keys** (pure fn, computed from the end): `WINNERS FINAL` / `WINNERS SEMIS` / `WINNERS · ROUND N`, same for losers, `GRAND FINAL` / `BRACKET RESET`. Skewed rail-cut chips, 22px, text un-skewed; the round containing a `ready|live` match gets a 3px gold edge + gold text; finals keys gold, others faint.
- **Card v2** (256w, slots 38h, keeps gs-109 slot plates + `--pa` accents :3975):
  - **Score is always a cell** — right-aligned 17px/900 italic tabular per slot: live = running score for everyone (`match_update` :3906 + `TNY.live` for your own), pre = em-dash, done = winner gold / loser dim. **Score flash**: in `tnyApplyDelta` `match_update`, a changed score gets `.scored` for 900ms — one gold flash-and-settle (4 lines).
  - **Loser slot drops to 55% opacity** (accent to 1px) — a completed bracket scans without reading checkmarks.
  - **Live pulse**: pulsing 8px dot replaces the READY pill + border animating line↔live at 1.8s. READY stays static gold.
  - **Your-match spotlight**: `.mine` = 2px gold outline + outer glow + 1.02 scale; the 10px corner micro-JOIN (:3990–3993) becomes a **full-width 24px bottom action strip** — molten `▶ JOIN YOUR MATCH` / outline `HOST MY MATCH` / red `● IN MATCH 1–1` / dim `⏳ WAITING ON HOST`, driven by the untouched `tnyHostState` switch. `scrollIntoView({block:'center'})` once per `state:matchId` stamp (the `TNY._yup` pattern — never re-scroll on the tick).
  - Pending slots dashed + faint; byes collapse to 24px; on-stream = skewed `ON STREAM` cut tag + 2px gold top edge.
  - **Auto-focus**: each section scrolls its `.tny-bcols` to the first non-done round on render + scroll-snap per column. No SVG connectors, no minimap — budget goes to cards.
- **GF-live strip (all audiences):** when a grand/reset match is live, the strip above the stage shows both plates + running score in 26px tabular + `GRAND FINAL` rail label + `Watch` cut. Advantage microcopy (`<name> holds the advantage — <name> must win two sets`) as polish.

## 4. PLAYER FLOW — one home per moment

| Moment | Home | Change |
|---|---|---|
| Register | Lobby card / hero gold CTA | as shipped (:3469) |
| Check-in | Hero CTA flips gold on `status` delta (full repaint :3922); ticker shows quiet `✓ Checked in — waiting on the bracket` after | styling only |
| **You're up** | **THE TICKER** — `#tnyAlert` under the hero, now `position:sticky; top:0` — rebuilt as a mini VS-banner: your plate (tier `--pa`) colliding with opponent's plate (`.h2h-pl` recipe verbatim), molten `VS` seam, round key above, ONE gold cut right. **Six-state machine + copy + beep stamp (:3614–3656) untouched — CSS/markup shape only.** New "on deck" state: seated vs TBD → amber `⏭ On deck — you play the winner of <from-label>` (from `p1_from`/`p2_from`, zero new data). | |
| Join | Ticker cut + card action strip + modal — all `tnyJoin` (:3805–3816), untouched | one visual grammar: JOIN=gold fill · HOST=gold outline · WAIT=dim spinner · IN MATCH=red fill, everywhere |
| Report | Auto-report daemon (:3788) primary; ticker `inmatch` state gains ghost `Report ▸` opening the existing modal buttons (:4069–4074); on `done`, ticker plays the payoff for 10s: `✓ 3–1 — you advance to LOSERS FINAL` / `eliminated — final placement #5` (derivable) | |

**Players board** (Entrants + Standings merged, one renderer + `phase` flag): pre-bracket `SEED · PLAYER · RANK · STATUS` (+ TO row actions gated exactly as :3580) → morphs to `PLACE · PLAYER · RANK · W–L · STATUS` using the standings reducer (:3548–3551); your row `.me` gold-inset + pinned, champion `.r1`, eliminated dim, top-3 as small plates above the rows post-completion. Players browse here; they never act here.

## 5. TO FLOW — a control layer, not a place

- **Pre-bracket: SETUP CHECKLIST** card in the CC slot (TO-only): `1 SEED (ELO · Shuffle) → 2 CHECK-IN (Open · Close · Finalize) → 3 START BRACKET ▶` (disabled until ≥2 checked in, tooltip says why); steps light gold as satisfied. Same `data-act`s as today — relocated, not duplicated.
- **Running: COMMAND STRIP** (upgrade of :3674–3687): dense rows `round key · A vs B (mini names) · state pill · 📣 CALL · 📺 · [MANAGE ▸]` — CALL fires the existing live:on alert, MANAGE opens the shipped modal (report/assign/undo :4076+, untouched). Cap 6 + "N more". Done matches linger 60s with a single `↩ UNDO` — the anti-misreport valve. Header: `COMMAND · 3 READY · 1 LIVE · ●● 2 stations` (station dots; click → drawer). Stationed-gate (:3666) folds in as the strip's top row.
- **Non-TO branch of the same renderer** = read-only "NOW PLAYING" strip (live matches only, clickable to tale-of-the-tape) — the spectator's stage; upgrades to the GF-live strip when grands are on.
- **ADMIN DRAWER** (gear cut, TO-gated, existing `.drawer` chassis, 440px right slide): Seeding · Check-in controls (mirror of checklist) · Add entrant · **Hosts** (enroll this PC / add by SteamID / remove / online dots — `tnyRenderHosts` TO branch relocates; heartbeat wiring :3721+ is location-independent) · Links · Danger zone with the type-the-name delete **verbatim** (:3473 comment exists because a live event got wiped). Admin tab and Stations tab both die.

## 6. CHAMPION MOMENT

On `bracket.champion` (SSE :3914), the ticker/strip region renders **THE PODIUM STAGE** (~200px, replaces the dead one-line banner): gold washes + skewed seams top/bottom, ghost italic `CHAMPION` @4%, confetti-free — the gold is the celebration. Center: champion mega-plate (`.ses-pl` recipe + `.ses-crown`, avatar 72, name 24px/900 italic, badge + flag, event line `5–1 · Seed 3 · def. Duc in Grand Finals` from the standings reducer + GF match). Flanking @82%: 2nd (GF loser) and 3rd (losers-final loser), silver/bronze edges, ghost placement digits. Below: `⧉ COPY RESULT` ghost cut → clipboard text block (event, top 3, W–L, date) — the shareable seed, same composition the Set Result victory card and future share pages plug into. The fact travels: hero CHAMPION stop, Players board `.r1`, lobby results row. GF win-pip row = polish.

## 7. FINAL PAGE STRUCTURE + ARENA-BAR SLICE

| Old tab | Verdict | Where the job went |
|---|---|---|
| Overview | **DEAD** | hero (identity/lifecycle/story line) + RULES modal |
| Bracket | **THE STAGE** (default when bracket exists) | — |
| Entrants | **MERGED** → Players board (pre-bracket face) | |
| Standings | **MERGED** → Players board (running/done face) | |
| Stations & Stream | **DEAD** | TO: drawer + strip dots · players: ticker/card/modal states (already flow) |
| Admin | **DEAD as tab, alive as DRAWER** (TO-gated) | hero/bar gear cut |

**Arena bar slice** (gs-113 lbTabs precedent :1110): entering detail sets `body.tab-tourney-detail`; the bar's middle = `‹ EVENTS back-cut · event name 13px/800 (22ch ellipsis) · [BRACKET | PLAYERS] SF6 cuts (active = molten gold, count pills un-skewed) · ⚙ gear cut (TO) · status pill`. Lobby state = `region ▾ · ＋ CREATE gold cut`. `#tnySub` (:1553) + underline `.tny-subtab` CSS (:842) die; `secOf` (:3527) collapses to the two-view switch; **`tnyRepaint`'s `TNY.sub` branches (:3865–3867) update in the same edit** or SSE repaints go dark. Skeleton slims to `tnyDetailHead / tnyAlert / tnyCC / tnyBracket / tnyPlayers / tnyEmpty` + drawer (`tnyTeamBar`/`tnyChamp`/`tnyGate`/`tnyOverview`/`tnyHosts`/`tnyStandings`/`tnyAdmin` containers die or fold). ONE control row app-wide, no exceptions.

**Global motion rule:** every pulse/slam/sweep wrapped in `@media (prefers-reduced-motion: no-preference)`; fallback = static edges + fades.

## 8. ANNOTATED LAYOUT (event page, running, 1280w / content 1180px)

```
ARENA BAR — 48px ───────────────────────────────────────────────────────────────
[🎮][🏆][🏟▮]  ‹ EVENTS · NOBD WEEKLY #12 · [BRACKET▮][PLAYERS 14] · ⚙  ●LIVE

EVENT HERO — ~230px ────────────────────────────────────────────────────────────
banner 120px: img + scanlines · ghost EVENT NAME 56-64px @4% · corner washes
              · gold seam lip (skew −9°)
identity 76px: TITLE 26/900 italic   REG─●CHECK-IN─●BRACKET─○CHAMPION (rail)
               meta rail-pairs                    [role chip][ ONE GOLD CTA 40px ]
story 28px:  ⚔ WINNERS SEMIS · 14/31 played · 3 live ▓▓▓▓▓░░ · LIVE NOW: A vs B ▸

TICKER — sticky top, 0 or 64px (tick-rebuilt; markup lives in the render fn) ───
▌my plate −6°▐ ⟨VS molten⟩ ▌opp plate▐  "lobby ready"   [ ▶ JOIN YOUR MATCH gold ]
  …or GF-LIVE strip (everyone): [plate] 2–1 26px tab [plate] [WATCH]
  …or PODIUM STAGE ~200px on champion

COMMAND STRIP (TO) / NOW PLAYING (all) — 0 or 40px/row, cap 6 ─────────────────
COMMAND · 3 READY · 1 LIVE · ●●2 stations                          [collapse ▾]
WINNERS FINAL   Duc vs JFRESH   ●LIVE   📣  📺   [ MANAGE ▸ ]      (↩ UNDO 60s)

STAGE — fills ──────────────────────────────────────────────────────────────────
BRACKET: WINNERS (blue wash, ghost 72px) → rounds = 260px cols, h-scroll+snap,
  auto-focused; cards 256×~104: [▌4px acc][seed][av20][badge13][flag][name…][score 17px]
  live = pulse dot + animated border · done = gold W / loser 55% · .mine = glow +
  full-width action strip 24px · skewed gold seam · LOSERS (red wash) ·
  GRAND FINAL centered 300px col, gold frame, molten label, RESET only when real
PLAYERS: .board 44px rows  SEED|PLAYER|RANK|STATUS → PLACE|PLAYER|RANK|W–L|STATUS

ADMIN DRAWER — 440px right slide (TO): Seeding / Check-in / Add entrant / Hosts /
  Links / Danger (type-name delete verbatim)
```

---

# DESIGN-LEAD SUMMARY

**(a) Tournament-lobby composition:** MARQUEE (live/your event, ~148px arena surface, one gold ENTER) → `rail-lab` + region select + CREATE in the bar slice → UPCOMING & OPEN card grid (status accent edges, corner-cut chips, ticket-stub dates, next-thing footers) → RESULTS line-list (champion inline when the payload has it). Status filter dead; rails encode it.

**(b) Event page top-to-bottom:** arena bar w/ contextual slice 48px → hero ~230px (banner 120 w/ event-name ghost + seam lip; identity 76 w/ lifecycle rail + one gold CTA; story line 28 w/ fill bar) → sticky ticker 0/64px (VS plates, six-state machine verbatim; also GF-live strip / podium stage ~200px) → command strip (TO) / now-playing (all) 0–120px → stage fills (bracket washes+seam+GF frame, or Players board 44px rows) → 440px admin drawer.

**(c) Final structure:** Bracket + Players (morphing Entrants/Standings board) as bar-slice cuts; Overview, Stations, Standings, Entrants, Admin tabs all dead; Admin lives as the TO-gated drawer; `#tnySub` row deleted; `tnyRepaint`/`secOf` updated in the same edit.

**(d) Bracket-card final design:** 256w unskewed card, skewed chrome; two 38h slot plates (4px tier accent, seed, 20px avatar, badge, flag, name) + always-on 17px/900 italic tabular score cell (gold winner, flash-on-delta); loser slot 55%; live = pulse dot + animated border; on-stream = skewed cut tag + gold top edge; pending dashed, byes 24px; `.mine` = gold glow + 1.02 + full-width 24px molten action strip driven by the untouched host-state machine + once-per-stamp center scroll; GF at ~300px in a gold frame.

**(e) Priority build list (~16h in 2 days):**
MUST — 1. Tab kill → two-view switch + bar slice + skeleton slim + `tnyRepaint` fix (2.5h) · 2. Players board merge (1.5h) · 3. Hero rebuild: ghost name, lifecycle rail, story line + bar, one-CTA, rules→modal (2h) · 4. Admin drawer w/ relocated hosts (1.5h) · 5. Bracket scenery: washes, ghosts, round-key fn, GF frame, auto-focus (1.5h) · 6. Card v2: score cells, loser dim, live pulse, action strip, spotlight scroll, score flash (2h) · 7. Sticky VS ticker restyle + on-deck state (1.5h) · 8. Command strip rows + checklist + gate fold + inline CALL/📺 (1.5h) · 9. Podium stage + copy-result (1h) · 10. Lobby marquee + rails + card v2 (1.5h).
POLISH (cut in order if squeezed): you're-up full takeover · sticky mini-header (IntersectionObserver) · FLIP standings reorder · GF advantage microcopy · undo-linger row · GF win pips · done-card champions · scroll-snap. Reduced-motion guards ship inside each MUST item, not as a pass. Each item ships alone: gs-N bump + `stage-frontend.mjs` + `node --check`; never touch the host machine, auto-report daemon, delete guard, or SSE applier — presentation only, all markup inside render fns (tick-rebuild discipline).

**(f) Mockup artboards:** 1. **Event page, running state** (hero + lifecycle rail + sticky ticker + command strip + winners/losers/GF stage) — the money shot; 2. **Bracket-card state sheet** (pending / ready / live / done / .mine ×4 host states / on-stream / GF at scale) — the engineer's contract; 3. **Tournament lobby** (marquee + rails + card v2 + bar slice); 4. **The payoff pair** — champion podium stage + the you're-up VS ticker/takeover on one board (the two emotional peaks, and the share-page seed).

---

# SEASONS — OWNER-APPROVED PLAN (2026-08-19)

- LENGTH: 2 months per season (6/yr, Valorant act cadence). Season Zero = current Open Beta (open-ended,
  ends at stable release); Season 1 starts at stable.
- NAMES (MvC2 mechanics, sequential): S1 SNAPBACK, S2 CROSSOVER, S3 ASSIST ME, S4 HYPER COMBO,
  S5 TEAM AERIAL, S6 DELAYED HYPER, S7 INFINITE, S8 OTG. Each season: accent color + badge glyph.
- MECHANICS: lifetime ELO remains the spine (NO hard resets — 100-player pool). A season is a TIME WINDOW:
  seasonal boards reuse the windowed-leaderboard mechanism (day/week/month → season range); add season +/-
  ELO stat. Placement gate applies per season for seasonal boards.
- SEASON END (automated): server snapshot per player {season_id, name, tier_at_end, rating_at_end,
  placement, wins, losses} appended to an additive seasons[] on the Player record → SEASON BADGES render
  as a shelf on the profile fighter card + feed the future Card Editor earned titles. Champion (=#1 rating)
  gets a gold season title.
- AUTOMATION: skinsync seasons.json [{id,name,start_ms,end_ms,accent}]; boot + daily tick: if now>end &&
  !snapshotted -> snapshot + award + auto-append next season from the name list (2-month window).
  New endpoint GET /skinsync/season -> {id,name,accent,ends_ms,days_left} consumed by the Rankings
  masthead rail line (SEASON 1 - SNAPBACK - ends in 23d).
- BUILD: server ~4-5h (config+snapshot+endpoint+tests), client ~2h (masthead line, profile badge shelf,
  seasonal board period cut "Season"). Schedule: after the Arena Bar + Stage ship.


## SEASONS — ON-CHAIN PERMANENCE (owner directive 2026-08-19: "end of season gets minted to be forever")
DESIGN (recommended): **season-end ATTESTATION, not player NFTs.** At snapshot time the server produces the
canonical season file (standings, tiers, champion, W/L, hash of every match id in the window), publishes it
at nobd.net/seasons/<id>.json, computes its sha256, and anchors that hash on-chain in ONE cheap tx
(Base/OP L2, ~<$0.01, server-held wallet w/ a few dollars; EAS attestation or raw calldata). Anyone can
verify forever: hash(file) == chain record, timestamped. Zero player wallets, zero gas for users.
UI: season badge shelf gets a small ⛓ "etched on-chain" mark linking to the tx + file.
⚠ COMMUNITY RISK (be deliberate): the FGC is historically NFT-hostile — frame as ARCHIVAL PROOF
("season results are carved in stone"), never as NFTs/crypto. Player-claimable badge NFTs = OPT-IN maybe
later, never default. Build: ~3-4h on top of the season snapshot job (wallet setup + anchor script + verify
endpoint + UI mark).