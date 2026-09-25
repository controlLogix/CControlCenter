---
id: "ADR-0023"
kind: "adr"
status: "proposed"
created: "2026-09-25T14:25:11.223Z"
board: "controllogix/ccontrolcenter"
title: "Host split: use API in WSL, field on Windows"
epic: "EP-001"
decisionKey: "b2fe05c0083f"
date: "2026-09-25"
updated: "2026-09-25T14:25:11.248Z"
---

## Context

Captured from an AskUserQuestion during a Claude Code session on 2026-09-25.
The question asked was: The plan puts the Node API and Python sidecar on Windows, with WSL untouched. But today the dashboard runs *inside* WSL: `dashboard/restart.sh:2` says "Run from the repo root inside WSL", `cc.db` lives at `$AGENTMUX_HOME` (`~/.agentmux`), and `server.py:907` shells `tmux -L agentmux` directly. Moving the API to Windows means SQLite over the 9p WSL/Windows boundary (a real corruption hazard) and `taskmgmt/coordination.py:51` losing its `127.0.0.1:8787` POST path. Meanwhile the field modules turn out to need no raw sockets — `profinet.py` is a schema/diff over imported DCP output, `ecat_diag.py` goes over ADS/TCP — so only serial Modbus RTU genuinely wants Windows. Where should each half live?

## Decision

**The plan puts the Node API and Python sidecar on Windows, with WSL untouched. But today the dashboard runs *inside* WSL: `dashboard/restart.sh:2` says "Run from the repo root inside WSL", `cc.db` lives at `$AGENTMUX_HOME` (`~/.agentmux`), and `server.py:907` shells `tmux -L agentmux` directly. Moving the API to Windows means SQLite over the 9p WSL/Windows boundary (a real corruption hazard) and `taskmgmt/coordination.py:51` losing its `127.0.0.1:8787` POST path. Meanwhile the field modules turn out to need no raw sockets — `profinet.py` is a schema/diff over imported DCP output, `ecat_diag.py` goes over ADS/TCP — so only serial Modbus RTU genuinely wants Windows. Where should each half live?** → chose **API in WSL, field on Windows**.

Rejected:
- **API on Windows + WSL broker** — Keeps the plan's Windows API, but adds a third process: a thin WSL-side broker that owns cc.db and tmux and speaks HTTP to the API. Honest about the boundary, but it is a second sidecar the plan doesn't budget for, and every board read becomes a network hop.
- **All on Windows, cc.db moves** — cc.db relocates to a Windows path; WSL agents reach it only over HTTP (coordination.py already speaks HTTP, so that path survives). Requires WSL mirrored networking for 127.0.0.1 to work both ways, and tmux reads go through wsl.exe — the quoting minefield the wsl-cli skill exists for.
- **Everything in WSL** — Simplest boundary — one host, one filesystem, no cross-OS anything. Costs serial COM port access for Modbus RTU and puts the field stack behind WSL2's NAT on the plant network, which may or may not matter depending on how you actually use the IIOT tab.

**The blade is specified as a text agent console whose mode YAML lists `mcp:` servers and `agents:`. But there is no agent runtime in this repo — no Anthropic SDK, no API client; the agents are the `codex` and `claude` CLIs living in tmux panes, and MCP servers are configured per-CLI. Something has to actually be an MCP client for `mcp: [codesys_rt, modbus, drawio]` to mean anything. What runs the conversation?** → chose **Node hosts its own agent loop**.

Rejected:
- **Drives the existing tmux panes** — The blade types into the codex/claude panes and renders capture-pane output. No new runtime, no second API key, and it stays true to Contract 2's "WSL remains authoritative". The mode YAML's mcp/agents lists become CLI config the blade writes before launching a pane.
- **Headless claude -p per turn** — Each blade turn shells a one-shot `claude -p` with the mode's MCP config. Stateless and simple, no long-lived runtime to babysit. Loses conversation continuity across turns unless you thread a session id, and interruption means killing a process.
- **UI-only in the first cut** — The blade ships as navigation, run status and confirmation cards — the parts that need no agent at all — and the conversation panel lands later once the rest of the rewrite is standing. Defers the hardest decision without blocking Phases 0-3.

**`dashboard/ccboard.py:11-16` says it deliberately reimplements the bytedesk `task-management` plugin's model — same EP-/TM-/ADR- key prefixes, same status vocabulary — backed by SQLite in `cc.db`, because `dashboard/SPEC_CC.md` binds the project to stdlib Python with no pip. But `.bytedesk/task-management/` is that actual plugin, running right now with its own `tm` CLI and its own dashboard on :45268, and this very plan lives inside it. Two stores, one key namespace. Phase 3 says migrate "Board and Kanban" without saying which one. Which is canonical after the rewrite?** → chose **Plugin store wins, cc.db board retires**.

Rejected:
- **cc.db wins, plugin is upstream-only** — cc.db stays the operational store for this repo's own work — it already holds runs, claims and the journal alongside the board, so the board keeps its foreign keys. The plugin store stays as the place plans and ADRs are authored, and the two are not reconciled.
- **Keep both, bridge them** — The new UI shows one board assembled from both stores, with provenance on each card. Nothing migrates and nothing retires. Most work, and it makes the ambiguity permanent rather than resolving it — but it breaks nothing that currently works.
- **Decide later, out of scope** — Phases 0-2 touch neither store's schema, so this can wait until Phase 3 actually reaches the Board view. Record it as an open question and keep moving. Risk is that Phase 1's handler port bakes in cc.db assumptions that are expensive to unpick later.

**The plan is six phases: a rebrand, an 83-handler backend rewrite, an 8-view frontend rewrite, a mode system, a blade, an IIOT/Rockwell rebuild, a brokerage automation, and remote access. That is a multi-month roadmap, and a plan file that treats all of it as equally committed is a plan nobody can hold you to. How much should I write as executable detail versus recorded direction?** → chose **All six in full detail**.

Rejected:
- **Phases 0-2 executable, rest as direction** — Rebrand, Node backend + field sidecar, and modes + blade shell get task-level detail, acceptance criteria and a verification section. Phases 3-6 stay as a one-paragraph sketch each with their decisions recorded so they are not relitigated. Re-plan when Phase 2 lands and the ground has moved.
- **Phase 0-1 only** — Just the rebrand and the backend port, planned to the task level. Tightest and most honest — the 83-handler differ is the real risk and deserves the whole plan's attention — but it leaves the blade and modes, the things you actually want, entirely unplanned.
- **Rebrand, then jump to IIOT/Rockwell** — Do Phase 0, then go straight at the IIOT tab and the pycomm3/Rockwell work on the existing Python stack — the thing with the clearest concrete payoff — and defer the whole Node rewrite. Fastest route to something you use, at the cost of building on a monolith you have decided to replace.

## Consequences

**What this makes easy.** `tmux -L agentmux` stays a local binary call rather than
`wsl.exe` interop on every read; `cc.db` stays on ext4 where it already is;
`taskmgmt/coordination.py:51`'s POST to `127.0.0.1:8787` keeps working unchanged,
which it would not if the API moved to Windows under NAT; and `dashboard/restart.sh`
already launches the server inside WSL, so nothing about how it runs has to change.

**What this makes hard.** The API and the field sidecar are on different hosts, and
under default NAT they cannot reach each other at all — `127.0.0.1` from WSL does
not reach a Windows loopback listener, and neither does the gateway address, because
that listener is loopback-bound. That is `docs/wsl-networking.md`, and it makes
mirrored networking a prerequisite rather than a nicety. The task store also sits on
the other side of the mount, where inotify does not fire and `store.mjs` can break a
live lock across the boundary.

**One stated justification did not survive measurement, and the decision does not
rest on it.** This ADR's question said a Windows-hosted API would mean "SQLite over
the 9p WSL/Windows boundary (a real corruption hazard)". Tested on 2026-09-25 with
the settings `ccstore.connection()` uses (WAL, `foreign_keys=ON`, `timeout=5`), four
concurrent writers at 300 committed inserts each:

| Scenario | Result |
|---|---|
| 4 WSL processes, ext4 | 1200/1200 rows, 0 busy/locked, `integrity_check: ok` |
| 4 WSL processes, `/mnt/c` (9p) | 1200/1200 rows, 0 busy/locked, `integrity_check: ok` |
| **2 Windows + 2 WSL, one file on 9p** | **1200/1200 rows, all four writers present, `integrity_check: ok`** |

The third row is the one that would have shown the hazard, since WSL and Windows take
different locking primitives. It did not. The decision stands on the three reasons in
"what this makes easy", none of which depend on the SQLite claim.

Recorded rather than quietly dropped: a reason nobody checks gets cited later to
force a decision it never supported. Note this is a *different* failure from the 9p
behaviour this repo has genuinely measured — transient **EIO under gate load**, which
is why `run_tests.sh` runs from an ext4 clone and is what killed whole scans in
`netscan.py` (TM-013). That one is real. And one probe is not a proof: it covers
short transactions on a small database with no crash injection.

**What would have to be true to revisit it.** If mirrored networking proves
unworkable on this host — the VMware VMnet adapters are the open question — the
cross-host hop becomes a firewall-scoped bind to the WSL adapter rather than
loopback, and at that point putting both halves on one host again is worth
re-costing. Equally, if the field work stops needing COM ports, the split loses its
other leg.