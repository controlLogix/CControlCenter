#!/usr/bin/env bash
# Can the gate say WHAT broke, not just THAT something did?
#
#   bash <(tr -d '\r' < dashboard/test_gate_reporting.sh)
#
# WHY THIS EXISTS AS ITS OWN SUITE. This property has been violated four separate
# ways in this repo, each time silently, and each time the symptom was a gate
# that was technically correct and practically useless:
#
#   TM-012  a suite exited 127 with zero assertions and reported "passed 12,
#           failed 0" - a green gate while a real check never ran
#   TM-014  seven suites counted a skip as a pass, and so did the gate, because
#           `0:OK *` matches `OK (skipped=1)`
#   2026-09-25  a suite reported "passed -1, failed 1", a number that cannot be
#           true, and the gate printed it without blinking
#   2026-09-25  a failing test_e2e.sh reported the tail of an unrelated log where
#           its counts should have been, and the gate said "1 suite(s) failed"
#           with nothing at all about what - it cost a full re-run just to learn
#           which suite it had been
#
# The last two are what this covers. They share a cause: the runner reads a
# suite by its FINAL LINE and greps its output for failure detail, so anything
# that displaces the summary or does not match the grep is invisible.
#
# These are assertions over the gate's own scripts, which is what they have to
# be: the behaviour under test is how run_tests.sh reports, and running the real
# gate to check its reporting would take ten minutes to answer a question about
# two lines of shell.
set -u
[ -f dashboard/testlib.sh ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }
. <(tr -d '\r' < dashboard/testlib.sh)   # tr: testlib may arrive CRLF; bash cannot source that

GATE="$(tr -d '\r' < dashboard/run_tests.sh)"
E2E="$(tr -d '\r' < dashboard/test_e2e.sh)"

# ── the three failure shapes the runner has to recognise ─────────────────────
#
# Three, because there are three kinds of suite here and they do not agree:
#   testlib:        '  FAIL  <what>'       indented
#   python unittest:'FAIL: <test>'         column zero, colon
#   test_e2e.mjs:   'FAIL <name>'          column zero, NO colon
#
# The third matched neither pattern, so a failing e2e printed nothing.
detail_pattern="$(printf '%s\n' "$GATE" | sed -n "s/.*grep -E '\(\^(FAIL|ERROR)[^']*\)'.*/\1/p" | head -1)"
if [ -z "$detail_pattern" ]; then
  bad 'the runner has no failure-detail grep at all'
else
  ok "the runner greps for failure detail with $detail_pattern"
  for sample in 'FAIL: test_thing (module.Class.test_thing)' 'FAIL the page logged no errors' 'ERROR: setUpClass (x.Y)'; do
    if printf '%s\n' "$sample" | grep -qE "$detail_pattern"; then
      ok "it matches: ${sample:0:42}"
    else
      bad "it does NOT match, so this failure would be silent: $sample"
    fi
  done
fi
# And the indented shape is handled by the other branch, which must still exist:
if printf '%s\n' "$GATE" | grep -q "grep -E '\^\[\[:space:\]\]+FAIL'"; then
  ok 'the indented testlib shape still has its own branch'
else
  bad 'the indented FAIL branch is gone; every testlib suite would report nothing'
fi

# ── a number that cannot be true ─────────────────────────────────────────────
#
# The suites share a `testsRun - failed - skipped` formula, and when setUpClass
# errors unittest records the error while testsRun stays at zero. Deliberately
# NOT clamped in the suites: the impossible number is the only evidence the
# class never ran, and clamping it to 0 would make it look like an ordinary
# empty suite. So the runner names it.
if printf '%s\n' "$GATE" | grep -q 'passed\\ -\*'; then
  ok 'the runner names a negative pass count rather than printing it'
else
  bad 'a suite reporting "passed -1" would be printed as-is'
fi
if printf '%s\n' "$GATE" | grep -q 'DID NOT RUN'; then
  ok 'and says the class or module setup failed, which is what it means'
else
  bad 'the negative-count case is caught but not explained'
fi

# ── the summary has to be the LAST line ──────────────────────────────────────
#
# run_tests.sh reports a suite by `tail -1`. test_e2e.sh printed its diagnostic
# AFTER the summary, so the gate read the tail of a server log where the counts
# should have been.
dump_line="$(printf '%s\n' "$E2E" | grep -n 'tail -40 "\$TEST_HOME/server.log"' | cut -d: -f1 | head -1)"
summary_line="$(printf '%s\n' "$E2E" | grep -n 'printf .*"\$summary"' | cut -d: -f1 | head -1)"
if [ -n "$dump_line" ] && [ -n "$summary_line" ] && [ "$dump_line" -lt "$summary_line" ]; then
  ok 'test_e2e.sh prints its diagnostic first and its summary last'
elif [ -z "$summary_line" ]; then
  bad 'test_e2e.sh never re-prints its summary, so a failure reports a log tail'
else
  bad 'test_e2e.sh prints the summary before the diagnostic, which displaces it'
fi
# One level further down, and the same rule. test_e2e.mjs printed its roll-call
# of failed names AFTER the counts, so even with the shell fixed the gate read a
# list of names where the summary should have been. The summary is the last
# thing the reporter prints, full stop.
MJS="$(tr -d '\r' < dashboard/test_e2e.mjs)"
roll="$(printf '%s
' "$MJS" | grep -n "console.log('failed: '" | cut -d: -f1 | head -1)"
counts="$(printf '%s
' "$MJS" | grep -n 'passed \${passed}, failed \${failed}' | cut -d: -f1 | head -1)"
if [ -n "$roll" ] && [ -n "$counts" ] && [ "$roll" -lt "$counts" ]; then
  ok 'test_e2e.mjs prints its roll-call before the counts, so the counts are last'
else
  bad 'test_e2e.mjs prints something after the counts, which displaces them'
fi
# And the shell finds the summary by PATTERN, not by position - an anchor that
# assumes nothing follows it breaks the next time something does.
if printf '%s
' "$E2E" | grep -q "grep -E '\^passed"; then
  ok 'test_e2e.sh finds the summary by pattern rather than by tail -1'
else
  bad 'test_e2e.sh assumes the summary is the last line of the reporter output'
fi

# And when node dies before counting anything, say THAT rather than letting the
# last line be whatever happened to be on stdout.
if printf '%s\n' "$E2E" | grep -q 'without reporting counts'; then
  ok 'a crash with no counts at all is reported as such'
else
  bad 'a crashed e2e run reports whatever line happened to be last'
fi

# ── the runner must not accept a summary it cannot parse ─────────────────────
#
# Two success shapes, because there are two kinds of suite. A third, unparsed
# shape slipping through as success is the TM-012 family.
if printf '%s\n' "$GATE" | grep -q 'failed 0")'; then
  ok 'the "passed N, failed 0" success shape is matched explicitly'
else
  bad 'the runner no longer recognises a testlib suite that passed'
fi
if printf '%s\n' "$GATE" | grep -q '0:OK'; then
  ok 'and the bare unittest OK shape, which is the other kind of suite here'
else
  bad 'the runner no longer recognises a raw unittest suite that passed'
fi
# The catch-all is what makes an unrecognised third shape a FAILURE rather than
# a silent pass - which is the TM-012 family, and the reason to check it here.
if printf '%s\n' "$GATE" | grep -q 'total_fail + 1'; then
  ok 'anything the runner cannot parse counts as a failed suite'
else
  bad 'an unparsed summary would not be counted as a failure'
fi

# ── no suite may hardcode a failure count it cannot reach ────────────────────
#
# test_frontend_collapse.sh printed `passed ${passed}, failed 0` - a literal
# zero, so it could not report a failure even in the runs where it noticed one.
# Its assertions also ran at module scope, outside any harness, so a failure
# threw out of the script and the gate reported Node's version banner as the
# result. Both halves of that were invisible until a card was added.
#
# A variable count beside a literal zero is the smell: it means someone wired up
# a pass counter and never a failure one.
hardcoded=""
while IFS= read -r -d '' file; do
  case "$file" in *dashboard/test_gate_reporting.sh) continue ;; esac
  # A literal zero is fine when the line ALSO branches on a real failure count -
  # test_idle.sh prints "failed 0" only inside `if [ "$failed" = 0 ]`, which is
  # correct and was the first thing this check flagged. A check that cries wolf
  # on the correct case is worse than no check, so the exemption is precise:
  # the line must nowhere else interpolate a failure variable.
  hits=$(grep -nE 'passed [^,]*\$[A-Za-z_{][^,]*, *failed 0' "$file" 2>/dev/null |
         grep -vE 'failed \$[A-Za-z_{]' || true)
  [ -z "$hits" ] || hardcoded="$hardcoded$file: $hits"$'
'
done < <(git ls-files -z -- 'dashboard/test_*.sh' 'dashboard/check_*.sh' 2>/dev/null)

if [ -z "$hardcoded" ]; then
  ok 'no suite reports a counted pass beside a hardcoded zero failure'
else
  bad 'a suite counts its passes and hardcodes "failed 0", so it cannot report a failure'
  printf '%s' "$hardcoded" | sed 's/^/          /'
fi

finish
