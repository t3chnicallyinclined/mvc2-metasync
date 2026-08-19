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