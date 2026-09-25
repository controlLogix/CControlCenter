---
id: "TM-016"
kind: "task"
status: "done"
created: "2026-09-25T16:27:32.870Z"
board: "controllogix/ccontrolcenter"
title: "The failability gate covers 5 of 54 suites, and cannot cover a python one"
epic: "EP-002"
acceptance: [{"text":"check_test_failability.sh accepts python suites as well as shell ones, with a failure count that understands unittest's FAIL:/ERROR: shape","done":true,"at":"2026-09-25T16:31:03.662Z"},{"text":"A suite that crashes rather than failing cleanly is still refused as proof, as it is today","done":true,"at":"2026-09-25T16:31:04.809Z"},{"text":"test_netscan.py is registered against a base where the pre-fix netscan.py is present and fails the minimum","done":true,"at":"2026-09-25T16:31:06.148Z"},{"text":"test_frontend_storage.sh is registered, or converted to testlib's ok/bad/finish so it can be","done":true,"at":"2026-09-25T16:31:07.722Z"},{"text":"The checker's own ten self-tests still pass, including the HEAD-base and non-ancestor refusals","done":true,"at":"2026-09-25T16:31:08.974Z"},{"text":"The table's coverage is recorded so the gap between registered and running suites is visible rather than assumed","done":true,"at":"2026-09-25T16:31:10.390Z"}]
evidence: [".bytedesk/task-management/evidence/TM-016-tm016.txt"]
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T16:31:41.823Z"
assignee: "claude"
evidenceSources: {".bytedesk/task-management/evidence/TM-016-tm016.txt":{"source":"/mnt/c/Users/Nick/AppData/Local/Temp/claude/C--Dev-agentmux/5748a917-ba3c-4a23-9c48-424b6c04104f/scratchpad/tm016.txt","sha256":"d84180ff8a95781a53ff12fc52d961c5f8a8901f09ac1b6d223b158a05d5d350","bytes":3004,"at":"2026-09-25T16:31:40.051Z"}}
closed: "2026-09-25T16:31:41.788Z"
---

Found 2026-09-25 while trying to register two new suites.

`check_test_failability.sh` is the meta-gate that proves suites can actually FAIL - its own comment is the argument for it: if the shared assertions cannot fail on the bug shapes they exist for, every suite using them is decoration. It runs each registered suite against a pinned historical base where the bug was still present and requires a minimum number of failures.

**Two structural limits mean it protects a small slice.**

1. **`:64` accepts only `.sh`**: `[[ ! "$suite" =~ ^test_[A-Za-z0-9_]+\.sh$ ]]` rejects the row outright. So **no python suite can ever be registered** - which is most of the gate, including every protocol suite (`test_enip.py`, `test_logix.py`, `test_modbus_poll.py`, `test_field_panels.py` at 188 assertions) and the new `test_netscan.py`.

2. **`:98` counts only testlib's shape**: `grep -cE '^  FAIL([[:space:]]|$)'`. A shell suite that asserts through node and throws - like the new `test_frontend_storage.sh` - exits non-zero with zero `  FAIL` lines, and `:107` then correctly refuses it, because a crashed suite is not proof of discrimination.

The registered table is five rows: `test_argguard.sh`, `test_run.sh`, `test_lifecycle.sh` (x2 bases), `test_coordination.sh`, `test_residue.sh`. Fifty-four suites run in the gate.

**This is the bug class that gets worse as features are added**, which is exactly why it is worth fixing rather than noting: every new suite added during the Node rewrite will be a suite nobody has proved can fail. Both suites added in Phase 0 had their failability proven **by hand** - `test_netscan.py` fails 5 of 13 against the pre-fix `netscan.py`, and `test_frontend_storage.sh` fails against an `index.html` with no migration block - and neither proof is standing.

Sequencing note: `.py` support needs a second failure-counting shape, because a unittest suite prints `FAIL:`/`ERROR:` at column zero rather than testlib's two-space `  FAIL`. `run_tests.sh:186-192` already had to learn exactly this distinction and its comment explains why matching only one shape hid what broke.