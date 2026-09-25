---
id: "ADR-0026"
kind: "adr"
status: "proposed"
created: "2026-09-25T22:47:10.993Z"
board: "controllogix/ccontrolcenter"
title: "Surface: use Windows desktop toasts"
epic: "EP-002"
decisionKey: "5c1585ad0502"
date: "2026-09-25"
updated: "2026-09-25T22:47:11.021Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-25.
The question asked was: Where are you actually seeing the hundreds of notifications?

## Decision

**Where are you actually seeing the hundreds of notifications?** → chose **Windows desktop toasts**.

Rejected:
- **In the terminal / session** — Text injected into the Claude Code conversation by hooks — status messages, git-link warnings, board reminders. Fixed by making the hooks quiet unless they have something actionable to say.
- **The agentmux dashboard** — The queue badge, inbox, chatter or Status tab filling up with items. Fixed in the dashboard's own feed and badge logic.
- **Orca's UI** — The claude-hook.cmd wired to every Claude Code event POSTs to a local Orca app on every tool call. That is outside this repo, but I can tell you exactly what it is sending.

**What should the bar be for interrupting you?** → chose **Only when I must act (Recommended)**.

Rejected:
- **That, plus completions** — Also tell me when a task or epic finishes, even if nothing needs my input. More signal, more volume.
- **Errors and failures only** — The strictest setting: nothing unless something broke or is blocked. Completions and progress stay silent.
- **Let me pick per event kind** — Build a settings surface listing every event kind with a toggle, defaulting everything off, so you tune it yourself rather than accepting my judgement.

## Consequences

_TODO: what this makes easy, what it makes hard, and what would have to be true to revisit it._