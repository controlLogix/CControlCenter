# Design pattern context

This registry records how, where, and why approved Dofactory and Enterprise Integration Patterns are used in this repository. Keep historical entries and transition their status rather than deleting them.

<!-- design-patterns-registry:v1 -->
```json
{
  "schemaVersion": "1.0.0",
  "lastReviewed": "2026-10-09",
  "entries": [
    {
      "id": "FED-01",
      "status": "applied",
      "catalog": "eip",
      "pattern": "Messaging Bridge",
      "source": "https://www.enterpriseintegrationpatterns.com/patterns/messaging/MessagingBridge.html",
      "referenceDepth": "full-public-reference",
      "how": "Each hub's local messaging (hub.db messages/work_items) is bridged to NATS subjects: TM-218's core-NATS Bridge for one operator's nodes, and EP-032's Federation runtime (JetStream) for other people's hubs.",
      "why": "Agents keep the local hub protocol; crossing to another hub or person must not change how an agent posts or claims.",
      "tradeoffs": "Two bridges coexist (single-operator nats_url and cross-user federation). Simpler alternative: one shared broker for every hub, rejected because it removes local offline operation and per-person trust.",
      "locations": [
        {
          "path": "hub/bridge.py",
          "symbol": "Bridge"
        },
        {
          "path": "hub/fed/runtime.py",
          "symbol": "Federation"
        }
      ],
      "verificationEvidence": [
        "hub/tests/test_fed_live.py",
        "hub/tests/test_nats_federation.py"
      ],
      "decisionEvidence": [
        "docs/FEDERATION.md"
      ]
    },
    {
      "id": "FED-02",
      "status": "applied",
      "catalog": "eip",
      "pattern": "Transactional Client",
      "source": "https://www.enterpriseintegrationpatterns.com/patterns/messaging/TransactionalClient.html",
      "referenceDepth": "full-public-reference",
      "how": "Work offer creation, incoming attribution/request, origin reservation/grant and result staging each have one SQLite commit boundary. Store migration 5 records a durable return obligation with terminal state; the work plugin retries staging it into the existing NATS outbox.",
      "why": "A crash must never publish something that did not happen or lose something that did (FEDERATION.md 8).",
      "tradeoffs": "At-least-once on the wire, so receivers must be idempotent (FED-04). Alternative: publish directly from the verb, rejected - loses messages on disconnect. The additional claim/grant exchange costs a round trip; new execution waits for its origin. Granted work stays reserved through disconnection.",
      "locations": [
        {
          "path": "hub/fed/runtime.py",
          "symbol": "Federation.stage"
        },
        {
          "path": "hub/fed/ledger.py",
          "symbol": "outbox_add"
        },
        {
          "path": "hub/store.py",
          "symbol": "Store._outbox"
        },
        {
          "path": "hub/fed/plugins/work.py",
          "symbol": "Work"
        },
        {
          "path": "hub/store.py",
          "symbol": "MIGRATIONS"
        }
      ],
      "verificationEvidence": [
        "hub/tests/test_fed_live.py",
        "hub/tests/test_governance.py"
      ],
      "decisionEvidence": [
        "docs/FEDERATION.md",
        "docs/planning/2026-10-09/governance-repairs.md"
      ],
      "implementationRevisions": [
        {
          "date": "2026-10-09",
          "reason": "Repairs for six explicitly authorized baseline findings",
          "previous": {
            "how": "Plugins write the outbox row (fed_outbox) and its audit row in the same SQLite transaction as the state change; the runtime publishes with a JetStream ack and only then marks the row sent.",
            "why": "A crash must never publish something that did not happen or lose something that did (FEDERATION.md 8).",
            "tradeoffs": "At-least-once on the wire, so receivers must be idempotent (FED-04). Alternative: publish directly from the verb, rejected - loses messages on disconnect."
          }
        }
      ]
    },
    {
      "id": "FED-03",
      "status": "applied",
      "catalog": "eip",
      "pattern": "Guaranteed Delivery",
      "source": "https://www.enterpriseintegrationpatterns.com/patterns/messaging/GuaranteedMessaging.html",
      "referenceDepth": "full-public-reference",
      "how": "AM_MSG, AM_WORK and AM_SHARE are file-backed JetStream streams (R3 on the cluster) with a 2-minute duplicate window; messages to an offline peer wait in the stream.",
      "why": "Interview requirement F7: things sent while a peer is offline drain when it reconnects.",
      "tradeoffs": "Needs the cluster's storage and an admin to provision streams. Alternative: core NATS plus local outboxes only, rejected - nothing survives the receiver being offline.",
      "locations": [
        {
          "path": "hub/fed/conn.py",
          "symbol": "STREAMS"
        },
        {
          "path": "hub/fed/admin.py",
          "symbol": "provision"
        }
      ],
      "verificationEvidence": [
        "hub/tests/test_fed_live.py"
      ],
      "decisionEvidence": [
        "docs/FEDERATION.md"
      ]
    },
    {
      "id": "FED-04",
      "status": "applied",
      "catalog": "eip",
      "pattern": "Idempotent Receiver",
      "source": "https://www.enterpriseintegrationpatterns.com/patterns/messaging/IdempotentReceiver.html",
      "referenceDepth": "full-public-reference",
      "how": "Incoming work also deduplicates by origin peer, origin node and immutable offer ID inside its owning transaction. A selected execution/grant and stable result ID survive retries beyond the broker deduplication window.",
      "why": "JetStream redelivers after ack_wait and the outbox is at-least-once (FED-02).",
      "tradeoffs": "fed_seen grows with traffic (pruning is future work). Alternative: exactly-once publishing, not available end to end. Broker acknowledgment alone cannot prevent duplicate execution across consumers; the origin grant is required before readiness.",
      "locations": [
        {
          "path": "hub/fed/runtime.py",
          "symbol": "Federation.receive"
        },
        {
          "path": "hub/fed/ledger.py",
          "symbol": "seen"
        },
        {
          "path": "hub/fed/plugins/work.py",
          "symbol": "Work"
        }
      ],
      "verificationEvidence": [
        "hub/tests/test_fed_live.py",
        "hub/tests/test_governance.py"
      ],
      "decisionEvidence": [
        "docs/FEDERATION.md",
        "docs/planning/2026-10-09/governance-repairs.md"
      ],
      "implementationRevisions": [
        {
          "date": "2026-10-09",
          "reason": "Repairs for six explicitly authorized baseline findings",
          "previous": {
            "how": "Every inbound envelope id is recorded in fed_seen after its ingest commits; redeliveries are acked and skipped. Publishes carry Nats-Msg-Id so the stream also drops republished outbox rows.",
            "why": "JetStream redelivers after ack_wait and the outbox is at-least-once (FED-02).",
            "tradeoffs": "fed_seen grows with traffic (pruning is future work). Alternative: exactly-once publishing, not available end to end."
          }
        }
      ]
    },
    {
      "id": "FED-05",
      "status": "applied",
      "catalog": "eip",
      "pattern": "Durable Subscriber",
      "source": "https://www.enterpriseintegrationpatterns.com/patterns/messaging/DurableSubscription.html",
      "referenceDepth": "full-public-reference",
      "how": "Each node binds durable pull consumers msg_<peer>_<node> (AM_MSG) and share_<peer>_<node> (AM_SHARE) and acks explicitly.",
      "why": "A node that restarts must resume where it stopped, not miss or replay the whole stream.",
      "tradeoffs": "Consumers accumulate on the server per node; removing a node needs consumer cleanup. Alternative: ephemeral subscriptions, rejected - lose traffic across restarts.",
      "locations": [
        {
          "path": "hub/fed/runtime.py",
          "symbol": "Federation._bind_core"
        }
      ],
      "verificationEvidence": [
        "hub/tests/test_fed_live.py"
      ],
      "decisionEvidence": [
        "docs/FEDERATION.md"
      ]
    },
    {
      "id": "FED-06",
      "status": "applied",
      "catalog": "eip",
      "pattern": "Competing Consumers",
      "source": "https://www.enterpriseintegrationpatterns.com/patterns/messaging/CompetingConsumers.html",
      "referenceDepth": "full-public-reference",
      "how": "V3 offers use am.work.<peer>.<rid>.<role>.v3 and work3_<peer>_<rid>_<role> consumers. Pullers honor repository scope, capacity and publisher trust. A receiver stages a claim while blocked; the origin selects one executor before any receiver becomes ready.",
      "why": "First claim wins across people: exactly one hub, then exactly one agent, does each item.",
      "tradeoffs": "One consumer per (publisher, repo, role). Hubs only pull from trusted publishers (A19), so an untrusted hub cannot swallow work. Alternative: per-subject queue groups (TM-218), rejected - no persistence. Old exact-filter consumers cannot swallow v3 offers. Redelivery can create another blocked candidate, but only the origin-selected candidate may execute. Legacy in-flight work needs explicit reconciliation.",
      "locations": [
        {
          "path": "hub/fed/plugins/work.py",
          "symbol": "Work.on_tick"
        },
        {
          "path": "hub/fed/plugins/work.py",
          "symbol": "Work"
        }
      ],
      "verificationEvidence": [
        "hub/tests/test_fed_live.py",
        "hub/tests/test_governance.py"
      ],
      "decisionEvidence": [
        "docs/FEDERATION.md",
        "docs/planning/2026-10-09/governance-repairs.md"
      ],
      "implementationRevisions": [
        {
          "date": "2026-10-09",
          "reason": "Repairs for six explicitly authorized baseline findings",
          "previous": {
            "how": "Federated role work goes to a work-queue stream; every hub that can serve (rid, role) pulls from one shared durable consumer per publisher, work_<from>_<rid>_<role>, only when it has idle capacity and trusts the publisher.",
            "why": "First claim wins across people: exactly one hub, then exactly one agent, does each item.",
            "tradeoffs": "One consumer per (publisher, repo, role). Hubs only pull from trusted publishers (A19), so an untrusted hub cannot swallow work. Alternative: per-subject queue groups (TM-218), rejected - no persistence."
          }
        }
      ]
    },
    {
      "id": "FED-07",
      "status": "applied",
      "catalog": "eip",
      "pattern": "Message Filter",
      "source": "https://www.enterpriseintegrationpatterns.com/patterns/messaging/Filter.html",
      "referenceDepth": "full-public-reference",
      "how": "Validate subject sender, plane, destination, repository and role against the envelope before policy and dispatch. Outgoing staging and control reception validate the same route. Old work protocols are quarantined and cannot bypass the v3 grant by operator approval.",
      "why": "Interview F4/F5: per-peer trust and per-repo opt-in; F11: remote work never triggers privileged tools.",
      "tradeoffs": "Policy lives in each hub, so the circle (account) is the confidentiality boundary (A7). Alternative: server-side per-repo ACLs, deferred - needs JWT reissue on every share change. This authenticates the peer through broker credentials, not independent nodes inside a peer. Semantic task/equipment safety remains a separate boundary.",
      "locations": [
        {
          "path": "hub/fed/guard.py",
          "symbol": "inbound"
        },
        {
          "path": "hub/fed/guard.py",
          "symbol": "outbound"
        }
      ],
      "verificationEvidence": [
        "hub/tests/test_fed_unit.py",
        "hub/tests/test_fed_live.py",
        "hub/tests/test_governance.py"
      ],
      "decisionEvidence": [
        "docs/FEDERATION.md",
        "docs/planning/2026-10-09/governance-repairs.md"
      ],
      "implementationRevisions": [
        {
          "date": "2026-10-09",
          "reason": "Repairs for six explicitly authorized baseline findings",
          "previous": {
            "how": "Inbound: drop malformed, spoofed (payload sender differs from the server-enforced subject token), self, unshared-rid and denied-peer traffic; quarantine approve-trust and privileged work. Outbound: refuse repos not shared with the recipient.",
            "why": "Interview F4/F5: per-peer trust and per-repo opt-in; F11: remote work never triggers privileged tools.",
            "tradeoffs": "Policy lives in each hub, so the circle (account) is the confidentiality boundary (A7). Alternative: server-side per-repo ACLs, deferred - needs JWT reissue on every share change."
          }
        }
      ]
    },
    {
      "id": "FED-08",
      "status": "applied",
      "catalog": "eip",
      "pattern": "Content Filter",
      "source": "https://www.enterpriseintegrationpatterns.com/patterns/messaging/ContentFilter.html",
      "referenceDepth": "full-public-reference",
      "how": "Every string in every outbound payload passes through redact.scrub: private keys, nkey seeds and creds block the publish; tokens, keys and secret assignments are replaced with [REDACTED:<kind>].",
      "why": "Interview F11: secret redaction before anything leaves the hub.",
      "tradeoffs": "Pattern-based: false positives redact harmless text, novel secret formats pass. Alternative: no auto-share of free text, rejected - the user asked for free sharing.",
      "locations": [
        {
          "path": "hub/fed/redact.py",
          "symbol": "scrub"
        }
      ],
      "verificationEvidence": [
        "hub/tests/test_fed_unit.py",
        "hub/tests/test_fed_live.py"
      ],
      "decisionEvidence": [
        "docs/FEDERATION.md"
      ]
    },
    {
      "id": "FED-09",
      "status": "applied",
      "catalog": "eip",
      "pattern": "Envelope Wrapper",
      "source": "https://www.enterpriseintegrationpatterns.com/patterns/messaging/EnvelopeWrapper.html",
      "referenceDepth": "full-public-reference",
      "how": "Remote text typed into an agent's context is wrapped: a one-line header for auto-trust peers, and a REMOTE DATA ... END REMOTE DATA frame for flag/approve trust.",
      "why": "A peer's message must reach the agent as information, not as instructions to obey (prompt-injection boundary).",
      "tradeoffs": "A frame is advice to the model, not enforcement; enforcement is FED-07 and the privileged gate hook.",
      "locations": [
        {
          "path": "hub/fed/guard.py",
          "symbol": "wrap"
        },
        {
          "path": "hub/fed/plugins/messages.py",
          "symbol": "Messages.on_envelope"
        }
      ],
      "verificationEvidence": [
        "hub/tests/test_fed_unit.py",
        "hub/tests/test_fed_live.py"
      ],
      "decisionEvidence": [
        "docs/FEDERATION.md"
      ]
    },
    {
      "id": "FED-10",
      "status": "applied",
      "catalog": "eip",
      "pattern": "Canonical Data Model",
      "source": "https://www.enterpriseintegrationpatterns.com/patterns/messaging/CanonicalDataModel.html",
      "referenceDepth": "full-public-reference",
      "how": "Non-work messages remain envelope v2; work, work_claim, work_grant and result use v3. The work subject suffix isolates incompatible consumers, and work data carries immutable offer identity/digest plus origin node and execution/grant references.",
      "why": "Interview F6: two people's differently named clones of one repo must line up.",
      "tradeoffs": "Every plugin must translate at its edge. Alternative: agree on shared names, rejected in the interview. Version isolation prevents unsafe fallback. Upgrades preserve old evidence but require draining or reconciling legacy work rather than fabricating missing authorization.",
      "locations": [
        {
          "path": "hub/fed/envelope.py",
          "symbol": "make"
        },
        {
          "path": "hub/fed/policy.py",
          "symbol": "rid_for_remote"
        }
      ],
      "verificationEvidence": [
        "hub/tests/test_fed_unit.py",
        "hub/tests/test_fed_live.py",
        "hub/tests/test_governance.py"
      ],
      "decisionEvidence": [
        "docs/FEDERATION.md",
        "docs/planning/2026-10-09/governance-repairs.md"
      ],
      "implementationRevisions": [
        {
          "date": "2026-10-09",
          "reason": "Repairs for six explicitly authorized baseline findings",
          "previous": {
            "how": "Envelope v2 {v,id,type,from,node,rid,to,at,data} and the repo identity rid = r + sha256(normalized remote)[:12]; local repo names are translated to and from rids at the edge.",
            "why": "Interview F6: two people's differently named clones of one repo must line up.",
            "tradeoffs": "Every plugin must translate at its edge. Alternative: agree on shared names, rejected in the interview."
          }
        }
      ]
    },
    {
      "id": "FED-11",
      "status": "applied",
      "catalog": "eip",
      "pattern": "Claim Check",
      "source": "https://www.enterpriseintegrationpatterns.com/patterns/messaging/StoreInLibrary.html",
      "referenceDepth": "full-public-reference",
      "how": "Code is pushed to the shared remote as refs/agentmux/<peer>/<slug>; only the pointer (ref, sha, base, files, stat) travels on NATS, and fetch verifies the sha.",
      "why": "Interview F8: share code through git refs; payloads stay small and reviewable.",
      "tradeoffs": "Needs a remote both sides can reach. Alternative: patches in an object store, rejected in the interview.",
      "locations": [
        {
          "path": "hub/fed/plugins/code.py",
          "symbol": "Code.v_share"
        },
        {
          "path": "hub/fed/plugins/code.py",
          "symbol": "Code.v_fetch"
        }
      ],
      "verificationEvidence": [
        "hub/tests/test_fed_live.py"
      ],
      "decisionEvidence": [
        "docs/FEDERATION.md"
      ]
    },
    {
      "id": "FED-12",
      "status": "applied",
      "catalog": "eip",
      "pattern": "Control Bus",
      "source": "https://www.enterpriseintegrationpatterns.com/patterns/messaging/ControlBus.html",
      "referenceDepth": "full-public-reference",
      "how": "am.ctl.<peer> carries the kill switch's revoke notice; receivers cancel unclaimed work from that peer and mark its cards and findings withdrawn. The kill state persists in fed_state.",
      "why": "Interview follow-up: a kill switch that disconnects and revokes outstanding shares.",
      "tradeoffs": "Core NATS (not persisted): a peer offline at revoke time misses the notice and only sees its absence. Alternative: a persisted control stream, possible later.",
      "locations": [
        {
          "path": "hub/fed/runtime.py",
          "symbol": "_v_kill"
        },
        {
          "path": "hub/fed/runtime.py",
          "symbol": "Federation._on_ctl"
        }
      ],
      "verificationEvidence": [
        "hub/tests/test_fed_live.py"
      ],
      "decisionEvidence": [
        "docs/FEDERATION.md"
      ]
    },
    {
      "id": "FED-13",
      "status": "applied",
      "catalog": "eip",
      "pattern": "Message Store",
      "source": "https://www.enterpriseintegrationpatterns.com/patterns/messaging/MessageStore.html",
      "referenceDepth": "full-public-reference",
      "how": "fed_audit records every inbound and outbound cross-user payload: direction, plane, peer, rid, subject, id, sha256, size, decision and reason - never the redacted values.",
      "why": "Interview F11: full audit log of what crossed and why.",
      "tradeoffs": "Grows without pruning yet. Alternative: logs only, rejected - not queryable from the dashboard.",
      "locations": [
        {
          "path": "hub/fed/ledger.py",
          "symbol": "audit"
        }
      ],
      "verificationEvidence": [
        "hub/tests/test_fed_live.py"
      ],
      "decisionEvidence": [
        "docs/FEDERATION.md"
      ]
    },
    {
      "id": "FED-14",
      "status": "applied",
      "catalog": "eip",
      "pattern": "Shared Database",
      "source": "https://www.enterpriseintegrationpatterns.com/patterns/messaging/SharedDataBaseIntegration.html",
      "referenceDepth": "full-public-reference",
      "how": "The shared board is the JetStream KV bucket am_board; every change is a compare-and-set on the card revision, and each hub mirrors cards for its shared repos into p_board_cards.",
      "why": "Interview: a shared central board, CAS.",
      "tradeoffs": "Writes need the connection (reads are local). Alternative: owner-authoritative replicas, rejected in the interview.",
      "locations": [
        {
          "path": "hub/fed/plugins/board.py",
          "symbol": "Board._write"
        }
      ],
      "verificationEvidence": [
        "hub/tests/test_fed_live.py"
      ],
      "decisionEvidence": [
        "docs/FEDERATION.md"
      ]
    },
    {
      "id": "FED-15",
      "status": "applied",
      "catalog": "eip",
      "pattern": "Messaging Gateway",
      "source": "https://www.enterpriseintegrationpatterns.com/patterns/messaging/MessagingGateway.html",
      "referenceDepth": "full-public-reference",
      "how": "Agents never see NATS: the CLI (agentmux hub fed ...) and the stdio MCP server expose verbs generated from one registry and call the hub socket.",
      "why": "Interview F10: CLI canonical, thin MCP wrapper.",
      "tradeoffs": "The MCP server is hand-written (A18). Alternative: agents use nats directly, rejected - would bypass identity and guardrails.",
      "locations": [
        {
          "path": "hub/fed/mcp.py",
          "symbol": "handle"
        },
        {
          "path": "hub/cli.py",
          "symbol": "fed_main"
        }
      ],
      "verificationEvidence": [
        "hub/tests/test_fed_unit.py"
      ],
      "decisionEvidence": [
        "docs/FEDERATION.md"
      ]
    },
    {
      "id": "FED-16",
      "status": "applied",
      "catalog": "eip",
      "pattern": "Correlation Identifier",
      "source": "https://www.enterpriseintegrationpatterns.com/patterns/messaging/CorrelationIdentifier.html",
      "referenceDepth": "full-public-reference",
      "how": "Correlate by origin peer/node, origin work ID, offer ID/digest and repository ID, then the selected peer/node/execution and grant. Accept terminal payload state/text only with a matching result digest. Store validated result identity on the origin record.",
      "why": "Results arrive asynchronously, from another person, on a shared inbox subject.",
      "tradeoffs": "Origin ids are only unique per hub; the pair (peer, origin_id) is the key. The result digest binds returned content but does not prove semantic correctness or verify arbitrary external artifacts; full product acceptance remains a later planned contract.",
      "locations": [
        {
          "path": "hub/fed/plugins/work.py",
          "symbol": "Work._on_result"
        },
        {
          "path": "hub/fed/plugins/work.py",
          "symbol": "Work"
        }
      ],
      "verificationEvidence": [
        "hub/tests/test_fed_live.py",
        "hub/tests/test_governance.py"
      ],
      "decisionEvidence": [
        "docs/FEDERATION.md",
        "docs/planning/2026-10-09/governance-repairs.md"
      ],
      "implementationRevisions": [
        {
          "date": "2026-10-09",
          "reason": "Repairs for six explicitly authorized baseline findings",
          "previous": {
            "how": "A federated item's result carries origin_id, the publisher's local work id, which closes the fed:pending placeholder on the origin hub.",
            "why": "Results arrive asynchronously, from another person, on a shared inbox subject.",
            "tradeoffs": "Origin ids are only unique per hub; the pair (peer, origin_id) is the key."
          }
        }
      ]
    },
    {
      "id": "FED-17",
      "status": "applied",
      "catalog": "dofactory",
      "pattern": "Facade",
      "source": "https://www.dofactory.com/net/facade-design-pattern",
      "referenceDepth": "full-public-reference",
      "how": "Plugins get the runtime as ctx: publish/stage, db, kv, policy, post_local, sender_of. They never touch the connection, so every publish passes the guard.",
      "why": "Interview F9: plugins extend capabilities without bypassing guardrails.",
      "tradeoffs": "ctx is wide; a plugin can still read any hub table. Alternative: per-plugin capability objects, possible if third-party plugins appear.",
      "locations": [
        {
          "path": "hub/fed/runtime.py",
          "symbol": "Federation"
        },
        {
          "path": "hub/fed/plugin.py",
          "symbol": "Plugin"
        }
      ],
      "verificationEvidence": [
        "hub/tests/test_fed_live.py"
      ],
      "decisionEvidence": [
        "docs/FEDERATION.md"
      ]
    },
    {
      "id": "PLAN-01",
      "status": "planned",
      "catalog": "dofactory",
      "pattern": "Abstract Factory",
      "source": "https://www.dofactory.com/net/abstract-factory-design-pattern",
      "referenceDepth": "full-public-reference",
      "how": "Create approved families of scoped service clients when constructing a plugin in each SDK. Proposed location: docs/planning/2026-10-09/implementation-plan.md, P03. Implementation locations will be recorded when implemented.",
      "why": "Independent SDKs must receive compatible service contracts and explicit lifetimes.",
      "tradeoffs": "A hand-written factory is simpler initially; factory APIs add abstraction and must not become a global service locator.",
      "locations": [],
      "verificationEvidence": [],
      "decisionEvidence": [
        "docs/planning/2026-10-09/implementation-plan.md",
        "docs/planning/2026-10-09/phases.json"
      ]
    },
    {
      "id": "PLAN-02",
      "status": "planned",
      "catalog": "dofactory",
      "pattern": "Adapter",
      "source": "https://www.dofactory.com/net/adapter-design-pattern",
      "referenceDepth": "full-public-reference",
      "how": "Translate client, worker, vendor, storage and AG-UI protocols at owning plugin boundaries. Proposed location: docs/planning/2026-10-09/implementation-plan.md, P03, P06, P07, P11. Implementation locations will be recorded when implemented. ADD-01 first maps existing CLI, hub plugin, dashboard and protocol implementations to retained or extracted code. A new boundary may wrap that code; any replacement needs behavior and migration evidence before cutover. LOCAL-01 client startup adapters invoke an idempotent local Compose bootstrap and expose the same authorized instance/hub status after start or reuse. Actual host hooks are qualified in P06; the dashboard uses the same contract in P07. P00 proposes command-hook or qualified launcher adapters translating LOCAL-01 status into each host output format. Existing dashboard control capabilities remain available; see delivery/decisions/startup-contract.md and runtime-and-deployment.md. This is a recommendation pending P00 review.",
      "why": "External interfaces differ while internal operations must remain language-neutral and NATS-based.",
      "tradeoffs": "A single bespoke integration is simpler; adapters add translation/version upkeep and cannot invent unsupported host capabilities. Maintaining transition paths and equivalent behavior adds testing cost. Reuse is preferred where contracts and authority permit it; a new framework or language alone is not a replacement justification. Host-specific automatic launch needs actual-host tests and protocol-clean output; manual launch is simpler but does not satisfy the accepted automatic-start requirement.",
      "locations": [],
      "verificationEvidence": [],
      "decisionEvidence": [
        "docs/planning/2026-10-09/implementation-plan.md",
        "docs/planning/2026-10-09/phases.json",
        "docs/planning/2026-10-09/component-preservation.md",
        "docs/planning/2026-10-09/delivery/decisions/README.md",
        "docs/planning/2026-10-09/delivery/contracts/README.md"
      ],
      "planningRevisions": [
        {
          "date": "2026-10-09",
          "decision": "ADD-01 preserve and extend existing functionality",
          "previous": {
            "how": "Translate client, worker, vendor, storage and AG-UI protocols at owning plugin boundaries. Proposed location: docs/planning/2026-10-09/implementation-plan.md, P03, P06, P07, P11. Implementation locations will be recorded when implemented.",
            "why": "External interfaces differ while internal operations must remain language-neutral and NATS-based.",
            "tradeoffs": "A single bespoke integration is simpler; adapters add translation/version upkeep and cannot invent unsupported host capabilities."
          },
          "reason": "Record explicit reuse obligations without changing historical FED entries or claiming implementation."
        },
        {
          "date": "2026-10-09",
          "decision": "LOCAL-01 approved automatic Compose startup direction",
          "previous": {
            "how": "Translate client, worker, vendor, storage and AG-UI protocols at owning plugin boundaries. Proposed location: docs/planning/2026-10-09/implementation-plan.md, P03, P06, P07, P11. Implementation locations will be recorded when implemented. ADD-01 first maps existing CLI, hub plugin, dashboard and protocol implementations to retained or extracted code. A new boundary may wrap that code; any replacement needs behavior and migration evidence before cutover.",
            "why": "External interfaces differ while internal operations must remain language-neutral and NATS-based.",
            "tradeoffs": "A single bespoke integration is simpler; adapters add translation/version upkeep and cannot invent unsupported host capabilities. Maintaining transition paths and equivalent behavior adds testing cost. Reuse is preferred where contracts and authority permit it; a new framework or language alone is not a replacement justification."
          },
          "reason": "Retain earlier rationale; clarify bootstrap versus runtime control and client status. Planned only, not implementation evidence."
        },
        {
          "date": "2026-10-09",
          "decision": "P00 concrete implementation recommendation; pending review",
          "previousHow": "Translate client, worker, vendor, storage and AG-UI protocols at owning plugin boundaries. Proposed location: docs/planning/2026-10-09/implementation-plan.md, P03, P06, P07, P11. Implementation locations will be recorded when implemented. ADD-01 first maps existing CLI, hub plugin, dashboard and protocol implementations to retained or extracted code. A new boundary may wrap that code; any replacement needs behavior and migration evidence before cutover. LOCAL-01 client startup adapters invoke an idempotent local Compose bootstrap and expose the same authorized instance/hub status after start or reuse. Actual host hooks are qualified in P06; the dashboard uses the same contract in P07.",
          "evidence": "docs/planning/2026-10-09/delivery/decisions/README.md"
        }
      ]
    },
    {
      "id": "PLAN-03",
      "status": "planned",
      "catalog": "dofactory",
      "pattern": "Composite",
      "source": "https://www.dofactory.com/net/composite-design-pattern",
      "referenceDepth": "full-public-reference",
      "how": "Leaf plugins and assemblies expose the same declared lifecycle/inspection component contract. Represent nesting with private-child ownership and independent-child references kept distinct, with explicit instance lifecycles and all inter-plugin calls over NATS. Proposed location: docs/planning/2026-10-09/implementation-plan.md, P03. Implementation locations will be recorded when implemented. P00 proposes fixed protected assembly membership and separately supervised processes, with explicit private-child ownership and independent child references for ordinary packages; see delivery/decisions/runtime-and-deployment.md. Process overhead remains to be measured. This is a recommendation pending P00 review.",
      "why": "Assemblies must install and operate together without erasing independent child identity.",
      "tradeoffs": "A flat dependency list is simpler; nesting increases lifecycle/version resolution complexity and must not imply inherited authority.",
      "locations": [],
      "verificationEvidence": [],
      "decisionEvidence": [
        "docs/planning/2026-10-09/implementation-plan.md",
        "docs/planning/2026-10-09/phases.json",
        "docs/planning/2026-10-09/delivery/decisions/README.md"
      ],
      "planningRevisions": [
        {
          "date": "2026-10-09",
          "decision": "P00 concrete implementation recommendation; pending review",
          "previousHow": "Leaf plugins and assemblies expose the same declared lifecycle/inspection component contract. Represent nesting with private-child ownership and independent-child references kept distinct, with explicit instance lifecycles and all inter-plugin calls over NATS. Proposed location: docs/planning/2026-10-09/implementation-plan.md, P03. Implementation locations will be recorded when implemented.",
          "evidence": "docs/planning/2026-10-09/delivery/decisions/README.md"
        }
      ]
    },
    {
      "id": "PLAN-04",
      "status": "planned",
      "catalog": "dofactory",
      "pattern": "Facade",
      "source": "https://www.dofactory.com/net/facade-design-pattern",
      "referenceDepth": "full-public-reference",
      "how": "Expose small scoped context clients for domain commands, approved NATS reads, configuration and artifacts. Injected handles do not expose unrestricted JetStream management or another project's data. Proposed location: docs/planning/2026-10-09/implementation-plan.md, STATE-01, P03, P04, P08. Implementation locations will be recorded when implemented. P00 proposes Python and TypeScript SDK clients that construct scoped domain service handles rather than expose unrestricted storage administration; see delivery/decisions/runtime-and-deployment.md and storage-contract.md. This is a recommendation pending P00 review.",
      "why": "Plugin authors need common logging, config and approved services without coupling to implementations.",
      "tradeoffs": "Direct shared-runtime access is simpler but violates the accepted scopes. Narrow clients add schema/version maintenance; typed handles alone do not sandbox trusted native plugins.",
      "locations": [],
      "verificationEvidence": [],
      "decisionEvidence": [
        "docs/planning/2026-10-09/implementation-plan.md",
        "docs/planning/2026-10-09/phases.json",
        "docs/planning/2026-10-09/delivery/decisions/README.md",
        "docs/planning/2026-10-09/delivery/contracts/README.md"
      ],
      "planningRevisions": [
        {
          "date": "2026-10-09",
          "decision": "STATE-01 approved NATS persistence direction",
          "previous": {
            "how": "Expose small scoped context service clients instead of broad runtime/database objects. Proposed location: docs/planning/2026-10-09/implementation-plan.md, P03, P04, P08. Implementation locations will be recorded when implemented.",
            "why": "Plugin authors need common logging, config and approved services without coupling to implementations.",
            "tradeoffs": "Direct access is simpler but violates the accepted boundary; facades can grow too wide and require explicit contract ownership."
          },
          "reason": "Preserve the original planning rationale while updating storage placement and recovery boundaries. This is a design revision, not implementation evidence."
        },
        {
          "date": "2026-10-09",
          "decision": "P00 concrete implementation recommendation; pending review",
          "previousHow": "Expose small scoped context clients for domain commands, approved NATS reads, configuration and artifacts. Injected handles do not expose unrestricted JetStream management or another project's data. Proposed location: docs/planning/2026-10-09/implementation-plan.md, STATE-01, P03, P04, P08. Implementation locations will be recorded when implemented.",
          "evidence": "docs/planning/2026-10-09/delivery/decisions/README.md"
        }
      ]
    },
    {
      "id": "PLAN-05",
      "status": "planned",
      "catalog": "dofactory",
      "pattern": "Observer",
      "source": "https://www.dofactory.com/net/observer-design-pattern",
      "referenceDepth": "full-public-reference",
      "how": "Deliver approved kernel information and versioned status updates over NATS subscriptions. Proposed location: docs/planning/2026-10-09/implementation-plan.md, P02, P07. Implementation locations will be recorded when implemented. P00 proposes exported kernel information in a separate account, consumed by ordinary status services without a kernel command path; see delivery/decisions/storage-contract.md. This is a recommendation pending P00 review.",
      "why": "Outside plugins need readiness information while kernel writes remain disallowed.",
      "tradeoffs": "Polling snapshots is simpler; subscriptions require replay/snapshot gap handling and bounded slow consumers.",
      "locations": [],
      "verificationEvidence": [],
      "decisionEvidence": [
        "docs/planning/2026-10-09/implementation-plan.md",
        "docs/planning/2026-10-09/phases.json",
        "docs/planning/2026-10-09/delivery/decisions/README.md",
        "docs/planning/2026-10-09/delivery/contracts/README.md"
      ],
      "planningRevisions": [
        {
          "date": "2026-10-09",
          "decision": "P00 concrete implementation recommendation; pending review",
          "previousHow": "Deliver approved kernel information and versioned status updates over NATS subscriptions. Proposed location: docs/planning/2026-10-09/implementation-plan.md, P02, P07. Implementation locations will be recorded when implemented.",
          "evidence": "docs/planning/2026-10-09/delivery/decisions/README.md"
        }
      ]
    },
    {
      "id": "PLAN-06",
      "status": "planned",
      "catalog": "dofactory",
      "pattern": "Strategy",
      "source": "https://www.dofactory.com/net/strategy-design-pattern",
      "referenceDepth": "full-public-reference",
      "how": "Select compatible provider, routing, evaluation and execution policies by explicit declared contracts. Proposed location: docs/planning/2026-10-09/implementation-plan.md, P03, P08, P10. Implementation locations will be recorded when implemented.",
      "why": "Customers need replaceable surrounding behavior without kernel replacement.",
      "tradeoffs": "One implementation is simpler; policy/provider compatibility and behavior drift require conformance tests.",
      "locations": [],
      "verificationEvidence": [],
      "decisionEvidence": [
        "docs/planning/2026-10-09/implementation-plan.md",
        "docs/planning/2026-10-09/phases.json"
      ]
    },
    {
      "id": "PLAN-07",
      "status": "planned",
      "catalog": "eip",
      "pattern": "Message Bus",
      "source": "https://www.enterpriseintegrationpatterns.com/patterns/messaging/MessageBus.html",
      "referenceDepth": "full-public-reference",
      "how": "Carry all inter-plugin communication on versioned NATS subjects and schemas. Proposed location: docs/planning/2026-10-09/implementation-plan.md, P01–P12. Implementation locations will be recorded when implemented. P00 proposes NATS for every inter-plugin exchange across the fixed protected assembly and ordinary scoped accounts. A bounded three-language request/reply spike proves client interoperability only; it does not qualify lifecycle, security or persistence. See delivery/spikes/runtime/comparison-result.json. This is a recommendation pending P00 review.",
      "why": "Accepted requirement mandates NATS locally and across connected systems.",
      "tradeoffs": "Direct local calls are simpler/faster but contradict scope; message contracts add latency, retry, schema and operational cost.",
      "locations": [],
      "verificationEvidence": [
        "docs/planning/2026-10-09/delivery/spikes/runtime/comparison-result.json"
      ],
      "decisionEvidence": [
        "docs/planning/2026-10-09/implementation-plan.md",
        "docs/planning/2026-10-09/phases.json",
        "docs/planning/2026-10-09/delivery/decisions/README.md",
        "docs/planning/2026-10-09/delivery/contracts/README.md"
      ],
      "planningRevisions": [
        {
          "date": "2026-10-09",
          "decision": "P00 concrete implementation recommendation; pending review",
          "previousHow": "Carry all inter-plugin communication on versioned NATS subjects and schemas. Proposed location: docs/planning/2026-10-09/implementation-plan.md, P01–P12. Implementation locations will be recorded when implemented.",
          "evidence": "docs/planning/2026-10-09/delivery/decisions/README.md"
        }
      ]
    },
    {
      "id": "PLAN-08",
      "status": "applied",
      "catalog": "eip",
      "pattern": "Canonical Data Model",
      "source": "https://www.enterpriseintegrationpatterns.com/patterns/messaging/CanonicalDataModel.html",
      "referenceDepth": "full-public-reference",
      "how": "The separate contracts/v1 package defines closed versioned infrastructure and domain payload schemas. registry.json binds ten contract IDs to their major version, message kind, payload schema and destination service. Independent Python and TypeScript SDK validation checks those bindings, payload/context identity agreement and explicit semantic invariants for manifests, protected assembly, contexts, owner records and attestations. Full envelope verification validates the registered payload plus RFC 8785 payload bytes, Ed25519 claims, signed audience and every duplicated envelope field. The legacy runtime does not import this package. Enrolled-key resolution, live grants, authoritative domain state schemas and full plugin runtime integration remain separate obligations; validated structure and signatures do not authorize execution.",
      "why": "Client/provider diversity must not obscure ownership or schema compatibility.",
      "tradeoffs": "Pairwise translation is simpler for two plugins; shared contracts require coordinated version evolution and independent conformance tests. Closed registration makes unsupported commands explicit, but every added domain operation needs a reviewed schema and mapping. Semantic invariants cannot all be expressed by JSON Schema and therefore require matching language implementations. Content-bound validator caches avoid repeated compilation while hashing current schema bytes prevents stale reuse; neither caches nor a supplied valid signature establish authority.",
      "locations": [
        {
          "path": "contracts/v1/schemas/message-envelope.schema.json",
          "symbol": "message-envelope"
        },
        {
          "path": "sdk/python/agentmux_contracts/wire.py",
          "symbol": "canonical_bytes"
        },
        {
          "path": "sdk/typescript/src/index.ts",
          "symbol": "canonicalBytes"
        },
        {
          "path": "contracts/v1/registry.json",
          "symbol": "contracts"
        },
        {
          "path": "sdk/python/agentmux_contracts/validation.py",
          "symbol": "validate_payload"
        },
        {
          "path": "sdk/python/agentmux_contracts/validation.py",
          "symbol": "semantic_errors"
        },
        {
          "path": "sdk/python/agentmux_contracts/attestation.py",
          "symbol": "verify_envelope"
        },
        {
          "path": "sdk/typescript/src/index.ts",
          "symbol": "validatePayload"
        },
        {
          "path": "sdk/typescript/src/index.ts",
          "symbol": "verifyEnvelope"
        }
      ],
      "verificationEvidence": [
        "tests/contracts/test_conformance.py",
        "sdk/python/tests/test_contracts.py",
        "sdk/typescript/src/test.ts",
        "tests/contracts/test_payloads.py",
        "tests/contracts/test_semantics.py"
      ],
      "decisionEvidence": [
        "docs/planning/2026-10-09/implementation-plan.md",
        "docs/planning/2026-10-09/phases.json",
        "docs/planning/2026-10-09/delivery/decisions/README.md",
        "docs/planning/2026-10-09/delivery/contracts/README.md",
        "contracts/v1/README.md"
      ],
      "planningRevisions": [
        {
          "date": "2026-10-09",
          "decision": "P00 concrete implementation recommendation; pending review",
          "previousHow": "Define versioned envelopes and identity/state vocabulary across languages and hubs. Proposed location: docs/planning/2026-10-09/implementation-plan.md, P01, P10. Implementation locations will be recorded when implemented.",
          "evidence": "docs/planning/2026-10-09/delivery/decisions/README.md"
        },
        {
          "date": "2026-10-09",
          "previousHow": "Define versioned envelopes and identity/state vocabulary across languages and hubs. Proposed location: docs/planning/2026-10-09/implementation-plan.md, P01, P10. Implementation locations will be recorded when implemented. P00 proposes shared versioned identities and transition/status fields across languages. Canonical JSON hashing and executable schemas remain P01/P00-T04 work; the spike checks decoded equality only. See delivery/decisions/storage-contract.md and startup-contract.md. This is a recommendation pending P00 review.",
          "reason": "P00 review resolved canonical bytes and authenticated caller binding."
        },
        {
          "date": "2026-10-09",
          "previousHow": "Define versioned envelopes and identity/state vocabulary across languages and hubs. Proposed location: docs/planning/2026-10-09/implementation-plan.md, P01, P10. Implementation locations will be recorded when implemented. P00 proposes shared versioned identities and transition/status fields across languages. Canonical JSON hashing and executable schemas remain P01/P00-T04 work; the spike checks decoded equality only. See delivery/decisions/storage-contract.md and startup-contract.md. This is a recommendation pending P00 review. P00 selects RFC 8785 JCS and an enrolled-ingress Ed25519 attestation binding the full operation, payload digest, source, contract and destination. Owners verify enrolled keys, recomputed digests, grants and durable replay state; P00 shapes do not implement this verification.",
          "previousStatus": "planned",
          "reason": "P01 initial executable wire contracts; broader domain/runtime work remains incomplete."
        }
      ],
      "implementationRevisions": [
        {
          "date": "2026-10-09",
          "reason": "P01 closed payload registry and independent semantic checks; bounded storage fixture qualification does not implement production ownership.",
          "previous": {
            "status": "applied",
            "how": "The isolated contracts/v1 package defines versioned infrastructure shapes. Independent Python and TypeScript libraries parse strict JSON, produce RFC 8785 bytes and verify Ed25519 attestation/envelope bindings against a supplied trusted key and expected audience. The current legacy runtime does not import these libraries. Domain payload registration, broker-backed ownership, enrollment and full SDK/runtime integration remain P01/later-phase obligations; cryptographic verification does not grant authorization.",
            "tradeoffs": "Pairwise translation is simpler for two plugins; shared contracts need careful evolution and must not become a universal domain schema.",
            "locations": [
              {
                "path": "contracts/v1/schemas/message-envelope.schema.json",
                "symbol": "message-envelope"
              },
              {
                "path": "sdk/python/agentmux_contracts/wire.py",
                "symbol": "canonical_bytes"
              },
              {
                "path": "sdk/typescript/src/index.ts",
                "symbol": "canonicalBytes"
              }
            ],
            "verificationEvidence": [
              "tests/contracts/test_conformance.py",
              "sdk/python/tests/test_contracts.py",
              "sdk/typescript/src/test.ts"
            ]
          }
        }
      ]
    },
    {
      "id": "PLAN-09",
      "status": "planned",
      "catalog": "eip",
      "pattern": "Transactional Client",
      "source": "https://www.enterpriseintegrationpatterns.com/patterns/messaging/TransactionalClient.html",
      "referenceDepth": "full-public-reference",
      "how": "Apply a bounded transaction boundary at the owning JetStream record or qualified atomic batch within one stream: state, provenance, operation outcome and recoverable outgoing intent commit together. Consumer acknowledgment, projection updates, cross-stream/hub transfer and external tool actions remain separate recoverable steps. Legacy SQL plus outbox repairs remain relevant to P01 baseline work; STATE-01 supersedes SQL as the preferred new authority. Proposed location: docs/planning/2026-10-09/implementation-plan.md, STATE-01, P01, P04, P05, P10. Implementation locations will be recorded when implemented. P00 prefers one conditional complete entity transition including state, provenance, outcome and effect intent. Same-stream batching requires the P01 SDK/concurrency proof; cross-boundary work remains recoverable. See delivery/decisions/storage-contract.md. This is a recommendation pending P00 review. Configuration and registry changes also commit to their owner ledger first; KV is a cursor-bearing projection, never a second authoritative write. P01 tests/storage/run.py now qualifies this boundary only in disposable fixture owners: Python and TypeScript conditional publishes append a complete state/provenance/effect-intent record, and a two-client race admits one subject revision. Raw Python and native TypeScript atomic batches are exercised on one file-backed R1 stream. Tests reject sequence gaps, stale conditions (including an intervening ordinary commit), uncommitted batches across graceful restart and attempted cross-stream batches. The opening staging reply is not a durable acknowledgment; only a final commit acknowledgment confirms the batch. Production domain owners remain planned for P04/P05/P10; no legacy authority moved.",
      "why": "Crash windows must not lose results or create unattributed executable work.",
      "tradeoffs": "One complete record is simpler than a batch and is preferred when it preserves the invariant. Same-stream atomic batches require pinned server/client qualification and do not create a distributed database/broker/hub/tool transaction. SQL authority is an explicit exception requiring evidence and review. Fixture qualification uses NATS Server 2.15.0 on WSL/Linux only. It does not prove native macOS, replication availability, power-loss durability, account permissions or business-level authorization. Full aggregate records remain preferred over batch coordination.",
      "locations": [
        {
          "path": "tests/storage/run.py",
          "symbol": "main"
        },
        {
          "path": "tests/storage/python_client.py",
          "symbol": "perform"
        },
        {
          "path": "tests/storage/typescript/src/client.ts",
          "symbol": "execute"
        }
      ],
      "verificationEvidence": [
        "tests/storage/run.py",
        "docs/planning/2026-10-09/delivery/evidence/P01/storage-result.json"
      ],
      "decisionEvidence": [
        "docs/planning/2026-10-09/implementation-plan.md",
        "docs/planning/2026-10-09/phases.json",
        "docs/planning/2026-10-09/delivery/decisions/README.md",
        "docs/planning/2026-10-09/delivery/contracts/README.md",
        "tests/storage/README.md"
      ],
      "planningRevisions": [
        {
          "date": "2026-10-09",
          "decision": "STATE-01 approved NATS persistence direction",
          "previous": {
            "how": "Use a bounded application/local-storage adaptation: authoritative state, provenance and durable outgoing intent commit at one owning storage boundary. NATS publication and consumer acknowledgement remain separate recoverable steps; this does not claim a transactional messaging session spanning the business database and broker. Proposed location: docs/planning/2026-10-09/implementation-plan.md, P04, P05, P10. Implementation locations will be recorded when implemented.",
            "why": "Crash windows must not lose results or create unattributed executable work.",
            "tradeoffs": "Separate writes are simpler but reproduce known defects; atomic local intent does not transact external tool effects or multiple hubs."
          },
          "reason": "Preserve the original planning rationale while updating storage placement and recovery boundaries. This is a design revision, not implementation evidence."
        },
        {
          "date": "2026-10-09",
          "decision": "P00 concrete implementation recommendation; pending review",
          "previousHow": "Apply a bounded transaction boundary at the owning JetStream record or qualified atomic batch within one stream: state, provenance, operation outcome and recoverable outgoing intent commit together. Consumer acknowledgment, projection updates, cross-stream/hub transfer and external tool actions remain separate recoverable steps. Legacy SQL plus outbox repairs remain relevant to P01 baseline work; STATE-01 supersedes SQL as the preferred new authority. Proposed location: docs/planning/2026-10-09/implementation-plan.md, STATE-01, P01, P04, P05, P10. Implementation locations will be recorded when implemented.",
          "evidence": "docs/planning/2026-10-09/delivery/decisions/README.md"
        },
        {
          "date": "2026-10-09",
          "previousHow": "Apply a bounded transaction boundary at the owning JetStream record or qualified atomic batch within one stream: state, provenance, operation outcome and recoverable outgoing intent commit together. Consumer acknowledgment, projection updates, cross-stream/hub transfer and external tool actions remain separate recoverable steps. Legacy SQL plus outbox repairs remain relevant to P01 baseline work; STATE-01 supersedes SQL as the preferred new authority. Proposed location: docs/planning/2026-10-09/implementation-plan.md, STATE-01, P01, P04, P05, P10. Implementation locations will be recorded when implemented. P00 prefers one conditional complete entity transition including state, provenance, outcome and effect intent. Same-stream batching requires the P01 SDK/concurrency proof; cross-boundary work remains recoverable. See delivery/decisions/storage-contract.md. This is a recommendation pending P00 review.",
          "reason": "Removed split config authority."
        }
      ],
      "implementationRevisions": [
        {
          "date": "2026-10-09",
          "reason": "P01 closed payload registry and independent semantic checks; bounded storage fixture qualification does not implement production ownership.",
          "previous": {
            "status": "planned",
            "how": "Apply a bounded transaction boundary at the owning JetStream record or qualified atomic batch within one stream: state, provenance, operation outcome and recoverable outgoing intent commit together. Consumer acknowledgment, projection updates, cross-stream/hub transfer and external tool actions remain separate recoverable steps. Legacy SQL plus outbox repairs remain relevant to P01 baseline work; STATE-01 supersedes SQL as the preferred new authority. Proposed location: docs/planning/2026-10-09/implementation-plan.md, STATE-01, P01, P04, P05, P10. Implementation locations will be recorded when implemented. P00 prefers one conditional complete entity transition including state, provenance, outcome and effect intent. Same-stream batching requires the P01 SDK/concurrency proof; cross-boundary work remains recoverable. See delivery/decisions/storage-contract.md. This is a recommendation pending P00 review. Configuration and registry changes also commit to their owner ledger first; KV is a cursor-bearing projection, never a second authoritative write.",
            "tradeoffs": "One complete record is simpler than a batch and is preferred when it preserves the invariant. Same-stream atomic batches require pinned server/client qualification and do not create a distributed database/broker/hub/tool transaction. SQL authority is an explicit exception requiring evidence and review.",
            "locations": [],
            "verificationEvidence": []
          }
        }
      ]
    },
    {
      "id": "PLAN-10",
      "status": "planned",
      "catalog": "eip",
      "pattern": "Idempotent Receiver",
      "source": "https://www.enterpriseintegrationpatterns.com/patterns/messaging/IdempotentReceiver.html",
      "referenceDepth": "full-public-reference",
      "how": "Bind an operation ID, canonical payload hash and expected version to the durable NATS-owned outcome. Reconcile lost acknowledgments, reject changed-payload ID reuse, and retain outcomes/deletion markers across the agreed replay and restore horizon. Proposed location: docs/planning/2026-10-09/implementation-plan.md, STATE-01, P01, P04, P10. Implementation locations will be recorded when implemented. P00 retains operation outcomes and payload digests beyond broker deduplication windows, with reconciliation-required on missing history. See delivery/decisions/storage-contract.md. This is a recommendation pending P00 review. P01 Python and TypeScript fixture clients independently scan retained authoritative history to recover an older operation ID and matching digest after later writes, a gracefully restarted broker and expiry of its short deduplication window. They return the existing record without republishing, reject changed digests and report missing history as reconciliation-required. The lost-ack fixture deliberately omits the publisher reply inbox. Production duplicate admission, durable indexes and external-effect control remain planned; fixture reconciliation is not a deployed receiver or exactly-once execution promise.",
      "why": "At-least-once delivery and uncertain replies must not create duplicate task attempts.",
      "tradeoffs": "Broker duplicate windows are simpler but insufficient for business ownership. Durable outcome records and conflict policy cost storage; external actions require their own idempotency or explicit unknown-outcome handling. The fixture scan is bounded to 10,000 retained records and is not a production indexing or retention strategy. Authoritative history costs storage; deterministic recovery requires preserving history or verified checkpoints, rather than interpreting absence as permission to re-execute.",
      "locations": [
        {
          "path": "tests/storage/python_client.py",
          "symbol": "perform"
        },
        {
          "path": "tests/storage/typescript/src/client.ts",
          "symbol": "execute"
        },
        {
          "path": "tests/storage/run.py",
          "symbol": "main"
        }
      ],
      "verificationEvidence": [
        "tests/storage/run.py",
        "docs/planning/2026-10-09/delivery/evidence/P01/storage-result.json"
      ],
      "decisionEvidence": [
        "docs/planning/2026-10-09/implementation-plan.md",
        "docs/planning/2026-10-09/phases.json",
        "docs/planning/2026-10-09/delivery/decisions/README.md",
        "docs/planning/2026-10-09/delivery/contracts/README.md",
        "tests/storage/README.md"
      ],
      "planningRevisions": [
        {
          "date": "2026-10-09",
          "decision": "STATE-01 approved NATS persistence direction",
          "previous": {
            "how": "Bind duplicate command/event IDs to a durable prior outcome under the authoritative owner. Proposed location: docs/planning/2026-10-09/implementation-plan.md, P04, P10. Implementation locations will be recorded when implemented.",
            "why": "At-least-once delivery and uncertain replies must not create duplicate task attempts.",
            "tradeoffs": "Best-effort duplicate windows are simpler but inadequate for business ownership; durable retention and conflict policy cost storage."
          },
          "reason": "Preserve the original planning rationale while updating storage placement and recovery boundaries. This is a design revision, not implementation evidence."
        },
        {
          "date": "2026-10-09",
          "decision": "P00 concrete implementation recommendation; pending review",
          "previousHow": "Bind an operation ID, canonical payload hash and expected version to the durable NATS-owned outcome. Reconcile lost acknowledgments, reject changed-payload ID reuse, and retain outcomes/deletion markers across the agreed replay and restore horizon. Proposed location: docs/planning/2026-10-09/implementation-plan.md, STATE-01, P01, P04, P10. Implementation locations will be recorded when implemented.",
          "evidence": "docs/planning/2026-10-09/delivery/decisions/README.md"
        }
      ],
      "implementationRevisions": [
        {
          "date": "2026-10-09",
          "reason": "P01 closed payload registry and independent semantic checks; bounded storage fixture qualification does not implement production ownership.",
          "previous": {
            "status": "planned",
            "how": "Bind an operation ID, canonical payload hash and expected version to the durable NATS-owned outcome. Reconcile lost acknowledgments, reject changed-payload ID reuse, and retain outcomes/deletion markers across the agreed replay and restore horizon. Proposed location: docs/planning/2026-10-09/implementation-plan.md, STATE-01, P01, P04, P10. Implementation locations will be recorded when implemented. P00 retains operation outcomes and payload digests beyond broker deduplication windows, with reconciliation-required on missing history. See delivery/decisions/storage-contract.md. This is a recommendation pending P00 review.",
            "tradeoffs": "Broker duplicate windows are simpler but insufficient for business ownership. Durable outcome records and conflict policy cost storage; external actions require their own idempotency or explicit unknown-outcome handling.",
            "locations": [],
            "verificationEvidence": []
          }
        }
      ]
    },
    {
      "id": "PLAN-11",
      "status": "planned",
      "catalog": "eip",
      "pattern": "Correlation Identifier",
      "source": "https://www.enterpriseintegrationpatterns.com/patterns/messaging/CorrelationIdentifier.html",
      "referenceDepth": "full-public-reference",
      "how": "Keep task, delegation, attempt, message, operation and artifact identities linked but distinct. Proposed location: docs/planning/2026-10-09/implementation-plan.md, P01, P05, P10. Implementation locations will be recorded when implemented.",
      "why": "Progress and results must bind to the selected executor and correct task version.",
      "tradeoffs": "One overloaded task ID is simpler but loses provenance; more IDs need disciplined propagation and do not authenticate a sender.",
      "locations": [],
      "verificationEvidence": [],
      "decisionEvidence": [
        "docs/planning/2026-10-09/implementation-plan.md",
        "docs/planning/2026-10-09/phases.json"
      ]
    },
    {
      "id": "PLAN-12",
      "status": "planned",
      "catalog": "eip",
      "pattern": "Claim Check",
      "source": "https://www.enterpriseintegrationpatterns.com/patterns/messaging/StoreInLibrary.html",
      "referenceDepth": "full-public-reference",
      "how": "Send authorized immutable artifact references and digests while owning providers retain the bytes in NATS Object Store where size/retention fit, or an approved external artifact store. Use version/digest names and recheck access on retrieval. Proposed location: docs/planning/2026-10-09/implementation-plan.md, STATE-01, P04, P10, P11. Implementation locations will be recorded when implemented. P00 proposes upload/verify before reference commit and reference-aware orphan collection, using immutable artifact IDs and byte digests. See delivery/decisions/storage-contract.md. This is a recommendation pending P00 review.",
      "why": "Code and engineering evidence can exceed safe message sizes and have separate access policies.",
      "tradeoffs": "Inline small evidence is simpler. References require coordinated retention and backups; uploading bytes and committing a task record are separate steps, with incomplete/orphan objects handled explicitly.",
      "locations": [],
      "verificationEvidence": [],
      "decisionEvidence": [
        "docs/planning/2026-10-09/implementation-plan.md",
        "docs/planning/2026-10-09/phases.json",
        "docs/planning/2026-10-09/delivery/decisions/README.md",
        "docs/planning/2026-10-09/delivery/contracts/README.md"
      ],
      "planningRevisions": [
        {
          "date": "2026-10-09",
          "decision": "STATE-01 approved NATS persistence direction",
          "previous": {
            "how": "Send authorized immutable artifact references/digests rather than large payloads in control messages. Proposed location: docs/planning/2026-10-09/implementation-plan.md, P04, P10, P11. Implementation locations will be recorded when implemented.",
            "why": "Code and engineering evidence can exceed safe message sizes and have separate access policies.",
            "tradeoffs": "Inline small payloads are simpler; referenced content requires access rechecks, partial-transfer handling and retention coordination."
          },
          "reason": "Preserve the original planning rationale while updating storage placement and recovery boundaries. This is a design revision, not implementation evidence."
        },
        {
          "date": "2026-10-09",
          "decision": "P00 concrete implementation recommendation; pending review",
          "previousHow": "Send authorized immutable artifact references and digests while owning providers retain the bytes in NATS Object Store where size/retention fit, or an approved external artifact store. Use version/digest names and recheck access on retrieval. Proposed location: docs/planning/2026-10-09/implementation-plan.md, STATE-01, P04, P10, P11. Implementation locations will be recorded when implemented.",
          "evidence": "docs/planning/2026-10-09/delivery/decisions/README.md"
        }
      ]
    },
    {
      "id": "PLAN-13",
      "status": "planned",
      "catalog": "eip",
      "pattern": "Message Store",
      "source": "https://www.enterpriseintegrationpatterns.com/patterns/messaging/MessageStore.html",
      "referenceDepth": "full-public-reference",
      "how": "Retain authoritative validated JetStream records with scoped replay, versioned checkpoints and explicit retention. Derive current KV views and optional SQL query indexes without replaying effects. Keep task/audit history separate from acknowledged work queues and bounded presence records. Proposed location: docs/planning/2026-10-09/implementation-plan.md, STATE-01, P04, P07, P10, P12. Implementation locations will be recorded when implemented. P00 proposes non-expiring authoritative history by default, explicit quota rejection, verified checkpoints and fenced restore, with optional rebuildable SQL views. See delivery/decisions/storage-contract.md. This is a recommendation pending P00 review.",
      "why": "Recovery, audits and authorized dashboard history must survive disconnected viewers and hubs.",
      "tradeoffs": "A local relational authority simplifies joins and multi-row constraints, but the accepted direction prefers shared NATS persistence. Rebuildable views add lag and recovery complexity; quotas, snapshots, schema evolution, privacy deletion and retention gaps require explicit evidence.",
      "locations": [],
      "verificationEvidence": [],
      "decisionEvidence": [
        "docs/planning/2026-10-09/implementation-plan.md",
        "docs/planning/2026-10-09/phases.json",
        "docs/planning/2026-10-09/delivery/decisions/README.md",
        "docs/planning/2026-10-09/delivery/contracts/README.md"
      ],
      "planningRevisions": [
        {
          "date": "2026-10-09",
          "decision": "STATE-01 approved NATS persistence direction",
          "previous": {
            "how": "Retain durable required events/evidence with scoped replay and retention policy. Proposed location: docs/planning/2026-10-09/implementation-plan.md, P04, P07, P12. Implementation locations will be recorded when implemented.",
            "why": "Recovery, audits and authorized dashboard history must survive disconnected viewers and hubs.",
            "tradeoffs": "Ephemeral logs are simpler but cannot support these guarantees; retention, deletion and sensitive data create operating cost."
          },
          "reason": "Preserve the original planning rationale while updating storage placement and recovery boundaries. This is a design revision, not implementation evidence."
        },
        {
          "date": "2026-10-09",
          "decision": "P00 concrete implementation recommendation; pending review",
          "previousHow": "Retain authoritative validated JetStream records with scoped replay, versioned checkpoints and explicit retention. Derive current KV views and optional SQL query indexes without replaying effects. Keep task/audit history separate from acknowledged work queues and bounded presence records. Proposed location: docs/planning/2026-10-09/implementation-plan.md, STATE-01, P04, P07, P10, P12. Implementation locations will be recorded when implemented.",
          "evidence": "docs/planning/2026-10-09/delivery/decisions/README.md"
        }
      ]
    },
    {
      "id": "PLAN-14",
      "status": "planned",
      "catalog": "eip",
      "pattern": "Control Bus",
      "source": "https://www.enterpriseintegrationpatterns.com/patterns/messaging/ControlBus.html",
      "referenceDepth": "full-public-reference",
      "how": "Expose surrounding runtime operations for allowed drain, pause, cancellation and recovery over authorized NATS contracts. Proposed location: docs/planning/2026-10-09/implementation-plan.md, P03, P05, P07, P10. Implementation locations will be recorded when implemented. LOCAL-01 startup reads scoped instance/hub status after readiness; P10 supplies real hub observations. Starting local infrastructure before NATS exists remains a bounded host bootstrap operation, not a kernel command channel. P00 proposes one authorized instance/work/partner status contract for terminal and dashboard clients; local pre-broker Compose startup is the bounded infrastructure exception. See delivery/decisions/startup-contract.md. This is a recommendation pending P00 review.",
      "why": "Operators need observable action control without opening protected kernel command channels.",
      "tradeoffs": "Local shell procedures are simpler but harder to govern; controls need authority, durable intent and honest unknown outcomes. Cached status must disclose age and unavailable services; it cannot authorize work, widen hub trust or prove partner capacity.",
      "locations": [],
      "verificationEvidence": [],
      "decisionEvidence": [
        "docs/planning/2026-10-09/implementation-plan.md",
        "docs/planning/2026-10-09/phases.json",
        "docs/planning/2026-10-09/delivery/decisions/README.md",
        "docs/planning/2026-10-09/delivery/contracts/README.md"
      ],
      "planningRevisions": [
        {
          "date": "2026-10-09",
          "decision": "LOCAL-01 approved automatic Compose startup direction",
          "previous": {
            "how": "Expose surrounding runtime operations for allowed drain, pause, cancellation and recovery over authorized NATS contracts. Proposed location: docs/planning/2026-10-09/implementation-plan.md, P03, P05, P07, P10. Implementation locations will be recorded when implemented.",
            "why": "Operators need observable action control without opening protected kernel command channels.",
            "tradeoffs": "Local shell procedures are simpler but harder to govern; controls need authority, durable intent and honest unknown outcomes."
          },
          "reason": "Retain earlier rationale; clarify bootstrap versus runtime control and client status. Planned only, not implementation evidence."
        },
        {
          "date": "2026-10-09",
          "decision": "P00 concrete implementation recommendation; pending review",
          "previousHow": "Expose surrounding runtime operations for allowed drain, pause, cancellation and recovery over authorized NATS contracts. Proposed location: docs/planning/2026-10-09/implementation-plan.md, P03, P05, P07, P10. Implementation locations will be recorded when implemented. LOCAL-01 startup reads scoped instance/hub status after readiness; P10 supplies real hub observations. Starting local infrastructure before NATS exists remains a bounded host bootstrap operation, not a kernel command channel.",
          "evidence": "docs/planning/2026-10-09/delivery/decisions/README.md"
        }
      ]
    },
    {
      "id": "PLAN-15",
      "status": "planned",
      "catalog": "eip",
      "pattern": "Content-Based Router",
      "source": "https://www.enterpriseintegrationpatterns.com/patterns/messaging/ContentBasedRouter.html",
      "referenceDepth": "full-public-reference",
      "how": "Route eligible work using explicit task requirements and current approved capabilities, with optional Jev advice. Proposed location: docs/planning/2026-10-09/implementation-plan.md, P05, P08, P10. Implementation locations will be recorded when implemented.",
      "why": "Connected teams need purposeful work distribution while preserving grants and origin ownership.",
      "tradeoffs": "Manual destination choice is simpler; semantic ranking adds cost/uncertainty and must never replace deterministic eligibility or receiver acceptance.",
      "locations": [],
      "verificationEvidence": [],
      "decisionEvidence": [
        "docs/planning/2026-10-09/implementation-plan.md",
        "docs/planning/2026-10-09/phases.json"
      ]
    }
  ]
}
```
