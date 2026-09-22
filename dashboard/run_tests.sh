#!/usr/bin/env bash
# Run every CCC suite. From the repo root, inside WSL:
#   bash <(tr -d '\r' < dashboard/run_tests.sh)
#
# Restarts the server first, because several suites assert on endpoints that only
# exist after a reload, and spawns two throwaway agents if none are running, because
# the stream checks need live panes. Both are cleaned up on exit. Exits non-zero if any
# suite fails.
#
# test_auth.py needs an interactive-ish shell for nvm's node (codex is validated
# through `codex exec --strict-config`), so run this under `bash -ic` if codex is
# not on PATH.
set -u
[ -f dashboard/server.py ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }

bash <(tr -d '\r' < dashboard/restart.sh) >/dev/null || exit 1

# Agents, if there are none.
#
# smoke.sh and test_snapshot.py assert against live panes: /api/stream-all has nothing
# to carry without one, and the snapshot framing checks need a real pane to frame. Run
# cold, that cost three checks in smoke.sh and six in test_snapshot.py - failures that
# look exactly like a streaming regression and have cost real time being investigated as
# one, twice.
#
# So the suite provides its own. Two `--cli shell` agents need no credentials and no
# network. Pre-existing agents are left completely alone: if any session is already up,
# nothing is spawned and nothing is killed, because the operator's agents are not the
# test's to manage.
#
# AGENTMUX_NO_COURIER=1 because a test run should not leave a daemon behind; the
# courier's own lifecycle is covered by test_courier.py against an isolated HOME.
SPAWNED=""
HARNESS=""

cleanup() {
  for agent in $SPAWNED; do
    bash "$HARNESS" kill "$agent" >/dev/null 2>&1
  done
  [ -n "$HARNESS" ] && rm -f "$HARNESS"
}
trap cleanup EXIT INT TERM

if command -v tmux >/dev/null 2>&1; then
  live="$(tmux -L agentmux list-sessions -F '#{session_name}' 2>/dev/null | grep -c . || true)"
  if [ "${live:-0}" -eq 0 ]; then
    HARNESS="$(mktemp)"
    tr -d '\r' < agentmux.sh > "$HARNESS"
    export AGENTMUX_REPO="${AGENTMUX_REPO:-$PWD}"
    export AGENTMUX_NO_COURIER=1
    for agent in ccc-selftest-1 ccc-selftest-2; do
      if bash "$HARNESS" spawn "$agent" --cli shell --cwd /tmp >/dev/null 2>&1; then
        SPAWNED="$SPAWNED $agent"
      fi
    done
    if [ -n "$SPAWNED" ]; then
      echo "(spawned$SPAWNED for the stream checks; they are killed on exit)"
      sleep 1
    else
      echo "WARNING: could not spawn test agents; stream checks will fail" >&2
    fi
  fi
else
  echo "WARNING: tmux not found; stream checks will fail without live agents" >&2
fi

total_fail=0

run() {
  local label="$1"; shift
  printf '%-16s ' "$label"
  local out
  out="$("$@" 2>&1)"
  local line
  line="$(printf '%s\n' "$out" | tail -1)"
  printf '%s\n' "$line"
  case "$line" in
    *"failed 0") ;;
    *) total_fail=$((total_fail + 1)); printf '%s\n' "$out" | grep -E '^\s+FAIL' ;;
  esac
}

# testlib first: it proves the shared assertions can FAIL on the bug shapes they exist
# for. If they cannot, every suite below that uses them is decoration.
run test_testlib.sh bash /dev/fd/8 8< <(tr -d '\r' < dashboard/test_testlib.sh)
run test_argguard.sh bash /dev/fd/9 9< <(tr -d '\r' < dashboard/test_argguard.sh)
run test_modal_guard.sh bash /dev/fd/4 4< <(tr -d '\r' < dashboard/test_modal_guard.sh)
run test_inbox_guard.sh bash /dev/fd/5 5< <(tr -d '\r' < dashboard/test_inbox_guard.sh)
run test_coordination.sh bash /dev/fd/6 6< <(tr -d '\r' < dashboard/test_coordination.sh)
run test_run.sh   bash /dev/fd/7 7< <(tr -d '\r' < dashboard/test_run.sh)
run test_lifecycle.sh bash /dev/fd/10 10< <(tr -d '\r' < dashboard/test_lifecycle.sh)
run smoke.sh      bash /dev/fd/3 3< <(tr -d '\r' < dashboard/smoke.sh)
run test_snapshot.py python3 dashboard/test_snapshot.py
run test_mqtt.py  python3 dashboard/test_mqtt.py
run test_tickets.py python3 dashboard/test_tickets.py
run test_courier.py python3 dashboard/test_courier.py
run test_gateway.py python3 dashboard/test_gateway.py
run test_auth.py  timeout 400 python3 dashboard/test_auth.py

# test_gateway.py needs no key and makes no network call, so it runs whether or not the
# Bedrock path is parked. Its last section compares the reconstructed
# taskmgmt/bedrock_gateway.py against the preserved 2026-09-19 bytecode, running both on
# identical inputs; that section skips itself once CPython can no longer load the .pyc.

echo
if [ "$total_fail" -eq 0 ]; then
  echo 'all suites passed'
else
  echo "$total_fail suite(s) failed"
fi
exit "$total_fail"
