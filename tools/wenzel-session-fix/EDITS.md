# Fix #2 — union sibling sessions in the set-card views (display-only, no SSOT write)

**What it fixes:** a single physical set can bind to TWO client-minted `session_id`s
(`s_<self>_<opp>_<ts>`, one per reporter) because the server keeps the FIRST non-empty report's
id per game (`routes.rs` session grouping). A per-game report-arrival race then scatters the set
across two ids, and the set-card readers filter on the exact id string, so a shared card shows
only the subset that won the race. Live example: `/s/1a0555f2765` shows Wenzel 8-0 when the
real set is 9-1 (Tris's win, match_index 2, lives under the other client's id).

**Approach:** a shared helper `stats::merged_session_ids(app, sid)` returns every `session_id`
that belongs to the same physical set. A sibling id is folded in ONLY when it is
(a) the same unordered player pair, (b) the same mode, (c) match_index-disjoint from the
set so far, and (d) time-adjacent (`<= SET_MERGE_GAP_MS`). The two readers call it instead of
comparing the raw id.

**Blast radius is exactly 2 filter sites + 1 new helper.** `ogimg.rs` (the PNG fight card) and the
in-app set modal both flow through `stats::session_stats`, so fixing that one function fixes the
`/skinsync/session` endpoint, the in-app SessionModal, AND the rendered OG image. `og_preview`
(the OG HTML title/meta) has its own inline filter and is fixed separately. Verified via
`rg session_id server/src` that no other set aggregation exists.

---

## Time-gap threshold: SET_MERGE_GAP_MS = 20 * 60 * 1000 (20 minutes)

Chosen from the actual data. In this set the inter-game report gaps are ~100-150s
(game + character-select + reload). 20 min of slack keeps even a slow set whole (bathroom break,
chat between games) while staying far below the gap to a fresh sit-down rematch.

The time gap is a belt-and-suspenders, not the primary guard. The primary guard is
match_index-disjointness: a genuinely separate later set ALSO restarts numbering at match_index 0,
so its indices collide with the anchor's index 0 and it is rejected regardless of timing. Even two
back-to-back sets stay separate because set 2 restarts at index 0. The time gap only additionally
prevents a merge across a long break where indices happen not to clash.

---

## EDIT 1 — server/src/stats.rs

Single find/replace, anchored on the doc-comment + session_stats signature + the filter/sort
lines (currently ~lines 15-20). It inserts the const + helper ABOVE session_stats and swaps the
exact-id filter for the merged-id filter.

### OLD (find this exact block)

```rust
// One ranked set's breakdown: every game in `session_id` (ordered by match_index) + each participant's W-L for
// the set. Reads the match log directly (session_id is stored on every MatchLog). Public so a set can be shared.
pub(crate) fn session_stats(app: &App, sid: &str) -> Value {
    if sid.is_empty() || sid.len() > 80 { return json!({"ok": false, "error": "bad session id"}); }
    let mut games: Vec<&MatchLog> = app.matches.iter().filter(|m| m.session_id == sid).collect();
    games.sort_by_key(|m| m.match_index);
```

### NEW (replace with this exact block)

```rust
/// The wall-clock gap (ms) two fragments may sit apart and still count as ONE physical set. Observed
/// in-set inter-game gaps run ~100-150s (game + char-select + reload); 20 min of slack keeps even a slow
/// set whole while a genuinely separate later rematch stays out. NOTE the disjoint-match_index guard below
/// is the PRIMARY protection (a separate set ALSO restarts at match_index 0 -> its indices collide -> it is
/// rejected regardless); this gap only stops a merge across a long break where indices happen not to clash.
const SET_MERGE_GAP_MS: u64 = 20 * 60 * 1000;

/// SESSION-FRAGMENTATION REPAIR (display-only — no matches.json write). A single physical set can land
/// under TWO session ids: each client mints its own `s_<self>_<opp>_<ts>` and the server binds the FIRST
/// non-empty report's id per game (routes.rs session grouping), so a per-game report-arrival race scatters
/// the set across ids. Given one session id, return EVERY session id that belongs to the same physical set,
/// so a set card shows ALL the games — not just the subset that won the id race. A sibling session is folded
/// in only when it is (a) the SAME unordered player pair, (b) the SAME mode, (c) match_index-DISJOINT from
/// the set so far, and (d) time-adjacent (<= SET_MERGE_GAP_MS from the set's span). Unknown/empty session ->
/// just `sid` (never fewer games than before).
pub(crate) fn merged_session_ids(app: &App, sid: &str) -> Vec<String> {
    let anchor: Vec<&MatchLog> = app.matches.iter().filter(|m| m.session_id == sid).collect();
    if anchor.is_empty() {
        return vec![sid.to_string()];
    }
    // unordered pair + mode of the anchor set (consistent across a real set; take the first game's)
    let pair = { let mut p = [anchor[0].winner.clone(), anchor[0].loser.clone()]; p.sort(); p };
    let mode = anchor[0].mode();
    let same_set = |m: &MatchLog| {
        let mut p = [m.winner.clone(), m.loser.clone()];
        p.sort();
        p == pair && m.mode() == mode
    };
    // accumulated occupied match_index slots + wall-clock span of the set so far
    let mut ids: Vec<String> = vec![sid.to_string()];
    let mut idx: std::collections::HashSet<u32> = anchor.iter().map(|m| m.match_index).collect();
    let mut lo = anchor.iter().map(|m| m.ts).min().unwrap_or(0);
    let mut hi = anchor.iter().map(|m| m.ts).max().unwrap_or(0);
    // group every OTHER non-empty session that shares this pair + mode
    let mut cand: std::collections::HashMap<&str, Vec<&MatchLog>> = std::collections::HashMap::new();
    for m in &app.matches {
        if m.session_id.is_empty() || m.session_id == sid || !same_set(m) {
            continue;
        }
        cand.entry(m.session_id.as_str()).or_default().push(m);
    }
    // fold in siblings earliest-first, so the accumulated span/index set grows deterministically
    let mut cand: Vec<(&str, Vec<&MatchLog>)> = cand.into_iter().collect();
    cand.sort_by_key(|(_, g)| g.iter().map(|m| m.ts).min().unwrap_or(0));
    for (cid, games) in cand {
        let s_lo = games.iter().map(|m| m.ts).min().unwrap_or(0);
        let s_hi = games.iter().map(|m| m.ts).max().unwrap_or(0);
        let disjoint = games.iter().all(|m| !idx.contains(&m.match_index));
        let adjacent = s_lo <= hi.saturating_add(SET_MERGE_GAP_MS)
            && s_hi.saturating_add(SET_MERGE_GAP_MS) >= lo;
        if disjoint && adjacent {
            for m in &games {
                idx.insert(m.match_index);
            }
            lo = lo.min(s_lo);
            hi = hi.max(s_hi);
            ids.push(cid.to_string());
        }
    }
    ids
}

// One ranked set's breakdown: every game in the physical set (ordered by match_index) + each participant's
// W-L. Reads the match log directly, UNIONING fragmented session ids (merged_session_ids) so a set split
// across two client-minted ids still shows all its games. Public so a set can be shared.
pub(crate) fn session_stats(app: &App, sid: &str) -> Value {
    if sid.is_empty() || sid.len() > 80 { return json!({"ok": false, "error": "bad session id"}); }
    let ids = merged_session_ids(app, sid);
    let mut games: Vec<&MatchLog> = app.matches.iter().filter(|m| ids.contains(&m.session_id)).collect();
    games.sort_by_key(|m| m.match_index);
```

**Unchanged after this block:** everything from `let mut by_player` onward. The `players`
aggregation and `elo` sums are computed FROM `games`, so they become 9-1 automatically once the
list is unioned. The response still returns `"session_id": sid` (the card keeps its own identity/URL).

**No new imports needed:** `App`, `MatchLog`, `json!`, `Value` are already in scope; `HashSet`/`HashMap`
are fully path-qualified (matches the existing `std::collections::HashMap` style already in this file).

---

## EDIT 2 — server/src/routes.rs  (inside fn og_preview, the /app/r/set/ branch, ~line 2222)

### OLD (find this exact block)

```rust
        let sess = rest.split(['?', '/']).next().unwrap_or("");
        let games: Vec<&crate::models::MatchLog> =
            app.matches.iter().filter(|m| !sess.is_empty() && m.session_id == sess).collect();
```

### NEW (replace with this exact block)

```rust
        let sess = rest.split(['?', '/']).next().unwrap_or("");
        // union sibling session ids so a fragmented set (stats::merged_session_ids) unfurls with ALL
        // its games, not just the subset that won the per-game report-arrival race. (SSOT untouched.)
        let ids = if sess.is_empty() { Vec::new() } else { crate::stats::merged_session_ids(app, sess) };
        let games: Vec<&crate::models::MatchLog> =
            app.matches.iter().filter(|m| ids.contains(&m.session_id)).collect();
```

**Unchanged after this block:** the `if !games.is_empty() { ... }` body. `games[0]` is the
first-appended (chronologically earliest) merged game = match_index 0 = a Wenzel win, so the title
renders `Wenzel 9-1 TRIS NOBDOG`. The `aw`/`bw` counts are pair-symmetric, so the SCORE is correct
regardless of title order.

Borrow note: `merged_session_ids(app, sess)` takes `&App`, returns an owned `Vec<String>`, and its
borrow ends before the `app.matches.iter()` borrow begins — same borrow shape as today, and
`app.disp_name(...)` (called later while `games` is alive) is `&self`, so nothing changes there.

---

## Why this is safe against over-merging (the only real regression risk)

A count going UP is not a regression if it reflects real fragmentation. Over-merging (pulling a
DIFFERENT set's games into a card) is the risk, and three independent guards prevent it:

1. Same unordered pair — a card can only ever gain games between the exact two players.
2. Disjoint match_index — any other set restarts at index 0, colliding with the anchor's
   index 0/1/... -> rejected. This alone blocks merging two full separate sets, even back-to-back.
3. Time-adjacent (<= 20 min) — rejects a temporally distant rematch even in the rare case its
   surviving indices don't collide.

verify.sh (in this folder) asserts the universal over-merge invariant for ANY session id:
all games share one unordered pair AND no match_index repeats.
