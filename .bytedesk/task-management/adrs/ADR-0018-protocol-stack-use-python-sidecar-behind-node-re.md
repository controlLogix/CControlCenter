---
id: "ADR-0018"
kind: "adr"
status: "proposed"
created: "2026-09-25T13:47:26.860Z"
board: "controllogix/ccontrolcenter"
title: "Protocol stack: use Python sidecar behind Node (Recommended)"
epic: "EP-001"
decisionKey: "2cd4d3312c56"
date: "2026-09-25"
updated: "2026-09-25T13:47:26.888Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-25.
The question asked was: Going Node end to end — what happens to the six Python industrial-protocol modules that have no npm equivalent?

## Decision

**Going Node end to end — what happens to the six Python industrial-protocol modules that have no npm equivalent?** → chose **Python sidecar behind Node (Recommended)**.

Rejected:
- **Port all of it to Node, no Python left** — Rewrite Modbus, EtherNet/IP, PROFINET DCP, EtherCAT, CODESYS and MQTT in TypeScript. Genuinely one language, one process model. Expect the protocol work alone to dominate the project timeline, and every bug surfaces as a misbehaving field device rather than a stack trace.
- **Port the easy ones, sidecar the hard ones** — Modbus TCP/RTU and MQTT move to Node (mature npm packages exist). PROFINET DCP, EtherCAT diagnostics, EtherNet/IP and CODESYS stay Python behind IPC permanently. Mixed, but each piece sits where the ecosystem actually supports it.

**What does the Fidelity / investing tab actually connect to? There's no official Fidelity retail API.** → chose **i like 1 and 3, but #1s no broker link should have a link with #3**.

Rejected:
- **Market data + research, no broker link** — Charts, watchlists, fundamentals, news, options chains from a real market-data API. Positions imported from a Fidelity CSV export when you want them. Zero ToS exposure, zero credential handling, and it's the part that actually serves 'researching before I invest'.
- **Read-only positions via browser automation** — A Playwright session logs into Fidelity with your credentials and scrapes balances, positions and order history into the dashboard. Real portfolio view. Brittle against UI changes, needs your credentials stored somewhere, and 2FA makes it fragile.
- **Read positions AND place orders** — Full automation including order entry. Maximum capability. Automating a brokerage UI is against Fidelity's terms, and a bug in an always-on voice-driven dashboard could place a real trade. I'd want a hard typed confirmation on every order regardless of your answer here.
- **I have a specific MCP in mind** — You've seen a particular Fidelity MCP server — name it and I'll evaluate what it actually does, what it needs, and whether it's safe to wire in before we design around it.

**Which direction for the Rockwell work? logix.py already does EtherNet/IP explicit messaging.** → chose **1, 2, 4**.

Rejected:
- **Extend the existing CIP client (Recommended)** — Add what's missing and documented as missing: tag browsing, UDT template discovery and member decoding, connected messaging, multi-service requests, chassis routing. No new dependency, no license, builds on code that already works against your hardware.
- **Adopt pycomm3** — Mature MIT library that already does tag browse, UDT decode, and struct read/write. You'd get full tag-level access quickly and delete most of logix.py. Adds a dependency and throws away working in-repo code that was written deliberately.
- **Logix Designer SDK (Studio 5000)** — The licensed Windows/.NET SDK — program upload/download, online edits, ACD file manipulation, automated project generation. The only path to actual program-level automation. Requires an installed licensed Studio 5000, is Windows-only, and logix.py's header explicitly rules it out, so that decision gets reversed on the record.
- **OPC UA / FactoryTalk Linx** — Go through OPC UA instead of raw CIP. Vendor-neutral, works across your CODESYS and Rockwell gear with one client, good npm support (node-opcua) which suits the Node rewrite. Needs a server configured on the Rockwell side.

**When you switch modes (investing / research / music / future), what changes?** → chose **Everything, defined in YAML (Recommended)**.

Rejected:
- **Views, tools and voice persona** — A mode gates the navigation, the MCP servers, and how the blade talks to you — but theme and layout stay constant so the app always feels like one product.
- **Voice context only** — The UI never changes; the mode only shapes what the voice assistant knows, which tools it can reach, and how it responds. Simplest to build, and modes stop being a UI concern entirely.

## Consequences

_TODO: what this makes easy, what it makes hard, and what would have to be true to revisit it._