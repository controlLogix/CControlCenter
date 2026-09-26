#!/usr/bin/env bash
# Run every agentmux suite. From the repo root, inside WSL:
#   bash <(tr -d '\r' < dashboard/run_tests.sh)
#
# Runs the server on a disposable AGENTMUX_HOME at the usual port, restores the
# operator home on exit/signals, and spawns throwaway agents if needed because
# the stream checks need live panes. Both are cleaned up on exit. Exits non-zero if any
# suite fails.
#
# test_auth.py needs an interactive-ish shell for nvm's node (codex is validated
# through `codex exec --strict-config`), so run this under `bash -ic` if codex is
# not on PATH.
set -u
[ -f dashboard/server.py ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }

# HTTP writes occur in the SERVER process: a client-side home cannot isolate them.
# Lease port 8787 for this suite, swap to an empty home, and restore without ever
# passing --fresh-db. The EXIT handler is installed before the first restart.
exec 200>"${TMPDIR:-/tmp}/agentmux-dashboard-tests-${UID}.lock"
flock -n 200 || {
  # This used to say "another dashboard suite owns port 8787", which sent two
  # separate investigations to netstat. The guard is a LOCK, not a port probe, so
  # say so and name the file - the holder is findable in one command from here.
  echo "another dashboard suite holds the lock (this is a flock, not a port check)" >&2
  echo "  lock: ${TMPDIR:-/tmp}/agentmux-dashboard-tests-${UID}.lock" >&2
  echo "  who:  fuser -v '${TMPDIR:-/tmp}/agentmux-dashboard-tests-${UID}.lock'" >&2
  echo "  a killed run can leave a detached tmux server or idle watchdog holding it" >&2
  exit 2
}
OPERATOR_ROOT="$(python3 dashboard/suite_server.py --fallback "${AGENTMUX_HOME:-$HOME/.agentmux}")" || exit 2
# WHICH CHECKOUT the operator's dashboard is serving, not just which home.
#
# TM-020: this gate runs from an ext4 clone, because 9p drops EIO under load -
# so the gate's $PWD is almost never the operator's checkout. Restoring without
# this put their dashboard back on the clone: the page worked, nothing logged an
# error, and the only symptom was that their edits did not appear.
#
# Empty when no dashboard is running, in which case this checkout is the only
# answer available and is also the right one.
OPERATOR_REPO="$(python3 dashboard/suite_server.py --server-cwd)" || exit 2
[ -n "$OPERATOR_REPO" ] && [ -f "$OPERATOR_REPO/dashboard/restart.sh" ] || OPERATOR_REPO="$PWD"
TEST_ROOT="$(mktemp -d)" || exit 2
SPAWNED=""
HARNESS=""
SUITE_PID=""
RESTORE_NEEDED=0

restart_for_home() {
  # $1 the home, $2 the CHECKOUT to serve from. Both, because restoring one
  # without the other is what TM-020 was: the right board, the wrong files.
  local home="$1" repo="${2:-$PWD}"
  # Cleanup ignores repeated interrupts, but the restored server must retain its
  # normal signal handlers so the next restart can stop it. os.chdir before the
  # exec, because restart.sh refuses unless dashboard/server.py is under the
  # working directory - and that is the whole point here.
  AGENTMUX_HOME="$home" python3 -c 'import os, signal, sys; signal.signal(signal.SIGINT, signal.SIG_DFL); signal.signal(signal.SIGTERM, signal.SIG_DFL); os.chdir(sys.argv[2]); os.execvp("bash", ["bash", sys.argv[1]])' \
    <(tr -d '\r' < "$repo/dashboard/restart.sh") "$repo" 200>&-
}

cleanup() {
  local status=$? restore_status=0
  trap - EXIT
  trap '' INT TERM
  if [ -n "$SUITE_PID" ]; then
    # A signal to this shell must stop the HTTP-writing child BEFORE restoring the
    # live server. Each suite has a private process group, including descendants.
    kill -TERM -- "-$SUITE_PID" 2>/dev/null || true
    for _ in {1..30}; do
      kill -0 -- "-$SUITE_PID" 2>/dev/null || break
      sleep 0.1
    done
    kill -KILL -- "-$SUITE_PID" 2>/dev/null || true
    wait "$SUITE_PID" 2>/dev/null || true
  fi
  for agent in $SPAWNED; do
    bash "$HARNESS" kill "$agent" >/dev/null 2>&1
  done
  [ -n "$HARNESS" ] && rm -f "$HARNESS"
  if [ "$RESTORE_NEEDED" = 1 ]; then
    restart_for_home "$OPERATOR_ROOT" "$OPERATOR_REPO" >/dev/null &&
      python3 dashboard/suite_server.py --expect "$OPERATOR_ROOT"
    restore_status=$?
  fi
  if [ "$restore_status" != 0 ]; then
    echo "  FAIL  could not restore dashboard home $OPERATOR_ROOT; retained test home $TEST_ROOT for recovery" >&2
    echo "  the takeover marker is left in place; the next agentmux command will retry" >&2
    status=1
  else
    # Cleared only once --expect has PROVED the restore, never merely attempted it. A
    # marker that outlives a failed restore is the whole point: the next agentmux
    # invocation reads it and finishes the job.
    python3 dashboard/suite_server.py --clear --operator "$OPERATOR_ROOT" 2>/dev/null
    rm -rf "$TEST_ROOT"
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

export AGENTMUX_HOME="$TEST_ROOT"
export AGENTMUX_NO_COURIER=1
# Suites simulate several identities; an invoking worker is not their identity.
unset AGENTMUX_AGENT
RESTORE_NEEDED=1
# WRITE THE ADDRESS DOWN BEFORE MOVING THE DASHBOARD.
#
# OPERATOR_ROOT was discovered by reading /proc, so until this line the only record of
# where the dashboard belongs is a variable in this shell. The EXIT trap below restores
# it - but a trap cannot survive SIGKILL, and the idle watchdog kills panes. When that
# happened the dashboard was left serving $TEST_ROOT, which is then deleted, and the
# board rendered every column empty with nothing in any log naming the cause.
#
# Deliberately before restart_for_home rather than after: a death BETWEEN arming the
# restore and completing it is exactly the window this protects.
python3 dashboard/suite_server.py --mark --operator "$OPERATOR_ROOT" \
  --test-home "$TEST_ROOT" --gate-pid $$ --repo "$OPERATOR_REPO" || exit 1
restart_for_home "$TEST_ROOT" "$PWD" >/dev/null || exit 1
python3 dashboard/suite_server.py --expect "$TEST_ROOT" || exit 1


# Agents, if there are none.
#
# smoke.sh and test_snapshot.py assert against live panes: /api/stream-all has nothing
# to carry without one, and the snapshot framing checks need a real pane to frame. Run
# cold, that cost three checks in smoke.sh and six in test_snapshot.py - failures that
# look exactly like a streaming regression and have cost real time being investigated as
# one, twice.
#
# So the suite provides its own. Two `--cli shell` agents need no credentials and no
# network. Pre-existing agents are left completely alone: if any session is already up,
# nothing is spawned and nothing is killed, because the operator's agents are not the
# test's to manage.
#
# AGENTMUX_NO_COURIER=1 because a test run should not leave a daemon behind; the
# courier's own lifecycle is covered by test_courier.py against an isolated HOME.
if command -v tmux >/dev/null 2>&1; then
  live="$(tmux -L agentmux list-sessions -F '#{session_name}' 2>/dev/null | grep -c . || true)"
  if [ "${live:-0}" -eq 0 ]; then
    HARNESS="$(mktemp)"
    tr -d '\r' < agentmux.sh > "$HARNESS"
    export AGENTMUX_REPO="${AGENTMUX_REPO:-$PWD}"
    export AGENTMUX_NO_COURIER=1
    for agent in agentmux-selftest-$$-1 agentmux-selftest-$$-2; do
      # 200>&- because the tmux SERVER this starts is a daemon that inherits our fd
      # table and outlives us. Without it a run killed before its EXIT handler left
      # tmux holding the single-instance lock, and every later run refused to start.
      # run() below already closes it for the same reason; this call site was missed.
      if bash "$HARNESS" spawn "$agent" --cli shell --cwd /tmp >/dev/null 2>&1 200>&-; then
        SPAWNED="$SPAWNED $agent"
      fi
    done
    if [ -n "$SPAWNED" ]; then
      echo "(spawned$SPAWNED for the stream checks; they are killed on exit)"
      sleep 1
    else
      echo "WARNING: could not spawn test agents; stream checks will fail" >&2
    fi
  fi
else
  echo "WARNING: tmux not found; stream checks will fail without live agents" >&2
fi

# Read-only stream fixtures for existing panes: the temporary server needs its own
# log paths and pane ids. Never copy credentials, tasks, or change a live pipe-pane.
mkdir -p "$TEST_ROOT/run" "$TEST_ROOT/logs"
while IFS=$'\t' read -r name pane; do
  [[ "$name" =~ ^[A-Za-z0-9_.-]{1,64}$ && "$pane" =~ ^%[0-9]+$ ]] || continue
  printf '%s\n' "$pane" > "$TEST_ROOT/run/$name.pane"
  touch "$TEST_ROOT/logs/$name.log"
done < <(tmux -L agentmux list-panes -a -F $'#{session_name}\t#{pane_id}' 2>/dev/null)

total_fail=0

run() {
  local label="$1"; shift
  printf '%-16s ' "$label"
  local out rc
  # Background bash jobs inherit SIGINT ignored. Reset it before exec so both
  # interactive interrupts and nested signal-regression probes exercise the traps.
  python3 -c 'import os, signal, sys; os.setsid(); signal.signal(signal.SIGINT, signal.SIG_DFL); signal.signal(signal.SIGTERM, signal.SIG_DFL); os.execvp(sys.argv[1], sys.argv[1:])' \
    "$@" > "$TEST_ROOT/suite.out" 2>&1 200>&- &
  SUITE_PID=$!
  wait "$SUITE_PID"; rc=$?
  SUITE_PID=""
  out="$(cat "$TEST_ROOT/suite.out")"
  local line
  line="$(printf '%s\n' "$out" | tail -1)"
  # A suite cannot have passed a negative number of tests, and one reported
  # "passed -1, failed 1" on 2026-09-25. The suites share a
  # `testsRun - failed - skipped` formula, and when setUpClass errors unittest
  # records the error while testsRun stays at zero - so the count goes below
  # zero and the gate prints it without blinking.
  #
  # Deliberately NOT clamped in the suites: a number that cannot be true is the
  # only evidence that the class never ran, and clamping it to 0 would make that
  # look like an ordinary empty suite. Name it here instead, where it is read.
  case "$line" in
    passed\ -*) line="DID NOT RUN - class or module setup failed ($line)" ;;
  esac
  printf '%s\n' "$line"
  # Keep unavailable-history skips visible even when a meta-check exits cleanly.
  printf '%s\n' "$out" | grep '^SKIP ' || true
  # And the shape that grep cannot see. A suite ending in plain unittest.main()
  # reports `OK (skipped=1)`, which the `0:OK *` case below accepts as success -
  # so a test that did not run looks exactly like one that passed. Surface it
  # here rather than failing the suite: a skip is an unknown, not a failure, and
  # a gate that goes red on every skip stops being read.
  case "$line" in
    OK\ *skipped=*) echo "SKIP $label reported $line" ;;
  esac
  case "$rc:$line" in
    # Two success shapes, because there are two kinds of suite. The shell suites and
    # the older python ones print "passed N, failed 0" via their own harness; a suite
    # using raw unittest prints "OK" and exits 0. Matching only the first counted four
    # passing suites as failures - the gate said "5 suite(s) failed" while every line
    # above it said OK, which is the kind of noise that gets a gate ignored.
    0:*"failed 0") ;;
    0:OK|0:OK\ *) ;;
    *) total_fail=$((total_fail + 1))
       # Two failure shapes, because there are two kinds of suite here. The shell
       # suites print '  FAIL  <what>' via testlib; a python unittest suite prints
       # 'FAIL: <test>' at column zero followed by its traceback. Matching only the
       # first meant a failing .py suite reported the bare word FAILED and nothing
       # else - you could see THAT it broke and never WHAT broke, which is how the
       # last person to hit this ended up bisecting by hand.
       #
       # THREE shapes, not two. test_e2e.mjs prints 'FAIL <name>' at column zero
       # with NO colon, so it matched neither pattern and a failing e2e run said
       # nothing whatsoever - which is what happened on 2026-09-25 and cost a
       # full re-run just to learn which suite it had been.
       if printf '%s\n' "$out" | grep -E '^[[:space:]]+FAIL'; then :; else
         printf '%s\n' "$out" | grep -E '^(FAIL|ERROR)[: ]' -A 12 | head -40
       fi ;;

  esac
}

# testlib first: it proves the shared assertions can FAIL on the bug shapes they exist
# for. If they cannot, every suite below that uses them is decoration.
run test_testlib.sh bash /dev/fd/8 8< <(tr -d '\r' < dashboard/test_testlib.sh)
# Historical differentials and the meta-check's own known-broken fixtures.
run check_test_failability.sh bash /dev/fd/11 11< <(tr -d '\r' < dashboard/check_test_failability.sh)
run test_argguard.sh bash /dev/fd/9 9< <(tr -d '\r' < dashboard/test_argguard.sh)
run test_modal_guard.sh bash /dev/fd/4 4< <(tr -d '\r' < dashboard/test_modal_guard.sh)
run test_inbox_guard.sh bash /dev/fd/5 5< <(tr -d '\r' < dashboard/test_inbox_guard.sh)
run test_coordination.sh bash /dev/fd/6 6< <(tr -d '\r' < dashboard/test_coordination.sh)
run test_run.sh   bash /dev/fd/7 7< <(tr -d '\r' < dashboard/test_run.sh)
run test_residue.sh bash /dev/fd/12 12< <(tr -d '\r' < dashboard/test_residue.sh)
run test_takeover_recovery.sh bash /dev/fd/21 21< <(tr -d '\r' < dashboard/test_takeover_recovery.sh)
run test_lifecycle.sh bash /dev/fd/10 10< <(tr -d '\r' < dashboard/test_lifecycle.sh)
run test_theme_import.sh bash /dev/fd/13 13< <(tr -d '\r' < dashboard/test_theme_import.sh)
run test_themes.sh bash /dev/fd/13 13< <(tr -d '\r' < dashboard/test_themes.sh)
run test_frontend.sh bash /dev/fd/12 12< <(tr -d '\r' < dashboard/test_frontend.sh)
run test_frontend_board.sh bash /dev/fd/14 14< <(tr -d '\r' < dashboard/test_frontend_board.sh)
run test_frontend_post.sh bash /dev/fd/19 19< <(tr -d '\r' < dashboard/test_frontend_post.sh)
run test_frontend_kanban.sh bash /dev/fd/18 18< <(tr -d '\r' < dashboard/test_frontend_kanban.sh)
run test_frontend_drawer.sh bash /dev/fd/20 20< <(tr -d '\r' < dashboard/test_frontend_drawer.sh)
run test_frontend_tabs.sh bash /dev/fd/15 15< <(tr -d '\r' < dashboard/test_frontend_tabs.sh)
# The idle-agent timeout. Sources agentmux.sh for its selection function and tests
# it against a fixture, so it needs no tmux server and cannot touch a live agent.
run test_idle.sh bash /dev/fd/17 17< <(tr -d '\r' < dashboard/test_idle.sh)
run smoke.sh      bash /dev/fd/3 3< <(tr -d '\r' < dashboard/smoke.sh)
# The board model and the dispatch seam. test_board.py landed with the store and
# was never listed here, so it had not run in the gate since the day it was
# written - a suite nothing invokes is decoration, which is the same standard
# test_testlib.sh is held to above.
run test_board.py python3 dashboard/test_board.py
run test_dispatch.py python3 dashboard/test_dispatch.py
run test_sandbox_coordination.py python3 dashboard/test_sandbox_coordination.py
# The Runs read surface and the human approval gate in front of completion.
run test_runsview.py python3 dashboard/test_runsview.py
# Notification channels, and who hears about what. AGENTMUX_NO_TOAST keeps the
# desktop channel out of it - a suite that pops toasts is a suite people stop
# running - so the real toast is exercised by hand via taskmgmt/notify.py.
run test_notify.py python3 dashboard/test_notify.py
# The wire between a completed run and the board cards it was assigned.
run test_runcards.py python3 dashboard/test_runcards.py
# The orchestrator warrant: what it permits, and everything it must still refuse.
run test_warrant.py python3 dashboard/test_warrant.py
# EP-015 suites are registered at the scaffold seam before their owning tasks land.
# Missing suites are explicit skips during the staged build; present suites use
# the same failure accounting as every existing suite above.
for suite in test_modbus_poll.py test_modbus_rtu.py test_enip.py test_orchestration_plugin.py test_plugin_skills.py test_agentdefs.py test_agentcli.py test_teamcli.py test_boardagents.py test_boardteams.py \
             test_launch.sh test_frontend_agents.sh test_frontend_teams.sh test_frontend_collapse.sh; do
  if [ ! -f "dashboard/$suite" ]; then
    echo "SKIP $suite (EP-015 suite has not landed yet)"
  elif [[ "$suite" == *.py ]]; then
    run "$suite" python3 "dashboard/$suite"
  else
    run "$suite" bash /dev/fd/13 13< <(tr -d '\r' < "dashboard/$suite")
  fi
done
run test_github_panel.py python3 dashboard/test_github_panel.py
run test_codesys_panel.py python3 dashboard/test_codesys_panel.py
run test_logix.py python3 dashboard/test_logix.py
run test_ads.py python3 dashboard/test_ads.py
# The one journal every write to physical equipment goes through. Its ordering
# and fail-closed properties are what make "every write is audited" true rather
# than aspirational, and the census test is what keeps a fourth client from
# quietly starting a fourth file the way ads.py did.
run test_writejournal.py python3 dashboard/test_writejournal.py
# The audited pycomm3 wrapper: tag browsing and UDT decoding on the read side,
# and on the write side a path that cannot be taken without leaving a record.
run test_rockwell.py python3 dashboard/test_rockwell.py
# Single-use, expiring write authorisations. The write route names a ticket
# and cannot say what to write; the ticket carries that, fixed when it was
# minted. This is the gate that had to exist before the route did.
run test_field_tickets.py python3 dashboard/test_field_tickets.py
# TM-020: a dashboard left behind by a gate run must SAY so. The failure it
# covers is the one nobody reports - the page looked entirely normal and
# simply served different files than the ones on disk.
run test_serving.py python3 dashboard/test_serving.py
# The device tree: the segment scan and CIP discovery merged without pretending
# they are equal kinds of knowing. Pure logic, no network.
run test_devicetree.py python3 dashboard/test_devicetree.py
# TM-017: the SSE slot guard. A page reload must not cost a slot - seven panes
# over a couple of reloads once exhausted all sixteen. Server-side, so no
# browser needed; proved by mutation, since the guard predates the repo's
# first commit and has no failability base.
run test_stream_slots.py python3 dashboard/test_stream_slots.py
# TM-017 AC 2: the same guard, LIVE. A real dashboard on an ephemeral port with a
# throwaway AGENTMUX_HOME and a stub tmux, driven over raw sockets left undrained
# - because a drained socket is not an abandoned EventSource, and the in-process
# suite can be wholly green while the running server still wedges. The catch it
# alone makes: a refused reload must free its own predecessor. ~7s.
run test_stream_slots_live.py python3 dashboard/test_stream_slots_live.py
# TM-031: a 9p read that failed transiently was answered as 404, so the browser
# was told kanban.js does not exist - and, because the body was JSON under the
# nosniff header, it refused to run the script and the board never rendered.
# The e2e suite saw only a timeout. This asserts the distinction the handler now
# keeps: absent is 404, unreadable is 503 and is retried first.
run test_static_serving.py python3 dashboard/test_static_serving.py
run test_pn_dcp.py python3 dashboard/test_pn_dcp.py
run test_ecat_diag.py python3 dashboard/test_ecat_diag.py
run test_snapshot.py python3 dashboard/test_snapshot.py
run test_mqtt.py  python3 dashboard/test_mqtt.py
# The monitor's session handling: TLS, reconnect and the missing-vendor path.
# Scoped to what test_field_panels.py does NOT already cover, and proved by
# mutation rather than by check_test_failability - see its docstring for why.
run test_mqtt_monitor.py python3 dashboard/test_mqtt_monitor.py
# netscan internals test_field_panels.py does not reach: the ARP parsers, the
# WSL fallback, and the never-fatal contract. Added after a 9p EIO stat inside
# neighbour_table killed whole scans on ~60% of e2e runs.
run test_netscan.py python3 dashboard/test_netscan.py
# The field sidecar's HTTP shell: the shared secret, the loopback assertion, and
# what it REFUSES. Asserted before any write route exists, because a write route
# added later inherits whatever posture is already here.
run test_field_sidecar.py python3 dashboard/test_field_sidecar.py
# Files that are PARSED rather than read must be LF. A CRLF testlib makes every
# suite exit 127 with no assertions; a CRLF task store makes tm board render
# "undefined undefined" while the documents are perfectly intact.
run check_line_endings.sh bash /dev/fd/22 22< <(tr -d '\r' < dashboard/check_line_endings.sh)
# Vendored third-party code: are these the bytes that were reviewed? Checked
# offline by hash, because the whole point of vendoring is the boxes that cannot
# reach PyPI - and a check that needed PyPI would not run on them.
run check_vendor.sh bash /dev/fd/25 25< <(tr -d '\r' < dashboard/check_vendor.sh)
# pycomm3 has exactly one importer and the sidecar has no raw-CIP route. Both
# are properties of what is ABSENT, which is the kind that gets deleted by
# accident because nothing visibly depends on it.
run check_field_writes.sh bash /dev/fd/26 26< <(tr -d '\r' < dashboard/check_field_writes.sh)
# Can the gate say WHAT broke, not just THAT something did? That property has
# been violated four separate ways here, each time silently, and each time the
# symptom was a gate that was technically correct and practically useless.
run test_gate_reporting.sh bash /dev/fd/27 27< <(tr -d '\r' < dashboard/test_gate_reporting.sh)
# THIS REPO IS PUBLIC, and Phase 5 adds a brokerage session. A push cannot be
# taken back, so the boundary is gated before the feature that needs it exists.
# The guard has its own suite because one that silently always passed would be
# counted as coverage - smoke.sh:181 is the recorded precedent here.
run check_no_financial_artifacts.sh bash /dev/fd/29 29< <(tr -d '\r' < dashboard/check_no_financial_artifacts.sh)
run test_no_financial_artifacts.sh bash /dev/fd/30 30< <(tr -d '\r' < dashboard/test_no_financial_artifacts.sh)
# The two interlocks in front of an order, built before the order pipeline for
# the same reason the ticket came before the write route. Pure logic and file
# state: no broker, no browser, no money.
run test_killswitch.py python3 agentmux-broker/test_killswitch.py
run test_guardrails.py python3 agentmux-broker/test_guardrails.py
# Selector drift: alert, never retry. The registry refuses to guess which button
# is Place Order, and a drift arms the switch even when the screenshot fails.
# NOT named selectors.py: `selectors` is stdlib and `subprocess` imports it, so
# a file by that name in this directory shadows it for the whole process - which
# broke test_killswitch.py with an AttributeError pointing nowhere near the
# cause. The map file on disk is still selectors.json.
run test_selectormap.py python3 agentmux-broker/test_selectormap.py
# The venue end of that pipeline: the thing that actually submits and reads back.
# Paper only, and the Alpaca adapter is driven against a loopback stub - no
# network reaches Alpaca, paper or otherwise.
run test_venue.py python3 agentmux-broker/test_venue.py
# Credential storage. Credential Manager via ctypes (preferred: the OS gives a UI
# to inspect and revoke), DPAPI as the documented fallback, and an in-memory
# backend so the module is testable where this gate runs. The sentinel suite
# drives every route out of the module - repr, describe, json, the CLI's stdout,
# every log record, every exception AND its traceback - asserting the value
# appears only where reveal() returns it. The Windows backends SKIP by name here
# rather than passing quietly.
run test_creds.py python3 agentmux-broker/test_creds.py
# The gate in front of a write to PHYSICAL EQUIPMENT. Until 2026-09-25 that was a
# one-click window.confirm and nothing tested it at all.
run test_frontend_iiot_write.sh bash /dev/fd/23 23< <(tr -d '\r' < dashboard/test_frontend_iiot_write.sh)
# TM-025: the age beside a value, driven through the real render path under a
# faked browser clock. An age computed across two clocks is worse than none -
# it still looks authoritative, and it decides whether a value reads as live.
run test_frontend_iiot_age.sh bash /dev/fd/24 24< <(tr -d '\r' < dashboard/test_frontend_iiot_age.sh)
# The device tree panel, driven through its real render: a guess and a statement
# must not look alike on screen, which is the whole reason the panel exists.
run test_frontend_devicetree.sh bash /dev/fd/28 28< <(tr -d '\r' < dashboard/test_frontend_devicetree.sh)
# The localStorage key migration, run against the real block in index.html.
# These keys are persisted operator state; renaming them without carrying the
# values across wipes themes and board layout silently.
run test_frontend_storage.sh bash /dev/fd/17 17< <(tr -d '\r' < dashboard/test_frontend_storage.sh)
# The IIOT field services. Self-contained: its own HTTP server on an ephemeral port
# and its own throwaway AGENTMUX_HOME, so it neither needs nor disturbs the shared
# server this suite brought up.
run test_field_panels.py timeout 300 python3 dashboard/test_field_panels.py
# The browser suite. Brings up its own dashboard and its own stub broker on
# ephemeral ports, so it needs neither the shared server this suite started nor the
# 8787 lock. It SKIPS, loudly, if no Playwright installation can be found - see the
# message it prints for how to get one.
run test_e2e.sh bash /dev/fd/16 16< <(tr -d '\r' < dashboard/test_e2e.sh)
run test_tickets.py python3 dashboard/test_tickets.py
run test_chatter.py python3 dashboard/test_chatter.py
run test_courier.py python3 dashboard/test_courier.py
run test_gateway.py python3 dashboard/test_gateway.py
run test_auth.py  timeout 400 python3 dashboard/test_auth.py

# test_gateway.py needs no key and makes no network call, so it runs whether or not the
# Bedrock path is parked. Its last section compares the reconstructed
# taskmgmt/bedrock_gateway.py against the preserved 2026-09-19 bytecode, running both on
# identical inputs; that section skips itself once CPython can no longer load the .pyc.

echo
if [ "$total_fail" -eq 0 ]; then
  echo 'all suites passed'
else
  echo "$total_fail suite(s) failed"
fi
exit "$total_fail"
