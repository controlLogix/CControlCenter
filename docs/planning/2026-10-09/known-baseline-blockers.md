# Baseline governance findings and resolutions

Status: all six baseline defects repaired and verified on October 9, 2026, on `feat/agentmux-platform-rearchitecture`. The [repair record](governance-repairs.md) explains the decisions, compatibility changes and limits. The [evidence record](governance-repair-evidence.json) contains the exact commands, source hashes and logs: 119 hub tests passed without skips, including real-broker cases; nine selected dashboard tests and syntax checks passed.

Ryan authorized autonomous implementation decisions for these six findings. Codex implemented and verified the repairs. Nick Klute and Ryan Helms remain the repository owners; their complete phase and final acceptance reviews remain outstanding. This scoped repair does not pass all of P00/P01, advance to P02 or authorize merging.

The original findings and their repair criteria are preserved below. Each historical evidence statement describes the source before this repair. The defects could not be deferred as unchanged adoption-era debt: federation files did not exist at adoption commit `f4c84b09b187f7e895d1406fb5a8f885d5845e35`, and `hub/store.py` had changed. Adoption history and the remediation ledger remain intact. The review retains the original findings as resolved records with new evidence rather than deleting their history.

<a id="amx-base-001"></a>

## AMX-BASE-001. Subject plane and envelope type can select different authorization/dispatch paths

- **Rule:** DP004. **Status:** resolved for the baseline defect, 2026-10-09.
- **Source:** [hub/fed/guard.py](../../../hub/fed/guard.py), `inbound`.
- **Historical evidence scope:** Reproduced in the earlier repository analysis with an authenticated shared peer. Source reread in this planning pass confirms that the guard uses subject plane while dispatch selects env.type.
- **Repair / acceptance:** Bind authenticated subject/account, envelope type, destination and operation scope before policy evaluation and dispatch. Verify alternate subjects cannot evade quarantine.
- **Resolution:** Route validation binds authenticated sender, operation plane, destination, repository and role before policy evaluation. `AuthorizationBinding` rejects conflicting subjects; live JWT tests retain sender-spoof enforcement. Evidence: [repair report](governance-repairs.md) and [executed tests](governance-repair-evidence.json).
- **Verification:** FAIL-05 in the [failure matrix](verification-matrix.md), plus a focused baseline regression that fails before the fix and passes afterward.
- **Accountability:** Nick Klute / Ryan Helms, repository owners; Codex implemented the repair under Ryan's scoped authorization. **Originally reported:** 2026-10-08. **Recorded/reconciled:** 2026-10-09. **Required by:** P01 exit.

<a id="amx-base-002"></a>

## AMX-BASE-002. Incoming work creation and remote provenance commit separately

- **Rule:** DP003. **Status:** resolved for the baseline defect, 2026-10-09.
- **Source:** [hub/fed/plugins/work.py](../../../hub/fed/plugins/work.py), `Work.on_envelope`.
- **Historical evidence scope:** Earlier interruption test left a ready work item without origin metadata and allowed duplicate creation on redelivery. Source reread confirms separate work_create and mark transactions.
- **Repair / acceptance:** Make execution creation, origin attribution, deduplication and permitted effect intent consistent at a single owning commit boundary.
- **Resolution:** Incoming creation, origin attribution, blocked state and claim outbox share one transaction. Fault injection rolls all of them back; retry creates one attributed item. Outgoing creation and offer staging are also atomic. Evidence: [repair report](governance-repairs.md) and [executed tests](governance-repair-evidence.json).
- **Verification:** FAIL-07, FAIL-08 in the [failure matrix](verification-matrix.md), plus a focused baseline regression that fails before the fix and passes afterward.
- **Accountability:** Nick Klute / Ryan Helms, repository owners; Codex implemented the repair under Ryan's scoped authorization. **Originally reported:** 2026-10-08. **Recorded/reconciled:** 2026-10-09. **Required by:** P01 exit.

<a id="amx-base-003"></a>

## AMX-BASE-003. Completed work can lose its return-result publication

- **Rule:** DP003. **Status:** resolved for the baseline defect, 2026-10-09.
- **Source:** [hub/fed/plugins/work.py](../../../hub/fed/plugins/work.py), `Work.on_local_event`.
- **Historical evidence scope:** Earlier injected failure after local completion and before result staging left the origin pending with no recoverable result record. Current release dispatch and callback paths still separate those steps.
- **Repair / acceptance:** Persist recoverable result intent consistently with terminal execution state and replay it after failures. Preserve result identity through retries.
- **Resolution:** Migration 5 records result intent and a stable result ID with terminal state. Restart and failed-staging recovery retry that result. Tests include an abrupt process exit and exhausted leases. Evidence: [repair report](governance-repairs.md) and [executed tests](governance-repair-evidence.json).
- **Verification:** FAIL-09 in the [failure matrix](verification-matrix.md), plus a focused baseline regression that fails before the fix and passes afterward.
- **Accountability:** Nick Klute / Ryan Helms, repository owners; Codex implemented the repair under Ryan's scoped authorization. **Originally reported:** 2026-10-08. **Recorded/reconciled:** 2026-10-09. **Required by:** P01 exit.

<a id="amx-base-004"></a>

## AMX-BASE-004. Same-peer work consumed by a different node can be acknowledged as stale

- **Rule:** DP003. **Status:** resolved for the baseline defect, 2026-10-09.
- **Source:** [hub/fed/plugins/work.py](../../../hub/fed/plugins/work.py), `Work.on_envelope`.
- **Historical evidence scope:** Code-backed finding, not a claimed live-cluster reproduction. The same-peer branch reopens origin_id in the consuming node's database without a full origin-node ownership check.
- **Repair / acceptance:** Add a multi-node regression and bind routing/ownership to full hub/node/delegation identity. Missing local state alone cannot justify dropping valid work.
- **Resolution:** Only the exact origin node can reopen its own placeholder. Another node under the same peer reserves and completes work through the normal exchange. Unit and real-broker tests cover this case. Evidence: [repair report](governance-repairs.md) and [executed tests](governance-repair-evidence.json).
- **Verification:** FAIL-17 in the [failure matrix](verification-matrix.md), plus a focused baseline regression that fails before the fix and passes afterward.
- **Accountability:** Nick Klute / Ryan Helms, repository owners; Codex implemented the repair under Ryan's scoped authorization. **Originally reported:** 2026-10-08. **Recorded/reconciled:** 2026-10-09. **Required by:** P01 exit.

<a id="amx-base-005"></a>

## AMX-BASE-005. Result processing lacks binding to the selected executor and original repository

- **Rule:** DP004. **Status:** resolved for the baseline defect, 2026-10-09.
- **Source:** [hub/fed/plugins/work.py](../../../hub/fed/plugins/work.py), `Work._on_result`.
- **Historical evidence scope:** Code-backed finding from the repository analysis, confirmed by source reread. The result path checks an origin work ID and pending state but does not bind the result to a recorded selected executor/repository contract.
- **Repair / acceptance:** Persist and verify selected executor, delegation scope, task/repository version and artifact evidence before changing current task state. Preserve historical evidence separately.
- **Resolution:** An origin-owned reservation selects one peer/node/execution/grant. Results must match the immutable offer, repository ID, grant and payload digest. Wrong-executor and wrong-reference cases cannot change current state. The broader checked-out repository-version, external-artifact and actor-delegation requirements remain open in P05/P10; see the explicit boundary in the repair record. This closure does not mark FAIL-16 or FAIL-19 fully passed. Evidence: [repair report](governance-repairs.md) and [executed tests](governance-repair-evidence.json).
- **Verification:** FAIL-16, FAIL-19 in the [failure matrix](verification-matrix.md), plus a focused baseline regression that fails before the fix and passes afterward.
- **Accountability:** Nick Klute / Ryan Helms, repository owners; Codex implemented the repair under Ryan's scoped authorization. **Originally reported:** 2026-10-08. **Recorded/reconciled:** 2026-10-09. **Required by:** P01 exit.

<a id="amx-base-006"></a>

## AMX-BASE-006. Backup names can collide and replace a retained snapshot

- **Rule:** DP006. **Status:** resolved for the baseline defect, 2026-10-09.
- **Source:** [hub/store.py](../../../hub/store.py), `Store.backup_to`.
- **Historical evidence scope:** Earlier offline retention test and frozen-clock reproduction identified millisecond timestamp filename collisions. Current code uses that stamp plus os.replace for the final backup path.
- **Repair / acceptance:** Use unique completed snapshot identities and test rapid/frozen-clock/concurrent backup and cleanup behavior with actual restore evidence.
- **Resolution:** Exclusive temporary creation and no-replace publication prevent retained snapshots being overwritten. Frozen-clock, concurrent-store, failed-copy and restore/integrity tests pass on the tested local filesystem. Evidence: [repair report](governance-repairs.md) and [executed tests](governance-repair-evidence.json).
- **Verification:** FAIL-34 in the [failure matrix](verification-matrix.md), plus a focused baseline regression that fails before the fix and passes afterward.
- **Accountability:** Nick Klute / Ryan Helms, repository owners; Codex implemented the repair under Ryan's scoped authorization. **Originally reported:** 2026-10-08. **Recorded/reconciled:** 2026-10-09. **Required by:** P01 exit.

## Evidence handling

The earlier report is `agentmux-repository-analysis.md` in the conversation artifact archive. Its observed results and code-backed concerns remain distinct. The repair pass reproduced all six defects against an isolated archive of `5ee428b` before recording closure. Current logs distinguish offline fault injection from real local-broker tests. The old review and planning-era finding assessments remain historical records. Future platform failure scenarios retain their own not-run status until their full contracts and environments are tested.
