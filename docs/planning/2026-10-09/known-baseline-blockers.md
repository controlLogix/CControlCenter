# Known baseline blockers

Status: open, planning record only. Originally reported in the analysis dated October 8, 2026 and recorded/reconciled with current source on October 9, 2026 during this planning pass. No runtime repair or fresh live-broker reproduction was performed here.

The existing repository owners are **Nick Klute and Ryan Helms**. They own triage of these records; named implementation assignment and calendar scheduling remain pending P00 review. The proposed repair deadline is **P01 exit, before P02 progression**. This is a phase gate, not a fabricated calendar commitment.

The required pattern gate cannot pass while these active findings remain. The federation files did not exist at configured adoption commit `f4c84b09b187f7e895d1406fb5a8f885d5845e35`, and `hub/store.py` changed after it. They cannot honestly be treated as unchanged adoption-era debt. Keep adoption history and the legacy-remediation ledger intact. Repair the findings under approved implementation work, attach evidence, and update the review truthfully.

P00 can review and record this known baseline, but this document does not mark P00 or any implementation gate accepted. P01 includes the baseline regressions and repairs so later phases do not depend on an impossible all-pass attestation. This planning package remains subject to the recorded governance blocker until repair.

<a id="amx-base-001"></a>

## AMX-BASE-001. Subject plane and envelope type can select different authorization/dispatch paths

- **Rule:** DP004. **Status:** open.
- **Source:** [hub/fed/guard.py](../../../hub/fed/guard.py), `inbound`.
- **Evidence scope:** Reproduced in the earlier repository analysis with an authenticated shared peer. Source reread in this planning pass confirms that the guard uses subject plane while dispatch selects env.type.
- **Repair / acceptance:** Bind authenticated subject/account, envelope type, destination and operation scope before policy evaluation and dispatch. Verify alternate subjects cannot evade quarantine.
- **Verification:** FAIL-05 in the [failure matrix](verification-matrix.md), plus a focused baseline regression that fails before the fix and passes afterward.
- **Accountability:** Nick Klute / Ryan Helms for P00 triage; implementation owner to be assigned. **Originally reported:** 2026-10-08. **Recorded/reconciled:** 2026-10-09. **Required by:** P01 exit.

<a id="amx-base-002"></a>

## AMX-BASE-002. Incoming work creation and remote provenance commit separately

- **Rule:** DP003. **Status:** open.
- **Source:** [hub/fed/plugins/work.py](../../../hub/fed/plugins/work.py), `Work.on_envelope`.
- **Evidence scope:** Earlier interruption test left a ready work item without origin metadata and allowed duplicate creation on redelivery. Source reread confirms separate work_create and mark transactions.
- **Repair / acceptance:** Make execution creation, origin attribution, deduplication and permitted effect intent consistent at a single owning commit boundary.
- **Verification:** FAIL-07, FAIL-08 in the [failure matrix](verification-matrix.md), plus a focused baseline regression that fails before the fix and passes afterward.
- **Accountability:** Nick Klute / Ryan Helms for P00 triage; implementation owner to be assigned. **Originally reported:** 2026-10-08. **Recorded/reconciled:** 2026-10-09. **Required by:** P01 exit.

<a id="amx-base-003"></a>

## AMX-BASE-003. Completed work can lose its return-result publication

- **Rule:** DP003. **Status:** open.
- **Source:** [hub/fed/plugins/work.py](../../../hub/fed/plugins/work.py), `Work.on_local_event`.
- **Evidence scope:** Earlier injected failure after local completion and before result staging left the origin pending with no recoverable result record. Current release dispatch and callback paths still separate those steps.
- **Repair / acceptance:** Persist recoverable result intent consistently with terminal execution state and replay it after failures. Preserve result identity through retries.
- **Verification:** FAIL-09 in the [failure matrix](verification-matrix.md), plus a focused baseline regression that fails before the fix and passes afterward.
- **Accountability:** Nick Klute / Ryan Helms for P00 triage; implementation owner to be assigned. **Originally reported:** 2026-10-08. **Recorded/reconciled:** 2026-10-09. **Required by:** P01 exit.

<a id="amx-base-004"></a>

## AMX-BASE-004. Same-peer work consumed by a different node can be acknowledged as stale

- **Rule:** DP003. **Status:** open.
- **Source:** [hub/fed/plugins/work.py](../../../hub/fed/plugins/work.py), `Work.on_envelope`.
- **Evidence scope:** Code-backed finding, not a claimed live-cluster reproduction. The same-peer branch reopens origin_id in the consuming node's database without a full origin-node ownership check.
- **Repair / acceptance:** Add a multi-node regression and bind routing/ownership to full hub/node/delegation identity. Missing local state alone cannot justify dropping valid work.
- **Verification:** FAIL-17 in the [failure matrix](verification-matrix.md), plus a focused baseline regression that fails before the fix and passes afterward.
- **Accountability:** Nick Klute / Ryan Helms for P00 triage; implementation owner to be assigned. **Originally reported:** 2026-10-08. **Recorded/reconciled:** 2026-10-09. **Required by:** P01 exit.

<a id="amx-base-005"></a>

## AMX-BASE-005. Result processing lacks binding to the selected executor and original repository

- **Rule:** DP004. **Status:** open.
- **Source:** [hub/fed/plugins/work.py](../../../hub/fed/plugins/work.py), `Work._on_result`.
- **Evidence scope:** Code-backed finding from the repository analysis, confirmed by source reread. The result path checks an origin work ID and pending state but does not bind the result to a recorded selected executor/repository contract.
- **Repair / acceptance:** Persist and verify selected executor, delegation scope, task/repository version and artifact evidence before changing current task state. Preserve historical evidence separately.
- **Verification:** FAIL-16, FAIL-19 in the [failure matrix](verification-matrix.md), plus a focused baseline regression that fails before the fix and passes afterward.
- **Accountability:** Nick Klute / Ryan Helms for P00 triage; implementation owner to be assigned. **Originally reported:** 2026-10-08. **Recorded/reconciled:** 2026-10-09. **Required by:** P01 exit.

<a id="amx-base-006"></a>

## AMX-BASE-006. Backup names can collide and replace a retained snapshot

- **Rule:** DP006. **Status:** open.
- **Source:** [hub/store.py](../../../hub/store.py), `Store.backup_to`.
- **Evidence scope:** Earlier offline retention test and frozen-clock reproduction identified millisecond timestamp filename collisions. Current code uses that stamp plus os.replace for the final backup path.
- **Repair / acceptance:** Use unique completed snapshot identities and test rapid/frozen-clock/concurrent backup and cleanup behavior with actual restore evidence.
- **Verification:** FAIL-34 in the [failure matrix](verification-matrix.md), plus a focused baseline regression that fails before the fix and passes afterward.
- **Accountability:** Nick Klute / Ryan Helms for P00 triage; implementation owner to be assigned. **Originally reported:** 2026-10-08. **Recorded/reconciled:** 2026-10-09. **Required by:** P01 exit.

## Evidence handling

The earlier report is `agentmux-repository-analysis.md` in the conversation artifact archive. Its observed results and code-backed concerns remain distinct. Reproduce the non-live findings under controlled fixtures in P01 before making stronger environment-specific claims. The old review's rule assessments remain preserved as historical records; the current review records these active findings instead of retaining unsupported all-pass status.
