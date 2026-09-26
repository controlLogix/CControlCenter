---
id: "TM-066"
kind: "task"
status: "open"
created: "2026-09-26T02:06:34.195Z"
board: "controllogix/ccontrolcenter"
title: "The funnel guard: prevention in the policy file, detection on a timer"
epic: "EP-004"
acceptance: [{"text":"The funnel node attribute is removed in the tailnet policy file, and that is recorded as the actual prevention","done":false},{"text":"Boot refuses on any funnel config for this node, not only one on the API port","done":false},{"text":"A 60 second re-check exits non-zero when a funnel appears after boot, proved by enabling one against a running process","done":false},{"text":"Any serve handler targeting 8788, 8789 or 8790 is a boot failure","done":false},{"text":"From OFF the tailnet, the host answers nothing on 8787-8790","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T03:15:37.739Z"
session: "pool-tm-066"
---

Phase 6.5 and 6.6. Two controls, and only one of them is a control.

PREVENTION: remove the funnel node attribute in the tailnet policy file. A node
without it cannot enable Funnel at all.

DETECTION: at boot, refuse on ANY funnel config for this node - not merely one on
the API port, because Funnel on 443 with a path prefix still reaches the API - and
RE-CHECK ON A 60 SECOND TIMER, exiting non-zero on detection. A funnel enabled at
3pm is exactly the event a boot-only guard sleeps through.

And the Windows services are never exposed: any serve handler targeting 8788,
8789 or 8790 is a BOOT FAILURE, not a warning.