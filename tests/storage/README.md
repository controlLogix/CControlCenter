# JetStream storage qualification

Run `python tests/storage/run.py` with the exact Python packages in `hub/requirements.lock`. The runner requires NATS Server 2.15.0 and the independently compiled TypeScript client; missing dependencies fail rather than skip.

Default prepared tools are `~/.cache/agentmux-governance/tools/nats-server` and `~/.cache/agentmux-governance/typescript-storage/dist/client.js`. Override their paths with `AGENTMUX_STORAGE_SERVER` and `AGENTMUX_STORAGE_TS_CLIENT`; `AGENTMUX_STORAGE_NODE` selects Node. Build the TypeScript sources with their exact lock in a disposable cache directory before running. The source/build hashes are part of the report.

The harness starts an owned loopback broker with a random token, private temporary configuration and file-backed store. Credentials pass to child clients through their environment, never command arguments or recorded evidence. The broker, clients and temporary files are cleaned up on success or failure. No real project stream or user credential is used.

The Python and TypeScript clients independently publish conditional complete records and read/reconcile retained history through JetStream. One record contains state, synthetic actor provenance and stable effect intent. The fixture never uses a separate KV claim. Concurrent expected-subject-sequence writes must admit exactly one transition. Reconciliation finds an older operation after later writes, a broker restart and expiry of a deliberately short duplicate window; reusing its identity with a changed digest fails.

The lost-ack test publishes without a reply inbox. An independent read confirms the resulting commit before the broker is restarted. This establishes recovery when the publisher has no acknowledgment; it is not a random packet-loss simulation or a power-failure test.

Atomic batches are exercised through Python raw headers and the TypeScript native API. Opening a batch returns an empty staging reply, not proof of commitment. Only the final acknowledgment confirms the batch count and sequence. The tests require no partial records before commit, after sequence gaps, or after restart of an uncommitted batch. A stale condition, including an ordinary write inserted between batch opening and commit, must reject the entire batch. Cross-stream batch attempts must fail.

The report at `docs/planning/2026-10-09/delivery/evidence/P01/storage-result.json` records executed cases, versions and exact source/build hashes. It is replaced with a failed report when a run fails; an old success cannot masquerade as the new result.

These are bounded fixture owners, not production domain services. Their history scans require complete retained history and are capped at 10,000 records. History holes produce an explicit reconciliation error. They do not prove account isolation, real identity/grants, R3 availability, native macOS execution, network partitions, OS power-loss durability, production retention, or external-effect execution. Atomic persistence cannot make other streams, hubs, projections or tools transactional.

Protocol basis: [NATS advanced publishing](https://docs.nats.io/learn/jetstream/advanced-publishing) and the [pinned server implementation](https://github.com/nats-io/nats-server/blob/v2.15.0/server/stream.go). Normal conditional publishing uses `Nats-Expected-Last-Subject-Sequence`; atomic batches use `Nats-Batch-Id`, increasing `Nats-Batch-Sequence` and final `Nats-Batch-Commit: 1`.
