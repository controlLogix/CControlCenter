# Design pattern context

This registry records how, where, and why approved Dofactory and Enterprise Integration Patterns are used in this repository. Keep historical entries and transition their status rather than deleting them.

<!-- design-patterns-registry:v1 -->
```json
{
  "schemaVersion": "1.0.0",
  "lastReviewed": "2026-10-08",
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
      "how": "Plugins write the outbox row (fed_outbox) and its audit row in the same SQLite transaction as the state change; the runtime publishes with a JetStream ack and only then marks the row sent.",
      "why": "A crash must never publish something that did not happen or lose something that did (FEDERATION.md 8).",
      "tradeoffs": "At-least-once on the wire, so receivers must be idempotent (FED-04). Alternative: publish directly from the verb, rejected - loses messages on disconnect.",
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
      "how": "Every inbound envelope id is recorded in fed_seen after its ingest commits; redeliveries are acked and skipped. Publishes carry Nats-Msg-Id so the stream also drops republished outbox rows.",
      "why": "JetStream redelivers after ack_wait and the outbox is at-least-once (FED-02).",
      "tradeoffs": "fed_seen grows with traffic (pruning is future work). Alternative: exactly-once publishing, not available end to end.",
      "locations": [
        {
          "path": "hub/fed/runtime.py",
          "symbol": "Federation.receive"
        },
        {
          "path": "hub/fed/ledger.py",
          "symbol": "seen"
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
      "how": "Federated role work goes to a work-queue stream; every hub that can serve (rid, role) pulls from one shared durable consumer per publisher, work_<from>_<rid>_<role>, only when it has idle capacity and trusts the publisher.",
      "why": "First claim wins across people: exactly one hub, then exactly one agent, does each item.",
      "tradeoffs": "One consumer per (publisher, repo, role). Hubs only pull from trusted publishers (A19), so an untrusted hub cannot swallow work. Alternative: per-subject queue groups (TM-218), rejected - no persistence.",
      "locations": [
        {
          "path": "hub/fed/plugins/work.py",
          "symbol": "Work.on_tick"
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
      "id": "FED-07",
      "status": "applied",
      "catalog": "eip",
      "pattern": "Message Filter",
      "source": "https://www.enterpriseintegrationpatterns.com/patterns/messaging/Filter.html",
      "referenceDepth": "full-public-reference",
      "how": "Inbound: drop malformed, spoofed (payload sender differs from the server-enforced subject token), self, unshared-rid and denied-peer traffic; quarantine approve-trust and privileged work. Outbound: refuse repos not shared with the recipient.",
      "why": "Interview F4/F5: per-peer trust and per-repo opt-in; F11: remote work never triggers privileged tools.",
      "tradeoffs": "Policy lives in each hub, so the circle (account) is the confidentiality boundary (A7). Alternative: server-side per-repo ACLs, deferred - needs JWT reissue on every share change.",
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
        "hub/tests/test_fed_live.py"
      ],
      "decisionEvidence": [
        "docs/FEDERATION.md"
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
      "how": "Envelope v2 {v,id,type,from,node,rid,to,at,data} and the repo identity rid = r + sha256(normalized remote)[:12]; local repo names are translated to and from rids at the edge.",
      "why": "Interview F6: two people's differently named clones of one repo must line up.",
      "tradeoffs": "Every plugin must translate at its edge. Alternative: agree on shared names, rejected in the interview.",
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
        "hub/tests/test_fed_live.py"
      ],
      "decisionEvidence": [
        "docs/FEDERATION.md"
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
      "how": "A federated item's result carries origin_id, the publisher's local work id, which closes the fed:pending placeholder on the origin hub.",
      "why": "Results arrive asynchronously, from another person, on a shared inbox subject.",
      "tradeoffs": "Origin ids are only unique per hub; the pair (peer, origin_id) is the key.",
      "locations": [
        {
          "path": "hub/fed/plugins/work.py",
          "symbol": "Work._on_result"
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
    }
  ]
}
```
