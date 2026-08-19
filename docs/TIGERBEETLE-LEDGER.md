# 🪙 QUARTERS on TigerBeetle — the ledger design

The quarters economy (free play-coins: everyone starts with 20, stake them on tournament entries and
match wagers, champion/winner takes the pot) runs on **TigerBeetle**, the purpose-built double-entry
accounting database, fronted by the `skinsync` server as the API + policy layer. The resident agent for
this domain is **tigerbeetle-expert** (`.claude/agents/tigerbeetle-expert.md`) — use it for any ledger
work; it carries the doc links, schema conventions, and TigerStyle rules.

## Why TigerBeetle
- **Double-entry enforced by the database**: every transfer debits one account and credits another;
  player accounts carry `debits_must_not_exceed_credits`, so overspending is impossible below the app.
- **Idempotency as a primitive**: transfer ids are client-chosen; a retried request returns `exists`
  instead of double-moving quarters. Perfect fit for SSE races and crash-retry paths.
- **Linked transfers**: winner-payout + host-fee settle as one atomic pair — both land or neither.
- **Built for the vision**: one cluster, one `ledger` number per game/currency, ~1M transfers/sec via
  batching — hundreds of retro-game lobbies later is a schema question we already answered, not a
  re-architecture.

## The shape
```
player account id   = SteamID64 (u128)
treasury            = account id 1 (the mint; may go negative)
tournament escrow   = sha256("escrow:<slug>")[..16]
match escrow        = sha256("mescrow:<match_key>")[..16]
ledger              = 700 (quarters) — new game/currency = new ledger number
code                = flow kind (1 genesis · 2 entry · 3 refund · 4 payout · 5 grant · 6-9 match flows)
transfer id         = sha256("<flow>:<refs>")[..16]  — the idempotency key
genesis             = 20 quarters, treasury→player, lazily on first touch
```

## Flows
- **Tournament**: register → `entry` player→escrow; drop/DQ/no-show/delete → `refund` escrow→player;
  champion at `done` → `payout` sweeps the escrow. (Live today.)
- **Match wager (per-match quarter-up, approved design)**: both stakes → `mescrow:<match_key>`;
  on result a LINKED pair settles `escrow→winner` (pot − fee) + `escrow→host` (flat 1-quarter fee,
  **neutral hosts only** — a playing host earns no fee); DC/timeout (~30 min TTL) → auto-refund both.
  The machine holds the pot — players trust the referee that read the KO, not each other.

## Resilience contract
TigerBeetle is **authoritative** when reachable (env `SKINSYNC_TB=<addr>`); the append-only
`ledger.jsonl` journal is the human-readable mirror + outage fallback so a coin-DB hiccup can never
stop matches. Divergence between the two is logged loudly, never papered over.

## Documentation (canonical)
- Docs root: https://docs.tigerbeetle.com/
- Account / Transfer / Requests reference: https://docs.tigerbeetle.com/reference/
- Coding guides + recipes (two-phase, linked events, reliable submission): https://docs.tigerbeetle.com/coding/
- TIGER_STYLE (the engineering philosophy this codebase's ledger work follows):
  https://github.com/tigerbeetle/tigerbeetle/blob/main/docs/TIGER_STYLE.md
- Rust client (community wrapper over the official tb_client): https://crates.io/crates/tigerbeetle-unofficial
