---
id: "TM-064"
kind: "task"
status: "open"
created: "2026-09-26T02:06:30.631Z"
board: "controllogix/ccontrolcenter"
title: "Extend allowed_origins() for serve without losing the reasoning"
epic: "EP-004"
acceptance: [{"text":"An explicit three-entry allowlist whose third element, serveOrigin, is resolved AT BOOT from the local Tailscale daemon and NEVER from the request","done":false},{"text":"serveOrigin is absent when serve is unconfigured","done":false},{"text":"The doc-comment's reasoning is carried forward in prose, not just its code, and says why this is an extension rather than a weakening","done":false},{"text":"A test proves a forged Origin is still rejected","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "main"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T02:06:30.671Z"
---

Phase 6.3, and the thing most likely to go wrong in this epic.

Over serve the browser's Origin is https://agentmux.<tailnet>.ts.net - a different
scheme, host AND port - so the existing port-derived guard returns the wrong
answer and EVERY mutating request from the phone is rejected as a forbidden
origin.

Someone will read that as the guard being wrong and delete it. The doc-comment's
actual point is 'derive the guard from what the server really is', and what the
server really is now has TWO FACES. Losing that reasoning would be the worst
outcome of this phase.