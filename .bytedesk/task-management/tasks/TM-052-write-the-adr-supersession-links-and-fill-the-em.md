---
id: "TM-052"
kind: "task"
status: "open"
created: "2026-09-26T02:04:47.756Z"
board: "controllogix/ccontrolcenter"
title: "Write the ADR supersession links and fill the empty Consequences"
epic: "EP-002"
acceptance: [{"text":"Every ADR that has been superseded says so, and names what superseded it","done":false},{"text":"ADR-0023's supersession of ADR-0001 and ADR-0021 D3 is written down","done":false},{"text":"ADR-0021 D2's reversal of ADR-0017 D3 is linked","done":false},{"text":"ADRs that are actually in force move off 'proposed', and Consequences is filled for those that have any","done":false},{"text":"No existing ADR text is edited to change what it decided - supersession only","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T03:15:27.778Z"
session: "pool-tm-052"
---

Section 10, item 3. All 26 ADRs are status: proposed with an empty Consequences
section. An ADR trail that records only the first answer is worse than none,
because it reads as current.

Known unlinked reversals: ADR-0023 supersedes ADR-0001 and ADR-0021 D3 without
saying so; ADR-0021 D2 reverses ADR-0017 D3 (voice) with no link.

An ADR saying CCC records what was decided THEN - supersede, never edit.