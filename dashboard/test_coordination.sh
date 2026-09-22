#!/usr/bin/env bash
# Verify work claims, leases, dependencies and the journal.
#   bash <(tr -d '\r' < dashboard/test_coordination.sh)
#
# Runs against a throwaway AGENTMUX_HOME. No tmux and no agents are required: the
# broadcast half is best-effort by design, and the part that must be correct - the
# mutual exclusion - is a file created with O_EXCL and is testable on its own.
#
# WHAT THIS PROTECTS. Three agents with unrestricted permissions on one repo will edit
# the same file given the chance. A message asking them not to is not a mechanism; the
# other agent may not be reading. These checks pin the part that does not depend on
# anyone cooperating.
set -u
[ -f taskmgmt/coordination.py ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }

HOME_DIR="$(mktemp -d)"
trap 'rm -rf "$HOME_DIR"' EXIT
export AGENTMUX_HOME="$HOME_DIR"
export AGENTMUX_DASHBOARD="http://127.0.0.1:1"     # unreachable on purpose
CO="python3 taskmgmt/coordination.py"

pass=0; fail=0
ok()  { printf '  ok    %s\n' "$1"; pass=$((pass + 1)); }
bad() { printf '  FAIL  %s\n' "$1"; fail=$((fail + 1)); }
check_rc() { # check_rc <label> <expected-rc> <actual-rc>
  if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (rc $3, wanted $2)"; fi
}

echo '--- a claim is exclusive ---'
$CO claim src/app.py --holder alice --note 'refactor' >/dev/null 2>&1
check_rc 'alice takes an unheld resource' 0 $?
out="$($CO claim src/app.py --holder bob 2>&1)"; rc=$?
check_rc 'bob is refused the same resource' 1 "$rc"
case "$out" in
  *alice*) ok 'the refusal names the holder' ;;
  *) bad "refusal did not name the holder: $out" ;;
esac
case "$out" in
  *'agentmux post alice'*) ok 'and tells bob how to reach them' ;;
  *) bad 'refusal did not suggest contacting the holder' ;;
esac

echo '--- re-claiming your own is a renewal, not a conflict ---'
$CO claim src/app.py --holder alice >/dev/null 2>&1
check_rc 'alice renews her own claim' 0 $?

echo '--- release ---'
$CO release src/app.py --holder bob >/dev/null 2>&1
check_rc 'bob cannot release what he does not hold' 1 $?
$CO release src/app.py --holder alice >/dev/null 2>&1
check_rc 'alice releases her own' 0 $?
$CO claim src/app.py --holder bob >/dev/null 2>&1
check_rc 'bob can now take it' 0 $?
$CO release src/app.py --holder alice --force >/dev/null 2>&1
check_rc '--force releases someone else (deliberate override)' 0 $?

echo '--- a lease expires, so a dead agent does not hold work forever ---'
$CO claim src/stale.py --holder ghost --ttl 60 >/dev/null 2>&1
python3 - <<'PY'
import json, os, pathlib, time
d = pathlib.Path(os.environ["AGENTMUX_HOME"]) / "claims"
p = d / "src%2Fstale.py.json"
c = json.loads(p.read_text())
c["expires_at"] = time.time() - 1          # pretend the lease ran out
p.write_text(json.dumps(c))
PY
$CO claim src/stale.py --holder alice >/dev/null 2>&1
check_rc 'an expired claim can be taken by someone else' 0 $?
if $CO claims 2>/dev/null | grep -q alice; then
  ok 'and the new holder is recorded'
else
  bad 'new holder not recorded'
fi

echo '--- listing ---'
$CO claim api/routes.py --holder bob --task CCC-42 --note 'adding auth' >/dev/null 2>&1
listing="$($CO claims 2>&1)"
case "$listing" in *api/routes.py*) ok 'claims lists the resource' ;; *) bad 'resource missing' ;; esac
case "$listing" in *bob*)           ok 'claims lists the holder' ;;   *) bad 'holder missing' ;; esac
case "$listing" in *CCC-42*)        ok 'claims lists the bound task' ;; *) bad 'task missing' ;; esac
if $CO claims --json 2>/dev/null | python3 -c 'import json,sys; sys.exit(0 if isinstance(json.load(sys.stdin), list) else 1)'; then
  ok '--json emits a parseable array'
else
  bad '--json did not parse'
fi

echo '--- dependencies are recorded and surfaced ---'
$CO claim web/ui.js --holder alice --depends-on api/routes.py >/dev/null 2>&1
check_rc 'a claim can declare a dependency' 0 $?
if $CO claims 2>/dev/null | grep -q 'depends on: api/routes.py'; then
  ok 'the dependency is shown in the listing'
else
  bad 'dependency not shown'
fi
out="$($CO claim web/other.js --holder alice --depends-on api/routes.py 2>&1)"
case "$out" in
  *'held by bob'*) ok 'and warns when a dependency is held by someone else' ;;
  *) bad "no warning about the held dependency: $out" ;;
esac

echo '--- traversal and bad input are refused ---'
for res in '../../etc/passwd' 'a/../../b'; do
  $CO claim "$res" --holder alice >/dev/null 2>&1
  check_rc "refuses resource '$res'" 2 $?
done
$CO claim ok.py --holder 'not a name' >/dev/null 2>&1
check_rc 'refuses an invalid holder' 2 $?
if find "$HOME_DIR/claims" -name '*.json' | grep -q 'passwd'; then
  bad 'a traversing claim created a file'
else
  ok 'no claim file escaped the claims directory'
fi

echo '--- the journal still records when the dashboard is down ---'
out="$($CO journal note 'starting the mqtt refactor' --agent alice 2>&1)"
check_rc 'journal accepts a valid kind' 0 $?
case "$out" in
  *'local file'*) ok 'falls back to a local file rather than losing the entry' ;;
  *) bad "no fallback: $out" ;;
esac
if grep -q 'mqtt refactor' "$HOME_DIR/journal.jsonl" 2>/dev/null; then
  ok 'the entry is on disk'
else
  bad 'entry not written'
fi
$CO journal bogus 'x' >/dev/null 2>&1
check_rc 'an unknown journal kind is refused' 2 $?

echo '--- a claim is journalled and queued, so it is visible, not just enforced ---'
if grep -q 'claimed' "$HOME_DIR/journal.jsonl" 2>/dev/null; then
  ok 'claims write a journal entry'
else
  bad 'claim was not journalled'
fi

echo '--- the task board degrades honestly when the dashboard is down ---'
# AGENTMUX_DASHBOARD points at a closed port for this whole suite, which is the
# interesting case: an agent told to use the board must be told clearly when it
# cannot, not fail with a stack trace or - worse - appear to succeed.
out="$($CO tasks 2>&1)"; rc=$?
check_rc 'tasks exits non-zero when the board is unreachable' 1 "$rc"
case "$out" in
  *unreachable*) ok 'and says the dashboard is unreachable' ;;
  *) bad "unhelpful error: $out" ;;
esac
case "$out" in
  *'dashboard/server.py'*) ok 'and says how to start it' ;;
  *) bad 'no remedy offered' ;;
esac
$CO task-status 1 in_progress >/dev/null 2>&1
check_rc 'a status change fails cleanly too' 1 $?
$CO task-status 1 bogus >/dev/null 2>&1
check_rc 'an invalid status is rejected before any request' 2 $?

echo '--- THE RACE: many agents, one resource, simultaneously ---'
# The sequential checks above prove the logic. This proves the mechanism: twelve
# processes going for the same claim at once. Exactly one must win. If O_EXCL were
# ever replaced with a read-then-write, this is the only check that would notice.
rm -rf "$HOME_DIR/claims"
winners="$HOME_DIR/winners"
: > "$winners"
for i in $(seq 1 12); do
  (
    if $CO claim contended/file.py --holder "racer$i" >/dev/null 2>&1; then
      echo "racer$i" >> "$winners"
    fi
  ) &
done
wait
count="$(wc -l < "$winners")"
if [ "$count" -eq 1 ]; then
  ok "exactly one of 12 concurrent claimants won ($(cat "$winners"))"
else
  bad "$count winners out of 12 - mutual exclusion is broken"
fi
held="$($CO claims --json 2>/dev/null | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
if [ "$held" = "1" ]; then
  ok 'and exactly one claim file exists'
else
  bad "$held claim files after the race"
fi
if [ "$(cat "$winners")" = "$($CO claims --json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["holder"])')" ]; then
  ok 'the recorded holder is the process that was told it won'
else
  bad 'the winner and the recorded holder disagree'
fi

echo
echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ] || exit 1
