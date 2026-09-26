---
id: "TM-044"
kind: "task"
status: "open"
created: "2026-09-26T02:03:35.956Z"
board: "controllogix/ccontrolcenter"
title: "The orchestrator chokepoint, and the five boot guards that replace a broken one"
epic: "EP-002"
acceptance: [{"text":"One chokepoint at packages/api/src/orchestrator/exec.ts: absolute binary paths, execFile with argv, shell false, a clean env that DELETES ANTHROPIC_API_KEY, a per-verb Zod schema, a timeout, one journal record per invocation","done":false},{"text":"G1 singleton: flock on AGENTMUX_HOME/api.lock plus the port bind","done":false},{"text":"G2 not impersonating: AGENTMUX_AGENT must be unset or exactly blade","done":false},{"text":"G3 write-surface self-test: the filesystem-write helper is called against every forbidden prefix IN PROCESS before the HTTP server binds, and every one must be refused","done":false},{"text":"G4 allowlist integrity: every exposed verb has an argv schema, every requires_commit entry maps to a card kind, no entry names a forbidden verb","done":false},{"text":"G5 reports and NEVER refuses - with three live claims held by others the API must BOOT, which is the regression test for the broken guard","done":false},{"text":"agentmux claim and release are forbidden outright in any form, especially claim --for, which is impersonation","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T03:13:17.161Z"
session: "pool-tm-044"
---

Phase 2.5. agentmux.sh grants orchestrator authority BY OMISSION - AGENTMUX_AGENT
unset means orchestrator - so a Node process shelling agentmux.sh with an
inherited environment IS the orchestrator, with 'run complete --force' and
'claim --for <agent>' live.

The draft's startup guard was wrong on three counts: claims are observable by
design, the API must never OWN a claim so 'a lock it does not own' is every lock
that exists, and it samples once at boot a value that changes continuously. It
trips on the first dispatch and is silent when it matters. G1-G5 replace it, and
G5 - closest to the original intent - REPORTS rather than refusing.

Identity is the control the draft missed: reads run with AGENTMUX_AGENT=blade, so
an attempt to escalate to dispatch is refused by agentmux.sh ITSELF.