---
id: "ADR-0004"
kind: "adr"
status: "proposed"
created: "2026-09-23T17:14:40.168Z"
board: "controllogix/ccontrolcenter"
title: "Page power: use Relax it — let the page hire"
epic: null
decisionKey: "527b65f467c8"
date: "2026-09-23"
updated: "2026-09-23T17:14:40.195Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-23.
The question asked was: The dashboard is read-only about actions by design. Adding/removing agent definitions is a write. How far does the page's new power go?

## Decision

**The dashboard is read-only about actions by design. Adding/removing agent definitions is a write. How far does the page's new power go?** → chose **Relax it — let the page hire**.

Rejected:
- **Definitions + approval only** — The page may create/edit/delete agent definitions and tick "roster approved" on a card. It still never spawns — the pool (a CLI process) sees the approval and does the hiring. The existing rule survives intact.
- **Definitions only** — Strictest. The page edits definitions; approval happens at the CLI (`agentmux dispatch --approve TM-42`). Nothing about running agents changes in the UI.

**How deeply should an agent definition constrain the worker it launches?** → chose **Also enforce tool limits**.

Rejected:
- **Brief prose + model/auth** — Persona text goes into the brief file dispatch.py already writes; the definition also picks cli/auth/model, which dispatch currently ignores. Works for codex, claude and grok identically. No changes to agentmux.sh.
- **Real system prompt** — Add --prompt / --append-system-prompt to agentmux.sh spawn so the persona is system-level, not something the model can drift from. Stronger, but per-CLI flag work and grok/codex differ.

**A lead plus two workers are on one card. Today a claim is all-or-nothing over the card's `touches`, held by one live tmux identity. Where does the team work?** → chose **A worktree each, lead merges**.

Rejected:
- **Lead owns claim, subclaims workers** — The lead takes the card's claim and hands each worker a disjoint subset of files. One worktree, no merge step, and the existing claim interlock keeps them off each other's files.
- **Sequential stages, one workspace** — Team members are stages, not concurrent: dev finishes and releases, then reviewer runs, then tester. One workspace, one claim handed along. Simplest and safest; no parallelism within a card.

**You said you want the per-task lead as an option with a default fallback. When does a lead actually get spawned?** → chose **Always a lead**.

Rejected:
- **Only when roster > 1** — Inferred roster of one agent → that agent runs solo, exactly like today's dispatch. Two or more → a lead is spawned to coordinate them. The fallback is current behaviour, so nothing regresses.
- **Only when you ask** — Solo worker is always the default. A lead appears only if you tick it on the card (or the card carries a `team:` label). Most conservative; you opt in every time.
- **Lead only above a size threshold** — Configurable: inferred size L (or >N touches / >N acceptance criteria) spawns a lead; anything smaller goes solo regardless of roster size.

## Consequences

_TODO: what this makes easy, what it makes hard, and what would have to be true to revisit it._