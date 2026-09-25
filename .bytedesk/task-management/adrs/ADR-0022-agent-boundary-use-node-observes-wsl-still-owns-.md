---
id: "ADR-0022"
kind: "adr"
status: "proposed"
created: "2026-09-25T13:59:28.440Z"
board: "controllogix/ccontrolcenter"
title: "Agent boundary: use Node observes, WSL still owns (Recommended)"
epic: "EP-001"
decisionKey: "50ef2e8e1e9b"
date: "2026-09-25"
updated: "2026-09-25T13:59:28.467Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-25.
The question asked was: Where does the Node backend stop and the existing WSL agent coordination begin?

## Decision

**With voice scrapped, what is the right-side blade now?** → chose **i like #1 , but it should be configurable in the settings, or in the blade itself. intuitive and modular.**.

Rejected:
- **Text agent console (Recommended)** — Same slide-out, driven by typing. Live conversation with agents, streaming responses you can stop mid-flight, trade tickets and PLC write confirmations as cards. Everything you specified minus the microphone.
- **Console plus command palette** — The agent conversation, plus a keyboard-driven palette for navigation and actions so the blade is also how you drive the app without a mouse.
- **Status and confirmation surface only** — No conversation. The blade shows what agents are doing, what needs your approval, and holds the confirm-to-commit cards. Chat stays in the terminal where it already works.
- **Scrap the blade too** — Voice was the reason for it. Drop the whole slide-out and put agent status and confirmations into the existing views instead.

**Where does the Node backend stop and the existing WSL agent coordination begin?** → chose **Node observes, WSL still owns (Recommended)**.

Rejected:
- **Node owns dispatch, WSL owns execution** — Node becomes the scheduler and queue; WSL tmux remains where agents actually run. More capability in the UI, but two things now decide what runs and they can disagree.
- **Node takes over coordination entirely** — Port the agentmux coordination logic into the Node backend, WSL becomes just a process host. Cleanest end state, and it rewrites the part of the system that currently works reliably.

## Consequences

_TODO: what this makes easy, what it makes hard, and what would have to be true to revisit it._