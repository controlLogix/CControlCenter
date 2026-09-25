---
id: "TM-012"
kind: "task"
status: "done"
created: "2026-09-25T15:29:44.185Z"
board: "controllogix/ccontrolcenter"
title: "BUG: two frontend suites miss the nvm node discovery their 7 siblings have"
epic: "EP-002"
acceptance: [{"text":"test_frontend_post.sh carries the same nvm discovery block as its 7 siblings and reports passed 1, failed 0 rather than exiting 127","done":true,"at":"2026-09-25T16:00:24.478Z"},{"text":"test_frontend.sh finds node and actually runs node --check app.js, rather than printing the skip note","done":true,"at":"2026-09-25T16:00:49.182Z"},{"text":"A deliberate syntax error in app.js makes test_frontend.sh FAIL, proving the parse check now runs","done":true,"at":"2026-09-25T16:00:53.019Z"},{"text":"All 9 test_frontend*.sh suites report a passed/failed line in the gate output, with none silently skipping","done":true,"at":"2026-09-25T16:00:57.111Z"},{"text":"run_tests.sh reports all suites passed from an ext4 clone","done":true,"at":"2026-09-25T16:09:39.475Z"}]
evidence: [".bytedesk\\task-management\\evidence\\TM-012-1790352010578.log"]
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T16:09:55.616Z"
evidenceSources: {".bytedesk\\task-management\\evidence\\TM-012-1790352010578.log":{"source":null,"sha256":"a88eaddd8da214254442d48d4b2a54a51927938a5fe99b6ec26c8a4b193bec05","bytes":2158,"at":"2026-09-25T16:00:10.579Z"}}
assignee: "claude"
closed: "2026-09-25T16:09:55.593Z"
---

Found while taking the Phase 0 baseline on 2026-09-25. Pre-existing, not introduced by the rewrite.

On this host `command -v node` returns nothing in WSL — nvm's v24.21.0 is installed but never sourced. Seven of the nine `test_frontend*.sh` carry a 4-line discovery block for exactly this:

```sh
if ! command -v node >/dev/null 2>&1; then
  board_node_dir=$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1 || true)
  [ -z "$board_node_dir" ] || export PATH="$board_node_dir:$PATH"
fi
```

Two do not, and they fail differently:

**1. `test_frontend_post.sh` — hard failure.** `set -euo pipefail` then a bare `node` heredoc at line 3. Baseline output: `/dev/fd/19: line 3: node: command not found`. Exits 127 with no "passed N, failed 0" line, so `run_tests.sh:182` (`0:*"failed 0"`) correctly counts it as a failed suite. The whole post-error-shape suite contributes zero assertions.

**2. `test_frontend.sh:129-132` — silent skip, which is worse.** It guards with `if command -v node`, prints "(node not on PATH; run under bash -ic for nvm to parse-check app.js)", and **still reports "passed 12, failed 0"**. So the gate goes green while the `node --check app.js` parse check never runs. That is precisely the failure mode `test_e2e.sh:19` warns about: "a test that silently passes without a browser is worse than no browser test."

This matters now because Phase 0 rewrites `app.js` heavily, and the parse check is the cheapest guard against shipping a syntax error.

Related: TM-010 pins `AGENTMUX_NODE` for the API. This is the same root cause in the test layer.