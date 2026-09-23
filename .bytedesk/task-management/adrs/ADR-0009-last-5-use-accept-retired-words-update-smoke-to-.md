---
id: "ADR-0009"
kind: "adr"
status: "proposed"
created: "2026-09-23T18:55:53.746Z"
board: "controllogix/ccontrolcenter"
title: "Last 5: use Accept retired words + update smoke to read the live vocabulary"
epic: "EP-001"
decisionKey: "d3c1d0d0a476"
date: "2026-09-23"
updated: "2026-09-23T18:55:53.773Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-23.
The question asked was: The id fix took smoke.sh from 18 failures to 5. The remaining five need a call about test expectations, not just code. How do you want them handled?

## Decision

**The id fix took smoke.sh from 18 failures to 5. The remaining five need a call about test expectations, not just code. How do you want them handled?** → chose **Accept retired words + update smoke to read the live vocabulary**.

Rejected:
- **Code only — leave smoke.sh alone** — Keep the compat fix so old callers work, and accept that three round-trip assertions stay red because the stored status genuinely differs from the word sent. Gate stays at 5 failures; I'd baseline those.
- **Revert my mapping change too** — Treat the new vocabulary as the intended contract, stop accepting retired words, and update smoke.sh to the current statuses throughout. Cleanest model, but the old board UI and agentmux.sh break if they still send todo.
- **Stop here, file the rest as a card** — Bank the 18-to-5 improvement now, put the remaining five on the board with the diagnosis attached, and start Wave 1. The gate baseline is 5 known failures.

**Two of the five are soft-delete semantics: deleting an already-deleted task returns 200 instead of 404, and the epic cascade counts a task that was already deleted. Both look like real bugs rather than stale tests. Fix them?** → chose **Fix both — they're real**.

Rejected:
- **Fix the 404, leave the cascade** — The repeat-delete 404 is clearly wrong. The cascade count is arguably correct-by-new-design (it reports everything it touched), so update that test expectation instead.
- **Leave both, file as a card** — Neither blocks the roster build. Record the diagnosis on the board and move to Wave 1.

## Consequences

_TODO: what this makes easy, what it makes hard, and what would have to be true to revisit it._