---
id: "TM-001"
kind: "task"
status: "open"
created: "2026-09-25T15:18:29.041Z"
board: "controllogix/ccontrolcenter"
title: "Pin boardId in the task-store config"
epic: "EP-002"
acceptance: [{"text":"config.json contains boardId set to controllogix/ccontrolcenter, matching the identity already stamped in every existing doc","done":true,"at":"2026-09-25T15:22:02.684Z"},{"text":"config.json is still valid JSON with all 23 original keys intact","done":true,"at":"2026-09-25T15:22:05.757Z"},{"text":"The diff is one added line, with no reformatting of the generated file","done":true,"at":"2026-09-25T15:22:09.203Z"},{"text":"A backup of the original config exists from before the edit","done":true,"at":"2026-09-25T15:22:12.189Z"},{"text":"The pin's real effect is recorded: boardIdentity() returns git first (store.mjs:753-757), so the pin sets `stored` and makes a mismatch report drifted:true rather than overriding the git-derived identity","done":true,"at":"2026-09-25T15:22:15.646Z"},{"text":"The repo-rename question is decided and written down: either the GitHub repo is not renamed, or the rename plan includes rewriting board: across every doc in the same change","done":false}]
evidence: [".bytedesk\\task-management\\evidence\\TM-001-1790349746833.log"]
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T16:19:20.382Z"
evidenceSources: {".bytedesk\\task-management\\evidence\\TM-001-1790349746833.log":{"source":null,"sha256":"36256b9035ac4d0389c2f6ec20931d09e541245c857febf0018f9dc891fd760f","bytes":1871,"at":"2026-09-25T15:22:26.834Z"}}
assignee: "claude"
---

Blocker for every other task in EP-002.

`store.mjs:753` reads `readJson(p.config, {}).boardId || null` and falls back to an identity guessed from the git remote (`:757`). `storeBoard()` stamps that onto every new doc (`:869`), and `write()` refuses any doc whose `board` differs: "<id> belongs to X, but this store is Y — refusing to file it here" (`:801-806`).

`.bytedesk/task-management/config.json` had no `boardId`, so the identity came from the remote `controlLogix/CControlCenter` (lowercased to `controllogix/ccontrolcenter`). Renaming the GitHub repo to `agentmux` — which the Phase 0 rebrand invites — would have made every existing epic and ADR unwritable.

Pin it before anything else touches the store.