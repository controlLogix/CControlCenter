---
id: "TM-072"
kind: "task"
status: "open"
created: "2026-09-26T03:07:00.460Z"
board: "controllogix/ccontrolcenter"
title: "Port the settings view to React, whole"
epic: "EP-005"
acceptance: [{"text":"docs/port-parity.json marks this view and every panel, preference and route it owns as ported, each naming its React file","done":false},{"text":"test_port_parity.py is green, so no claimed file is missing from disk","done":false},{"text":"The view's old test_frontend*.sh is deleted in the same commit as its React replacement, and MIGRATED_VIEWS is updated","done":false},{"text":"Every element rendering a reading carries .is-value; no value tweens","done":false},{"text":"No hex literal and no duration literal in the new source, enforced by the existing lint and check-literals","done":false},{"text":"The full gate is green, e2e included, with counts recorded before and after","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T03:15:44.362Z"
session: "pool-tm-072"
---

Parity first: this view is marked `ported` in docs/port-parity.json ONLY when
every panel, stored preference and endpoint it owns works. Not a screenshot
match - a behaviour match.

THE HARD PART HERE: the secret-presence contract must be encoded IN THE TYPE ({present: boolean, value?: never}) so round-tripping a secret is a compile error rather than a review catch

SEQUENCING FACT THAT UNBLOCKS THIS. Porting a view does NOT wait for the Node
API. packages/web can call server.py's existing endpoints through the Vite dev
proxy, and the production bundle is served by whichever server is live. So view
work and the Node port (TM-039/040/041) proceed in parallel rather than in
series - that is the single largest scheduling win available on this board.

The old shell test is deleted in the SAME COMMIT that lands the replacement -
never before, never batched. run_tests.sh gains the view to MIGRATED_VIEWS so
the total assertion count cannot silently drop.