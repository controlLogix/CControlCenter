---
id: "TM-036"
kind: "task"
status: "parked"
created: "2026-09-26T02:03:21.164Z"
board: "controllogix/ccontrolcenter"
title: "Split codesys_panel.py - the client half is a field module, the rest is not"
epic: "EP-002"
acceptance: [{"text":"field/protocols/codesys_client.py contains no ccboard or ccstore import, asserted by a test","done":false},{"text":"The API-side half keeps its endpoints byte-identical, proved against the differ corpus","done":false},{"text":"Existing codesys tests pass unchanged or their replacement covers the same assertions","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "tm/TM-036-split-codesys-panel-py-the-client-half-is-a-fiel"
worktree: "/mnt/c/Dev/agentmux/.bytedesk/worktrees/TM-036-split-codesys-panel-py-the-client-half-is-a-fiel"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T03:08:29.350Z"
session: "pool-tm-036"
dispatched: {"backend":"tmux","run":"tmux:tm-TM-036","session":"pool-tm-036","at":"2026-09-26T03:07:45.720Z"}
parkedReason: "worker exited without closing"
comments: [{"author":"worker:tmux","ts":"2026-09-26T03:08:29.267Z","text":"worker exited without closing"}]
---

Phase 1.1. It is 473 lines and imports ccboard and ccstore, so it cannot move
whole. The client half becomes field/protocols/codesys_client.py; targets,
plcstate, bootapp and journal stay API-side because they read board state.

Budget a day. This was not in the original plan and is the only module in the
set that cannot be moved by renaming it.