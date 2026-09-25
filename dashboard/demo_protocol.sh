#!/usr/bin/env bash
# Every guard in the run protocol and the coordination layer, exercised in one pass.
#   bash <(tr -d '\r' < dashboard/demo_protocol.sh)
#
# This is a DEMONSTRATION, not a test suite - the suites already cover this ground and
# run in CI order. What this adds is a single readable transcript of who is allowed to
# do what, because the answer is currently spread across run.py, coordination.py and
# agentmux.sh and nobody should have to read three files to find out.
#
# Everything here runs against a THROWAWAY AGENTMUX_HOME. It never writes to the
# operator's state, never kills a live agent, and only ever exercises the REFUSAL side
# of teardown - the one verb whose success path would end other people's work.
set -u
[ -f dashboard/testlib.sh ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }
# shellcheck source=/dev/null
. <(tr -d '\r' < dashboard/testlib.sh)   # tr: testlib may arrive CRLF; bash cannot source that

HARNESS="$(mktemp)"
tr -d '\r' < agentmux.sh > "$HARNESS"
export AGENTMUX_HOME="$(mktemp -d)"
export AGENTMUX_REPO="$PWD"
export AGENTMUX_NO_COURIER=1
trap 'rm -rf "$AGENTMUX_HOME" "$HARNESS"' EXIT

RUN="python3 taskmgmt/run.py"
CO="python3 taskmgmt/coordination.py"

# The suites run without tmux, so identities cannot be checked for liveness there.
# This demo runs with the real tmux server up, so it does NOT set that bypass except
# where a section is explicitly about the bypass itself.
LIVE="$(tmux -L "${AGENTMUX_SOCKET:-agentmux}" list-sessions -F '#{session_name}' 2>/dev/null | tr '\n' ' ')"
echo "live agents: ${LIVE:-(none)}"
echo "throwaway home: $AGENTMUX_HOME"
echo

WORKER="${DEMO_WORKER:-codex}"
REVIEWER="${DEMO_REVIEWER:-claude}"
case " $LIVE " in
  *" $WORKER "*) ;;
  *) echo "NOTE: $WORKER is not live; liveness assertions will be skipped" >&2 ;;
esac

# ── 1. only the orchestrator opens and closes a run ──────────────────────────

echo '--- 1. the orchestrator owns start, assign, complete and teardown ---'
R=$($RUN start "demo run" 2>/dev/null)
if printf '%s' "$R" | grep -Eq '^[0-9a-f]{6}$'; then
  ok "orchestrator opens a run ($R)"
else
  bad "start failed: $R"; finish
fi

AGENTMUX_AGENT="$WORKER" $RUN start "an agent opening its own run" >/dev/null 2>&1
check_rc 'an agent CANNOT open a run' 2 "$?"

AGENTMUX_AGENT="$WORKER" $RUN assign "$R" --worker "$WORKER" --reviewer "$REVIEWER" >/dev/null 2>&1
check_rc 'an agent CANNOT assign' 2 "$?"
check 'and no job id was allocated by the refusal' 0 "$(ls "$AGENTMUX_HOME/runs/$R/jobs" 2>/dev/null | wc -l)"

J=$($RUN assign "$R" --worker "$WORKER" --reviewer "$REVIEWER" --brief 'demo' 2>/dev/null)
check 'orchestrator assigns' "$R/1" "$J"

$RUN assign "$R" --worker "$WORKER" --reviewer "$WORKER" >/dev/null 2>&1
check_rc 'the reviewer CANNOT be the worker' 2 "$?"

AGENTMUX_AGENT="$WORKER" bash "$HARNESS" run teardown "$R" >/dev/null 2>&1
check_rc 'an agent CANNOT tear down a run' 2 "$?"
check 'and every live agent is still running' "$LIVE" \
  "$(tmux -L "${AGENTMUX_SOCKET:-agentmux}" list-sessions -F '#{session_name}' 2>/dev/null | tr '\n' ' ')"

# ── 2. identity is resolved, not accepted ────────────────────────────────────

echo '--- 2. a pane cannot be anyone but itself ---'
AGENTMUX_AGENT="$WORKER" $RUN submit "$J" --by someone-else >/dev/null 2>&1
check_rc "--by that disagrees with the pane is refused" 2 "$?"

AGENTMUX_AGENT="$REVIEWER" $RUN submit "$J" --by "$WORKER" --summary x >/dev/null 2>&1
check_rc "the reviewer's pane cannot submit as the worker" 2 "$?"

AGENTMUX_AGENT=ghost-agent $RUN submit "$J" --summary x >/dev/null 2>&1
check_rc 'an identity that is not a live session is refused' 2 "$?"

$RUN complete "$R" --by "$REVIEWER" >/dev/null 2>&1
check_rc 'complete cannot be attributed to anyone but the orchestrator' 2 "$?"

echo '--- 2b. and the Python CLI enforces it too, not just the shell wrapper ---'
# Before b64cef1 these four walked straight past the guard `agentmux claim` provided.
for verb in "claim demo/x --holder victim" "release demo/x --holder victim" \
            "journal note demo --agent victim" "task-status 1 done --agent victim"; do
  # The label is computed BEFORE the command runs. Putting a $(...) in the check_rc
  # argument list instead made bash evaluate the substitution first, which reset $?
  # to the substitution's status - so four refused forgeries were reported as
  # accepted. A demo that lies about the thing it exists to demonstrate.
  label="direct CLI: ${verb%% *} forgery refused"
  # shellcheck disable=SC2086
  AGENTMUX_AGENT="$WORKER" $CO $verb >/dev/null 2>&1
  rc=$?
  check_rc "$label" 2 "$rc"
done
bash "$HARNESS" claim demo/y --holder victim >/dev/null 2>&1
check_rc 'shell wrapper: --holder override refused' 1 "$?"
bash "$HARNESS" claim demo/y --holder=victim >/dev/null 2>&1
check_rc 'shell wrapper: --holder=victim refused too' 1 "$?"

echo '--- 2c. the orchestrator is still allowed to be the orchestrator ---'
bash "$HARNESS" claim demo/z --note 'orchestrator smoke' >/dev/null 2>&1
check_rc 'orchestrator claims with no $AGENTMUX_AGENT set' 0 "$?"
bash "$HARNESS" release demo/z >/dev/null 2>&1
check_rc 'and releases' 0 "$?"

# ── 3. a claim has exactly one winner ────────────────────────────────────────

echo '--- 3. a claim is a mechanism, not a courtesy ---'
AGENTMUX_AGENT="$WORKER" bash "$HARNESS" claim src/shared.py --note 'demo' >/dev/null 2>&1
check_rc "$WORKER takes an unheld resource" 0 "$?"
out="$(AGENTMUX_AGENT="$REVIEWER" bash "$HARNESS" claim src/shared.py 2>&1)"
check_rc "$REVIEWER is refused the same resource" 1 "$?"
case "$out" in
  *"$WORKER"*) ok 'and the refusal names who holds it' ;;
  *) bad "the refusal does not name the holder: $out" ;;
esac
AGENTMUX_AGENT="$REVIEWER" bash "$HARNESS" release src/shared.py >/dev/null 2>&1
check_rc "$REVIEWER cannot release someone else's claim" 1 "$?"
AGENTMUX_AGENT="$WORKER" bash "$HARNESS" release src/shared.py >/dev/null 2>&1
check_rc 'the holder can' 0 "$?"

# ── 4. the review gate ───────────────────────────────────────────────────────

echo '--- 4. work is verified by someone who did not do it ---'
AGENTMUX_AGENT="$WORKER" $RUN submit "$J" --summary 'demo submission' >/dev/null 2>&1
check_rc 'the worker submits' 0 "$?"

AGENTMUX_AGENT="$WORKER" $RUN verdict "$J" --pass --reason 'looks good to me' >/dev/null 2>&1
check_rc 'the worker CANNOT sign off its own work' 2 "$?"

AGENTMUX_AGENT=grok $RUN verdict "$J" --pass --reason 'not my job' >/dev/null 2>&1
check_rc 'nor can an agent who is not the assigned reviewer' 2 "$?"

$RUN complete "$R" >/dev/null 2>&1
check_rc 'THE GATE: complete is refused while a job is unverified' 1 "$?"

AGENTMUX_AGENT="$REVIEWER" $RUN verdict "$J" --fail --reason 'first draft is incomplete' >/dev/null 2>&1
check_rc 'the reviewer rejects it' 0 "$?"
# grep -F "$J" matches the job's row AND the "BLOCKING completion:" line that lists
# it, so the field came back as two lines. Anchor on the row.
job_state() { $RUN status "$1" 2>/dev/null | awk -v j="$2" '$1 == j {print $2}'; }
check 'the job is back with the worker' rejected "$(job_state "$R" "$J")"

AGENTMUX_AGENT="$WORKER" $RUN submit "$J" --summary 'second attempt' >/dev/null 2>&1
AGENTMUX_AGENT="$REVIEWER" $RUN verdict "$J" --pass --reason 'addressed' >/dev/null 2>&1
check 'and on the second attempt it verifies' verified "$(job_state "$R" "$J")"

$RUN complete "$R" >/dev/null 2>&1
check_rc 'the gate opens once every job is verified' 0 "$?"

echo '--- 4b. a completed run is closed ---'
AGENTMUX_AGENT="$REVIEWER" $RUN verdict "$J" --fail --reason 'too late' >/dev/null 2>&1
check_rc 'a verdict after completion is refused' 2 "$?"
AGENTMUX_AGENT="$WORKER" $RUN submit "$J" --summary 'also too late' >/dev/null 2>&1
check_rc 'a submit after completion is refused' 2 "$?"
$RUN complete "$R" >/dev/null 2>&1
check_rc 'and completion cannot fire twice' 1 "$?"

# ── 5. three strikes ─────────────────────────────────────────────────────────

echo '--- 5. three failed reviews escalate, and still block the gate ---'
R2=$($RUN start "escalation demo" 2>/dev/null)
J2=$($RUN assign "$R2" --worker "$WORKER" --reviewer "$REVIEWER" 2>/dev/null)
for attempt in 1 2 3; do
  AGENTMUX_AGENT="$WORKER"   $RUN submit  "$J2" --summary "attempt $attempt" >/dev/null 2>&1
  AGENTMUX_AGENT="$REVIEWER" $RUN verdict "$J2" --fail --reason "rejection $attempt" >/dev/null 2>&1
done
check 'the third rejection escalates' escalated "$(job_state "$R2" "$J2")"
$RUN complete "$R2" >/dev/null 2>&1
check_rc 'an escalated job still blocks completion' 1 "$?"
$RUN complete "$R2" --force >/dev/null 2>&1
check_rc '--force overrides it' 0 "$?"
if [ -f "$AGENTMUX_HOME/runs/$R2/FORCED.md" ]; then
  ok 'and records what was left unfinished, before any teardown'
else
  bad 'a forced completion left no record of what was unfinished'
fi

echo
echo "nothing above touched the operator's state; home was $AGENTMUX_HOME"
finish
