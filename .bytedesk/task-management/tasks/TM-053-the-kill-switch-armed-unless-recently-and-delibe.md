---
id: "TM-053"
kind: "task"
status: "done"
created: "2026-09-26T02:06:10.407Z"
board: "controllogix/ccontrolcenter"
title: "The kill switch: armed unless recently and deliberately disarmed"
epic: "EP-003"
acceptance: [{"text":"Checked INSIDE the broker, on disk, re-read immediately before the click, never cached and never trusted from the API","done":true,"at":"2026-09-26T02:10:34.480Z"},{"text":"Disarming requires a typed phrase AND sets an expiry, capped at 60 minutes","done":true,"at":"2026-09-26T02:10:36.397Z"},{"text":"Re-arms automatically on expiry, process restart (pid mismatch), selector drift, verification mismatch, any unknown outcome, and any guardrails change","done":true,"at":"2026-09-26T02:10:38.441Z"},{"text":"With the API's check stubbed to ALLOW, the broker must still refuse - proved by test_broker_side_check_is_authoritative","done":true,"at":"2026-09-26T02:10:40.973Z"},{"text":"allowed() exposes no override parameter, asserted by signature rather than by convention","done":true,"at":"2026-09-26T02:10:42.300Z"}]
evidence: [".bytedesk/task-management/evidence/TM-053.log"]
commits: ["d82ddeb"]
blockedBy: []
blocks: []
actor: "main"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T02:13:09.106Z"
assignee: "main"
evidenceSources: {".bytedesk/task-management/evidence/TM-053.log":{"source":"/tmp/ev/TM-053.log","sha256":"cc4316b3a9e2bd5618dccc1b205789ca1059e9d298a5ecdb643a955edb0aa68b","bytes":1674,"at":"2026-09-26T02:13:07.426Z"}}
closed: "2026-09-26T02:13:09.051Z"
---

Phase 5.5. BUILT AHEAD OF THIS TASK - agentmux-broker/killswitch.py, committed in
d82ddeb. Back-filled so the work is attributable.

'A file that exists at install' is not strong enough. The default is not 'on at
install' - it is ON UNLESS RECENTLY AND DELIBERATELY DISARMED. Walking away from
the desk re-arms it.

allowed() has NO override parameter, deliberately. An override argument is a
thing a caller can pass, and the whole point is that the caller cannot.