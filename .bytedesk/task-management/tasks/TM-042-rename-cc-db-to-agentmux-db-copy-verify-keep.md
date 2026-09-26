---
id: "TM-042"
kind: "task"
status: "open"
created: "2026-09-26T02:03:32.418Z"
board: "controllogix/ccontrolcenter"
title: "Rename cc.db to agentmux.db, copy-verify-keep"
epic: "EP-002"
acceptance: [{"text":"The migration is copy-verify-keep: open both, use the SQLite backup API, PRAGMA integrity_check, and only on ok rename the original to cc.db.migrated-<date>","done":false},{"text":"The operator's only copy is never deleted","done":false},{"text":"ccstore.py:30 is the single definition that changes; ccstore.py and ccboard.py are NOT renamed","done":false},{"text":"Lands in Phase 1 alongside the store migration so one script handles shape and name together","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "main"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T02:03:32.460Z"
---

Open question 4, answered yes - but the DATA FILE ONLY, not the modules. 'cc' is
the last load-bearing trace of the old name on a path the product CREATES ON
EVERY FRESH INSTALL, and ADR-0017 scoped the rebrand to live surfaces. A file
manufactured on a new machine in 2027 is a live surface.

Do NOT rename ccstore.py or ccboard.py in the same change: about ten files import
them, half those tables are about to retire, and churning every import in the
commit that migrates the data doubles the blast radius of a bad afternoon.