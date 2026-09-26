---
id: "TM-051"
kind: "task"
status: "open"
created: "2026-09-26T02:04:46.271Z"
board: "controllogix/ccontrolcenter"
title: "Resolve the EP and ADR key collisions before the store migration"
epic: "EP-002"
acceptance: [{"text":"Every EP and ADR key means exactly one thing across cc.db, the task store and the plan text","done":false},{"text":"The plan's by-number citations are corrected to whatever the resolution decides, or the keys are moved - but not left disagreeing","done":false},{"text":"activeEpic is resolved explicitly: cc.db says EP-023 and config.json says EP-001, and neither is allowed to silently win","done":false},{"text":"The re-key is a pure function with an exact inverse, so it is mechanically reversible","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "main"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T02:04:46.340Z"
---

Section 10, item 2. Migration without re-keying silently merges unrelated work,
which is the one failure this store exists to prevent.

EP-001 means two different things: cc.db says 'Controls Control Center rebrand',
bytedesk says 'Configurable agents, teams...' - which cc.db records SEPARATELY as
EP-015, done. ADR-0001 collides too.

And the plan's own ADR numbering has already drifted from the board's: the plan
calls ADR-0024 'Sidecar dependency policy: vendored wheels' while the board's
ADR-0024 is 'WSL bridge: mirrored networking'; the plan calls ADR-0025 'tax lots'
while the board's is 'Sequencing'. Both of those are cited by number in the plan
text, so this has to be resolved before anyone follows a reference.