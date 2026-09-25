---
id: "TM-027"
kind: "task"
status: "done"
created: "2026-09-25T21:04:00.854Z"
board: "controllogix/ccontrolcenter"
title: "BUG: three suites read /mnt/c and fail with 9p EIO under gate load"
epic: "EP-002"
acceptance: [{"text":"Every filesystem call against a /mnt/c path in these three suites is guarded, so an EIO cannot escape as a bare OSError","done":true,"at":"2026-09-25T21:38:59.890Z"},{"text":"A suite whose subject is unreachable SKIPs with a stated reason instead of ERRORing","done":true,"at":"2026-09-25T21:39:00.122Z"},{"text":"run_tests.sh can never report a negative passed count; a suite that produced no summary is reported as not having run","done":true,"at":"2026-09-25T21:39:00.342Z"},{"text":"test_agentdefs.py does not depend on the operator's real ~/.claude/agents directory","done":true,"at":"2026-09-25T21:41:29.716Z"},{"text":"The gate gives the same verdict on two consecutive runs of an unchanged tree","done":true,"at":"2026-09-25T21:57:06.288Z"}]
evidence: [".bytedesk\\task-management\\evidence\\TM-027-1790372463168.log",".bytedesk\\task-management\\evidence\\TM-027-1790373420051.log"]
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T21:57:06.710Z"
evidenceSources: {".bytedesk\\task-management\\evidence\\TM-027-1790372463168.log":{"source":null,"sha256":"d3ea9cce95ba212703e627eb846459170b905becab85c782815bf3798791a713","bytes":3609,"at":"2026-09-25T21:41:03.169Z"},".bytedesk\\task-management\\evidence\\TM-027-1790373420051.log":{"source":null,"sha256":"558d1b9cb89f7c5bd9877b661c0b39acf85d662a3266c2c9017e56be71dc112a","bytes":946,"at":"2026-09-25T21:57:00.052Z"}}
assignee: "claude"
closed: "2026-09-25T21:57:06.692Z"
---

Found 2026-09-25 by running the gate twice on two adjacent commits. **The same gate, on trees differing only in the write-journal refactor, gave "all suites passed" and then "4 suite(s) failed".** Three of those four failures had nothing to do with the change.

This is R29 / TM-013 again — `[Errno 5] Input/output error` from the 9p mount — but in a place TM-013 did not reach. TM-013 fixed `netscan.py`, which called `Path.exists()` on `/mnt/c/Windows/System32/ARP.EXE`. These three suites read `/mnt/c` for a different reason: they reach **outside the repo entirely**, into the plugin marketplace and the user's `~/.claude`.

| Suite | Path it reads | What happened |
| --- | --- | --- |
| `test_orchestration_plugin.py:41` | `/mnt/c/theWork/ADAG-CSAI/marketplace/plugins/agentmux-orchestration` | `shutil.copytree` raised `shutil.Error` listing **22** separate EIO failures; `setUpClass` died, so the whole class never ran. Reported `passed -1, failed 1` |
| `test_plugin_skills.py` | same marketplace path | `OSError: [Errno 5]` — no assertions at all, no summary line |
| `test_agentdefs.py:273` | `/home/nick/.claude/agents/hr-recruiter.md` | `Path.is_file()` raised EIO mid-iteration |

**Why this matters more than the individual failures.** The gate runs from an ext4 clone precisely so 9p cannot make it lie. These three step back out onto 9p and reintroduce exactly that, so "all suites passed" becomes partly a matter of luck — and `passed -1` is a summary line that cannot be true, which means the runner's own accounting is being fed nonsense.

It is also the same shape as TM-014 and TM-012: a suite that does not run is not a suite that passed, and the difference has to be visible.

**The fix is the one TM-013 established, applied to a different call site.** `Path.exists()`, `Path.is_file()` and `shutil.copytree` all re-raise any errno that is not ENOENT/ENOTDIR/EBADF/ELOOP, so on 9p under load they raise out of code that reads as total. Every filesystem call against a `/mnt/c` path needs a try/except, and a suite whose *subject* is unreachable should SKIP with a reason rather than ERROR — a skip that says why is information; an EIO traceback is noise that trains people to re-run the gate until it goes green.

`test_agentdefs.py` has a second problem worth separating: it reads the operator's real `~/.claude/agents`, so its result depends on a directory outside the repo that the gate does not control.

**Not caused by, and not fixed by, the write-journal work in TM-026.** The fourth failure in that run (`test_ecat_diag.py`) was mine and is fixed.