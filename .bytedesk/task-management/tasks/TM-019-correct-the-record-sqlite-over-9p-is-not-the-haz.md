---
id: "TM-019"
kind: "task"
status: "done"
created: "2026-09-25T17:28:09.505Z"
board: "controllogix/ccontrolcenter"
title: "Correct the record: SQLite over 9p is not the hazard the host split was justified with"
epic: "EP-002"
acceptance: [{"text":"The plan no longer claims SQLite-over-9p corruption as a justification, and states the measured result instead","done":true,"at":"2026-09-25T17:29:11.496Z"},{"text":"ADR-0023 carries a note that this specific justification did not survive measurement, without reopening the decision itself","done":true,"at":"2026-09-25T17:29:12.821Z"},{"text":"The reasons the host split actually rests on are written down: tmux locality, the inbound coordination.py POST path, and COM ports","done":true,"at":"2026-09-25T17:29:13.782Z"},{"text":"The distinction between this and the real, measured 9p EIO-under-load failure is explicit, so the genuine hazard is not discarded along with the false one","done":true,"at":"2026-09-25T17:29:15.083Z"},{"text":"The probe's limits are recorded: short transactions, small database, no crash injection","done":true,"at":"2026-09-25T17:29:16.567Z"}]
evidence: [".bytedesk/task-management/evidence/TM-019-tm019.txt"]
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T17:29:17.569Z"
evidenceSources: {".bytedesk/task-management/evidence/TM-019-tm019.txt":{"source":"/mnt/c/Users/Nick/AppData/Local/Temp/claude/C--Dev-agentmux/5748a917-ba3c-4a23-9c48-424b6c04104f/scratchpad/tm019.txt","sha256":"291130af8fb33e8f35428faf1545f87d610198977d926106e09a70a842680af3","bytes":2304,"at":"2026-09-25T17:29:09.612Z"}}
assignee: "claude"
closed: "2026-09-25T17:29:17.528Z"
---

Measured 2026-09-25, because Phase 1.2 is about to be built on this assumption.

ADR-0023 and the rewrite plan both justify putting the API in WSL partly on "SQLite over the 9p WSL/Windows boundary is a corruption hazard". **That claim does not survive measurement.**

Four concurrent writers, 300 committed inserts each, using exactly the settings `ccstore.connection()` uses (WAL, `foreign_keys=ON`, `timeout=5`):

| Scenario | Result |
|---|---|
| 4 WSL processes, database on ext4 | 1200/1200 rows, 0 busy/locked, `integrity_check: ok` |
| 4 WSL processes, database on `/mnt/c` (9p) | 1200/1200 rows, 0 busy/locked, `integrity_check: ok`, same wall-clock (3.7s vs 3.9s) |
| **2 Windows + 2 WSL processes, one file on 9p** | **1200/1200 rows, all four writers present, `integrity_check: ok`** |

The third row is the one that matters: WSL and Windows take different locking primitives, and that is the case where SQLite can quietly lose writes. It did not. Every writer reported 300 committed and all 1200 rows were present afterwards.

**The decision does not change, but its stated reason has to.** The host split stands on grounds that were always stronger and are independent of this:

- `server.py:907` shells `tmux -L agentmux` as a **local binary**; a Windows API needs `wsl.exe` interop for every read, which is the quoting minefield the `wsl-cli` skill exists for.
- `taskmgmt/coordination.py:51` POSTs to `127.0.0.1:8787` **from WSL**, which under NAT only reaches a WSL-side listener.
- `restart.sh:2` already launches the server inside WSL, and `cc.db` is already at `$AGENTMUX_HOME` on ext4.
- COM ports and plant-NIC proximity pull the *field* half to Windows, per `modbus_rtu.py:97-98`.

**Stated honestly, because one probe is not a proof.** This covers short transactions on a small database with no crash injection. It does not clear long transactions, WAL checkpoint contention, or a process killed mid-write. And it is a different failure from the one this repo genuinely has measured — **transient EIO under gate load**, which is why `run_tests.sh` must run from an ext4 clone and is what killed whole scans in `netscan.py` (TM-013).

Worth fixing because an unexamined justification gets cited later to block or force a decision it never actually supported.