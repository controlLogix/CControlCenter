---
id: "TM-040"
kind: "task"
status: "in_progress"
created: "2026-09-26T02:03:28.555Z"
board: "controllogix/ccontrolcenter"
title: "The first authentication port 8787 has ever had"
epic: "EP-002"
acceptance: [{"text":"The sessions table is added by a PYTHON migration, because there is one schema owner","done":false},{"text":"Login is a one-time bootstrap URL printed to the terminal; there is no password field anywhere","done":false},{"text":"Cookie is __Host-agentmux_sid, HttpOnly, SameSite=Lax; CSRF is double-submit with timingSafeEqual","done":false},{"text":"The Origin allowlist is KEPT as defence in depth with allowed_origins()'s exact semantics","done":false},{"text":"Machine clients read a bearer token from AGENTMUX_HOME/api-token at 0600 and send no cookie, therefore no CSRF check","done":false},{"text":"POST /api/journal still accepts a request with NO Origin header, or every agentmux claim breaks","done":false},{"text":"Industrial writes keep their own typed-confirmation gate on top; auth authorises the request, the phrase authorises the shot","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent"]
triagedBy: "auto"
updated: "2026-09-26T03:16:28.829Z"
session: "pool-tm-040"
---

Phase 1.4. Verified against the live dashboard: GET /api/agents with no auth and
no origin returns 200, and POST /api/board/create with NO Origin header at all
passes the guard completely and reaches payload validation. Any local process can
write to the board with no credential.

That is acceptable ONLY because the bind is loopback, which is why Phase 6 must
not widen the bind until this lands.

Login without a secret in the browser, preserving SPEC_CC.md:19: the API prints a
one-time bootstrap URL to the terminal, single-use, ten-minute expiry. No password
field, ever - it violates the posture and creates a credential store this repo
deliberately does not have.

A behaviour change worth naming: the 17 board writes take actor from the REQUEST
BODY today (server.py:1424). After this the server takes it from the session and
overrides the body, so the differ flags every write - which is why this lands
after the write-path baseline is green, with the expected-diff list checked in.