#!/usr/bin/env bash
# Differential proof that the current regression suites can fail on known-old code.
#   bash <(tr -d '\r' < dashboard/check_test_failability.sh)
#
# A file, not nested shell quoting: wsl.exe bash -c wrappers expand inline commands
# in the wrong shell. See check_test_residue.sh for the same constraint.
#
# LIMIT: the base MUST predate the fix. HEAD (including aliases resolving to HEAD)
# cannot demonstrate regression detection. Neither can an unrelated/future commit.
# For an uncommitted fix whose base is still HEAD, validate in a disposable
# descendant checkout; do not bypass this rule or move the workspace HEAD.
# Never advance a baseline merely to make this check green. Counts are a lower bound,
# not proof that each failure has the right cause; review the differential logs too.
# A suite crash is NOT evidence of discrimination: require its complete testlib summary
# and matching failure count/exit status, in addition to the declared threshold.
#
# --table FILE selects an explicit suite/base/minimum table (also used by the self-
# tests). With the built-in table, known-broken fixtures test this checker first.
set -uo pipefail
TABLE=""
if [ "$#" -gt 0 ]; then
  if [ "$#" = 2 ] && [ "$1" = --table ] && [ -f "$2" ]; then
    TABLE="$(realpath "$2")"
  else
    echo 'usage: check_test_failability.sh [--table FILE]' >&2
    exit 2
  fi
fi
if [ "$(git rev-parse --is-inside-work-tree 2>/dev/null)" != true ]; then
  echo 'SKIP failability: not in a git checkout; archived trees have no base history'
  echo 'passed 0, failed 0'
  exit 0
fi
REPO="$(git rev-parse --show-toplevel)"
cd "$REPO" || exit 2
. <(tr -d '\r' < dashboard/testlib.sh)   # tr: testlib may arrive CRLF; bash cannot source that
WORK="$(mktemp -d)" || exit 2
trap 'rm -rf "$WORK"' EXIT
skipped=0

if [ -z "$TABLE" ]; then
  TABLE="$WORK/baselines"
  # Measured after d49d4b jobs 1 and 2 (2026-09-22). Explicit historical refs only.
  # suite                    base       minimum FAIL lines
  cat > "$TABLE" <<'BASELINES'
test_argguard.sh             753d791    11
test_run.sh                  753d791    9
test_lifecycle.sh            753d791    15
# Job 1: direct coordination identity enforcement.
test_coordination.sh        a2258a8    12
# Job 2: selected-home auth, Atlassian, and safe fresh-db paths.
test_lifecycle.sh            a2258a8    6
# Residue gate and temporary dashboard lifecycle, including signal restoration.
test_residue.sh              b64cef1    26
# The 9p EIO that killed whole scans: Path.exists() on /mnt/c re-raises anything
# that is not ENOENT/ENOTDIR/EBADF/ELOOP, and neighbour_table() - documented
# "Never fatal" - let it out. 5 of 13 fail against the pre-fix module.
test_netscan.py              6afd65b    5
# The localStorage migration. Against a base with no migration block every
# property fails cleanly rather than crashing - which is the point: a crashed
# suite is not proof, so the block's absence must FAIL, not throw.
test_frontend_storage.sh     6afd65b    8
# The equipment-write gate. Against the commit before it, iiot.js still used a
# one-click window.confirm and four of the five properties do not hold.
test_frontend_iiot_write.sh  00912ba    4
# TM-025, the two-clock age, and the feed-level banner that came with it.
# Against the commit before the fix the panel renders a CLOCK READING ("last
# good 6:26:40 AM") instead of an age, decides staleness with
# Date.now()/1000 - last_good so a fresh feed reads STALE the moment the
# browser's clock is ten minutes fast, and prints one word for four different
# faults. 7 of 8 fail there.
test_frontend_iiot_age.sh    6b2d581    7
# The unified write journal. Against the commit before it, enip/logix/ads each
# kept their own file and writejournal.py does not exist - so all 22 fail, via
# the suite's guarded import rather than an ImportError that would crash it and
# prove nothing. A floor rather than an equality: the count only grows, since a
# tree without the module fails every test in the suite by construction.
test_writejournal.py         aaa5cae    22
# The audited pycomm3 wrapper. Against the commit before it, field/rockwell.py
# does not exist - so all 20 fail through the suite's guarded import rather than
# an ImportError that would crash it. A floor, like the row above: the count
# only grows, since a tree without the module fails every test by construction.
test_rockwell.py             9855905    20
# The ticket gate. Against the commit before it, field/tickets.py does not
# exist and all 14 fail through the guarded import. A floor: the count only
# grows, since a tree without the module fails every test by construction.
test_field_tickets.py        838c5f9    14
# The serving/takeover status. Against the commit before it, serving_snapshot()
# does not exist and all 8 fail through the guarded import. Measured in WSL,
# where the gate runs: on a platform with no os.getuid the marker cases skip
# and only 3 fail, which is why the number is measured rather than counted.
test_serving.py              bb0ae43    8
# Can the gate say WHAT broke? Against the commit before the reporting fixes,
# test_e2e.sh printed its diagnostic after its summary, test_e2e.mjs printed
# its roll-call after the counts, and the runner's grep could not match the
# e2e failure shape at all. 5 of 14 fail there.
test_gate_reporting.sh       77696cb    5
# The device tree. Against the commit before it neither devicetree.py nor
# devicetree.js exists, and both suites fail cleanly through their guards
# rather than crashing - which is what makes the proof mean anything.
test_devicetree.py           85e6ddb    18
test_frontend_devicetree.sh  85e6ddb    1
# The order interlocks. Against the commit before them neither module exists,
# and both suites fail cleanly through their guarded imports.
agentmux-broker/test_killswitch.py  b8041df    24
agentmux-broker/test_guardrails.py  b8041df    25
BASELINES
  SELF_TEST=1
else
  SELF_TEST=0
fi

check_row() {
  local suite="$1" ref="$2" expected="$3" extra="$4"
  local base head tree output actual rc summary reported
  # A suite may name its directory: agentmux-broker/test_killswitch.py. The
  # bare form still means dashboard/, so every existing row is unchanged.
  if [[ ! "$suite" =~ ^([A-Za-z0-9_-]+/)?test_[A-Za-z0-9_]+\.(sh|py)$ ]] ||
     [[ ! "$expected" =~ ^[1-9][0-9]*$ ]] || [ -n "$extra" ]; then
    bad "failability: invalid row ($suite $ref $expected); expected a suite, explicit base, positive minimum"
    return
  fi
  if ! base=$(git rev-parse --verify --end-of-options "$ref^{commit}" 2>/dev/null); then
    echo "SKIP failability: $suite base=$ref expected=$expected actual=unavailable (base ref missing)"
    skipped=$((skipped + 1))
    return
  fi
  head=$(git rev-parse HEAD)
  if [ "$base" = "$head" ]; then
    bad "failability: $suite base=$ref resolves to HEAD; the base must predate the fix"
    return
  fi
  if ! git merge-base --is-ancestor "$base" "$head"; then
    bad "failability: $suite base=$ref is not an ancestor of HEAD; unrelated code cannot prove this regression"
    return
  fi
  tree=$(mktemp -d "$WORK/base.XXXXXX") || { bad 'failability: cannot make base tree'; return; }
  if ! git archive "$base" | tar -x -C "$tree"; then
    bad "failability: could not archive $suite base=$ref"
    return
  fi
  # testlib goes in for a shell suite; harmless for a python one, and copying it
  # unconditionally keeps the .sh path byte-identical to what it was.
  # Where the suite lives, and where it is run from. A bare name means
  # dashboard/; a name carrying a directory keeps it. testlib always goes into
  # dashboard/, because that is where every suite sources it from.
  local suite_dir suite_file
  case "$suite" in
    */*) suite_dir="${suite%/*}"; suite_file="${suite##*/}" ;;
    *)   suite_dir="dashboard";  suite_file="$suite" ;;
  esac
  if ! mkdir -p "$tree/dashboard" "$tree/$suite_dir" ||
     ! cp dashboard/testlib.sh "$tree/dashboard/" ||
     ! cp "$suite_dir/$suite_file" "$tree/$suite_dir/"; then
    bad "failability: cannot copy current $suite and testlib into base=$ref"
    return
  fi
  output="$tree/output.log"
  # The suites supply their own homes and identities. The invoking worker's pane
  # identity must not interfere with test_run's synthetic workers and reviewers.
  # Two kinds of suite, so two invocations and two failure shapes. A python suite
  # cannot be run through process substitution, and it prints unittest's
  # 'FAIL:'/'ERROR:' at column zero rather than testlib's two-space '  FAIL'.
  # run_tests.sh:186-192 documents the same distinction and why matching only one
  # shape meant you could see THAT a suite broke and never WHAT broke.
  if [[ "$suite" == *.py ]]; then
    (cd "$tree" || exit 2; unset AGENTMUX_AGENT; python3 "$suite_dir/$suite_file") > "$output" 2>&1
    rc=$?
    actual=$(grep -cE '^(FAIL|ERROR):' "$output" || true)
  else
    (cd "$tree" || exit 2; unset AGENTMUX_AGENT; bash <(tr -d '\r' < "$suite_dir/$suite_file")) > "$output" 2>&1
    rc=$?
    actual=$(grep -cE '^  FAIL([[:space:]]|$)' "$output" || true)
  fi
  summary=$(tail -1 "$output")
  reported=""
  if [[ "$summary" =~ ^passed\ ([0-9]+),\ failed\ ([0-9]+)$ ]]; then
    reported="${BASH_REMATCH[2]}"
  fi
  if [ "$reported" != "$actual" ] ||
     { [ "$actual" = 0 ] && [ "$rc" != 0 ]; } ||
     { [ "$actual" != 0 ] && [ "$rc" != 1 ]; }; then
    bad "failability: $suite base=$ref expected=$expected actual=$actual invalid summary/exit (rc=$rc); a crashed suite is not proof"
    tail -12 "$output"
  elif [ "$actual" -lt "$expected" ]; then
    bad "failability: $suite base=$ref expected=$expected actual=$actual; too few failures on pre-fix code"
  else
    ok "failability: $suite base=$ref expected=$expected actual=$actual"
  fi
  rm -rf "$tree"
}

self_test() {
  local fixture="$WORK/checker-fixture" checker="$REPO/dashboard/check_test_failability.sh"
  local old unrelated output rc label expected needle
  mkdir -p "$fixture/dashboard" "$WORK/outside"
  cp dashboard/testlib.sh "$fixture/dashboard/"
  git -C "$fixture" init -q || return 1
  git -C "$fixture" config user.name 'Failability test'
  git -C "$fixture" config user.email 'failability@example.invalid'
  printf 'broken\n' > "$fixture/behavior"
  git -C "$fixture" add dashboard/testlib.sh behavior
  git -C "$fixture" commit -qm base || return 1
  old=$(git -C "$fixture" rev-parse HEAD)
  printf 'fixed\n' > "$fixture/behavior"
  git -C "$fixture" add behavior
  git -C "$fixture" commit -qm current || return 1
  unrelated=$(printf 'unrelated\n' | git -C "$fixture" commit-tree 'HEAD^{tree}') || return 1

  # Every probe invokes the REAL checker in a disposable git repository. A stub
  # suite that always passes is deliberately useless at detecting its base's bugs.
  for label in nondiscriminating below-threshold discriminating crashed head head-alias unrelated missing invalid-minimum outside; do
    printf '. dashboard/testlib.sh\nok "always green"\nfinish\n' > "$fixture/dashboard/test_fixture.sh"
    printf 'test_fixture.sh %s 1\n' "$old" > "$fixture/table"
    expected=1; needle='actual=0; too few failures'
    case "$label" in
      below-threshold)
        printf '. dashboard/testlib.sh\nbad "one"\nfinish\n' > "$fixture/dashboard/test_fixture.sh"
        printf 'test_fixture.sh %s 2\n' "$old" > "$fixture/table"
        needle='expected=2 actual=1; too few failures' ;;
      discriminating)
        printf '. dashboard/testlib.sh\ncheck one fixed "$(cat behavior)"\ncheck two fixed "$(cat behavior)"\nfinish\n' > "$fixture/dashboard/test_fixture.sh"
        printf 'test_fixture.sh %s 2\n' "$old" > "$fixture/table"
        expected=0; needle='expected=2 actual=2' ;;
      crashed)
        printf '. dashboard/testlib.sh\nbad "one"\nexit 2\n' > "$fixture/dashboard/test_fixture.sh"
        needle='invalid summary/exit' ;;
      head) printf 'test_fixture.sh HEAD 1\n' > "$fixture/table"; needle='resolves to HEAD' ;;
      head-alias)
        printf 'test_fixture.sh %s 1\n' "$(git -C "$fixture" rev-parse HEAD)" > "$fixture/table"
        needle='resolves to HEAD' ;;
      unrelated) printf 'test_fixture.sh %s 1\n' "$unrelated" > "$fixture/table"; needle='not an ancestor' ;;
      missing) printf 'test_fixture.sh no-such-base 1\n' > "$fixture/table"; expected=0; needle='SKIP failability:' ;;
      invalid-minimum) printf 'test_fixture.sh %s 0\n' "$old" > "$fixture/table"; needle='positive minimum' ;;
      outside) expected=0; needle='SKIP failability: not in a git checkout' ;;
    esac
    if [ "$label" = outside ]; then
      output=$(cd "$WORK/outside" && bash "$checker" --table "$fixture/table" 2>&1); rc=$?
    else
      output=$(cd "$fixture" && bash "$checker" --table "$fixture/table" 2>&1); rc=$?
    fi
    if [ "$rc" = "$expected" ] && [[ "$output" == *"$needle"* ]]; then
      ok "failability self-test: $label (exit=$rc)"
    else
      bad "failability self-test: $label (exit=$rc expected=$expected)"
      printf '%s\n' "$output"
    fi
  done
}

if [ "$SELF_TEST" = 1 ]; then
  self_test || bad 'failability: could not construct the checker fixtures'
fi
rows=0
while read -r suite ref minimum extra; do
  [ -z "$suite" ] && continue
  [[ "$suite" == \#* ]] && continue
  rows=$((rows + 1))
  check_row "$suite" "$ref" "$minimum" "$extra"
done < "$TABLE"
[ "$rows" -gt 0 ] || bad 'failability: empty baseline table checks nothing'
echo "failability: $skipped baseline(s) skipped"
finish
