---
id: "TM-062"
kind: "task"
status: "open"
created: "2026-09-26T02:06:26.153Z"
board: "controllogix/ccontrolcenter"
title: "Market data behind a provider interface, with scraping rejected"
epic: "EP-003"
acceptance: [{"text":"Any method may return NotSupported, and the UI renders 'not available from <provider>' - a missing number must LOOK missing","done":false},{"text":"Fundamentals and news are deferred, and getOptionChain returns NotSupported until Polygon is added","done":false},{"text":"No yfinance or Yahoo scraping adapter exists, and the rejection is recorded where someone would go to add one","done":false},{"text":"No independent tax-lot or cost-basis engine; position-level basis is mirrored and lot selection is linked out","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T03:12:27.603Z"
session: "pool-tm-062"
---

Open question 1. A MarketDataProvider interface with two adapters and one named
rejection.

Alpaca free tier is primary, and the reason is EXECUTION, not data: its paper
trading API is the legitimate venue for the ExecutionVenue work. Polygon.io
Options Starter when options chains are actually needed; until then
getOptionChain returns NotSupported.

yfinance and Yahoo scraping are REJECTED - the project is already carrying ToS
risk at one venue, and a second unofficial scrape multiplies fragility for no
capability gain. Recorded so it is not quietly reintroduced.

Tax lots are explicitly out: mirror the broker's position-level basis and
unrealized P/L, and LINK to its lot-selection UI. A second computed basis would
eventually disagree with the tax form and would be an attractive but wrong number
to size from.