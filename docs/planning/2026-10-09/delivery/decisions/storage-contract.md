# STATE-01 implementation contract

Status: detailed recommendation for Codex P00 review. Ryan approved NATS-backed shared authority; the concrete layout and operating profiles below still require review and P01/P04/P10/P12 qualification. No authoritative SQL exception is proposed.

## S01. Account, domain and service boundaries

Each autonomous hub has a stable hub ID and its own JetStream domain. Domain names locate persistence; they are not authorization boundaries. Use separate NATS accounts for system administration, protected kernel traffic, application control and each confidential organization/project scope. Local solo mode uses the same layout with one organization/project account initially; it does not bypass application authorization.

The kernel account exports only bounded public boot/status subjects. Ordinary plugins cannot publish or subscribe to its internal lifecycle traffic. Broker system credentials stay with the deployment administrator; they are not inherited PluginContext services. Application status is assembled outside the kernel from permitted kernel observations and domain-owner responses.

Domain owners receive credentials restricted to their command, event and storage subjects. A scoped SDK handle is convenient but insufficient on its own: broker credentials must deny unauthorized subjects and management APIs as well. Clients, workers and third-party packages call domain commands; they do not receive general stream creation/deletion, arbitrary KV writes or another owner's records. Query projections use read/consume permissions and separately scoped writes to their own projection bucket. Audit and enrollment administrators have distinct identities.

Partner connections terminate in dedicated agreement accounts. Export only approved commands/events or selected projections with bilateral scope, expiry and onward-sharing policy. Do not leaf-link a partner into the kernel, system or entire project account. The receiving hub validates the original actor, agreement, operation and project mapping before invoking its local owners. Record origin hub, export policy and forwarding chain to prevent unbounded forwarding loops.

Leaf links carry subject interest; independent persistence and selected replication require explicit configuration. Mirror/source lag is a visibility concern, not a transfer of task ownership. Separate accounts provide subject isolation; domains keep independent JetStream systems addressable. [NATS leaf-node documentation](https://docs.nats.io/learn/topologies/leaf-nodes).

## S02. One authoritative transition record

Use one complete append-only record for a domain transition. Partition its subject by schema major version, organization, project, owner domain and entity ID. For example, `amx.v1.o.<org>.p.<project>.ledger.task.<taskId>` is a proposed logical subject; P01 must validate allowed token syntax and the real broker permission set. Identifiers are generated opaque tokens, never unchecked user strings inserted into a subject.

| Field group | Required meaning |
| --- | --- |
| Record identity | Schema version, immutable record ID, entity ID/version, previous committed revision, owning hub/domain and record type. |
| Operation | Stable operation ID, canonical payload digest, requested expected version, accepted/rejected outcome and correlation/causation IDs. |
| Authority | Validated actor, service/plugin instance, organization/project, delegation/approval references and relevant policy version. Caller-supplied text cannot establish identity. |
| State | Complete resulting owner state, including active reservation, selected executor and acceptance state when applicable. |
| Recoverable work | Required outgoing messages/effects with stable effect IDs and their allowed scope. An intent is not proof of execution. |
| Evidence | Immutable artifact references/digests, repository revision, reported result and validation/acceptance references where required. |

The owner conditionally appends against the last committed subject revision. A revision conflict forces an authoritative reread and full revalidation. No separate pre-commit KV claim can authorize execution. The broker's subject-sequence condition is a candidate primitive to qualify with the pinned SDK/server. [NATS conditional publishing](https://docs.nats.io/learn/jetstream/advanced-publishing).

Keep operation outcomes durably discoverable for the entire retained entity history. The owner rebuilds an operation index from committed records/checkpoints and reconciles a lost reply against the original operation ID and digest. Identical replay returns the recorded outcome; changed content under the same ID is rejected. If history needed to decide was removed, return reconciliation-required rather than create a new operation. `Nats-Msg-Id` deduplication alone is insufficient after its window expires.

A transition's state, provenance, outcome and effect intent fit in one record. Where a domain genuinely needs multiple atomic records, use a qualified same-stream atomic batch only after P01 proves the required conditional-write combination and final acknowledgment behavior. If that combination is unavailable, redesign the bounded aggregate or review an explicit alternative; do not replace it with sequential puts. No transaction is claimed across streams, accounts, hubs, object uploads or external actions.

An effect dispatcher reads committed intent, checks current execution authority and invokes the target with the same effect identity. Record receipts/outcomes through the owner. Crash recovery retries only when the effect's contract is idempotent or reconciles its prior outcome; otherwise show an uncertain effect for review. Rebuilding views never invokes tools or providers. Owner replicas can receive concurrent commands, but the qualified conditional commit selects the state transition; queue delivery does not select business ownership.

P01 must select canonical JSON rules shared by all SDKs, including numbers, duplicate keys, Unicode and unknown fields. Until then, the runtime spike's equal decoded JSON is interoperability evidence only, not a canonical-signature or payload-hash contract.

## S03. Storage families and retention

| Family | Proposed configuration | Recovery and deletion rule |
| --- | --- | --- |
| Authoritative task/run/delegation/approval records and required audit | File-backed Limits retention; no automatic age expiry; discard-new at quota rather than evict old authority. Owner-controlled writes. | Retain unresolved work, operation outcomes and reservation evidence until explicit reconciliation. Archive/compact only with a verified checkpoint, retained operation/deletion history and reference checks. |
| Work delivery and retry notifications | Separate durable delivery streams/consumers with bounded redelivery and dead-letter handling. | Acknowledging delivery cannot delete the authoritative task/history. Exhaustion is an alert/reconciliation state. |
| Task/board/search views | Rebuildable KV or optional local SQL indexes, with applied stream cursor and schema version. | Delete/rebuild only the projection. Missing cursor ranges stop readiness and request repair; never present an empty project as a successful recovery. |
| Configuration and registry | Owner-controlled KV with CAS; required change history also retained in a ledger. | Keep last known valid version on invalid changes. CAS protects one key; multi-key consistency needs a separate owner record. |
| Presence/capacity hints | KV TTL candidate: heartbeat every 10 seconds, expire after 30 seconds. | Expiry makes availability stale/unavailable; it never cancels a grant or frees reserved work. |
| Conversation/progress | Scoped retained stream; default proposed 30-day raw-progress retention, with accepted evidence and required records retained separately. | Retention is disclosed and configurable. Summaries cannot erase mandatory obligations, audit or result evidence. |
| Artifacts and packages | Object Store with immutable content/version identifiers; default record body cap 64 KiB, larger payloads referenced. | Upload, verify bytes/digest, then commit a reference. Orphan uploads are collected only after a grace period and a reference check. Referenced bytes cannot disappear through an unrelated TTL. |

Initial capacity fixture: 10 GiB authoritative metadata and 20 GiB artifact allowance for solo; 100 GiB metadata and 500 GiB artifacts for team, sized on the declared disk with headroom for replicas, snapshots and temporary copies. Warn at 70%, stop new bulk admissions at 85%, and preserve a separately budgeted completion/reconciliation reserve. P01/P04 must prove how the application enforces that reserve; a full stream cannot be assumed to accept final results. The quotas are qualification starting points, not purchase recommendations or measured capacity.

Checkpoint at least every 10,000 records or 15 minutes of active changes, whichever comes first, without deleting the source ledger automatically. A checkpoint manifest binds owner/schema versions, record revisions, stream cursors, operation outcomes, active reservations and immutable artifacts. Verify restore and replay before permitting any log compaction. Deletion is an authorized operation with tombstones and reference checks; disconnected/unknown delegations prevent destructive compaction of their required history.

## S04. Durability and recovery profiles

| Profile | Candidate configuration | Proposed recovery objective and limits |
| --- | --- | --- |
| Local durable | One file-backed NATS server, `sync_interval: always`, persistent user-owned Compose volumes. | Process restart target under 60 seconds without loss of acknowledged records in the tested process-crash model. Disk destruction uses the last verified off-volume backup; no single-disk high availability claim. |
| Team durable | Three NATS replicas on independent qualified hosts/disks, synchronous persistence policy, quorum-aware admission. | Target zero acknowledged-record loss for a tested single-node failure and service recovery within 60 seconds. Power-loss and storage-controller behavior require separate drills. |
| Backup restore | Hourly encrypted backup to a separately protected destination; daily restore sampling, then the full P12 drill. | Candidate backup RPO up to one hour and restore target 30 minutes at the declared dataset size. These are targets until measured; sites may choose tighter profiles. |
| Offline hub | Independent domain with locally durable accepted-execution records and cached scoped grant. | Continue only allowed work. Loss of contact does not start replacement execution. Reconnect reconciles both sides before new overlapping admission. |

NATS Server 2.15.0 accepted `sync_interval: always` in a `-t` configuration check on this machine. That verifies syntax only. The official configuration reference describes the sync setting and its throughput tradeoff; it does not replace a tested application durability claim. [NATS configuration reference](https://github.com/nats-io/nats.docs/blob/master/running-a-nats-service/configuration/README.md), [node-loss guidance](https://docs.nats.io/learn/jetstream/surviving-node-loss).

Broker snapshots alone do not form a consistent multi-stream/application backup. Pause admission where necessary, capture owner watermarks, preserve unresolved effects/reservations, bind artifact inventories, and restore into a fenced environment. An older restored origin cannot assume an absent reservation means unassigned work. Mark restored owners reconciliation-required until their recovery epoch and external execution history are reconciled. Use dedicated storage profiles for lower-value telemetry only when their weaker promise is explicit; do not mix them with authoritative work.

## S05. Migration and qualification

P04 maps legacy SQLite/file IDs, provenance, pending deliveries, approvals and reservations into the new owner records. Snapshot and compare first; fence the legacy writer before cutover. Imported records retain source identity and a stable import operation. Re-running an import cannot create duplicate work or resend an old effect. Optional SQL stays a rebuildable projection. Reversing a cutover after new NATS writes requires a tested reverse migration and reservation reconciliation, not simply restoring yesterday's SQLite file.

P01-T07 must prove competing conditional writes, changed-payload retries, lost acknowledgments, recovery beyond the deduplication window and state-plus-intent atomicity. P04-T02/T06 must prove authority restrictions, import/replay, checkpoint integrity and projection rebuild. P10-T04/T08 must prove disconnected reservations, selective replication gaps and old-origin restore. P12 must qualify the exact sync/replica/storage versions, quotas, backup/restore and published RPO/RTO. The existing AMX-BASE regressions remain assigned by the [baseline reconciliation](../evidence/P00/baseline-findings.md).
