#!/usr/bin/env bash
# Run a workspace's `node --test` suite and print it in the shape run_tests.sh reads.
#
#   . <(tr -d '\r' < packages/nodesuite.sh)
#   node_suite scene "packages/scene/test/*.test.*" three
#
# WHY THIS EXISTS. run_tests.sh decides whether a suite passed from the LAST LINE
# of its output: it accepts `... failed 0` or a bare `OK`. `node --test` ends with
# `# duration_ms 322.2086`, which matches neither - so a perfectly green Node
# suite is reported as a failed one, and a gate that reports a false failure gets
# re-run until it goes green, which is how a gate stops being read. This
# translates. The logic is identical to packages/api/test_api.sh, which was
# written first and is left standalone rather than churned; this is for the two
# suites that came after, so the translation exists once for them rather than
# twice more.
#
# It SKIPS LOUDLY rather than failing when it cannot run at all. run_tests.sh
# greps for `^SKIP `, so a skip is visible. A suite that quietly passes without
# running is worse than one that is not registered - that is TM-012, where a
# green gate hid a check that had not executed.

node_suite() {
  local label="$1"        # e.g. scene  -> reported as test_scene
  local glob="$2"         # quoted glob; node does the expansion, not bash
  local dep="${3:-}"      # a node_modules entry proving install happened

  [ -f dashboard/server.py ] || { echo 'run this from the agentmux repo root' >&2; return 2; }

  . <(tr -d '\r' < scripts/node-env.sh) 2>/dev/null
  if [ -z "${AGENTMUX_NODE:-}" ] || [ ! -x "${AGENTMUX_NODE:-/nonexistent}" ]; then
    echo "SKIP test_${label}: no usable Node in WSL"
    echo '  nvm install 24      (or: export AGENTMUX_NODE=/path/to/bin/node)'
    echo 'passed 0, failed 0'
    return 0
  fi

  if [ -n "$dep" ] && [ ! -e "node_modules/$dep" ] && [ ! -e "packages/$label/node_modules/$dep" ]; then
    echo "SKIP test_${label}: dependencies are not installed ($dep missing)"
    echo '  From WINDOWS PowerShell, at the repo root:  npm install'
    echo '  Not from WSL: node_modules on /mnt/c is painfully slow from the Linux'
    echo '  side, and 9p raises transient EIO under load, which reads as a corrupt'
    echo '  install rather than as the filesystem it actually is.'
    echo 'passed 0, failed 0'
    return 0
  fi

  local out rc
  out="$("$AGENTMUX_NODE" --test --test-reporter=tap \
          --disable-warning=ExperimentalWarning "$glob" 2>&1)"
  rc=$?

  local passed failed
  passed="$(printf '%s\n' "$out" | sed -n 's/^# pass \([0-9][0-9]*\)$/\1/p' | tail -1)"
  failed="$(printf '%s\n' "$out" | sed -n 's/^# fail \([0-9][0-9]*\)$/\1/p' | tail -1)"

  # A crash before the TAP trailer leaves these EMPTY, which would render as
  # "passed , failed " - a line containing "failed 0" nowhere, so it would be
  # caught, but saying nothing about what happened. Name it instead.
  if [ -z "$passed" ] || [ -z "$failed" ]; then
    echo "test_${label}: node --test produced no TAP trailer (exit $rc). Raw output:"
    printf '%s\n' "$out" | tail -40
    echo 'passed 0, failed 1'
    return 1
  fi

  # TAP writes `not ok N - <name>`, which matches neither FAIL shape run_tests.sh
  # greps for, so print the failures here where they are certain to be read.
  if [ "$failed" -ne 0 ] || [ "$rc" -ne 0 ]; then
    printf '%s\n' "$out" | grep -E '^not ok [0-9]+ - ' | head -40
    printf '%s\n' "$out" | grep -E "^ +(error|failureType|code|expected|actual):" | head -60
  fi

  printf '%s\n' "$out" | sed -n "s/^ok [0-9][0-9]* - \(.*\) # SKIP \(.*\)$/SKIP test_${label}: \1 (\2)/p"

  if [ "$rc" -ne 0 ] && [ "$failed" -eq 0 ]; then
    echo "test_${label}: node exited $rc with no reported failure - treating as one"
    failed=1
  fi

  echo "passed ${passed}, failed ${failed}"
  [ "$failed" -eq 0 ] || return 1
  return 0
}
