---
id: "ADR-0007"
kind: "adr"
status: "proposed"
created: "2026-09-23T18:32:50.106Z"
board: "controllogix/ccontrolcenter"
title: "Dirty tree: use Commit it first, then build"
epic: "EP-001"
decisionKey: "22bf18423323"
date: "2026-09-23"
updated: "2026-09-23T18:32:50.136Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-23.
The question asked was: agentmux has 547 lines of uncommitted work across 12 files — including every file the panes will edit. How do we start clean?

## Decision

**agentmux has 547 lines of uncommitted work across 12 files — including every file the panes will edit. How do we start clean?** → chose **Commit it first, then build**.

Rejected:
- **Branch, then build there** — Commit the current work on main, then cut a feature branch for the whole roster build. Keeps main untouched until the six stages land and the gate is green.
- **Stash it** — Set the work aside, build on a clean tree, restore afterwards. Risky here — the stash and the new work touch the same files, so restoring it later will conflict.
- **Proceed dirty** — Start panes on the tree as it is. Fastest to begin; a pane that damages a file cannot be reverted without losing your uncommitted changes too.

**The board caps concurrency: `dispatchWip` 3 and `wipLimit` 3. How wide should the waves run?** → chose **Keep 3 — it's a real limit**.

Rejected:
- **Raise to 5** — Wider waves finish sooner, at the cost of more concurrent agents writing to the repo and more for you to watch. Requires bumping both dispatchWip and wipLimit.
- **Two: one per repo** — One pane on agentmux, one on the marketplace plugin. Minimal contention, easiest to follow, and the two repos genuinely cannot collide. Slowest overall.
- **You decide per wave** — I propose a width for each wave based on how independent its tasks really are, and you approve before it runs.

## Consequences

_TODO: what this makes easy, what it makes hard, and what would have to be true to revisit it._