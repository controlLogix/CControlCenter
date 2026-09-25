#!/usr/bin/env bash
# agentmux dashboard smoke test. Run from the repo root inside WSL:
#   bash <(tr -d '\r' < dashboard/smoke.sh)
#
# Read-only except the round-trip section, which creates a throwaway epic/task/
# journal entry in the test dashboard database. Run through run_tests.sh for isolation.
#
# NOTE ON WRITES: every POST here checks its response body. An earlier version
# sent writes to /dev/null and reported them as passing while the server was in
# fact rejecting them - a test that cannot fail is worse than no test.
set -u
BASE="http://127.0.0.1:8787"
# shellcheck source=/dev/null
. dashboard/testlib.sh          # ok/bad/check/check_rc/rc_is/count_msgs, one copy

code() { curl -s -o /dev/null -w '%{http_code}' "$BASE/$1"; }
jpost() { curl -s -X POST -H 'Content-Type: application/json' --data "$2" "$BASE/$1"; }

echo '--- static assets ---'
# index.html is served at / only; it is deliberately not reachable as a path.
# resources.json is a server-side manifest and is NOT served - the browser gets
# its contents via /api/resources, which strips secret_output details.
check '/ serves the page'   200 "$(code '')"
check 'resources.json withheld' 404 "$(code 'resources.json')"
for f in app.js blade.js modes.js style.css themes.json assets/logo-agentmux.svg assets/logo-agentmux-24.svg \
         vendor/xterm.js vendor/addon-fit.js vendor/xterm.css; do
  check "$f" 200 "$(code "$f")"
done

echo '--- readable endpoints ---'
for e in api/agents api/resources api/epics api/journal api/messages api/devices; do
  check "GET $e" 200 "$(code "$e")"
done

echo '--- write-only endpoints reject GET ---'
for e in api/tasks api/status api/delete; do
  check "GET $e" 405 "$(code "$e")"
done
check 'POST api/messages (read-only)' 405 \
  "$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
      --data '{}' "$BASE/api/messages")"

echo '--- mutating-endpoint guards ---'
for e in api/epics api/tasks api/journal api/devices api/status api/delete; do
  # No JSON content type -> 415. This is what forces a CORS preflight, which is
  # the actual CSRF defence for a localhost server.
  check "POST $e no-ctype" 415 "$(curl -s -o /dev/null -w '%{http_code}' \
      -X POST --data '{}' "$BASE/$e")"
  check "POST $e cross-origin" 403 "$(curl -s -o /dev/null -w '%{http_code}' \
      -X POST -H 'Content-Type: application/json' -H 'Origin: https://evil.example' \
      --data '{}' "$BASE/$e")"
  check "POST $e unknown field" 400 "$(curl -s -o /dev/null -w '%{http_code}' \
      -X POST -H 'Content-Type: application/json' --data '{"wat":1}' "$BASE/$e")"
done

echo '--- rejection reasons are specific (Invalid must not collapse to ValueError) ---'
check 'bad status names the field' 'invalid status' \
  "$(jpost api/status '{"kind":"epic","id":1,"status":"bogus"}' \
     | python3 -c 'import json,sys; print(json.load(sys.stdin).get("error",""))')"
check 'bad limit names the bound' 'limit must be between 1 and 1000' \
  "$(curl -s "$BASE/api/journal?limit=0" \
     | python3 -c 'import json,sys; print(json.load(sys.stdin).get("error",""))')"

echo '--- multiplexed stream (one connection for every agent) ---'
# A browser allows ~6 connections per host, and an SSE stream holds one open. With seven
# panes the seventh could never connect and two panes traded places every second. All
# agents now share /api/stream-all, so pane count is no longer capped by the browser.
mux="$(timeout 6 curl -sN "$BASE/api/stream-all?tail=512" 2>/dev/null)"
check 'stream-all returns frames' true "$([ -n "$mux" ] && echo true || echo false)"
# LIVE agents only. A stale entry is an agent whose tmux session is gone; it has no
# log to follow, so the client deliberately opens no stream for it, and comparing
# against the TOTAL made this check fail for a reason with nothing to do with
# multiplexing. That is what happened on 2026-09-22: seven sets of orphaned sidecars
# from a rebooted-away tmux server sat in run/, /api/agents reported seven agents,
# the stream carried none, and four checks here failed. `agentmux reap` removes such
# orphans; this counts correctly whether or not anyone has run it.
agent_count="$(curl -s "$BASE/api/agents" | python3 -c '
import json, sys
print(sum(1 for a in json.load(sys.stdin)["agents"] if a.get("state") != "stale"))')"
named="$(printf '%s' "$mux" | python3 -c '
import json, sys
names = set()
for line in sys.stdin.read().splitlines():
    if line.startswith("data: "):
        try:
            names.add(json.loads(line[6:]).get("agent"))
        except ValueError:
            pass
print(len(names - {None}))
')"
check 'every agent appears on the one connection' "$agent_count" "$named"
check 'frames are tagged with an agent' true   "$(printf '%s' "$mux" | grep -q '"agent"' && echo true || echo false)"
check 'snapshot frames are CRLF-framed' true   "$(printf '%s' "$mux" | grep -q 'event: snapshot' && echo true || echo false)"

echo '--- a sidecar with no tmux session is stale, and does not inflate the live count ---'
# Sidecars outlive their sessions whenever the tmux server goes away without
# `agentmux kill` - a reboot does exactly that. The server must call such an agent
# stale rather than counting it as running. Uses a name no real agent would take, and
# removes it again below.
PHANTOM="${AGENTMUX_HOME:-$HOME/.agentmux}/run/zz-smoke-phantom.cli"
live_before="$(curl -s "$BASE/api/agents" | python3 -c '
import json, sys
print(sum(1 for a in json.load(sys.stdin)["agents"] if a.get("state") != "stale"))')"
printf 'shell\n' > "$PHANTOM"
phantom_json="$(curl -s "$BASE/api/agents" | python3 -c '
import json, sys
rows = {a["name"]: a for a in json.load(sys.stdin)["agents"]}
row = rows.get("zz-smoke-phantom")
print(json.dumps({"present": row is not None,
                  "state": (row or {}).get("state"),
                  "live": sum(1 for a in rows.values() if a.get("state") != "stale")}))')"
rm -f "$PHANTOM"
check 'phantom sidecar is listed'        true    "$(printf '%s' "$phantom_json" | python3 -c 'import json,sys; print(str(json.load(sys.stdin)["present"]).lower())')"
check 'phantom sidecar reads as stale'   stale   "$(printf '%s' "$phantom_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["state"])')"
check 'phantom does not raise live count' "$live_before" "$(printf '%s' "$phantom_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["live"])')"
check 'phantom sidecar cleaned up'       false   "$([ -e "$PHANTOM" ] && echo true || echo false)"

echo '--- path traversal ---'
for p in '../server.py' '..%2fserver.py' 'assets/../../agentmux.sh' 'assets/../server.py'; do
  got="$(code "$p")"
  if [ "$got" = 200 ]; then
    printf '  FAIL  %-36s SERVED\n' "$p"; fail=$((fail + 1))
  else
    printf '  ok    %-36s %s\n' "$p" "$got"; pass=$((pass + 1))
  fi
done

echo '--- themes.json shape ---'
if python3 - <<'PY'
import json, sys, urllib.request
d = json.load(urllib.request.urlopen('http://127.0.0.1:8787/themes.json'))
tok = set(d['tokens'])
bad = [t['id'] for t in d['themes'] if tok - set(t['tokens'])]
print(f"        {len(d['themes'])} themes, default={d['default']}: "
      + ', '.join(t['id'] for t in d['themes']))
if bad:
    print(f"        incomplete token sets: {bad}")
    sys.exit(1)
if d['default'] not in {t['id'] for t in d['themes']}:
    print('        default names a theme that does not exist')
    sys.exit(1)
PY
then
  printf '  ok    %-36s\n' 'every theme declares all tokens'; pass=$((pass + 1))
else
  printf '  FAIL  %-36s\n' 'themes.json is inconsistent'; fail=$((fail + 1))
fi

echo '--- DB round-trip (statuses must match ccstore vocabularies) ---'
eid="$(jpost api/epics '{"title":"smoke epic","jira_key":"SMOKE-1"}' \
       | python3 -c 'import json,sys; print(json.load(sys.stdin).get("id",""))')"
if [ -z "$eid" ]; then
  printf '  FAIL  epic create returned no id\n'; fail=$((fail + 1))
else
  printf '  ok    %-36s id=%s\n' 'epic created' "$eid"; pass=$((pass + 1))
  check 'task created' 'smoke task' \
    "$(jpost api/tasks "{\"epic_id\":$eid,\"title\":\"smoke task\",\"agent\":\"codex\"}" \
       | python3 -c 'import json,sys; print(json.load(sys.stdin).get("title",""))')"
  check 'epic -> in_progress' 'in_progress' \
    "$(jpost api/status "{\"kind\":\"epic\",\"id\":$eid,\"status\":\"in_progress\"}" \
       | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))')"
  check 'epic reads back with its task' 'in_progress 1' \
    "$(curl -s "$BASE/api/epics" | python3 -c "
import json, sys
for e in json.load(sys.stdin)['epics']:
    if e['id'] == $eid:
        print(e['status'], len(e.get('tasks', []))); break
")"
  check 'unknown epic id -> 404' 404 \
    "$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
        --data '{"kind":"epic","id":999999,"status":"done"}' "$BASE/api/status")"

  # Every status the frontend offers must be accepted by the backend. app.js
  # declares EPIC_STATUSES / TASK_STATUSES to build its dropdowns; if those drift
  # from ccstore.py the control silently 400s, which is how `active`/`doing` shipped
  # broken the first time. Assert the whole vocabulary, not one value.
  #
  # The lists are READ FROM THE SERVED app.js rather than repeated here. Copying
  # them made this a test of a third list that could itself go stale - and it did:
  # the board store replaced the old per-table words, app.js kept offering
  # `archived`/`todo`/`cancelled`, and this loop went on asserting the dead
  # vocabulary was fine. Reading what the browser is actually handed is the only
  # version of this check that can detect the drift it was written for.
  statuses_from_app() {
    curl -s "$BASE/app.js" | python3 -c "
import re, sys
src = sys.stdin.read()
m = re.search(r'const $1 = \[(.*?)\];', src, re.S)
print(' '.join(re.findall(r\"'([a-z_]+)'\", m.group(1))) if m else '')
"
  }
  epic_vocab="$(statuses_from_app EPIC_STATUSES)"
  task_vocab="$(statuses_from_app TASK_STATUSES)"
  check 'epic vocabulary is readable from app.js' 'yes' \
    "$([ -n "$epic_vocab" ] && echo yes || echo no)"
  check 'task vocabulary is readable from app.js' 'yes' \
    "$([ -n "$task_vocab" ] && echo yes || echo no)"

  for s in $epic_vocab; do
    check "epic status $s accepted" "$s" \
      "$(jpost api/status "{\"kind\":\"epic\",\"id\":$eid,\"status\":\"$s\"}" \
         | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))')"
  done
  check 'bogus epic status rejected' 'invalid status' \
    "$(jpost api/status "{\"kind\":\"epic\",\"id\":$eid,\"status\":\"doing\"}" \
       | python3 -c 'import json,sys; print(json.load(sys.stdin).get("error",""))')"

  tid="$(jpost api/tasks "{\"epic_id\":$eid,\"title\":\"vocab task\"}" \
         | python3 -c 'import json,sys; print(json.load(sys.stdin).get("id",""))')"
  for s in $task_vocab; do
    check "task status $s accepted" "$s" \
      "$(jpost api/status "{\"kind\":\"task\",\"id\":$tid,\"status\":\"$s\"}" \
         | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))')"
  done

  echo '--- delete, and the cascade ---'
  check 'delete a task' 'True' \
    "$(jpost api/delete "{\"kind\":\"task\",\"id\":$tid}" \
       | python3 -c 'import json,sys; print(json.load(sys.stdin).get("ok",""))')"
  check 'deleting it twice -> 404' 404 \
    "$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
        --data "{\"kind\":\"task\",\"id\":$tid}" "$BASE/api/delete")"
  check 'journal cannot be deleted' 400 \
    "$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
        --data '{"kind":"journal","id":1}' "$BASE/api/delete")"
  # The epic still has its original smoke task, so this proves the cascade runs.
  check 'deleting the epic cascades its tasks' 1 \
    "$(jpost api/delete "{\"kind\":\"epic\",\"id\":$eid}" \
       | python3 -c 'import json,sys; print(json.load(sys.stdin).get("cascaded_tasks",""))')"
  check 'the epic is gone' 0 \
    "$(curl -s "$BASE/api/epics" | python3 -c "
import json, sys
print(sum(1 for e in json.load(sys.stdin)['epics'] if e['id'] == $eid))
")"
fi

# grok finding 1: the store allows an 8192-byte journal body, so the request cap
# must too. The old check used a 13-byte body and so never exercised this.
long_body="$(python3 -c 'print("x" * 4000)')"
check 'long journal body stores (not 413)' 'longbody'   "$(jpost api/journal "{\"kind\":\"note\",\"subject\":\"longbody\",\"body\":\"$long_body\"}"      | python3 -c 'import json,sys; print(json.load(sys.stdin).get("subject",""))')"
check 'oversize journal body still 413' 413   "$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json'       --data "{\"kind\":\"note\",\"subject\":\"toobig\",\"body\":\"$(python3 -c 'print("x" * 12000)')\"}"       "$BASE/api/journal")"

# grok's note: smoke did not cover the MQTT endpoints, so a dropped guard there
# would still have printed 48/48. test_mqtt.py covers them in depth; these two keep
# the guard set honest even if that file is not run.
for e in api/mqtt/publish api/mqtt/subscribe; do
  check "GET $e" 405 "$(code "$e")"
  check "POST $e no-ctype" 415 "$(curl -s -o /dev/null -w '%{http_code}'       -X POST --data '{}' "$BASE/$e")"
done

check 'journal round-trip' 'smoke' \
  "$(jpost api/journal '{"kind":"note","subject":"smoke","body":"from smoke.sh"}' \
     | python3 -c 'import json,sys; print(json.load(sys.stdin).get("subject",""))')"
did="$(jpost api/devices '{"name":"smoke-plc","kind":"plc","address":"10.0.0.5","port":502,"protocol":"modbus-tcp"}' \
       | python3 -c 'import json,sys; print(json.load(sys.stdin).get("id",""))')"
check 'device round-trip' true "$([ -n "$did" ] && echo true || echo false)"
# Clean up after ourselves. Earlier runs had no delete, so each one left a row
# behind and the IIOT view filled with duplicate smoke-plc entries.
check 'device deleted' 'True' \
  "$(jpost api/delete "{\"kind\":\"device\",\"id\":$did}" \
     | python3 -c 'import json,sys; print(json.load(sys.stdin).get("ok",""))')"


echo '--- activity feed ---'
# The feed merges five sources server-side. The thing most worth guarding is the
# TIMESTAMP NORMALISATION: the sources emit three different formats
# (2026-09-23T02:11:57+00:00, 2026-09-22T21:59:46-05:00, 2026-09-22T21:13:08-0500),
# the first two of which are the same instant as the third. A string sort over the raw
# values interleaves them wrongly and the newest line is not at the bottom.
feed="$(curl -s "$BASE/api/feed?limit=50")"
check 'GET api/feed' 200 "$(code 'api/feed')"
check 'feed declares its sources' 'True'   "$(printf '%s' "$feed" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d.get("sources",[])) >= 5)')"
check 'entries are newest-first and comparable' 'True'   "$(printf '%s' "$feed" | python3 -c '
import json,sys
e=[x["at"] for x in json.load(sys.stdin)["entries"] if x["at"]]
print(all(e[i] >= e[i+1] for i in range(len(e)-1)))')"
check 'every timestamp is normalised to UTC' 'True'   "$(printf '%s' "$feed" | python3 -c '
import json,sys
e=json.load(sys.stdin)["entries"]
print(all(x["at"].endswith("+00:00") for x in e if x["at"]))')"
check 'every entry carries the full shape' 'True'   "$(printf '%s' "$feed" | python3 -c '
import json,sys
need={"at","source","severity","who","text","ref"}
print(all(need <= set(x) for x in json.load(sys.stdin)["entries"]))')"
check 'severity is drawn from a closed set' 'True'   "$(printf '%s' "$feed" | python3 -c '
import json,sys
d=json.load(sys.stdin)
ok=set(d["severities"])
print(all(x["severity"] in ok for x in d["entries"]))')"
check 'limit is honoured' 'True'   "$(curl -s "$BASE/api/feed?limit=3" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["entries"]) <= 3)')"
# A silly limit must fall back, not 500 and not allocate.
check 'a bad limit falls back rather than failing' 200 "$(code 'api/feed?limit=999999')"
check 'api/feed rejects POST' 405   "$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json'       --data '{}' "$BASE/api/feed")"

finish
