---
id: "TM-060"
kind: "task"
status: "open"
created: "2026-09-26T02:06:22.196Z"
board: "controllogix/ccontrolcenter"
title: "The order pipeline: dry run by default, intent before the click, read-back after"
epic: "EP-003"
acceptance: [{"text":"local dry run makes zero browser calls, proved by a Playwright double that counts EVERY attribute access and asserts the counter is 0","done":false},{"text":"preview never clicks Place Order, proved by a patched click that RAISES if the locator equals the place button - the test cannot pass by accident","done":false},{"text":"A dry run writes a dry_run journal record and NO intent record","done":false},{"text":"The typed phrase is derived and encodes target and value, so muscle memory cannot commit a different order","done":false},{"text":"The confirmation is hash-bound with a 90 second expiry","done":false},{"text":"On unknown, no retry button is RENDERED - not disabled, not rendered","done":false},{"text":"A read-back mismatch arms the kill switch and offers 'open the broker in a real browser at the Orders page' instead of any automatic action","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T03:15:31.019Z"
session: "pool-tm-060"
---

Phase 5.4. research, OrderTicket, guardrails, DRY RUN, typed confirmation, kill
switch, intent record fsync'd BEFORE the click, submit, read-back, terminal
record.

TWO DISTINCT DRY RUNS, because conflating them is dangerous. 'local' is the
DEFAULT and makes ZERO browser calls. 'preview' is opt-in per ticket and drives
the venue's own preview page to capture its cost estimate, then navigates away -
never clicking Place Order. A dry run that silently drives a live order form is
not what most people mean by dry run, so the UI labels them differently.

Unknown means investigate, never auto-retry - the same words as enip.py:8-11.
A mismatch arms the switch and attempts NO automatic cancel: an auto-cancel is
another unconfirmed order action taken by software that has just demonstrated it
does not know what it did.