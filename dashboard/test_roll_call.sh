#!/usr/bin/env bash
# The Agent Roll Call app's own node:test suite (e2e/roll-call/), scored the way
# run_tests.sh scores every suite: exit 0 and a last line ending "failed 0".
#   bash <(tr -d '\r' < dashboard/test_roll_call.sh)
#
# node --test does not print that line itself, so this reads the TAP summary and
# restates it. A run with no summary at all (node crashed, the suite vanished) is a
# failure, not a pass with zero tests.
set -u
[ -f e2e/roll-call/server/index.js ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }

if ! command -v node >/dev/null 2>&1; then
  rc_node_dir=$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1 || true)
  [ -z "$rc_node_dir" ] || export PATH="$rc_node_dir:$PATH"
fi
if ! command -v node >/dev/null 2>&1; then
  echo 'SKIP test_roll_call: node is not on PATH'
  echo 'passed 0, failed 0'
  exit 0
fi

out="$(cd e2e/roll-call && node --test --test-reporter=tap 2>&1)"
rc=$?
printf '%s\n' "$out"
pass="$(printf '%s\n' "$out" | sed -n 's/^# pass \([0-9][0-9]*\)$/\1/p' | tail -1)"
fail="$(printf '%s\n' "$out" | sed -n 's/^# fail \([0-9][0-9]*\)$/\1/p' | tail -1)"
if [ -z "$pass" ] || [ -z "$fail" ]; then
  echo "no node:test summary (exit $rc)"
  exit 1
fi
# node reports "pass 0, fail 0" when it finds no test files at all.
if [ "$pass" -eq 0 ] && [ "$fail" -eq 0 ]; then
  echo "no tests ran in e2e/roll-call (exit $rc)"
  exit 1
fi
# A non-zero exit with no failed test (a crash after the summary) still fails.
[ "$rc" -eq 0 ] || [ "$fail" -ne 0 ] || fail=1
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
