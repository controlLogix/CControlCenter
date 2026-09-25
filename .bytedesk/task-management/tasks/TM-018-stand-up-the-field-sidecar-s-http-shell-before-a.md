---
id: "TM-018"
kind: "task"
status: "done"
created: "2026-09-25T16:40:26.864Z"
board: "controllogix/ccontrolcenter"
title: "Stand up the field sidecar's HTTP shell, before any write route exists"
epic: "EP-002"
acceptance: [{"text":"field/app.py boots, binds 127.0.0.1 only, and refuses a non-loopback bind with a message naming why","done":true,"at":"2026-09-25T16:53:07.705Z"},{"text":"A request without the shared secret gets a bodyless 401; a wrong or truncated key is refused by constant-time comparison","done":true,"at":"2026-09-25T16:53:08.687Z"},{"text":"POST is refused even with a valid key, and authorization is checked before the method so an unauthenticated caller learns nothing","done":true,"at":"2026-09-25T16:53:09.864Z"},{"text":"No route names a CIP service, class, instance or attribute, proven by inspecting code rather than file text","done":true,"at":"2026-09-25T16:53:11.234Z"},{"text":"That raw-CIP assertion is shown to fail when such a route is injected","done":true,"at":"2026-09-25T16:53:12.588Z"},{"text":"/health reports which protocol modules loaded and the exact error for any that did not, and a missing one does not fail boot","done":true,"at":"2026-09-25T16:53:13.450Z"},{"text":"test_field_sidecar.py is registered in run_tests.sh and the full gate is green","done":true,"at":"2026-09-25T16:53:14.503Z"}]
evidence: [".bytedesk/task-management/evidence/TM-018-tm018.txt"]
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T16:53:15.853Z"
evidenceSources: {".bytedesk/task-management/evidence/TM-018-tm018.txt":{"source":"/mnt/c/Users/Nick/AppData/Local/Temp/claude/C--Dev-agentmux/5748a917-ba3c-4a23-9c48-424b6c04104f/scratchpad/tm018.txt","sha256":"c08c8f6d1a25d8b3ee2142ce74dc1776d3e110704cee48558e0ccb321a526114","bytes":3291,"at":"2026-09-25T16:53:05.258Z"}}
assignee: "claude"
closed: "2026-09-25T16:53:15.822Z"
---

Phase 1.1, first increment. `field/app.py` plus `dashboard/test_field_sidecar.py`.

**Additive, not a move.** The plan's 1.1 says "two consumers, one library": this imports the protocol modules from `dashboard/` and `server.py` keeps importing them exactly as it does today. A `git mv` into `field/protocols/` would churn ~13 test files — `test_enip.py:16` is a bare `import enip` relying on the script's own directory — for no functional gain while the sidecar does not exist yet. One `sys.path` line follows the modules when they do move.

**The posture is asserted now, deliberately, because a write route added later inherits whatever is already here.**

- **Shared secret** in `X-AgentMux-Field-Key`, `hmac.compare_digest`, checked before the body is read. An unauthenticated caller gets a bodyless 401 and learns nothing about what is behind it. A one-character-short key is refused — the test exists so nobody replaces the comparison with `startswith`.
- **Loopback asserted, not assumed.** `assert_loopback` refuses `0.0.0.0`, a LAN address, or `::`, and runs both before the bind and against the address actually bound.
- **No write routes at all.** POST answers 405 with the key, 401 without — authorization is checked before the method, so an unauthenticated caller cannot even learn which methods exist. Writes arrive with the ticket mechanism rather than being bolted on afterwards, because a write route that predates its ticket is a write route with no gate.
- **No raw-CIP surface.** There is no `generic_message` passthrough, and a test parses the module with `ast` to prove it stays that way. That absence is the real audit boundary — the capability wrapper planned for pycomm3 is defence in depth, but Python has no private and a determined caller reaches the driver anyway; the process boundary is what holds.
- **Degrades, never dies.** Each protocol module is imported in its own `try`, and `/health` reports which loaded and the exact error for any that did not. That is the posture `modbus_rtu.py:86-88` and `mqtt_monitor.py:61-71` already take: a missing wheel disables one panel, it does not fail the sidecar's boot.

**Two flaws in my own test, found by running it.** The raw-CIP assertion first grepped the file text and tripped on the docstring explaining that very rule — a test that cannot tell an implementation from a comment about it is not asserting what it claims. It now inspects code via `ast`, exempting docstrings. And its failure printed three kilobytes of identifiers; it now names the offender (`['/field/generic_message'] != []`).

Verified: 13 tests pass; the raw-CIP assertion fails when a `/field/generic_message` route is injected; the sidecar boots, mints a 64-char key, answers 401 without it and 200 with it, and reports all 10 protocol modules loaded with zero errors.