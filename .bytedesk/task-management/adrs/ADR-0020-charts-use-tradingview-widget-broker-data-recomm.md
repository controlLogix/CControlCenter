---
id: "ADR-0020"
kind: "adr"
status: "proposed"
created: "2026-09-25T13:51:40.697Z"
board: "controllogix/ccontrolcenter"
title: "Charts: use TradingView widget + broker data (Recommended)"
epic: "EP-001"
decisionKey: "5029097f50cf"
date: "2026-09-25"
updated: "2026-09-25T13:51:40.726Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-25.
The question asked was: What draws the market charts, and where does the data come from?

## Decision

**What does a long research session need to actually be long?** → chose **Durable session state, Background agents that keep going, Findings become artifacts, Source capture and citation**.

Rejected:
- **Durable session state** — A session survives restarts and days. Sources, findings and open threads persist to disk and reload exactly where you left off.
- **Background agents that keep going** — Dispatch research agents that run while you do other things, report in through the blade, and queue findings for review.
- **Findings become artifacts** — Output lands as structured documents in the repo (research packs, ADRs, task cards) rather than scrollback you lose.
- **Source capture and citation** — Every claim tracks back to a URL or file with a timestamp, so a session from three weeks ago is still auditable.

**What draws the market charts, and where does the data come from?** → chose **TradingView widget + broker data (Recommended)**.

Rejected:
- **lightweight-charts, self-rendered** — TradingView's open-source charting library, you own the rendering and the data pipeline. Full control of overlays and theming, more work, no vendor iframe.
- **Scraped from Fidelity alongside orders** — Since Playwright is already logged into Fidelity for orders, pull chart data and quotes from the same session. One source, no extra API. Brittle and rate-limited.
- **Custom D3 charts** — Built from scratch to match the dashboard design system exactly. Most control over look, most effort, and financial charting has a lot of hard-won detail in it.

**How does the blade behave as a piece of UI?** → chose **Persists across view changes, "Push and pin, not just overlay", Barge-in and interrupt, Confirmations surface in the blade**.

Rejected:
- **Persists across view changes** — The conversation and listening state survive navigation. Switching from IIOT to investing does not reset the blade.
- **Push and pin, not just overlay** — Can pop out as an overlay or pin open and reflow the main content so charts and terminals are not covered while you work.
- **Barge-in and interrupt** — You can talk over its response and it stops speaking immediately. Without this, always-on voice is unusable in practice.
- **Confirmations surface in the blade** — Trade tickets and PLC write confirmations render as cards in the blade with an explicit press-to-commit, not as browser dialogs.

**What order should this ship in? There are six workstreams here.** → chose **Foundation first (Recommended)**.

Rejected:
- **Blade first as a vertical slice** — Build the voice blade end to end against the existing Python server to prove the hardest unknown works, then do the Node rewrite underneath it.
- **Investing tab first** — Ship the tab you most want, learn the patterns from it, then generalize into modes and the rewrite. Highest early payoff, most rework.
- **Rebrand and IIOT first** — Finish what is already half-built. Rename everything, extend the Rockwell stack, then take on the rewrite and new features with a clean base.

## Consequences

_TODO: what this makes easy, what it makes hard, and what would have to be true to revisit it._