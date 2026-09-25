---
id: "TM-006"
kind: "task"
status: "done"
created: "2026-09-25T15:19:32.222Z"
board: "controllogix/ccontrolcenter"
title: "Rename the three ccc-* agent definitions and their orchestrator binding"
epic: "EP-002"
acceptance: [{"text":"The three ccc-*.md agent definitions are renamed to agentmux-*.md with git mv, filenames and bodies both","done":true,"at":"2026-09-25T16:21:39.042Z"},{"text":"agentmux.sh:2241 ORCH_DEFAULT_AGENT is updated in the same commit as the rename, along with :2230 and :2352","done":true,"at":"2026-09-25T16:21:40.190Z"},{"text":"The three netcap-*.md definitions are left untouched","done":true,"at":"2026-09-25T16:21:41.123Z"},{"text":"The orchestrator resolves its definition after the rename, verified by running it rather than by inspection","done":true,"at":"2026-09-25T16:21:42.870Z"},{"text":"test_agentdefs.py and test_agentcli.py pass","done":true,"at":"2026-09-25T16:21:43.891Z"},{"text":"run_tests.sh is green","done":true,"at":"2026-09-25T16:21:45.023Z"}]
evidence: [".bytedesk/task-management/evidence/TM-006.txt"]
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T16:21:47.157Z"
evidenceSources: {".bytedesk/task-management/evidence/TM-006.txt":{"source":"/tmp/phase0-evidence/TM-006.txt","sha256":"fea4d1c827510251064abbd027256d7d30463a638e2d917131a89503a12fb3f9","bytes":1012,"at":"2026-09-25T16:21:36.669Z"}}
assignee: "claude"
closed: "2026-09-25T16:21:47.122Z"
---

Three agent definitions carry the brand in their **filenames**: `.agentmux/agents/ccc-frontend-dev.md`, `ccc-frontend-reviewer.md`, `ccc-orchestrator.md`. The three `netcap-*.md` files are untouched.

The trap the draft plan missed: **`agentmux.sh:2241` reads `ORCH_DEFAULT_AGENT="ccc-orchestrator"`**, outside the 62-file rebrand scope. Renaming the files without that line breaks orchestration **silently** — the orchestrator simply fails to resolve its definition. Related sites at `agentmux.sh:2230` and `:2352`.

`agentmux.sh` is otherwise declared off-limits by this plan; this one line is the deliberate exception, and it must land in the same commit as the `git mv`.

Check `test_agentdefs.py` and `test_agentcli.py` for the literal names before committing.