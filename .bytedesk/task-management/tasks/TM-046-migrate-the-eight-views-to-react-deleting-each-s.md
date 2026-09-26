---
id: "TM-046"
kind: "task"
status: "parked"
created: "2026-09-26T02:04:36.589Z"
board: "controllogix/ccontrolcenter"
title: "Migrate the eight views to React, deleting each shell test with its replacement"
epic: "EP-002"
acceptance: [{"text":"Each view's shell test is deleted in the same commit as its React replacement, enforced by MIGRATED_VIEWS rather than by intention","done":false},{"text":"The total assertion count never silently drops across the migration","done":false},{"text":"Settings encodes the secret-presence contract IN THE TYPE, so round-tripping a secret is a compile error rather than a review catch","done":false},{"text":"Board reads from an in-process projection, not tm --json per request, and reconciles on an unknown event kind rather than dropping it","done":false},{"text":"Runs gets real streaming - runs.js:22-23 says outright there is no SSE today - using fs.watch on AGENTMUX_HOME, which is ext4","done":false},{"text":"Status's badge stays honest WHILE HIDDEN, modelled as a store subscription rather than a component effect","done":false},{"text":"GitHub does not widen the write surface: push, merge, force-push and delete stay deliberately absent, recorded as a decision","done":false},{"text":"dangerouslySetInnerHTML is banned by lint, not by discipline","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T03:13:02.634Z"
session: "pool-tm-046"
parkedReason: "Superseded by the per-view cards TM-072 and TM-074 through TM-080, which carry the parity-first requirement in their acceptance. Do not work this card; it would duplicate one of them."
---

Phase 3. Order: Settings, Organization, Board, Runs, Status, GitHub, Terminals,
IIOT - IIOT last because Phase 4 rewrites it, and building the device tree twice
is the waste the ordering exists to avoid.

The nine test_frontend*.sh suites are grep assertions over app.js. They are not
portable, BUT THE BUGS THEY ENCODE ARE. Replace by class: Vitest and RTL for
logic, Playwright for anything about load order, layout or box, and a repo-level
grep test kept in shell for source invariants.

Enforcement is the part that usually fails: a view's old shell test is deleted IN
THE SAME COMMIT that lands its React replacement - never before, never batched.
run_tests.sh gains a MIGRATED_VIEWS list so the total assertion count cannot
silently drop.

style.css is 72 KB of a deliberate identity - Valve-era Steam, flat dark slate,
thin light orange accent used sparingly and never as a fill. It is PORTED TO
DESIGN TOKENS, not redesigned. The rebrand changes the name, not the look.