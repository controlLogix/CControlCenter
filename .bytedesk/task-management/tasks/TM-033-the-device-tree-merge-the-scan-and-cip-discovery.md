---
id: "TM-033"
kind: "task"
status: "done"
created: "2026-09-25T22:56:41.997Z"
board: "controllogix/ccontrolcenter"
title: "The device tree — merge the scan and CIP discovery without flattening them"
epic: "EP-002"
acceptance: [{"text":"Every row records which sources reported it, and a device known only from a port sweep never acquires an identity it did not report","done":true,"at":"2026-09-25T22:56:49.751Z"},{"text":"Two sources disagreeing are both kept with their origins and the row is flagged, rather than one winning silently","done":true,"at":"2026-09-25T22:56:49.998Z"},{"text":"\"Nothing has looked yet\" and \"nothing answered\" render as different answers","done":true,"at":"2026-09-25T22:56:50.225Z"},{"text":"GET /api/devices/tree touches no network; discovery is an explicit POST","done":true,"at":"2026-09-25T22:56:50.437Z"},{"text":"Promotion writes the existing cc.db devices table with no new schema, and a bare address with no protocol is not promotable","done":true,"at":"2026-09-25T22:56:50.658Z"},{"text":"Both suites fail cleanly against the commit before the feature rather than crashing","done":true,"at":"2026-09-25T22:56:50.861Z"}]
evidence: [".bytedesk\\task-management\\evidence\\TM-033-1790378554349.log"]
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T23:22:42.608Z"
evidenceSources: {".bytedesk\\task-management\\evidence\\TM-033-1790378554349.log":{"source":null,"sha256":"7b89f61816fe7294ffb2f7a8906f580c302208ad2d815ccdfa8bc4ae693de48d","bytes":2980,"at":"2026-09-25T23:22:34.350Z"}}
assignee: "claude"
closed: "2026-09-25T23:22:42.592Z"
---

Done 2026-09-25, plan §4.7. Commit `cbf9811`.

**The distinction the whole panel exists for.** The Ethernet scanner answers *"what is listening?"* — a TCP connect and an OUI lookup. That is an **inference**. CIP ListIdentity answers *"what are you?"* — the device's own vendor, product, revision, serial and state. That is a **statement**. Both are useful; they are not the same thing, and rendering them with equal confidence would be the same class of lie as an un-aged value on the tag table.

So the origin survives the merge. Every row carries which sources reported it; every field that came from somewhere carries where; the left border is solid for a device that identified itself and faint for one that merely answered a port; `unidentified` renders as a real answer rather than as a gap.

**Disagreement is shown, never resolved.** When the OUI table says `Rockwell Automation` and the device says `Rockwell Automation/Allen-Bradley`, both appear with their sources and the row is flagged. Picking a winner — newest, most specific, highest priority — is how the wrong one ends up on screen with nothing to say it was ever in doubt.

**The two empty states are different answers.** "Nothing has looked yet" and "nothing answered" used to be the same blank list, and a blank list reads as the second when it is almost always the first. CIP discovery being unavailable (no pycomm3) is stated with its reason rather than showing as a quiet zero.

**Nothing puts traffic on a wire by itself.** `GET /api/devices/tree` merges what is already known and touches no network, so a panel left open is not quietly broadcasting on a plant segment. Discovery is a `POST` behind a button. A GET on the discover path is 405; a bodyless POST is 415, through the same `read_cc_body` guards as everything else.

**Promotion uses the existing `cc.db devices` table** (`ccstore.py:67`) — no new schema, because a device tree with its own store would be a second inventory to keep in step with the first. The saved row records *how* the device was found. A bare address with no protocol is not promotable: an ssh port is a ping reply, not a device.

**Tests:** `test_devicetree.py` 18 assertions over the pure merge, driven from recorded scan and discovery output with no network; `test_frontend_devicetree.sh` 8 more driving the real render. Both registered in the failability gate against `85e6ddb` and both fail cleanly there rather than crashing — the frontend suite now splits its guards, because being in the wrong directory is not a test result but a missing subject is.

**Not done:** OPC UA endpoints are merged if supplied, but nothing fetches them yet — plan §4.5 puts node-opcua in the Node API, which is Phases 1–3. The merge and its tests already handle the empty case, which ADR-0019 says is the normal one.