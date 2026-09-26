---
id: "TM-038"
kind: "task"
status: "open"
created: "2026-09-26T02:03:24.803Z"
board: "controllogix/ccontrolcenter"
title: "Scaffold the Node API, and never let it run DDL"
epic: "EP-002"
acceptance: [{"text":"The API boots, asserts user_version equals 2, and refuses otherwise rather than migrating","done":false},{"text":"A test proves the API never issues DDL, by intercepting the statement rather than by inspection","done":false},{"text":"ccstore.py path safety is ported verbatim: a symlink cc.db is refused, st_nlink not equal to 1 is refused","done":false},{"text":"stream_superseded and the BoundedSemaphore(16) rule are ported, with test_stream_slots.py's assertions passing against the Node implementation","done":false},{"text":"prestart refuses a node resolved under /mnt/c","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "main"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T02:03:24.849Z"
---

Phase 1.2. Fastify 5, Zod, TS strict, npm workspaces. SQLite via node:sqlite
(built in) - no native build, no node-gyp, no ABI mismatch when the same
checkout is opened from both OSes. better-sqlite3 was rejected: faster, but needs
a toolchain and a rebuild per Node minor, which is the exact dependency posture
vendor/README.md exists to avoid.

Three rules while Python and tm are concurrent writers: Node never runs DDL
(Python owns migrations for the whole strangler), Node never creates the file,
one connection with short transactions and IMMEDIATE for writes.

tmux is execFile with an argv array and shell false. SSE frame format stays
'data: base64' byte-identical.