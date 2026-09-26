---
id: "TM-039"
kind: "task"
status: "parked"
created: "2026-09-26T02:03:26.436Z"
board: "controllogix/ccontrolcenter"
title: "Build the differ, and record the corpus before the second handler moves"
epic: "EP-002"
acceptance: [{"text":"/api/epics moves first WITH the harness, and nothing else moves until the differ reports zero diffs across the corpus","done":false},{"text":"The proxy strips Origin on forward and adds X-Forwarded-Origin, proved by a test that would 403 without it","done":false},{"text":"Write differs replay against two copies of a frozen cc.db and diff response JSON AND a canonical DB dump","done":false},{"text":"Timestamp and uuid normalisation is a WHITELIST, so an unnormalised field that drifts is a finding rather than noise","done":false},{"text":"run_tests.sh's lease on 8787 still works, reusing suite_server.py's takeover rather than a second mechanism","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
actor: "pool"
branch: "main"
worktree: "/mnt/c/Dev/agentmux"
labels: ["ready-for-agent","human-only"]
triagedBy: "auto"
updated: "2026-09-26T03:12:31.406Z"
session: "pool-tm-039"
parkedReason: "The differ decides whether a ported handler is byte-identical to the one it replaces. A worker closing this card removes the only check on the entire strangler. Phase 1.3 wants a human reading its output - unpark when one is."
---

Phase 1.3. The strangler only works if the two servers can be proved identical.
Node takes 8787, server.py moves to --port 8788, Node reverse-proxies un-ported
routes - and the proxy is the corpus recorder, so every request the browser, the
e2e suite and coordination.py already make writes the corpus for free.

The one detail that will cost a day if missed: a proxied POST arrives at
server.py carrying Origin http://127.0.0.1:8787 while it is bound to 8788, and
read_cc_body 403s it. The proxy MUST strip Origin on forward - safe, because Node
has already run the origin and CSRF checks - and add X-Forwarded-Origin for the
record.

Not everything is differ-able and the plan says which: SSE is not, stateful
singletons are not, hardware writes must NEVER be differed against live
equipment.