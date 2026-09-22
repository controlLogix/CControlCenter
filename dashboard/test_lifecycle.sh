#!/usr/bin/env bash
# Agent lifecycle: reap, kill, the close-out marker, and the inbox archive.
#   bash <(tr -d '\r' < dashboard/test_lifecycle.sh)
#
# WHY. Every check here is a TOCTOU or a silent drop on state that is expensive to
# lose, and all four shapes had already been fixed once somewhere else in this repo
# before being found again here:
#
#   #15  reap checks liveness, then makes two Jira/Confluence calls with a 90s ceiling
#        each, then deletes. Agent names are ROLES - claude, rev, codex are respawned
#        constantly - so a respawn inside that three-minute window had its LIVE
#        sidecars deleted.
#   #16  kill, reap and the dashboard reaper all closed the same agent out. Each
#        checked a marker and then wrote it, and both shell paths then deleted the
#        marker microseconds later as part of the sidecar sweep. Result: duplicate
#        close-out comments and duplicate Confluence reports on a real ticket.
#   #20  kill swept the sidecars whether or not kill-session succeeded, leaving a LIVE
#        agent with no .cli, no .task and nothing the dashboard could say about it.
#   #18  inbox --clear os.replace'd onto a fixed .read name, so the second clear
#        destroyed what the first preserved. The comment promised recoverability; it
#        held for exactly one generation, and clearing twice is the normal case.
#
# These use a real tmux session on the agentmux socket, because `have` is the thing
# under test and faking it would test the fake.
set -u
[ -f dashboard/testlib.sh ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }
# shellcheck source=/dev/null
. dashboard/testlib.sh

command -v tmux >/dev/null 2>&1 || { echo 'tmux not found; lifecycle suite needs it' >&2; exit 2; }

HARNESS="$(mktemp)"
tr -d '\r' < agentmux.sh > "$HARNESS"
export AGENTMUX_HOME="$(mktemp -d)"
export AGENTMUX_REPO="$PWD"
export AGENTMUX_NO_COURIER=1
SOCKET="${AGENTMUX_SOCKET:-agentmux}"
RUNDIR="$AGENTMUX_HOME/run"
mkdir -p "$RUNDIR"

# Names are suffixed so a concurrent operator session is never touched.
TAG="lct$$"
cleanup() {
  for n in "$TAG-live" "$TAG-dead" "$TAG-kill"; do
    tmux -L "$SOCKET" kill-session -t "=$n" 2>/dev/null
  done
  rm -rf "$AGENTMUX_HOME" "$HARNESS"
}
trap cleanup EXIT INT TERM

am() { bash "$HARNESS" "$@"; }
sidecars() { ls "$RUNDIR/$1".* 2>/dev/null | wc -l; }
make_sidecars() {
  printf 'shell\n' > "$RUNDIR/$1.cli"
  printf '/tmp\n'  > "$RUNDIR/$1.cwd"
  printf '%s\n' "$2" > "$RUNDIR/$1.started"
}

echo '--- #15: reap must not delete a LIVE agent it is mid-close-out on ---'
tmux -L "$SOCKET" new-session -d -s "$TAG-live" 'sleep 300' 2>/dev/null
make_sidecars "$TAG-live" stamp-1
make_sidecars "$TAG-dead" stamp-1
am reap >/dev/null 2>&1
check "the live agent keeps its sidecars" 3 "$(sidecars "$TAG-live")"
check "the dead agent's sidecars are gone" 0 "$(sidecars "$TAG-dead")"

echo '--- #15: a respawn during close-out is detected by the spawn stamp ---'
# The liveness re-check alone misses an agent that came back and died again inside
# the window. The stamp catches that, so the two together cover the window rather
# than just its common case.
make_sidecars "$TAG-dead" stamp-1
if grep -q 'respawned during close-out' agentmux.sh; then
  ok 'reap re-reads the spawn stamp before deleting'
else
  bad 'no stamp re-check: a fast respawn-and-die still loses its sidecars'
fi
if grep -q 'came back alive during close-out' agentmux.sh; then
  ok 'reap re-checks liveness before deleting'
else
  bad 'no liveness re-check: the original #15'
fi

echo '--- #16: the close-out marker is claimed once, and survives the sweep ---'
# Claimed with noclobber, which is O_EXCL: exactly one of kill/reap/dashboard wins.
claim() { ( . /dev/stdin <<CLAIM
RUNDIR="$RUNDIR"
$(sed -n '/^claim_reported() {/,/^}/p' "$HARNESS")
claim_reported "$1" "$2"
CLAIM
); }
rm -rf "$RUNDIR/reported"
claim "$TAG-dead" first  && ok 'the first close-out claim succeeds' \
                         || bad 'the first claim was refused'
claim "$TAG-dead" second && bad 'a SECOND claim also succeeded - duplicate close-out' \
                         || ok 'the second claim is refused (no duplicate Jira post)'
check 'the winner is recorded' first "$(cat "$RUNDIR/reported/$TAG-dead" 2>/dev/null)"

# 16-way, because a check-then-write looks correct until it is contended. This is the
# assertion that found the two-winner claim bug, pointed at the same shape.
rm -rf "$RUNDIR/reported"
mkdir -p "$RUNDIR/reported"
claim_race() { claim "$TAG-race" "w$$"; }
assert_one_winner 'close-out claim' 16 "$RUNDIR/reported/$TAG-race" claim_race

echo '--- #16: the sweep does not destroy the marker it just wrote ---'
rm -rf "$RUNDIR/reported"; mkdir -p "$RUNDIR/reported"
make_sidecars "$TAG-dead" stamp-2
claim "$TAG-dead" killed-by-cli >/dev/null 2>&1
am reap >/dev/null 2>&1
if [ -f "$RUNDIR/reported/$TAG-dead" ]; then
  ok 'the marker outlives the sidecar sweep'
else
  bad 'the sweep deleted the marker - the dashboard reaper will post a duplicate'
fi
check 'and the sidecars are still swept' 0 "$(sidecars "$TAG-dead")"

echo '--- #20: a FAILED kill must not delete the sidecars ---'
make_sidecars "$TAG-kill" stamp-3
printf '%s\n' "$RUNDIR" >/dev/null
# No session by that name, so kill-session fails. The agent in the real failure mode
# is alive; what matters here is that a failed kill never sweeps.
am kill "$TAG-kill" >/dev/null 2>&1
rc=$?
check_rc 'a kill that could not kill reports failure' 1 "$rc"
check 'and leaves every sidecar in place' 3 "$(sidecars "$TAG-kill")"

echo '--- #18: clearing an inbox twice keeps both generations ---'
mkdir -p "$AGENTMUX_HOME/inbox"
I="$AGENTMUX_HOME/inbox/claude.jsonl"
printf '%s\n' '{"at":"t1","sender":"a","kind":"status","body":"gen-one"}' > "$I"
am inbox claude --clear >/dev/null 2>&1
printf '%s\n' '{"at":"t2","sender":"a","kind":"status","body":"gen-two"}' > "$I"
am inbox claude --clear >/dev/null 2>&1
ARCHIVE="$AGENTMUX_HOME/inbox/claude.jsonl.read"
check 'the first generation survived the second clear' 1 "$(grep -c gen-one "$ARCHIVE" 2>/dev/null || echo 0)"
check 'the second generation is there too'             1 "$(grep -c gen-two "$ARCHIVE" 2>/dev/null || echo 0)"
check 'no staging file was left behind' 0 "$(ls "$AGENTMUX_HOME/inbox/" | grep -c taking || true)"

echo '--- #21: the dashboard reader says when it drops queue records ---'
# The courier logs once per unknown kind; this reader dropped on the same condition
# and said nothing, so the courier DELIVERED a message the dashboard rendered a
# conversation without. Two components disagreeing, with no record of the disagreement.
QUEUE="$AGENTMUX_HOME/queue"; mkdir -p "$QUEUE"
printf '%s\n' '{"at":"2026-09-22T00:00:00Z","sender":"a","recipient":"b","kind":"invented","body":"x"}' \
  > "$QUEUE/a.jsonl"
noise="$(AGENTMUX_HOME="$AGENTMUX_HOME" python3 -c "
import sys; sys.path.insert(0, 'dashboard')
import ccstore
ccstore.queue_messages()
" 2>&1 >/dev/null)"
case "$noise" in
  *"dropping queue records"*) ok 'a dropped record is reported, with its cause' ;;
  *) bad "the drop was silent: [$noise]" ;;
esac
case "$noise" in
  *"invented"*) ok 'and the report names the kind it did not know' ;;
  *) bad 'the report does not say which kind was dropped' ;;
esac

finish
