#!/usr/bin/env bash
# Run every CCC suite. From the repo root, inside WSL:
#   bash <(tr -d '\r' < dashboard/run_tests.sh)
#
# Restarts the server first, because several suites assert on endpoints that only
# exist after a reload. Exits non-zero if any suite fails.
#
# test_auth.py needs an interactive-ish shell for nvm's node (codex is validated
# through `codex exec --strict-config`), so run this under `bash -ic` if codex is
# not on PATH.
set -u
[ -f dashboard/server.py ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }

bash <(tr -d '\r' < dashboard/restart.sh) >/dev/null || exit 1

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

run smoke.sh      bash /dev/fd/3 3< <(tr -d '\r' < dashboard/smoke.sh)
run test_snapshot.py python3 dashboard/test_snapshot.py
run test_mqtt.py  python3 dashboard/test_mqtt.py
run test_tickets.py python3 dashboard/test_tickets.py
run test_courier.py python3 dashboard/test_courier.py
run test_auth.py  timeout 400 python3 dashboard/test_auth.py

# NOT RUN, because it does not exist: STATUS_CCC_2026-09-20.md lists a sixth suite,
# test_gateway.py (31 checks, Bedrock translation). It is absent from the tree and
# from git history - the 09-20 credential purge deleted the two Bedrock setup
# scripts and this appears to have gone with them. taskmgmt/bedrock_gateway.py is
# therefore untested. Reinstating it is worth doing if the Bedrock path is ever
# unparked.

echo
if [ "$total_fail" -eq 0 ]; then
  echo 'all suites passed'
else
  echo "$total_fail suite(s) failed"
fi
exit "$total_fail"
