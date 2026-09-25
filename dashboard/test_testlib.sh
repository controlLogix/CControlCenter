#!/usr/bin/env bash
# Verify the test helpers themselves - specifically that they can FAIL.
#   bash <(tr -d '\r' < dashboard/test_testlib.sh)
#
# WHY. smoke.sh:181 carries a comment saying it checks the frontend's status list
# against ccstore's - and then hardcodes the list, so it compares the test to itself
# and can never fail. A guard that cannot fail is worse than no guard, because it is
# counted as coverage.
#
# assert_one_winner and assert_no_loss are the two assertions that found every real
# defect on 2026-09-22. If either of them silently always passed, the suite would look
# green while the class of bug they exist for walked straight through. So each is
# pointed at a KNOWN-BROKEN implementation and must report failure, and at a
# known-correct one and must report success.
set -u
[ -f dashboard/testlib.sh ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }
# shellcheck source=/dev/null
. <(tr -d '\r' < dashboard/testlib.sh)   # tr: testlib may arrive CRLF; bash cannot source that

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Run an assertion in a subshell and report whether it said ok or FAIL, without its
# result touching this suite's counters.
verdict_of() {
  ( . dashboard/testlib.sh; "$@" ) 2>&1 | grep -qE '^  FAIL' && echo FAIL || echo OK
}

# ── subjects ─────────────────────────────────────────────────────────────────

# Correct: O_CREAT|O_EXCL. Exactly one caller can win.
exclusive_take() {
  python3 -c "
import os, sys
try:
    fd = os.open('$WORK/excl.lock', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
except FileExistsError:
    sys.exit(1)
os.write(fd, b'held'); os.close(fd)
"
}

# Broken: check-then-act, the shape of the original claim bug. Several callers can
# see "absent" before any of them creates it.
racy_take() {
  python3 -c "
import os, sys, time
p = '$WORK/racy.lock'
if os.path.exists(p):
    sys.exit(1)
time.sleep(0.05)                 # widen the window the real bug had
open(p, 'w').write('held')
"
}

count_lines() { count_msgs "$WORK/data.txt"; }

writer_20() {
  local i
  for i in $(seq 1 20); do
    echo "line-$i" >> "$WORK/data.txt"
    sleep 0.03
  done
}

# Correct: claim the file atomically, then read the snapshot.
safe_consume() { python3 -c "
import os
os.replace('$WORK/data.txt', '$WORK/data.snap')
"; }

# Broken: read, then truncate. Anything appended in between is destroyed - the
# original inbox bug.
lossy_consume() { python3 -c "
p = '$WORK/data.txt'
open(p).read()
open(p, 'w').close()
"; }

count_all() { echo $(( $(count_msgs "$WORK/data.txt") + $(count_msgs "$WORK/data.snap") )); }

# ── assert_one_winner must distinguish correct from broken ───────────────────

echo '--- assert_one_winner ---'
rm -f "$WORK"/excl.lock
result=$(verdict_of assert_one_winner "exclusive" 8 "$WORK/excl.lock" exclusive_take)
if [ "$result" = "OK" ]; then
  ok 'passes an O_EXCL implementation'
else
  bad 'rejected a correct implementation'
fi

rm -f "$WORK"/racy.lock
result=$(verdict_of assert_one_winner "racy" 8 "$WORK/racy.lock" racy_take)
if [ "$result" = "FAIL" ]; then
  ok 'CATCHES a check-then-act implementation (the original claim bug)'
else
  bad 'a check-then-act race passed - the assertion cannot fail'
fi

# ── assert_no_loss must distinguish correct from broken ──────────────────────

echo '--- assert_no_loss ---'
rm -f "$WORK"/data.txt "$WORK"/data.snap
result=$(verdict_of assert_no_loss "safe" 20 count_all writer_20 safe_consume)
if [ "$result" = "OK" ]; then
  ok 'passes an atomic-claim consumer'
else
  bad 'rejected a correct consumer'
fi

rm -f "$WORK"/data.txt "$WORK"/data.snap
result=$(verdict_of assert_no_loss "lossy" 20 count_all writer_20 lossy_consume)
if [ "$result" = "FAIL" ]; then
  ok 'CATCHES a read-then-truncate consumer (the original inbox bug)'
else
  bad 'a lossy consumer passed - the assertion cannot fail'
fi

# ── and it must refuse to pass vacuously ─────────────────────────────────────

echo '--- a test that never raced must not report success ---'
rm -f "$WORK"/data.txt "$WORK"/data.snap
writer_instant() { local i; for i in $(seq 1 20); do echo "line-$i" >> "$WORK/data.txt"; done; }
result=$(verdict_of assert_no_loss "vacuous" 20 count_all writer_instant safe_consume)
if [ "$result" = "FAIL" ]; then
  ok 'fails when the writer finished before the destructive op (no interleave)'
else
  bad 'reported success without the race happening - this is the vacuous pass'
fi

echo '--- the shared helpers behave ---'
check 'check compares equal values' 5 5
check_rc 'check_rc compares return codes' 0 0
rm -f "$WORK/missing.txt"
check 'count_msgs on a missing file is 0' 0 "$(count_msgs "$WORK/missing.txt")"
printf 'a\nb\nc\n' > "$WORK/three.txt"
check 'count_msgs counts lines' 3 "$(count_msgs "$WORK/three.txt")"

finish
