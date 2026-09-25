---
id: "ADR-0021"
kind: "adr"
status: "proposed"
created: "2026-09-25T13:57:01.760Z"
board: "controllogix/ccontrolcenter"
title: "Framework: use React + Vite + TanStack Router (Recommended)"
epic: "EP-001"
decisionKey: "a971c45832ca"
date: "2026-09-25"
updated: "2026-09-25T13:57:01.791Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-25.
The question asked was: Which frontend framework for the Node rewrite?

## Decision

**Which frontend framework for the Node rewrite?** → chose **React + Vite + TanStack Router (Recommended)**.

Rejected:
- **SvelteKit** — Closest in spirit to the existing hand-written DOM code, smallest bundles, excellent with live SSE streams. Smaller ecosystem for the terminal and finance widgets you need.
- **Next.js** — React with routing, server actions and a build pipeline out of the box. Adds an SSR model that buys nothing on a loopback dashboard and complicates the SSE and terminal work.
- **SolidJS** — Fine-grained reactivity, excellent for dashboards with many live values updating at once. Smallest community of the four.

**How far do you want the voice stack to go locally, given the 4090?** → chose **scrap the voice plan altogether.**.

Rejected:
- **Local STT and TTS, cloud LLM (Recommended)** — Whisper large-v3 in, Kokoro or XTTS out, both on the 4090. Audio never leaves the machine. The reasoning still goes to Claude, so the blade is as smart as this session.
- **Fully local including the LLM** — Add a local model for the blade so nothing at all leaves the box. Total privacy and works offline. Noticeably weaker reasoning than Claude, and the 4090 gets busy.
- **Hybrid, routed by mode** — PLC mode runs fully local because it touches equipment; investing and research mode use Claude for reasoning. The YAML profile decides per mode.
- **Local STT, cloud TTS** — Whisper locally, but a cloud voice for the most natural speech back. Only the synthesized text leaves, never your microphone.

**Where does the rewritten stack actually run?** → chose **i like #1, we need to not hammer the existing framework from WSL, make sure this agent coordiantion**.

Rejected:
- **Windows host, WSL for agents (Recommended)** — Node backend and Python sidecar on Windows where the 4090, the CODESYS toolchain and the field network live. tmux agent panes stay in WSL as they are now.
- **All in WSL** — Node, Python and agents together in Ubuntu. One POSIX environment, simpler scripts. Complicates GPU passthrough for voice and serial or field-network access for Modbus RTU.
- **Split by concern** — Node backend in WSL, Python protocol sidecar on Windows for direct hardware and serial access, talking over the WSL bridge. Each piece where it works best, one more network hop to debug.

**What should I produce from this interview?** → chose **Full implementation plan document**.

Rejected:
- **The hardened prompt (Recommended)** — A single sharpened prompt capturing every decision, constraint and non-goal from this interview, ready for you to run in plan mode or hand to another agent. Literal answer to the reverse-prompt ask.
- **Hardened prompt plus task store** — The prompt, plus an epic, ADRs for the eight decisions made here, and task cards written into the task-management store so the board reflects the real plan.
- **Prompt now, everything else after review** — Hand back the prompt first, you read it and correct it, then I write the epic, ADRs and cards from the corrected version.

## Consequences

_TODO: what this makes easy, what it makes hard, and what would have to be true to revisit it._