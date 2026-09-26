---
id: "TM-071"
kind: "task"
status: "open"
created: "2026-09-26T02:27:07.517Z"
board: "controllogix/ccontrolcenter"
title: "Scaffold the Node API: node:sqlite, no DDL, loopback only"
epic: "EP-005"
acceptance: [{"text":"Asserts PRAGMA user_version == 2 at boot and refuses otherwise; never creates the database file","done":false},{"text":"Ports ccstore.py's path safety verbatim - a symlinked db is refused, st_nlink != 1 is refused","done":false},{"text":"prestart refuses a node resolving under /mnt/c, which would be the Windows one through interop","done":false},{"text":"Binds 127.0.0.1 only, asserted by a boot test that enumerates listening sockets","done":false},{"text":"One shared route wrapper applies the Zod schema so no handler can opt out of validation","done":false},{"text":"The tmux helper is an argv allowlist permitting display geometry only - send-keys, new-session, kill-session and respawn-pane are refused","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T03:19:59.935Z"
session: "pool-tm-071"
---

Plan Phase 1.0 and 1.2. The skeleton only - no handler is ported until the
differ exists (TM-039).

node:sqlite because the same checkout is opened from Windows and WSL and
better-sqlite3 would need a toolchain and a rebuild per Node minor. Node never
runs DDL because Python owns migrations for the whole strangler, and two schema
owners is how a half-migrated database happens.