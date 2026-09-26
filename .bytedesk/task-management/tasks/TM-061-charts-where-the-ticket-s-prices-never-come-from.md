---
id: "TM-061"
kind: "task"
status: "open"
created: "2026-09-26T02:06:23.810Z"
board: "controllogix/ccontrolcenter"
title: "Charts where the ticket's prices never come from the iframe"
epic: "EP-003"
acceptance: [{"text":"The ticket records the provenance of every price: provider or typed","done":false},{"text":"No price input is ever read out of the chart iframe, asserted by test","done":false},{"text":"The trade/chart split ratio is user-controlled and persisted","done":false},{"text":"Entry markers, cost basis and open orders render from the canonical rows, not from the widget","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "main"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T02:06:24.135Z"
---

Phase 5.7. TradingView Advanced Chart widget, overlaid with entry markers, a
cost-basis line and open-order levels, with a user-controlled trade/chart split
and a persisted ratio.

The iframe is CROSS-ORIGIN and is a display surface. Reading a number out of it is
neither reliable nor auditable, so the ticket's price inputs never come from it.
Prices come from the provider or are typed, and the ticket RECORDS WHICH.