---
id: "ADR-0019"
kind: "adr"
status: "proposed"
created: "2026-09-25T13:50:25.941Z"
board: "controllogix/ccontrolcenter"
title: "Rockwell split: use Layered by job (Recommended)"
epic: "EP-001"
decisionKey: "b3ebffbcf6da"
date: "2026-09-25"
updated: "2026-09-25T13:50:25.970Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-25.
The question asked was: How do the three Rockwell paths divide the work?

## Decision

**Orders have to reach a market somehow. Which mechanism places them?** → chose **i like #3 but i want charts and trade view / chart view**.

Rejected:
- **Fidelity read-only + API broker (Recommended)** — Scrape Fidelity for positions and history so your real portfolio is visible. Execute through a broker with a documented API (Alpaca, Tradier, IBKR), paper mode by default. Fully programmatic, no ToS violation. Cost: execution lives at a second broker.
- **Staged orders, you click the final button** — Dashboard does research, sizing and builds the exact order ticket, then hands it to you to confirm in Fidelity's own UI. Nothing automated can place a trade by accident, which matters with an always-on mic. One manual step per trade.
- **Full browser automation of Fidelity orders** — Playwright drives Fidelity's web UI to submit orders. One account, hands-free. Against Fidelity's terms, breaks on any UI change, needs credentials and 2FA handled, and a bug places a real trade with real money.
- **Paper trading only for now** — Build the whole pipeline against a simulated account and decide real execution after watching it behave for a few weeks. Defers the risky call without blocking any of the work.

**How do the three Rockwell paths divide the work?** → chose **Layered by job (Recommended)**.

Rejected:
- **pycomm3 first, OPC UA later** — pycomm3 replaces logix.py now for fastest capability gain; enip.py stays only as the write-audit path. OPC UA deferred to a later phase once the Node backend is stable.
- **OPC UA as the primary layer** — One vendor-neutral client for everything, with CIP and pycomm3 only where OPC UA cannot reach. Cleanest long-term architecture, but needs an OPC UA server configured on the Rockwell side before anything works.
- **Extend enip.py, others as fallback** — Keep the hand-written stack as the primary and add the missing tag browse and UDT decode yourself. pycomm3 and OPC UA exist only as cross-checks. Most control, most work, no new runtime dependency.

**What does music production mode actually do? Pick everything that belongs.** → chose **" scrap music production, this was a type, sorry replace with PLC mode"**.

Rejected:
- **DAW control by voice** — Transport, track arm, clip launch, tempo, mixer moves in Ableton or Reaper over OSC and MIDI. Hands stay on the instrument while the blade drives the session.
- **Idea capture to inbox** — Hum or sing into the blade, get pitch-tracked MIDI plus a tagged voice memo in a project inbox that survives into the DAW. Catches the idea before it evaporates.
- **Library and project index** — Searchable sample library, stem separation, reference-track shelf, project versioning and a view of what state each track is in.
- **AI assist** — Chord and arrangement suggestions, mastering-chain advice, generated MIDI variations, lyric and structure co-writing driven from the blade.

**What is the voice blade allowed to do on its own? Pick every authority it gets.** → chose **Run agents and read status, Trades and industrial writes with confirm, Navigate and dictate**.

Rejected:
- **Navigate and dictate** — Switch views, filter, search, fill forms, read the screen back. Nothing that changes system state. The safe floor.
- **Run agents and read status** — Spawn agents, dispatch tasks, approve or reject gates, get spoken status on runs. This is the agentmux core made hands-free.
- **Industrial reads only, never writes** — Ask for a tag value, a device scan, a PLC status out loud. Modbus writes, Logix writes and CODESYS forces stay keyboard-only with the existing typed confirmation.
- **Trades and industrial writes with confirm** — Voice can initiate a trade or a PLC write, but every one requires a second explicit confirmation before it executes. Maximum reach, and the one combination that can cost money or move equipment.

## Consequences

_TODO: what this makes easy, what it makes hard, and what would have to be true to revisit it._