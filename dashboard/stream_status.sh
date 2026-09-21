#!/usr/bin/env bash
# HTTP status of every agent's SSE stream, plus how many slots the server has left.
#   bash <(tr -d '\r' < dashboard/stream_status.sh)
set -u
BASE='http://127.0.0.1:8787'
names="$(curl -s "$BASE/api/agents" \
  | python3 -c 'import json,sys; print(" ".join(a["name"] for a in json.load(sys.stdin)["agents"]))')"
for name in $names; do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$BASE/api/stream/$name?tail=1024")"
  state="$(curl -s "$BASE/api/agents" | python3 -c "
import json, sys
for a in json.load(sys.stdin)['agents']:
    if a['name'] == '$name':
        print(a.get('state'), str(a.get('cols')) + 'x' + str(a.get('rows')))
        break
")"
  printf '  %-12s HTTP %-4s %s\n' "$name" "$code" "$state"
done
