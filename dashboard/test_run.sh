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
# shellcheck source=/dev/null
. dashboard/testlib.sh          # ok/bad/check/check_rc/rc_is/count_msgs, one copy

HOME_DIR="$(mktemp -d)"
trap 'rm -rf "$HOME_DIR"' EXIT
export AGENTMUX_HOME="$HOME_DIR"
export AGENTMUX_DASHBOARD="http://127.0.0.1:1"     # unreachable: journal falls back

# Identity is resolved against LIVE tmux sessions, and this suite deliberately runs
# with no tmux at all - see the header. The escape hatch exists for exactly this, and
# for nothing else: it is never set by the harness, only by tests. The negative cases
# at the bottom of this file unset it, because a guard only tested with its own
# bypass turned on is not tested.
export AGENTMUX_TRUST_IDENTITY=1
RUN="python3 taskmgmt/run.py"

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


echo '--- identity is resolved, not accepted ---'
# `run verdict --by claude` was believed on the strength of the string. During live
# testing the ORCHESTRATOR typed a verdict with --by set to the reviewer's name, and
# the ledger recorded a review that never happened - which makes the reviewer field,
# and therefore the gate, decorative.
ir=$($RUN start "identity checks" 2>/dev/null)
$RUN assign "$ir" --worker worker-a --reviewer rev-a >/dev/null 2>&1
ijob="$ir/1"

# A pane cannot rename itself with --by.
#
# The discriminating case is the REVIEWER's pane submitting the WORKER's job. Old code
# compared --by against row["worker"] and nothing else, so `--by worker-a` from rev-a's
# pane was accepted and the ledger recorded a submission worker-a never made. Passing a
# name that matches nobody would have been refused by the old code too, for an unrelated
# reason, and would have proved nothing.
AGENTMUX_AGENT=rev-a $RUN submit "$ijob" --by worker-a --summary x >/dev/null 2>&1
check_rc "the reviewer's pane cannot submit as the worker" 2 "$?"
AGENTMUX_AGENT=worker-a $RUN submit "$ijob" --by someone-else >/dev/null 2>&1
check_rc '--by that disagrees with the pane is refused' 2 "$?"

AGENTMUX_AGENT=worker-a $RUN submit "$ijob" --summary done >/dev/null 2>&1
check_rc 'the pane submits as itself with no --by at all' 0 "$?"

# The worker still cannot sign off its own work, by any route.
AGENTMUX_AGENT=worker-a $RUN verdict "$ijob" --pass --reason ok >/dev/null 2>&1
check_rc 'the worker cannot verify its own job' 2 "$?"

# And the orchestrator cannot transcribe a verdict for the reviewer.
AGENTMUX_AGENT= $RUN verdict "$ijob" --by rev-a --pass --reason ok >/dev/null 2>&1
check_rc 'a --by verdict from outside any pane is accepted only under the test flag' 0 "$?"

echo '--- and the guard itself works when it is not bypassed ---'
# Everything above runs with AGENTMUX_TRUST_IDENTITY=1, so it proves the plumbing and
# NOT the liveness check. Turn the bypass off: with no tmux running, live_agents() is
# empty, so every named identity must now be refused. If these pass, the check is real.
jr=$($RUN start "liveness" 2>/dev/null)
$RUN assign "$jr" --worker worker-b --reviewer rev-b >/dev/null 2>&1
jjob="$jr/1"
( unset AGENTMUX_TRUST_IDENTITY; AGENTMUX_AGENT=worker-b $RUN submit "$jjob" --summary x ) >/dev/null 2>&1
check_rc 'a non-live identity cannot submit' 2 "$?"
( unset AGENTMUX_TRUST_IDENTITY; AGENTMUX_AGENT=rev-b $RUN verdict "$jjob" --pass --reason x ) >/dev/null 2>&1
check_rc 'a non-live identity cannot verify' 2 "$?"

# complete is the orchestrator's, and the orchestrator has no session - so "not a live
# agent" is exactly the test for "not inside a pane".
( unset AGENTMUX_TRUST_IDENTITY; AGENTMUX_AGENT=worker-b $RUN complete "$jr" --force ) >/dev/null 2>&1
check_rc 'an agent cannot complete the run it is working in' 2 "$?"
$RUN complete "$jr" --by rev-b --force >/dev/null 2>&1
check_rc '--by on complete is refused rather than silently ignored' 2 "$?"

echo '--- a verdict cannot land after the gate has closed ---'
# The gate used to fold, decide, and only then take COMPLETE. A --fail arriving in
# that window completed a run with a rejected job while printing "all verified".
# TWO jobs, and the run is FORCED with the second still submitted. That is what makes
# this discriminating: verdicting an already-verified job was refused by the old code
# too ("verified, nothing to verify"), so a one-job version of this test went green
# without exercising the race at all. A job left in `submitted` is genuinely
# verdict-able, and the old code accepted the verdict happily - producing a fail
# recorded against a run whose result had already been reported.
kr=$($RUN start "gate race" 2>/dev/null)
$RUN assign "$kr" --worker worker-c --reviewer rev-c >/dev/null 2>&1
$RUN assign "$kr" --worker worker-c --reviewer rev-c >/dev/null 2>&1
kjob="$kr/1"; klate="$kr/2"
AGENTMUX_AGENT=worker-c $RUN submit "$kjob" --summary x >/dev/null 2>&1
AGENTMUX_AGENT=rev-c $RUN verdict "$kjob" --pass --reason ok >/dev/null 2>&1
AGENTMUX_AGENT=worker-c $RUN submit "$klate" --summary x >/dev/null 2>&1
$RUN complete "$kr" --force >/dev/null 2>&1
check_rc 'the run completes (forced, one job still open)' 0 "$?"
AGENTMUX_AGENT=rev-c $RUN verdict "$klate" --fail --reason "too late" >/dev/null 2>&1
check_rc 'a verdict on a still-open job after completion is refused' 2 "$?"
AGENTMUX_AGENT=worker-c $RUN submit "$klate" --summary "also too late" >/dev/null 2>&1
check_rc 'a submit after completion is refused' 2 "$?"

echo '--- an oversized event spills to a sidecar rather than tearing the log ---'
# EVENT_MAX was declared as what "keeps one append atomic" and then the oversized line
# was written anyway, so the guarantee the append-only design rests on was a comment.
lr=$($RUN start "overflow" 2>/dev/null)
$RUN assign "$lr" --worker worker-d --reviewer rev-d \
  --brief "$(head -c 4000 /dev/zero | tr '\0' 'b')" >/dev/null 2>&1
AGENTMUX_AGENT=worker-d $RUN submit "$lr/1" \
  --files "$(python3 -c 'print(",".join(f"f{i}.py" for i in range(400)))')" \
  --summary over >/dev/null 2>&1
longest=$(awk '{ if (length($0) > m) m = length($0) } END { print m + 1 }' \
  "$HOME_DIR/runs/$lr/events.jsonl")
if [ "$longest" -le 1024 ]; then
  ok "every event stayed under the atomic cap (longest $longest)"
else
  bad "an event of $longest bytes was written past EVENT_MAX - the append can tear"
fi
if ls "$HOME_DIR/runs/$lr"/event-overflow-*.json >/dev/null 2>&1; then
  ok 'the oversized payload was spilled to a sidecar'
else
  bad 'nothing was spilled; the event was silently truncated instead'
fi

echo '--- assignment and teardown belong to the orchestrator ---'
# All inputs name a valid run and distinct workers/reviewers, so the refusal cannot
# come from a missing run or malformed pairing. Disable the synthetic identity bypass.
guard_run=$(env -u AGENTMUX_AGENT $RUN start 'assignment guard' 2>/dev/null)
out=$(env -u AGENTMUX_TRUST_IDENTITY AGENTMUX_AGENT=untrusted-pane \
  $RUN assign "$guard_run" --worker guarded-worker --reviewer guarded-reviewer 2>&1); rc=$?
guard_count=$($RUN status "$guard_run" --json 2>/dev/null | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["jobs"]))')
if [ "$rc/$guard_count" = 2/0 ] && [ ! -d "$HOME_DIR/runs/$guard_run/jobs" ] && \
   [[ "$out" == *"orchestrator's to call"* ]]; then
  ok 'ownership: a pane cannot assign a job or allocate its directory'
else
  bad "ownership: pane assignment was not refused before allocation (rc=$rc jobs=$guard_count)"
fi

# A positive case alone already passed on the base. Pair acceptance with the
# ownership boundary, so this assertion also fails against the unguarded CLI.
owner_run=$(env -u AGENTMUX_AGENT $RUN start 'orchestrator assignment' 2>/dev/null)
owner_job=$(env -u AGENTMUX_AGENT -u AGENTMUX_TRUST_IDENTITY \
  $RUN assign "$owner_run" --worker owner-worker --reviewer owner-reviewer 2>/dev/null); owner_rc=$?
out=$(env -u AGENTMUX_TRUST_IDENTITY AGENTMUX_AGENT=owner-worker \
  $RUN assign "$owner_run" --worker friendly-worker --reviewer friendly-reviewer 2>&1); pane_rc=$?
owner_count=$($RUN status "$owner_run" --json 2>/dev/null | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["jobs"]))')
if [ "$owner_rc/$pane_rc/$owner_count" = 0/2/1 ] && [ "$owner_job" = "$owner_run/1" ]; then
  ok 'ownership: orchestrator assignment works and a pane cannot add its own pairing'
else
  bad "ownership: assignment boundary failed (orchestrator=$owner_rc pane=$pane_rc jobs=$owner_count)"
fi

# Inspect the actual persisted event AND fold. Include a legacy assignment with no
# worker field, because existing runs (including this job) still use that schema.
attribution=$(python3 - "$owner_run" <<'PYATTR'
import sys
sys.path.insert(0, 'taskmgmt')
import run
run_id = sys.argv[1]
events = run.load_events(run_id)
event = next(e for e in events if e.get('event') == 'assign')
state = run.fold(events)['jobs'][event['job']]
legacy = run.fold([{'event': 'assign', 'job': 'legacy/1', 'by': 'legacy-worker',
                    'reviewer': 'legacy-reviewer'}])['jobs']['legacy/1']
print('/'.join(str(x) for x in (event.get('by'), event.get('worker'), state['worker'],
                                state['reviewer'], legacy['worker'], legacy['reviewer'])))
PYATTR
)
check 'ownership: actor attribution and new/legacy worker folding' \
  'orchestrator/owner-worker/owner-worker/owner-reviewer/legacy-worker/legacy-reviewer' "$attribution"

# Exercise the actual shell entry point against an isolated home. Unique, nonexistent
# session names ensure the broken base cannot kill an operator agent. A sentinel
# sidecar detects whether teardown got past its guard and performed destructive work.
teardown_run=$(env -u AGENTMUX_AGENT $RUN start 'teardown guard' 2>/dev/null)
teardown_worker="ownership-worker-$$"
teardown_reviewer="ownership-reviewer-$$"
env -u AGENTMUX_AGENT $RUN assign "$teardown_run" --worker "$teardown_worker" \
  --reviewer "$teardown_reviewer" >/dev/null 2>&1
mkdir -p "$HOME_DIR/run"
printf 'shell\n' > "$HOME_DIR/run/$teardown_worker.cli"
tr -d '\r' < agentmux.sh > "$HOME_DIR/harness.sh"
out=$(env -u AGENTMUX_TRUST_IDENTITY AGENTMUX_AGENT="$teardown_worker" AGENTMUX_REPO="$PWD" \
  bash "$HOME_DIR/harness.sh" run teardown "$teardown_run" 2>&1); pane_rc=$?
survived=no
[ -f "$HOME_DIR/run/$teardown_worker.cli" ] && survived=yes
# Also prove the guard does not disable legitimate teardown. The synthetic names
# need the normal test-only liveness bypass for coordination, never real sessions.
env -u AGENTMUX_AGENT AGENTMUX_REPO="$PWD" bash "$HOME_DIR/harness.sh" \
  run teardown "$teardown_run" >/dev/null 2>&1; owner_rc=$?
if [ "$pane_rc/$owner_rc/$survived" = 2/0/yes ] && \
   [[ "$out" == *"orchestrator's to call"* ]] && [ ! -f "$HOME_DIR/run/$teardown_worker.cli" ]; then
  ok 'ownership: pane teardown is refused before side effects; orchestrator teardown works'
else
  bad "ownership: teardown boundary failed (pane=$pane_rc orchestrator=$owner_rc sentinel=$survived)"
fi

finish
