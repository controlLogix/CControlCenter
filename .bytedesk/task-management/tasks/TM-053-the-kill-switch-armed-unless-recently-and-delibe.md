---
id: "TM-053"
kind: "task"
status: "open"
created: "2026-09-26T02:06:10.407Z"
board: "controllogix/ccontrolcenter"
title: "The kill switch: armed unless recently and deliberately disarmed"
epic: "EP-003"
acceptance: [{"text":"Checked INSIDE the broker, on disk, re-read immediately before the click, never cached and never trusted from the API","done":false},{"text":"Disarming requires a typed phrase AND sets an expiry, capped at 60 minutes","done":false},{"text":"Re-arms automatically on expiry, process restart (pid mismatch), selector drift, verification mismatch, any unknown outcome, and any guardrails change","done":false},{"text":"With the API's check stubbed to ALLOW, the broker must still refuse - proved by test_broker_side_check_is_authoritative","done":false},{"text":"allowed() exposes no override parameter, asserted by signature rather than by convention","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "main"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T02:06:10.452Z"
---

Phase 5.5. BUILT AHEAD OF THIS TASK - agentmux-broker/killswitch.py, committed in
d82ddeb. Back-filled so the work is attributable.

'A file that exists at install' is not strong enough. The default is not 'on at
install' - it is ON UNLESS RECENTLY AND DELIBERATELY DISARMED. Walking away from
the desk re-arms it.

allowed() has NO override parameter, deliberately. An override argument is a
thing a caller can pass, and the whole point is that the caller cannot.