# Independent TypeScript storage fixture client

This bounded spike uses Node 22, TypeScript 7.0.2, `@nats-io/transport-node` 3.4.0 and `@nats-io/jetstream` 3.4.0. The exact dependency graph is locked. It is not a production owner service: it assumes a disposable, complete fixture ledger and does not implement domain authorization, enrollment, checkpoints or arbitrary historical compaction.

Copy this directory into an isolated cache, run `npm ci --ignore-scripts` and `npm run build`, then invoke `node dist/client.js`. Do not install `node_modules` or emit builds in the repository. The Python harness owns the disposable broker and stream. Supply `AMX_STORAGE_URL` and `AMX_STORAGE_TOKEN` through the process environment. Non-loopback brokers are rejected. No credentials or raw broker errors are written to stdout.

Each process reads one JSON request from stdin and exits after one `{ok,result}` or `{ok:false,error,apiCode?}` response:

- `inspect`: `stream`; returns broker version, stream configuration and state.
- `publish`: `subject`, `record`, `expectedSequence`, optional `msgId` and `headers`; uses the real JetStream expected-last-subject-sequence condition. Returns acknowledged `sequence`, `duplicate` and `stream`.
- `read`: `stream`, `subject`; obtains the latest record through the stream management API, not a derived view or consumer cursor.
- `reconcile`: `stream`, `subject`, `operationId`, `payloadDigest`; scans retained records and returns the matching operation with `replayed:true`, rejects changed content, or reports `not_found`. A deleted/truncated or oversized fixture history reports `history_gap`. Absence cannot authorize a retry when history is incomplete.
- `batch`: `subject`, `records` (2–1,000), `expectedSequence`, optional `commit:false`; uses native `startBatch`, `add` and `commit`. Staged output explicitly says `committed:false`. Only the final acknowledgment reports commitment.
- Raw `batch`: `messages:[{subject,record,headers}]`; sends explicit request/reply protocol headers for negative sequence and commit fixtures. Returns acknowledgments or a structured server error.

Records retain the complete supplied state, provenance and effect intent in one JSON publication. Reconciliation checks `record.operation.operationId` and `record.operation.payloadDigest`. The caller controls record construction and digests; this fixture does not authenticate them. Stream scans are limited to 10,000 messages and require complete sequence history. Concurrent pruning is outside the fixture contract.

## Atomic batch capability and limits

The installed 3.4.0 package exposes native `startBatch`, acknowledged `add` and final `commit`. Its typed initial publish options include conditional subject sequence. The server must enable `allow_atomic`. [Official advanced publishing documentation](https://docs.nats.io/learn/jetstream/advanced-publishing) describes staging, final commit, abandoned batches and the required stream opt-in; [the client documentation](https://github.com/nats-io/nats.js/blob/main/jetstream/README.md) describes conditional publishing and manager reads.

API presence does not prove that a particular server accepts the combination of atomic batching and conditional publication. The harness must execute complete, partial, conflicting and lost-acknowledgment cases on the pinned real broker and inspect stored records. No cross-stream, cross-account or external-effect transaction is claimed. An uncommitted batch is not a partial success.
