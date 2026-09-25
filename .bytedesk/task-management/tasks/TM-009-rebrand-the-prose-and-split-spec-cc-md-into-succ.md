---
id: "TM-009"
kind: "task"
status: "done"
created: "2026-09-25T15:20:09.578Z"
board: "controllogix/ccontrolcenter"
title: "Rebrand the prose and split SPEC_CC.md into successor specs"
epic: "EP-002"
acceptance: [{"text":"README.md, docs/CONTRACTS_agents.md, SPEC.md and the BRIEF/REVIEW docs are rebranded","done":true,"at":"2026-09-25T16:22:17.520Z"},{"text":"docs/SPEC_field.md states the vendored-wheel dependency policy the paho vendoring already follows","done":true,"at":"2026-09-25T16:22:18.988Z"},{"text":"docs/SPEC_WEB.md states the one-SSE-connection-per-tab rule and the server-time rule, each with its evidence","done":true,"at":"2026-09-25T16:22:20.808Z"},{"text":"The four surviving SPEC_CC.md constraints are carried forward verbatim, including the brand section","done":true,"at":"2026-09-25T16:22:22.263Z"},{"text":"The Phase 0 acceptance grep returns nothing, with the documented exclusions for the Rockwell PDF, the retained ccstore/ccboard/cc.db identifiers, cc-dark/cc-light, and the Jira-key test fixtures","done":true,"at":"2026-09-25T16:22:23.219Z"},{"text":"git grep -c STATUS_CCC on .gitignore still returns 1","done":true,"at":"2026-09-25T16:22:25.186Z"},{"text":"run_tests.sh is green from an ext4 clone","done":true,"at":"2026-09-25T16:22:26.425Z"}]
evidence: [".bytedesk/task-management/evidence/TM-009.txt"]
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T16:22:27.991Z"
evidenceSources: {".bytedesk/task-management/evidence/TM-009.txt":{"source":"/tmp/phase0-evidence/TM-009.txt","sha256":"077d44e80c9d0e49441d0a59771491cb7da211fdaa1964952143c3d7f2924ed6","bytes":2159,"at":"2026-09-25T16:22:15.076Z"}}
assignee: "claude"
closed: "2026-09-25T16:22:27.957Z"
---

Closes Phase 0.

Prose: `README.md` (the densest file at 12 brand hits), `docs/CONTRACTS_agents.md`, `dashboard/SPEC.md`, `dashboard/BRIEF_*.md`, `dashboard/REVIEW_CCC_FINDINGS.md`.

`dashboard/SPEC_CC.md:14-24` lists **six** standing constraints, and the draft plan never mentioned the file. Two change, four must not. Split it rather than repealing it:
- `docs/SPEC_field.md` — the sidecar's dependency policy: stdlib plus `field/vendor/` only, every vendored package pinned by wheel URL and sha256, no pip at runtime, no network at start-up. This is what the existing paho vendoring already does; write down the rule it was following.
- `docs/SPEC_WEB.md` — the frontend contract. Two load-bearing rules: **exactly one SSE connection per tab**, multiplexed by topic (forced by the measured 6-connection cap at `server.py:1974-1992`), and **server time, never client time**, for anything that reads as freshness (`iiot.js:11-14`).

Carry forward verbatim: "No secret is ever entered through the browser" (`:19`) and "terminals stay read-only; the page never sends keystrokes" (`:20`).

**Carry the brand section forward too.** `SPEC_CC.md:26-33` specifies the look — flat dark slate, tight 1px borders, dense information, thin light orange accent used sparingly and never as a fill. `style.css` is 72 KB of that identity. The rewrite ports it to tokens in Phase 3; it does not redesign it. The rebrand changes the name, not the look.

**Leave alone:** every ADR (supersede, never edit), `events.jsonl`, `audit_2026-09-17/`, `.backup-2026-09-18/`, the five `STATUS_CCC_*.md` and `.gitignore:25` which ignores them.