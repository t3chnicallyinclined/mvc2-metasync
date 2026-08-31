# DEPLOY — session-fragmentation display fix (fix #2)

Land the two edits in EDITS.md, build with the tb feature, staging-then-prod swap per the rr-server
recipe, bust the OG image cache, then verify the wenzel card reads 9-1 with no regressions.
DISPLAY-ONLY: no matches.json write, no money/ledger touch, no schema change.

- Server:        root@149.28.44.118 (VPS)
- rr-server:     127.0.0.1:7250  (systemd unit: rr-server)  live binary: /opt/rr-server/rr-server
- source clone:  /opt/rr-server-src   (build here: /root/.cargo/bin/cargo)
- staging:       /opt/rr-staging  127.0.0.1:7260  (unit: rr-staging; own snapshot, RR_BUS=0, no Surreal)
- ogimg cache:   /opt/rr-server/ogcache/   (100% derived — safe to wipe)

The checker (verify.sh + verify.py) lives in this folder. Copy it to the box first:

```bash
scp verify.py verify.sh root@149.28.44.118:/root/rrfix/
```

## 0. Pre-flight snapshot (BEFORE any change)

Record the current counts so you can diff after. Run on the box (or set RR_BASE):

```bash
cd /root/rrfix
bash verify.sh s_76561197999665347_76561198029172402_1a0555f2765   # TARGET  — expect count 8 (the bug)
bash verify.sh s_76561198029172402_76561197999665347_1a0555f010f   # SIBLING — expect count 2, idx [2,7]
bash verify.sh s_76561197999665347_76561198060934479_1a05504e43d   # CONTROL — record its count; must NOT change
```

Pre-fix expectation: TARGET count 8 (idx 0,1,3,4,5,6,8,9), SIBLING count 2 (idx 2,7). Both VERDICT PASS
(the invariant holds even while fragmented — that is why the bug is invisible to a naive check).

## 1. Apply the two edits

Apply EDIT 1 (server/src/stats.rs) and EDIT 2 (server/src/routes.rs) from EDITS.md — each is an exact
OLD -> NEW find/replace. Then confirm both landed:

```bash
cd /opt/rr-server-src
grep -n "merged_session_ids" server/src/stats.rs server/src/routes.rs
```

Expect 3 hits: the fn definition + its call in session_stats (stats.rs), and one call in og_preview (routes.rs).

## 2. Build (release, tb feature)

The cfg(tb) code's first real compile happens here (tb does not build on Windows). A failed build
leaves the OLD binary untouched — safe. Only proceed once it prints "Finished".

```bash
cd /opt/rr-server-src
/root/.cargo/bin/cargo build --release --features tb
```

## 3. Staging swap + smoke (rr-staging on :7260)

```bash
systemctl stop rr-staging
cp -f /opt/rr-server-src/target/release/rr-server /opt/rr-staging/rr-server
systemctl start rr-staging
sleep 1
curl -s http://127.0.0.1:7260/skinsync/health
```

Smoke: the binary boots + serves. The staging SNAPSHOT predates today's games, so the wenzel set is
likely absent there — that is fine; staging proves the build runs, prod (step 6) proves the fix. If the
set IS present in the snapshot, run step 6's checks with RR_BASE=http://127.0.0.1:7260.

## 4. Prod swap

Stop first (a cp over the RUNNING binary gives "Text file busy"). Keep a .bak for instant rollback.

```bash
systemctl stop rr-server
cp -f /opt/rr-server/rr-server /opt/rr-server/rr-server.bak
cp -f /opt/rr-server-src/target/release/rr-server /opt/rr-server/rr-server
systemctl start rr-server
sleep 1
curl -s http://127.0.0.1:7250/skinsync/health
```

## 5. Bust the OG image cache (REQUIRED)

ogimg caches PNGs at /opt/rr-server/ogcache/<sid>.png and writes <sid>.done when a set is fully verified.
A fully-verified set caches an IMMUTABLE card, so any stale 8-0 .png + .done that exists sits there and will NOT re-render on their
own. The cache is 100% derived (re-generated on next request), so wipe it:

```bash
ls /opt/rr-server/ogcache/ | head
rm -f /opt/rr-server/ogcache/*
```

External unfurl caches (Discord/Facebook/Twitter) are out of our control — re-scrape via each platform's
debugger if an already-shared link needs its thumbnail refreshed.

## 6. VERIFY the effect (prod)

(a) TARGET card now reads 9-1 over 10 games, indices 0..9 (Tris's win at index 2 is back):

```bash
cd /root/rrfix
bash verify.sh s_76561197999665347_76561198029172402_1a0555f2765
```
Expect: count 10 | match_idx [0,1,2,3,4,5,6,7,8,9] | score TRIS NOBDOG 1-9, Wenzel 9-1 | VERDICT PASS

(b) the SIBLING id renders the SAME complete set (the union is symmetric — a share of either link is whole):

```bash
bash verify.sh s_76561198029172402_76561197999665347_1a0555f010f
```
Expect: count 10 | VERDICT PASS

(c) the OG HTML meta (scraper user-agent) now says 9-1:

```bash
curl -s -A "facebookexternalhit/1.1" "http://127.0.0.1:7250/s/1a0555f2765" | grep -io "Wenzel 9-1 TRIS NOBDOG"
```
Expect the title to contain: Wenzel 9-1 TRIS NOBDOG  (and og:description "10 games ...").

(d) the PNG fight card regenerates (fresh bytes after the scrape):

```bash
curl -s "http://127.0.0.1:7250/rr/ogimg/s_76561197999665347_76561198029172402_1a0555f2765.png" -o /tmp/card.png
ls -la /tmp/card.png /opt/rr-server/ogcache/s_76561197999665347_76561198029172402_1a0555f2765.png
```

(e) REGRESSION — the CONTROL set's count is UNCHANGED vs step 0:

```bash
bash verify.sh s_76561197999665347_76561198060934479_1a05504e43d
```
Expect: SAME count as the step-0 snapshot, VERDICT PASS.

(f) broad over-merge sweep — spot-check other recent sets. List recent distinct session ids, then run
verify.sh on each; ANY "FAIL - over-merge detected" is a real regression to investigate:

```bash
curl -s "http://127.0.0.1:7250/skinsync/history?steamid=76561198029172402&limit=50" -o /tmp/h.json
python3 -c "import json; rows=json.load(open('/tmp/h.json'))['rows']; print(chr(10).join(sorted(set(r['session_id'] for r in rows if r['session_id']))))"
# then for each id printed:  bash verify.sh <id>   (every one must say VERDICT PASS)
```

## 7. Docs

Append the line in DATA-STACK-NOTE.txt to docs/DATA-STACK.md (both the /opt/rr-server-src copy and your
local RetroReceipts-server clone), then commit it alongside the two src edits.

## Rollback (display-only, instant)

```bash
systemctl stop rr-server
cp -f /opt/rr-server/rr-server.bak /opt/rr-server/rr-server
systemctl start rr-server
rm -f /opt/rr-server/ogcache/*
```

Nothing to undo in DATA — no matches.json, ledger, wager, rail, or schema was touched. The .bak is the
pre-fix binary; the ogcache wipe drops any 9-1 cards the new binary rendered so the old one re-renders 8-0.
