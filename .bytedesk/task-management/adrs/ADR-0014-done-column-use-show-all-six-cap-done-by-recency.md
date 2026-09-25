---
id: "ADR-0014"
kind: "adr"
status: "proposed"
created: "2026-09-25T01:13:59.185Z"
board: "controllogix/ccontrolcenter"
title: "Done column: use Show all six, cap done by recency"
epic: "EP-001"
decisionKey: "af39836ce81d"
date: "2026-09-25"
updated: "2026-09-25T01:13:59.213Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-25.
The question asked was: The board is 81 done, 2 open, 4 statuses unused. How should the Kanban handle that?

## Decision

**The board is 81 done, 2 open, 4 statuses unused. How should the Kanban handle that?** → chose **Show all six, cap done by recency**.

Rejected:
- **Only columns with cards** — Columns appear when something is in them. A tidy board today, but the workflow is invisible — you cannot see that 'blocked' or 'parked' exist until something lands there, and you cannot drag a card into a column that is not rendered.
- **Group by epic, status as a badge** — Columns are epics rather than statuses; each card shows its status as a chip. Closer to today's list view, and avoids the lopsided column entirely — but it is not really a Kanban.

**Jira detail needs a new backend call — atlassian.py has no single-issue fetch. How far do you want to go?** → chose **Keep Jira shallow for now**.

Rejected:
- **Add the one function** — A `jira_issue(cfg, key)` in atlassian.py plus one read endpoint, so the panel can show description, comments and available transitions. About 40 lines of backend, guarded and cached like the existing ticket read.
- **Reuse jira_search with a key JQL** — No new function: query `key = TM-123` through the existing jira_search and widen the fields it extracts. Cheaper and reuses a guarded path, but the field extraction in tickets_snapshot is currently hard-coded and would need loosening.

## Consequences

_TODO: what this makes easy, what it makes hard, and what would have to be true to revisit it._