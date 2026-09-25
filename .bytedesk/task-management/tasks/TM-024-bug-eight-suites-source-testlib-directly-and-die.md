---
id: "TM-024"
kind: "task"
status: "done"
created: "2026-09-25T19:49:47.864Z"
board: "controllogix/ccontrolcenter"
title: "BUG: eight suites source testlib directly and die on a CRLF checkout"
epic: "EP-002"
acceptance: [{"text":"All eight scripts source testlib in a form that strips CR, so a CRLF testlib cannot break them","done":true,"at":"2026-09-25T19:59:58.794Z"},{"text":"A suite run against a deliberately CRLF testlib passes, and the old direct form is shown to exit 127 against the same file","done":true,"at":"2026-09-25T20:00:00.552Z"},{"text":"*.sh is pinned to LF in .gitattributes with the reason recorded","done":true,"at":"2026-09-25T20:00:01.793Z"},{"text":"check_line_endings.sh fails when a tracked shell script has CRLF, and names the file","done":true,"at":"2026-09-25T20:00:03.425Z"},{"text":"check_line_endings.sh fails if a script reverts to sourcing testlib without stripping CR","done":true,"at":"2026-09-25T20:00:04.363Z"},{"text":"The check is registered in run_tests.sh and the full gate is green","done":true,"at":"2026-09-25T20:00:05.498Z"}]
evidence: [".bytedesk/task-management/evidence/TM-024-tm024.txt"]
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T20:00:06.798Z"
evidenceSources: {".bytedesk/task-management/evidence/TM-024-tm024.txt":{"source":"/mnt/c/Users/Nick/AppData/Local/Temp/claude/C--Dev-agentmux/5748a917-ba3c-4a23-9c48-424b6c04104f/scratchpad/tm024.txt","sha256":"ed5217b0a3119869c7c8af5b1fbdee71cb412b24653df61aa3fcc69d483862ed","bytes":2546,"at":"2026-09-25T19:59:56.325Z"}}
assignee: "claude"
closed: "2026-09-25T20:00:06.763Z"
---

The sibling of TM-023 — same cause, different victim, and the one that hides itself better.

bash cannot source a CRLF file. `. dashboard/testlib.sh` fails with a carriage-return "command not found" on every line, every helper it defines goes missing, and the suite exits 127 having asserted nothing.

The repo already knows about this: every suite is invoked as `bash <(tr -d '\r' < script)`. That strips carriage returns from the script being **run** — it does nothing for a sibling that script **sources**. I first said three scripts did this; it is **eight**:

    check_test_failability.sh   demo_protocol.sh
    test_argguard.sh            test_frontend.sh
    test_lifecycle.sh           test_residue.sh
    test_takeover_recovery.sh   test_testlib.sh

`core.autocrlf` is true here, so a plain `git clone`, a branch switch, or a `git checkout -- .` produces the condition. I triggered it with the last of those while fixing the same class of problem for the task store, which is a fair measure of how easy it is to hit.

**What makes it worse than a normal breakage:** `run_tests.sh` reports the suite with no tally at all, because it died before printing one. The gate says a suite failed and shows nothing about why — and `test_frontend.sh`'s thirteen assertions simply do not exist that run.

**Fixed in three layers, because the pin alone is not a fix:**

1. `.gitattributes` pins `*.sh` to `text eol=lf`, so git stops producing the condition.
2. All eight now source via `. <(tr -d '\r' < dashboard/testlib.sh)`, so a CRLF testlib arriving by a route git does not control — a zip, an editor, a Windows share — still works. This is the layer that matters, because the pin only helps where git is involved.
3. `dashboard/check_line_endings.sh`, registered in the gate, fails loudly if any tracked `*.sh` or task-store document has CRLF, if either `.gitattributes` pin is missing, or if any script goes back to sourcing testlib without stripping CR.

**Verified both directions.** With `testlib.sh` deliberately converted to CRLF: the old direct form gives `exit=127` and `$'\r': command not found`; the new form gives `passed 13, failed 0`.