---
id: "TM-081"
kind: "task"
status: "open"
created: "2026-09-26T03:11:02.347Z"
board: "controllogix/ccontrolcenter"
title: "The board itself is on 9p and fails under load with a lie"
epic: "EP-005"
acceptance: [{"text":"bin/tm retries a transient module-resolution failure before reporting it, the way ninep.read_retrying does for the dashboard","done":false},{"text":"A failure that survives the retries says the filesystem could not be read and names 9p, rather than saying the module does not exist","done":false},{"text":"Reproduced under concurrent load rather than asserted, with the reproduction recorded","done":false},{"text":"A pooled worker hitting it is told to retry rather than to reinstall the plugin","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T03:15:54.418Z"
session: "pool-tm-081"
---

Measured 2026-09-26, while creating tasks under concurrent load:

    Error [ERR_MODULE_NOT_FOUND]: Cannot find module
      '.../cache/bytedesk/task-management/c592fc862edf/lib/query.mjs'

The module is there. 49 lib files present, query.mjs among them, 0 failures in
40 sequential re-reads at idle. The plugin lives on /mnt/c, which df reports as
type 9p, and a transient read failure there surfaces through Node's ESM
resolver as MODULE_NOT_FOUND - which says the file does not exist.

This is R29 in the most load-bearing place available: the board every pooled
worker coordinates through. With dispatch on and wipLimit 3 the concurrency
that produced it is now the normal operating condition, and a worker that hits
it will conclude the plugin is broken and may try to reinstall it.

Same family as TM-031's 404-for-an-EIO and ninep.py's 'not there' versus 'could
not find out' - a transient failure reported as a definite answer.