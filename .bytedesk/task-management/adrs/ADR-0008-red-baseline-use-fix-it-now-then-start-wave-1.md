---
id: "ADR-0008"
kind: "adr"
status: "proposed"
created: "2026-09-23T18:49:26.139Z"
board: "controllogix/ccontrolcenter"
title: "Red baseline: use Fix it now, then start Wave 1"
epic: "EP-001"
decisionKey: "450620f6b49c"
date: "2026-09-23"
updated: "2026-09-23T18:49:26.166Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-23.
The question asked was: The gate has been red before we started: 20 assertions across smoke.sh and test_coordination.sh, from an id-semantics regression in the legacy compatibility surface. How should I handle it?

## Decision

**The gate has been red before we started: 20 assertions across smoke.sh and test_coordination.sh, from an id-semantics regression in the legacy compatibility surface. How should I handle it?** → chose **Fix it now, then start Wave 1**.

Rejected:
- **Baseline it as known-red** — Record the 20 failures as the accepted starting point and gate each wave on "no NEW failures" instead. Starts Wave 1 immediately, but every future gate run needs a human to compare against a known-bad list.
- **File it as a task and fix it in a wave** — Put it on the board as its own card with the diagnosis attached, and let a pane fix it as part of Wave 1. Keeps the fix in the dogfooded flow rather than me doing it by hand — but Wave 1 then starts red.
- **Update the tests instead** — Treat the new key-string id as correct and change smoke.sh and test_coordination.sh to match. Accepts the API change as intentional rather than restoring the old contract.

## Consequences

_TODO: what this makes easy, what it makes hard, and what would have to be true to revisit it._