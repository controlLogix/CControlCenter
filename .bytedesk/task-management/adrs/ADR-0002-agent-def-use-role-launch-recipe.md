---
id: "ADR-0002"
kind: "adr"
status: "proposed"
created: "2026-09-23T17:04:35.619Z"
board: "controllogix/ccontrolcenter"
title: "Agent def: use Role + launch recipe"
epic: null
decisionKey: "7dd26b89dd05"
date: "2026-09-23"
updated: "2026-09-23T17:04:35.647Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-23.
The question asked was: What is an "agent" in this system — what does a definition actually contain?

## Decision

**What is an "agent" in this system — what does a definition actually contain?** → chose **Role + launch recipe**.

Rejected:
- **Role only; launch is separate** — Definition is pure persona/capability. The cli/auth/model is chosen at dispatch time (or by a default), so one role can run on codex OR claude.
- **Launch recipe only** — Thin: a named, reusable spawn preset (cli + auth + model + cwd + permissions). No persona — the brief comes from the task card.

**How should a team get assembled for a given task?** → chose **Lead agent recruits**.

Rejected:
- **Named preset teams** — You define teams explicitly ("plc-pipeline" = dev → reviewer → tester). A task is routed to a team by label or picked by hand. Predictable, easy to reason about.
- **Capability matching** — Agents declare capabilities; tasks declare needs (labels/touches). The dispatcher assembles an ad-hoc team from whoever matches. Flexible, less predictable.
- **Both: presets + fallback** — Named teams for known shapes of work; capability matching as the fallback when no preset fits. More to build, but covers the long tail.

**"Tasks of all shapes and sizes" — what decides how much agent firepower a task gets?** → chose **i like numner 2 and 3**.

Rejected:
- **Size field on the card** — Each task carries a size (S/M/L or points). Size maps to a team template: S = solo agent, M = dev+reviewer, L = full pipeline with research and test stages.
- **Human picks at dispatch** — The board offers you a team for each card and you confirm or change it. Nothing large spawns without you saying so.
- **Dispatcher infers it** — Derived from signals already on the card — touches breadth, blockedBy depth, acceptance-criteria count, labels. No new field to maintain.
- **Per-agent-team WIP only** — No sizing concept. Every task gets its team from routing; the only throttle is how many agents each team is allowed to run at once.

**Where do agent definitions live on disk, and in what format?** → chose **Markdown + frontmatter**.

Rejected:
- **JSON, like auth.json** — Global ~/.agentmux/agents.json, repo-local dashboard/agents.json. Matches the existing auth.json / resources.json / themes.json pattern the dashboard already loads and edits.
- **In the task store** — Keep them in .bytedesk/task-management/ alongside tasks, using the existing keyed store with its gates and event log. Definitions get history and SSE updates for free — but are repo-bound by nature.

## Consequences

_TODO: what this makes easy, what it makes hard, and what would have to be true to revisit it._