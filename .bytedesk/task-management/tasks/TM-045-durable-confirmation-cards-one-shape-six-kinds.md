---
id: "TM-045"
kind: "task"
status: "open"
created: "2026-09-26T02:03:37.413Z"
board: "controllogix/ccontrolcenter"
title: "Durable confirmation cards: one shape, six kinds"
epic: "EP-002"
acceptance: [{"text":"Six kinds share one shape: industrial_write, trade, orchestrator_dispatch, orchestrator_send, board_write, file_write","done":false},{"text":"The hook denies any dangerous call not carrying a one-shot token bound to (sessionId, toolUseId, paramsHash); the card mints nothing itself","done":false},{"text":"A test denies mcp__modbus__write_register with the tool BARE in allowedTools AND permissionMode bypassPermissions","done":false},{"text":"Commit checks in order, each a distinct 4xx: exists, not expired, not decided, kill switch clear, hash matches, phrase matches, session actor equals actor.operator","done":false},{"text":"A deferred card survives the last SSE consumer disconnecting and the operator closing the laptop","done":false},{"text":"readBackAt null means the UI must say 'no current value' rather than showing a stale one","done":false},{"text":"Never a browser dialog, enforced by lint plus a grep test over the BUILT bundle","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T03:15:23.502Z"
session: "pool-tm-045"
---

Phase 2.7. One shape because the audit, expiry, dry-run and did-the-params-change
questions are identical for a PLC write and a trade; the kind-specific part is the
shape of target and dryRun.rendering, and that is data, not a type.

PreToolUse is enforcement; canUseTool is the UI. The SDK documents that an allow
rule or a permissive mode SKIPS canUseTool entirely, so the safety property must
not rest on it.

paramsHash is load-bearing. canUseTool may return updatedInput - if the card could
commit an input other than the one rendered, the dry run is decoration.

The typed phrase is DERIVED, never 'yes', and typing is reserved for the kinds
that cost money or move equipment. Requiring a phrase for a status change trains
the operator to type phrases, which is precisely how the phrase stops being read.