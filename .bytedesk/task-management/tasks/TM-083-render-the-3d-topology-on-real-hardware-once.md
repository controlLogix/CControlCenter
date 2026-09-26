---
id: "TM-083"
kind: "task"
status: "open"
created: "2026-09-26T03:12:36.969Z"
board: "controllogix/ccontrolcenter"
title: "Render the 3D topology on real hardware, once"
epic: "EP-005"
acceptance: [{"text":"The topology renders in a real browser on a real GPU, with a screenshot attached as evidence","done":false},{"text":"A confirmed device and an inferred one are distinguishable in that screenshot WITHOUT reading a legend","done":false},{"text":"A conflicted address visibly renders as two linked nodes","done":false},{"text":"The field opacity token is set from looking at it, and its comment records that it was","done":false},{"text":"Selecting a device emits its identity and every origin that contributed to it","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T03:15:56.664Z"
session: "pool-tm-083"
---

packages/scene has 90 tests and every one of them is arithmetic, lifecycle or
teardown. The scene graph has never been drawn.

Headless Chromium falls back to SwiftShader, which the package correctly
refuses via failIfMajorPerformanceCaveat - so the DEGRADE path is thoroughly
covered and the RENDER path is not covered at all. That asymmetry is worth
naming: the tests prove it fails safely, not that it works.

Settle the field opacity in the same pass, while a GPU is available. It sits at
0.28, chosen by palette arithmetic because headless Firefox declines the WebGL
context too. tokens.css's own comment is the acceptance test: if you can read
the background, it is too strong.