---
id: "TM-057"
kind: "task"
status: "done"
created: "2026-09-26T02:06:17.722Z"
board: "controllogix/ccontrolcenter"
title: "Credential storage: presence, never value"
epic: "EP-003"
acceptance: [{"text":"Credential Manager via advapi32 and DPAPI via crypt32, both ctypes, no new dependency","done":true,"at":"2026-09-26T02:11:18.795Z"},{"text":"describe() returns presence, source and fingerprint, and is STRUCTURALLY incapable of returning the value","done":true,"at":"2026-09-26T02:11:20.190Z"},{"text":"A sentinel appears only in the return value of get() - never in a repr, a describe, a serialisation, a log line or an exception message","done":true,"at":"2026-09-26T02:11:21.549Z"},{"text":"The module never reads or writes ~/.agentmux/env, asserted by path","done":true,"at":"2026-09-26T02:11:22.867Z"},{"text":"On a host with no Credential Manager it SKIPS with a stated reason rather than passing silently","done":true,"at":"2026-09-26T02:11:24.189Z"}]
evidence: [".bytedesk/task-management/evidence/TM-057.log"]
commits: ["2a1fc2b"]
blockedBy: []
blocks: []
actor: "main"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T02:13:33.627Z"
assignee: "main"
evidenceSources: {".bytedesk/task-management/evidence/TM-057.log":{"source":"/tmp/ev/TM-057.log","sha256":"0db283f931ad4c969b304291c6d0651943e69473b1ef0c08b1151086d87b9eca","bytes":2389,"at":"2026-09-26T02:13:31.116Z"}}
closed: "2026-09-26T02:13:33.383Z"
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