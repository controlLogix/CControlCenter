---
id: "TM-057"
kind: "task"
status: "open"
created: "2026-09-26T02:06:17.722Z"
board: "controllogix/ccontrolcenter"
title: "Credential storage: presence, never value"
epic: "EP-003"
acceptance: [{"text":"Credential Manager via advapi32 and DPAPI via crypt32, both ctypes, no new dependency","done":false},{"text":"describe() returns presence, source and fingerprint, and is STRUCTURALLY incapable of returning the value","done":false},{"text":"A sentinel appears only in the return value of get() - never in a repr, a describe, a serialisation, a log line or an exception message","done":false},{"text":"The module never reads or writes ~/.agentmux/env, asserted by path","done":false},{"text":"On a host with no Credential Manager it SKIPS with a stated reason rather than passing silently","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "main"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T02:06:17.778Z"
---

Phase 5.6. Windows Credential Manager via ctypes to advapi32, preferred over a
raw DPAPI blob because THE OS GIVES A UI TO INSPECT AND REVOKE, and revocability
matters more than blob simplicity. DPAPI is the documented fallback. Both are
ctypes against system DLLs, so no new dependency.

The API key must NEVER go in ~/.agentmux/env - that file is sourced into every
agent pane, which would hand it to every codex and claude worker. That is exactly
the failure check_key_exposure.sh was written after.

The sentinel test is the one that matters: store a known sentinel, drive every
path that could emit it, and grep every response body, repr, serialisation and
exception message.