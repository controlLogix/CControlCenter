---
id: "TM-059"
kind: "task"
status: "open"
created: "2026-09-26T02:06:21.023Z"
board: "controllogix/ccontrolcenter"
title: "2FA by persistent profile; failure locks, it never retries"
epic: "EP-003"
acceptance: [{"text":"A persistent profile directory outside the repo; storageState is not used","done":false},{"text":"Two failed password attempts means LOCKED, cleared only by hand - no automated password retry anywhere","done":false},{"text":"No 2FA secret is stored and no token generation is implemented; proposing it requires a new ADR","done":false},{"text":"Keepalive is jittered 8-12 minutes, market hours plus/minus 30, and ONLY while investing mode is active","done":false},{"text":"On expiry the broker alerts and does not attempt to re-authenticate","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T03:15:29.953Z"
session: "pool-tm-059"
---

Phase 5.2. launchPersistentContext(userDataDir), NOT storageState, so cookies,
IndexedDB and the device-trust token all survive. A remembered device turns the
overwhelming majority of sessions into password-only, which is worth more than
any clever automation.

On expiry the broker ALERTS AND DOES NOT RE-AUTH; the operator logs in by hand in
that profile. This holds SPEC_CC.md:19 completely - no secret ever touches the
dashboard.

Locking out a real brokerage account is strictly worse than a broken panel, and a
retry loop against a login form is exactly how that happens.