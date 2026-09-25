---
id: "TM-030"
kind: "task"
status: "done"
created: "2026-09-25T21:38:41.366Z"
board: "controllogix/ccontrolcenter"
title: "BUG: the IIOT panel printed one word for four different faults"
epic: "EP-002"
acceptance: [{"text":"Each of the four faults renders a distinct banner naming which link is at fault","done":true,"at":"2026-09-25T21:38:47.572Z"},{"text":"One stale tag greys its own chip and no others","done":true,"at":"2026-09-25T21:38:47.785Z"},{"text":"A dead feed still greys every chip, because the per-tag verdicts are frozen and ageing","done":true,"at":"2026-09-25T21:38:47.994Z"},{"text":"A live feed carrying old values is amber, not red","done":true,"at":"2026-09-25T21:38:48.210Z"},{"text":"The suite covers a page that has stopped hearing, and fails against the pre-fix commit","done":true,"at":"2026-09-25T21:38:48.409Z"}]
evidence: [".bytedesk\\task-management\\evidence\\TM-030-1790372723834.log"]
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T21:45:30.457Z"
assignee: "claude"
evidenceSources: {".bytedesk\\task-management\\evidence\\TM-030-1790372723834.log":{"source":null,"sha256":"202477a661b8278dce8db8b8c069be6b29f4975fa12c359905e6f7ec666a71e1","bytes":2678,"at":"2026-09-25T21:45:23.835Z"}}
closed: "2026-09-25T21:45:30.439Z"
---

Found and fixed 2026-09-25 while writing the TM-025 regression tests. Commit `213f555`.

The panel said **DISCONNECTED** for all of these, and they send you to different ends of the building:

1. this page cannot reach the dashboard — the fetch threw
2. this page has not had a fresh snapshot — `expired`
3. the dashboard cannot reach the device — `snapshot.connected`
4. one particular value is old — `tag.stale`

The old `connected` ANDed all four together, and every chip in the table took its colour from that one boolean. So **a single stale tag reported the whole feed as DISCONNECTED and greyed forty chips**. Forty chips greying at once is one connectivity fact rendered forty times, and what it teaches the operator is that the chips do not mean anything — the opposite of what `iiot.js:11-14` asks of them.

The banner now carries the feed-level fact once and names which link is down. A live feed with old values on it reads `CONNECTED — 2 of 12 tags stale`, in amber rather than red: a real problem, and not the same problem as a dead link.

**The asymmetry is deliberate and is the whole fix.** A stale *tag* no longer says anything about the feed. But a dead *feed* does say something about every tag: those per-tag verdicts were the server's, computed at a moment that has passed, and they get less true every second. A chip reading "live" off a reading nobody has confirmed since the link dropped is exactly the lie this panel exists to avoid — so the rows still all grey when the link is genuinely down, with the banner above now saying why.

Caught by my own test asserting a dead feed must not read as live, which is the case I would have missed by reasoning alone.

`test_frontend_iiot_age.sh` grew from 6 checks to 8; 7 of the 8 now fail against `6b2d581`, up from 4 of 6.

**Not done:** this is the Modbus panel only. Plan §4.6 wants the same treatment on the merged tag table when OPC UA and Logix feeds land beside it, where "feed-level staleness is its own banner" has to hold per feed rather than once.