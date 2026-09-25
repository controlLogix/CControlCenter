---
id: "ADR-0017"
kind: "adr"
status: "proposed"
created: "2026-09-25T13:44:49.471Z"
board: "controllogix/ccontrolcenter"
title: "UI overhaul: use Full rewrite, Node backend too"
epic: "EP-001"
decisionKey: "90a5d57ca722"
date: "2026-09-25"
updated: "2026-09-25T13:44:49.499Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-25.
The question asked was: How should the UI overhaul actually happen, given 172KB of working vanilla JS with a passing test suite behind it?

## Decision

**How should the UI overhaul actually happen, given 172KB of working vanilla JS with a passing test suite behind it?** → chose **Full rewrite, Node backend too**.

Rejected:
- **Strangler fig (Recommended)** — Add Vite + a component framework as the new shell. Build the NEW surfaces natively in it — voice blade, investing tab, overhauled IIOT — and migrate the 8 existing views one at a time, keeping their tests green as each moves. Python backend untouched. Slowest to 'fully modern', but nothing is ever broken.
- **Full frontend rewrite, keep Python** — Rewrite all 8 views in React/Svelte/Next in one pass. Python server stays as the API. Fastest to a coherent modern UI, but invalidates the 37 shell frontend tests at once and you fly blind until they're rewritten.
- **Modernize in place, no framework** — Keep vanilla but add a build step, ES modules, web components, and a design-token pass on the 72KB CSS. Preserves every test. Cheapest, but you won't get the componentized feel you're describing and the blade gets harder to build.

**What exposure model do you want for "full access remotely"? The dashboard can write to live PLCs.** → chose **Tailscale serve, tailnet-only (Recommended)**.

Rejected:
- **Split: Funnel read-only, tailnet for writes** — Public Funnel URL serves only read views (charts, board, status). Anything that mutates — Modbus writes, Logix tag writes, CODESYS forces, agent dispatch — is refused unless the request arrives over the tailnet. More work, but genuinely safe to share a link.
- **Tailscale Funnel, full access** — Public internet URL with full read/write. Requires building real auth (sessions, MFA), rate limiting, and an audit trail before it's defensible — the current CSRF design assumes loopback and would need replacing outright. Highest risk, most convenient.
- **Tailnet + hard write-confirm everywhere** — Tailnet-only transport, plus a typed/confirmed second step on every industrial write regardless of origin. Belt and braces for the case where voice or a remote phone tap could trigger a PLC write by accident.

**How should the voice CLI in the blade capture and speak? You said "dynamically listening".** → chose **Always-on wake word, local models (Recommended)**.

Rejected:
- **Push-to-talk, local models** — Hotkey or click to talk instead of continuous listening. Same local Whisper/Piper stack, far simpler, no wake-word false positives, no idle CPU. Not "dynamically listening" as you described it.
- **Always-on, cloud STT/TTS** — Deepgram/AssemblyAI streaming in, ElevenLabs/OpenAI out. Best latency and accuracy, natural barge-in. Your microphone audio continuously leaves the machine to a third party, and it costs per minute.
- **Browser Web Speech API** — Zero infrastructure — the browser does it. Chrome-only, quality is mediocre, audio goes to Google, and continuous mode drops out regularly. Fine as a week-one placeholder, wrong as the destination.

**How far should the CCC to agentmux rename reach? ~140 files mention it, mostly history.** → chose **Live surfaces only (Recommended)**.

Rejected:
- **Everything, history included** — Also rewrite ADRs, the event log, audit journals and status files so no trace of CCC remains anywhere. Clean, but events.jsonl is append-only evidence the dashboard replays, and rewriting it risks breaking the board's own state.
- **Live surfaces + one historical note** — Rename everything active, and add a single line to the ADR index noting CCC was the former name of agentmux, so old records stay readable without being edited.

## Consequences

_TODO: what this makes easy, what it makes hard, and what would have to be true to revisit it._