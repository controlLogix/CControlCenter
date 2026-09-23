---
id: "ADR-0005"
kind: "adr"
status: "proposed"
created: "2026-09-23T17:22:45.837Z"
board: "controllogix/ccontrolcenter"
title: "Marketplace: use An existing repo we own"
epic: null
decisionKey: "a91b84150d3b"
date: "2026-09-23"
updated: "2026-09-23T17:22:45.864Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-23.
The question asked was: Which marketplace is "ours"? The installed `bytedesk` one belongs to ByteDeskAI, not you.

## Decision

**Which marketplace is "ours"? The installed `bytedesk` one belongs to ByteDeskAI, not you.** → chose **An existing repo we own**.

Rejected:
- **New marketplace repo of our own** — Create a fresh marketplace repo (e.g. adag-marketplace) with .claude-plugin/marketplace.json, publish our plugin there, and add it with /plugin marketplace add. Fully ours to control.
- **Host it inside C:\Dev\agentmux** — The agentmux repo doubles as the marketplace — the plugin lives beside the harness it drives, so a version of the plugin always matches the agentmux it wraps. No second repo to keep in sync.
- **Contribute to bytedesk** — Send it upstream to ByteDeskAI's marketplace alongside agentconf/fleet/agent-orchestration. Requires push access or a PR, and the plugin becomes public.

**What does the plugin actually ship, beyond skill markdown?** → chose **Skills + hooks + MCP tools**.

Rejected:
- **Skills + hooks** — Skills drive the workflows by calling the agentmux and tm CLIs; hooks enforce the gates. No MCP server to run or version. Matches how task-management gates TaskCreate today.
- **Skills only** — Pure markdown wrapper over the agentmux CLI. Cheapest to build, publish and review; nothing to break at runtime. No enforcement — the skills describe the workflow, the CLI enforces it.

**Which skills should the suite contain?** → chose **Agent CRUD + roster, Team compose + dispatch, Config + doctor, Review + merge gate**.

Rejected:
- **Agent CRUD + roster** — Create/edit/remove an agent definition (absorbing what hr-recruiter does today), list the merged roster across global/repo/.claude scopes, and show collisions.
- **Team compose + dispatch** — Propose a roster for a card, approve it, hire the lead, watch the team, collect results. The orchestration core.
- **Config + doctor** — Read/set dispatch config (WIP, poll, enabled, per-role caps), plus a doctor that validates every definition, checks auth methods resolve, and reports what this host can actually launch.
- **Review + merge gate** — The lead's integration step as its own skill: per-member worktrees reviewed, merged, conflicts surfaced, evidence attached to the card.

**The skill-creator eval loop spawns baseline AND with-skill runs per test prompt, then grades them. How far do we take it?** → chose **Full loop on every skill**.

Rejected:
- **Full loop on the risky ones** — Full eval treatment for the skills where a wrong answer costs real work (dispatch, merge gate); triggering-description optimization only for the simple ones. Pragmatic middle.
- **Triggering optimization only** — Run improve_description.py so each skill fires on the right prompts and not the wrong ones. Skips behavioural grading — cheap, catches the most common skill failure.
- **Write evals, run later** — Author evals/evals.json for every skill as part of the build, but don't execute the loop now. The suite exists and is runnable when you want it.

## Consequences

_TODO: what this makes easy, what it makes hard, and what would have to be true to revisit it._