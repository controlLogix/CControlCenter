---
id: "TM-055"
kind: "task"
status: "done"
created: "2026-09-26T02:06:14.036Z"
board: "controllogix/ccontrolcenter"
title: "The selector registry, and why there is never a fallback locator"
epic: "EP-003"
acceptance: [{"text":"resolve() raises SelectorDrift and has no fallback path, proved by a test enumerating the public surface","done":true,"at":"2026-09-26T02:10:53.862Z"},{"text":"On drift: capture screenshot and DOM snapshot outside the repo, journal, session DEGRADED, kill switch ARMED, alert - and it does not return normally","done":true,"at":"2026-09-26T02:10:55.014Z"},{"text":"The kill switch is armed EVEN IF the evidence capture fails; a screenshot failing is not a reason to leave trading enabled","done":true,"at":"2026-09-26T02:10:56.263Z"},{"text":"verify_all() reports stale entries and never auto-updates one","done":true,"at":"2026-09-26T02:10:57.546Z"},{"text":"The module imports and is fully testable with no browser present; the capture function is injected","done":true,"at":"2026-09-26T02:10:58.924Z"},{"text":"No real Fidelity selector and no capture ever lands in the tree","done":true,"at":"2026-09-26T02:11:00.254Z"}]
evidence: [".bytedesk/task-management/evidence/TM-055.log"]
commits: ["2a1fc2b"]
blockedBy: []
blocks: []
actor: "main"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T02:13:18.036Z"
assignee: "main"
evidenceSources: {".bytedesk/task-management/evidence/TM-055.log":{"source":"/tmp/ev/TM-055.log","sha256":"932e89db47be442dfbad06602ec1c9d907fdaac3910cdb2a80f392ab9d1528ce","bytes":2158,"at":"2026-09-26T02:13:16.754Z"}}
closed: "2026-09-26T02:13:18.006Z"
---

Phase 5.3. A versioned selectors map from logical names to locators, each with a
probe and a lastVerified.

The design is one sentence: on an order form, guessing which button is Place
Order is how you submit something nobody authorised. So there is NEVER a fallback
locator and never 'click the next likely button'. That has to be ENFORCED, not
documented - a whitelist test over the public surface, so a new method that could
return a guessed locator fails until someone classifies it.

The map itself is operator-supplied runtime data and lives OUTSIDE the repo. The
shipped default carries placeholders only.