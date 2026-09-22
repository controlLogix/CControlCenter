#!/usr/bin/env bash
# Verify the run protocol: assignment, reviewer-only verdicts, the completion gate,
# escalation, derived staleness and forced capture.
#   bash <(tr -d '\r' < dashboard/test_run.sh)
#
# Throwaway AGENTMUX_HOME, no tmux and no agents required. That is deliberate: the
# gate and the fold are the parts that must be right, and like the claim mechanism
# they are testable with nothing running.
#
# WHAT THIS PROTECTS. Before this, a completion signal was prose in a brief - a worker
# printed "ORCHESTRATION COMPLETE" and the orchestrator grepped for it. Nothing
# verified work before it shipped, and the penguin deliverable reached the operator's
# Desktop with three factual errors as a result.
set -u
[ -f taskmgmt/run.py ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }

HOME_DIR="$(mktemp -d)"
trap 'rm -rf "$HOME_DIR"' EXIT
export AGENTMUX_HOME="$HOME_DIR"
export AGENTMUX_DASHBOARD="http://127.0.0.1:1"     # unreachable: journal falls back
RUN="python3 taskmgmt/run.py"

pass=0; fail=0
ok()  { printf '  ok    %s\n' "$1"; pass=$((pass + 1)); }
bad() { printf '  FAIL  %s\n' "$1"; fail=$((fail + 1)); }
rc_is() { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (rc $3, wanted $2)"; fi; }

echo '--- a run is an explicit boundary ---'
r=$($RUN start "make the thing" --by orchestrator 2>/dev/null)
if printf '%s' "$r" | grep -Eq '^[0-9a-f]{6}$'; then ok "start returns a run id ($r)"; else bad "bad run id: $r"; fi
[ -f "$HOME_DIR/runs/$r/request.md" ] && ok 'the request is recorded verbatim' || bad 'request.md missing'
grep -q 'make the thing' "$HOME_DIR/runs/$r/request.md" && ok 'and it is the operator text' || bad 'request text wrong'
$RUN status "$r" >/dev/null 2>&1; rc_is 'status works on an empty run' 0 $?

echo '--- assignment ---'
j1=$($RUN assign "$r" --worker w1 --reviewer rev --brief "do part one" 2>/dev/null)
j2=$($RUN assign "$r" --worker w2 --reviewer rev --brief "do part two" 2>/dev/null)
if [ "$j1" = "$r/1" ] && [ "$j2" = "$r/2" ]; then ok "job ids are run-scoped ($j1, $j2)"; else bad "job ids wrong: $j1 $j2"; fi
$RUN assign "$r" --worker same --reviewer same >/dev/null 2>&1
rc_is 'a worker cannot review its own job' 2 $?
$RUN assign "$r" --worker 'bad name' --reviewer rev >/dev/null 2>&1
rc_is 'invalid agent names are refused' 2 $?
$RUN assign zzzzzz --worker w1 --reviewer rev >/dev/null 2>&1
rc_is 'assigning to a nonexistent run is refused' 2 $?

echo '--- THE GATE: completion refuses while any job is unverified ---'
$RUN complete "$r" >/dev/null 2>&1
rc_is 'refuses with nothing verified' 1 $?
out=$($RUN complete "$r" 2>&1)
case "$out" in *"$j1"*) ok 'the refusal names the blocking job' ;; *) bad "refusal did not name $j1" ;; esac
case "$out" in *--force*) ok 'and mentions the override' ;; *) bad 'no override mentioned' ;; esac
[ -f "$HOME_DIR/runs/$r/COMPLETE" ] && bad 'COMPLETE was created despite refusal' || ok 'no COMPLETE marker was created'

echo '--- only the reviewer may sign off ---'
$RUN submit "$j1" --by w1 --summary "part one done" >/dev/null 2>&1
rc_is 'the worker submits' 0 $?
$RUN verdict "$j1" --by w1 --pass >/dev/null 2>&1
rc_is 'the worker cannot verify its own work' 2 $?
$RUN verdict "$j1" --by someone-else --pass >/dev/null 2>&1
rc_is 'a third party cannot verify it either' 2 $?
$RUN verdict "$j1" --by rev --pass --reason "looks right" >/dev/null 2>&1
rc_is 'the assigned reviewer can' 0 $?
$RUN status "$r" 2>/dev/null | grep -q 'verified' && ok 'the job folds to verified' || bad 'not verified'

echo '--- one verified job is not enough ---'
$RUN complete "$r" >/dev/null 2>&1
rc_is 'still refuses with the second job open' 1 $?
out=$($RUN complete "$r" 2>&1)
case "$out" in *"$j2"*) ok "the refusal names only the unverified job" ;; *) bad 'wrong job named' ;; esac

echo '--- and then it completes ---'
$RUN submit "$j2" --by w2 --summary "part two done" >/dev/null 2>&1
$RUN verdict "$j2" --by rev --pass --reason ok >/dev/null 2>&1
$RUN complete "$r" >/dev/null 2>&1
rc_is 'completes once every job is verified' 0 $?
[ -f "$HOME_DIR/runs/$r/COMPLETE" ] && ok 'COMPLETE marker exists' || bad 'no COMPLETE marker'
$RUN complete "$r" >/dev/null 2>&1
rc_is 'completion cannot fire twice (O_EXCL)' 1 $?
grep -q 'run .* COMPLETE' "$HOME_DIR/inbox/orchestrator.jsonl" 2>/dev/null \
  && ok 'the signal reached the orchestrator inbox' || bad 'no inbox notification'
grep -q 'COMPLETE' "$HOME_DIR/journal.jsonl" 2>/dev/null \
  && ok 'and the journal (via its offline fallback)' || bad 'no journal entry'

echo '--- three strikes escalates and keeps the gate shut ---'
r2=$($RUN start "escalation case" 2>/dev/null)
j=$($RUN assign "$r2" --worker w1 --reviewer rev 2>/dev/null)
for attempt in 1 2 3; do
  $RUN submit "$j" --by w1 --summary "try $attempt" >/dev/null 2>&1
  $RUN verdict "$j" --by rev --fail --reason "still wrong ($attempt)" >/dev/null 2>&1
done
$RUN status "$r2" 2>/dev/null | grep -q 'escalated' && ok 'the job escalates on the third failure' || bad 'no escalation'
$RUN complete "$r2" >/dev/null 2>&1
rc_is 'an escalated job still blocks completion' 1 $?
grep -q 'ESCALATED' "$HOME_DIR/inbox/orchestrator.jsonl" 2>/dev/null \
  && ok 'escalation notifies the orchestrator' || bad 'no escalation notice'

echo '--- forced completion records what was left unfinished ---'
$RUN complete "$r2" --force >/dev/null 2>&1
rc_is 'force overrides the gate' 0 $?
report="$HOME_DIR/runs/$r2/FORCED.md"
[ -f "$report" ] && ok 'a forced report is written' || bad 'no FORCED.md'
grep -q "$j" "$report" 2>/dev/null && ok 'it names the unverified job' || bad 'job not named'
grep -q 'still wrong (3)' "$report" 2>/dev/null && ok 'and the last rejection reason' || bad 'reason missing'
grep -q 'attempts: 3' "$report" 2>/dev/null && ok 'and the attempt count' || bad 'attempts missing'
$RUN status "$r2" 2>/dev/null | grep -q 'FORCED' && ok 'status shows the run was forced, not clean' || bad 'forced state not shown'

echo '--- CONCURRENCY: simultaneous writers must not lose an event ---'
# The design review caught this: a mutable runs/<id>.json would lose one of two
# concurrent submits, and a lost submit hangs the gate forever. Append-only + fold
# is the fix, and this is the check that proves it.
r3=$($RUN start "concurrency" 2>/dev/null)
for n in $(seq 1 12); do $RUN assign "$r3" --worker "w$n" --reviewer rev >/dev/null 2>&1; done
for n in $(seq 1 12); do
  ( $RUN submit "$r3/$n" --by "w$n" --summary "concurrent $n" >/dev/null 2>&1 ) &
done
wait
submitted=$($RUN status "$r3" --json 2>/dev/null \
  | python3 -c 'import json,sys; print(sum(1 for j in json.load(sys.stdin)["jobs"] if j["state"]=="submitted"))')
if [ "$submitted" = "12" ]; then
  ok 'all 12 concurrent submits survived the fold'
else
  bad "only $submitted of 12 submits survived - events were lost"
fi
if python3 -c 'import json,sys; [json.loads(l) for l in open(sys.argv[1]) if l.strip()]' \
     "$HOME_DIR/runs/$r3/events.jsonl" 2>/dev/null; then
  ok 'every event record is intact JSON - no torn appends'
else
  bad 'a record was torn'
fi

echo '--- a long verdict goes in a file, not in the event log ---'
r4=$($RUN start "size" 2>/dev/null)
j4=$($RUN assign "$r4" --worker w1 --reviewer rev 2>/dev/null)
$RUN submit "$j4" --by w1 >/dev/null 2>&1
python3 -c 'print("x" * 5000)' > "$HOME_DIR/long.md"
$RUN verdict "$j4" --by rev --fail --reason-file "$HOME_DIR/long.md" >/dev/null 2>&1
rc_is 'a reason file is accepted' 0 $?
[ -f "$HOME_DIR/runs/$r4/jobs/1/verdict-1.md" ] && ok 'the long reasoning is kept in a sidecar' || bad 'no verdict file'
longest=$(awk '{ if (length($0) > max) max = length($0) } END { print max+0 }' "$HOME_DIR/runs/$r4/events.jsonl")
if [ "$longest" -le 1024 ]; then
  ok "no event exceeds the 1024-byte atomic cap (longest $longest)"
else
  bad "an event is $longest bytes - appends are no longer atomic"
fi

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ] || exit 1
