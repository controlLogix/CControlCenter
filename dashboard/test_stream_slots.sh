#!/usr/bin/env bash
# Prove the SSE slot pool cannot be exhausted by repeated page loads.
#   bash <(tr -d '\r' < dashboard/test_stream_slots.sh) [rounds]
#
# THE BUG THIS GUARDS. A browser reload opens a fresh EventSource per pane while the
# previous ones are still established; the server cannot tell a client has gone until it
# next tries to write. Seven panes over a couple of reloads consumed all sixteen slots,
# and three panes then sat at HTTP 503 rendering nothing — which looks exactly like a
# dead agent. Each agent now holds at most one stream (server.py: claim_stream /
# stream_superseded), so the ceiling is the agent count rather than the reload count.
#
# WHY THIS WAS NOT IN THE GATE. It was written, it worked, and nothing ran it - and a
# suite nothing invokes is decoration, the same standard test_testlib.sh is held to.
# Registering it meant a summary line, a skip that is not a failure, an address that
# is not nailed to one port, and waits that are polls rather than sleeps.
#
# AND THE THING THAT MATTERED MORE THAN ALL FOUR: AS WRITTEN IT COULD NOT FAIL.
# Measured, not assumed - run against a copy of the tree with stream_superseded()
# stubbed to `return False`, the original passed exactly as it did unmodified.
#
# Two reasons, and both had to go:
#
#   1. THE STORM WAS SMALLER THAN THE POOL. Four rounds was written when the author
#      had seven panes open. Against the two agents run_tests.sh spawns it is 8 opens
#      against a pool of 16 - nothing to exhaust. Rounds are derived from the pool
#      size and the live agent count now.
#   2. IT WAITED OUT THE EVIDENCE. An abandoned stream is reaped anyway when the next
#      heartbeat write fails, so "are the streams back?" is answered YES after fifteen
#      seconds whether or not the fix exists. The generation mechanism is not what
#      makes the slots come back - it is what stops them being taken in the first
#      place. So the probe happens IMMEDIATELY after the storm and inside the
#      heartbeat window, and if the box was too slow for that the suite says it
#      proved nothing rather than claiming a pass.
set -u
[ -f dashboard/server.py ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }
. dashboard/testlib.sh

BASE="${AGENTMUX_BASE_URL:-http://127.0.0.1:8787}"
# Both read out of server.py rather than trusted from memory, and both asserted: this
# suite is sized against the pool and timed against the heartbeat, so either one
# drifting turns it back into decoration. A mismatch is a failure here, loudly.
POOL=16
HEARTBEAT=15
pool_in_source="$(grep -oE 'STREAM_SLOTS = threading\.BoundedSemaphore\([0-9]+\)' dashboard/server.py \
                  | grep -oE '[0-9]+' || true)"
beat_in_source="$(grep -oE '^HEARTBEAT_SECONDS = [0-9]+' dashboard/server.py \
                  | grep -oE '[0-9]+' || true)"

# One HEAD per probe. The handler sends its headers and returns before the streaming
# loop (server.py: `if self.command == "HEAD"`), so the slot is taken and handed back
# at once - "would a stream be granted right now" answered without holding one open to
# ask. A GET probe had to be bounded by --max-time, which spent that whole timeout on
# every healthy answer and pushed the check outside the window it has to land in.
probe() { curl -s -o /dev/null -w '%{http_code}' -I --max-time 10 "$BASE/api/stream/$1?tail=512"; }

if ! curl -fsS -o /dev/null --max-time 10 "$BASE/" 2>/dev/null; then
  echo "SKIP test_stream_slots: no dashboard answering at $BASE"
  exit 0
fi

names="$(curl -s --max-time 10 "$BASE/api/agents" 2>/dev/null | python3 -c 'import json, sys
try:
    print(" ".join(a["name"] for a in json.load(sys.stdin)["agents"]))
except Exception:
    pass' 2>/dev/null)"
count="$(printf '%s\n' $names | wc -w)"
if [ "${count:-0}" -eq 0 ]; then
  # Not a failure. The streams under test are per-agent, so with no agent there is
  # nothing to exhaust - and spawning one is the harness's job, not this suite's.
  echo "SKIP test_stream_slots: no live agents at $BASE (run under run_tests.sh, which spawns two)"
  exit 0
fi

check 'the pool is the size this storm is sized against' "$POOL" "$pool_in_source"
check 'the heartbeat is the window this check races' "$HEARTBEAT" "$beat_in_source"

# Enough opens to bury the pool half again over, whatever the agent count happens to
# be - and never fewer than two rounds, so "the same agent, opened again" is always
# part of what is exercised.
ROUNDS="${1:-$(( (POOL + POOL / 2 + count - 1) / count ))}"
[ "$ROUNDS" -ge 2 ] || ROUNDS=2
opens=$(( ROUNDS * count ))
echo "  $count agents, $ROUNDS rounds = $opens abandoned opens against a pool of $POOL ($BASE)"

# ABANDONED, which is the whole point: `timeout 1 curl` walks away without closing
# politely, exactly as a browser does when the page is reloaded out from under an
# EventSource. The server only learns the client has gone when it next tries to write.
started=$SECONDS
for _round in $(seq 1 "$ROUNDS"); do
  for name in $names; do
    timeout 1 curl -sN --max-time 2 "$BASE/api/stream/$name?tail=512" >/dev/null 2>&1 &
  done
  sleep 0.2
done
wait 2>/dev/null

# IMMEDIATELY, and the clock is part of the assertion.
refused=0
results=""
for name in $names; do
  code="$(probe "$name")"
  results="$results$name=$code "
  [ "$code" = 200 ] || refused=$((refused + 1))
done
elapsed=$(( SECONDS - started ))

if [ "$refused" -eq 0 ] && [ "$elapsed" -ge "$HEARTBEAT" ]; then
  # Every stream answered - but late enough that the heartbeat could have reaped the
  # abandoned ones on its own, so this run cannot tell the fix from its absence. Say
  # so. A green concurrency test that never raced is worse than no test.
  echo "SKIP test_stream_slots: storm and probe took ${elapsed}s, at or past the ${HEARTBEAT}s"
  echo "  heartbeat that reaps abandoned streams anyway - this run proves nothing."
  exit 0
fi

for name in $names; do
  code="${results#*$name=}"; code="${code%% *}"
  if [ "$code" = 200 ]; then
    ok "$(printf '%-28s stream granted %ss after %s abandoned opens' "$name" "$elapsed" "$opens")"
  else
    bad "$(printf '%-28s HTTP %s at +%ss - %s abandoned opens exhausted a pool of %s' \
             "$name" "$code" "$elapsed" "$opens" "$POOL")"
  fi
done

finish
