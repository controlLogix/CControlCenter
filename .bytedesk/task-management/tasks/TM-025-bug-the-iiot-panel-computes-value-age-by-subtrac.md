---
id: "TM-025"
kind: "task"
status: "done"
created: "2026-09-25T20:10:11.564Z"
board: "controllogix/ccontrolcenter"
title: "BUG: the IIOT panel computes value age by subtracting two different clocks"
epic: "EP-002"
acceptance: [{"text":"The IIOT panel never subtracts a server timestamp from a browser timestamp","done":true,"at":"2026-09-25T20:46:04.871Z"},{"text":"The server supplies both the staleness verdict and an age measured at the source","done":true,"at":"2026-09-25T20:46:07.703Z"},{"text":"The client renders a ticking age using a monotonic clock only, never wall-clock arithmetic","done":true,"at":"2026-09-25T20:46:10.599Z"},{"text":"A test fakes a ten-minute client clock skew and the staleness verdicts are unchanged","done":true,"at":"2026-09-25T20:46:13.664Z"},{"text":"A tag with no reading still renders visibly as having no value, rather than as zero or blank","done":true,"at":"2026-09-25T20:46:16.298Z"}]
evidence: [".bytedesk\\task-management\\evidence\\TM-025-1790369189374.log"]
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T21:44:09.027Z"
evidenceSources: {".bytedesk\\task-management\\evidence\\TM-025-1790369189374.log":{"source":null,"sha256":"22366002caf9cdefd1c41ce1fae4f0bc07e7c01732d3a8c178c822a4fa3614e2","bytes":2602,"at":"2026-09-25T20:46:29.375Z"}}
assignee: "claude"
closed: "2026-09-25T21:44:09.008Z"
---

Found while wiring the equipment-write confirmation, 2026-09-25. Not fixed — the confirmation card deliberately avoids it, but the panel itself still does it.

`iiot.js:95` decides whether a tag is stale with:

    Date.now() / 1000 - t.last_good < config.interval

`Date.now()` is the **browser's** clock. `last_good` is the **server's**. Subtracting one from the other only works while the two agree, and nothing makes them agree.

`iiot.js:11-14` is emphatic about why this matters, and it is right:

> The server owns the poll; this renders what it has and shows explicitly whether each value is live or stale, because a number on screen with no age next to it is the single most dangerous thing a panel like this can display.

An age computed across two clocks is worse than no age: it looks authoritative and it is wrong by whatever the skew happens to be.

**Three things make the skew real rather than theoretical here:**

- WSL2's clock drifts against the Windows host after the host sleeps — a well-known and recurring class of problem on exactly this setup.
- The dashboard is reached over the tailnet in Phase 6, so the browser may be a phone that has never agreed with anything.
- `modbus_poll.py:245` **already computes the verdict server-side** (`stale = not connected or last_good is None or now - last_good >= interval`), so the client is recomputing, less reliably, something it is already being told.

**The fix is to stop computing it.** The server should send `stale` and an `ageMs` measured at the source, and the client should render `ageMs + (performance.now() - snapshotArrivedAt)` for a smoothly ticking age — one monotonic clock, never a subtraction between two wall clocks. That is the rule the rewrite plan already states for the merged tag table (§4.6), so doing it here is bringing the existing panel up to the standard the replacement will hold.

The write-confirmation card added today sidesteps this by reporting the server's own `stale` flag and saying "as last polled" rather than inventing a precise age, and `test_frontend_iiot_write.sh` asserts it stays that way. The panel still needs fixing.