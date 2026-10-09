# P00 contract boundary

This package defines the proposed language-neutral contracts for P01 implementation. The schema version is `0.1.0`. Passing these fixtures validates draft shapes and selected state transitions; it does not establish production security, broker permissions, persistence or platform support.

## Protected kernel and ordinary plugins

The protected release assembly contains boot, kernel lifecycle, internal communication and exported status plugins. Its membership comes from the verified Agentmux release, never from an ordinary package manifest. Ordinary plugins can subscribe to published kernel status. They cannot grant themselves internal kernel access or replace protected members. Kernel extensions need a separately reviewed interface and a reason for every allowed command.

An ordinary manifest explicitly allows independent installation, private-child installation, or both. A private child receives its own instance identity and scoped service handles. Its grant is bound to the exact parent grant revision and cannot exceed the parent's actions, resources or lifetime. An independent child reference does not give its parent authority over that installation. Package dependencies describe compatibility; they do not confer permissions.

The current nesting fixtures require exact scope equality. A future narrower scope must use an explicit, tested containment rule. A null project or workspace means that dimension is absent, never an implicit wildcard. An empty resource list grants no resources. Organization-level actions require a separately declared action and resource; callers cannot turn an absent project into access to all projects.

## Common system objects

The host constructs an immutable plugin context after authenticating the package instance and resolving its granted permissions. Plugins do not construct authoritative contexts themselves. Wire descriptors identify versioned interfaces and scoped handles; SDKs expose them as typed objects through dependency injection. This supports language-neutral composition without requiring implementation inheritance.

| Object | Lifetime and responsibility |
| --- | --- |
| Logger | Instance lifetime; structured events with immutable instance, hub and package fields, redaction and bounded output. |
| Configuration | Versioned snapshot plus change notification; validated values and secret references, never ambient environment access. |
| Lifecycle | Instance lifetime; readiness, health, drain and cancellation signals. A child cannot stop its parent through this handle. |
| Clock | Instance lifetime; monotonic elapsed time for local deadlines and explicit UTC timestamps for records. Tests can inject a clock. |
| Tracing | Instance lifetime; operation-scoped trace and causation references, with bounded metadata and no private reasoning. |
| Metrics | Instance lifetime; scoped names and bounded labels. Tenant identifiers and arbitrary payloads are not uncontrolled labels. |
| Domain gateway | Instance lifetime; versioned NATS requests and subscriptions with broker and domain authorization. It is not an unrestricted connection. |
| Secret references | Grant-bound references resolved only by an authorized service for the intended operation; no secret values in contexts, logs or manifests. |

Each request also receives an operation context: authenticated caller, effective actor, tenant/project/workspace scope, operation identity, payload digest, expected entity version, delegation and approval references, trace identity, deadline and cancellation reference. Parent identity is provenance, not permission. Domain owners authenticate the caller and resolve referenced grants; accepting an identifier in JSON does not authenticate it.

Pure local operations such as clock reads and logger formatting need no network round trip. Communication between plugins, domains, hubs and UI services uses NATS through the scoped interfaces. Shared state belongs to its NATS-backed domain owner. A logger may buffer within documented bounds but cannot acknowledge a durable audit event before its durable owner accepts it.

## Authenticated message binding

A reference to an identity is not proof of the sender. An enrolled ingress authenticates the client using a mapped scoped transport credential or a verified login session. It discards caller-supplied authoritative context, resolves the effective actor and grants, and issues an Ed25519 attestation. The signed claims bind the complete operation context, contract identity/version, message kind, destination owner/hub and validity interval. Each owner verifies the signature against enrolled issuer keys, checks audience/time/grants, and recomputes the payload digest from received data. Caller-provided key URLs cannot establish trust. Broker permissions also restrict which ingress can reach each owner; neither mechanism replaces the other.

A delegated receiving hub authenticates its partner agreement and validates original actor/grant provenance before issuing a local attestation. Copying an attestation to another payload, command, owner or hub fails. A valid retry still passes the owner's durable operation-ID check. An expired request needs newly authenticated admission with the same business identity, never an automatic new task. Replies and events carry equivalent source binding; correlation alone is not authentication. A later event uses its own bounded operation context and the original causation/task references, so reporting completed work does not reuse an expired command deadline or create another execution. P01 proves signing/verification and replay boundaries in independent implementations; P04 proves credential enrollment, issuer rotation and revocation.

## Canonical bytes and compatibility choice

Use RFC 8785 JCS, encoded as UTF-8, for signed claims and payload hashing. Reject duplicate keys before ordinary object decoding, invalid Unicode and non-finite numbers. Preserve Unicode strings without normalization. Revision/counter integers stay within the existing safe-integer range; exact decimals or larger integers use domain-defined strings. These rules follow the [JCS specification](https://www.rfc-editor.org/rfc/rfc8785); P01 must qualify actual serializers with shared and independent vectors.

Hash the validated domain payload before it is placed in an operation context, avoiding a self-referential digest. Sign the canonical attestation claims, excluding its signature wrapper. Use explicit contract identity/version and destination fields inside the signed claims to prevent substitution. Domain schemas must reject unknown fields unless a versioned extension slot allows them. This chooses the byte contract; it does not claim the P00 validator implements canonicalization or cryptographic verification.

## Compatibility and ownership

Schemas use closed objects at infrastructure boundaries. Domain `payload` and `state` fields are extension points: P01 must select a registered, versioned domain schema before execution. Unknown commands and unsupported major versions fail explicitly. Minor compatibility needs producer/consumer fixtures before publication. The initial draft uses stable three-part versions; prerelease and build metadata are not yet supported.

One owner serializes changes to each entity. A committed owner record contains the resulting state, authenticated operation provenance, outcome and effect intents together. Retrying the same operation identity and digest returns the recorded outcome; reusing an identity with different input fails. Effect identity remains stable across delivery retries. Cross-entity changes use explicit intermediate states and recovery; this record is not a cross-stream transaction.

The five models cover plugin lifecycle, origin task, receiving delegation, execution attempt and external effect. Loss of connectivity never releases reserved work. Cancellation remains pending until execution and effects are reconciled. A late result cannot erase a cancellation request. An uncertain external effect cannot be retried solely because a timeout elapsed. Explicit reassignment requires a new assignment epoch and either verified fencing of the old execution or an authorized, recorded acceptance of unresolved execution uncertainty. A new epoch alone cannot stop an already issued external effect; the decision must identify that risk.

## Migration ownership

The existing SQLite stores remain operational until their owning phase proves the replacement and migration. They become local caches only after authority moves. No phase may silently drop a table, identity, route or user action.

| Existing data | Target owner and qualification phase |
| --- | --- |
| `hub/store.py`: repositories, aliases, paths, groups, agents, legacy names, teams and memberships | Identity and project domains, P04; preserve aliases and references used by existing callers. |
| Message kinds, messages, search index and deliveries | Conversation domain, P05; preserve delivery/read state and rebuild search as a projection. |
| Work items and claims | Work domain, P04 foundation and P05 orchestration; preserve origin ownership and active reservations. |
| Hub events, including work, delivery and agent lifecycle events | The relevant work, conversation or identity owner, P04/P05; preserve the source event identity, order and cross-domain provenance in the durable event history. Do not reclassify all events as work events. |
| NATS outbox and terminal intent flags | Owning operation's durable intent and receipt records, P04; preserve pending and uncertain effects. |
| Federation outbox, seen records, audit, quarantine and state | Federation domain, P10; retain deduplication history, scoped grants, cursor meaning and quarantine reasons. |
| `dashboard/ccstore.py`: epics, tasks, journal, messages and devices | Work, conversation and device domains, P05; preserve all cross-record IDs and dashboard behavior. |
| `dashboard/ccboard.py`: counters, ADRs, sprints, capabilities, acceptance, labels, dependencies, evidence, commits, touches, roster, comments, links, history, configuration and board state | Board/project domains, P05; preserve allocation sequences and every relationship. Views remain derived from those owners. |
| `hub/fed/plugins/board.py`: `p_board_cards` | Federation board adapter, P10; these SQLite rows mirror authoritative JetStream KV `am_board`. Migrate from the authoritative KV state and preserve its sequences/revisions; reconcile the local projection separately. |
| `hub/fed/plugins/knowledge.py`: `p_knowledge_items`, `p_knowledge_fts`; `code.py`: `p_code_shares` | Federation knowledge and code-sharing adapters, P10; preserve item/share IDs, source provenance and access boundaries; rebuild the full-text projection. |
| `dashboard/chatter_feed.py`: `chatter_receipts` | Conversation/terminal delivery owner, P05/P06; preserve actual CLI send receipts and their correlation separately from message and journal records. |
| Local credentials, terminal installation settings and host paths | Host identity and terminal adapters, P06; export references only, retain machine-specific path mappings. |
| Dashboard tool settings and industrial integration configuration | Owning tool plugins, P11; migrate configuration without performing device writes. |

Before each migration, the owner captures a consistent source checkpoint and its schema version, row counts, relationship checks, stable IDs and pending operations. Imports are idempotent and map source IDs explicitly. Validate source and target semantically, including absent/null values, timestamps, ordering and uniqueness. Fence the legacy writer before changing the authority epoch; do not run two authoritative writers. Redirect old entry points only after the target proves equivalent behavior and added requirements.

Before cutover, rollback restores the checkpoint while the target remains fenced. After new writes, rollback requires a verified reverse migration or forward repair that preserves those writes. It cannot restore an old database and discard accepted work. Keep the source snapshot and migration journal until the phase's recovery checks and retention policy permit removal. Active claims and uncertain effects require explicit reconciliation, not a default completed or cancelled state.

## Verification and remaining proof

Install `requirements.lock` in an isolated Python environment, then run `python verify.py`. The report records source hashes, validator versions and individual fixture outcomes. `verification.json` is an executed report; its limitations remain part of the result.

P01 must prove runtime schema selection, negotiation, authenticated context construction, scoped SDK interfaces and lifecycle behavior. P02/P04 must prove actual broker isolation, domain authorization, durable ownership and recovery. P05/P10 must prove concurrency, cancellation, delegation and disconnect behavior against real processes. Migration owners must exercise source-to-target, restart and rollback fixtures. The model examples are intentionally bounded and are not exhaustive state-space exploration.
