---
id: "TM-013"
kind: "task"
status: "done"
created: "2026-09-25T15:41:06.257Z"
board: "controllogix/ccontrolcenter"
title: "BUG: the netscan e2e test fails ~60% of runs, and reports a bare \"OSError\""
epic: "EP-002"
acceptance: [{"text":"netscan.py records the exception message alongside the class name, bounded, with the traceback going to the server log","done":true,"at":"2026-09-25T16:10:04.852Z"},{"text":"A failed scan's status line names an actionable cause rather than a bare class name","done":true,"at":"2026-09-25T16:10:08.580Z"},{"text":"The underlying OSError is identified from the captured detail and either fixed or explained with evidence","done":true,"at":"2026-09-25T16:10:15.287Z"},{"text":"test_e2e.sh passes 10 consecutive runs with zero scanner failures","done":true,"at":"2026-09-25T16:19:18.716Z"},{"text":"A regression test covers whatever the root cause turns out to be","done":true,"at":"2026-09-25T16:10:18.706Z"}]
evidence: [".bytedesk\\task-management\\evidence\\TM-013-1790352178655.log"]
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T16:19:29.614Z"
evidenceSources: {".bytedesk\\task-management\\evidence\\TM-013-1790352178655.log":{"source":null,"sha256":"66d4fd594577ee4740b2796aa8f364ac606958f160f63f431d5a194a588d8217","bytes":2581,"at":"2026-09-25T16:02:58.656Z"}}
assignee: "claude"
closed: "2026-09-25T16:19:29.580Z"
---

Found taking the Phase 0 baseline, 2026-09-25. Pre-existing. One of the two suites that made the baseline gate report "2 suite(s) failed".

**The flake.** `test_e2e.mjs:331` "the scanner finds a host on a port it was told to probe" scans `127.0.0.1/32` for the dashboard's own ephemeral port. Measured across 6 runs of `test_e2e.sh`: **3 failed, 3 passed.** It fails more often than it passes, which makes every phase's "run_tests.sh reports all suites passed" acceptance unachievable by luck rather than correctness.

Failure state string:
`ERROR - 127.0.0.1/32 - 0 host(s) answered of 1 scanned - finished 10:36:05 AM - OSError`

**Not reproducible in isolation.** A standalone harness driving `netscan.Scanner` against a real listener on 127.0.0.1 ran 12/12 clean (`state=done, hosts=1`). So it is load- or environment-dependent: it only appears with the dashboard server and headless Firefox running alongside. `ulimit -n` in this WSL is 1024, making fd exhaustion a live hypothesis, though `WORKERS=64` is never reached for a single-host /32.

**The reportability defect, which is why the cause is still a hypothesis.** `netscan.py:402` recorded only `f"{type(err).__name__}"`, and `netscan.js:196` pushes that straight into the operator's status line. A bare "OSError" is a class name, not a diagnosis - nobody can act on it, and it is exactly what the module's own `neighbour_table` comment complains about elsewhere ("the panel said nothing about why").

Already fixed in this task: the handler now records class plus message, bounded to 200 chars, with the traceback to the server log. Root cause is being chased with that detail in hand.