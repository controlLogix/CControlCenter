---
id: "TM-073"
kind: "task"
status: "open"
created: "2026-09-26T03:07:38.338Z"
board: "controllogix/ccontrolcenter"
title: "BUG: an approved, verified run sits open forever and reads as a fresh ask"
epic: "EP-005"
acceptance: [{"text":"An approved run that nothing can complete says so, naming that no orchestrator is running - it does not render as a pending review","done":false},{"text":"attention() distinguishes waiting-on-you from stalled-waiting-on-a-worker, and the badge and the sort still read from ONE selector","done":false},{"text":"The stalled state renders the verb that fixes it, the way ccboard.Refused.missing already does","done":false},{"text":"run complete does not claim agents are running when no tmux server exists","done":false},{"text":"Proved against a fixture run in each state, including the approved-and-stalled one","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T03:20:04.334Z"
session: "pool-tm-073"
---

Measured 2026-09-26. Run 8bd2ab: jobs 3, verified 3, review.state approved by
the operator, blocking [], escalated [] - and complete false, because
dispatch.enabled was false and no pane existed to complete it.

runs.js attention() returns '' for an approved run, so it is not badged - but it
is still listed as open with an approval block, which reads as a pending ask
every single time the page is opened. The operator asked, in as many words, to
stop being made to approve it.

This is the project's signature bug in another place: the UI cannot distinguish
'waiting for you' from 'waiting for a worker that is not running'. Same family
as ninep.py's 'not there' versus 'could not find out', and as TM-030's four
faults printing one word.

Note run complete ALSO printed 'agents are still running - tear them down' when
there was no tmux server at all. A second false statement in the same breath.