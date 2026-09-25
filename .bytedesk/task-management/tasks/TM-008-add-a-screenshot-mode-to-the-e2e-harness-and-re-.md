---
id: "TM-008"
kind: "task"
status: "done"
created: "2026-09-25T15:19:55.350Z"
board: "controllogix/ccontrolcenter"
title: "Add a screenshot mode to the e2e harness and re-capture the five doc PNGs"
epic: "EP-002"
acceptance: [{"text":"dashboard/capture_docs.mjs and capture_docs.sh exist and reuse test_e2e.sh's find_playwright() unchanged","done":true,"at":"2026-09-25T16:22:04.264Z"},{"text":"The throwaway home is seeded so no screenshot shows an empty product","done":true,"at":"2026-09-25T16:22:05.792Z"},{"text":"All five docs/images PNGs are regenerated and each has a commit timestamp later than the visible-rebrand commit","done":true,"at":"2026-09-25T16:22:07.051Z"},{"text":"No regenerated PNG shows the old wordmark, checked by eye","done":true,"at":"2026-09-25T16:22:08.730Z"},{"text":"capture_docs is NOT wired into run_tests.sh","done":true,"at":"2026-09-25T16:22:09.787Z"},{"text":"Re-running the capture twice produces the same five views without manual steps","done":true,"at":"2026-09-25T16:22:11.221Z"}]
evidence: [".bytedesk/task-management/evidence/TM-008.txt"]
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T16:22:13.068Z"
evidenceSources: {".bytedesk/task-management/evidence/TM-008.txt":{"source":"/tmp/phase0-evidence/TM-008.txt","sha256":"a69a276aa3ee38316ae5e5a05e170398af46b4e39b6baf113f33025be63a0dd2","bytes":1551,"at":"2026-09-25T16:22:01.554Z"}}
assignee: "claude"
closed: "2026-09-25T16:22:13.034Z"
---

`docs/images/board.png`, `iiot.png`, `runs-view.png`, `settings-orchestration.png` and `status-feed.png` show the old brand in the **rendered UI**. They must be re-captured, not edited — and re-captured *after* the rename commits land, or they bake the old name straight back in.

`dashboard/test_e2e.mjs` already brings up a real dashboard on an ephemeral port with a throwaway `AGENTMUX_HOME` and a stub MQTT broker, and already navigates all five views. It has **zero `page.screenshot()` calls** and drives **Firefox** at 1400x950. So the cheapest correct route is a screenshot mode reusing that harness, which also makes the shots reproducible next time.

Seed the throwaway home from `seed_queue.py` plus a small board fixture — otherwise the screenshots are of an empty product.

**Keep it out of `run_tests.sh`**: ~450 KB of binary churning on every gate run is repo poison. It is an operator command.

Reuse `test_e2e.sh`'s `find_playwright()` verbatim — `:38-46` documents why a mismatched npx cache holding a Windows Playwright fails confusingly from WSL.