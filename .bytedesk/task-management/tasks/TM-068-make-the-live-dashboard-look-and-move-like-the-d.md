---
id: "TM-068"
kind: "task"
status: "open"
created: "2026-09-26T02:27:01.802Z"
board: "controllogix/ccontrolcenter"
title: "Make the live dashboard look and move like the design system"
epic: "EP-005"
acceptance: [{"text":"style.css consumes the tokens; hex literals, duration literals and ad-hoc radii are gone from it","done":false},{"text":"Both themes still work and the stored theme VALUES are unrenamed, because renaming them resets every operator's theme","done":false},{"text":"Every element rendering a reading carries .is-value and does not transition its value","done":false},{"text":"All nine test_frontend*.sh suites and test_e2e.sh are green, with before/after counts recorded","done":false},{"text":"index.html's script-error banner and its listener-before-scripts ordering still hold","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T03:12:32.326Z"
session: "pool-tm-068"
---

The React rewrite is months of work. This is the visible win on the product
the operator actually opens, and it de-risks the migration by proving the
tokens against a real eight-view app before anything is ported.

A token substitution, NOT a redesign: style.css is 72 KB of a deliberate
identity and the measured finding is that the reference speaks the same
language. Layout, density and structure are unchanged.