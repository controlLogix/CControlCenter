---
id: "TM-063"
kind: "task"
status: "open"
created: "2026-09-26T02:06:28.462Z"
board: "controllogix/ccontrolcenter"
title: "Run tailscaled inside WSL, and keep the API on loopback"
epic: "EP-004"
acceptance: [{"text":"The API still binds 127.0.0.1 only after this lands, asserted by enumerating listening sockets","done":false},{"text":"tailscale serve status --json shows exactly one handler and it targets 8787","done":false},{"text":"Userspace networking is sufficient; subnet routing and exit-node behaviour are explicitly not wanted","done":false},{"text":"BLOCKED ON TM-040: the bind must not be widened before authentication exists","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T03:15:34.377Z"
session: "pool-tm-063"
---

Phase 6.1 and 6.2. tailscaled with --tun=userspace-networking, then tailscale
serve --bg --https=443 to http://127.0.0.1:8787.

Why in WSL rather than on Windows: the tailnet boundary and the API boundary
become the SAME boundary - nothing crosses hosts to serve a remote request, and
the funnel guard runs in the same process tree as the thing it guards. The
Windows host's networking is untouched, which on a machine that talks to live
equipment matters.

With serve, Tailscale terminates TLS on the tailnet address and proxies to
loopback, so there is EXACTLY ONE listener on the tailnet and it is Tailscale's -
which already checks node identity before a byte reaches us. That is strictly
better than 'bind loopback plus the tailnet interface'.

netsh portproxy was rejected: WSL's eth0 changes every boot, so an invisible
forwarder would need rewriting at startup and fails silently in front of an API
whose authentication is the thing under test.