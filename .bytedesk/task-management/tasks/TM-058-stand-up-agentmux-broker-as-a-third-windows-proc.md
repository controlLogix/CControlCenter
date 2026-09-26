---
id: "TM-058"
kind: "task"
status: "open"
created: "2026-09-26T02:06:19.643Z"
board: "controllogix/ccontrolcenter"
title: "Stand up agentmux-broker as a third Windows process"
epic: "EP-003"
acceptance: [{"text":"A separate process on loopback only, with its own shared secret, asserted by a boot test that enumerates listening sockets","done":false},{"text":"Restarting the broker does not interrupt field polling, and vice versa","done":false},{"text":"The kill switch can mean 'stop this process', not merely 'refuse this call'","done":false},{"text":"No broker artifact is written anywhere inside the repo","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T03:15:28.860Z"
session: "pool-tm-058"
---

Phase 5.1. NOT in the field sidecar: the process that can write to a PLC must not
also be the process that can spend money.

Four reasons. Blast radius - Chromium rendering a broker site plus third-party
assets in the same tree as the CIP write path is an unforced error. Independent
lifecycles - restarting the browser session must not stop field polling while
someone is watching a line. Credential scope. And a kill switch that can mean
'stop the process'.

Windows rather than WSL despite the vendored Linux Chromium (untracked scratch,
deleted): DPAPI is Windows, 2FA needs a human at a real window and a headed
Chromium on Windows is a native window on the desktop the operator is sitting at,
and the profile stays on NTFS rather than 9p.