# P01 lifecycle models and leaf recovery checkpoint

This checkpoint adds executable model rules and a real two-broker transport fixture. P01 remains active. None of these results accepts a later phase or authorizes a merge.

## Lifecycle contracts

The version 1 model package retains all five accepted P00 tables and all 68 transitions. Python and TypeScript independently evaluate a closed request containing the owner snapshot, expected revision, operation identity, actor evidence and required guard evidence. The response is a candidate next state and revision. References supplied by a fixture are not authenticated authority; this evaluator neither commits a transition nor deduplicates operations.

Shared tests cover every accepted transition, each missing required guard, wrong actors, stale revisions, invalid owner bindings, unsupported fields, preserved P00 model examples and literal ordered histories. Delivery receipts and provider completion cannot accept a task. Origin acceptance requires its separate authorized transition.

Review found that an uncertain attempt could otherwise lose pending cancellation by moving to a terminal-report state that has no cancellation-reconciliation edge. A separate `cancellationPending` field now retains that fact. Pending attempts reject resume and terminal shortcuts, retain uncertainty and use the existing cancellation reconciliation path. Confirmed cancellation clears the pending flag while its transition evidence preserves history. A trusted owner may also discover and record cancellation during reconciliation.

Cross-language review found differences in integral JSON numbers, Unicode code-point length and whitespace defaults. Both SDKs now share explicit rules, with boundary tests for `3.0`, supplementary characters, maximum reference length and Unicode blank characters. The test runner explicitly selects the mirrored model file and hashes the original P00 expected tables, so ambient environment settings or changed expectations cannot silently substitute other models.

The final `state-model-conformance-result.json` records 29 tests and 1,452 subtests passing with no skips or errors in 32.466 seconds including report checks. Repository, copied-input and compiled-build identity checks all pass. The focused eight-model-test result is retained separately. Existing wire, signature, payload and semantic tests remain in the full run.

The Python unit suite passes all 17 tests using a temporary native source copy. TypeScript passes all 13 unit tests against its rebuilt isolated cache. All 22 tracker tests and the component coverage validator pass. The inventory now covers 406 files while retaining all 338 baseline files, 93 components and 198 behavior checks.

## Leaf transport and recovery

`leaf-result.json` records eleven executed checks on NATS Server 2.15.0 and nats-py 2.16.0, using two loopback processes with separate file-backed stores and JetStream domains. Private owner accounts hold distinct ledgers. Dedicated federation accounts and leaf credentials allow only the intended command and event subjects.

The fixture commits receiver acceptance before deliberately losing its acknowledgment. The origin retains an unknown acceptance outcome and its reservation. While the origin is stopped, the receiver performs one scoped read-only hash and retains its result. Both brokers restart independently. Reconciliation over the restored leaf returns the same acceptance, rejects changed offer content and does not execute again. The receiver reports completion; only the origin owner records task acceptance. Input bytes remain unchanged.

Unrelated accounts cannot observe the exchange. Bridge credentials cannot access owner storage or publish outside scope. Independent local probes also verify the leaf credential restrictions themselves. `leaf-denial-negative.json` records a deliberate mutation to generated temporary credentials: broadening them causes the existing isolation assertion to fail on unrelated traffic. No repository source, user configuration or real project stream was changed by that mutation. Cleanup passed.

The leaf fixture uses a narrow, explicit fixture protocol. It does not yet carry the promoted signed SDK envelopes or resolve real enrollment, grants and approvals. Its origin acceptance is fixture logic, not a production task service. These limits prevent treating this checkpoint as production federation or the final bilateral demonstration.

## Remaining P01 obligations

Connect the promoted wire contracts to the real transport fixtures and complete timed-out, delayed, reordered, replay and approval histories. Pure model evaluation does not establish a durable replay decision. Deadline and unavailable/unknown recovery rules still need full executable coverage. CI jobs, supported macOS/Linux/WSL evidence, deliberate pipeline rejection, current baseline-repair regression mapping and the full preservation/phase gate remain required. Existing criteria and dependencies remain unchanged.
