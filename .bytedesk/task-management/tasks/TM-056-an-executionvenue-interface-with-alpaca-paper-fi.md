---
id: "TM-056"
kind: "task"
status: "done"
created: "2026-09-26T02:06:16.260Z"
board: "controllogix/ccontrolcenter"
title: "An ExecutionVenue interface, with Alpaca paper first"
epic: "EP-003"
acceptance: [{"text":"An ExecutionVenue interface with an Alpaca paper adapter and an in-process fake; tests never contact a live API","done":true,"at":"2026-09-26T02:11:03.609Z"},{"text":"Intent is journalled and fsync'd BEFORE transmission, proved by a transport side effect that reads the journal off disk at the moment of the call","done":true,"at":"2026-09-26T02:11:05.020Z"},{"text":"Fail-closed: a journal write that raises means the transport is never called, proved by assert_not_called","done":true,"at":"2026-09-26T02:11:06.879Z"},{"text":"The same idempotency key submitted twice does not create two orders","done":true,"at":"2026-09-26T02:11:08.464Z"},{"text":"An unknown outcome exposes NO retry path - not a disabled one, no method at all - asserted over the public surface","done":true,"at":"2026-09-26T02:11:09.955Z"},{"text":"Read-back matches by venue order id, falling back to symbol/side/qty/time window; a mismatch ARMS the kill switch and attempts no automatic cancel","done":true,"at":"2026-09-26T02:11:11.573Z"},{"text":"The kill switch is re-read from disk inside the venue immediately before submission","done":true,"at":"2026-09-26T02:11:12.922Z"}]
evidence: [".bytedesk/task-management/evidence/TM-056.log"]
commits: ["2a1fc2b"]
blockedBy: []
blocks: []
actor: "main"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T02:13:27.716Z"
assignee: "main"
evidenceSources: {".bytedesk/task-management/evidence/TM-056.log":{"source":"/tmp/ev/TM-056.log","sha256":"e15118d32ef04339241e29304f6dc117e5f9bc083298cdfc5f6bf777b5aac9ca","bytes":2049,"at":"2026-09-26T02:13:26.380Z"}}
closed: "2026-09-26T02:13:27.682Z"
---

Phase 5.8. Not a hedge on the Fidelity decision - it is how you get the first
live order right. Free, a real order lifecycle, no ToS exposure, and it exercises
read-back, guardrails, idempotency, the kill switch and the audit record end to
end with no money and no Fidelity contact.

Fidelity then becomes one adapter behind an interface that already has a proven
consumer.

Any method may return NotSupported and the UI renders 'not available from
<provider>' - a missing capability must LOOK missing.