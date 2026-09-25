---
id: "TM-010"
kind: "task"
status: "done"
created: "2026-09-25T15:20:20.431Z"
board: "controllogix/ccontrolcenter"
title: "Make Node usable inside WSL and guard against the Windows interop node"
epic: "EP-002"
acceptance: [{"text":"AGENTMUX_NODE resolves to an absolute path under ~/.nvm/versions/node and reports v24.x from a NON-interactive WSL shell","done":true,"at":"2026-09-25T16:18:51.477Z"},{"text":"The discovery reuses the shape already in test_e2e.sh:24-30 rather than adding a second mechanism","done":true,"at":"2026-09-25T16:18:52.912Z"},{"text":"A prestart guard refuses to run when node resolves anywhere under /mnt/c, with a message naming the cause","done":true,"at":"2026-09-25T16:18:54.833Z"},{"text":"The guard is proven by pointing PATH at the Windows node and observing the refusal","done":true,"at":"2026-09-25T16:18:55.791Z"},{"text":"bin/tm runs from WSL without exit 127, or the reason it still cannot is documented","done":true,"at":"2026-09-25T16:18:56.950Z"}]
evidence: [".bytedesk\\task-management\\evidence\\TM-010-1790353070604.log"]
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T16:19:28.319Z"
evidenceSources: {".bytedesk\\task-management\\evidence\\TM-010-1790353070604.log":{"source":null,"sha256":"ed2dd3a0e6c826643d531729804b7f84df732e5cdb4e9c6bf712f919aafce92a","bytes":2363,"at":"2026-09-25T16:17:50.605Z"}}
assignee: "claude"
closed: "2026-09-25T16:19:28.286Z"
---

Blocks all of Phase 1. The draft plan recorded "Node v24.14.0 present" — that is the **Windows** install.

Measured 2026-09-25 inside Ubuntu:
```
~/.nvm/versions/node/v24.21.0      exists
command -v node                     -> none   (login AND non-interactive)
command -v npm  -> /mnt/c/Program Files/nodejs/npm   (Windows, via interop)
```
So nvm is installed and never sourced, and the only reachable npm is the Windows one leaking through `/mnt/c`. That is worse than nothing: building `better-sqlite3` or any native module with Windows npm from a Linux shell produces binaries for the wrong platform, with failure modes that do not name their cause.

ADR-0023 puts the API in WSL, so this must be solved before any API scaffolding.

`dashboard/test_e2e.sh:24-30` already does this discovery for Playwright — reuse its shape rather than inventing a second one.

Related: `.bytedesk/task-management/bin/tm` is a Node shim (`#!/usr/bin/env node`) and currently fails in WSL with exit 127 for the same reason.