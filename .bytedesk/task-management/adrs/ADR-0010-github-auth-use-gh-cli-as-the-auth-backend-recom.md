---
id: "ADR-0010"
kind: "adr"
status: "proposed"
created: "2026-09-24T12:59:15.138Z"
board: "controllogix/ccontrolcenter"
title: "GitHub auth: use gh CLI as the auth backend (Recommended)"
epic: "EP-001"
decisionKey: "5c150ef671d4"
date: "2026-09-24"
updated: "2026-09-24T12:59:15.167Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-24.
The question asked was: For the GitHub overhaul — how should "login" actually work? The project's standing posture is that no secret ever travels from the browser (secrets live in ~/.agentmux/env, 0600, entered in a terminal).

## Decision

**For the GitHub overhaul — how should "login" actually work? The project's standing posture is that no secret ever travels from the browser (secrets live in ~/.agentmux/env, 0600, entered in a terminal).** → chose **gh CLI as the auth backend (Recommended)**.

Rejected:
- **OAuth device flow, token stored server-side** — Page shows a user code + verification URL from GitHub's device endpoint, server polls for the token and writes it to ~/.agentmux/env 0600. Needs a registered OAuth App client_id configured in Settings first. Cleanest "login button" feel, but nothing works until you register the app.
- **PAT pasted into Settings** — A personal access token field in Settings, POSTed to the server and stored 0600. Simplest and immediate, but it breaks the no-secret-from-the-browser rule this codebase enforces everywhere else.

**Board item #9 — "freely movable" means which kind of movement?** → chose **Both: drag tasks between epics, drag epic cards anywhere (Recommended)**.

Rejected:
- **Semantic only — drag tasks between epics** — Task rows drag from one epic to another and reorder, persisted server-side through /api/board/move. Epic cards stay in a normal flow layout but become collapsible. Less code, nothing cosmetic to get out of sync.
- **Layout only — free positioning of cards** — Epic cards can be dragged anywhere on a canvas and the positions are remembered in this browser. Nothing changes server-side; task membership is still changed through the existing controls.

## Consequences

_TODO: what this makes easy, what it makes hard, and what would have to be true to revisit it._