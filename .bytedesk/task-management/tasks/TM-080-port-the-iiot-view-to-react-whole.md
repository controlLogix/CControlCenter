---
id: "TM-080"
kind: "task"
status: "open"
created: "2026-09-26T03:10:59.043Z"
board: "controllogix/ccontrolcenter"
title: "Port the iiot view to React, whole"
epic: "EP-005"
acceptance: [{"text":"docs/port-parity.json marks this view and every panel, preference and route it owns as ported, each naming its React file","done":false},{"text":"test_port_parity.py green - no claimed file missing from disk","done":false},{"text":"The old test_frontend*.sh is deleted in the same commit as the replacement; MIGRATED_VIEWS updated","done":false},{"text":"Every element rendering a reading carries .is-value; no value tweens","done":false},{"text":"No hex or duration literal in the new source","done":false},{"text":"Full gate green, e2e included, counts recorded before and after","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T03:15:53.248Z"
session: "pool-tm-080"
---

Parity first: marked `ported` in docs/port-parity.json ONLY when every panel,
stored preference and endpoint it owns works. A behaviour match, not a
screenshot match.

THE HARD PART: every honesty affordance survives: age authored at the source, three-valued quality, TWO rows for one point seen by two sources, and no retry button RENDERED on an unknown outcome. Mount packages/scene for the 3D topology

SEQUENCING FACT THAT UNBLOCKS THIS. Porting a view does NOT wait for the Node
API. packages/web calls server.py's existing endpoints through the Vite dev
proxy. So view work and the Node port (TM-039/040/041) run in parallel rather
than in series - the largest scheduling win on this board.

The old shell test is deleted in the SAME COMMIT that lands the replacement,
never before and never batched, and run_tests.sh gains the view to
MIGRATED_VIEWS so the assertion count cannot silently drop.