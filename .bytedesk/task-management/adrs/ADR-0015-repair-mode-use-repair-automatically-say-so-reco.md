---
id: "ADR-0015"
kind: "adr"
status: "proposed"
created: "2026-09-25T12:46:25.408Z"
board: "controllogix/ccontrolcenter"
title: "Repair mode: use Repair automatically, say so (Recommended)"
epic: "EP-001"
decisionKey: "54cfadac9f72"
date: "2026-09-25"
updated: "2026-09-25T12:46:25.437Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-25.
The question asked was: When a stranded dashboard is detected (serving a home that a killed gate left behind), what should happen?

## Decision

**When a stranded dashboard is detected (serving a home that a killed gate left behind), what should happen?** → chose **Repair automatically, say so (Recommended)**.

Rejected:
- **Detect and report, repair on request** — Print a warning with the exact command to fix it, and do nothing else. Never surprises you by restarting a process. Cost: you still hit the broken board once, you just get told why.
- **Only the dashboard self-checks** — The server itself notices its home directory has vanished and reports it in the UI / an endpoint, rather than any CLI doing the repair. Narrowest blast radius, but it cannot restart itself onto the right home.

**What should trigger the staleness check?** → chose **Every agentmux command (Recommended)**.

Rejected:
- **Only at the start of a gate run** — run_tests.sh repairs the previous run's mess before taking over again. Very contained, zero cost elsewhere — but only helps if you happen to run the gate again.
- **A new explicit command** — e.g. `agentmux dashboard restore`. Nothing happens on its own; you run it when the board looks wrong. Simplest and most predictable, but you have to already suspect the problem.

## Consequences

_TODO: what this makes easy, what it makes hard, and what would have to be true to revisit it._