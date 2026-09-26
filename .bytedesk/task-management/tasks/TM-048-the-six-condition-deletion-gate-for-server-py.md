---
id: "TM-048"
kind: "task"
status: "open"
created: "2026-09-26T02:04:39.948Z"
board: "controllogix/ccontrolcenter"
title: "The six-condition deletion gate for server.py"
epic: "EP-002"
acceptance: [{"text":"Every view has a React implementation in the production bundle and all nine shell tests are deleted alongside their replacements","done":false},{"text":"The differ has been green over the recorded corpus for FOURTEEN consecutive days of real use - not a week, which contains no monthly cron and may contain no weekend idle","done":false},{"text":"coordination.py's POST to 127.0.0.1:8787 succeeds against the Node API, verified by running the real CLI from WSL and asserting the row lands","done":false},{"text":"Every 8787 hardcode is inventoried and either working or retired - 40 code hits","done":false},{"text":"The PROTOCOL python tests still pass against the sidecar; only the HTTP-layer tests retire","done":false},{"text":"A tagged commit and a dashboard/ archive branch exist before the deletion","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "main"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T02:04:39.992Z"
---

Phase 3. All six, not 'when the last view is migrated'. A half-deleted dispatcher
is worse than either end state, so this is one commit and one PR with the differ
report attached.

ccstore.py, ccboard.py and cc.db do NOT die with it - only the board tables
retire. Twelve of the forty board ops MOVE and stay on cc.db: agents, teams,
codesys and chatter. Any later work assuming they retire is wrong.