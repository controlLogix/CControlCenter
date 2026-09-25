#!/usr/bin/env bash
# Re-capture docs/images/*.png against a real dashboard.
#
#     bash <(tr -d '\r' < dashboard/capture_docs.sh)
#
# An OPERATOR command, deliberately not in run_tests.sh: five PNGs is ~450 KB of
# binary churn, and a gate that rewrites images on every run poisons the history.
#
# Run it AFTER the rebrand commits land. Run it before, and the new screenshots
# bake the old name straight back in.
#
# The server, the seeded home and the Playwright discovery are the same ones
# test_e2e.sh uses - deliberately, so a screenshot shows what the e2e suite
# asserts on rather than some other configuration that happens to render.
set -u
[ -f dashboard/server.py ] || { echo 'run this from the agentmux repo root' >&2; exit 2; }

if ! command -v node >/dev/null 2>&1; then
  cap_node_dir=$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1 || true)
  [ -z "$cap_node_dir" ] || export PATH="$cap_node_dir:$PATH"
fi
if ! command -v node >/dev/null 2>&1; then
  echo 'capture_docs: node is not on PATH' >&2
  exit 2
fi

# Identical to test_e2e.sh's discovery, and for the same reason: an npx cache can
# hold a WINDOWS playwright - this repo lives on /mnt/c - whose firefox binary
# cannot be launched from WSL. ~/pw is the linux install; prefer it.
find_playwright() {
  if [ -n "${PLAYWRIGHT_DIR:-}" ] && [ -d "$PLAYWRIGHT_DIR" ]; then
    printf '%s' "$PLAYWRIGHT_DIR"; return 0
  fi
  if [ -d "$HOME/pw/node_modules/playwright" ]; then
    printf '%s' "$HOME/pw/node_modules/playwright"; return 0
  fi
  local cache found
  for cache in "$HOME/.npm/_npx" "${LOCALAPPDATA:-}/npm-cache/_npx"; do
    [ -d "$cache" ] || continue
    found=$(find "$cache" -maxdepth 3 -type d -name playwright 2>/dev/null | head -1)
    if [ -n "$found" ]; then printf '%s' "$found"; return 0; fi
  done
  return 1
}

PW=$(find_playwright) || {
  echo 'capture_docs: no Playwright installation found.' >&2
  echo '  mkdir -p ~/pw && cd ~/pw && npm init -y && npm install playwright' >&2
  echo '  npx playwright install firefox        # the LINUX browser' >&2
  exit 2
}
PW=${PW//\\//}
echo "playwright: $PW"

CAP_HOME=$(mktemp -d) || exit 2
SERVER_PID=""
BROKER_PID=""
cleanup() {
  local status=$?
  trap - EXIT
  [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null
  [ -n "$BROKER_PID" ] && kill "$BROKER_PID" 2>/dev/null
  rm -rf "$CAP_HOME"
  exit "$status"
}
trap cleanup EXIT INT TERM

free_port() {
  python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'
}
PORT=$(free_port)
BROKER_PORT=$(free_port)
echo "dashboard: 127.0.0.1:$PORT   home: $CAP_HOME"

# Seed a run, so the Runs screenshot is of a populated view rather than an empty
# state. Same shape as test_e2e.sh's seed: one run waiting on the operator, one
# still in flight, so the picture shows both.
AGENTMUX_HOME="$CAP_HOME" python3 - <<'SEEDRUN'
import sys
sys.path.insert(0, 'taskmgmt')
import run
rid = "d0c001"   # six HEX chars: run.valid_run rejects anything else
run.run_dir(rid).mkdir(parents=True, exist_ok=True)
run.append_event(rid, {"event": "start", "by": "orchestrator",
                       "base": "0" * 40,
                       "detail": "rebrand: port the frontend shell"})
for i in (1, 2):
    job = f"{rid}/{i}"
    run.append_event(rid, {"event": "assign", "job": job, "by": "orchestrator",
                           "worker": "agentmux-frontend-dev",
                           "reviewer": "agentmux-frontend-reviewer", "task": "TM-003"})
    run.append_event(rid, {"event": "submit", "job": job, "by": "agentmux-frontend-dev",
                           "files": ["dashboard/app.js"]})
    run.append_event(rid, {"event": "verdict", "job": job,
                           "by": "agentmux-frontend-reviewer",
                           "result": "pass", "attempt": 1, "detail": "ran it"})
rid2 = "d0c002"
run.run_dir(rid2).mkdir(parents=True, exist_ok=True)
run.append_event(rid2, {"event": "start", "by": "orchestrator",
                        "detail": "rebrand: re-capture the documentation images"})
run.append_event(rid2, {"event": "assign", "job": f"{rid2}/1", "by": "orchestrator",
                        "worker": "agentmux-frontend-dev",
                        "reviewer": "agentmux-frontend-reviewer"})
run.append_event(rid2, {"event": "submit", "job": f"{rid2}/1",
                        "by": "agentmux-frontend-dev", "files": ["docs/images/board.png"]})
SEEDRUN

AGENTMUX_HOME="$CAP_HOME" python3 dashboard/server.py --port "$PORT" >"$CAP_HOME/server.log" 2>&1 &
SERVER_PID=$!
python3 dashboard/stub_broker.py --port "$BROKER_PORT" --quiet >"$CAP_HOME/broker.log" 2>&1 &
BROKER_PID=$!

for _ in $(seq 1 60); do
  curl -fsS -o /dev/null "http://127.0.0.1:$PORT/" && break
  sleep 0.25
done
if ! curl -fsS -o /dev/null "http://127.0.0.1:$PORT/"; then
  echo '  FAIL  the capture dashboard never came up' >&2
  cat "$CAP_HOME/server.log" >&2
  exit 1
fi

# A couple of board cards, so the Board screenshot is not an empty column set.
CAP_PORT="$PORT" AGENTMUX_HOME="$CAP_HOME" python3 - <<'SEEDBOARD'
import json, os, sys, urllib.error, urllib.request

base = "http://127.0.0.1:" + os.environ["CAP_PORT"]

def call(path, payload=None):
    if payload is None:
        req = urllib.request.Request(base + path)
    else:
        req = urllib.request.Request(base + path, method="POST",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as err:
        # A screenshot of an empty board is exactly what this seed exists to
        # prevent, so say why rather than shrugging.
        detail = err.read().decode("utf-8", "replace")[:300]
        print(f"  SEED FAILED {path}: HTTP {err.code} {detail}", file=sys.stderr)
    except Exception as err:
        print(f"  SEED FAILED {path}: {err}", file=sys.stderr)
    return None

# ccboard.create enforces the same gates as the CLI: a card needs acceptance
# criteria at creation. test_e2e.mjs:639 uses this exact payload shape.
epic = call("/api/board/create", {
    "kind": "epic", "title": "agentmux rebrand",
    "body": "Live surfaces only: the name changes, the look does not.",
    "acceptance": ["no brand residue outside the documented retentions"],
    "actor": "docs"})
epic_key = (epic or {}).get("key")

CARDS = [
    # Not "done": the board correctly refuses to close a card with no ticked
    # acceptance and no evidence, and a seed should not fight its own gates.
    ("Rename the window.CCC namespace", "in_progress",
     "79 replacements across 20 files."),
    ("Migrate the remembered-state keys", "blocked",
     "12 localStorage keys, carried across rather than renamed."),
    ("Re-capture the documentation images", "open",
     "The mark is rendered, so a text edit cannot fix these."),
]
for title, status, body in CARDS:
    payload = {"kind": "task", "title": title, "body": body,
               "acceptance": ["verified against the gate"], "actor": "docs"}
    if epic_key:
        payload["epic"] = epic_key
    task = call("/api/board/create", payload)
    key = (task or {}).get("key")
    if key and status != "open":
        # server.py:1410 - target() reads "id", not "key".
        call("/api/board/status", {"id": key, "status": status, "actor": "docs"})
SEEDBOARD

CAP_PORT="$PORT" AGENTMUX_HOME="$CAP_HOME" node dashboard/capture_docs.mjs \
  "http://127.0.0.1:$PORT" "$PW" "${1:-docs/images}"
status=$?
if [ "$status" != 0 ]; then
  echo '--- capture server log ---' >&2
  tail -30 "$CAP_HOME/server.log" >&2
fi
exit "$status"
