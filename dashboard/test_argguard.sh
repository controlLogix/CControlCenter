#!/usr/bin/env bash
# Every subcommand must REFUSE an unknown flag, never swallow it.
#   bash <(tr -d '\r' < dashboard/test_argguard.sh)
#
# WHY. `cmd_ask` used to append unrecognised tokens to the prompt, so
# `ask rev --lines 20 "check this"` typed "--lines 20 check this" AT the agent.
# That was fixed; five sibling commands had the same loop and were not. The two
# shapes both cost real money:
#
#   post rev --knid request "x"  -> body becomes "--knid request x", which the
#                                   courier TYPES INTO A PANE and Enters, persists
#                                   to queue/*.jsonl, and the dashboard renders as
#                                   that agent's own words.
#   tail rev --line 20           -> both tokens dropped, so the caller who asked for
#                                   20 lines gets the 200-line default: thousands of
#                                   tokens of redraw noise, which is the entire thing
#                                   --lines exists to prevent.
#   wait rev --timout 30         -> blocks for the default timeout, not the 30s asked.
#   inbox --clear claude         -> name parsed as "--clear", rewritten to
#                                   "orchestrator", so the operator DESTRUCTIVELY
#                                   cleared the wrong inbox and claude's messages
#                                   stayed unread.
#
# A refused flag is a typo. A swallowed one is corrupt data with a plausible receipt.
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

am() { bash "$HARNESS" "$@" >/dev/null 2>&1; }
refuses() { am "$@"; check_rc "refuses: agentmux $*" 1 "$?"; }

mkdir -p "$AGENTMUX_HOME/inbox"

# A LIVE session, because most of these commands call `need <name>` before they parse
# anything. Without it they exit 1 for "no such agent" and the suite goes green having
# never reached the arg loop - which is exactly what a differential run against the
# pre-fix code revealed. Named off $$ so a real agent is never touched.
SOCKET="${AGENTMUX_SOCKET:-agentmux}"
TARGET="argg$$"
if command -v tmux >/dev/null 2>&1 && tmux -L "$SOCKET" new-session -d -s "$TARGET" 'sleep 120' 2>/dev/null; then
  mkdir -p "$AGENTMUX_HOME/run"
  printf 'shell\n' > "$AGENTMUX_HOME/run/$TARGET.cli"
  # `tail` reads a log file and dies when there is none - AFTER parsing, but the
  # die still lands first for a name with no log, so the flag check would go green
  # on "no log for X" without the arg loop ever being reached.
  mkdir -p "$AGENTMUX_HOME/logs"
  printf 'scrollback\\n' > "$AGENTMUX_HOME/logs/$TARGET.log"
  trap 'tmux -L "$SOCKET" kill-session -t "=$TARGET" 2>/dev/null; rm -rf "$AGENTMUX_HOME" "$HARNESS"' EXIT
else
  echo 'WARNING: no tmux; flag checks would pass on "no such agent" instead' >&2
  TARGET="rev"
fi

echo '--- unknown flags are refused, not swallowed ---'
# --lines is a REAL ask flag, so a typo of it is the honest test; passing the
# valid one would have asserted that a working option fails.
refuses ask      "$TARGET" --linez 20 hello
refuses post     "$TARGET" --knid request hello
refuses exec     "$TARGET" --kidn hello
refuses read     "$TARGET" --line 20
refuses tail     "$TARGET" --line 20
refuses wait     "$TARGET" --timout 30
refuses inbox    claude --clera

echo '--- a body that legitimately starts with a dash still gets through ---'
# The escape hatch has to work, or the guard just breaks a real use.
am post "$TARGET" -- --not-a-flag-but-a-body
check_rc 'post -- --looks-like-a-flag is accepted' 0 "$?"

echo '--- inbox: the flag is positional-independent, and hits the right file ---'
# `inbox --clear claude` used to clear the ORCHESTRATOR's inbox instead. That is a
# destructive operation aimed at the wrong target, reported as success.
echo '{"from":"x","kind":"status","body":"claude msg"}'  > "$AGENTMUX_HOME/inbox/claude.jsonl"
echo '{"from":"y","kind":"status","body":"orch msg"}'    > "$AGENTMUX_HOME/inbox/orchestrator.jsonl"
am inbox --clear claude
check_rc 'inbox --clear claude succeeds' 0 "$?"
if [ -f "$AGENTMUX_HOME/inbox/claude.jsonl" ]; then
  bad 'inbox --clear claude did NOT clear claude'
else
  ok 'inbox --clear claude cleared claude'
fi
if [ -f "$AGENTMUX_HOME/inbox/orchestrator.jsonl" ]; then
  ok "the orchestrator's inbox was left alone"
else
  bad "the orchestrator's inbox was cleared as collateral - the original bug"
fi
if [ -f "$AGENTMUX_HOME/inbox/claude.jsonl.read" ]; then
  ok 'the cleared messages are still recoverable from the snapshot'
else
  bad 'a destructive clear left nothing behind'
fi

echo '--- inbox: reading is still non-destructive and still defaults ---'
echo '{"from":"y","kind":"status","body":"orch msg"}' > "$AGENTMUX_HOME/inbox/orchestrator.jsonl"
out="$(bash "$HARNESS" inbox 2>&1)"
case "$out" in *'orch msg'*) ok 'bare `inbox` reads the orchestrator inbox' ;;
                *) bad "bare inbox printed no message: $out" ;; esac
if [ -f "$AGENTMUX_HOME/inbox/orchestrator.jsonl" ]; then
  ok 'a read without --clear leaves the inbox in place'
else
  bad 'a plain read destroyed the inbox'
fi
am inbox a b
check_rc 'two names are refused rather than one silently ignored' 1 "$?"

echo '--- identity flags cannot be overridden from the command line ---'
# `claim x --holder victim` used to claim in someone else's name, which made the
# comment two lines above it ("cannot claim on someone else's behalf") false.
AGENTMUX_AGENT=attacker am claim res-1 --holder victim
check_rc 'claim --holder is refused' 1 "$?"
AGENTMUX_AGENT=attacker am release res-1 --holder victim
check_rc 'release --holder is refused' 1 "$?"

finish
