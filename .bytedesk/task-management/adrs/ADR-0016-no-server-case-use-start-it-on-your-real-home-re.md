---
id: "ADR-0016"
kind: "adr"
status: "proposed"
created: "2026-09-25T12:48:11.781Z"
board: "controllogix/ccontrolcenter"
title: "No server case: use Start it on your real home (Recommended)"
epic: "EP-001"
decisionKey: "f3ab19df4a1b"
date: "2026-09-25"
updated: "2026-09-25T12:48:11.808Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-25.
The question asked was: A killed gate can leave a stale marker with no dashboard running at all (the server died too, not just got stranded). What should the auto-repair do then?

## Decision

**A killed gate can leave a stale marker with no dashboard running at all (the server died too, not just got stranded). What should the auto-repair do then?** → chose **Start it on your real home (Recommended)**.

Rejected:
- **Only clear the marker, start nothing** — Repair the *stranded* case only. If nothing is listening, leave it that way — you may have deliberately stopped it. Never starts a process you didn't ask for.
- **Record whether one was running, honour that** — The marker stores whether the operator actually had a dashboard up at takeover time. Restore only if they did. Most faithful, slightly more state to keep correct.

## Consequences

_TODO: what this makes easy, what it makes hard, and what would have to be true to revisit it._