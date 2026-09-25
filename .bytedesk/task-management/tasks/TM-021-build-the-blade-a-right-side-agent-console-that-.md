---
id: "TM-021"
kind: "task"
status: "done"
created: "2026-09-25T19:14:25.185Z"
board: "controllogix/ccontrolcenter"
title: "Build the blade: a right-side agent console that reflows"
epic: "EP-002"
acceptance: [{"text":"Pinned narrows the main content rather than covering it, proven by measured geometry not by assertion","done":true,"at":"2026-09-25T19:32:16.176Z"},{"text":"Hidden returns the full width to the main content","done":true,"at":"2026-09-25T19:32:17.786Z"},{"text":"The three states, the width and the chosen panel survive a reload","done":true,"at":"2026-09-25T19:32:19.174Z"},{"text":"No CSS transform is applied to the blade, and the re-fit is dispatched on transitionend","done":true,"at":"2026-09-25T19:32:20.448Z"},{"text":"The endpoint carries the same guards as every other mutating route: POST only, 415 on wrong content-type, 403 cross-origin, bounded body","done":true,"at":"2026-09-25T19:32:22.106Z"},{"text":"A confirmation renders as a card with a derived typed phrase, and committing requires that exact phrase","done":true,"at":"2026-09-25T19:32:23.781Z"},{"text":"blade.js does not throw when registered against the DOM stub, and the full gate is green","done":true,"at":"2026-09-25T19:32:25.006Z"}]
evidence: [".bytedesk/task-management/evidence/TM-021-tm021.txt"]
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T19:32:26.702Z"
assignee: "claude"
evidenceSources: {".bytedesk/task-management/evidence/TM-021-tm021.txt":{"source":"/mnt/c/Users/Nick/AppData/Local/Temp/claude/C--Dev-agentmux/5748a917-ba3c-4a23-9c48-424b6c04104f/scratchpad/tm021.txt","sha256":"473478fe991feb907db8eb261504e1fcf438088d7165c922e8f9707c0be93b6f","bytes":1925,"at":"2026-09-25T19:32:12.355Z"}}
closed: "2026-09-25T19:32:26.643Z"
---

Built on the current Python + vanilla-JS stack, per the operator's sequencing choice (ADR-0025) — the plan's foundation-first order put every visible feature behind a Node backend and a React rewrite, which is why none of them existed yet.

**Pinned genuinely reflows, and that is the point.** The blade is a third flex child of `.shell`, not an overlay. Measured against the live dashboard:

    pinned : blade 420px, .views 923px, blade right edge 1400
    hidden : .views 1343px

The main content narrows and gives the width back. That matters for exactly the two things this page is for — a terminal grid measures its own container to choose a font size, and a chart measures its own container to choose a scale. A panel sitting on top of either is useless.

**No CSS transform anywhere on it.** `fitmatrix.js` records that a transform resamples terminal glyphs into mush. Width is animated instead, and the re-fit fires on `transitionend` rather than per frame — four earlier fitting attempts oscillated because a measurement taken at the current size fed the choice of the next size. `agentmux:blade-resize` is dispatched once the width settles, so the terminal grid listens rather than polls.

**Three states**, hidden / overlay / pinned, with the width drag-resizable (snapped to 20px, clamped 320–900), keyboard-reachable, and persisted per browser. `Ctrl+\`` toggles; `Ctrl+Shift+\`` swaps pinned and overlay. Below 900px the pinned state overlays instead, because it cannot reflow to a useful width.

**Conversation survives navigation** because the element is never unmounted — switching views hides a `.view`, it does not touch `.shell`'s third child.

**Confirmations are cards, never dialogs.** One typed shape for every kind, because the questions a PLC write and a trade ask are identical: who, what exactly, what would it do, does it still match what was rendered, is the kill switch clear. The typed phrase is *derived from the action* — `MCU-PLC:bDoorOpen=TRUE`, `BUY 100 AAPL LIMIT 189.50` — so muscle memory cannot commit a different write than the one on screen, and it is reserved for the kinds that cost money or move equipment. A dialog was rejected: it blocks the page, cannot render a dry run, and cannot be left open while you go and check something at the equipment.

**The console's runtime is interim and says so.** ADR-0023 chose the Claude Agent SDK inside the Node API; there is no Node API yet, so `POST /api/blade/send` shells `claude -p`, one invocation per turn. Its limits are stated in the source rather than discovered later: no continuity between turns, no tool use, no streaming. It is **not** `send-keys` into a pane — it starts a fresh headless process and cannot reach an existing agent's session, so "terminals stay read-only" is untouched.