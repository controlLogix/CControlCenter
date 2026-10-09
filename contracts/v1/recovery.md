# Recovery fixture contract

`tests/contracts/test_recovery.py` combines hand-authored operation histories with both independent SDKs. It is a trusted, in-memory fixture coordinator, not a production owner service. No result here proves persistence, atomic storage or restart recovery. Those require the separate real-broker storage and leaf tests.

For a newly admitted transition, the fixture resolves the requester and scope, checks its admission deadline, computes the actual payload's canonical digest independently in both SDKs, and supplies the current owner snapshot to both transition evaluators. Both must return the same complete result before the fixture updates state. The hand-authored history supplies expected outcomes; it does not derive them from the promoted model table.

An operation identity binds the machine, entity, owner hub, scope, event, authorized role and payload digest. An identical replay returns the retained outcome without advancing the revision or creating another execution. Reusing the operation identity for changed input fails. Current authorization is checked before returning any retained result. The in-memory outcome map merely makes these semantics executable; a production owner must preserve the binding and outcome durably with its state and effect intent.

An expired command cannot be used as a newly authenticated lookup. Late reconciliation is a separate, currently authorized request with a fresh deadline, referring to the original operation. It returns the retained outcome and leaves reservations intact. Revoked requesters and foreign scopes cannot read it. An out-of-order result, stale expected revision, receiving-hub acceptance or timeout-based reassignment is rejected by both transition evaluators. Signed reservation envelopes are independently verified before the deadline and rejected at expiration.

Cancellation remains pending through an unknown attempt outcome. A late terminal observation does not justify resuming or completing that attempt; the fixture follows the existing cancellation reconciliation and confirmed-stop edges. Hard denial cannot be overridden by human approval: the required not-hard-denied evidence is absent and both evaluators reject the transition. Review-required work proceeds only after the fixture supplies the separate approval evidence.

A missing reply means unknown, not unavailable. The fixture permits unavailable only when its own before-dispatch checkpoint proves the particular operation was never sent and no outcome exists. A timeout, a different operation's checkpoint or a previously admitted operation cannot provide that proof. Unknown outcomes are not automatically retried. Both SDKs validate the outcome shape, including rejection of an accepted-record reference on unknown/unavailable results.

The distinction between unknown and unavailable is an owner responsibility. The current JSON schema checks representation, not the truth of a non-admission claim or current authorization. This fixture supplies those observations explicitly and does not claim schema validation establishes them. Production admission, authenticated evidence lookup, retention gaps, distributed races and durable reconciliation remain separate implementation obligations.

Run the focused selection with the prepared independent clients:

```text
python tests/contracts/run.py --match Recovery
```

The existing runner makes hash-verified native source copies, preserves test deadlines and rejects skipped checks. No product data, external account or real worker is modified by these scenarios.
