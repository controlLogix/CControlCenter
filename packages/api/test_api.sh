#!/usr/bin/env bash
# The @agentmux/api suite, in the shape dashboard/run_tests.sh reads.
#
#   bash <(tr -d '\r' < packages/api/test_api.sh)
#
# WHY THIS WRAPPER EXISTS AND IS NOT JUST `npm test`. run_tests.sh decides whether
# a suite passed from the LAST LINE of its output (run(), around line 186): it
# accepts `... failed 0` or a bare `OK`, and counts anything else as a failure.
# `node --test` ends with `# duration_ms 322.2086`, which matches neither - so a
# perfectly green Node suite would be reported as a failed one, and the gate would
# be lying in the direction that gets gates ignored. This translates.
#
# It SKIPS, loudly, rather than failing, in the two cases where it cannot run at
# all: no usable Node in WSL, and no installed dependencies. Both print what to do.
# run_tests.sh greps for `^SKIP ` and surfaces those lines, so a skip is visible
# rather than silent - a suite that quietly passes without running is worse than
# one that is not registered.
set -u
[ -f dashboard/server.py ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }
[ -f packages/api/package.json ] || { echo 'packages/api is missing' >&2; exit 2; }

# THE NODE. scripts/node-env.sh resolves the nvm one and refuses the Windows one
# reached through /mnt interop; packages/api/scripts/guard-node.mjs repeats the
# refusal at `npm start`. One mechanism, two entry points - see either file for
# the measurement behind it.
. <(tr -d '\r' < scripts/node-env.sh)
if [ $? -ne 0 ] || [ -z "${AGENTMUX_NODE:-}" ]; then
  echo 'SKIP test_api: no usable Node in WSL'
  echo '  nvm install 24      (or: export AGENTMUX_NODE=/path/to/bin/node)'
  echo 'passed 0, failed 0'
  exit 0
fi

if [ ! -d node_modules/fastify ]; then
  echo 'SKIP test_api: dependencies are not installed'
  echo '  From WINDOWS PowerShell, at the repo root:  npm install'
  echo '  Not from WSL: node_modules on /mnt/c is painfully slow from the Linux side'
  echo '  and 9p raises transient EIO under load, which reads as a corrupt install.'
  echo 'passed 0, failed 0'
  exit 0
fi

# --test-reporter=tap, pinned. The default reporter differs between a TTY and a
# pipe, and the counts below are parsed from the TAP trailer - so leaving it to
# the default means the parse works interactively and silently stops working
# inside run_tests.sh, which is the only place it matters.
#
# The argument is a GLOB, not the directory. `node --test packages/api/test/`
# looks like it ought to scan that directory and does not: Node 24 resolves a
# positional argument as a path to LOAD, so it tried to require the directory
# itself and died with MODULE_NOT_FOUND before running a single test. This wrapper
# caught it and said "passed 0, failed 1" - correctly, but naming a module rather
# than a suite. Quoted, so node does the expansion and the result does not depend
# on whether bash happened to match anything first.
out="$("$AGENTMUX_NODE" --test --test-reporter=tap \
        --disable-warning=ExperimentalWarning "packages/api/test/*.test.*" 2>&1)"
rc=$?

passed="$(printf '%s\n' "$out" | sed -n 's/^# pass \([0-9][0-9]*\)$/\1/p' | tail -1)"
failed="$(printf '%s\n' "$out" | sed -n 's/^# fail \([0-9][0-9]*\)$/\1/p' | tail -1)"
skipped="$(printf '%s\n' "$out" | sed -n 's/^# skipped \([0-9][0-9]*\)$/\1/p' | tail -1)"

# A crash before the TAP trailer leaves the counts EMPTY, and an empty count would
# render as "passed , failed " - which contains the string "failed 0" nowhere and
# would at least be caught, but says nothing about what happened. Name it instead.
if [ -z "$passed" ] || [ -z "$failed" ]; then
  echo "test_api: node --test produced no TAP trailer (exit $rc). Raw output:"
  printf '%s\n' "$out" | tail -40
  echo 'passed 0, failed 1'
  exit 1
fi

# The failures themselves, before the summary line. run_tests.sh prints the last
# line and then greps the rest for FAIL shapes; TAP writes `not ok N - <name>`,
# which matches neither of its patterns, so print the names here where they are
# certain to be read.
if [ "$failed" -ne 0 ] || [ "$rc" -ne 0 ]; then
  printf '%s\n' "$out" | grep -E '^not ok [0-9]+ - ' | head -40
  printf '%s\n' "$out" | grep -E "^ +(error|failureType|code|expected|actual):" | head -60
fi

# Skips, in the shape run_tests.sh already greps for. The symlink refusal skips on
# a Windows host without Developer Mode, and that must stay visible: this suite is
# registered because it runs under WSL, where that check DOES run.
printf '%s\n' "$out" | sed -n 's/^ok [0-9][0-9]* - \(.*\) # SKIP \(.*\)$/SKIP test_api: \1 (\2)/p'

if [ "$rc" -ne 0 ] && [ "$failed" -eq 0 ]; then
  echo "test_api: node exited $rc with no reported failure - treating as one"
  failed=1
fi

echo "skipped ${skipped:-0}"
echo "passed $passed, failed $failed"
[ "$failed" -eq 0 ] || exit 1
