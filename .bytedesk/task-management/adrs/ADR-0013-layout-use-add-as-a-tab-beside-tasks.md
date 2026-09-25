---
id: "ADR-0013"
kind: "adr"
status: "proposed"
created: "2026-09-25T01:11:36.677Z"
board: "controllogix/ccontrolcenter"
title: "Layout: use Add as a tab beside Tasks"
epic: "EP-001"
decisionKey: "4cea780d829d"
date: "2026-09-25"
updated: "2026-09-25T01:11:36.704Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-25.
The question asked was: How should the Kanban view coexist with the current epic-list board?

## Decision

**How should the Kanban view coexist with the current epic-list board?** → chose **Add as a tab beside Tasks**.

Rejected:
- **A view switcher inside Tasks** — One Tasks panel with a List / Kanban toggle at the top, remembered per browser. Fewer tabs, but the two layouts share one panel's state.
- **Kanban replaces the list** — The epic list goes away; Kanban becomes the board. Simplest to build and maintain, but loses the epic-grouped view and the drag-between-epics that already works.

**When you open a ticket in depth, what is it showing?** → chose **all of it**.

Rejected:
- **Board cards (TM-/EP-)** — The local SQLite board: body, acceptance criteria, evidence, commits, comments, history, roster, blockers. Everything already exists in the payload — no backend work.
- **Board cards, with GitHub linked in** — Board card detail as above, plus any linked GitHub issue/PR pulled through the existing gh integration. Needs gh working inside WSL, which is the symlink question.
- **Jira issues too** — The detail panel also opens real Jira issues from the Atlassian tab. Larger scope — Jira reads are cached and rate-limited, and writes there leave this machine.

**Should the detail panel be able to change the card, or only show it?** → chose **Full edit, including body and acceptance**.

Rejected:
- **Read deeply, edit the safe fields** — Show everything; allow tick acceptance, add comment/evidence/commit, change status, set assignee. All of these already have write endpoints and gates. No new backend.
- **Read-only** — A pure inspection panel. Safest and smallest, but you would still edit cards from the CLI or the existing list view.

**What do you actually want gh for here?** → chose **Just stop re-authenticating in WSL**.

Rejected:
- **Also link cards to issues/PRs** — The above, plus the card detail panel showing a linked GitHub issue or PR and its state. Uses the existing gh shell-outs.
- **Leave gh alone for now** — Do the Kanban and detail panel only; revisit gh separately. Keeps this change purely local and UI-shaped.

## Consequences

_TODO: what this makes easy, what it makes hard, and what would have to be true to revisit it._