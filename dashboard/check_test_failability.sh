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
. dashboard/testlib.sh
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
# The mistyped-key refusal: at this base need_key still raised out of sixteen verbs.
test_coordination.sh         514bd33    3
BASELINES
  SELF_TEST=1
else
  SELF_TEST=0
fi

check_row() {
  local suite="$1" ref="$2" expected="$3" extra="$4"
  local base head tree output actual rc summary reported
  # .sh and .py both, because the extension was the only reason a python suite
  # could not be pinned. A suite still has to print the standard summary to be
  # accepted, which is the real bar - a unittest-style suite prints "OK"/"FAILED"
  # and is rejected below by the summary check, visibly, rather than by its name
  # here. smoke.sh stays out: it drives a LIVE dashboard on 8787, so running it
  # from a disposable base tree would write to whichever board answers.
  if [[ ! "$suite" =~ ^test_[A-Za-z0-9_]+\.(sh|py)$ ]] ||
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
  if ! mkdir -p "$tree/dashboard" ||
     ! cp dashboard/testlib.sh "dashboard/$suite" "$tree/dashboard/"; then
    bad "failability: cannot copy current $suite and testlib into base=$ref"
    return
  fi
  output="$tree/output.log"
  # The suites supply their own homes and identities. The invoking worker's pane
  # identity must not interfere with test_run's synthetic workers and reviewers.
  if [[ "$suite" == *.py ]]; then
    (cd "$tree" || exit 2; unset AGENTMUX_AGENT; python3 "dashboard/$suite") > "$output" 2>&1
  else
    (cd "$tree" || exit 2; unset AGENTMUX_AGENT; bash <(tr -d '\r' < "dashboard/$suite")) > "$output" 2>&1
  fi
  rc=$?
  actual=$(grep -cE '^  FAIL([[:space:]]|$)' "$output" || true)
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
  for label in nondiscriminating below-threshold discriminating crashed head head-alias unrelated missing invalid-minimum live-suite outside; do
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
      # smoke.sh drives the live dashboard; a base-tree run of it would write to
      # whichever board is answering. It must stay unpinnable BY NAME.
      live-suite) printf 'smoke.sh %s 1\n' "$old" > "$fixture/table"; needle='invalid row' ;;
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

# HOW MANY SUITES ARE PINNED AT ALL.
#
# This gate proves that the suites IN ITS TABLE can fail on pre-fix code. It has
# never said anything about the ones that are not, and there are far more of those
# - which reads exactly like full coverage to anyone watching it go green. That is
# the same shape as the bugs it exists to catch: a mechanism that appears to work
# and quietly covers less than it looks like it does.
#
# So the number is printed. It is deliberately NOT a failure: each row costs a full
# suite run at a historical base, and a gate that demanded all of them would take
# long enough that people would stop running it. Stating the sample size is the
# honest middle.
if [ "$SELF_TEST" = 1 ] && [ -f dashboard/run_tests.sh ]; then
  registered=$(grep -oE '^run [A-Za-z0-9_.]+' dashboard/run_tests.sh | awk '{print $2}' | sort -u)
  pinned=$(awk '!/^#/ && NF {print $1}' "$TABLE" | sort -u)
  missing=$(comm -23 <(printf '%s\n' "$registered") <(printf '%s\n' "$pinned"))
  echo "failability: $(printf '%s\n' "$pinned" | grep -c .) of" \
       "$(printf '%s\n' "$registered" | grep -c .) registered suites have a pinned baseline"
  printf '%s\n' "$missing" | grep -c . >/dev/null && \
    printf '  unpinned: %s\n' "$(printf '%s ' $missing)" | fold -s -w 100 | sed '2,$s/^/            /'
fi
finish
