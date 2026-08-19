# Real-time bus — deferred work + handoff notes (2026-08-19)

Context: the real-time push bus is shipped and live (see `docs/TOURNAMENT-REALTIME-ARCH.md` §AS-BUILT). Channels live: `tourney.{id}`, `leaderboard`, `presence`, `matches` (results + now-playing). Client through **0.1.100**. This file tracks what's NOT done yet + a hard gotcha.

## ⚠⚠ CRITICAL GOTCHA — concurrent editing of `web/index.html`
During the 0.1.99→0.1.100 work the **user was actively editing `web/index.html` in their own editor (VSCode) at the same time as agents**. Their editor's saves repeatedly **overwrote on-disk agent edits** — the app-wide `matches` subscribe was reverted twice, and the **entire Increment-4 profile current-match feature was wiped** (all of `pfCurMatchHtml`/`pfLiveSid`/`pfLiveMatchDelta`/`cmDuration`/`.pfx-live` → 0 occurrences after a save).

**Rule for any future agent touching `web/index.html`:** confirm the user is NOT editing it in an editor before you make changes, OR you WILL get clobbered on their next save (and you may clobber their redesign). One writer at a time. If in doubt, ask the user to close the file, make your changes, build, and hand it back. Server files (`skinsync/src/*`, `push-gateway/*`, `src-tauri/src/*.rs`) were NOT affected — only `web/index.html`, which the user's UI-redesign work lives in.

## Deferred #1 — Profile "🟢 Current match — vs X" (Increment 4)
The user asked: opening a player's profile should show their live in-match status. **Server code is DONE and on disk; client code was written then clobbered and must be re-applied.**

- **SERVER (done, on disk in `skinsync/src`, NOT yet deployed):**
  - `App::active_match_for(&self, steamid) -> Option<&ActiveMatch>` in `app.rs` (scans `active_matches` for the pair containing the id).
  - `GET /skinsync/profile?steamid=…` (`stats::profile`) returns an additive `current_match` field: `null`, or `{opp, opp_name, since, my_chars, opp_chars}` (opp = the other sorted player; `since` = `last_seen_ms`). Purely additive; 55 tests pass.
  - ⚠ This is committed to the Windows `skinsync/src` tree but **NOT deployed to the VPS** (I held the deploy to avoid another restart). Deploy it (build on VPS + atomic-mv swap, per `docs/SERVER-DEPLOY-HANDOVER.md`) when the client is re-applied.
- **CLIENT (must be RE-APPLIED — was clobbered):** in `web/index.html`, in `openProfile`'s render, show the current-match line from `p.current_match` (HTTP snapshot on open — a correct one-shot read), then update it **purely via push** (NO polling — this is a hard requirement the user enforced):
  - Render helper `pfCurMatchHtml(cm)` → the `🟢 Current match — vs {opp_name}` banner (reuse `--good`/`--live` vars + the `lrpulse`/`lr-dot` pulse); empty string when `cm` is null. Opp name clickable → `openProfile(opp)` when opp is a 17-digit id.
  - An always-present `<div id="pfLiveSlot">` anchor in the modal so the push handler can patch just that line.
  - Track the open profile's sid in a module var `pfLiveSid` (set after render, cleared on modal close / `openProfile` re-entry / `openSession`).
  - Add `pfLiveMatchDelta(d)` and call it as the FIRST line of `rtMatchesApply(d)` (which runs on every `matches` delta): if `pfLiveSid` is in `d.players` (match_start) → set `#pfLiveSlot` to the banner; if `pfLiveSid` in `d.players` (match_end) or is `d.winner`/`d.loser` (match_result) → clear `#pfLiveSlot`.
  - **`matches` is already an app-wide subscription** (subscribed once at boot next to `rtSubscribe('presence')`; NOT in `rtRanksEnter`/`rtRanksLeave` anymore), so the profile just reacts to the shared stream. Do NOT re-add matches to the Ranks enter/leave.

## Deferred #2 — Move 🔴 Live Results + 🟢 Now Playing to the Match tab
User decision: the feeds should live on the **Match tab** (`#p-match`), not the Rankings tab (`#p-ranks`) where they compete with the leaderboard. Not done because it's markup surgery inside the section the user is actively redesigning (see the gotcha).
- Move the `<div class="lr-feed" id="lrFeed">…</div>` block (Live Results + Now Playing markup) from inside `#p-ranks` `.lb-wrap` to a stable spot in `#p-match` (e.g. just before the `#banner` div at the end of `#p-match`).
- Update CSS: the feed styles are scoped `#p-ranks .lr-feed` / `#p-ranks .lr-*` / `.np-*` — re-scope to `#p-match` (or unscope).
- Repoint render hooks: `rtMatchesRender()`/`npRender()` + the 30s `RT.lrTimer` (relative-time tick) currently fire in `rtRanksEnter` and gate on `$('#p-ranks').classList.contains('on')` — move those to fire on Match-tab entry (add to `switchTab`'s `t==='match'` path; Match is the default tab so it also renders on load) and change the timer's gate to `#p-match`. Leave the `leaderboard` channel + the 60s `RT.lbTimer` board-refetch on the Ranks tab (the board only needs refetching while it's being viewed).
- `matches` stays app-wide (already), so the feed data is populated regardless of which tab is active.

## Already-shipped fix (0.1.100), for reference
The leaderboard "LEADERBOARD UNAVAILABLE" flicker: `renderLeaderboard`'s catch used to wipe the whole board on ANY fetch failure. Fixed to keep-last-good — only shows UNAVAILABLE on a cold load with nothing on screen (`if(!list.querySelector('.board')&&!list.querySelector('.podium'))`). Root trigger was the ~2s skinsync restart windows during the increment deploys.
