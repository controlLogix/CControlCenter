---
id: "TM-003"
kind: "task"
status: "done"
created: "2026-09-25T15:19:00.128Z"
board: "controllogix/ccontrolcenter"
title: "Rename the window.CCC JS namespace and the ccc:ready boot event"
epic: "EP-002"
acceptance: [{"text":"window.CCC is renamed to window.AGENTMUX across all 11 source files and 6 test files","done":true,"at":"2026-09-25T16:20:59.715Z"},{"text":"ccc:ready is renamed to agentmux:ready at every emitter and listener","done":true,"at":"2026-09-25T16:21:01.374Z"},{"text":"window.CCCOpenCard is renamed at app.js and kanban.js and its two tests","done":true,"at":"2026-09-25T16:21:02.273Z"},{"text":"The rename and every assertion that references it land in a single commit","done":true,"at":"2026-09-25T16:21:03.451Z"},{"text":"run_tests.sh and the Playwright e2e suite are both green","done":true,"at":"2026-09-25T16:21:04.512Z"},{"text":"Every view and subtab still renders a non-empty panel in a real browser","done":true,"at":"2026-09-25T16:21:06.325Z"}]
evidence: [".bytedesk/task-management/evidence/TM-003.txt"]
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T16:21:08.385Z"
evidenceSources: {".bytedesk/task-management/evidence/TM-003.txt":{"source":"/tmp/phase0-evidence/TM-003.txt","sha256":"238aba11a576a207d355e6a94ec9f1c7484d54ada57a7ce9c6c82bac14bdce17","bytes":1204,"at":"2026-09-25T16:20:56.909Z"}}
assignee: "claude"
closed: "2026-09-25T16:21:08.341Z"
---

The largest of four cross-file runtime contracts, and the one that breaks loudest if half-renamed.

`window.CCC` carries `el`, `getJSON`, `post`, `say`, `registerPanel`, `markAgent` and spans 11 source files plus 6 tests. `ccc:ready` is the boot event 12 source files listen for. `window.CCCOpenCard` is referenced at `app.js:3099,3102` and `kanban.js:143`.

Miss any one end and every view module fails to register — panels render blank with no error, which is exactly the class of failure `CCC_SCRIPT_ERRORS` exists to catch and cannot catch here.

Source files: `app.js`, `agents.js`, `chatter.js`, `codesys.js`, `github.js`, `iiot.js`, `kanban.js`, `mqtt.js`, `netscan.js`, `runs.js`, `teams.js`, `index.html`. Tests asserting on these: `test_frontend_{agents,drawer,kanban,tabs,teams}.sh`, `test_codesys_panel.py:456`, `test_github_panel.py:255,292`, `test_pn_dcp.py:314`, `test_e2e.mjs`.

**Source and assertions land in one commit** — a split commit leaves the gate red for no reason.