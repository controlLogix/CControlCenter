#!/usr/bin/env bash
# Drive the real dashboard in a real browser. Run from the repo root:
#   bash <(tr -d '\r' < dashboard/test_e2e.sh)
#
# WHAT IT BRINGS UP, AND WHY NONE OF IT TOUCHES YOURS. A dashboard of its own on an
# ephemeral port with a throwaway AGENTMUX_HOME, plus a stub MQTT broker on another
# ephemeral port. It never binds 8787, never reads your cc.db, and never needs the
# suite lock, so it can run while your own dashboard is up.
#
# That is only possible because the write guard derives its allowed origin from the
# port the server actually bound (Handler.allowed_origins). While that was the
# literal string "http://127.0.0.1:8787", every write from any other port was
# refused, so the only way to test the write paths in a browser was to take the
# operator's port away from them.
#
# PLAYWRIGHT IS NOT VENDORED. This repo has no package.json and no node_modules, so
# rather than add one, the browser driver is discovered: $PLAYWRIGHT_DIR if you set
# it, otherwise whatever `npx @playwright/mcp` already unpacked into the npm cache.
# If neither is there the suite SKIPS with the command to fix it, because a browser
# test that silently passes without a browser is worse than no browser test.
set -u
[ -f dashboard/server.py ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }

if ! command -v node >/dev/null 2>&1; then
  e2e_node_dir=$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1 || true)
  [ -z "$e2e_node_dir" ] || export PATH="$e2e_node_dir:$PATH"
fi
if ! command -v node >/dev/null 2>&1; then
  echo 'SKIP test_e2e: node is not on PATH'
  exit 0
fi

find_playwright() {
  if [ -n "${PLAYWRIGHT_DIR:-}" ] && [ -d "$PLAYWRIGHT_DIR" ]; then
    printf '%s' "$PLAYWRIGHT_DIR"
    return 0
  fi
  # A LOCAL install first, and it has to be first. The npx caches below can hold a
  # WINDOWS playwright build - this repo lives on /mnt/c - whose firefox binary cannot
  # be launched from WSL. Finding that one made the suite fail with "Executable doesn't
  # exist" rather than skip, which reads like a broken test rather than a missing
  # browser. ~/pw is the linux install; prefer it.
  if [ -d "$HOME/pw/node_modules/playwright" ]; then
    printf '%s' "$HOME/pw/node_modules/playwright"
    return 0
  fi
  local cache
  for cache in "$HOME/.npm/_npx" "${LOCALAPPDATA:-}/npm-cache/_npx"; do
    [ -d "$cache" ] || continue
    local found
    found=$(find "$cache" -maxdepth 3 -type d -name playwright 2>/dev/null | head -1)
    if [ -n "$found" ]; then
      printf '%s' "$found"
      return 0
    fi
  done
  return 1
}

PW=$(find_playwright) || {
  cat <<'MSG'
SKIP test_e2e: no Playwright installation found.

  Install one, then re-run:
      mkdir -p ~/pw && cd ~/pw && npm init -y && npm install playwright
      npx playwright install firefox           # the LINUX browser

  A Windows playwright under /mnt/c will be found but cannot launch from WSL.

  Or point at an existing one:
      PLAYWRIGHT_DIR=/path/to/node_modules/playwright bash dashboard/test_e2e.sh
MSG
  exit 0
}

# Forward slashes: this path is handed to node's require() from inside the script.
PW=${PW//\\//}
echo "playwright: $PW"

TEST_HOME=$(mktemp -d) || exit 2
SERVER_PID=""
BROKER_PID=""

cleanup() {
  local status=$?
  trap - EXIT
  [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null
  [ -n "$BROKER_PID" ] && kill "$BROKER_PID" 2>/dev/null
  rm -rf "$TEST_HOME"
  exit "$status"
}
trap cleanup EXIT INT TERM

# An ephemeral port each, asked for from the OS rather than guessed at, so two of
# these can run at once and neither can collide with 8787.
free_port() {
  python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'
}
PORT=$(free_port)
BROKER_PORT=$(free_port)

echo "dashboard: 127.0.0.1:$PORT   broker: 127.0.0.1:$BROKER_PORT   home: $TEST_HOME"

# ONE RUN, ALREADY VERIFIED AND WAITING ON A PERSON.
#
# The Runs view has nothing to draw without one, and the state worth exercising in a
# browser is precisely the one a suite cannot reach by clicking: every job passed
# review, so the run is sitting at the operator gate. Seeded here rather than in the
# .mjs because it is filesystem state under AGENTMUX_HOME, which is this script's job.
AGENTMUX_HOME="$TEST_HOME" python3 - <<'SEEDRUN'
import sys
sys.path.insert(0, 'taskmgmt')
import run
rid = "e2e001"
run.run_dir(rid).mkdir(parents=True, exist_ok=True)
run.append_event(rid, {"event": "start", "by": "orchestrator",
                       "base": "0" * 40,      # no such commit: exercises the fallback
                       "detail": "e2e: a run waiting on the operator"})
for i in (1, 2):
    job = f"{rid}/{i}"
    run.append_event(rid, {"event": "assign", "job": job, "by": "orchestrator",
                           "worker": "e2e-worker", "reviewer": "e2e-reviewer",
                           "task": "TM-E2E"})
    run.append_event(rid, {"event": "submit", "job": job, "by": "e2e-worker",
                           "files": ["dashboard/runs.js"]})
    run.append_event(rid, {"event": "verdict", "job": job, "by": "e2e-reviewer",
                           "result": "pass", "attempt": 1, "detail": "ran it"})
# A second run that is still blocked, so the view has both shapes to draw.
rid2 = "e2e002"
run.run_dir(rid2).mkdir(parents=True, exist_ok=True)
run.append_event(rid2, {"event": "start", "by": "orchestrator",
                        "detail": "e2e: a run still in flight"})
run.append_event(rid2, {"event": "assign", "job": f"{rid2}/1", "by": "orchestrator",
                        "worker": "e2e-ghost", "reviewer": "e2e-reviewer"})
run.append_event(rid2, {"event": "submit", "job": f"{rid2}/1", "by": "e2e-ghost",
                        "files": ["x.txt"]})
SEEDRUN

AGENTMUX_HOME="$TEST_HOME" python3 dashboard/server.py --port "$PORT" >"$TEST_HOME/server.log" 2>&1 &
SERVER_PID=$!
python3 dashboard/stub_broker.py --port "$BROKER_PORT" --quiet >"$TEST_HOME/broker.log" 2>&1 &
BROKER_PID=$!

for _ in $(seq 1 60); do
  if curl -fsS -o /dev/null "http://127.0.0.1:$PORT/"; then break; fi
  sleep 0.25
done
if ! curl -fsS -o /dev/null "http://127.0.0.1:$PORT/"; then
  echo '  FAIL  the test dashboard never came up' >&2
  cat "$TEST_HOME/server.log" >&2
  exit 1
fi

node dashboard/test_e2e.mjs "http://127.0.0.1:$PORT" "$PW" "$BROKER_PORT" 2>&1 | tee "$TEST_HOME/e2e.out"
status=${PIPESTATUS[0]}
# Found by pattern, not by position. tail -1 assumed the summary was last, and
# it was not - test_e2e.mjs printed its roll-call of failed names after it. An
# anchor that depends on nothing else being printed afterwards is an anchor that
# breaks the next time anything is.
summary="$(grep -E '^passed [0-9]+, failed [0-9]+$' "$TEST_HOME/e2e.out" | tail -1)"

if [ "$status" != 0 ]; then
  echo '--- test server log ---' >&2
  tail -40 "$TEST_HOME/server.log" >&2
  # THE SUMMARY HAS TO COME LAST. run_tests.sh reports a suite by its final line,
  # and this diagnostic used to be printed after it - so a failing e2e reported
  # the tail of an unrelated log where its counts should have been, and the gate
  # said "1 suite(s) failed" with nothing at all about what. Observed 2026-09-25.
  case "$summary" in
    'passed '*', failed '*) printf '%s\n' "$summary" ;;
    # No summary at all means node died before it could count - a crash, a
    # browser that never launched, an OOM. Say that, rather than letting the
    # last line be whatever happened to be on stdout.
    *) printf 'passed 0, failed 1 (test_e2e.mjs exited %s without reporting counts)\n' "$status" ;;
  esac
fi
exit "$status"
