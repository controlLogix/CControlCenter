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

echo '--- every component uses the selected AGENTMUX_HOME ---'
# Extract only the production helpers, with their actual ROOT expression; do not
# source the harness dispatch, spawn anything, or override the operator's HOME.
PATH_HELPERS="$AGENTMUX_HOME/path-helpers.sh"
{
  sed -n '/^ROOT=/p' "$HARNESS"
  sed -n '/^auth_default_for() {/,/^}/p' "$HARNESS"
  sed -n '/^auth_resolve() {/,/^}/p' "$HARNESS"
  sed -n '/^task_cli() {/,/^}/p' "$HARNESS"
} > "$PATH_HELPERS"
PATH_HOME="$AGENTMUX_HOME/selected home"
mkdir -p "$PATH_HOME"
printf '{"active":{"codex":"isolated-%s"}}\n' "$TAG" > "$PATH_HOME/auth.json"
default=$(AGENTMUX_HOME="$PATH_HOME" bash -c '. "$1"; auth_default_for codex' _ "$PATH_HELPERS")
if [ "$default" = "isolated-$TAG" ]; then
  ok 'home: auth_default_for reads the selected auth.json'
else
  bad 'home: auth_default_for read another home or lost the configured default'
fi

# A minimal manifest requires both settings and a secret NAME in the selected home.
# None of the data is real credentials; the production helper only emits settings.
mkdir -p "$PATH_HOME/repo/dashboard"
cat > "$PATH_HOME/repo/dashboard/auth.json" <<'JSON'
{"providers":[{"id":"home-test","settings":[{"key":"region"}],"secrets":["HOME_TEST_KEY"]}],"methods":[{"id":"home-test","cli":"codex","provider":"home-test","settings":[{"key":"model"}],"env_from_provider":{"HOME_TEST_REGION":"region"},"env_from_method":{"HOME_TEST_MODEL":"model"}}]}
JSON
printf '%s\n' '{"providers":{"home-test":{"region":"isolated-region"}},"methods":{"home-test":{"model":"isolated-model"}}}' > "$PATH_HOME/auth.json"
printf '%s\n' 'export HOME_TEST_KEY=fixture-only' > "$PATH_HOME/env"
resolved=$(AGENTMUX_HOME="$PATH_HOME" AGENTMUX_REPO="$PATH_HOME/repo" bash -c '. "$1"; auth_resolve home-test codex' _ "$PATH_HELPERS" 2>/dev/null); rc=$?
if [ "$rc" = 0 ] && [[ "$resolved" == *'HOME_TEST_REGION=isolated-region;'*'HOME_TEST_MODEL=isolated-model;'* ]]; then
  ok 'home: auth_resolve reads settings and secret names from the selected home'
else
  bad "home: auth_resolve ignored the selected configuration (rc=$rc)"
fi

# Exercise both directions, so this discriminates whether or not the operator has
# a real atlassian.json. A config in another home must not enable the task hooks.
printf '# fixture CLI\n' > "$PATH_HOME/task.py"
printf '{}\n' > "$PATH_HOME/atlassian.json"
selected_cli=$(AGENTMUX_HOME="$PATH_HOME" AGENTMUX_TASK_CLI="$PATH_HOME/task.py" bash -c '. "$1"; task_cli' _ "$PATH_HELPERS"); present_rc=$?
rm "$PATH_HOME/atlassian.json"
AGENTMUX_HOME="$PATH_HOME" AGENTMUX_TASK_CLI="$PATH_HOME/task.py" bash -c '. "$1"; task_cli' _ "$PATH_HELPERS" >/dev/null; absent_rc=$?
if [ "$present_rc/$absent_rc" = 0/1 ] && [ "$selected_cli" = "$PATH_HOME/task.py" ]; then
  ok 'home: task_cli requires atlassian.json in the selected home only'
else
  bad "home: task_cli used another home (present=$present_rc absent=$absent_rc)"
fi

# Execute just ROOT and the --fresh-db branch, never pgrep/kill/nohup/curl.
# The rm shim maps any attempted deletion in the REAL default directory to a
# disposable mirror. Even the broken base cannot delete the operator's files.
# Its selected-home files remain, and its default-home mirror is destroyed, so
# each assertion below fails on the original destructive path.
RESTART_PATHS="$AGENTMUX_HOME/restart-paths.sh"
tr -d '\r' < dashboard/restart.sh | sed -n '/^ROOT=/p; /^if .*--fresh-db/,/^fi$/p' > "$RESTART_PATHS"
OPERATOR_MIRROR="$AGENTMUX_HOME/operator-mirror"
mkdir -p "$OPERATOR_MIRROR"
for file in cc.db cc.db-wal cc.db-shm; do
  printf 'selected %s\n' "$file" > "$PATH_HOME/$file"
  printf 'operator %s\n' "$file" > "$OPERATOR_MIRROR/$file"
done
export PATH_HOME OPERATOR_MIRROR
# Also verify the actual operator database is unchanged; it is only ever read.
real_db_before=$(sha256sum "$HOME/.agentmux/cc.db" 2>/dev/null || printf 'ABSENT')
AGENTMUX_HOME="$PATH_HOME" bash -s -- "$RESTART_PATHS" <<'RESTART' >/dev/null
set -eu
rm() {
  local arg
  for arg in "$@"; do
    case "$arg" in
      -f) ;;
      "$HOME/.agentmux/"*) command rm -f "$OPERATOR_MIRROR/${arg##*/}" ;;
      "$PATH_HOME/"*) command rm -f "$arg" ;;
      *) echo "unexpected deletion target: $arg" >&2; return 1 ;;
    esac
  done
}
script="$1"
set -- --fresh-db
. "$script"
RESTART
restart_rc=$?
real_db_after=$(sha256sum "$HOME/.agentmux/cc.db" 2>/dev/null || printf 'ABSENT')
for file in cc.db cc.db-wal cc.db-shm; do
  if [ "$restart_rc" = 0 ] && [ "$real_db_before" = "$real_db_after" ] && \
     [ ! -e "$PATH_HOME/$file" ] && \
     cmp -s "$OPERATOR_MIRROR/$file" <(printf 'operator %s\n' "$file"); then
    ok "home: fresh-db removes selected $file and preserves default-home bytes"
  else
    bad "home: fresh-db targeted the wrong $file (or the deletion block failed)"
  fi
done

finish
