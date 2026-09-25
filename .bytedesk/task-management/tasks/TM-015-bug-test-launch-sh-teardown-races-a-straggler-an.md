---
id: "TM-015"
kind: "task"
status: "done"
created: "2026-09-25T16:15:06.887Z"
board: "controllogix/ccontrolcenter"
title: "BUG: test_launch.sh teardown races a straggler and fails the suite"
epic: "EP-002"
acceptance: [{"text":"test_launch.sh uses ignore_cleanup_errors so a straggler cannot fail a suite whose assertions passed","done":true,"at":"2026-09-25T16:22:45.388Z"},{"text":"The eight launch assertions still run and still pass","done":true,"at":"2026-09-25T16:22:47.711Z"},{"text":"Three consecutive standalone runs are green","done":true,"at":"2026-09-25T16:22:48.601Z"},{"text":"A full run_tests.sh gate is green with the change in place","done":true,"at":"2026-09-25T16:22:49.764Z"},{"text":"The reason is recorded in the source, so the parameter is not removed later as noise","done":true,"at":"2026-09-25T16:22:51.635Z"}]
evidence: [".bytedesk/task-management/evidence/TM-015.txt"]
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T16:22:55.196Z"
assignee: "claude"
evidenceSources: {".bytedesk/task-management/evidence/TM-015.txt":{"source":"/tmp/phase0-evidence/TM-015.txt","sha256":"07c012ad7c3c58c8159af23749723a5572f8769fc765faa8ad1c6961b071fe5a","bytes":1076,"at":"2026-09-25T16:22:43.015Z"}}
closed: "2026-09-25T16:22:55.163Z"
---

Found in gate run 5, 2026-09-25. Pre-existing; I had not touched this file.

    test_launch.sh   OSError: [Errno 39] Directory not empty: 'home'

The suite's eight assertions had all already passed. What failed was the teardown: `test_launch.sh:7` uses `tempfile.TemporaryDirectory(prefix='agentmux-launch-')` as a context manager, and on unwind `shutil.rmtree` walked `<root>/home` while a process spawned through the fake tmux was still writing into it.

**Load-dependent, not deterministic.** Standalone: 4 of 4 runs passed. It surfaced only when the gate ran alongside other work (a documentation capture and a Node-environment probe on the same box). That is the worst shape for a gate failure - it appears under exactly the conditions where you are least able to attribute it, and it reads as "the launch tests broke" when nothing about launching broke at all.

**Fix.** `ignore_cleanup_errors=True`, the parameter CPython added in 3.10 for this case (WSL here runs 3.12.3). A temp directory that will not delete is not a launch-harness defect, and leaked files are already `check_test_residue.sh`'s job - it has its own suite and its own accounting. Failing here instead just teaches people to re-run the gate until it goes green, which is how a gate stops being read.

Rejected: waiting for the spawned children before unwinding. The suite deliberately spawns through a fake tmux and does not track pids, so there is nothing to wait on without inventing bookkeeping the test does not otherwise need.