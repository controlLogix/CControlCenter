#!/usr/bin/env bash
# Shared test helpers for agentmux suites.
#
#   source dashboard/testlib.sh       # from the repo root
#
# WHY THIS EXISTS
# ---------------
# Two reasons, and the second is the important one.
#
# 1. Five suites had each grown their own `ok`/`bad`/`check`/`rc_is`/`check_rc`, with
#    different names for the same thing. Writing a test in one suite and pasting it
#    into another produced "rc_is: command not found" - which happened.
#
# 2. Every real defect found on 2026-09-22 was found by a CONCURRENCY or PROPERTY test,
#    not by an example test and not by reading:
#      - `cmd_claim` produced two winners under a 16-way race
#      - `inbox --clear` lost messages that arrived while it printed
#      - the claim race only surfaced at all because an unrelated change shifted timing
#    Those two shapes - "exactly one winner" and "nothing was lost" - are the tools that
#    work here, so they belong in the toolbox rather than being reinvented per suite.
#
# THE RULE THIS FILE ENFORCES: a concurrency test that cannot prove it was concurrent
# is decoration. `assert_no_loss` fails if the interleave did not happen, because the
# first version of that test passed vacuously - the writer finished before the
# destructive operation even started, and it looked green.

# ── counters and reporting ───────────────────────────────────────────────────

pass=0
fail=0

ok()   { printf '  ok    %s\n' "$1"; pass=$((pass + 1)); }
bad()  { printf '  FAIL  %s\n' "$1"; fail=$((fail + 1)); }

# check <label> <expected> <actual>
check() {
  if [ "$2" = "$3" ]; then
    printf '  ok    %-52s %s\n' "$1" "$3"; pass=$((pass + 1))
  else
    printf '  FAIL  %-52s got [%s] want [%s]\n' "$1" "$3" "$2"; fail=$((fail + 1))
  fi
}

# check_rc <label> <expected-rc> <actual-rc>   (alias: rc_is, for suites that used it)
check_rc() {
  if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (rc $3, wanted $2)"; fi
}
rc_is() { check_rc "$@"; }

# Count JSON lines in a file that may not exist. `grep -c` on a missing file both
# prints 0 AND returns non-zero, so a naive `|| echo 0` yields "0\n0".
count_msgs() { [ -f "$1" ] && grep -c . "$1" 2>/dev/null || printf '0'; }

finish() {
  echo
  echo "passed $pass, failed $fail"
  [ "$fail" -eq 0 ] || exit 1
}

# ── assert_one_winner ────────────────────────────────────────────────────────
#
#   assert_one_winner <label> <n> <artifact-glob> <command...>
#
# Runs <command> <n> times concurrently. Exactly one invocation must succeed, and
# exactly one artifact must exist afterwards. This is the shape that caught the
# two-winner claim bug - and only under stress, so callers should loop it.
assert_one_winner() {
  local label="$1" n="$2" glob="$3"; shift 3
  local winners
  winners="$(mktemp)"
  local i
  for i in $(seq 1 "$n"); do
    ( "$@" >/dev/null 2>&1 && echo "win" >> "$winners" ) &
  done
  wait
  local count files
  count=$(count_msgs "$winners")
  files=$(ls $glob 2>/dev/null | wc -l)
  rm -f "$winners"
  if [ "$count" = "1" ] && [ "$files" = "1" ]; then
    ok "$label ($n concurrent, 1 winner, 1 artifact)"
  else
    bad "$label - $count winner(s), $files artifact(s) out of $n attempts"
  fi
}

# ── assert_no_loss ───────────────────────────────────────────────────────────
#
#   assert_no_loss <label> <expected-total> <count-fn> <writer-fn> <destructive-fn>
#
# Runs <writer-fn> in the background and fires <destructive-fn> partway through, then
# asks <count-fn> for the total surviving records. Nothing may be lost.
#
# It ALSO fails when the two did not overlap. That is not pedantry: the first version
# of the inbox test passed while proving nothing, because the writer finished before
# the clear began. A green concurrency test that never raced is worse than no test,
# because it is believed.
assert_no_loss() {
  local label="$1" expected="$2" count_fn="$3" writer_fn="$4" destructive_fn="$5"
  "$writer_fn" &
  local writer=$!
  sleep 0.3
  local mid
  mid=$("$count_fn")          # how much existed when the destructive op fired
  "$destructive_fn"
  wait "$writer"
  local total
  total=$("$count_fn")
  if [ "$total" -ne "$expected" ]; then
    bad "$label - $((expected - total)) record(s) lost ($total of $expected survived)"
    return
  fi
  if [ "$mid" -ge "$expected" ] || [ "$mid" -eq 0 ]; then
    bad "$label - no interleave (writer had produced $mid of $expected); the race was not exercised"
    return
  fi
  ok "$label (all $expected survived; destructive op fired at $mid)"
}
