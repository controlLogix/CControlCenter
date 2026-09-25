---
id: "TM-032"
kind: "task"
status: "open"
created: "2026-09-25T22:48:02.529Z"
board: "controllogix/ccontrolcenter"
title: "Raise the bar on Windows toasts to \"only when I must act\""
epic: "EP-002"
acceptance: [{"text":"Every call site of notify.deliver is checked against the bar its own docstring states, and any that fires for progress rather than for a decision is changed or removed","done":false},{"text":"A toast fires only when a person must act: a run waiting on a human, a review gate, a dead worker, a finished orchestration","done":false},{"text":"Claude Code's own desktop notifications are separated from this repo's in the write-up, so the operator knows which setting governs which","done":false},{"text":"The volume is measured before and after, from events.jsonl, rather than asserted","done":false},{"text":"git_link_unattributed stops firing for every git command that names no task, or stops being surfaced at all","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T22:48:02.601Z"
---

Asked and answered 2026-09-25. Parked with the investigation already done, so whoever picks this up does not repeat it.

**The complaint:** "hundreds of notifications that seem to be BS."
**The surface, per the operator:** Windows desktop toasts.
**The bar, per the operator:** only when they must act.

### What was ruled out by measurement, not assumption

| Candidate | State |
| --- | --- |
| `ntfy` push (the plugin's dispatcher) | `"ntfy": {}` — every kind off by default |
| `webhooks` | `[]`, `webhooksAllowRemote: false` |
| Browser `Notification` API in the dashboard | not used anywhere in app.js, runs.js, blade.js, index.html |
| agentmux plugin hook (`agentmux-hook.sh`) | exits immediately unless the command names an agent verb |
| Orca's `claude-hook.cmd` | POSTs to a local app; produces no OS toast itself |

So **none of the repo's own push machinery is switched on.** Whatever is toasting is either `taskmgmt/notify.py`'s PowerShell/WinRT channel or Claude Code's own desktop notifications.

### The two remaining sources

1. **`taskmgmt/notify.py` → `toast()`**, a WinRT toast via PowerShell. Called from `courier.py:590`, `courier.py:636`, `run.py:732`. Its own docstring already states the right bar — *"a run that has stopped and is waiting on a person, a card parked after three failed reviews, an agent that died mid-job, a whole orchestration finishing. Not per-job progress, not spawns, not passing verdicts"* — so the work is checking each call site actually holds to it, not inventing a policy.

2. **Claude Code's own notifications.** The store logged **125** `notification` events reading `"Claude is waiting for your input"`. That is Claude Code's built-in desktop notification, not this repo's. It is configured in Claude Code settings, and it is the most likely single source of sheer volume.

### Event-log volume, for context

1,197 events across 10 sessions, **404 in one session**: 340 `update`, 265 `subagent_stop`, 178 `ac_met`, 125 `notification`, 82 `git_link_unattributed`. The log itself is not a toast surface, but `git_link_unattributed` firing on every git command that does not name a task is the clearest example of a signal with no action attached to it.

**Deliberately not started** — the operator asked to move to the next phase first.