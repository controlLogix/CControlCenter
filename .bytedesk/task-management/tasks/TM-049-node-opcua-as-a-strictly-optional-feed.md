---
id: "TM-049"
kind: "task"
status: "open"
created: "2026-09-26T02:04:41.845Z"
board: "controllogix/ccontrolcenter"
title: "node-opcua as a strictly optional feed"
epic: "EP-002"
acceptance: [{"text":"The tag table is FULLY functional, including writes, with ZERO OPC UA endpoints configured","done":false},{"text":"SignAndEncrypt with Basic256Sha256 is the default; a downgraded endpoint is recorded and badged, never the default","done":false},{"text":"check_api_readonly.sh proves the API has no OPC UA write path","done":false},{"text":"StatusCode maps to three values and sourceTimestamp is preferred over serverTimestamp","done":false},{"text":"One physical point available on both Modbus and OPC UA renders as TWO rows, linked, with disagreement highlighted - never averaged, never fresher-wins","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T03:15:24.467Z"
session: "pool-tm-049"
---

Phase 4.5. Rockwell's embedded OPC UA server is firmware- and SKU-dependent, and
ADR-0019 already records that it needs configuring on the Rockwell side first. So
this can never be a dependency of the tag table.

The API constructs node-opcua READ-ONLY with no write path, and check_api_readonly.sh
proves it. The invariant everything in Phase 4 follows from: the API never writes
to field equipment, only the sidecar does.

Do not flatten OPC UA's quality model into a boolean. Use sourceTimestamp over
serverTimestamp and map StatusCode to three values.