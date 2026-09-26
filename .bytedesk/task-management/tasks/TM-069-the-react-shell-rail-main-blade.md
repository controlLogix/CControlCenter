---
id: "TM-069"
kind: "task"
status: "open"
created: "2026-09-26T02:27:03.572Z"
board: "controllogix/ccontrolcenter"
title: "The React shell: rail, main, blade"
epic: "EP-005"
acceptance: [{"text":"Vite + React 19 + TypeScript + TanStack Router, with the shell grid and a three-state blade","done":false},{"text":"startMotion() and startField() are mounted once at boot, not per component","done":false},{"text":"A Value component carries .is-value, and its comment says why a tweened reading is a false reading","done":false},{"text":"dangerouslySetInnerHTML is banned by lint, not by convention","done":false},{"text":"No hex literal and no duration literal appears anywhere in packages/web","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T03:19:56.141Z"
session: "pool-tm-069"
---

Plan Phase 3's shell, built on the design system rather than re-deciding it.
CSS grid rail | 1fr | blade; pinned reflows, overlay is fixed with a backdrop.

Nothing measures the viewport - everything uses ResizeObserver on its own
container, and the refit debounces to transitionend rather than per frame.
fitmatrix.js records four earlier attempts that all oscillated, every one
because a measurement taken at the current size fed the choice of the next
size. A pinned blade animating its column would reproduce that exactly.