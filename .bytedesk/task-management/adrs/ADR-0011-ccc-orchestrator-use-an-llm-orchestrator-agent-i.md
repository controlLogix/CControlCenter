---
id: "ADR-0011"
kind: "adr"
status: "proposed"
created: "2026-09-24T18:39:58.749Z"
board: "controllogix/ccontrolcenter"
title: "CCC orchestrator: use An LLM orchestrator agent in its own pane (Recommended)"
epic: "EP-001"
decisionKey: "e33148a29694"
date: "2026-09-24"
updated: "2026-09-24T18:39:58.779Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-24.
The question asked was: When "the CCC is the orchestrator", what is actually doing the orchestrating?

## Decision

**When "the CCC is the orchestrator", what is actually doing the orchestrating?** → chose **An LLM orchestrator agent in its own pane (Recommended)**.

Rejected:
- **A deterministic policy loop inside server.py** — No LLM. A background thread picks the top ready card, spawns worker+reviewer from the roster, assigns the job with the card's own body/acceptance as the brief, waits for the verdict, completes or parks. Predictable and cheap, but it cannot write a brief, judge ambiguity, or react when an agent goes sideways.
- **Extend the existing dispatch pool** — You already have `agentmux dispatch`/`collect`/`pool` which hands one ready card to one fresh agent. Grow that into a full run-gated cycle (add a reviewer, verdicts, completion) rather than building a second orchestration system beside it.

**How much can the CCC orchestrator do without a human in the loop?** → chose **Fully autonomous, including closing cards**.

Rejected:
- **Everything except closing the card (Recommended)** — It can open runs, spawn worker+reviewer, brief, collect verdicts and complete the RUN. It cannot tick acceptance criteria or close a board card — that needs evidence and a human judgement, which is exactly the gap we just hit with EP-021. Cards land in a 'ready to close' state for you.
- **Spawn and brief only; a human verdicts** — It picks cards, spawns agents and writes briefs, then stops and waits for you to review and verdict every job. Safest, but it is a queue feeder rather than an orchestrator, and you are still the bottleneck.

**What does the setting actually switch between?** → chose **An on/off switch for the CCC orchestrator only**.

Rejected:
- **Who may START runs; both can always observe (Recommended)** — One authority at a time. Set to 'this session' and the CCC orchestrator will not pick up work; set to 'CCC' and it does. Either way both surfaces show every run, and you can always intervene by hand. A run already in flight is never orphaned by flipping the switch.
- **Per-epic, not global** — Each epic is marked as orchestrated-by-session or orchestrated-by-CCC, so autonomous work can run on one epic while you drive another by hand. More precise, more state to keep straight.

## Consequences

_TODO: what this makes easy, what it makes hard, and what would have to be true to revisit it._