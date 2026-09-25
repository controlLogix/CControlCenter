---
id: "TM-014"
kind: "task"
status: "done"
created: "2026-09-25T16:04:44.691Z"
board: "controllogix/ccontrolcenter"
title: "Make skip accounting consistent across the python suites"
epic: "EP-002"
acceptance: [{"text":"All eleven python suites compute passed as testsRun minus failures minus skipped","done":true,"at":"2026-09-25T16:22:32.157Z"},{"text":"A skipped test prints a SKIP line at column zero so run_tests.sh:175 surfaces it in the gate output","done":true,"at":"2026-09-25T16:22:33.091Z"},{"text":"The seven patched suites still report their original pass counts with nothing skipped","done":true,"at":"2026-09-25T16:22:34.608Z"},{"text":"A deliberately skipped test is visible in the gate output and is not counted as a pass","done":true,"at":"2026-09-25T16:22:36.424Z"},{"text":"The shell-suite variant, where a zero-assertion skip scores as success, is either fixed the same way or recorded as accepted with a reason","done":true,"at":"2026-09-25T16:22:37.871Z"}]
evidence: [".bytedesk/task-management/evidence/TM-014.txt"]
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T17:31:39.016Z"
evidenceSources: {".bytedesk/task-management/evidence/TM-014.txt":{"source":"/tmp/phase0-evidence/TM-014.txt","sha256":"cc56ea534f9c73b4fc0797bfae4f0e3ce5d3613d79628e338011b07b020cd6f1","bytes":1596,"at":"2026-09-25T16:22:28.995Z"}}
assignee: "claude"
closed: "2026-09-25T16:22:41.611Z"
comments: [{"author":"main","ts":"2026-09-25T17:31:38.957Z","text":"Third instance of this defect family, found 2026-09-25 and fixed. The first two were inside the suites (seven python tallies counting a skip as a pass; test_frontend_agents.sh emitting an indented note the gate cannot grep). This one is in the GATE itself. Four suites - test_runsview.py, test_notify.py, test_runcards.py, test_warrant.py - end with plain unittest.main(verbosity=2) and report a bare OK rather than a tally. run_tests.sh:183 allows that with the case 0:OK|0:OK\\ *, whose second alternative exists so shapes like OK (expected failures=1) pass. But unittest also prints OK (skipped=1), which that glob accepts too, and the grep for ^SKIP at :175 cannot see it because the text is OK (skipped=1), not a line beginning SKIP. So a skipped test in any of those four counted as a pass AND was invisible. run_tests.sh now surfaces that shape as a SKIP line rather than reclassifying it: a skip is an unknown, not a failure, and a gate that goes red on every skip stops being read - the same reasoning that put a SKIP line rather than a tally change into the python suites. Verified by summary shape: OK passes silently; OK (expected failures=2) passes silently, because an expected failure is not a skip; OK (skipped=1) passes but is now surfaced; passed 12, failed 1 still fails."}]
---

Found while hunting the silent-skip bug class on 2026-09-25. **Latent, not active** - worth being precise, because my first read of this was wrong and the correction matters.

Eleven python suites end with a hand-rolled tally. Four of them - `test_chatter.py`, `test_pn_dcp.py`, `test_codesys_panel.py`, `test_github_panel.py` - already compute `result.testsRun - failed - len(result.skipped)`. They are the four that actually call `skipTest()`, and they were written correctly.

The other seven used `result.testsRun - failures`, which counts a skipped test as a passed one. **None of those seven currently calls `skipTest`**, so nothing is being miscounted today. The defect is that the formula is wrong and the codebase disagrees with itself: add one `skipTest` to any of the seven and the gate silently reports it as a pass.

I initially claimed this was actively wrong, using `test_chatter.py` as evidence. That was a mistake: `test_chatter.py:175-178` does its own nvm discovery, so it found node and never skipped. "passed 11" was eleven genuinely-run tests.

**Fix applied.** All seven now use the same formula as the other four, and print one `SKIP <test> - <reason>` line per skipped test. That shape was chosen deliberately: `run_tests.sh:182` matches the last line against `0:*"failed 0"`, anchored at the end, so appending ", skipped N" to the tally would reclassify every skip as a suite FAILURE - too blunt, since a skip is an unknown rather than a failure. But `run_tests.sh:175` already greps `'^SKIP '` and surfaces those lines, so this reuses a mechanism that exists instead of adding one.

Patched: `test_agentcli.py`, `test_agentdefs.py`, `test_enip.py`, `test_modbus_poll.py`, `test_modbus_rtu.py`, `test_netscan.py`, `test_teamcli.py`.

Related: the shell suites have the same shape of hazard. `test_frontend_agents.sh:12-14` prints a skip note, emits `passed 0, failed 0` and exits 0, which `run_tests.sh:182` scores as success with zero assertions. Currently masked because nvm discovery works.