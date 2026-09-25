#!/usr/bin/env bash
# Restart agentmux dashboard server. Run from the repo root inside WSL:
#   bash <(tr -d '\r' < dashboard/restart.sh) [--fresh-db]
#
# A file rather than a one-liner because nesting $(pgrep ...) inside a
# `wsl.exe bash -c "..."` call gets expanded by the *outer* Windows shell first.
set -u
ROOT="${AGENTMUX_HOME:-$HOME/.agentmux}"

# Deliberately no `cd "$(dirname "$0")"`: run via process substitution, $0 is
# /dev/fd/63, so that would land in /dev. Run this from the repo root.
if [ ! -f dashboard/server.py ]; then
  echo 'run this from the agentmux repo root' >&2
  exit 2
fi

# Match on a pattern that cannot match this script's own command line.
for pid in $(pgrep -f 'dashboard/serv' 2>/dev/null); do
  [ "$pid" = "$$" ] || kill "$pid" 2>/dev/null
done
sleep 1

if [ "${1:-}" = '--fresh-db' ]; then
  rm -f "$ROOT/cc.db" "$ROOT/cc.db-wal" "$ROOT/cc.db-shm"
  echo 'cc.db removed'
fi

# The restored dashboard must outlive the suite process group.
nohup setsid python3 dashboard/server.py > /tmp/agentmux-server.log 2>&1 &
sleep 3
if curl -s -o /dev/null "http://127.0.0.1:8787/"; then
  echo "up: http://127.0.0.1:8787  (pid $!)"
else
  echo 'FAILED to come up:'
  cat /tmp/agentmux-server.log
  exit 1
fi
