---
id: "TM-020"
kind: "task"
status: "done"
created: "2026-09-25T18:58:36.637Z"
board: "controllogix/ccontrolcenter"
title: "BUG: the gate's dashboard restore restores the home but not the working directory"
epic: "EP-002"
acceptance: [{"text":"The restore brings the dashboard back up with the repo root as its working directory, not the gate clone's","done":true,"at":"2026-09-25T22:01:44.554Z"},{"text":"A dashboard serving from a directory other than the repo root says so visibly rather than looking normal","done":true,"at":"2026-09-25T22:01:44.758Z"},{"text":"The takeover marker records the working directory alongside the home, so a restore can verify both","done":true,"at":"2026-09-25T22:01:44.964Z"},{"text":"Running the full gate leaves the operator's dashboard serving the repo's own files, verified against /proc/<pid>/cwd afterwards","done":true,"at":"2026-09-25T22:01:45.171Z"},{"text":"A regression test covers the restored working directory, not just the restored home","done":true,"at":"2026-09-25T22:01:45.375Z"}]
evidence: [".bytedesk\\task-management\\evidence\\TM-020-1790373444399.log",".bytedesk\\task-management\\evidence\\TM-020-1790373720840.log"]
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T22:02:22.202Z"
evidenceSources: {".bytedesk\\task-management\\evidence\\TM-020-1790373444399.log":{"source":null,"sha256":"6b0aee58cf940872e153c427bd228b8cfdbdb5155ca58831e5b8ecad933ae87d","bytes":3223,"at":"2026-09-25T21:57:24.400Z"},".bytedesk\\task-management\\evidence\\TM-020-1790373720840.log":{"source":null,"sha256":"a1ebf93cd9cd721d93dc47f1c29652694af89c163a000e86b0b0cc6fe01c464a","bytes":2990,"at":"2026-09-25T22:02:00.841Z"}}
assignee: "claude"
closed: "2026-09-25T22:02:22.185Z"
---

Hit for real on 2026-09-25, and the operator saw it as "the interface doesn't show my changes".

`run_tests.sh` leases port 8787, moves the operator's dashboard onto a throwaway `AGENTMUX_HOME`, and restores it afterwards. `suite_server.py` and the `.dashboard-takeover.json` marker (shipped at `6afd65b`) make the *home* survive a killed gate — that work is sound and did its job.

**But the restore brings the server back up from whatever working directory it is invoked in.** `restart.sh` runs `nohup setsid python3 dashboard/server.py` relative to `$PWD`, and the gate runs from an ext4 clone. So after a gate run:

    pid 2374302
      cwd:  /home/nick/gate-agentmux        <- the throwaway clone
      HOME: /home/nick/.agentmux            <- correctly restored

The home was restored; the *code being served* was not. `server.py` serves `app.js`, `index.html`, `style.css` and `assets/` relative to its own location, so the operator's dashboard was serving a snapshot of a disposable directory — one that was then deleted and recreated several times underneath the running process.

**Why it is worse than it looks.** The takeover marker reports clean, because by its own definition the restore succeeded. Nothing warns. The dashboard answers on 8787 and looks entirely normal; it is simply serving different files than the ones on disk in the repo. An operator editing `dashboard/app.js` sees no effect and has no reason to suspect the server.

**Detection is cheap.** The dashboard already knows where it was started from. The page or `/api/agents` could report the server's own `cwd`, and a mismatch against the repo root is a one-line banner — the same class of honesty the load-failure banner at `index.html:9-19` already provides for scripts that fail to load.

Immediate recovery, for the record: kill the process whose `cwd` is not the repo (by PID, never by name), then restart from the repo root.