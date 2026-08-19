# MetaSync Design System — "THE ARENA" (the design bible)

The UI/UX authority for MetaSync. Every new surface, modal, or component follows this document.
Full decision history + per-surface specs: `docs/UI-REDESIGN-SPEC.md`. Mockups: the "MetaSync Redesign"
canvas artifact. Owner-locked decisions are marked ⭐.

## Identity
FGC competitive app (tournaments / stats / rankings / skins) for MvC2. The register is a **fighting-game
broadcast**, not a SaaS dashboard: think EVO overlays, SF6 menus, Valorant-tracker stat hierarchy.
⭐ Standing directive: **less is more** — every element earns its place; one fact, one home.

## Tokens
`--bg #0d1017 · --panel #12151d · --panel-2 #161a24 · --line #2a3140 · --ink #e8ecf2 · --dim #9aa4b2 ·
--faint #6b7488 · --gold #e8b93c · --gold-ink #241700 · good #3ddc84/#4ade80 · red corner rgba(214,31,60,x) ·
blue corner rgba(74,168,255,x)`. Font: system-ui stack; numerals ALWAYS `font-variant-numeric:tabular-nums`
(mono family for scores/ratings). Type scale: 10 rail · 11.5 micro · 13.5 body/names · 15–17 emphasis ·
20+ heroes (one numeric hero per page max).

## The vocabulary (use these, never invent parallels)
- **Plate**: `transform:skewX(-6..-8deg)`, children counter-skewed; 3–4px accent edge (`border-left`, or
  `border-right`/`border-top` mirrored); wash `linear-gradient(120deg, color-mix(in srgb, var(--pa) 14%,
  transparent), transparent 70%)` over `--panel-2`; accent vars `--pa/--pb` = **skin colors** (paintPlate/
  skinAccent) when the player has one, else **tier colors** (RK_PLATE map). Used by: scoreboard, podium,
  profile hero, set-result card, region hero, h2h.
- **Cut**: SF6 parallelogram button, `skewX(-12..-14deg)`; active = molten gold
  `linear-gradient(180deg,#ffe084,#c98f0e)` + `--gold-ink` text + italic; inactive = dim, often icon-only.
- **Arena surface**: red wash from the left corner + blue wash from the right (≈7–10% alpha), a **skewed
  gold seam** divider, and a **ghost watermark** — giant italic 900 text at 3.5–5% opacity naming the place.
- **Rail label**: 10px/700/caps/.16em `--faint`. Section headers are rails, never big type.
- **Board**: dense columnar table (`.bd-*`), 44px rows, sticky 32px head, `.me` gold-inset row, color-coded
  win% (≥60 green / ≥45 lime / else orange). ⚠ scope `display:block` — global `.board` is the Match grid.
- **Pills**: 10px caps state pills (gold=yours/champion, green=verified/live-good, red=live-hot).
- **Badges**: Marvel rank sprite `#rk-civilian…#rk-galactus` + `.rk-*` text colors; render via
  rankOf/rkBadge/rkTag/rkInline/rkB (client derives tier from rating+games — never trust a server string).
- **Icons**: stroke SVG symbols `#ic-*` on currentColor. NEVER raw emoji for stat icons (flags 🇺🇸 and a few
  brand emoji in copy are fine).
- **Empty states**: dashed border + action-inviting copy. Never dead placeholders.

## Hard rules
1. ⭐ **ONE bar**: the arena bar (gs-115) is the only global chrome — brand cab, cut tabs (inactive collapse
   to icons), gold seam, ONE contextual slice per page, utility cluster right. Never a second control row.
2. **Gold budget**: gold = yours / first / the one primary action. Amber = #rcBanner only, app-wide.
3. **Accent discipline**: per-board/per-season accents appear only in ≤20px slivers (underline, unit label,
   active cut). Player plates stay tier/skin-colored.
4. **Identity appears once per page** (the header meCard is the global echo).
5. **Ghost watermarks name the place**; they are always ≤5% opacity, italic 900, never interactive.
6. **Debug/dev chrome** hides behind `body.debug` (triple-click the state pill).

## Implementation guardrails (this codebase)
- Single file `web/index.html`; ship gate after EVERY change: `node src-tauri/stage-frontend.mjs` must print
  "parse cleanly". Bump the `gs-N` comment tag. Edit tool only — never shell string edits.
- ⚠ Unguarded DOM fills: some legacy `$('#id').x=` writes have no null guard — removing an element they fill
  throws in the 4s tick loop. Park such ids in `#legacySinks` (hidden) until a cleanup pass strips the writes.
- Tick-rebuilt surfaces (`setOpp` 4s, `tnyAlert` 1.2s, SSE `tnyApplyDelta`, renderDetail) accept NO one-shot
  DOM edits — state must be cached (e.g. `_oppRep`) and re-applied in the renderer.
- Keep element ids stable across restyles; JS fill-sites map to ids, not classes.
- Respect `prefers-reduced-motion` for any animation; flashes ≤900ms, pulses ≥1.8s.

## Current state / roadmap
Shipped in tree: Marvel ladder + badges, Player-Plates scoreboard (Option D ⭐), Rankings broadcast board,
fighter-card profile, Set-Result victory card, arena bar (Nav G ⭐, gs-115), Regions inside Rankings,
Library locker pills. Specs approved & pending build: **Rankings Marvel-Ladder masthead** (your plate left,
channel rail, podiums everywhere, tier cutlines + unclaimed Galactus line), **Tournament "The Stage"**
(Bracket+Players+Admin drawer, lifecycle-rail hero, arena-corner brackets, score-cell cards), **Seasons**
(2-month, MvC2-mechanic names, automated snapshots + season badges — see UI-REDESIGN-SPEC §Seasons).
Future: Card Editor (earned titles/plate gradients), shareable card pages on nobd.net.
