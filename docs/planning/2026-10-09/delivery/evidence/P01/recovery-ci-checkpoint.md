# P01 recovery and CI checkpoint

P01 remains active. This checkpoint adds recovery examples, signed envelopes over a real leaf connection, and native CI qualification. It does not accept the phase or authorize a merge.

## Executed local evidence

- `recovery-conformance-result.json`: all 35 cross-language tests pass with no skips or errors. Six new recovery tests exercise stable operation identity, changed-input rejection, deadlines, current authorization, late lookup, reordered results, cancellation, approval and unavailable versus unknown outcomes. Both independent SDKs calculate actual digests and must return equal complete transition results. The owner is explicitly an in-memory fixture.
- `signed-leaf-result.json`: all 19 checks pass against two real NATS 2.15.0 brokers with separate ledgers and scoped leaf accounts. Python and TypeScript sign and verify each other's promoted envelopes. The receiver persists its decision before a deliberately lost publication, retains reserved work through independent broker restarts and returns the original decision and result on reconciliation without executing again.
- Review found missing owner binding for signed decisions and results. The fixture now checks sender, destination and work identity against the offer after SDK verification. Three decision and five result mismatch cases use valid signatures and matching operation contexts, proving owner rejection independently of schema rejection. Malformed input, invalid UTF-8, unknown contracts, wrong audience, tampering and expiry are also rejected before ledger mutation. Artifact bytes and digest must match before origin acceptance.
- `leaf-result.json`: all 11 original scoped leaf checks pass after the signed extension. `storage-result.json`: all 14 bounded JetStream cases pass. These preserve the original assertions and separately qualify their original scope.
- `baseline-full-result.json`: all 125 existing hub tests pass under WSL, including the six baseline repair cases and live federation. This is source-bound regression evidence, not phase acceptance.
- `regression-retention-result.json`: verifies the accepted snapshot's 105 regression files or exact reviewed replacements. Removing an actual assertion in memory must fail. The three reviewed replacements preserve executable assertions and existing documentation; see `regression-replacement-review.md`.

Reports contain their actual command, environment and source hashes. Earlier sourceCommit values identify the base checkout; the exact candidate is established by matching report hashes to committed bytes. Historical reports remain evidence only for their recorded source and assumptions.

## Native CI and evidence handling

`.github/workflows/contracts.yml` adds Ubuntu and macOS jobs on this feature branch. `tests/contracts/ci.py` installs locked dependencies, builds independent TypeScript clients, verifies the pinned official broker archive and runs SDK, recovery, storage, leaf, tracker, preservation and pattern checks. A deliberately broken positive contract fixture must trigger the expected assertion failures in both clients. Existing tracker tests separately reject invalid phase advancement.

CI writes fresh evidence outside the checkout. Review caught and removed an earlier approach that would overwrite committed broker reports and invalidate the reviewed source. All three broker runners retain their default local destination and accept an explicit CI evidence directory. Process deadlines fail checks and terminate their process groups. Evidence includes actual runtime versions, exit codes and before/after source identity.

Native CI execution is still pending at this checkpoint. A workflow definition or a local pass is not macOS/Linux evidence. Missing native evidence prevents phase acceptance.

## Limits and next gate work

Fixture public keys, clock and grants are fixed trusted test inputs. These tests do not implement production enrollment, dynamic grant lookup, TLS, real plugin execution or a production task owner. R1 graceful broker restart does not prove R3 quorum or power-loss recovery. The final independently enrolled bilateral hub demonstration remains a later obligation.

The inventory retains 338 baseline files, 93 components and 198 behavior checks, and maps 73 additive files. All P01 tasks remain open except the previously accepted preflight. Run and review native CI, finish every task's full acceptance mapping and review the complete phase preservation/failure matrix before passing P01. No later phase has started.
