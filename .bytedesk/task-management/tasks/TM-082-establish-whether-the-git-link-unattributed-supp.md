---
id: "TM-082"
kind: "task"
status: "open"
created: "2026-09-26T03:11:04.062Z"
board: "controllogix/ccontrolcenter"
title: "Establish whether the git_link_unattributed suppression is actually live"
epic: "EP-005"
acceptance: [{"text":"It is established, by measurement, which surfaces did and did not show these rows BEFORE the change","done":false},{"text":"It is established whether the cache copy or the marketplace copy is what runs, and whether a marketplace refresh overwrites or restores the edit","done":false},{"text":"If the fix is needed, it lives where it actually runs; if it is not, it is reverted and TM-032 AC5 is closed with the measurement that shows why","done":false},{"text":"test_hook_noise.py is either registered in the gate or deleted, with the reason recorded","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T03:12:43.229Z"
session: "pool-tm-082"
---

UNRESOLVED, and recorded rather than guessed at.

TM-032's fix was written into the MARKETPLACE copy of the plugin
(~/.claude/plugins/marketplaces/bytedesk/task-management/lib/render.mjs), but
TM_PLUGIN_ROOT resolves to the CACHE copy
(~/.claude/plugins/cache/bytedesk/task-management/c592fc862edf/), and a diff
ignoring comments shows the cache copy does NOT contain the UNSURFACED set or
either of its two call sites.

And yet: 94 rows exist in events.jsonl, 43 of them inside the last 1000, and
`tm log 400|1000|2000` each surface ZERO.

So the rows are being hidden by something that is not this fix. The most likely
explanation is that tm log renders only rows carrying an entity id and these
carry none - meaning the fix addressed a surface that already did not show
them, and the surfaces that DO show them (the dashboard activity panel, the MCP
log tool, standup) were never measured after the change.

Do not register dashboard/test_hook_noise.py in the gate until this is settled.
It is written and green, but registering it makes the gate depend on an edit
outside this repository, and right now it is not established that the edit
changes anything.