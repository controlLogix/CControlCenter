---
id: "TM-047"
kind: "task"
status: "open"
created: "2026-09-26T02:04:38.410Z"
board: "controllogix/ccontrolcenter"
title: "Terminals in React: an unmounted island, and the fit matrix that proves it"
epic: "EP-002"
acceptance: [{"text":"xterm is created once in a useRef and a re-render never re-creates it, proved by a test that counts constructions","done":false},{"text":"The terminals route is never unmounted while the app is open; scrollTop survives a view switch and a pin/unpin","done":false},{"text":"fitmatrix.js is ported as a Playwright spec asserting legible, capped, STABLE, crisp and predicted","done":false},{"text":"Moves to @xterm/xterm - the vendoring existed only because there was no build step","done":false},{"text":"open_log is ported verbatim: regular files only, reject st_nlink greater than 1, O_NOFOLLOW, size caps","done":false},{"text":"The tmux argv allowlist permits display geometry and nothing else, asserted by a G3-style boot self-test","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "main"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T02:04:38.454Z"
---

Phase 3, and the single thing most likely to be got wrong. xterm is a useRef
island created ONCE and never re-created by render - the React translation of
invariant 2. The terminals route is NEVER unmounted while the app is open (use a
hidden keepalive), which is the React translation of the viewScroll bug.

fitmatrix.js records FOUR earlier attempts that all oscillated, every one because
a measurement taken at the current size fed the choice of the next size. So
nothing measures the viewport - everything uses ResizeObserver on its own
container - and the refit debounces to transitionend, not per frame. A pinned
blade animating its column would reproduce that exactly.

No CSS transform on a terminal: it resamples glyphs into mush.

Terminals is also the view that proves ADR-0023 was right. With the API inside
WSL, tmux -L agentmux is a local socket and capture-pane a local process; on
Windows every one is an interop round trip.