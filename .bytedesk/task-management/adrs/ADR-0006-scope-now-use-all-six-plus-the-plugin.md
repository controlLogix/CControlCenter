---
id: "ADR-0006"
kind: "adr"
status: "proposed"
created: "2026-09-23T18:29:25.463Z"
board: "controllogix/ccontrolcenter"
title: "Scope now: use All six plus the plugin"
epic: "EP-001"
decisionKey: "f6d1f4a2ed09"
date: "2026-09-23"
updated: "2026-09-23T18:29:25.492Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-23.
The question asked was: How much of the six stages should this implementation round actually cover?

## Decision

**How much of the six stages should this implementation round actually cover?** → chose **All six plus the plugin**.

Rejected:
- **Stages 1–3 (the roster)** — Definitions exist, are enforced, and are editable from the dashboard. Ships a complete, useful feature and stops before any team machinery. Stages 4–6 get planned but not built this round.
- **Stage 1 only** — The loader, the read-only roster endpoint and view. Smallest possible proof — byte-identical behaviour with zero definitions on disk. Reassess before anything else.
- **Stages 1–4** — Everything up to and including roster proposal and approval, but no teams actually spawning. Stage 4 is what de-risks stage 5, so this leaves you positioned for it.

**How should the work actually be executed?** → chose **Dogfood it with agentmux panes, but make sure all of our tasks are on the board**.

Rejected:
- **Me, sequentially, checkpointing per stage** — I build each stage in order in this session, run the gate after each, and stop for your review before the next. Slowest wall-clock, easiest to follow and correct.
- **Parallel subagents where independent** — I fan out Claude Code subagents on genuinely independent pieces (loader vs UI vs tests), then integrate and run the gate myself. Faster; I own the merge.
- **Dogfood it with agentmux panes** — Spawn real codex/claude panes via agentmux to do the work, driving them as the harness intends. Tests the harness while building it — but the team features being built don't exist yet, so it's manual coordination.
- **File the board tasks, then build** — First create the tasks under EP-001 with acceptance criteria and blockedBy edges, then work them one at a time. Best paper trail; adds a filing step up front.

**Still open from last round: what happens when a `.agentmux` definition and a `.claude/agents` one share a name?** → chose **Error, like any other collision**.

Rejected:
- **Shadow, and report it (recommended)** — The .agentmux one wins; the .claude one is listed as shadowed in the UI. Keeps decision 5 strict where it was decided (.agentmux vs .agentmux stays an error) without breaking existing repos on first load.
- **Shadow silently** — Nearest wins, nothing reported. Matches how .gitignore and CLAUDE.md layer. Least noise, but a definition you think is live may not be.

**Part B — the marketplace plugin. When?** → chose **in parallel and dogfood these as well**.

Rejected:
- **After the CLI surface settles** — The skills wrap agentmux commands, so building them before those commands exist means rewriting them. Build the plugin once the stages it wraps are done.
- **In parallel, skills stubbed** — Scaffold the plugin, manifest and catalog entry now so the structure and eval harness exist; fill each skill's body as its underlying command lands.
- **Separate effort entirely** — Keep it out of this plan's scope — it lives in a different repo with its own publish gates. Plan and build it as its own piece of work later.

## Consequences

_TODO: what this makes easy, what it makes hard, and what would have to be true to revisit it._