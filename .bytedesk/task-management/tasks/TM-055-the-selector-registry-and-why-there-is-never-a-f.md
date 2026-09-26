---
id: "TM-055"
kind: "task"
status: "open"
created: "2026-09-26T02:06:14.036Z"
board: "controllogix/ccontrolcenter"
title: "The selector registry, and why there is never a fallback locator"
epic: "EP-003"
acceptance: [{"text":"resolve() raises SelectorDrift and has no fallback path, proved by a test enumerating the public surface","done":false},{"text":"On drift: capture screenshot and DOM snapshot outside the repo, journal, session DEGRADED, kill switch ARMED, alert - and it does not return normally","done":false},{"text":"The kill switch is armed EVEN IF the evidence capture fails; a screenshot failing is not a reason to leave trading enabled","done":false},{"text":"verify_all() reports stale entries and never auto-updates one","done":false},{"text":"The module imports and is fully testable with no browser present; the capture function is injected","done":false},{"text":"No real Fidelity selector and no capture ever lands in the tree","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "main"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T02:06:14.117Z"
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