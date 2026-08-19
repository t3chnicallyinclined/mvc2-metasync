# Tournament Real-Time Architecture — Redis push, phased

Status: **✅ AS-BUILT / DEPLOYED LIVE (2026-08-18, client 0.1.98).** Phases 0–2 shipped and validated end-to-end on prod (`nobd.net`) with real clients on Windows + Bazzite. Goal: make tournament mode smooth and correct at **32–64+ concurrent users per event** (and multiple concurrent events), with sub-second bracket/standings/alert updates, on the existing single small VPS.

Grounded in a full audit of `skinsync/` (server) + `web/index.html` / `src-tauri/src/sync.rs` (client) and current NATS/Redis practice (Aug 2026). Sections 1–7 below are the design; the box here is what actually shipped.

> ### AS-BUILT summary (what's running now)
> - **Redis 7.0.15** on the VPS (localhost, AOF everysec, 256MB `noeviction`) — pub/sub + capped Streams. Transport/log only; skinsync memory+JSON stays authoritative.
> - **skinsync `bus.rs`** (added): background publisher thread; every mutating `tourney::*` handler calls `bus.publish` → `XADD tourney:{tid}:log MAXLEN ~ 500` (entry id = seq) + `PUBLISH tourney.{tid}`. Best-effort, `SKINSYNC_BUS` gated. **Phase 0** also landed: `mirror_tournament` off-threaded; per-event `tournaments/<id>.json` (no more whole-file rewrite per heartbeat).
> - **push-gateway** (new crate `push-gateway/`, tokio+axum+redis async) → `/opt/push-gateway`, systemd `push-gateway.service`, **`127.0.0.1:7251`**. SSE `GET /tourney/{id}/stream`: snapshot-on-connect (unwraps the `{ok,tournament}` envelope so it carries the doc), live via `SUBSCRIBE`, reconnect gap-fill via `XRANGE` + `Last-Event-ID`. Env `GATEWAY_ADDR`, `SNAPSHOT_BASE=http://127.0.0.1:7250/skinsync`, `REDIS_URL`.
> - **nginx** `location /skinsync/rt/` → `http://127.0.0.1:7251/` (buffering off, `Connection ""`, 1h read timeout). Public SSE = `https://nobd.net/skinsync/rt/tourney/{id}/stream`.
> - **Client 0.1.98**: `tourney_subscribe`/`_unsubscribe` in `sync.rs` (reused `ureq` streaming, no new dep) → `emit("tourney-delta")`; `tnyApplyDelta` patches `TNY.data` in place; 5s poll replaced by a 30s safety-poll fallback.
> - **Ops:** cargo lives at `~/.cargo/bin` on the VPS (not in non-login PATH); swap a running binary with `cp .new && mv -f` (plain `cp` = "Text file busy"). Rollback backups at `/root/rt-rollback-*`. Redis 8.x upgrade + `requirepass` + presence-as-single-zset are the deferred hardening backlog (§6b).

---

## 0. TL;DR — the decision

- **The scaling win is the PUSH/DELTA model, not the broker.** 5 s full-state polling → sub-second per-field deltas: ~10× latency, ~50× less bandwidth, and the per-poll full-doc serialization on the single server thread disappears.
- **Redis alone covers it. No NATS at this scale.** Redis pub/sub (live fan-out) + a capped Redis Stream (replayable log / gap-fill) + Hash/TTL (presence). NATS is a *Phase-4 option* only for native-WebSocket-to-client + per-SteamID subject authz — never a capacity requirement.
- **Transport = SSE, hybrid command path.** Server→client push over **Server-Sent Events** (unidirectional, dead-simple, sails through nginx). Client→server **commands stay on the existing HTTP** (already built + authed). The Tauri Rust backend holds one SSE connection and bridges to the webview via `emit`.
- **Do NOT move state into Redis yet.** Once push replaces polling, the single-threaded command server is no longer a bottleneck (its heavy load *was* the polls). Keep the in-memory + JSON state; add Redis purely as the **pub/sub + event-log transport**. Redis-as-state-store is a later, optional scale step.
- **Minimal-invasive, incremental, each phase shippable and independently valuable.**

---

## 1. Current state — the bottlenecks (audited, quantified)

The server (`skinsync/src/main.rs:141`) is **single-threaded**: `for req in server.incoming_requests() { handle(&mut app, req) }` — exactly one request in flight, ever. No locks (single-owner `&mut App`), but **every request across every feature queues behind the current one**.

| # | Problem | Evidence | Impact at 64 users |
|---|---|---|---|
| 1 | **Full-doc serialization per poll** | `tourney::get` does `serde_json::to_value(t)` on the whole `Tournament` (63 matches + 32 regs + hosts ≈ **30 KB**, up to ~80 KB with an inline banner) — every poll | 64 clients × (1/5s) = **12.8 get/s** re-serializing ~30 KB unchanged → **~385 KB/s–1 MB/s** egress for ONE event, mostly resending identical bytes |
| 2 | **5 s update latency** | `setInterval(tnyPoll, 5000)` → `tourney_get`; no push | a reported result / opened lobby / "you're up" alert lags up to 5 s |
| 3 | **Poll-flap band-aid** | `if(!t && TNY.data...) t=TNY.data` (keep last-good) exists only because polls blip to "not found" and flap the view | masks the reliability gap, doesn't close it |
| 4 | **Per-IP rate-limit NAT collisions** | token bucket 60 burst / 6-sustained per public IP (`app.rs:252`), keyed on last `X-Forwarded-For` hop | players on one venue LAN / household share one bucket → **429s** → trips the flap band-aid |
| 5 | **Total serialization (single thread)** | `main.rs:141` | a slow tournament write, a `/result` records rebuild, or an **8 MB gamestate upload** freezes tournament polling for *everyone* |
| 6 | **SurrealDB mirror ON the write path, synchronously** | `mirror_tournament` → `ureq…timeout(3s)` (`surreal.rs:83`) on the request thread (unlike player/match mirror which is spawned off-thread) | every register/checkin/report/host_assign/lobby_report can **stall the whole server up to 3 s** if Surreal is slow |
| 7 | **Whole-file JSON rewrite per write** | `save_tournaments()` re-serializes + rewrites **all events** in `tournaments.json` on every write — **including every 6 s host heartbeat** | write cost grows with total stored events, not the change size |
| 8 | **No isolation across events** | one thread, one rate map, one `tournaments.json` | concurrent live events compound instead of isolating |

**The load-bearing insight:** a `Tournament` is **~90 % immutable after `start`** (schedule, rules, routing topology, seeds). The bytes that actually change during play are a *tiny* surface:
- per-match: `state`, `winner`, `score`, `host`, `lobby_id` (~5 fields on ~1 of 63 matches at a time)
- per-host presence: `lobby_id`, `members`, `active`, `last_seen_ms` (every 6 s)

Yet today we **ship and rewrite the entire doc** on every change and every poll. Push exactly those deltas and problems 1–3 collapse; move the mirror off-thread and stop full-file rewrites and 5–7 collapse; a persistent SSE connection (not repeated polls) neutralizes 4 and 8.

---

## 2. Target architecture

```
                          ┌───────────────────────────────────────────────┐
   Tauri client(s)        │                 nobd.net VPS                   │
 ┌──────────────┐  HTTP   │  ┌───────────────┐   publish    ┌───────────┐  │
 │ webview (JS) │◄──cmd──►│  │  tiny_http     │──delta──────►│  Redis    │  │
 │   listen()   │  invoke │  │  (commands)    │  XADD+PUBLISH│ pub/sub + │  │
 │      ▲       │         │  │  in-mem + JSON │              │  Stream   │  │
 │   emit│      │         │  │  (authoritative)│             │  + TTL    │  │
 │ ┌────┴─────┐ │  SSE    │  └───────────────┘              └─────┬─────┘  │
 │ │ Rust core│◄├─────────┼─────────────────────────────────────┐│        │
 │ │ 1 SSE conn│ │ (push)  │  ┌───────────────────────────────┐  ││ SUBSCRIBE
 │ └──────────┘ │         │  │  push-gateway (tokio/axum, async)│◄┘│ + XRANGE
 └──────────────┘         │  │  holds N long-lived SSE conns    │──┘        │
                          │  │  snapshot-on-connect + deltas    │           │
                          │  └───────────────────────────────┘           │
                          └───────────────────────────────────────────────┘
```

**Three roles, clean separation:**
- **`tiny_http` (existing) — the command/write path.** Keep it. Handlers mutate the in-memory + JSON state as today, then **additionally** `XADD` the delta to a capped Redis Stream and `PUBLISH` it. That's the only new code on the write path. It stays cheap because push kills the poll load (its heaviest job).
- **Redis — the transport + event log.** `PUBLISH tourney.{id} <delta>` for live fan-out; `XADD tourney:{id}:log MAXLEN ~ 500 * …` as the ordered, replayable log (entry IDs = sequence numbers); TTL keys for presence. **State stays authoritative in tiny_http; Redis is the message bus, not (yet) the store.**
- **push-gateway (new, async tokio/axum) — the read/push path.** Holds the long-lived **SSE** connections (async → thousands cheaply, unlike single-threaded tiny_http). On connect: send a **full snapshot** + current seq; then **`SUBSCRIBE tourney.{id}`** and stream deltas; on reconnect (`Last-Event-ID`): **`XRANGE`** the gap and replay, or resend a snapshot if the gap is older than the log window.

**Client:** the Tauri **Rust backend holds one SSE connection**, parses events, and `emit`s them to the webview (`@tauri-apps/api/event` `listen`). The webview never touches Redis or the gateway directly — one connection per client process, all reconnect logic in Rust, no broker creds in JS. Commands still go webview→`invoke`→Rust→**HTTP** (unchanged).

### 2.1 Delta protocol (concrete)
Per-event messages (NOT JSON-Patch, NOT full event-sourcing). Every delta carries the tournament id, a monotonic `seq` (the Redis Stream entry id), a `type`, and only the changed fields:
```jsonc
{ "tid":"nobd-test-2", "seq":"1723999999999-0", "type":"match_update",
  "mid":7, "state":"done", "winner":"7656…", "score":"2-1" }
{ "tid":"…", "seq":"…", "type":"host_update",
  "steamid":"7656…", "lobby_id":"1097…", "active":1, "members":["…","…"] }
{ "tid":"…", "seq":"…", "type":"bracket_advance", "matches":[{mid, p1, p2, state}] }
{ "tid":"…", "seq":"…", "type":"status", "status":"running" }
{ "tid":"…", "seq":"…", "type":"alert", "audience":"7656…", "kind":"call_to_station", "mid":7 }
```
- **Snapshot on connect** (never apply deltas onto an unknown base): the gateway sends `{type:"snapshot", seq:<stream head>, tournament:<full doc>}` first, then live deltas.
- **Gap detection:** client tracks last applied `seq`. On a gap → gateway `XRANGE tourney:{id}:log (lastSeq +` fills exactly the missing events; if `lastSeq` is older than the capped window → send a fresh snapshot instead.
- **SSE mechanics:** each delta is one SSE event with `id: <seq>`; the browser/Rust reconnect sends `Last-Event-ID: <seq>` automatically → the gateway resumes precisely. This is why SSE (not raw WS) is the sweet spot here — gap-fill is built into the protocol.

### 2.2 Redis key/channel map
| Purpose | Redis | Notes |
|---|---|---|
| Live fan-out | `PUBLISH tourney.{id} <delta>` | gateway `SUBSCRIBE`s per open tournament |
| Event log / gap-fill | `XADD tourney:{id}:log MAXLEN ~ 500 * …` | entry id = seq; ring buffer for reconnect |
| Presence | `SET presence:{id}:{steamid} 1 EX 30` (heartbeat refresh) | crash = auto-expire, no cleanup |
| "Who's active" | `ZADD tourney:{id}:online <ts> <steamid>` | cheap "active in last 2 min" |
| (Phase 5, optional) state | `HSET tourney:{id} …` / RedisJSON | only if we move to multi-instance |

---

## 3. The workstream — phased, each shippable

### Phase 0 — Stop the stalls (no new infra, hours) — *do first*
The two write-path stalls are pure wins independent of everything else.
1. **Move the SurrealDB tournament mirror OFF the request thread.** `App::mirror_tournament` → spawn the `ureq` round-trip like the player/match mirror already does (`mirror.rs:44`). Kills pain #6 (the 3 s freeze-everyone).
2. **Stop rewriting the whole `tournaments.json` per write.** Either (a) write **one file per tournament** (`tournaments/{id}.json`) so a heartbeat rewrites only that event, or (b) **debounce** `save_tournaments` (coalesce writes on a ~1 s timer). Kills pain #7.
   - Simplest: per-tournament files + a debounce on the whole-map save. Keep the `.deleted.jsonl` archive.
- **Risk:** low. **Rollback:** revert two functions. **Ships as a normal server deploy.**

### Phase 1 — Redis transport + delta publish (server side, ~1–2 days)
1. Stand up **Redis 8.x** on the VPS (127.0.0.1, `appendonly everysec`, `maxmemory` + `volatile-ttl` so presence TTLs evict but the log/state can't be dropped). Footprint is negligible next to tiny_http.
2. Add a thin `bus.rs` to `skinsync/`: a `redis` `MultiplexedConnection` (auto-reconnect via `connection-manager`); `publish_delta(tid, delta)` = `XADD tourney:{tid}:log MAXLEN ~ 500 * event <json>` **then** `PUBLISH tourney.{tid} <json-with-seq>`. Best-effort (a Redis blip must never break a command — log + continue, exactly like the Surreal mirror contract).
3. In each mutating `tourney::*` handler, after the existing mutate+save, **emit the minimal delta** (match_update / host_update / bracket_advance / status / registration / alert). This is the bulk of the work but it's mechanical and additive — the handlers otherwise unchanged.
- **Risk:** low (additive; no client change yet; deltas just accumulate in Redis unread). **Rollback:** feature-flag `SKINSYNC_BUS=0`. **Value alone:** none user-visible yet — sets up Phase 2.

### Phase 2 — Push gateway + client SSE (the UX win, ~2–3 days)
1. **New async binary** `push-gateway` (tokio + `axum`), same VPS: `GET /tourney/{id}/stream` (SSE). On connect: fetch the snapshot (internal `GET` to tiny_http `/tourney/get`, or read the JSON), send `snapshot` event with the current stream head as `seq`; `SUBSCRIBE tourney.{id}`; stream deltas as SSE events (`id:` = seq). On `Last-Event-ID`: `XRANGE` the gap or resend snapshot. nginx: proxy `/skinsync/stream/…` → gateway, `proxy_buffering off; proxy_read_timeout 1h;`.
2. **Client (`src-tauri/src/sync.rs`):** a `tourney_subscribe(id)` command that opens the SSE stream (reqwest streaming or an SSE crate), parses events, and `app.emit("tourney-delta", …)`; auto-reconnect with `Last-Event-ID`.
3. **Client (`web/index.html`):** on entering a tournament, call `tourney_subscribe`; `listen('tourney-delta')` → apply deltas to `TNY.data` and re-render the affected piece (match card, standings row, host chip, alert). **Replace the 5 s `tnyPoll`** with the subscription; keep a **slow 30 s poll as a safety net** (belt-and-suspenders) and the "keep last-good" only as a true-failure guard.
4. Presence: the host heartbeat / a light client ping refreshes `presence:{id}:{steamid}`; the gateway can publish join/leave.
- **Risk:** medium (new component + client change). **Rollback:** clients fall back to the 30 s poll if SSE fails to connect; the gateway is independent of tiny_http (if it's down, commands still work). **Value:** sub-second updates, ~50× less bandwidth, no flap, NAT-safe (one persistent conn, not repeated polls) — **this is the deliverable that makes tournament mode smooth.**

### Phase 3 — Trim the command path (~1 day, optional)
- Host heartbeat → publish a `host_update` delta (already added in P1) and refresh presence TTL; the heartbeat can go to a **lighter cadence** (10 s) since presence is now TTL-based, not poll-inferred.
- Consider per-SteamID identity for rate-limit bucketing (fixes NAT collisions #4 more directly than IP), or simply exempt the (now-rare) command traffic — polling was the volume, and it's gone.

### Phase 4 — NATS (optional, only if earned)
Adopt `async-nats` **0.50** over **WSS/443** *only* if we want: native WebSocket straight to desktop clients (retire the SSE gateway), per-SteamID **subject authz** (decentralized JWT scoped to `player.<steamid>.>`), or multi-server queue-group routing. **Not a scale need at 64–256 users** — an ergonomics/security choice. Redis stays the state/log store; NATS becomes only the client fabric.

### Phase 5 — Redis as state store (optional, only for horizontal scale)
Move the authoritative tournament doc into Redis (Hash or RedisJSON) so multiple stateless tiny_http/gateway instances can serve one event. Removes the last single-thread/single-file coupling. **Only needed beyond one server / for many simultaneous large events.** At current scale, skip.

---

## 4. Scale math (why this is enough)
- **Today:** 64 clients × full-doc poll / 5 s = **12.8 get/s × ~30 KB = ~385 KB/s**, single-threaded, per event.
- **After Phase 2:** 64 persistent SSE conns (idle, ~0 bytes), + deltas **only when something changes** (a report ≈ a few hundred bytes fanned to 64 = ~tens of KB, *once*). Steady-state egress drops from ~385 KB/s to **~kilobytes/minute**. Get load on tiny_http drops from 12.8/s to ~1 snapshot per client-connect. The single thread now trivially serves the residual command traffic (a few req/s).
- Redis on a small VPS: sub-100 MB, microsecond pub/sub, a 500-entry capped stream per event = kilobytes. Three concurrent 64-player events are still negligible.
- **Honest overkill check:** the **push model is not overkill** — it's the actual upgrade (latency + bandwidth + reliability). **NATS *would* be mild overkill now** — hence Phase 4-optional. Redis + SSE is the right-sized answer.

---

## 5. Crate / infra stack (verified Aug 2026)
| Component | Pick | Version | Notes |
|---|---|---|---|
| Redis client (Rust) | `redis` | **1.6.0** | stable 1.x; `tokio-comp`, `connection-manager` (auto-reconnect), `MultiplexedConnection` (cheap-clone, no pool needed unless blocking cmds) |
| Redis pool (only if blocking `XREAD`) | `deadpool-redis` | 0.23.0 | give blocking stream reads their own conn |
| Push gateway | `axum` + `tokio` | current | `axum::response::sse` is first-class; async holds many conns |
| Client SSE | `reqwest` (stream) or `eventsource-client` | current | Tauri backend; `Last-Event-ID` reconnect |
| Redis server | Redis | **8.x** | Streams/JSON in-core; `appendonly everysec` + `maxmemory` |
| NATS (Phase 4 only) | `async-nats` | 0.50 | WS+TLS default features; JWT subject authz |
| nginx | existing | — | proxy SSE (`proxy_buffering off`), later WSS/443 for NATS |

---

## 6. Risks & rollback
- **Redis down** → `publish_delta` is best-effort (log+continue); commands + JSON persistence unaffected; clients fall back to the 30 s safety poll. No hard dependency introduced.
- **Gateway down** → commands (tiny_http) keep working; clients fall back to the 30 s poll. Independent failure domains.
- **SSE through corporate/venue proxies** → some strip streaming; the 30 s poll fallback covers it. (Phase 4 NATS/WSS would be more robust there if it ever matters.)
- **Delta/snapshot drift** → snapshot-on-connect + seq-gap-fill + a periodic reconcile (client re-snapshots every N minutes) guarantee convergence; JSON stays authoritative.
- **Every phase is independently revertible** (feature flags: `SKINSYNC_BUS`, gateway on/off, client SSE-vs-poll), and Phases 0–2 deliver ~all the value before any optional work.

---

## 6b. Redis expert review — findings + hardening backlog (2026-08-18)
An independent Redis/distributed-systems review validated the design: **it needs nothing newer than Redis 6.2** — pub/sub + a capped Stream + a zset for presence are all mature primitives, and there is no missing feature. Confirmed correct as-designed: keep **both** pub/sub (live) + Stream (`XRANGE` gap-fill) and **never** add consumer groups (single gateway = broadcast, not work-distribution); `MAXLEN ~ 500` (approximate trim) is the right form; `maxmemory-policy noeviction` is correct (log/presence must never be evicted); AOF `everysec` is right. Explicitly NOT worth it here: consumer groups, sharded pub/sub (`SSUBSCRIBE` is Cluster-only), keyspace notifications (unreliable pub/sub + lazy-expiry lag — diff the zset instead), `CLIENT TRACKING`, `io-threads`/`activedefrag`, Dragonfly, and in-core JSON/Search (revisit only if Redis ever becomes the state store).

**Hardening backlog (deferred out of the build sprint — maintenance, not blockers):**
1. **Upgrade Redis 7.0.15 → stock 8.2.x/8.10** (official apt repo). 7.0 is upstream-EOL; this is a security/maintenance move, RESP-compatible, config carries over. AGPLv3 self-host imposes no obligation on our app (clients talk to our server, never to Redis). Do it in a calm window.
2. **Add `requirepass`/ACL** even on localhost (Redis shares the VPS with the HTTP server). Requires updating `REDIS_URL` in both the server env and the gateway systemd unit in lockstep. Keep `timeout 0` so the gateway's long-lived pub/sub connections aren't reaped.
3. **Presence refinement:** implement presence as a **single sorted set per tournament** scored by last-heartbeat ms (`ZADD tourney:{id}:online <now> <steamid>`; online = `ZRANGEBYSCORE (now-30 +inf`; reap via periodic `ZREMRANGEBYSCORE -inf (now-30)`) — ordered/range-by-time, fewer keys, works on 7.0 now. Prefer this over `HEXPIRE` hash-field TTL (needs 7.4+, loses ordering).

## 7. Recommended order of execution
1. **Phase 0** (hours) — off-thread the mirror + stop whole-file rewrites. Ship immediately; pure win.
2. **Phase 1** (1–2 d) — Redis + delta publishing (dark; no client change).
3. **Phase 2** (2–3 d) — push gateway + client SSE + replace the poll. **This is the "tournament mode is smooth" release.**
4. Phases 3–5 as/if the platform grows. NATS and Redis-as-store are explicitly *optional*, not on the critical path.
</content>
