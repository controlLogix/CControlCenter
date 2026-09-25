---
id: "TM-004"
kind: "task"
status: "done"
created: "2026-09-25T15:19:10.545Z"
board: "controllogix/ccontrolcenter"
title: "Migrate the 12 ccc.* localStorage keys without wiping operator state"
epic: "EP-002"
acceptance: [{"text":"All 12 ccc.* keys are renamed to agentmux.* in source and in the 4 tests that reference them","done":true,"at":"2026-09-25T16:21:12.648Z"},{"text":"A migrateKey helper runs once at boot and is read-through: read new, else read old, write new, remove old","done":true,"at":"2026-09-25T16:21:14.096Z"},{"text":"A browser carrying pre-existing ccc.* keys keeps its theme, board layout, collapse state and current view after reload — verified manually once","done":true,"at":"2026-09-25T16:21:15.137Z"},{"text":"The theme values cc-dark and cc-light are left unchanged","done":true,"at":"2026-09-25T16:21:17.092Z"},{"text":"A browser with no prior keys starts cleanly with defaults","done":true,"at":"2026-09-25T16:21:18.128Z"},{"text":"run_tests.sh is green","done":true,"at":"2026-09-25T16:21:19.413Z"}]
evidence: [".bytedesk/task-management/evidence/TM-004.txt"]
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T16:21:22.638Z"
evidenceSources: {".bytedesk/task-management/evidence/TM-004.txt":{"source":"/tmp/phase0-evidence/TM-004.txt","sha256":"28b136a90cb9ac8b1f308e6764d0f230a1dcb77f9ebeba6ce37f92969b5754d6","bytes":1630,"at":"2026-09-25T16:21:09.981Z"}}
assignee: "claude"
closed: "2026-09-25T16:21:22.606Z"
---

The most dangerous item in Phase 0, and one the draft plan missed entirely. These are **persisted operator data**, not strings — a naive find-and-replace silently wipes every operator's themes, board layout, collapse state and current view on next load, with no error.

The 12 keys, across `app.js`, `netscan.js`, `runs.js` and 4 tests:
`ccc.theme`, `ccc.importedThemes`, `ccc.boardFree`, `ccc.boardPlacements.v1`, `ccc.authOpen`, `ccc.feed.v1`, `ccc.panePlacement`, `ccc.queueSeenAt`, `ccc.tab.v1`, `ccc.view`, `ccc.netscan.v1`, `ccc.runs.v1`.

Needs a read-through migration, not a rename: one `migrateKey(old, new)` helper run once at boot over all 12 — read new, else read old, write new, remove old.

**The theme *values* `cc-dark` and `cc-light` are NOT renamed.** They are the stored values, not the keys, and renaming them resets every operator's theme even after a correct key migration.