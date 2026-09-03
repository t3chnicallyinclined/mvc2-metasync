# Hand-off to lane 1 (RetroReceipts-server): tape uploads rejected with 413

**Symptom (2026-09-03):** every v5 tape (agent 0.3.35 and later, 3–14 MB gzipped) fails `POST /rr/gamestate` with
HTTP 413. No v5 tape has reached the server; the agent's local spool holds them (34 tapes, 259 MB on the owner's box).
Agent 0.3.42+ parks a 413-rejected tape for 6 h (`.toolarge` marker) instead of retrying every idle cycle.

**Cause (read-only, server repo):**
- `server/src/config.rs:25` `GS_MAX_BODY = 8 * 1024 * 1024` — the envelope carries `frames_gz` as base64, so a 6 MB gz
  tape is already an 8 MB body.
- `server/src/receipt.rs:61` `TAPE_MAX_GZ = 3_000_000` and `:107` `REPLAY_MAX_GZ = 3_000_000` — inline-parse guards.
- nginx `/rr/` already allows `client_max_body_size 64M` (`/etc/nginx/sites-enabled/nobd-web:221`).

**Proposed change (lane 1 decides):**
```diff
--- server/src/config.rs
-pub(crate) const GS_MAX_BODY: usize = 8 * 1024 * 1024; // 8 MB cap for a game-state recording upload
+pub(crate) const GS_MAX_BODY: usize = 64 * 1024 * 1024; // 64 MB (matches nginx); v5 tapes are 3-14 MB gz = 4-19 MB base64
--- server/src/receipt.rs
-    const TAPE_MAX_GZ: u64 = 3_000_000;
+    const TAPE_MAX_GZ: u64 = 24_000_000;
-    const REPLAY_MAX_GZ: u64 = 3_000_000;
+    const REPLAY_MAX_GZ: u64 = 24_000_000;
```
Consider also accepting the gz stream raw (no base64) on a new endpoint; the agent can switch when it exists.
Storage: `enforce_gamestate_cap` (app.rs:1823) already bounds the directory; check its budget against ~5 MB/match.

**After the change:** the agent re-drains automatically when the 6 h marker expires, or delete
`%LOCALAPPDATA%\RetroReceipts\gs-cache\*.toolarge` to re-drain immediately. Verify with the trace line
`[gamestate] uploaded <key> (<n> bytes gz)`.
