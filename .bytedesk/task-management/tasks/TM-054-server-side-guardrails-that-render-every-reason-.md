---
id: "TM-054"
kind: "task"
status: "done"
created: "2026-09-26T02:06:12.108Z"
board: "controllogix/ccontrolcenter"
title: "Server-side guardrails that render every reason, not the first"
epic: "EP-003"
acceptance: [{"text":"Six rules: max notional, max percent of portfolio, max orders per day, allow/denylist, require-limit outside RTH, churn guard","done":true,"at":"2026-09-26T02:10:45.732Z"},{"text":"Each returns pass/fail WITH a reason, and every reason renders","done":true,"at":"2026-09-26T02:10:46.834Z"},{"text":"evaluate() runs every rule; it does not stop at the first failure","done":true,"at":"2026-09-26T02:10:48.098Z"},{"text":"notional() returns None rather than 0 when it cannot be computed, asserted by test","done":true,"at":"2026-09-26T02:10:49.329Z"},{"text":"Guardrails are not overridable from the blade, and changing them re-arms the kill switch","done":true,"at":"2026-09-26T02:10:50.767Z"}]
evidence: [".bytedesk/task-management/evidence/TM-054.log"]
commits: ["d82ddeb"]
blockedBy: []
blocks: []
actor: "main"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T02:13:13.708Z"
assignee: "main"
evidenceSources: {".bytedesk/task-management/evidence/TM-054.log":{"source":"/tmp/ev/TM-054.log","sha256":"dcc15f390bbcc277d3fe63a0dd0af87867cc50bb11cdc446180ab153c8d3b464","bytes":2246,"at":"2026-09-26T02:13:12.296Z"}}
closed: "2026-09-26T02:13:13.670Z"
---

Phase 5.4. BUILT AHEAD OF THIS TASK - agentmux-broker/guardrails.py, committed in
d82ddeb. Back-filled so the work is attributable.

Configured in a file and NOT overridable from the blade. evaluate() runs EVERY
rule rather than short-circuiting, because an operator who fixes the first
complaint and resubmits only to hit the second learns to stop reading them.

notional() returns None, never 0. A missing number that renders as zero passes a
max-notional check silently.