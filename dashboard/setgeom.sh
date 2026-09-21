#!/usr/bin/env bash
# Set every agent pane to a given geometry, through the dashboard's own /api/resize.
# From the repo root inside WSL:
#   bash <(tr -d '\r' < dashboard/setgeom.sh) 200 50
#
# A file rather than a one-liner because the JSON body has to survive
# wsl.exe -> bash -> curl, and it kept being mangled inline.
set -u
COLS="${1:-200}"
ROWS="${2:-50}"
BASE='http://127.0.0.1:8787'

names="$(curl -s "$BASE/api/agents" \
  | python3 -c 'import json,sys; print(" ".join(a["name"] for a in json.load(sys.stdin)["agents"]))')"
[ -n "$names" ] || { echo 'no agents'; exit 1; }

for name in $names; do
  body="$(printf '{"cols":%d,"rows":%d}' "$COLS" "$ROWS")"
  out="$(curl -s -w '\n%{http_code}' -X POST -H 'Content-Type: application/json' \
         --data "$body" "$BASE/api/resize/$name")"
  code="$(printf '%s' "$out" | tail -1)"
  printf '  %-12s -> HTTP %s  %s\n' "$name" "$code" "$(printf '%s' "$out" | head -1)"
done

sleep 2
echo '--- geometry now ---'
# No escaped quotes inside this single-quoted program: a backslash-quote survives the
# shell layers literally and Python then rejects it.
curl -s "$BASE/api/agents" | python3 -c '
import json, sys
for a in json.load(sys.stdin)["agents"]:
    name = a["name"]
    print("  " + name.ljust(12) + " " + str(a.get("cols")) + "x" + str(a.get("rows")))
'
