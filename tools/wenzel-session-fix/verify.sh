#!/usr/bin/env bash
# verify.sh — fetch one set card and run the over-merge check. Run from THIS folder (needs verify.py here).
# Usage:  bash verify.sh <session_id>          [RR_BASE overrides http://127.0.0.1:7250]
# On the VPS:  scp this folder up, or paste verify.py + run against 127.0.0.1:7250.
set -euo pipefail
SID="${1:?usage: bash verify.sh <session_id>}"
BASE="${RR_BASE:-http://127.0.0.1:7250}"
TMP="/tmp/rr_sess.$$.json"
curl -fsS "$BASE/skinsync/session?id=$SID" -o "$TMP"
python3 verify.py "$TMP"
rm -f "$TMP"
