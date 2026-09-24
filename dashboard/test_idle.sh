#!/usr/bin/env bash
# The idle-agent timeout. Run from the repo root:
#   bash <(tr -d '\r' < dashboard/test_idle.sh)
#
# WHAT IT GUARDS. An agent nobody is using still holds a CLI process, a provider
# session and - when spawned unrestricted - a shell with the approval bypass off.
# The timeout closes those. The risk is the timeout closing something that IS in
# use, so most of what follows is about the cases where it must keep its hands off:
# an attached session, a session that produced output a minute ago, and a tmux that
# cannot be queried at all.
#
# The selection is tested against a FIXTURE rather than a live tmux server, so it
# runs anywhere and covers boundaries (exactly at the limit, one second under) that
# a real server cannot be posed into.
set -u
[ -f agentmux.sh ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }

passed=0; failed=0
ok()  { passed=$((passed+1)); printf '  ok    %s\n' "$1"; }
bad() { failed=$((failed+1)); printf '  FAIL  %s\n     %s\n' "$1" "${2:-}"; }
check() {
  if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "got '$3' want '$2'"; fi
}

# Load the script's functions without running its dispatch. `return` at the top
# level of a sourced file stops sourcing, which is how the command table at the
# bottom is skipped.
SRC="$(mktemp)"; trap 'rm -f "$SRC"' EXIT
tr -d '\r' < agentmux.sh | sed 's/^case "\${1:-}" in$/return 0 \# test harness stops here/' > "$SRC"
# shellcheck source=/dev/null
AGENTMUX_IDLE_MINUTES=60 . "$SRC" 2>/dev/null || true

if ! declare -f idle_candidates >/dev/null; then
  echo '  FAIL  idle_candidates was not defined by sourcing agentmux.sh' >&2
  exit 1
fi

NOW=1790000000
LIMIT=3600      # 60 minutes

candidates() { printf '%s\n' "$1" | idle_candidates "$LIMIT" "$NOW"; }

echo '--- what gets closed ---'
check "an hour of silence is closed" "old 3600" \
      "$(candidates "old $((NOW - 3600)) 0")"
check "and so is a day of it" "ancient 86400" \
      "$(candidates "ancient $((NOW - 86400)) 0")"

echo '--- what does NOT ---'
check "one second under the limit is left alone" "" \
      "$(candidates "nearly $((NOW - 3599)) 0")"
check "a session busy right now is left alone" "" \
      "$(candidates "busy $NOW 0")"
# The one that matters most: somebody has it on screen. Not having typed for an
# hour is not permission to close their terminal.
check "an ATTACHED session is never closed, however idle" "" \
      "$(candidates "watched $((NOW - 999999)) 1")"
check "nor is an attached session at exactly the limit" "" \
      "$(candidates "watched $((NOW - 3600)) 1")"

echo '--- a mixed board picks out only the idle, detached ones ---'
mixed="$(printf '%s\n' \
  "fresh $NOW 0" \
  "stale $((NOW - 7200)) 0" \
  "watched $((NOW - 7200)) 1" \
  "borderline $((NOW - 3600)) 0")"
check "two of four" "stale 7200
borderline 3600" "$(candidates "$mixed")"

echo '--- malformed input is skipped, never guessed at ---'
for junk in "noactivity" "name notanumber 0" "name 123 notanumber" ""; do
  check "'$junk' yields nothing" "" "$(candidates "$junk")"
done
check "a bad line does not stop the good one after it" "good 7200" \
      "$(candidates "$(printf 'bad line here\ngood %s 0\n' "$((NOW - 7200))")")"

echo '--- the timeout can be turned off, and says so ---'
out="$(AGENTMUX_IDLE_MINUTES=0 IDLE_MINUTES=0 cmd_idle 2>&1)"
check "0 disables it" "idle timeout disabled (AGENTMUX_IDLE_MINUTES=0)" "$out"
out="$(cmd_idle --minutes abc 2>&1)"; rc=$?
check "a non-numeric --minutes is refused" "1" "$rc"
case "$out" in *"whole number"*) ok "and says why" ;; *) bad "and says why" "$out" ;; esac
out="$(cmd_idle --wat 2>&1)"; rc=$?
check "an unknown flag is refused" "1" "$rc"

echo '--- the default is 60 minutes ---'
check "IDLE_MINUTES default" "60" "$(AGENTMUX_IDLE_MINUTES= bash -c '
  eval "$(sed -n "s/^IDLE_MINUTES=.*/&/p" "$1")"; printf "%s" "$IDLE_MINUTES"' _ "$SRC")"
grep -q 'AGENTMUX_IDLE_MINUTES' agentmux.sh \
  && ok "the env var is documented in usage" \
  || bad "the env var is documented in usage"
grep -q 'idle   \[--minutes N\]' agentmux.sh \
  && ok "the verb is in usage" || bad "the verb is in usage"

echo '--- the watchdog can find the script it has to re-run ---'
# THE BUG THIS CAUGHT. agentmux is normally invoked as
#     bash <(tr -d '\r' < agentmux.sh)
# because the working tree is CRLF. Inside that, both $0 and BASH_SOURCE are a
# /dev/fd entry that stops existing the moment the pipeline ends - so the first
# version of the watchdog was written with AGENTMUX_SELF=/dev/fd/agentmux.sh and
# logged "No such file or directory" every tick, forever, closing nothing.
if declare -f agentmux_self >/dev/null; then
  ok "agentmux_self exists"
  found="$(agentmux_self || echo NONE)"
  case "$found" in
    */agentmux.sh) [ -f "$found" ] && ok "it resolves to a real file: $found" \
                                   || bad "it resolves to a real file" "$found" ;;
    *) bad "it resolves to a real file" "$found" ;;
  esac
  case "$found" in
    /dev/fd/*|/proc/self/fd/*) bad "a /dev/fd path is never returned" "$found" ;;
    *) ok "a /dev/fd path is never returned" ;;
  esac
  # AGENTMUX_REPO must be cleared too, or this does not test what it says: it is the
  # FIRST candidate agentmux_self tries, so with it set the function correctly finds
  # the repo from any directory and the assertion fails for the right reason. Run
  # alone this passed by luck; run after any suite that exports it, it went red.
  ( cd / && unset AGENTMUX_REPO && [ -z "$(agentmux_self 2>/dev/null)" ] ) \
    && ok "and it refuses rather than guessing when the repo is nowhere to be found" \
    || bad "and it refuses rather than guessing"
else
  bad "agentmux_self exists" "not defined"
fi
# The generated watchdog must strip CR too, or it cannot run the script it found.
# Fixed-string: the line is full of quotes and backslashes that a regex would only
# obscure. It must pipe the script through `tr` rather than running it directly.
if grep -qF 'tr -d' agentmux.sh && grep -qF '< "$script") idle' agentmux.sh; then
  ok "the watchdog it writes strips CR before running agentmux.sh"
else
  bad "the watchdog it writes strips CR" "a CRLF checkout would make every tick fail"
fi
grep -q 'idle timeout NOT armed' agentmux.sh \
  && ok "and it says so out loud when it cannot arm the timeout" \
  || bad "it says so when it cannot arm the timeout"

echo '--- the watchdog is tied to there being an agent ---'
grep -q 'start_idle_watchdog' agentmux.sh && ok "spawn starts it" || bad "spawn starts it"
grep -c 'stop_idle_watchdog_if_no_agents' agentmux.sh | {
  read -r n
  # Both kill paths plus the definition: a timeout that outlives the last agent is
  # the orphan this repo keeps removing from run/.
  [ "$n" -ge 4 ] && ok "every kill path stops it ($n sites)" \
                 || bad "every kill path stops it" "only $n sites"
}

echo '--- a timeout closes an agent the same way a person does ---'
grep -q 'cmd_kill "\$name"' agentmux.sh \
  && ok "it routes through cmd_kill, so Jira close-out and the sidecar sweep happen" \
  || bad "it routes through cmd_kill"

echo
if [ "$failed" = 0 ]; then echo "passed $passed, failed 0"; else echo "passed $passed, failed $failed"; fi
[ "$failed" = 0 ]
