#!/usr/bin/env python3
# Over-merge / correctness check for ONE set card (post session-fragmentation fix).
# Reads /skinsync/session JSON from a file arg or stdin. Asserts the universal invariant:
# all games share ONE unordered pair AND no match_index repeats. Exit 0 = PASS, 1 = FAIL.
# Also prints count + per-player score so you can eyeball the expected tally (e.g. 9-1).
import sys, json
src = open(sys.argv[1]) if len(sys.argv) > 1 else sys.stdin
d = json.load(src)
sid = d.get("session_id", "?")
games = d.get("games", [])
pairs = sorted({ tuple(sorted((g["winner"], g["loser"]))) for g in games })
idxs = [g["match_index"] for g in games]
dupes = sorted({ i for i in idxs if idxs.count(i) > 1 })
players = d.get("players", [])
score = ", ".join(f"{p['name']} {p['wins']}-{p['losses']}" for p in players)
print("session_id :", sid)
print("count      :", d.get("count"))
print("pairs      :", len(pairs), pairs)
print("match_idx  :", sorted(idxs))
print("dup idx    :", dupes if dupes else "none")
print("score      :", score)
ok = (len(pairs) <= 1) and (not dupes)
print("VERDICT    :", "PASS (no over-merge)" if ok else "FAIL - over-merge detected")
sys.exit(0 if ok else 1)
