---
id: "TM-050"
kind: "task"
status: "open"
created: "2026-09-26T02:04:44.122Z"
board: "controllogix/ccontrolcenter"
title: "test_netscan.py for the branches test_field_panels.py does not reach"
epic: "EP-002"
acceptance: [{"text":"_parse_arp is tested across Linux ip neigh, Linux arp -an, and Windows arp -a dash-separated MACs","done":false},{"text":"The WSL fallback branch is covered for both answers","done":false},{"text":"check_ports(None) returns a COPY, not the shared default","done":false},{"text":"A raising journal callback does not abort the scan, because netscan.py:352-356 swallows it deliberately and that is load-bearing","done":false},{"text":"Scoped so it does not duplicate test_field_panels.py:392-455, stated in the docstring","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "main"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T02:04:44.191Z"
---

Phase 4.8. test_field_panels.py:392-455 already covers guards, sweep, OUI and
under_wsl, so this is scoped to what it does NOT reach.

The WSL fallback branch is the most consequential untested branch in the module,
and the one netscan.py:186-201 spends fifteen lines justifying.

Note the never-fatal contract is load-bearing and was already violated once:
TM-013 killed whole scans because Path.exists() re-raises EIO out of a function
whose own docstring says 'Never fatal'.