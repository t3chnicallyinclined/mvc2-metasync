# MetaSync portable rewrite — what's next (2026-08-19)

State of the PWA session (`rewrite/portable-web-agent`, worktree `metasync-rewrite`). The **web app is
feature-complete and live at nobd.net/app**; this is the forward plan, ordered by what unblocks what.

## ✅ Done (live at nobd.net/app, all on this branch, tip `20cadb5`)
- Full read/social app: Ranks, Match (live feed), Tournament (browse + live detail), Regions, Library
  (team tier list), Profiles (stats, mode chips, per-mode records, Rivalries).
- Steam sign-in (OpenID, persistent). Signed-in actions: tournament register/check-in/unregister, profile
  lobby-visibility toggle.
- Settings page: account, theme toggle (Dark default / Light / Auto), install prompt, agent placeholder.
- Mobile-hardened + audited 320→1024px (ox=0 everywhere), iOS input-zoom/dvh/safe-area fixed.
- Design spec for Phase 3: `docs/PHASE3-LOWLATENCY-ARCH.md`.

## 🔴 Blocked on the 0.2.5 desktop release merge (do NOT start until it lands)
The tray agent lifts `src-tauri/src/sync.rs`/`mem.rs`/`lib.rs` verbatim — those files are owned by
`nobd-arcade` + `season-ledger` and are merging into `release-0.2.5` right now. Starting now = collide with
the release + port a moving target. **After 0.2.5 merges to main:**
1. **Extract a shared `core` crate** from `src-tauri/` (reader/painter/`mem`) so there's ONE copy of the RE,
   used by both the (retiring) Tauri app and the new tray binary. Do this off the stable post-merge `sync.rs`.
2. **Build the tray agent** per `PHASE3-LOWLATENCY-ARCH.md`: `tray-icon`+`tao`/`muda` shell (status / Open
   MetaSync / Quit + Run-key autostart), the cadence state machine, silent self-updater (`self-replace` +
   `minisign-verify` against the existing `latest.json`, apply only when no game running).

## 🟠 Blocked on server coordination (needs new endpoints; `metasync-srv` is multi-session — fetch + check
`git log origin/server-optimizations` before touching it)
3. **Phase 3 command protocol** (server): `POST /skinsync/skin/apply {char,skin}` + a per-user `cmd.{steamid}`
   channel; **gateway authz** so only your bearer can subscribe to your `cmd.*`/`state.*` (public read
   channels stay open). Then the agent SSE-subscribes + keeps a local pref cache + prefetches opponent skins
   at the netplay-pair edge.

## 🟢 Safe to do anytime (this branch, `app/`-only, zero conflict)
4. **Web skin picker / loadout** (`app/`): per-character skin selection, optimistic UI. Browsing is buildable
   now against `/skins/list`; *saving/applying* waits on the Phase 3 endpoints (#3). Can scaffold the UI now.
5. **Scope switcher** (Ranked / Lobby / Tournament boards) on Ranks — the server `?scope=` param is already
   live. ⚠ Match the desktop's final 0.2.5 scope UX, so do this **after** 0.2.5 freezes that design.
6. More PWA polish: notification prefs, richer empty/error states, a11y pass, tournament bracket rendering
   once a started bracket exists to test against.

## 🔵 Later (Phase 5)
7. Economy/QUARTERS on web, browser Studio (ROM bake in-browser), Web Push, ledger money fixes
   (settle-on-verified, two-phase transfers, fail-closed TB, closed-loop quarters).

## Coordination notes
- **This branch is excluded from 0.2.5** (per `metasync-server/docs/RELEASE-0.2.5-HANDOVER.md` — PWA is a
  separate artifact/deploy). Don't merge it into `release-0.2.5`.
- **Server:** my `/playerstats` tie-break fix is `730557b` on `server-optimizations`; a newer session commit
  (`d379c77`) landed on top — confirm the fix is included in whatever server build ships next.
- **Deploy the PWA:** `MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*" BASE_PATH=/app npm run build` →
  `tar czf - -C build . | ssh root@nobd.net 'tar xzf - -C /var/www/metasync-app/app'`. nginx `^~ /app/`.
