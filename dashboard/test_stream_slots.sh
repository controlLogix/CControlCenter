#!/usr/bin/env bash
# Prove the SSE slot pool cannot be exhausted by repeated page loads.
#   bash <(tr -d '\r' < dashboard/test_stream_slots.sh) [rounds]
#
# THE BUG THIS GUARDS. A browser reload opens a fresh EventSource per pane while the
# previous ones are still established; the server cannot tell a client has gone until it
# next tries to write. Seven panes over a couple of reloads consumed all sixteen slots,
# and three panes then sat at HTTP 503 rendering nothing — which looks exactly like a
# dead agent. Each agent now holds at most one stream, so the ceiling is the agent count
# rather than the reload count.
#
# NOT IN THE GATE, deliberately rather than by omission. This needs /api/agents
# to return REAL agents; the gate's dashboard runs on a throwaway AGENTMUX_HOME
# with none, so it would exit 1 with "no agents to test" for a reason that has
# nothing to do with the guard. It also talks to 8787 directly, which the gate
# has leased for itself.
#
# The MECHANISM is gated, in test_stream_slots.py: generations, supersession,
# the claim-before-acquire ordering and slot release, with no server needed.
# This file is the end-to-end proof, for a dashboard that has something on it.
set -u
ROUNDS="${1:-4}"
BASE='http://127.0.0.1:8787'

names="$(curl -s "$BASE/api/agents" \
  | python3 -c 'import json,sys; print(" ".join(a["name"] for a in json.load(sys.stdin)["agents"]))')"
count="$(printf '%s\n' $names | wc -w)"
[ "$count" -gt 0 ] || { echo 'no agents to test'; exit 1; }
echo "  $count agents, $ROUNDS rounds of abandoned streams"

for _round in $(seq 1 "$ROUNDS"); do
  for name in $names; do
    timeout 1 curl -sN "$BASE/api/stream/$name?tail=512" >/dev/null 2>&1 &
  done
  sleep 1.2
done
wait 2>/dev/null
sleep 3

fail=0
for name in $names; do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$BASE/api/stream/$name?tail=512")"
  if [ "$code" = 200 ]; then
    printf '  ok    %-12s HTTP %s\n' "$name" "$code"
  else
    printf '  FAIL  %-12s HTTP %s  <-- slot pool exhausted\n' "$name" "$code"
    fail=$((fail + 1))
  fi
done
echo
[ "$fail" -eq 0 ] && echo "all $count streams still available after $((ROUNDS * count)) opens" \
                  || echo "$fail stream(s) refused"
exit "$fail"
