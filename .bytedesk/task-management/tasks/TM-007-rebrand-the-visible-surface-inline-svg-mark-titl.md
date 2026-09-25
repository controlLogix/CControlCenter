---
id: "TM-007"
kind: "task"
status: "done"
created: "2026-09-25T15:19:45.384Z"
board: "controllogix/ccontrolcenter"
title: "Rebrand the visible surface: inline SVG mark, title, favicon, error strings"
epic: "EP-002"
acceptance: [{"text":"index.html :6 title, :7 favicon href, :40 comment, :42-52 inline mark, :43 aria-label and both tokens on :53 are rebranded","done":true,"at":"2026-09-25T16:21:50.930Z"},{"text":"The :38-41 comment explaining why the mark is inline rather than an img src is rewritten, not deleted","done":true,"at":"2026-09-25T16:21:52.488Z"},{"text":"The logo-ccc*.svg assets are git mv'd to logo-agentmux*.svg and the orphan logo.svg is deleted","done":true,"at":"2026-09-25T16:21:53.866Z"},{"text":"server.py:1209 and :1336 user-visible error strings are updated together with any suite assertion on them","done":true,"at":"2026-09-25T16:21:54.877Z"},{"text":"The /tmp/ccc-server.log path and test_residue.sh:204 change in the same commit","done":true,"at":"2026-09-25T16:21:55.994Z"},{"text":"The favicon renders in a fresh browser profile and the header mark inherits currentColor in both themes","done":true,"at":"2026-09-25T16:21:56.880Z"},{"text":"ccstore.py, ccboard.py and the cc.db filename are deliberately unchanged","done":true,"at":"2026-09-25T16:21:58.462Z"}]
evidence: [".bytedesk/task-management/evidence/TM-007.txt"]
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T16:21:59.988Z"
evidenceSources: {".bytedesk/task-management/evidence/TM-007.txt":{"source":"/tmp/phase0-evidence/TM-007.txt","sha256":"f0ca1e905eb3e354c029c63b8b784b60cd5bb80b89c9373567be1df5101a5c15","bytes":1783,"at":"2026-09-25T16:21:48.684Z"}}
assignee: "claude"
closed: "2026-09-25T16:21:59.957Z"
---

The user-visible half of the rebrand.

**The brand mark is inline SVG at `index.html:42-52`, not an `<img src>`.** The comment at `:38-41` explains why — `currentColor` does not inherit into an `<img>`. It is load-bearing: rewrite it, do not delete it. The four `dashboard/assets/logo-ccc*.svg` files exist **only for the favicon** at `:7`, so swapping those files alone changes nothing visible. The draft plan had this backwards.

Sites: `:6` title, `:7` favicon href, `:40` comment, `:42-52` the mark, `:43` aria-label, `:53` which carries **two** tokens (the brand span plus a nested `<span class="brand-abbr">CCC</span>`, styled separately in style.css), `style.css:2`.

Also **user-visible API error strings** at `server.py:1209,1336` ("Control Center storage unavailable") — grep the suites for them before changing. Plus docstrings in `ccstore.py:1`, `ccboard.py:5,20,301`, `server.py:2,1018`, `seed_queue.py:26,44`, `restart.sh:2`, `run_tests.sh:2`, `smoke.sh:2`, `testlib.sh:2`, `test_warrant.py:6`; and `/tmp/ccc-server.log` which `test_residue.sh:204` rewrites — same commit.

`git mv` the logo assets; delete the orphan pre-rebrand `logo.svg`. `server.py:2390` serves `/assets/*.svg` by pattern, so no allowlist change. Leave `state-*.svg` alone.

**Do not rename** `ccstore.py`, `ccboard.py` or the `cc.db` filename here — internal identifiers across 59 files, and most of that surface retires in Phase 1.5 anyway.