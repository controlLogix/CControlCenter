#!/usr/bin/env bash
# demo.sh - the EP-032 cross-user demo (docs/FEDERATION.md; hub/fed/demo.py).
#
#   demo.sh all          cluster up if needed, fresh demo hubs, the walkthrough, nick's dashboard
#   demo.sh up | run | down
#   demo.sh live         real claude sessions for nick and alice do a task together (needs `up`;
#                        uses the claude CLI and its credentials; ~5-15 min)
#   demo.sh dashboard    nick's dashboard on http://127.0.0.1:8790 (Federation view)
#   demo.sh as <peer> <agentmux hub args...>   run any hub verb as that person's operator
#                        e.g. demo.sh as alice fed board list
#
# Uses the kind cluster (deploy/nats/up.sh). AGENTMUX_FED_KIND=0 uses a throwaway local
# nats-server instead.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
PY="$REPO/.venv/bin/python"
DEMO="${AGENTMUX_FED_DEMO_DIR:-$HOME/.agentmux-demo}"   # short: AF_UNIX paths max out at 104 bytes
PORT="${DEMO_DASHBOARD_PORT:-8790}"
export AGENTMUX_FED_KIND="${AGENTMUX_FED_KIND:-1}"
cd "$REPO"
[ -x "$PY" ] || python3 hub/cli.py fed setup

cluster() {
  [ "$AGENTMUX_FED_KIND" = 1 ] || return 0
  kubectl --context kind-agentmux-nats -n nats get statefulset nats >/dev/null 2>&1 || "$HERE/up.sh"
}

dashboard() {
  local home="$DEMO/homes/nick"
  [ -d "$home" ] || { echo "no demo: demo.sh up" >&2; exit 1; }
  if [ -f "$DEMO/dashboard.pid" ] && kill -0 "$(cat "$DEMO/dashboard.pid")" 2>/dev/null; then
    echo "dashboard already up: http://127.0.0.1:$PORT  (Federation view)"; return
  fi
  AGENTMUX_HOME="$home" nohup python3 dashboard/server.py --port "$PORT" > "$DEMO/dashboard.log" 2>&1 &
  echo $! > "$DEMO/dashboard.pid"
  sleep 1
  echo "nick's dashboard: http://127.0.0.1:$PORT  -> Federation"
}

case "${1:-all}" in
  up) cluster; "$PY" -m hub.fed.demo up ;;
  run) "$PY" -m hub.fed.demo run ;;
  live) "$PY" -m hub.fed.demo live ;;
  down)
    "$PY" -m hub.fed.demo down
    [ -f "$DEMO/dashboard.pid" ] && kill "$(cat "$DEMO/dashboard.pid")" 2>/dev/null && rm -f "$DEMO/dashboard.pid"
    true ;;
  dashboard) dashboard ;;
  as) shift; who="${1:?peer}"; shift
      AGENTMUX_HOME="$DEMO/homes/$who" "$PY" hub/cli.py "$@" ;;
  all) cluster; "$PY" -m hub.fed.demo up; "$PY" -m hub.fed.demo run; dashboard ;;
  *) sed -n '2,14p' "$0"; exit 2 ;;
esac
