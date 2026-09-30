#!/usr/bin/env bash
# Live smoke: hub + tmux + a shell agent. Proves doorbell -> inbox -> ack, role claim,
# and liveness, with no LLM in the loop. Leaves no agents behind.
set -uo pipefail
AM="${AGENTMUX_BIN:-$HOME/.local/bin/agentmux}"
H() { "$AM" hub "$@"; }
fail() { echo "SMOKE FAIL: $*"; H kill calc-worker-smoke_sh >/dev/null 2>&1; exit 1; }

bash "$(dirname "$0")/setup_repos.sh" >/dev/null
H start
H repo add calc "$HOME/hubdemo/calc" --group demo >/dev/null
H repo add report "$HOME/hubdemo/report" --group demo >/dev/null
H spawn calc worker smoke_sh --cli shell || fail spawn
S=calc-worker-smoke_sh

# The welcome message rings the doorbell; a shell executes the bell line, which
# runs `agentmux hub inbox --ack` inside the pane - so ack proves the whole loop.
for i in $(seq 1 30); do
  st=$(H inbox --session "$S" --json | python3 -c 'import sys,json;print(len(json.load(sys.stdin)["messages"]))' 2>/dev/null)
  [ "$st" = 0 ] && break
  sleep 1
done
[ "$st" = 0 ] || fail "welcome never acked (unacked=$st)"
echo "welcome acked by the pane itself"

id=$(H post --to "agent:$S" --kind request --json "smoke ping" | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
for i in $(seq 1 20); do
  n=$(H events --entity delivery --json | python3 -c "import sys,json;print(sum(1 for e in json.load(sys.stdin) if e['entity_id'].startswith('$id') and e['event']=='acked'))")
  [ "$n" -ge 1 ] && break; sleep 1
done
[ "$n" -ge 1 ] || fail "ping not acked"
echo "direct message acked"

w=$(H work add --to role:calc/worker --title "smoke work" --json | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
out=$(H --as "$S" claim) || fail "claim"
echo "$out" | grep -q "$w" || fail "claim did not return $w: $out"
H --as "$S" done "$w" --result "smoke ok" >/dev/null || fail done
echo "role claim + done ok"

H kill "$S" >/dev/null
sleep 4
H agents | grep "$S" | grep -q dead || fail "agent not marked dead after kill"
echo "SMOKE PASS"
