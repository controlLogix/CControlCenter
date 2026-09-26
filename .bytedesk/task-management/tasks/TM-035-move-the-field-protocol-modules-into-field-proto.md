---
id: "TM-035"
kind: "task"
status: "in_progress"
created: "2026-09-26T02:03:19.745Z"
board: "controllogix/ccontrolcenter"
title: "Move the field protocol modules into field/protocols/"
epic: "EP-002"
acceptance: [{"text":"Every protocol module lives in field/protocols/ and the single sys.path line is the only thing that followed them","done":false},{"text":"No module exists in two places, asserted by a test rather than by inspection","done":false},{"text":"The full gate is green before and after, and the move is its own commit","done":false},{"text":"server.py imports them through the same path, unchanged in behaviour","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T03:07:08.094Z"
session: "pool-tm-035"
---

Phase 1.1b. The shell already imports them from dashboard/ via one sys.path line
(TM-018), so this is now a pure rename with a green gate either side.

The order was deliberately reversed: doing the move first churns ~13 test files -
test_enip.py:16 is a bare 'import enip' relying on Python putting the script's own
directory on sys.path - for no functional gain while the sidecar does not exist.

The invariant that matters is that there is never a second copy. Two copies drift
within a week, and the differ then compares a module against its own stale twin.