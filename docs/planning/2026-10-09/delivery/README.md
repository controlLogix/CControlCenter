# Implementation task tracking

Ryan chose repository-based tracking instead of Jira. No Atlassian installation or account is needed. This tracks delivery of the implementation plan; it is not a new runtime task store for the Agentmux product.

## Source of truth

- `tasks.json` owns task status, scope, dependencies, implementation steps, acceptance criteria, evidence, commit references and append-only change history.
- [Implementation status](../implementation-status.md) is the generated human-readable board.
- `phases.json` remains the design contract for phase scope and acceptance. Its `proposed` field is not a second execution-status field.
- Each phase is an epic. Each numbered phase work item has an implementation task. Every Jev use case, video record and skill has a qualification task with its original proposal and item-specific acceptance criteria. Shared implementation links prevent treating overlapping records as separate services or additive savings.
- Each phase has a separate `Pxx-GATE` task. It owns full acceptance, failure, rollback and advancement review. Individual task completion does not pass the gate.
- `MERGE-01` is a final task after all 15 gates. It tracks the real Ryan/Nick demonstration and final decision; the ordinary status-update command cannot authorize a merge.

This initial decomposition retains all source work. Refine broad tasks into bounded child tasks before starting them when needed, preserving parent scope and coverage. Phase-level verification procedures listed on an individual implementation task provide context: run the checks relevant to that slice, then the complete required matrix at its gate. Only the dedicated preflight task must finish before other implementation work in that phase; ongoing candidate preservation checks finish at the phase gate.

A component's documentation owner can differ from the phase that qualifies its running behavior. A behavior check may declare `qualificationPhase`; otherwise it uses the component's `ownerPhase`. Every check has exactly one qualification owner in the tracker. For example, P00 reviews the repository instructions, while P06 must prove REPO-01-C01 by loading them in supported agent hosts. This changes the verification sequence, not the required assertion. Preflight work must still identify such later checks and any baseline gaps before a safe change proceeds.

## Status and updates

Allowed states are `planned`, `ready`, `in_progress`, `blocked`, `verification`, and `done`. Record a task as blocked with a specific reason and next action. Do not use done for a partial implementation, skipped environment, unapproved scope reduction, or a worker's self-report.

From the repository root:

```text
python docs/planning/2026-10-09/delivery/track.py check
python docs/planning/2026-10-09/delivery/track.py update P00-T06 in_progress --note "Review phase-owned components and baseline evidence."
python docs/planning/2026-10-09/delivery/track.py update P00-GATE blocked --note "Complete P00 tasks and obtain the required Ryan/Nick review."
python docs/planning/2026-10-09/delivery/track.py render
```

Update status when starting work, encountering a blocker, entering verification or finishing a task. Add notes to the task history for decisions, changed evidence or reopened work. Commit the tracker and generated board with the related work. Before advancing a phase, commit and push all code and reviewed phase evidence on `feat/agentmux-platform-rearchitecture`, verify the remote commit, then record phase completion and push that tracking update. Do not merge.

Use one tracker writer at a time in a checkout. Updates replace the JSON file atomically, but independent concurrent edits still require Git conflict review; this delivery tool does not claim distributed task ownership.

For `done`, pass `--record <repository-relative evidence JSON>`. That record must contain `taskId`, `sourceCommit` and `acceptanceResults`, with one entry for every task criterion: `criterionId`, `status: passed`, and nonempty `evidence` references. Include actual commands, exit codes, environments, limitations and reviewed outputs. The commit must exist. Phase verification also requires a `gateRecord` based on `gate-record.template.json`, `advancementApproval`, and `remoteCommit`; the tool checks the pushed candidate and phase criterion coverage. Required failure, migration, component and human-review evidence must be inspected by the reviewer. JSON validation cannot prove that test claims or human approvals are authentic.

Only enter a human approval after that person actually gives it. P00 still requires Ryan and Nick's review; the instruction to proceed is not evidence of Nick's review. Final MERGE-01 requires every approved phase, their real-instance safe orchestration in both directions, joint evidence review and Ryan's explicit merge authorization.

## Keeping scope and evidence current

`track.py check` detects missing phase work, catalog records, component behavior checks, phase criteria, failure assignments, unresolved predecessor states and dependency cycles. It also rejects changed planning-source hashes. When scope changes, reconcile affected task contents and ownership, preserve the old values in history, update the source hashes deliberately, then rerun the check. Never refresh hashes just to hide drift.

Material implementation changes require reviewing affected completed tasks and evidence. Reopen affected tasks and downstream gates together before resuming; the checker refuses a done dependent with an incomplete predecessor. Existing governance repairs and fast-test tooling remain reusable historical evidence, not automatic phase passes. Missing host/vendor/provider evidence stays open.

Use the [fast local test workflow](../../../LOCAL_TESTING.md): focused tests while editing, then affected suites and complete required gates on stable candidates. No runtime test is necessary merely to render a status page.
