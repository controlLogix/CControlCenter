# P00 baseline defect reconciliation

Source candidate: `c513ffa0565936916b342ae8ad7a8dc837b4d6e8`, reviewed October 9, 2026. P00-T03 identifies the defect scope, retained evidence and future regression owners. It does not pass P01 or the complete failure matrix.

The prior repair report, acceptance wording and limitations remain in [governance-repairs.md](../../../governance-repairs.md) and [known-baseline-blockers.md](../../../known-baseline-blockers.md). This record assigns their invariants to replacement work so a rewrite cannot silently lose the repairs.

## Evidence checked

- Frozen baseline: `df46e94570fadf78ef67a75a692dd48b968a10f7`.
- Old-source reproduction: `5ee428b8152ef3ac3f5036b8e1a930b1eec31d4e`. Its five affected runtime blobs exactly match the frozen baseline. The nine selected tests produced 13 assertion/subtest failures and one backup-collision error. This is retained historical evidence, not a new run.
- All eight repair source/test hashes and three historical log hashes match [the original evidence](../../../governance-repair-evidence.json).
- The current focused run passed 20 governance tests with no skips: [result](governance-result.json), [log](governance-tests.log). The test runner's source fingerprints were checked against this candidate. No live broker is used by this focused module.
- The earlier 119-test local real-broker suite remains attributable to its own source, environment and fault model. It does not establish R3, multi-host partition, native macOS or actual agent-provider behavior.

The exact comparisons and hashes are in [source-checks.json](source-checks.json). No product implementation changed in this reconciliation.

## Regression ownership

All six findings first belong to P01-T06 for preservation of the fixed baseline assertions. The following later tasks own the invariant when its implementation moves.

| Finding | Preserved assertion and focused fixture | Replacement owner and failure scenarios |
| --- | --- | --- |
| AMX-BASE-001 | `AuthorizationBinding`: a subject/envelope mismatch in plane, sender, destination, repository or role is rejected before policy dispatch. Moving work onto an information subject cannot bypass authorization. | P04-T01 identity/authorization; P10-T02 trust and scoped broker access. FAIL-05. Retain authenticated-broker spoof tests alongside unit checks. |
| AMX-BASE-002 | `WorkRecovery.test_incoming_creation_rolls_back_when_attribution_fails` and `WorkProtocol.test_receive_is_atomic_with_claim_and_retry_after_injected_crash`: incoming task, origin identity, blocked state and claim intent commit together or not at all; retry does not duplicate execution. | P01-T07 persistence spike; P04-T02 domain authority; P05-T08 transitions; P10-T04 delegation. FAIL-07/08. Carry the invariant into the NATS record boundary rather than retaining shared SQLite authority. |
| AMX-BASE-003 | `WorkRecovery.test_completion_keeps_durable_return_intent_without_callback` and `WorkProtocol` restart, failed-staging, abrupt-exit and exhausted-lease cases: terminal state retains a stable return-result obligation until delivered/reconciled. | P04-T02 state owner; P05-T08 transition/effect handling; P10-T04 return/reconciliation. FAIL-09. Broker publish acknowledgment alone is not completion. |
| AMX-BASE-004 | `WorkRecovery.test_same_peer_other_node_is_not_discarded` and `WorkProtocol.test_same_peer_other_node_completes_without_confusing_origin_rows`: only the exact originating node reopens its placeholder; another node executes through the reservation protocol. | P10-T03 routing and P10-T04 reservation. FAIL-17. Keep the live same-peer/different-node round trip. |
| AMX-BASE-005 | `WorkRecovery.test_wrong_peer_result_does_not_complete_origin` and `WorkProtocol.test_result_binds_peer_node_attempt_task_repo_grant_and_evidence`: only the selected executor's matching grant, offer, repository ID and result text digest can update current origin state. Competing receivers cannot both become ready. | P05-T04 evidence versus acceptance; P10-T04/T05 delegation/provenance. FAIL-16/19 remain incomplete until repository-version, external-artifact and delegated-actor evidence are qualified. |
| AMX-BASE-006 | `BackupIdentity`: frozen-clock and concurrent backups retain distinct restorable snapshots; an interrupted copy cannot publish or prune a completed snapshot. | P04-T02/T06 durable state and projection rebuild; P12-GATE packaging/restore. FAIL-34. Port the recovery invariant to NATS backup/checkpoint tooling and test actual restores; local filesystem results do not establish replicated or power-loss durability. |

## Compatibility and remaining work

Preserve work envelope v3, its isolated `.v3` subjects and `work3_` consumers while the current runtime remains in use. Messages and other existing capabilities keep their existing protocol versions. Store migration 5 adds durable result intent; it does not justify running old writers against current active reservations. Retain old uncertain work for explicit reconciliation; never use an upgrade or lost acknowledgment as permission to reassign accepted work automatically.

The baseline fixes bind repository identity and returned text. They do not prove that a worker checked out the requested commit, that external artifact bytes match, that a delegated actor stayed within scope, or that returned work meets the user's request. P05/P10 must implement and verify those requirements. Baseline findings remain closed only within their documented repair boundary; the broader scenarios retain their original acceptance criteria and not-run status.

No human approval, capability retirement, live-instance result or phase advancement is entered by this record. The P00 task is complete when reproduction/scoping and regression ownership are recorded; execution of every replacement-phase case remains with its own task and gate.
