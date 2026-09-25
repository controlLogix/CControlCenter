---
id: "TM-017"
kind: "task"
status: "open"
created: "2026-09-25T16:34:45.378Z"
board: "controllogix/ccontrolcenter"
title: "The SSE slot-exhaustion guard has no automated test"
epic: "EP-002"
acceptance: [{"text":"run_tests.sh or the docs state explicitly that test_stream_slots.sh is an operator command and why it cannot run in the gate, so its absence is not read as an oversight","done":false},{"text":"An automated test exercises the one-stream-per-agent rule against the e2e harness's ephemeral-port dashboard","done":false},{"text":"The test fails if STREAM_SLOTS or stream_superseded is reverted, proven against a base where the bug was present","done":false},{"text":"Repeated page loads across several agents leave every stream available, which is the property the manual suite asserts today","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T16:34:45.444Z"
---

Found 2026-09-25 by cross-checking which suites the gate registers against which exist on disk.

`dashboard/test_stream_slots.sh` exists, is executable, is documented in `README.md:440` and `:529`, and **is not registered in `run_tests.sh`**. It is the only suite in that position; everything else in `dashboard/` is in the gate.

**It is manual-only by design, not by oversight.** It hardcodes `BASE='http://127.0.0.1:8787'` and begins by reading `/api/agents` to get live names, so it needs a running dashboard on the fixed port with real tmux agents attached. None of that is available in the gate, which runs from a throwaway home on an ephemeral port. So this is not a registration bug to fix by adding a line.

**What it means is that a measured bug has no automated guard.** From the suite's own header, and `README.md:525-529` says the same:

> A browser reload opens a fresh EventSource per pane while the previous ones are still established; the server cannot tell a client has gone until it next tries to write. Seven panes over a couple of reloads consumed all sixteen slots, and three panes then sat at HTTP 503 rendering nothing - which looks exactly like a dead agent.

The fix is in `server.py:51` (`STREAM_SLOTS = threading.BoundedSemaphore(16)`) and `:76` (`stream_superseded`, one stream per agent). Nothing in the gate exercises either. A regression would present as panes that render nothing, which is the failure mode hardest to attribute.

This is already on the rewrite's risk register as R13 ("six-connection cap returns"), whose mitigation is a Playwright test counting `text/event-stream` requests under React strict-mode double-mount. That test is the right home for this guard, because Playwright can drive real reloads against the ephemeral-port dashboard the e2e suite already stands up - which is exactly what `test_stream_slots.sh` cannot do.

Until then, record that the guard is manual so nobody assumes the gate covers it.