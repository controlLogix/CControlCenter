---
id: "ADR-0001"
kind: "adr"
status: "proposed"
created: "2026-09-23T15:08:53.272Z"
board: "controllogix/ccontrolcenter"
title: "Canonical store: use cc.db stays canonical (Recommended)"
epic: null
decisionKey: "133093d8e590"
date: "2026-09-23"
updated: "2026-09-23T15:08:53.297Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-23.
The question asked was: Which store should be the single source of truth after integration?

## Decision

**Which store should be the single source of truth after integration?** → chose **cc.db stays canonical (Recommended)**.

Rejected:
- **tm store becomes canonical** — Migrate cc.db's epics/tasks/journal into .bytedesk/task-management and make the CCC Task Board view a reader of that store. Inherits the dispatch pool, collect, handoff and worktrees natively. Cost: a real migration of 36 tasks + 289 journal entries, and CCC-specific concepts (claims, devices, terminals, journal) need a home in a store that has no schema for them.
- **Bridge, keep both writable** — Two-way sync between cc.db and the tm store so either CLI works. I'd advise against this one: two writable stores that both mint keys will drift, and the repo's own design notes call out key reuse as a defect class. Listed because it is the lowest-disruption option if you need both CLIs working today.

**How much do you want in the first pass?** → chose **Full integration in one go**.

Rejected:
- **Thin slice first (Recommended)** — Make one real task dispatch end to end against the canonical store — ready task -> agent spawned -> claim bound -> result collected -> board updated. Proves the seam before the rest is built on it. Then iterate.
- **Plan only, no code yet** — I write up the integration design — seam, schema mapping, migration, what retires — as a spec you review before any implementation starts.

## Consequences

_TODO: what this makes easy, what it makes hard, and what would have to be true to revisit it._