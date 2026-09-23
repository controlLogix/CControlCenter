---
id: "ADR-0003"
kind: "adr"
status: "proposed"
created: "2026-09-23T17:08:27.898Z"
board: "controllogix/ccontrolcenter"
title: "The lead: use Per-task lead agent"
epic: null
decisionKey: "599db53927b8"
date: "2026-09-23"
updated: "2026-09-23T17:08:27.924Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-23.
The question asked was: What IS the lead, concretely, when a task gets dispatched?

## Decision

**What IS the lead, concretely, when a task gets dispatched?** → chose **Per-task lead agent**.

Rejected:
- **One standing foreman** — A single long-lived foreman agent per repo handles every dispatch, recruiting and releasing workers as cards flow through. Cheaper, keeps context across tasks; one failure point, and its context grows.
- **Your session is the lead** — No lead agent. The Claude Code session you're talking to reads the card, proposes the roster, you approve, it hires. Zero extra agent cost; only works while a session is open.
- **Pool proposes, lead only if big** — Small/medium cards go straight to a solo worker with no lead at all. Only cards inferred as large get a lead agent spawned to coordinate. Cost scales with task size.

**You picked both "human picks" and "dispatcher infers" — where exactly does your approval sit?** → chose **Infer → propose → you approve roster**.

Rejected:
- **Approve every hire** — The lead must ask before each individual worker spawns. Maximum control, maximum interruption — the pool can never drain while you're away.
- **Approve by budget, not by name** — You approve a headcount/cost ceiling for the task ("up to 3 agents"). The lead recruits freely under that ceiling and must come back to you to exceed it.
- **Auto under a threshold** — Inferred-small tasks dispatch with no approval so the pool drains unattended; anything above the threshold waits for you on the board. Threshold is configurable.

**A repo-local agent has the same name as a global one. What happens?** → chose **Collision is an error**.

Rejected:
- **Repo extends global** — Repo-local file may declare `extends: <global>` and override only some fields (e.g. keep the persona, swap the model). Non-extending same-name files are an error you see in the UI.
- **Repo silently wins** — Nearest definition wins outright, like .gitignore or CLAUDE.md layering. Simple and predictable; no partial overrides, you restate the whole agent.

**You already have a Claude Code subagent roster (plc-dev, senior-reviewer, plc-test-engineer, scheduler, hr-recruiter) in .claude/agents/*.md. How should these relate?** → chose **One roster, agentmux reads both**.

Rejected:
- **Separate, but importable** — agentmux keeps its own directories, with an "import from .claude/agents" action in the UI that copies a definition in once. Clean separation; drift is possible after import.
- **Fully separate** — Claude Code subagents and agentmux agents are different things and stay that way. Least coupling, but you maintain two rosters by hand.

## Consequences

_TODO: what this makes easy, what it makes hard, and what would have to be true to revisit it._