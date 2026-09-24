---
id: "ADR-0012"
kind: "adr"
status: "proposed"
created: "2026-09-24T18:43:58.205Z"
board: "controllogix/ccontrolcenter"
title: "Escalation: use Stop, park the card, and wait for you (Recommended)"
epic: "EP-001"
decisionKey: "381d43d1c1cb"
date: "2026-09-24"
updated: "2026-09-24T18:43:58.233Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-24.
The question asked was: When a reviewer fails the same job three times, what should an autonomous orchestrator do?

## Decision

**When you "start an orchestration", what is its scope and lifetime?** → chose **i like all of these, it needs to be a configurable option in settings, defaulted to #1**.

Rejected:
- **One goal, stated at start; it ends when done (Recommended)** — You type a request ("build the pcap analyser", or point it at an epic) and hit start. The orchestrator opens ONE run, works that scope to completion, closes the cards, tears down its agents and stops. Matches how you and I work today, and the run gate already models exactly this.
- **Continuous: it works the ready queue forever** — Once on, it keeps pulling from the board's dispatchable queue and orchestrating whatever is ready, until you turn it off. Closest to a true autonomous pool. It never stops on its own, so the WIP cap and the kill switch become the only limits on what it does.
- **One epic at a time** — You nominate an epic; it orchestrates every task in that epic to completion, then stops. Narrower than the whole board, broader than a single goal, and the board already groups work this way.

**When a reviewer fails the same job three times, what should an autonomous orchestrator do?** → chose **Stop, park the card, and wait for you (Recommended)**.

Rejected:
- **Stop the whole orchestration** — Any job that fails three times halts everything, agents are torn down and the run is left open for you. Safest and loudest, but one bad card stops unrelated work.
- **Force-complete and move on** — Use `run complete --force`, which records what was unverified before teardown. Keeps things moving without you, but it means shipping work a reviewer explicitly rejected three times.

**Where do you want to watch a run happening?** → chose **A new Runs view in the rail (Recommended)**.

Rejected:
- **A tab under Status** — Status already consolidates Feed, Queue, Journal and Chatter. Runs becomes a fifth tab there, keeping the rail at seven entries. Less room for job detail, but it is where you already look for what is happening.
- **On the Board, beside the dispatch strip** — Extend the existing strip on the Board so a run appears against the cards it is working. Most direct connection between work and card, but a run spanning several cards has nowhere natural to live.

## Consequences

_TODO: what this makes easy, what it makes hard, and what would have to be true to revisit it._