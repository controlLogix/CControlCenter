#!/usr/bin/env bash
# Prove the test suite leaves the operator's live ~/.agentmux/auth.json byte-identical.
#   bash <(tr -d '\r' < dashboard/check_test_residue.sh)
#
# Worth its own script because the suite drives the RUNNING dashboard, which reads and
# writes that real file — the /api/* checks cannot be sandboxed without a second server.
# A test that edits a real config is a config editor, not a test.
#
# A file rather than an inline command because `python3 -c "..."` nested inside
# `wsl.exe bash -c "..."` loses its quoting entirely.
set -u
[ -f agentmux.sh ] || { echo 'run from the agentmux repo root' >&2; exit 2; }
FILE="$HOME/.agentmux/auth.json"

digest() {
  [ -f "$1" ] || { echo 'ABSENT'; return; }
  sha256sum "$1" | awk '{print $1}'
}

before="$(digest "$FILE")"
echo "  before: $before"

bash <(tr -d '\r' < dashboard/run_tests.sh) > /tmp/agentmux-residue-run.log 2>&1
tail -8 /tmp/agentmux-residue-run.log | sed 's/^/      /'

after="$(digest "$FILE")"
echo "  after:  $after"

if [ -z "$before" ] || [ -z "$after" ]; then
  echo '  NOT VERIFIED: a digest came back empty'
  exit 1
elif [ "$before" = "$after" ]; then
  echo '  IDEMPOTENT: the live auth.json is byte-identical after a full run'
else
  echo '  RESIDUE: the suite modified the live auth.json'
  exit 1
fi
