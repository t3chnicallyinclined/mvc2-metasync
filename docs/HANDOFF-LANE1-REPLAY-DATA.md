# HAND-OFF → LANE 1 (`RetroReceipts-server`): the replay/credit data contracts, in execution order

**2026-09-03 · stack expert (SSOT / Redis / Surreal / R2), read-only on the server repo.** (Persisted verbatim by the
render lane from the expert's report; every struct/field/line below was read in `RetroReceipts-server/server/src`.)
Consolidates: `HANDOFF-LANE1-GS-MAX-BODY.md`, `HANDOFF-LANE1-TAPE-ARCHIVE.md` §2/§3/§6, `LIVE-TAB-SPEC.md` §11 (C1–C9),
`REPLAY-OVERLAY-SPEC.md` (C10–C15). Anything not confirmed in code is tagged **UNKNOWN**.

Nothing here makes a derived store authoritative, nothing adds an unbounded Redis key, and every byte-moving path is
specified to stay off the single request thread. **Read §0 before writing code** — it changes how steps 1 and 4 must be built.

## 0. Two facts about this server that shape steps 1 and 4

### 0.1 The request loop is strictly serial — a big body blocks everyone
`main.rs:201` is `for req in server.incoming_requests() { … handle(&mut app, req) … }`. One request at a time, no worker pool.

- **Uploads.** `http.rs:83 read_body_capped` does `req.as_reader().take(cap+1).read_to_string(&mut buf)` then
  `serde_json::from_str(&buf)`; `routes.rs:2325` then base64-decodes `frames_gz`. Raising `GS_MAX_BODY` to 64 MB makes the
  worst case ≈64 MB `String` + ≈64 MB parsed `Value` + ≈48 MB decoded `Vec<u8>` **live at once**, on the loop.
- **Downloads.** `http.rs:52 reply_bytes` builds a `Vec<u8>` and `req.respond(...)` writes it synchronously. Serving a
  3–14 MB tape to a slow client blocks the loop for the **entire transfer**. Tolerable today only because
  `GET /skinsync/gamestate/<id>` is admin-gated and rare (`routes.rs:999-1012`).

**Therefore:** step 1 ships a raw-body upload arm (no base64, no serde over the payload, streamed to disk); step 4 serves
tape bytes via **nginx `X-Accel-Redirect`**, not from the Rust process.

### 0.2 The R2 archive already exists — as rclone, not as an S3 client
`ops/r2-sync-gamestates.sh` runs `rclone copy "$GS_DIR" r2:mvc2-dataset/rr-gamestates --include '*.json.gz' --min-age 1m`
from cron every 10 min, upload-only, never deleting.

- The archive is a **flat prefix of `<match_key>_<reporter>.json.gz`**, not the `tapes/<session_id>/<match_key>.json.gz`
  layout the earlier hand-off proposed. **Do not reshape it** — the existing objects are the archive.
- Lane 1 needs **no S3/R2 crate and no credentials in the binary**. "Archived" comes from an index file the same cron writes;
  the pull is `rclone copy` spawned off-thread. `Cargo.toml` has no S3 dep and adding one is not recommended.
- **UNKNOWN:** whether the cron is installed on rise3 (the header says prereqs are satisfied on "this box", written
  pre-migration). `crontab -l | grep r2-sync-gamestates` before relying on `archived`.

## Execution order

| # | Step | Depends on |
|---|---|---|
| 1 | `GS_MAX_BODY` + raw-body tape upload | — |
| 2 | `wside`/`lside`/`p1`/`p2`/`reporter` on results + session games | — |
| 3 | Loadout provenance (`CharSkin` + vault author) | — |
| 4 | Tape index + authed read/request/archive | 1 |
| 5 | `replay` state + `{type:'tape'}` bus event | 4 |
| 6 | `TMatch.session_id` / `match_key` | — |
| 7 | Creator stats on `/rr/profile` | 3 |

---

# STEP 1 — `GS_MAX_BODY` and a raw-body tape upload (C4, BLOCKER)

**Store:** hot tape dir (`App.gamestates_dir`, `app.rs:68`) — a derived cache, capped/evicted by `enforce_gamestate_cap`
(`app.rs:1823`); R2 is its durable mirror. No SSOT change.

### 1A — the one-line unblock (no client change)

`config.rs:25`
```diff
-pub(crate) const GS_MAX_BODY: usize = 8 * 1024 * 1024;
+pub(crate) const GS_MAX_BODY: usize = 32 * 1024 * 1024; // v5 tapes are 3-14 MB gz = 4-19 MB base64
```
`receipt.rs:61` and `:107`
```diff
-    const TAPE_MAX_GZ: u64 = 3_000_000;
+    const TAPE_MAX_GZ: u64 = 16_000_000;
-    const REPLAY_MAX_GZ: u64 = 3_000_000;
+    const REPLAY_MAX_GZ: u64 = 16_000_000;
```
Recommend **32 MB, not 64 MB**. 64 MB is the *nginx* limit; matching it means holding ~64+64+48 MB simultaneously on the
serial loop. 32 MB covers a 24 MB gz tape at base64 inflation and halves the worst case.

⚠ **Second-order cost of 1A:** `receipt.rs:180` (`match_receipt`) reads and **gunzips up to 8 tapes inline** per receipt
GET; `receipt.rs:136` (`replay()`) gunzips one. At a 16 MB guard, one `GET /rr/receipt?id=…` can gunzip ~100 MB on the
request loop. Mitigate before raising `TAPE_MAX_GZ`: either have `tape_block` read metadata from the step-4 index
(preferred, drops the inline gunzip), or lower the per-receipt cap from 8 to 2 (`receipt.rs:191`, `if i < 8`).

### 1B — the raw-body arm (what the agent migrates to)
New route, placed **above** the existing `(Method::Post, "/skinsync/gamestate")` arm at `routes.rs:710`:
```
POST /rr/gamestate/raw?match_key=<key>&reporter=<sid>&frames=<n>&ver=<agent_ver>
Content-Type: application/gzip · Authorization: Bearer <token>
<body = the gzip bytes verbatim>   →  200 {"ok":true,"id":"<key>_<reporter>","bytes":N}
```
```rust
// auth + reporter==who + match_key exactly as handle_gamestate (routes.rs:2303-2320)
let path = std::path::Path::new(&app.gamestates_dir).join(format!("{id}.json.gz"));
let tmp  = format!("{}.tmp", path.to_string_lossy());
let mut f = std::fs::File::create(&tmp)?;
let n = std::io::copy(&mut req.as_reader().take(GS_MAX_BODY as u64 + 1), &mut f)?;
if n > GS_MAX_BODY as u64 { let _ = std::fs::remove_file(&tmp); return reply_json(req, 413, …); }
std::fs::rename(&tmp, &path)?;   // same atomic tmp+rename as handle_gamestate
```
Peak memory O(64 KB) instead of O(3×body); wire drops 33 %. The post-write work — `parse_gamestate_gz` →
`derive_true_winner` → `apply_correction_swap` → `tier3_autoconfirm` → duration stamp (`routes.rs:2352-2392`) — must be
factored into `fn ingest_tape(app: &mut App, match_key: &str, raw: &[u8])` and called from **both** arms; that logic
rewrites `matches.json`, so the two paths must never diverge.

⚠ `req.as_reader()` decodes chunked transfer but does **not** gunzip — which is what we want (gz bytes land verbatim).

**Content-Encoding: the recommendation is DON'T.** Send `Content-Type: application/gzip` with the raw gz as the entity.
`Content-Encoding: gzip` means "decode this to get the payload" — the server would then be obliged to gunzip and re-gzip
to store, and any intermediary is entitled to transparently decode it. **UNKNOWN:** nginx core has no request-body gunzip
module so today it would pass through, but that is inference — V1.3 settles it if lane 1 insists.

**Rate limit:** `routes.rs:276 TIGHT_WRITES` is an **exact-path** allowlist containing `"/skinsync/gamestate"`. Add
`"/skinsync/gamestate/raw"` (bump to `[&str; 5]`) or the new arm lands on the generous read bucket.

**Storage:** JSON SSOT untouched (the ingest can *correct* it — existing behavior). Disk: `GS_DIR_MAX_BYTES = 6 GB`
(`config.rs:27`) at 3–14 MB/tape ≈ 430–2000 tapes, **not** the 30 000 files `GS_DIR_MAX_FILES` assumes — bytes bind
first. Leave the caps. R2: the cron picks new files up automatically. Redis/Surreal: none.

**Compat:** agent 0.3.x keeps working on `POST /rr/gamestate`; 1A alone drains the spooled tapes (delete
`%LOCALAPPDATA%\RetroReceipts\gs-cache\*.toolarge` to re-drain now). Agent 0.2.6 does not upload tapes. PWA unaffected.

**Verify**
```
# V1.1 — 1A accepts a >8 MB envelope (staging)
curl -sS -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:7260/rr/gamestate \
  -H "Authorization: Bearer $RR_STAGING_TOKEN" -H 'content-type: application/json' \
  --data-binary @/root/tape-envelope-12mb.json          # expect 200, not 413

# V1.2 — the raw arm stores the bytes verbatim
curl -sS -X POST "http://127.0.0.1:7260/rr/gamestate/raw?match_key=$KEY&reporter=$SID&frames=7200" \
  -H "Authorization: Bearer $RR_STAGING_TOKEN" -H 'content-type: application/gzip' \
  --data-binary @/root/tape.json.gz
cmp /root/tape.json.gz /opt/rr-staging/gamestates/${KEY}_${SID}.json.gz && echo BYTE-IDENTICAL

# V1.3 — only if using Content-Encoding: prove nginx leaves the request body alone
curl -sS -X POST "https://nobd.net/rr/gamestate/raw?match_key=$KEY&reporter=$SID" \
  -H "Authorization: Bearer $TOKEN" -H 'content-encoding: gzip' --data-binary @/root/tape.json.gz
# then cmp the stored file as in V1.2 — a mismatch means an intermediary decoded it
```

---

# STEP 2 — seats (`wside`/`lside`) and `reporter` on results + session games (C10)

**Store:** `matches.json` (SSOT) + derived read payloads. `p1`/`p2` are **derived at read time**; nothing new is stored
except the optional forensic `reporter`.

### 2.1 What exists, exactly
`MatchLog` (`models.rs:288-293`):
```rust
pub(crate) wside: u8, // reporter-claimed physical side of the WINNER (1=P1, 2=P2, 0=unknown)
pub(crate) lside: u8, // reporter-claimed physical side of the LOSER; wside+lside should be {1,2}
```
Filled per-reporter at `routes.rs:1552-1558` (`side` on the `/result` body; only `1|2` accepted), completed on the
consensus path at `routes.rs:1711`, and emitted today **only** on the money receipt (`receipt.rs:203`).

**The mapping, stated once:**
```
p1 = if wside == 1 { winner } else if lside == 1 { loser } else { "" }
p2 = if wside == 2 { winner } else if lside == 2 { loser } else { "" }
// wside == lside (clash or both 0) → BOTH "" — never guess.
// Same discipline as receipt::combo_by (receipt.rs:35-44), which returns "" whenever the side is unknown.
```
Because `wside`/`lside` are already **absolute** (winner/loser-keyed, not reporter-relative), the PWA does **not** need
`reporter` to seat players. `source.ts:189 seatsOf` needs `side`+`reporter` only because the *tape envelope* expresses
side relative to its reporter (`local_pn`). Server-side the seats are complete.

### 2.2 ⚠ `reporter` does not exist on `MatchLog`
The whole struct was read (`models.rs:240-334`): **there is no `reporter` field.** `Pending.reporters: HashSet<String>`
(`models.rs:449`) holds it and `app.pending.remove(&key)` (`routes.rs:1723`) discards it at consensus. It cannot be
"echoed" — it must be added.

- **(a) Recommended: don't add it.** Emit `p1`/`p2` and drop `reporter` from C10. Zero SSOT change.
- **(b) If lane 1 wants the audit field:** additive `#[serde(default)] pub(crate) reporter: String` on `MatchLog` **and**
  in the manual `Default` impl (`models.rs:338` — the derive is deliberately not used there, `counted` must default true);
  `pub(crate) reporter: String` on `Pending` (first reporter wins); both `Pending` literals (`routes.rs:1424` creation and
  `routes.rs:1590-1624` snapshot) construct field-by-field and will not compile without it; `app.rs:1051 record_result`
  copies it. Legacy rows read `""` — treat `""` as unknown, never as a SteamID. The reporter SteamID is already in scope
  at `routes.rs:1376`.

### 2.3 The payload changes (ONE builder each — SSOT V6)
`app.rs:944-975 App::match_result_delta` — the single builder feeding the feed seed (`matches_feed_snapshot`,
`app.rs:887`) **and** both bus publishes (`routes.rs:1655`, `routes.rs:1735`):
```diff
             "duration_s": m.duration_s,
+            "wside": m.wside,
+            "lside": m.lside,
+            "p1": crate::receipt::seat_sid(m, 1),
+            "p2": crate::receipt::seat_sid(m, 2),
+            "reporter": m.reporter,          // ONLY under option (b); omit under (a)
             "verified": m.verified,
```
One shared helper, next to `combo_by` in `receipt.rs`:
```rust
/// seat (1=P1, 2=P2) → the SteamID that sat there. "" when unknown or clashing — never a guess.
pub(crate) fn seat_sid(m: &crate::models::MatchLog, seat: u8) -> String {
    if m.wside == m.lside { return String::new(); }
    if m.wside == seat { return m.winner.clone(); }
    if m.lside == seat { return m.loser.clone(); }
    String::new()
}
```
`stats.rs:36-50 session_stats` game rows, same four fields:
```diff
-            "combo_by": crate::receipt::combo_by(m), "duration_s": m.duration_s
+            "combo_by": crate::receipt::combo_by(m), "duration_s": m.duration_s,
+            "wside": m.wside, "lside": m.lside,
+            "p1": crate::receipt::seat_sid(m, 1), "p2": crate::receipt::seat_sid(m, 2)
```
Consider the same two lines in `stats.rs:381 history_row` (profile `recent` + `/rr/history`) so a replay opened from a
profile row seats correctly — same helper, no new cost.

**JSON before → after** (`/rr/matches/feed`, one row):
```jsonc
// before
{"type":"match_result","winner":"7656…A","loser":"7656…B","winner_name":"Tris","loser_name":"LurKMan",
 "winner_rating":1147,"winner_rank":"VIBRANIUM","loser_rating":1180,"loser_rank":"ADAMANTIUM",
 "winner_team":[3,17,42],"loser_team":[8,21,5],"mode":"ranked","elo":12,"combo":31,
 "ocv":false,"perfect":false,"comeback":true,"session_id":"s_A_B_18f…","key":"…","duration_s":118,
 "verified":true,"ts":1756900000000}
// after (+5 fields; every existing field byte-identical)
{ …unchanged…, "wside":2, "lside":1, "p1":"7656…B", "p2":"7656…A", "reporter":"7656…A" }
```

**Storage/bus/mirror.** JSON SSOT unchanged under (a); one additive `#[serde(default)]` string under (b). **Redis: no new
channel, no new key** — the enriched `match_result` rides `matches` → stream `matches:log`, `MAXLEN ~ 500` +
`EXPIRE 172800` (`bus.rs:136-149`); ~100 extra bytes/delta and the window is entry-count-capped, so it does **not**
shrink. Surreal: none — `mirror.rs:20 match_obj` carries no sides; leave it (`RR_SURREAL_READS` off). R2: none.

**Compat.** PWA: purely additive; `matchfeed.svelte.ts:45-47` already declares `side`/`reporter` as "absent today", so
the resolver lights up automatically. Agent 0.3.x parses named fields, ignores extras. Agent 0.2.6 does not consume this
channel. Legacy rows have `wside=lside=0` → `p1`/`p2` are `""` → client plays stock and shows `stock colors`
(REPLAY-OVERLAY-SPEC §5a). Correct by construction.

**Verify**
```
# V2.1 — seats present and consistent
curl -sS 'https://nobd.net/rr/matches/feed?limit=5' \
 | python -c "import json,sys;[print(r['key'],r['wside'],r['lside'],r['p1'],r['p2']) for r in json.load(sys.stdin)['results']]"
# expect: rows with wside!=lside give {p1,p2}=={winner,loser}; 0/0 rows give two empty strings

# V2.2 — session modal agrees with the feed for the same game
curl -sS 'https://nobd.net/rr/session?sid=<session_id>' \
 | python -c "import json,sys;[print(g['match_key'],g['p1'],g['p2']) for g in json.load(sys.stdin)['games']]"

# V2.3 — the SSE row is not a subset of its seeded twin (the V6 rule)
curl -sN 'https://nobd.net/rr-push/sse?ch=matches' | grep -m1 match_result
```

---

# STEP 3 — loadout provenance and the vault's `author` (C13)

**Store:** `loadouts.json` (`App.loadouts: HashMap<String, Vec<CharSkin>>`, `app.rs:111`) and `user_skins.json`
(`App.user_skins`). Both are already **durable side-stores in their own right** (records.json is a rebuilt cache and
cannot carry them) — this step widens two existing rows, it does **not** add a new authoritative store.

### 3.1 `CharSkin`
`models.rs:39-43` today is `{ cid: u8, colors: Vec<u32> }`. After:
```rust
pub(crate) struct CharSkin {
    pub(crate) cid: u8,
    #[serde(default)] pub(crate) colors: Vec<u32>,          // UNCHANGED — the tray reads this
    // provenance: additive, omitted when empty so the tray's wire shape stays byte-identical
    #[serde(default, skip_serializing_if = "String::is_empty")] pub(crate) skin_id: String,
    #[serde(default, skip_serializing_if = "String::is_empty")] pub(crate) name: String,
    #[serde(default, skip_serializing_if = "String::is_empty")] pub(crate) author_steamid: String, // SERVER-DERIVED
    #[serde(default, skip_serializing_if = "String::is_empty")] pub(crate) author_credit: String,  // bare NAME, code/library only
    #[serde(default, skip_serializing_if = "String::is_empty")] pub(crate) source: String,         // studio|code|library
}
```
The stored field is **`author_credit`, not `author_name`**. `author_name` is a *response* field computed at read time:
`disp_name(author_steamid)` when a SteamID is held, else `author_credit`. That is the SSOT names rule (`app.rs:1445
disp_name` is the complete resolver; a stored display-name copy on a live struct is a defect) — a creator renaming on
Steam propagates to every old replay with no migration.

⚠ `CharSkin` is also `TeamLoadout.entries` (`models.rs:98`). The `skip_serializing_if` guards keep locker snapshots
byte-identical when empty; when set, re-applying a saved team re-equips the same credited skins — correct.

**`source` — one closed set.** The specs disagree: REPLAY-OVERLAY-SPEC §4.1 says `vault|code|community|legacy`; this
hand-off's brief says `studio|code|library`. **Ship `studio|code|library`**, mapping `studio ≡ vault`,
`library ≡ community`; `legacy` is not a client value — an **absent/empty `source` reads as legacy**. Validate against
the closed set and store `""` otherwise, exactly like the `origin` handling at `routes.rs:1574-1577`. **Confirm the three
words with Tris** before the PWA hard-codes them.

### 3.2 `POST /rr/loadout` (the equip write, `routes.rs:620-646`)
```jsonc
// before
POST /rr/loadout   {"cid": 42, "colors": [16 ints]}
// after (all new fields optional; a body without them behaves exactly as today)
POST /rr/loadout   {"cid":42,"colors":[16 ints],"skin_id":"3f2a…","name":"NIGHTFALL",
                    "source":"studio","author_credit":"Ruby"}
→ {"ok": true, "count": 3}     // response shape UNCHANGED
```
Rules — these are the point of the step, do not soften:
1. **`author_steamid` is never accepted from the client.** It is resolved server-side from `skin_id` via the
   `skin_id → owner` index (§3.4). A non-resolving `skin_id` drops the whole provenance block (colors still applied);
   no error, no partial credit.
2. `source == "studio"` requires a resolving `skin_id`. `code`/`library` forbid `skin_id` and accept `author_credit` only.
3. `name` → `clean(&…, 60)` (`util.rs:26`); `author_credit` → `clean(&…, 40)` (the share-code author budget).
4. **Refuse mojibake.** `util::clean` filters control chars and `<`/`>` but does **not** reject `U+FFFD`. Add
   `if s.contains('\u{FFFD}') { return String::new() }` for both `name` and `author_credit`.
5. Empty `colors` still means revert-to-stock: the whole `CharSkin` is removed (`app.rs:1604-1611`), provenance with it.

`App::set_char_skin` (`app.rs:1602-1620`) grows args (or takes a prepared `CharSkin`). Its
`bus.publish("cmd.{steamid}", {"type":"skin","cid":…,"colors":…})` at `app.rs:1615` **must not change shape** — the
tray's `apply_cmd_skin` (`agent/src/painter.rs:454`) reads exactly `cid` + `colors`.

### 3.3 `GET /rr/loadout` (the public read, `routes.rs:585-613`)
Must stop serializing `CharSkin` straight through, because `author_name` is computed. One projection for all three arms
(own-read `skins`, `?steamid=` `loadout`, `?steamids=` `loadouts`):
```rust
fn char_skin_pub(app: &App, c: &CharSkin) -> Value {
    let author_name = if !c.author_steamid.is_empty() { app.disp_name(&c.author_steamid) }
                      else { c.author_credit.clone() };
    let mut o = json!({"cid": c.cid, "colors": c.colors});
    for (k, v) in [("skin_id",&c.skin_id),("name",&c.name),("author_steamid",&c.author_steamid),("source",&c.source)] {
        if !v.is_empty() { o[k] = json!(v); }
    }
    if !author_name.is_empty() { o["author_name"] = json!(author_name); }
    o
}
```
```jsonc
// before — GET /rr/loadout?steamid=7656…A
{"ok":true,"steamid":"7656…A","loadout":[{"cid":42,"colors":[16 ints]}]}
// after
{"ok":true,"steamid":"7656…A","loadout":[
  {"cid":42,"colors":[16 ints],"skin_id":"3f2a…","name":"NIGHTFALL",
   "author_steamid":"7656…R","author_name":"Ruby","source":"studio"},
  {"cid":17,"colors":[16 ints]}                       // legacy entry: unchanged shape
]}
```
Cost: `disp_name` is two HashMap lookups (`app.rs:1450-1455`), ≤3 per player, ≤25 players on the batch arm → ≤75 lookups.

### 3.4 The `skin_id → owner` index (derived, never authoritative)
`user_skins` is keyed by owner, so resolving an id otherwise means scanning every vault.
```rust
pub(crate) skin_owner: HashMap<String, String>, // skin_id -> owner. DERIVED from user_skins; never persisted.
```
Built once in `App::load` after `user_skins` loads; inserted in `handle_skin_save` (`routes.rs:2404-2444`); removed in
`handle_skin_delete`. ⚠ `enforce_caps`'s `evict_oldest(&mut self.user_skins, VAULT_USERS_CAP, …)` (`app.rs:1041`)
evicts **whole users** — rebuild the index after an eviction. Fully re-derivable from `user_skins.json`, never written
to disk ⇒ **no new authoritative store**.

### 3.5 The vault must stop writing `author: ''` — what the PWA must send
Server-side, `handle_skin_save` already stores `author = clean(&s_field(&b,"author"), 60)` into `SavedSkin.author`
(`models.rs:77-91`). **No server shape change required.** What changes is the contract plus two guards:
- **Contract:** `SavedSkin.author == ""` means **the vault owner is the author** (own design). It never means
  "unknown". Never store the owner's own display name there — a frozen name copy the SSOT audit forbids.
- **Guard 1:** reject an `author` that is a 17-digit SteamID (`is_steamid`) → store `""`. `author` is a name;
  identities live in `author_steamid` on the loadout.
- **Guard 2:** refuse `U+FFFD` (same one-liner as §3.2 rule 4).

**PWA changes (lane 2 — listed so lane 1 knows the wire):**

| Call site | Today | Must send |
|---|---|---|
| `pwa/src/lib/stores/vault.svelte.ts:79` (`save()`) | `author: ''` always | thread an `author` argument through; the caller decides |
| `pwa/src/routes/skins/[cid]/+page.svelte:158` (save a pasted code) | `author: ''` | `vault.save(cid, name, palette, undefined, codeSkin.author)` |
| `pwa/src/lib/components/DyeStation.svelte:162` (own design) | `author: ''` | keep `''` — correct under the new contract |
| `pwa/src/lib/stores/loadouts.svelte.ts:114 equipOwn` | `{cid, colors}` | `{cid, colors, skin_id?, name?, source, author_credit?}` from `trying` (`skins/[cid]/+page.svelte:37,54`): `vaultId` → `source:'studio'` + `skin_id`; code card → `source:'code'` + `author_credit`; community card → `source:'library'` + `author_credit` |

**Storage/bus/mirror.** JSON: `loadouts.json` rows grow ≤~120 B per credited character; `user_skins.json` unchanged.
Redis: unchanged shape on `cmd.<steamid>`, **no new channel** — `cmd:<sid>:log` is the unbounded-cardinality family
from the register and is TTL'd (`bus.rs:149`); do not add a per-skin/per-creator channel. Surreal: `mirror_skin`
(`app.rs:1789`) picks up nothing new — **do not** add a Surreal query for author resolution (mirror never authoritative;
every query in `surreal.rs` is `format!`-built with no `$param` binds, register R1). R2: none.

**Compat.** Agent 0.3.x `reader.rs:402 fetch_loadout` parses `cid`+`colors` field-by-field from a `Value` and ignores
everything else; there is **no `deny_unknown_fields` anywhere in the agent**. Agent 0.2.6 never calls `/loadout`.
PWA `loadouts.svelte.ts:26 normalize` reads only `cid`/`colors`. Old `loadouts.json` loads clean (`#[serde(default)]`)
and serializes back byte-identical. A rollback to the previous binary also loads it, but silently drops provenance on
the next write — note that in the runbook.

**Verify**
```
# V3.1 — equip with provenance, read back with the author resolved
curl -sS -X POST https://nobd.net/rr/loadout -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"cid":42,"colors":[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],"skin_id":"'$SKIN_ID'","name":"NIGHTFALL","source":"studio"}'
curl -sS "https://nobd.net/rr/loadout?steamid=$MY_SID" | python -m json.tool
# expect author_steamid == the vault owner of SKIN_ID, author_name == that owner's CURRENT display name

# V3.2 — a forged author_steamid is ignored
curl -sS -X POST https://nobd.net/rr/loadout -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"cid":42,"colors":[…16…],"skin_id":"'$SKIN_ID'","author_steamid":"76561190000000000"}'
curl -sS "https://nobd.net/rr/loadout?steamid=$MY_SID" | grep -o '"author_steamid":"[^"]*"'   # expect the REAL owner

# V3.3 — rename propagation: change the creator's Steam persona, re-run V3.1's GET; author_name follows.

# V3.4 — a code save keeps its credit
curl -sS -X POST https://nobd.net/rr/skins/save -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"cid":"42","name":"DUSK","author":"Ruby","palette":[…]}'
curl -sS https://nobd.net/rr/skins/list -H "Authorization: Bearer $TOKEN" | grep -o '"author":"[^"]*"'
```

---

# STEP 4 — the tape index, and the authed tape read / request / archive (C2)

**Store:** hot dir = derived cache; R2 = durable mirror; the index = **in-memory, derived, never persisted as truth**.
OK on the prime directive *provided* byte-serving goes through nginx (§0.1) and the R2 pull is spawned.

### 4.1 The tape index (prerequisite for 4.2 and all of step 5)
Every tape lookup today is a `read_dir` on the request thread: `routes.rs:720` (`/gamestate/exists`), `receipt.rs:120`
(`replay()`), `receipt.rs:180` (`match_receipt`); and `app.rs:1823 enforce_gamestate_cap` runs on **every sweep and
every upload**. Adding a per-row `replay.state` to a 100-row feed without an index would be a `read_dir` per row.
```rust
// app.rs — DERIVED cache of the hot tape dir. Rebuilt from one read_dir at boot and after each eviction;
// never persisted, never authoritative. Losing it costs one directory scan.
pub(crate) struct TapeEntry { pub reporter: String, pub bytes: u64, pub mtime_ms: u64, pub frames: u32 }
pub(crate) tapes: HashMap<String, TapeEntry>,   // match_key -> best (largest) tape on disk
pub(crate) tapes_archived: HashSet<String>,     // match_keys known in R2 (from the index file)
```
Built in `App::load` (one `read_dir`, split each filename on the last `_`); `ingest_tape` inserts/updates;
`enforce_gamestate_cap` becomes a method (or returns removed paths) so the index drops what it unlinked and adds those
keys to `tapes_archived`. Bonus: switch `receipt.rs:120` and `routes.rs:720` to the index and stop scanning.

`tapes_archived` loads from `<workdir>/tape_archive.json` (a plain `["<match_key>", …]`), written by the **same cron**:
```sh
# append to ops/r2-sync-gamestates.sh, after the rclone copy
rclone lsf "$R2_REMOTE" --include '*.json.gz' \
  | sed 's/_[0-9]\{17\}\.json\.gz$//' | sort -u \
  | python3 -c 'import sys,json;json.dump([l.strip() for l in sys.stdin if l.strip()],open("/opt/rr-server/tape_archive.json","w"))'
```
Re-read when its mtime changes, on the existing 256-request sweep — one `stat`, no timer. **Derived from R2**
(regenerate any time) ⇒ not a new authoritative store.

### 4.2 The endpoints
All authed (`auth_steamid`), all under the existing `/rr/*` → `/skinsync/*` shim (`routes.rs:214`). ⚠ **Arm ordering:**
exact-path arms must sit *above* any `p.starts_with("/skinsync/tape/")` guard — exactly as `/gamestate/exists` and
`/list` sit above the `/skinsync/gamestate/` prefix arm at `routes.rs:999`.

| method | path | body/query | response |
|---|---|---|---|
| GET | `/rr/tape?key=<match_key>` | | `{ok, state, tape_url?, bytes?, frames?, ts?, session_id?, match_index?}` |
| GET | `/rr/tape?session=<session_id>` | | `{ok, tapes:[{key, state, match_index, bytes?}]}` |
| POST | `/rr/tape/request` | `{key}` | `{ok, state:"pending"}` |
| GET | `/rr/tape/<match_key>.json.gz` | | the gz bytes (see 4.3) |
| POST | `/rr/tape/save` | `{key}` | **deferred — money-path** |

```rust
pub(crate) fn tape_state(&self, key: &str) -> &'static str {
    if self.tapes.contains_key(key) { return "ready"; }
    if self.tape_requests.contains(key) { return "pending"; }            // in-flight pull, in-memory
    if let Some(m) = self.matches.iter().rev().find(|m| m.key == key) {
        if now_ms().saturating_sub(m.ts) < 180_000 { return "pending"; } // ended <3 min ago, upload in flight
    }
    if self.tapes_archived.contains(key) { return "archived"; }
    "none"
}
```
`expired` (LIVE-TAB C5) is a **product decision that is not made yet** — do not invent it. Until Tris signs the
retention window those rows are honestly `none`.

**Authorization gate — do this, it closes a real hole.** `match_key` is **client-supplied** (`routes.rs:1409-1417`:
`clip(&s_field(b,"match_key"), 80)`, with a server fallback), and `util.rs:160 sanitize_id` **strips rather than
rejects**, so two distinct keys can collapse to one filename (the same class as Surreal's `rid()` R4). Therefore:
1. The key MUST resolve to a `MatchLog` in `app.matches` — no match ⇒ `404` and **no filesystem touch at all**.
2. Apply the visibility rule `receipt.rs:113` already uses: `m.counted || m.mode() != "lobby"`, else `403`.
3. Only then `sanitize_id` to build the path.

**`POST /rr/tape/request` — the pull must not block:**
```rust
let (key, dir) = (key.clone(), app.gamestates_dir.clone());
app.tape_requests.insert(key.clone());               // in-memory; also the idempotency guard
std::thread::spawn(move || {
    let _ = std::process::Command::new("rclone")
        .args(["copy", &format!("{R2_REMOTE}/{key}_*.json.gz"), &dir, "--include", "*.json.gz"])
        .status();
});
reply_json(req, 200, &json!({"ok": true, "state": "pending"}));
```
⚠ The worker cannot touch `&mut App`. Pick one and write it down: **(a) recommended** — the worker only writes the
file, and the **next sweep** (`App::sweep`, already every 256 requests) indexes it and publishes the `tape` event;
**(b)** an `mpsc` from workers drained at the top of `handle()` for immediacy.

Rate-limit **per account, not per IP** (IPs are shared behind NAT — same reasoning as `RAIL_MAX_BETS_PER_MIN`,
`config.rs:84`): `HashMap<steamid,(count,window_start)>`, e.g. 5 pulls/min, in memory. A key already in
`tape_requests` returns `pending` without spawning again.

**`POST /rr/tape/save` touches coins → route to `retro-receipts-money-expert`.** Price, wallet flow, and whether a saved
tape is exempt from the 6 GB cap are money/product decisions (LIVE-TAB Q2). A `saved_by` in an R2 sidecar would put a
retention-governing fact **outside the JSON SSOT** — a design event, not a drive-by.

### 4.3 Serving the bytes — `X-Accel-Redirect`, not `reply_bytes`
nginx already proxies `/rr/` and gives Range, ETag, conditional GET and slow-client buffering for free.
```nginx
# /etc/nginx/sites-enabled/nobd-web — internal, not reachable from outside
location /__tapes/ {
    internal;
    alias /opt/rr-server/gamestates/;
    add_header Cache-Control "private, max-age=86400";
    types { } default_type application/gzip;
}
```
```rust
// after auth + visibility + index checks
let resp = Response::from_data(Vec::new()).with_status_code(StatusCode(200))
    .with_header(Header::from_bytes(&b"X-Accel-Redirect"[..],
        format!("/__tapes/{id}.json.gz").as_bytes()).unwrap())
    .with_header(Header::from_bytes(&b"Content-Type"[..], &b"application/gzip"[..]).unwrap());
```
Loop time: microseconds. Authorization stays in Rust; bytes never enter the process.

**Fallback if nginx is off-limits:** `tiny_http::Response::from_file(File)` streams instead of buffering — fixes memory
but **not** the blocked loop; `http.rs:34 cors()` is typed `Response<Cursor<Vec<u8>>>` and needs a generic sibling; and
**Range is not implemented by tiny_http**. Take the nginx route.

**ETag:** do not sha256 on the request path (~40 ms for 14 MB on the loop). Under `X-Accel-Redirect` nginx emits its own
`ETag`/`Last-Modified`. If a content hash is ever needed, get it off-box (`rclone hashsum sha256`).

**Storage.** JSON SSOT untouched. Hot-dir caps unchanged; eviction (`app.rs:1836-1848`, oldest first) is now
non-destructive **only if** the file was ≥1 min old and the cron ran. To make it airtight, have eviction refuse to unlink
a key absent from `tapes_archived` and log instead. Redis: none in this step. Surreal: none — do not mirror tapes. R2:
read path only.

**Compat.** `GET /skinsync/gamestate/<id>` (admin, `routes.rs:999`) stays exactly as-is — it is the ops path. No client
depends on `/rr/tape*` today (`source.ts` degrades on 404), so partial shipping is safe. Agents unaffected.

**Verify**
```
# V4.1 — state for a hot key
curl -sS "https://nobd.net/rr/tape?key=$KEY" -H "Authorization: Bearer $TOKEN"
# expect {"ok":true,"state":"ready","tape_url":"/rr/tape/<key>.json.gz","bytes":…,"frames":…}

# V4.2 — unauthenticated refused; unknown key never touches disk
curl -sS -o /dev/null -w '%{http_code}\n' "https://nobd.net/rr/tape?key=$KEY"                       # 401
curl -sS -o /dev/null -w '%{http_code}\n' "https://nobd.net/rr/tape?key=../../etc/passwd" \
     -H "Authorization: Bearer $TOKEN"                                                              # 404

# V4.3 — a private lobby game's tape is refused
curl -sS -o /dev/null -w '%{http_code}\n' "https://nobd.net/rr/tape?key=$LOBBY_KEY" \
     -H "Authorization: Bearer $TOKEN"                                                              # 403

# V4.4 — bytes stream via nginx, with Range (the C2 gate)
curl -sS -o /dev/null -w '%{http_code} %{size_download}\n' -r 0-1023 \
     "https://nobd.net/rr/tape/$KEY.json.gz" -H "Authorization: Bearer $TOKEN"                      # 206 1024
curl -sS "https://nobd.net/rr/tape/$KEY.json.gz" -H "Authorization: Bearer $TOKEN" | gunzip | head -c 200

# V4.5 — the loop did NOT block during a 14 MB download (run V4.4 concurrently with:)
while true; do curl -sS -o /dev/null -w '%{time_total}\n' https://nobd.net/rr/health; sleep 0.2; done
# every probe should stay in the low ms; a spike matching the download = X-Accel not wired

# V4.6 — archive pull is idempotent and non-blocking (run twice; only one rclone should spawn)
curl -sS -X POST https://nobd.net/rr/tape/request -H "Authorization: Bearer $TOKEN" \
     -H 'content-type: application/json' -d "{\"key\":\"$ARCHIVED_KEY\"}"      # {"ok":true,"state":"pending"}
```

---

# STEP 5 — `replay` state on the payloads + the `{type:'tape'}` bus event (C1)

**Store:** derived read payloads + one Redis delta. O(1) index lookup per row, no new Redis key. **Depends on 4.1.**

### 5.1 The `replay` block — ONE builder
```rust
// app.rs, next to match_result_delta — the ONE replay-availability projection. O(1): index lookups only.
pub(crate) fn replay_avail(&self, m: &MatchLog) -> serde_json::Value {
    let state = self.tape_state(&m.key);
    let mut o = serde_json::json!({ "state": state });
    if state == "ready" {
        if let Some(t) = self.tapes.get(&m.key) {
            o["tape_url"] = json!(format!("/rr/tape/{}.json.gz", m.key));
            o["bytes"] = json!(t.bytes);
            o["frames"] = json!(t.frames);
        }
    }
    o
}
```
Wire into **both** consumers: `app.rs:944 match_result_delta` → `"replay": self.replay_avail(m)` (the feed seed and both
bus publishes at `routes.rs:1655`/`:1735` inherit it automatically), and `stats.rs:36 session_stats` game rows →
`"replay": app.replay_avail(m)`. Optionally `stats.rs:381 history_row`.
```jsonc
// before  (a result row)
{"type":"match_result", …, "key":"…","duration_s":118,"verified":true,"ts":…}
// after
{"type":"match_result", …, "key":"…","duration_s":118,
 "replay":{"state":"ready","tape_url":"/rr/tape/….json.gz","bytes":4128332,"frames":7180},
 "verified":true,"ts":…}
// fresh result, tape still uploading:   "replay":{"state":"pending"}
// old result, tape rolled out of hot:   "replay":{"state":"archived"}
```
⚠ `matches_feed_snapshot` (`app.rs:887-905`) already builds `(0..len)` and sorts the **whole** match log per feed GET —
O(n log n) on the request thread, unrelated to this change but the reason `replay_avail` must stay O(1). Never put a
`read_dir`, `stat` or file read inside it. (Separate cleanup ticket: the log is append-ordered by ts, so a reverse
iterator + filter replaces the sort.)

### 5.2 The bus event
Published from `ingest_tape` (upload) and from the sweep that notices an archive pull:
```rust
app.bus.publish("matches", json!({
    "type": "tape", "key": key, "state": "ready",
    "frames": frames, "bytes": bytes,
    "duration_s": duration_s,   // the value just stamped onto the MatchLog (routes.rs:2380-2390)
    "ts": now_ms()
}));
```
- **Channel `matches`** — existing. Stream `matches:log`, `MAXLEN ~ 500` + `EXPIRE 172800` (`bus.rs:136-149`). **No new
  key, no new cardinality ⇒ register R1 untouched.** Accepted trade-off: tape events share the 500-entry replay window
  with `match_start`/`match_result`/rail deltas. **Do not create a `tape.<key>` channel.**
- Carrying `duration_s` means the client upgrades length *and* affordance from one delta.
- Fire-and-forget (`bus.publish` → mpsc → worker, `bus.rs:76`). A Redis outage drops it; the next `/rr/matches/feed` seed
  carries the same `replay.state`.
- Push-gateway needs no change if it fans out whatever is on `matches`. **UNKNOWN:** whether it filters by `type` —
  grep `push-gateway/` for a type allow-list before assuming pass-through.

**Compat.** PWA `matchfeed.svelte.ts:341 #toResult` ignores unknown `type` values — an unhandled `tape` event is a no-op
until wired. Agent 0.3.x subscribes to `cmd.<steamid>`, not `matches`. Agent 0.2.6 unaffected.

**Verify**
```
# V5.1 — every feed row carries a replay state
curl -sS 'https://nobd.net/rr/matches/feed?limit=20' \
 | python -c "import json,sys;print({r['replay']['state'] for r in json.load(sys.stdin)['results']})"
# expect a subset of {'ready','pending','archived','none'}

# V5.2 — the SSE tape event
curl -sN 'https://nobd.net/rr-push/sse?ch=matches' | grep -m1 '"type":"tape"'

# V5.3 — no new Redis keys appeared
redis-cli --scan --pattern 'tape*' | head    # expect EMPTY
redis-cli TTL matches:log                    # expect ~172800, refreshed on write
redis-cli XLEN matches:log                   # expect <= ~500
```

---

# STEP 6 — `TMatch` gains `session_id` / `match_key` (C11)

**Store:** the per-tournament JSON (`App.tournaments`, per-event `save_tournament`). The pointer is derived from data
already stamped at ingest and is re-derivable from `matches.json` at any time.

### 6.1 The struct
The client's `BracketMatch` is the server's `TMatch` (`tourney.rs:69-104`).
```diff
     #[serde(default)]
     pub(crate) on_stream: bool,
+    // the SET this bracket match was played as — stamped at result ingest from the first game whose
+    // (pair, live tournament) matched this node. Never overwritten; "" = no game landed yet.
+    // DERIVED: rebuildable from matches.json (session_id of rows carrying this tourney_id + pair).
+    #[serde(default)] pub(crate) session_id: String,
+    #[serde(default)] pub(crate) match_key: String,   // last game's key — the fallback when session_id is ""
```
`TMatch` derives `Default`, so no manual-Default edit (unlike `MatchLog`).

### 6.2 The stamp — at ingest, not at report
`App::live_tourney_match_for_pair` (`app.rs:1638-1653`) already walks to the exact `TMatch` and throws the match id
away. Widen the return:
```diff
-    pub(crate) fn live_tourney_match_for_pair(&self, a: &str, b: &str) -> Option<String> {
+    /// (tournament id, bracket match id) for a live, undecided bracket node containing this exact pair.
+    pub(crate) fn live_tourney_match_for_pair(&self, a: &str, b: &str) -> Option<(String, u32)> {
-                        return Some(t.id.clone());
+                        return Some((t.id.clone(), m.id));
```
Sole caller, `routes.rs:1634`:
```diff
-        snap.tourney_id = app.live_tourney_match_for_pair(&winner, &loser).unwrap_or_default();
+        let tm = app.live_tourney_match_for_pair(&winner, &loser);
+        snap.tourney_id = tm.as_ref().map(|(t, _)| t.clone()).unwrap_or_default();
```
then, after the `record_result` block (so the MatchLog exists):
```rust
if let Some((tid, mid)) = tm {
    let delta = app.tournaments.get_mut(&tid).and_then(|t| t.bracket.as_mut())
        .and_then(|br| br.matches.get_mut(mid as usize))
        .map(|m| {
            if m.session_id.is_empty() { m.session_id = snap.session_id.clone(); } // first game wins
            m.match_key = key.clone();                                             // last game wins
            (m.id, m.session_id.clone(), m.match_key.clone())
        });
    if let Some((id, sid, mk)) = delta {
        app.save_tournament(&tid);
        app.bus.publish_tourney(&tid, json!({"tid": tid, "type": "match_update",
            "mid": id, "session_id": sid, "match_key": mk}));
    }
}
```
**Why at ingest, not at `tourney::report`:** the reference exists as soon as the first game lands, is identical for
every game of the set, and self-reported bracket results (`tourney.rs:1763`) can arrive without a game ever being
logged. The PWA gates the chip on `state === 'done'` anyway (REPLAY-OVERLAY-SPEC §5b).

Add the two fields to `match_update_delta` (`tourney.rs:1131-1153`), omitted when empty — same style as
`host`/`lobby_id`. Leave `match_row` (`tourney.rs:1120`) alone.
```jsonc
// before — a bracket match in GET /rr/tourney?id=<tid>
{"id":7,"bracket":"Winners","round":2,"p1":"7656…A","p2":"7656…B","winner":"7656…A",
 "score":"2-1","state":"Done","best_of":3,"lobby_id":"1090…","host":"7656…H","on_stream":true}
// after
{ …unchanged…, "session_id":"s_A_B_18f2c…", "match_key":"7656…A_7656…B_7656…A_58e…" }
```
**Storage/bus/mirror.** JSON: two short strings per played node; `save_tournament` is a per-event write. Redis: rides the
existing `tourney.<tid>` → `tourney:<tid>:log` (R1 unbounded-cardinality family, TTL'd at 48 h, `bus.rs:149`) — **do
not add a new channel**. Surreal: `mirror_tournament` (`app.rs:1730`) serializes the whole `Tournament` and
`put_tournament` interpolates it as a JSON literal (`surreal.rs:154`) — serde escapes the values, injection-safe by
construction; SCHEMALESS, no `schema.surql` change. R2: none.

**Compat.** PWA `lib/tourney.ts:42-60` parses named fields; extras ignored. Old tournament JSON loads clean
(`#[serde(default)]`); historical nodes stay `""` and show no chip. **Optional offline backfill:** for each `TMatch`
with a winner, find `MatchLog`s with `tourney_id == tid` and `{winner,loser} == {p1,p2}`, take the earliest
`session_id` — pure re-derivation from the SSOT, safe to re-run.

**Verify**
```
# V6.1 — a played bracket node carries its set
curl -sS "https://nobd.net/rr/tourney?id=$TID" \
 | python -c "import json,sys;[print(m['id'],m['state'],m.get('session_id',''),m.get('match_key','')) for m in json.load(sys.stdin)['bracket']['matches']]"

# V6.2 — the reference opens the right set
curl -sS "https://nobd.net/rr/session?sid=$SESSION_ID" \
 | python -c "import json,sys;d=json.load(sys.stdin);print(d['count'],[g['match_index'] for g in d['games']])"

# V6.3 — the live delta carried it
curl -sN "https://nobd.net/rr-push/sse?ch=tourney.$TID" | grep -m1 session_id
```

---

# STEP 7 — creator stats as derived counts (C15)

**Store:** none — pure derivation from `user_skins.json` + `loadouts.json`. Depends on step 3.

`stats.rs:411 profile(app: &App, id: &str, owner: bool)` gains:
```rust
// SKINS — creator counts, derived on read. `designs` is O(1); `worn_by` is one bounded pass over
// loadouts.json. Never cached, never stored.
let designs = app.user_skins.get(id).map(|v| v.len()).unwrap_or(0);
let worn_by = if app.loadouts.len() <= LOADOUT_SCAN_MAX {
    Some(app.loadouts.values()
        .filter(|entries| entries.iter().any(|c| c.author_steamid == id))
        .count())                       // a creator wearing their own design counts (spec §3.4)
} else { None };                        // too big to scan on the request thread — report unknown, never block
json!({"designs": designs, "worn_by": worn_by, "in_replays": Value::Null})
```
added as `"skins": {…}` on the profile payload.
```jsonc
// before — GET /rr/profile?steamid=7656…R
{"steamid":"7656…R","found":true,"wins":…,"losses":…,"teams":[…],"recent":[…],"vs":[…]}
// after
{ …unchanged…, "skins":{"designs":14,"worn_by":6,"in_replays":null} }
```
**The bound.** ⚠ `App.loadouts` is **not** in `enforce_caps` (`app.rs:1032-1042`) — a pre-existing unbounded-growth path
this step must not worsen. Add `LOADOUT_SCAN_MAX = 5_000` to `config.rs`; past it return `worn_by: null` and render `—`.
Separately recommend `evict_oldest(&mut self.loadouts, …)` — but `Vec<CharSkin>` has no timestamp, so it needs a `ts`
field first. **Its own ticket.**

**`in_replays` is deliberately `null`.** Its definition (spec §4.4) requires joining the tape index by *player*; step 4's
index is keyed by `match_key`. Ship `null`; revisit with a `steamid → [match_key]` index if Tris wants it. **UNKNOWN:**
whether the count should track "wears now" — Q8, unanswered.

**Storage/bus/mirror/compat.** JSON read-only. Redis none. Surreal none. R2 none. PWA/agents: additive. Before step 3
lands it correctly returns `0`.

**Verify**
```
# V7.1
curl -sS "https://nobd.net/rr/profile?steamid=$CREATOR" | python -c "import json,sys;print(json.load(sys.stdin)['skins'])"

# V7.2 — reconcile worn_by against the store (on the VPS)
python3 - <<'PY'
import json
lo = json.load(open('/opt/rr-server/loadouts.json')); c = '<CREATOR_STEAMID>'
print(sum(1 for _, e in lo.items() if any(x.get('author_steamid') == c for x in e)))
PY
```

---

# Risk-register deltas (for `RetroReceipts-server/docs/DATA-STACK.md`)

- **Redis:** no new channels. Tape deltas ride `matches`; bracket set-references ride `tourney.<tid>`. Both streams are
  `MAXLEN ~ 500` + `EXPIRE 172800` — **R1 remains closed** (the EXPIRE and the bus-worker timeouts, R4, are both live in
  `bus.rs` today; the shortlist entry is stale and should be marked DONE). **Any future per-tape or per-creator channel
  is refused.**
- **New store classification:** `App.tapes`, `App.tapes_archived`, `App.skin_owner` are **DERIVED, in-memory, never
  persisted as truth**. `loadouts.json` and `user_skins.json` were already durable side-stores and now carry provenance
  ⇒ backup-critical. **UNKNOWN:** verify `backup.sh` covers them; it explicitly skips `gamestates/`.
- **Blocking-call register (new entries):** (i) `read_body_capped` reads the whole body into a `String` on the loop —
  bounded by `GS_MAX_BODY`, now 32 MB; the raw arm (`std::io::copy`) is the non-blocking path. (ii) Serving tape bytes
  from `reply_bytes` blocks the loop for the whole transfer — **tape reads MUST go through nginx `X-Accel-Redirect`**.
  (iii) `receipt.rs` gunzips up to 8 tapes inline per receipt GET; with `TAPE_MAX_GZ` raised this must move to the tape
  index or drop to 2.
- **Pre-existing, unrelated tickets:** `App.loadouts` has no cap/eviction; `matches_feed_snapshot` sorts the entire match
  log per feed GET; `util::sanitize_id` strips rather than rejects — step 4's "key must resolve to a MatchLog" gate is the
  tape-path mitigation, not a general fix.
- **Money boundary:** `POST /rr/tape/save` and any `saved_by` retention exemption are **money-path** — route to
  `retro-receipts-money-expert`.

# UNKNOWNs (do not guess past these)

1. Is the R2 mirror cron installed on rise3? (`crontab -l | grep r2-sync-gamestates`) — without it, `archived` is never true.
2. Does `backup.sh` include `loadouts.json` / `user_skins.json`? It explicitly skips `gamestates/`; the rest unverified.
3. Does nginx pass a `Content-Encoding: gzip` request body through untouched here? Inferred, not verified — V1.3 settles
   it. Recommendation stands: use `Content-Type: application/gzip`.
4. Does the push-gateway filter SSE deltas by `type`? Grep `push-gateway/` before shipping step 5.
5. `source` vocabulary: `studio|code|library` (this hand-off) vs `vault|code|community|legacy` (spec §4.1). One word from Tris.
6. Share-code v2 with `author_steamid` (C14) is a PWA format change; the server needs nothing until a code can carry a
   SteamID — the **one** case where a client-supplied `author_steamid` would have to be trusted. Store it as
   `author_credit` (a name) unless it can be verified against a vault. Do not build it into step 3.
7. `expired` (C5) and the paid-save price (C6/Q2) are unmade product decisions — step 4 reports `none`.
8. The tape envelope's `side`/`session_id`/`stage_id`/`p1_team`/`p2_team`/`agent_ver`/`sha256` named in the archive
   hand-off §1: the server only ever parses `reporter`, `winner`, `loser`, `local_pn`, `schema`, `ver`, `frames`,
   `set_start`, `set_end`, `synthetic_frames` (`reconcile.rs:63-95, 253-273`). The rest are **UNKNOWN server-side** —
   copy verbatim, never assume.
9. C7 (server-rendered tape-frame poster) and C12 (agent-built asset packs) have no owner and are out of scope here.

# Deploy notes

- None of the above touches `tb.rs` / `ledger.rs` / `wager.rs` / `rail.rs`, so the deploy build is the usual
  `cargo build --release --features tb` on the VPS (cfg(tb) does not compile on Windows).
- **Use staging** (`rr-staging.service`, `/opt/rr-staging`, port 7260, own snapshot, `RR_BUS=0`, no Surreal). Every V-curl
  that does not involve Redis or Surreal runs against `http://127.0.0.1:7260/rr/…` with a snapshot bearer. The bus checks
  (V5.2, V5.3, V6.3) and the `X-Accel-Redirect` checks (V4.4–V4.5) need prod or a staging nginx location.
- A failed build leaves the old binary in place (safe); `cp` over a running binary gives "Text file busy" — stop the
  service first.

## Key files read (all under `C:\Users\trist\projects\RetroReceipts-server\server\src` unless noted)

`main.rs` (:201) · `http.rs` (:83, :52, :34) · `config.rs` (:25, :26-27) · `models.rs` (:39-43, :77-91, :240-334,
:418-452) · `app.rs` (:944-975, :887, :1445, :1602, :1638, :1789, :1823) · `routes.rs` (:214, :276, :585-660, :1366-1745,
:2300-2394, :2404-2444) · `stats.rs` (:17-51, :381) · `receipt.rs` (:35, :60, :106, :163) · `reconcile.rs` (:63, :253) ·
`bus.rs` (:132-157) · `tourney.rs` (:69-104, :1131, :1763) · `surreal.rs` (:41, :128-170) · `mirror.rs` ·
`RetroReceipts-server/ops/r2-sync-gamestates.sh` · agent `reader.rs` (:402), `painter.rs` (:454) · PWA
`loadouts.svelte.ts` (:26, :114), `vault.svelte.ts` (:71-89).

## STEP 0 (do first, one line) — `LATEST_AGENT_VER` → `0.3.50`

Agent **0.3.50** is released (GitHub `v0.3.50`, `rr-agent.exe` + `.sig`; `/opt/rr-server/update/agent-latest.json` flipped
2026-09-04, backup `agent-latest.json.bak-0.3.31`; Linux binary follows from the Beelink build). The server's update-nag
constant `LATEST_AGENT_VER` still says an older version — bump it to `0.3.50` and redeploy (`rr-server-lane.md`:
"REMEMBER TO BUMP IT each agent release"). Fleet auto-updates on next game-close. The 8 MB body limit (STEP 1) is what
makes the fleet's tapes actually arrive — until then every 0.3.4x tape parks for 6 h and retries.
