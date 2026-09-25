---
id: "TM-029"
kind: "task"
status: "open"
created: "2026-09-25T21:38:27.964Z"
board: "controllogix/ccontrolcenter"
title: "The sidecar write route, gated by single-use expiring tickets"
epic: "EP-002"
acceptance: [{"text":"The write route cannot specify a target or a value, and a request that tries is refused with the field named","done":true,"at":"2026-09-25T21:38:46.390Z"},{"text":"A ticket is single-use and expiring, and survives eight concurrent redemptions with exactly one winner","done":true,"at":"2026-09-25T21:38:46.632Z"},{"text":"Tickets are never persisted, asserted by a test over the module's imports and calls","done":true,"at":"2026-09-25T21:38:46.865Z"},{"text":"A flood is refused rather than evicting a ticket somebody is about to confirm","done":true,"at":"2026-09-25T21:38:47.128Z"},{"text":"An unknown outcome says investigate at the equipment and exposes no retry","done":true,"at":"2026-09-25T21:38:47.353Z"}]
evidence: []
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T21:38:47.370Z"
---

Done 2026-09-25, plan §4.4 layer 4. Commit `c932e46`.

`field/app.py` had no write route at all until now, deliberately: a write route that predates its gate never gets one, because by then something is calling it the old way.

**The property.** The write route does not say *what* to write. It names a ticket, and the ticket carries the target and the value, fixed when it was minted. A request that is replayed, guessed or reused can only redo a write that was already authorised, and only once. That is the difference between "this caller may write" and "this write is allowed".

If the request carried the parameters, the thing that was reviewed and the thing that executes would be two separate objects that merely look alike, and every confirmation UI would render a claim rather than the write. A request that tries to restate the write is **refused**, not ignored — ignoring it would let a caller believe it had specified something.

**`field/tickets.py`.** In memory only: a ticket that survived a restart would be an authorisation that outlived the thing that authorised it, and the operator who approved it is not necessarily still at the desk. A test asserts the module imports nothing that could persist one. A flood is refused rather than evicting the oldest — evicting would silently invalidate a ticket somebody is about to confirm, and the write would fail at the least explicable moment. Expiry sweeps, so an expired flood cannot wedge it. Single use survives concurrency: eight threads through a barrier, exactly one wins, which matters because the sidecar is a `ThreadingHTTPServer`.

Outcomes keep the `enip.py:8-11` shape: a controller refusal is 409 `rejected`; anything else is 502 `unknown`, with "investigate at the equipment, do not retry this write" and **nothing rendered that looks like a retry**.

Two tests that said "there are no write routes" were replaced by tests of what the one route refuses. The raw-CIP test is untouched — that absence is still the audit boundary.

**Still not done:** nothing calls this yet. The dashboard's IIOT panel writes Modbus directly through `server.py`; routing it via the sidecar is Phase 1.1b/3 work.