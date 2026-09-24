#!/usr/bin/env bash
# Run every CCC suite. From the repo root, inside WSL:
#   bash <(tr -d '\r' < dashboard/run_tests.sh)
#
# Runs the server on a disposable AGENTMUX_HOME at the usual port, restores the
# operator home on exit/signals, and spawns throwaway agents if needed because
# the stream checks need live panes. Both are cleaned up on exit. Exits non-zero if any
# suite fails.
#
# test_auth.py needs an interactive-ish shell for nvm's node (codex is validated
# through `codex exec --strict-config`), so run this under `bash -ic` if codex is
# not on PATH.
set -u
[ -f dashboard/server.py ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }

# HTTP writes occur in the SERVER process: a client-side home cannot isolate them.
# Lease port 8787 for this suite, swap to an empty home, and restore without ever
# passing --fresh-db. The EXIT handler is installed before the first restart.
exec 200>"${TMPDIR:-/tmp}/agentmux-dashboard-tests-${UID}.lock"
flock -n 200 || { echo 'another dashboard suite owns port 8787' >&2; exit 2; }
OPERATOR_ROOT="$(python3 dashboard/suite_server.py --fallback "${AGENTMUX_HOME:-$HOME/.agentmux}")" || exit 2
TEST_ROOT="$(mktemp -d)" || exit 2
SPAWNED=""
HARNESS=""
SUITE_PID=""
RESTORE_NEEDED=0

restart_for_home() {
  # Cleanup ignores repeated interrupts, but the restored server must retain its
  # normal signal handlers so the next restart can stop it.
  AGENTMUX_HOME="$1" python3 -c 'import os, signal, sys; signal.signal(signal.SIGINT, signal.SIG_DFL); signal.signal(signal.SIGTERM, signal.SIG_DFL); os.execvp("bash", ["bash", sys.argv[1]])' \
    <(tr -d '\r' < dashboard/restart.sh) 200>&-
}

cleanup() {
  local status=$? restore_status=0
  trap - EXIT
  trap '' INT TERM
  if [ -n "$SUITE_PID" ]; then
    # A signal to this shell must stop the HTTP-writing child BEFORE restoring the
    # live server. Each suite has a private process group, including descendants.
    kill -TERM -- "-$SUITE_PID" 2>/dev/null || true
    for _ in {1..30}; do
      kill -0 -- "-$SUITE_PID" 2>/dev/null || break
      sleep 0.1
    done
    kill -KILL -- "-$SUITE_PID" 2>/dev/null || true
    wait "$SUITE_PID" 2>/dev/null || true
  fi
  for agent in $SPAWNED; do
    bash "$HARNESS" kill "$agent" >/dev/null 2>&1
  done
  [ -n "$HARNESS" ] && rm -f "$HARNESS"
  if [ "$RESTORE_NEEDED" = 1 ]; then
    restart_for_home "$OPERATOR_ROOT" >/dev/null &&
      python3 dashboard/suite_server.py --expect "$OPERATOR_ROOT"
    restore_status=$?
  fi
  if [ "$restore_status" != 0 ]; then
    echo "  FAIL  could not restore dashboard home $OPERATOR_ROOT; retained test home $TEST_ROOT for recovery" >&2
    status=1
  else
    rm -rf "$TEST_ROOT"
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

export AGENTMUX_HOME="$TEST_ROOT"
export AGENTMUX_NO_COURIER=1
# Suites simulate several identities; an invoking worker is not their identity.
unset AGENTMUX_AGENT
RESTORE_NEEDED=1
restart_for_home "$TEST_ROOT" >/dev/null || exit 1
python3 dashboard/suite_server.py --expect "$TEST_ROOT" || exit 1


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
if command -v tmux >/dev/null 2>&1; then
  live="$(tmux -L agentmux list-sessions -F '#{session_name}' 2>/dev/null | grep -c . || true)"
  if [ "${live:-0}" -eq 0 ]; then
    HARNESS="$(mktemp)"
    tr -d '\r' < agentmux.sh > "$HARNESS"
    export AGENTMUX_REPO="${AGENTMUX_REPO:-$PWD}"
    export AGENTMUX_NO_COURIER=1
    for agent in ccc-selftest-$$-1 ccc-selftest-$$-2; do
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

# Read-only stream fixtures for existing panes: the temporary server needs its own
# log paths and pane ids. Never copy credentials, tasks, or change a live pipe-pane.
mkdir -p "$TEST_ROOT/run" "$TEST_ROOT/logs"
while IFS=$'\t' read -r name pane; do
  [[ "$name" =~ ^[A-Za-z0-9_.-]{1,64}$ && "$pane" =~ ^%[0-9]+$ ]] || continue
  printf '%s\n' "$pane" > "$TEST_ROOT/run/$name.pane"
  touch "$TEST_ROOT/logs/$name.log"
done < <(tmux -L agentmux list-panes -a -F $'#{session_name}\t#{pane_id}' 2>/dev/null)

total_fail=0

run() {
  local label="$1"; shift
  printf '%-16s ' "$label"
  local out rc
  # Background bash jobs inherit SIGINT ignored. Reset it before exec so both
  # interactive interrupts and nested signal-regression probes exercise the traps.
  python3 -c 'import os, signal, sys; os.setsid(); signal.signal(signal.SIGINT, signal.SIG_DFL); signal.signal(signal.SIGTERM, signal.SIG_DFL); os.execvp(sys.argv[1], sys.argv[1:])' \
    "$@" > "$TEST_ROOT/suite.out" 2>&1 200>&- &
  SUITE_PID=$!
  wait "$SUITE_PID"; rc=$?
  SUITE_PID=""
  out="$(cat "$TEST_ROOT/suite.out")"
  local line
  line="$(printf '%s\n' "$out" | tail -1)"
  printf '%s\n' "$line"
  # Keep unavailable-history skips visible even when a meta-check exits cleanly.
  printf '%s\n' "$out" | grep '^SKIP ' || true
  case "$rc:$line" in
    0:*"failed 0") ;;
    *) total_fail=$((total_fail + 1)); printf '%s\n' "$out" | grep -E '^\s+FAIL' ;;
  esac
}

# testlib first: it proves the shared assertions can FAIL on the bug shapes they exist
# for. If they cannot, every suite below that uses them is decoration.
run test_testlib.sh bash /dev/fd/8 8< <(tr -d '\r' < dashboard/test_testlib.sh)
# Historical differentials and the meta-check's own known-broken fixtures.
run check_test_failability.sh bash /dev/fd/11 11< <(tr -d '\r' < dashboard/check_test_failability.sh)
run test_argguard.sh bash /dev/fd/9 9< <(tr -d '\r' < dashboard/test_argguard.sh)
run test_modal_guard.sh bash /dev/fd/4 4< <(tr -d '\r' < dashboard/test_modal_guard.sh)
run test_inbox_guard.sh bash /dev/fd/5 5< <(tr -d '\r' < dashboard/test_inbox_guard.sh)
run test_coordination.sh bash /dev/fd/6 6< <(tr -d '\r' < dashboard/test_coordination.sh)
run test_run.sh   bash /dev/fd/7 7< <(tr -d '\r' < dashboard/test_run.sh)
run test_residue.sh bash /dev/fd/12 12< <(tr -d '\r' < dashboard/test_residue.sh)
run test_lifecycle.sh bash /dev/fd/10 10< <(tr -d '\r' < dashboard/test_lifecycle.sh)
run test_frontend.sh bash /dev/fd/12 12< <(tr -d '\r' < dashboard/test_frontend.sh)
run test_frontend_board.sh bash /dev/fd/14 14< <(tr -d '\r' < dashboard/test_frontend_board.sh)
run smoke.sh      bash /dev/fd/3 3< <(tr -d '\r' < dashboard/smoke.sh)
# The board model and the dispatch seam. test_board.py landed with the store and
# was never listed here, so it had not run in the gate since the day it was
# written - a suite nothing invokes is decoration, which is the same standard
# test_testlib.sh is held to above.
run test_board.py python3 dashboard/test_board.py
run test_dispatch.py python3 dashboard/test_dispatch.py
run test_sandbox_coordination.py python3 dashboard/test_sandbox_coordination.py
# EP-015 suites are registered at the scaffold seam before their owning tasks land.
# Missing suites are explicit skips during the staged build; present suites use
# the same failure accounting as every existing suite above.
for suite in test_orchestration_plugin.py test_plugin_skills.py test_agentdefs.py test_agentcli.py test_teamcli.py test_boardagents.py test_boardteams.py \
             test_launch.sh test_frontend_agents.sh test_frontend_teams.sh test_frontend_collapse.sh; do
  if [ ! -f "dashboard/$suite" ]; then
    echo "SKIP $suite (EP-015 suite has not landed yet)"
  elif [[ "$suite" == *.py ]]; then
    run "$suite" python3 "dashboard/$suite"
  else
    run "$suite" bash /dev/fd/13 13< <(tr -d '\r' < "dashboard/$suite")
  fi
done
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
