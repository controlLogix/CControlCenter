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
. dashboard/testlib.sh

HARNESS="$(mktemp)"
tr -d '\r' < agentmux.sh > "$HARNESS"
export AGENTMUX_HOME="$(mktemp -d)"
export AGENTMUX_REPO="$PWD"
export AGENTMUX_NO_COURIER=1
trap 'rm -rf "$AGENTMUX_HOME" "$HARNESS"' EXIT

am() { bash "$HARNESS" "$@" >/dev/null 2>&1; }
am_out() { bash "$HARNESS" "$@" 2>&1; }
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

echo '--- key: a typo is still refused, and a numbered menu can still be answered ---'
# `key` rejects anything that is not recognisably a tmux key name, because tmux
# treats an unknown NAME as literal text and exits 0 - so `key rev Dowm Enter` would
# type the word "Dowm" at the agent and submit it. That guard has to stay.
refuses key "$TARGET" Dowm
refuses key "$TARGET" Entr
refuses key "$TARGET" "Down Enter"
refuses key "$TARGET" ""
# But it also has to be able to answer the modal it EXISTS for. Every fresh codex
# pane opens on a numbered menu whose first option runs `npm install -g`:
#     1. Update now   <- preselected
#     2. Skip
# and the documented answer is `key`, precisely so nothing appends Enter and
# actuates the highlight. `key <pane> 2` was refused as "not a recognised tmux key
# name", which left the modal unanswerable - `send` would type 2 AND Enter. Four
# panes sat on it. A single character cannot be a mistyped key name, because every
# name is two characters or more, so exactly one printable character is allowed.
for single in 2 y n q 3; do
  am key "$TARGET" "$single"
  check_rc "key answers a numbered menu: $single" 0 "$?"
done

echo '--- the team verbs are reachable through agentmux, not only through python ---'
# roster, recruit, approve, retire and hire lived in coordination.py and were wired
# into nothing, so `agentmux recruit TM-100` answered "unknown command" and staffing a
# card meant invoking python3 by hand. That is the same gap cmd_task was written to
# close - "reachable only by invoking python3 by hand ... the same reason the board
# went unused before `agentmux tasks` existed" - and every document that said
# `agentmux recruit` was wrong. A refusal FROM the board is the proof: it means the
# verb was dispatched and reached it.
for verb in roster recruit approve retire hire; do
  out="$(am_out "$verb" NOT-A-KEY 2>&1)"
  case "$out" in
    *"unknown command"*) bad "agentmux $verb reaches the board (got: unknown command)" ;;
    *) ok "agentmux $verb reaches the board" ;;
  esac
done
# Identity stays un-spoofable on the three that sign a decision.
refuses 'approve --agent is refused' approve TM-1 --member x --agent someone-else
refuses 'recruit --agent is refused' recruit TM-1 --agent someone-else
refuses 'retire  --agent is refused' retire TM-1 --member x --agent someone-else

echo '--- identity flags cannot be overridden from the command line ---'

# `claim x --holder victim` used to claim in someone else's name, which made the
# comment two lines above it ("cannot claim on someone else's behalf") false.
AGENTMUX_AGENT=attacker am claim res-1 --holder victim
check_rc 'claim --holder is refused' 1 "$?"
AGENTMUX_AGENT=attacker am release res-1 --holder victim
check_rc 'release --holder is refused' 1 "$?"

# THE THIRD APPEARANCE OF THE SAME BUG. --agent and --holder are refused above; --by
# was not, and cmd_run's verbs disagreed with each other by accident of argument
# order - verdict put the wrapper's --by last and won, submit put the caller's args
# last and lost. Measured before the fix: as `orchestrator`,
# `agentmux run submit <job> --by dev` wrote a submit event recorded by "dev".
# "A worker cannot mark its own homework" is checked against `by`, so a `by` the
# caller sets is that mechanism with its one input handed to the person it binds.
for verb in start submit verdict complete; do
  AGENTMUX_AGENT=attacker am run "$verb" X --by victim
  check_rc "run $verb --by is refused" 1 "$?"
done

finish
