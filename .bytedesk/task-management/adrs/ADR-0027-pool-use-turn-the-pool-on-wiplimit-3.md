---
id: "ADR-0027"
kind: "adr"
status: "proposed"
created: "2026-09-26T03:02:51.151Z"
board: "controllogix/ccontrolcenter"
title: "Pool: use Turn the pool on, wipLimit 3"
epic: "EP-005"
decisionKey: "887ad67fdf94"
date: "2026-09-26"
updated: "2026-09-26T03:02:51.179Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-26.
The question asked was: A team can't run unsupervised as things stand: dispatch.enabled is false, the pool is off, and wipLimit is 3. Turning it on is the decision the plan deliberately left to you. What should I set up before you go?

## Decision

**A team can't run unsupervised as things stand: dispatch.enabled is false, the pool is off, and wipLimit is 3. Turning it on is the decision the plan deliberately left to you. What should I set up before you go?** → chose **Turn the pool on, wipLimit 3**.

Rejected:
- **Turn it on, raise wipLimit to 6** — More parallelism while you're away. Higher chance of two agents colliding on one file — this session already saw that risk and handled it by partitioning by file up front.
- **Leave the pool off; I dispatch by hand** — Nothing runs unattended. Safest, but means almost no progress while you're away — which is the opposite of what you asked for.
- **Turn it on, but only for a named safe set** — Pool runs only tasks I've tagged as low-blast-radius (tests, docs, pure-logic modules). Anything touching server.py, the gate, or field equipment waits for you.

**What should the team drive hardest first? This orders everything else.** → chose **UI fidelity — the React 1:1 port, PLC / IIOT depth, "Finish the Node port — differ, auth, store migration", "Polish what exists — motion, 3D on real hardware, field opacity"**.

Rejected:
- **UI fidelity — the React 1:1 port** — Work the 131-item parity manifest down: port views one at a time, delete each shell test in the same commit as its replacement. This is the largest single body of remaining work.
- **PLC / IIOT depth** — node-opcua as an optional feed (4.5), test_netscan.py (TM-050), the device tree and tag table ported with every honesty affordance intact. Closest to what the product is actually for.
- **Finish the Node port — differ, auth, store migration** — TM-039 differ, TM-040 the first-ever auth on 8787, TM-041 board-store migration. Unglamorous, but Phase 3 and Phase 6 are both blocked behind it.
- **Polish what exists — motion, 3D on real hardware, field opacity** — Verify the 3D scene renders, tune --field-opacity on a real GPU, extend motion across the remaining views. Smallest scope, most visible.

**You said 1:1, nothing lost. How strictly should the team read that against shipping new features?** → chose **Parity first, per view — port it whole or not at all**.

Rejected:
- **Parity and new features together, per view** — Each view gets its 1:1 port plus its new motion/3D work in one pass. Fewer trips through each file, but a half-done view looks finished.
- **New features first on the live dashboard, port later** — Keep improving the vanilla UI (which operators use today) and treat the React port as background work. Lowest risk to you day-to-day.

**While you're away, what may agents do on their own? The repo is PUBLIC, which makes some of these irreversible.** → chose **Commit and push to the public remote, May run wsl --shutdown for TM-011, May edit files outside the repo**.

Rejected:
- **Commit to main, do not push** — What this session has been doing. ~65 commits already sit unpushed. Everything stays local and reviewable.
- **Commit and push to the public remote** — Work becomes visible immediately. Irreversible: anything pushed to a public repo is public, and history rewrites don't reliably un-publish it.
- **May edit files outside the repo** — E.g. the marketplace plugin fix for the notification noise. These changes are global, affect your other projects, and a marketplace refresh silently reverts them.
- **May run wsl --shutdown for TM-011** — Needed twice to finish the networking spike and exercise its rollback. Kills your dashboard, every agent pane, and any running work at that moment.

## Consequences

_TODO: what this makes easy, what it makes hard, and what would have to be true to revisit it._