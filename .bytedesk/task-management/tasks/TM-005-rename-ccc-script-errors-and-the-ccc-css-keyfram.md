---
id: "TM-005"
kind: "task"
status: "done"
created: "2026-09-25T15:19:21.606Z"
board: "controllogix/ccontrolcenter"
title: "Rename CCC_SCRIPT_ERRORS and the ccc-* CSS keyframes"
epic: "EP-002"
acceptance: [{"text":"CCC_SCRIPT_ERRORS is renamed to AGENTMUX_SCRIPT_ERRORS at all four sites: index.html:20, index.html:24, app.js:3883-3884, test_frontend_tabs.sh:555,561","done":true,"at":"2026-09-25T16:21:26.164Z"},{"text":"The listener still appears before the scripts it watches, and test_frontend_tabs.sh still asserts that ordering","done":true,"at":"2026-09-25T16:21:28.053Z"},{"text":"Deliberately breaking a script load still raises the banner","done":true,"at":"2026-09-25T16:21:29.417Z"},{"text":"The ccc-live-pulse and ccc-arrive keyframes are renamed in style.css with no orphaned references","done":true,"at":"2026-09-25T16:21:30.620Z"},{"text":"run_tests.sh is green","done":true,"at":"2026-09-25T16:21:32.199Z"}]
evidence: [".bytedesk/task-management/evidence/TM-005.txt"]
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T16:21:35.058Z"
evidenceSources: {".bytedesk/task-management/evidence/TM-005.txt":{"source":"/tmp/phase0-evidence/TM-005.txt","sha256":"8597a7a450b9b5e236c285224342d7713ec8bc994533308809a39312438cdc77","bytes":1091,"at":"2026-09-25T16:21:23.957Z"}}
assignee: "claude"
closed: "2026-09-25T16:21:34.956Z"
---

Two small, self-contained renames grouped because neither justifies its own commit.

**`window.CCC_SCRIPT_ERRORS`** is a cross-file runtime contract, not a cosmetic string: set at `index.html:20`, pushed to at `:24`, consumed at `app.js:3883-3884`, asserted at `test_frontend_tabs.sh:555,561`. The comment at `index.html:9-19` explains it exists because a script that fails to *load* cannot report its own failure — it is the load-failure banner. A half-rename produces a banner that never fires, which is precisely the failure it was built to catch.

`test_frontend_tabs.sh:555` asserts the listener appears **before** the scripts it watches. Preserve that ordering.

**CSS keyframes** `ccc-live-pulse` and `ccc-arrive` are confined to `style.css` and have no cross-file consumers.