---
id: "TM-065"
kind: "task"
status: "open"
created: "2026-09-26T02:06:32.257Z"
board: "controllogix/ccontrolcenter"
title: "Auth parity on the tailnet, and strip the identity headers"
epic: "EP-004"
acceptance: [{"text":"A test asserts the auth middleware has NO origin-conditional branch","done":false},{"text":"Tailscale-User-* headers are stripped unconditionally at the first hook and are never used for authorization","done":false},{"text":"Lockout and expiry behave identically over the tailnet and over loopback","done":false},{"text":"The second-listener approach is recorded as the safe way to recover tailnet identity later","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T03:15:36.586Z"
session: "pool-tm-065"
---

Phase 6.4. Same session, CSRF, expiry and lockout on the tailnet as on loopback.

Tailscale serve injects Tailscale-User-* headers, but it connects over LOOPBACK -
so the API cannot distinguish a serve-proxied request from a direct local one by
socket alone, and a local client could forge them. Stripping eliminates the
forgery class at the cost of tailnet identity in the audit record, which is the
right trade for v1.

If that identity is wanted later, the safe way is a SECOND loopback listener that
only serve proxies to, with a per-listener trust flag - not trusting a header on
the shared one. Recorded so nobody reaches for the header instead.