---
id: "EP-004"
kind: "epic"
status: "open"
created: "2026-09-26T02:01:36.304Z"
board: "controllogix/ccontrolcenter"
title: "Remote access: the tailnet, and the guard that must not be deleted"
actor: "main"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
updated: "2026-09-26T02:01:36.444Z"
---

Plan Phase 6. Remote access to the dashboard from a phone on the tailnet,
without widening the bind and without a public listener.

The shape: tailscaled runs INSIDE WSL in userspace mode, and `tailscale serve`
terminates TLS on the tailnet address and proxies to 127.0.0.1. So the API keeps
binding loopback, there is exactly one listener on the tailnet and it is
Tailscale's, and the Windows host's networking is untouched - which on a machine
that talks to live equipment matters.

The thing most likely to go wrong is not the networking. It is that
allowed_origins() derives the guard from the server's own bound port, and over
serve the browser's Origin is https://agentmux.<tailnet>.ts.net - a different
scheme, host and port. Every mutating request from the phone is then rejected as
a forbidden origin. Someone will read that as the guard being wrong and delete
it. The doc-comment's REASONING has to be carried forward, not just its code.

Hard prerequisites: Phase 1.4 auth must land before the bind is widened. Port
8787 is unauthenticated today and the Origin allowlist only stops a browser.

Non-goals, recorded so they are not reopened: no Tailscale Funnel, no public
exposure, no port forwarding.