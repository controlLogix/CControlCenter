#!/usr/bin/env bash
# Restart the CCC dashboard server. Run from the repo root inside WSL:
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
# Wait for them to actually go. `sleep 1` was a guess, and a previous server still
# holding 8787 when the replacement binds is the whole of the failure below.
for _ in $(seq 1 50); do
  pgrep -f 'dashboard/serv' >/dev/null 2>&1 || break
  sleep 0.1
done

if [ "${1:-}" = '--fresh-db' ]; then
  # MOVED ASIDE, NOT DELETED - and the flag still means exactly what it says: the
  # server comes up on an empty database.
  #
  # What changed is what happens to the old one. cc.db has never been in git, so
  # `rm -f` here was the only copy of every epic, task, acceptance row and history
  # entry in the selected home ceasing to exist, with no undo and nothing to restore
  # from. Typing a destructive flag should be destructive; it should not be
  # IRREVERSIBLE when making it reversible costs a rename. 81 tasks and 880 history
  # rows is what was on the board the day this was written.
  #
  # test_lifecycle.sh already proves this only ever touches the SELECTED home, which
  # is the part that would actually be dangerous. This is the other half: it also
  # proves the bytes survive the flag.
  aside="$ROOT/cc.db.aside-$(date +%Y%m%d-%H%M%S)"
  moved=''
  for db_file in cc.db cc.db-wal cc.db-shm; do
    if [ -e "$ROOT/$db_file" ]; then
      mkdir -p "$aside"
      mv "$ROOT/$db_file" "$aside/$db_file"
      moved="$moved $db_file"
    fi
  done
  if [ -n "$moved" ]; then
    echo "cc.db moved aside (${moved# }) -> $aside"
    echo "  to undo:  mv $aside/* $ROOT/  &&  bash <(tr -d '\\r' < dashboard/restart.sh)"
  else
    echo 'cc.db: nothing to move aside; starting empty'
  fi
fi

# The restored dashboard must outlive the suite process group.
nohup setsid python3 dashboard/server.py > /tmp/ccc-server.log 2>&1 &
sleep 3
if ! curl -s -o /dev/null "http://127.0.0.1:8787/"; then
  echo 'FAILED to come up:'
  cat /tmp/ccc-server.log
  exit 1
fi

# ANSWERING IS NOT THE SAME AS BEING OURS.
#
# If the bind failed - because the old server had not released the port yet, or
# because it serves a different home and the kill above never found it - then the
# PREVIOUS server answers that curl and the check passes. Measured: with a server
# that dies instantly on "Address already in use", the old script printed
# "up: http://127.0.0.1:8787 (pid ...)" and exited 0, naming a pid that was
# already gone.
#
# That is not a cosmetic lie. A suite restarts the dashboard onto a throwaway home
# to isolate itself; if the restart silently leaves the operator's server holding
# the port, every write in that suite lands on the operator's real board while the
# run believes it is isolated. run_tests.sh already re-checks this after each of
# its own restarts - the verification belongs here, where the restart is.
if ! python3 dashboard/suite_server.py --port 8787 --expect "$ROOT" 2>/dev/null; then
  echo "FAILED: 8787 answers, but not from a dashboard serving $ROOT" >&2
  serving=$(python3 dashboard/suite_server.py --port 8787 --fallback '' 2>/dev/null)
  [ -n "$serving" ] && echo "  it is serving: $serving" >&2
  tail -5 /tmp/ccc-server.log >&2
  exit 1
fi
echo "up: http://127.0.0.1:8787  (home $ROOT)"
