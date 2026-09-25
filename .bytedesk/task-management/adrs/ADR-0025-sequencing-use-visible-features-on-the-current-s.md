---
id: "ADR-0025"
kind: "adr"
status: "proposed"
created: "2026-09-25T18:56:09.404Z"
board: "controllogix/ccontrolcenter"
title: "Sequencing: use Visible features on the current stack"
epic: "EP-002"
decisionKey: "5a7d1788fd19"
date: "2026-09-25"
updated: "2026-09-25T18:56:09.431Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-25.
The question asked was: The plan's foundation-first sequencing puts every visible feature behind a Node backend and a React rewrite. That is defensible, and it is also why you have seen almost nothing. What should I build next?

## Decision

**The plan's foundation-first sequencing puts every visible feature behind a Node backend and a React rewrite. That is defensible, and it is also why you have seen almost nothing. What should I build next?** → chose **Visible features on the current stack**.

Rejected:
- **Foundation first, as planned** — Scaffold the Node API, port the 45 handlers behind the differ, then React, then the features. Nothing you can look at for a long time, but nothing gets built twice. This is what ADR-0020 D4 chose.
- **Blade first, as a vertical slice** — Build just the agent console end to end on the current stack — the thing you asked for most specifically — and leave modes, IIOT and investing until the Node work. One visible feature, done properly, rather than four half-built.
- **IIOT and Rockwell first** — Go straight at the field work — pycomm3 tag browsing, UDT decoding, the live tag table with honest value age — on the existing IIOT panel. The most concrete payoff for actual controls work, and the part with real hardware behind it.

**Everything is on `phase-0-rebrand`; `main` is untouched at 6afd65b. This repo's own habit is 79 commits straight to main.** → chose **Merge to main now**.

Rejected:
- **Keep it on the branch** — Leave main untouched so you can review the 7 commits first and merge yourself. Nothing on main changes until you say so.

## Consequences

_TODO: what this makes easy, what it makes hard, and what would have to be true to revisit it._