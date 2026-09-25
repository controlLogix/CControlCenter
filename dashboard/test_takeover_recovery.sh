#!/usr/bin/env bash
# The dashboard takeover marker, and the repair that finishes what a killed gate could not.
#
# WHAT WENT WRONG. run_tests.sh repoints the operator's dashboard at a disposable home
# for the length of a gate run and restores it from an EXIT trap. The trap is careful -
# it verifies the restore with `suite_server.py --expect` rather than assuming it - but a
# trap cannot survive SIGKILL, and the idle watchdog kills panes after 60 minutes without
# pane output, which a long gate run produces none of.
#
# When that happened, OPERATOR_ROOT died with the shell. It is discovered by reading
# /proc, so nothing on disk knew where the dashboard belonged. The server kept serving a
# temp directory that was then deleted; the board rendered every column as (0); and
# nothing in any log named the cause. Twenty minutes to diagnose.
#
# So the gate writes the address down BEFORE it moves anything, and agentmux repairs it
# on the next invocation.
#
# THE SHAPE OF THESE TESTS. Every positive is paired with the negative that proves it is
# discriminating: "it repaired" is worthless without "it left a running gate alone".
set -u
[ -f dashboard/testlib.sh ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }
# shellcheck source=/dev/null
. <(tr -d '\r' < dashboard/testlib.sh)   # tr: testlib may arrive CRLF; bash cannot source that

REAL_REPO="$PWD"
FIX="$(mktemp -d)"
OPER="$(mktemp -d)"
TEST_HOME="$(mktemp -d)"
trap 'rm -rf "$FIX" "$OPER" "$TEST_HOME"' EXIT

HARNESS="$FIX/agentmux.sh"
tr -d '\r' < agentmux.sh > "$HARNESS"

# A fixture checkout. The marker logic is the REAL suite_server.py; only restart.sh and
# the --expect verification are stubbed, so nothing actually restarts a live server.
mkdir -p "$FIX/dashboard" "$FIX/bin"
cp dashboard/suite_server.py "$FIX/dashboard/suite_server.py"
python3 - "$FIX" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1]) / 'dashboard' / 'suite_server.py'
s = p.read_text(encoding='utf-8')
# Anchored on the real --expect branch rather than the line above it: main()
# gained a --server-cwd branch in between. This guard existing at all is why
# that drift was loud rather than silent.
old = "        if args.expect:\n            if home != str(Path(args.expect).resolve()):"
assert old in s, 'suite_server.py main() shape changed; fixture shim needs updating'
p.write_text(s.replace(old, "        if args.expect:\n            return\n" + old), encoding='utf-8')
PY

export FIXLOG="$FIX/restarts.log"
: > "$FIXLOG"
restart_stub_ok() {
  printf '#!/usr/bin/env bash\nprintf "%%s\\n" "${AGENTMUX_HOME:-<unset>}" >> "$FIXLOG"\n' \
    > "$FIX/dashboard/restart.sh"
}
restart_stub_fails() {
  printf '#!/usr/bin/env bash\nexit 1\n' > "$FIX/dashboard/restart.sh"
}
restart_stub_ok

SS="$FIX/dashboard/suite_server.py"
# A pid that is provably not running: allocate one and reap it.
dead_pid() { python3 -c 'import subprocess; p = subprocess.Popen(["true"]); p.wait(); print(p.pid)'; }
mark()     { python3 "$SS" --mark --operator "$OPER" --test-home "$TEST_HOME" \
                           --gate-pid "$1" --repo "$FIX"; }
clear_marker() { python3 "$SS" --clear --operator "$OPER" 2>/dev/null; }
marker_there() { [ -f "$OPER/.dashboard-takeover.json" ] && echo yes || echo no; }
restarts()     { wc -l < "$FIXLOG" | tr -d ' '; }
run()          { AGENTMUX_HOME="$OPER" AGENTMUX_REPO="$FIX" bash "$HARNESS" "$@"; }

# ── the marker itself ────────────────────────────────────────────────────────

mark "$(dead_pid)"
check "the marker is private" "-rw-------" "$(ls -l "$OPER/.dashboard-takeover.json" | cut -d' ' -f1)"
check "it records the operator home" "$OPER" \
  "$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["operator_home"])' "$OPER/.dashboard-takeover.json")"
# repo is not decoration: restart.sh refuses unless dashboard/server.py is under the cwd,
# so without it the note says where to put the dashboard back but not what can do it.
check "and the checkout that can repair it" "$FIX" \
  "$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["repo"])' "$OPER/.dashboard-takeover.json")"

printf 'not json at all' > "$OPER/.dashboard-takeover.json"
python3 "$SS" --stale --operator "$OPER" >/dev/null 2>&1
check_rc "a corrupt marker reads as absent rather than raising" 1 "$?"

# The version bump must be rejected FOR ITS VERSION. A stub like {"version": 99} is
# also missing every other field, so it would be refused either way and the test could
# not tell the two reasons apart - which is exactly what a mutation removing the
# version check proved. Change nothing but the number.
mark "$(dead_pid)"
python3 - "$OPER/.dashboard-takeover.json" <<'PY'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1])
record = json.loads(p.read_text(encoding='utf-8'))
record['version'] = 99
p.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
PY
python3 "$SS" --stale --operator "$OPER" >/dev/null 2>&1
check_rc "an otherwise-valid marker of an unknown version is refused" 1 "$?"
clear_marker

# ── the repair ───────────────────────────────────────────────────────────────

: > "$FIXLOG"; mark "$(dead_pid)"
run help > "$FIX/out.txt" 2> "$FIX/err.txt" || true
check "a stranded dashboard is restored to the operator home" "$OPER" "$(head -1 "$FIXLOG")"
check "and the marker is cleared afterwards" "no" "$(marker_there)"
# STDOUT IS LOAD-BEARING. `run start` prints a run id that run_tests.sh and the
# orchestrator both capture; a repair line on stdout would be read as part of it.
check "the repair says nothing on stdout" "0" "$(grep -c 'dashboard was serving' "$FIX/out.txt")"
check "it reports on stderr instead" "1" "$(grep -c 'dashboard was serving' "$FIX/err.txt")"
check "and names where it put it back" "1" "$(grep -c "Restored to $OPER" "$FIX/err.txt")"

# THE PAIRED NEGATIVE. Without this, "it repaired" cannot be told apart from "it
# restarts the dashboard whenever it feels like it" - which would black out the board
# in the middle of every gate run.
: > "$FIXLOG"; mark $$
run help >/dev/null 2>&1
check "a gate that is still running is left alone" "0" "$(restarts)"
check "and its marker is kept" "yes" "$(marker_there)"
clear_marker

# The same scoping, from the other side: run_tests.sh exports AGENTMUX_HOME=$TEST_ROOT,
# so agentmux calls INSIDE a gate resolve ROOT to the test home and never see the marker.
: > "$FIXLOG"; mark "$(dead_pid)"
AGENTMUX_HOME="$TEST_HOME" AGENTMUX_REPO="$FIX" bash "$HARNESS" help >/dev/null 2>&1
check "a child inside the gate never repairs" "0" "$(restarts)"
check "and leaves the marker untouched" "yes" "$(marker_there)"
clear_marker

: > "$FIXLOG"; mark "$(dead_pid)"
AGENTMUX_NO_AUTO_RESTORE=1 AGENTMUX_HOME="$OPER" AGENTMUX_REPO="$FIX" \
  bash "$HARNESS" help >/dev/null 2>&1
check "AGENTMUX_NO_AUTO_RESTORE=1 disables it" "0" "$(restarts)"
clear_marker

# A repair that fails must not eat the evidence: the marker is the only record of where
# the dashboard belongs, so losing it on a failed attempt loses the address for good.
: > "$FIXLOG"; mark "$(dead_pid)"; restart_stub_fails
run help >/dev/null 2> "$FIX/err.txt" || true
check "a failed repair keeps the marker for the next try" "yes" "$(marker_there)"
check "and prints the command to run by hand" "1" "$(grep -c 'bash dashboard/restart.sh' "$FIX/err.txt")"
restart_stub_ok; clear_marker

# ── the cost of doing nothing ────────────────────────────────────────────────

# This runs before EVERY verb, including `help`. If the common path is not a single
# stat, it taxes every invocation forever. A python3 that screams proves it is not
# reached: no marker, no work.
printf '#!/bin/sh\necho "PYTHON WAS CALLED" >&2\nexit 99\n' > "$FIX/bin/python3"
chmod +x "$FIX/bin/python3"
err="$(PATH="$FIX/bin:$PATH" AGENTMUX_HOME="$OPER" AGENTMUX_REPO="$FIX" \
        bash "$HARNESS" help 2>&1 >/dev/null || true)"
check "with no marker, nothing is executed at all" "0" "$(printf '%s' "$err" | grep -c 'PYTHON WAS CALLED')"
rm -f "$FIX/bin/python3"

# ── the wiring, pinned so it cannot quietly move ─────────────────────────────

src="$(tr -d '\r' < "$REAL_REPO/agentmux.sh")"
check "the check runs before the dispatch, not inside a verb" "1" \
  "$(printf '%s' "$src" | grep -c '^check_stale_takeover$')"
check "the fast path is a single test on the marker" "1" \
  "$(printf '%s' "$src" | grep -c 'dashboard-takeover.json" \] || return 0')"

gate="$(tr -d '\r' < "$REAL_REPO/dashboard/run_tests.sh")"
check "the gate marks BEFORE it moves the dashboard" "1" \
  "$(printf '%s\n' "$gate" | grep -n 'suite_server.py --mark' | cut -d: -f1 |
     while read -r m; do
       r="$(printf '%s\n' "$gate" | grep -n 'restart_for_home "\$TEST_ROOT"' | cut -d: -f1)"
       [ "$m" -lt "$r" ] && echo 1
     done)"
check "and clears only on the proved-restore branch" "1" \
  "$(printf '%s' "$gate" | grep -c 'suite_server.py --clear')"

# ── TM-020: the dashboard must go back to the OPERATOR's checkout ────────────
#
# The gate runs from an ext4 clone, because 9p drops EIO under load, so its $PWD
# is almost never the checkout the operator is editing. Restoring the home
# without the working directory put their dashboard back on the clone: the page
# worked, nothing logged an error, and the only symptom was that their edits did
# not appear. Measured live on 2026-09-25, serving /home/nick/gate-agentmux with
# AGENTMUX_HOME pointing at a temp directory that was about to be deleted.

check "the restore is given the operator checkout, not the gate's" "1" \
  "$(printf '%s\n' "$gate" | grep -c 'restart_for_home "$OPERATOR_ROOT" "$OPERATOR_REPO"')"
check "and the takeover still serves the gate's own checkout" "1" \
  "$(printf '%s\n' "$gate" | grep -c 'restart_for_home "$TEST_ROOT" "$PWD"')"
# The marker is the recovery path when the EXIT trap never runs, so it has to
# name the same checkout the trap would have restored to. Passing $PWD here was
# half the bug: even the repair put it back in the wrong place.
check "the marker records the operator checkout too" "1" \
  "$(printf '%s\n' "$gate" | grep -c -- '--repo "$OPERATOR_REPO"')"
check "and OPERATOR_REPO comes from the running dashboard" "1" \
  "$(printf '%s\n' "$gate" | grep -c 'OPERATOR_REPO="$(python3 dashboard/suite_server.py --server-cwd)"')"

# The branch that would take the whole gate down if it were wrong. Whether a
# dashboard happens to be running while this suite runs is not something the
# suite controls, so assert the property that holds either way: it must succeed,
# and whatever it prints must be usable as a checkout by the caller that falls
# back on it.
cwd_out="$(cd "$FIX" && python3 "$SS" --server-cwd 2>"$FIX/cwd.err")"
cwd_rc=$?
check "--server-cwd succeeds whether or not a dashboard is up" "0" "$cwd_rc"
check "and says nothing on stderr" "0" "$(wc -c < "$FIX/cwd.err" | tr -d ' ')"
if [ -z "$cwd_out" ]; then
  ok "--server-cwd printed nothing, so the caller keeps its own checkout"
elif [ -f "$cwd_out/dashboard/restart.sh" ]; then
  ok "--server-cwd printed a checkout that can actually restart a dashboard"
else
  bad "--server-cwd printed $cwd_out, which has no dashboard/restart.sh; the gate would restore into it"
fi

# And it reports a cwd when there IS one. The suite's own python is not a
# dashboard, so this asserts the shape rather than a live value: server_location
# returns a pair, and both halves come from the same process.
check "server_location returns a (home, cwd) pair" "2" \
  "$(cd "$FIX" && python3 -c '
import sys
sys.path.insert(0, "dashboard")
import suite_server
print(len(suite_server.server_location()))')"
check "server_home is still the home alone" "1" \
  "$(cd "$FIX" && python3 -c '
import sys
sys.path.insert(0, "dashboard")
import suite_server
home = suite_server.server_home()
print(0 if isinstance(home, tuple) else 1)')"

# ── TM-020, the other half: discovery must cover what the kill covers ────────
#
# restart.sh:18-20 kills every process matching 'dashboard/serv', from any
# checkout. Discovery used to recognise only THIS checkout's server.py - so a
# gate running from the ext4 clone displaced the operator's dashboard without
# ever identifying it, and then had nothing to put back. That asymmetry is the
# bug; "this checkout's dashboard" was written as a feature.
OTHER="$FIX/../other-checkout"
mkdir -p "$OTHER/dashboard"
: > "$OTHER/dashboard/server.py"
: > "$OTHER/dashboard/restart.sh"
NOTADASH="$FIX/../not-a-dashboard"
mkdir -p "$NOTADASH/dashboard"
: > "$NOTADASH/dashboard/server.py"          # no restart.sh beside it

shape() { cd "$FIX" && python3 -c '
import sys
from pathlib import Path
sys.path.insert(0, "dashboard")
import suite_server
print("yes" if suite_server.is_dashboard(Path(sys.argv[1])) else "no")' "$1"; }

check "a dashboard in ANOTHER checkout is recognised" "yes" \
  "$(shape "$OTHER/dashboard/server.py")"
check "a server.py with no restart.sh beside it is not" "no" \
  "$(shape "$NOTADASH/dashboard/server.py")"
check "a server.py outside a dashboard directory is not" "no" \
  "$(shape "$FIX/server.py")"
# The parent IS named dashboard here, so this reaches the filesystem call rather
# than short-circuiting before it. These paths can live on the 9p mount, where a
# stat under load raises EIO out of a call that reads as total - the TM-013
# family - so a process this cannot classify must simply not be counted, and
# must never take the caller down with it.
check "a missing path answers no rather than raising" "no" \
  "$(shape "$FIX/no-such-checkout/dashboard/server.py")"

finish
