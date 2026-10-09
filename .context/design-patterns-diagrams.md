# Design pattern diagrams

Generated from `.context/design-patterns.md` and verified repository evidence. User notes may be added outside the generated sections.

## Abstract pattern architecture

```mermaid
flowchart LR
  Agent[Agent CLI / Claude] -->|FED-15 Messaging Gateway| Hub[Local hub]
  Hub -->|FED-02 Transactional Client| Outbox[(Outbox)]
  Outbox -->|FED-08 Content Filter + FED-07 Message Filter| Bridge[FED-01 Messaging Bridge]
  Bridge -->|FED-03 Guaranteed Delivery| Streams[(JetStream streams)]
  Streams -->|FED-05 Durable Subscriber| Inbound[Inbound guard]
  Streams -->|FED-06 Competing Consumers| Work[Work pullers]
  Inbound -->|FED-04 Idempotent Receiver| Plugins[Capability plugins]
  Plugins -->|FED-17 Facade| Bridge
  Plugins -->|FED-09 Envelope Wrapper| Agent
  Plugins -->|FED-14 Shared Database| KV[(KV board)]
  Plugins -->|FED-11 Claim Check| Git[(Shared git remote)]
  Bridge -->|FED-13 Message Store| Audit[(Audit log)]
  Operator[Operator] -->|FED-12 Control Bus| Bridge
  Envelope[FED-10 Canonical Data Model] -.-> Streams
  Result[FED-16 Correlation Identifier] -.-> Work
```

```plantuml
@startuml
actor Agent
actor Operator
component "Local hub" as Hub
database "Outbox" as Outbox
component "FED-01 Messaging Bridge" as Bridge
database "JetStream streams" as Streams
component "Inbound guard" as Inbound
component "Capability plugins" as Plugins
database "KV board" as KV
database "Shared git remote" as Git
database "Audit log" as Audit
Agent --> Hub : FED-15 Messaging Gateway
Hub --> Outbox : FED-02 Transactional Client
Outbox --> Bridge : FED-08 Content Filter / FED-07 Message Filter
Bridge --> Streams : FED-03 Guaranteed Delivery
Streams --> Inbound : FED-05 Durable Subscriber
Streams --> Plugins : FED-06 Competing Consumers
Inbound --> Plugins : FED-04 Idempotent Receiver
Plugins --> Bridge : FED-17 Facade
Plugins --> Agent : FED-09 Envelope Wrapper
Plugins --> KV : FED-14 Shared Database
Plugins --> Git : FED-11 Claim Check
Bridge --> Audit : FED-13 Message Store
Operator --> Bridge : FED-12 Control Bus
note right of Streams : FED-10 Canonical Data Model (envelope v2, rid)
note right of Plugins : FED-16 Correlation Identifier (origin_id)
@enduml
```

## Concrete implementation architecture

```mermaid
classDiagram
  class Bridge["hub/bridge.py Bridge (FED-01)"]
  class Federation["hub/fed/runtime.py Federation (FED-01, FED-05, FED-12, FED-17)"]
  class Ledger["hub/fed/ledger.py (FED-02, FED-04, FED-13)"]
  class Guard["hub/fed/guard.py (FED-07, FED-09)"]
  class Redact["hub/fed/redact.py scrub (FED-08)"]
  class Envelope["hub/fed/envelope.py + policy.py (FED-10)"]
  class Conn["hub/fed/conn.py STREAMS (FED-03)"]
  class Plugin["hub/fed/plugin.py Plugin"]
  class Messages["plugins/messages.py"]
  class Work["plugins/work.py (FED-06, FED-16)"]
  class Board["plugins/board.py (FED-14)"]
  class Knowledge["plugins/knowledge.py"]
  class Code["plugins/code.py (FED-11)"]
  class Mcp["hub/fed/mcp.py + hub/cli.py fed_main (FED-15)"]
  Federation --> Ledger
  Federation --> Guard
  Guard --> Redact
  Guard --> Envelope
  Federation --> Conn
  Federation o-- Plugin
  Plugin <|-- Messages
  Plugin <|-- Work
  Plugin <|-- Board
  Plugin <|-- Knowledge
  Plugin <|-- Code
  Mcp --> Federation : hub socket verbs
```

```plantuml
@startuml
class "hub/bridge.py Bridge (FED-01)" as Bridge
class "hub/fed/runtime.py Federation (FED-01, FED-05, FED-12, FED-17)" as Federation
class "hub/fed/ledger.py (FED-02, FED-04, FED-13)" as Ledger
class "hub/fed/guard.py (FED-07, FED-09)" as Guard
class "hub/fed/redact.py scrub (FED-08)" as Redact
class "hub/fed/envelope.py + policy.py (FED-10)" as Envelope
class "hub/fed/conn.py STREAMS (FED-03)" as Conn
abstract class "hub/fed/plugin.py Plugin" as Plugin
class "plugins/messages.py" as Messages
class "plugins/work.py (FED-06, FED-16)" as Work
class "plugins/board.py (FED-14)" as Board
class "plugins/knowledge.py" as Knowledge
class "plugins/code.py (FED-11)" as Code
class "hub/fed/mcp.py + cli fed_main (FED-15)" as Mcp
Federation --> Ledger
Federation --> Guard
Guard --> Redact
Guard --> Envelope
Federation --> Conn
Federation o-- Plugin
Plugin <|-- Messages
Plugin <|-- Work
Plugin <|-- Board
Plugin <|-- Knowledge
Plugin <|-- Code
Mcp --> Federation : hub socket verbs
@enduml
```

## Traceability

| Registry ID | Pattern | Role | Repository location | Evidence |
| --- | --- | --- | --- | --- |
| FED-01 | Messaging Bridge | hub messaging <-> NATS | `hub/bridge.py` Bridge, `hub/fed/runtime.py` Federation | `hub/tests/test_fed_live.py`, `hub/tests/test_nats_federation.py` |
| FED-02 | Transactional Client | outbox in the state change's transaction | `hub/fed/runtime.py` Federation.stage, `hub/fed/ledger.py` outbox_add, `hub/store.py` Store._outbox | `hub/tests/test_fed_live.py` |
| FED-03 | Guaranteed Delivery | JetStream file streams, R3 | `hub/fed/conn.py` STREAMS, `hub/fed/admin.py` provision | `hub/tests/test_fed_live.py` |
| FED-04 | Idempotent Receiver | fed_seen + Nats-Msg-Id | `hub/fed/runtime.py` Federation.receive, `hub/fed/ledger.py` seen | `hub/tests/test_fed_live.py` |
| FED-05 | Durable Subscriber | per-node durable pull consumers | `hub/fed/runtime.py` Federation._bind_core | `hub/tests/test_fed_live.py` |
| FED-06 | Competing Consumers | per-publisher work-queue consumers | `hub/fed/plugins/work.py` Work.on_tick | `hub/tests/test_fed_live.py` |
| FED-07 | Message Filter | trust, scope, spoof, privilege | `hub/fed/guard.py` inbound/outbound | `hub/tests/test_fed_unit.py`, `hub/tests/test_fed_live.py` |
| FED-08 | Content Filter | secret redaction/blocking | `hub/fed/redact.py` scrub | `hub/tests/test_fed_unit.py`, `hub/tests/test_fed_live.py` |
| FED-09 | Envelope Wrapper | remote text framed as data | `hub/fed/guard.py` wrap, `hub/fed/plugins/messages.py` | `hub/tests/test_fed_unit.py`, `hub/tests/test_fed_live.py` |
| FED-10 | Canonical Data Model | envelope v2, rid | `hub/fed/envelope.py` make, `hub/fed/policy.py` rid_for_remote | `hub/tests/test_fed_unit.py`, `hub/tests/test_fed_live.py` |
| FED-11 | Claim Check | git refs + pointer | `hub/fed/plugins/code.py` Code.v_share/v_fetch | `hub/tests/test_fed_live.py` |
| FED-12 | Control Bus | kill switch, revoke notice | `hub/fed/runtime.py` _v_kill, Federation._on_ctl | `hub/tests/test_fed_live.py` |
| FED-13 | Message Store | audit log | `hub/fed/ledger.py` audit | `hub/tests/test_fed_live.py` |
| FED-14 | Shared Database | KV board with CAS | `hub/fed/plugins/board.py` Board._write | `hub/tests/test_fed_live.py` |
| FED-15 | Messaging Gateway | CLI + MCP over the hub socket | `hub/fed/mcp.py` handle, `hub/cli.py` fed_main | `hub/tests/test_fed_unit.py` |
| FED-16 | Correlation Identifier | result -> origin item | `hub/fed/plugins/work.py` Work._on_result | `hub/tests/test_fed_live.py` |
| FED-17 | Facade | runtime as plugin ctx | `hub/fed/runtime.py` Federation, `hub/fed/plugin.py` Plugin | `hub/tests/test_fed_live.py` |

## Planned platform rearchitecture (proposal, October 9, 2026)

This section records the proposed destination for review. Existing FED diagrams above describe the current implementation and remain unchanged. PLAN entries have status `planned` and do not claim implemented or approved behavior.

```mermaid
flowchart TB
  Clients["Client / vendor / AG-UI adapters (PLAN-02)"] <--> Bus["NATS message contracts (PLAN-07, PLAN-08, PLAN-11)"]
  Runtime["Plugin construction and scoped clients (PLAN-01, PLAN-04)"] <--> Bus
  Runtime -->|Constructs scoped instances| Assembly["Nested assembly (PLAN-03)"]
  Assembly -->|Owns private child instance| Private["Parent-owned child"]
  Assembly -.->|References reusable package| Independent["Independent child package"]
  Boot["Protected kernel"] -->|Published information only, PLAN-05| Bus
  Bus <--> Work["Task / attempt owners and routing (PLAN-06, PLAN-15)"]
  Bus <--> State["Domain-owned conditional commits (PLAN-09, PLAN-10)"]
  State -->|NATS storage contracts| Records[("Authoritative JetStream records (PLAN-13)")]
  Records -->|Scoped replay| Views["View-building plugins"]
  Views -->|NATS KV API| KV[("Derived current views")]
  Views --> SQL[("Optional rebuildable SQL indexes")]
  Views <--> Bus
  Bus <--> Artifacts["Artifact reference service (PLAN-12)"]
  Bus <--> History["Scoped history and recovery (PLAN-13)"]
  History --> Records
  Bus <--> Control["Surrounding runtime controls (PLAN-14)"]
```

```plantuml
@startuml
component "Protected kernel" as Kernel
component "Client / vendor / AG-UI adapters\nPLAN-02" as Adapters
component "NATS contracts\nPLAN-07, PLAN-08, PLAN-11" as Bus
component "Plugin construction and scoped clients\nPLAN-01, PLAN-04" as Runtime
component "Nested assembly\nPLAN-03" as Assembly
component "Parent-owned child instance" as Private
component "Independent child package" as Independent
component "Task / attempt owners and routing\nPLAN-06, PLAN-15" as Work
component "Domain-owned conditional commits\nPLAN-09, PLAN-10" as State
database "Authoritative JetStream records\nPLAN-13" as Records
component "View-building plugins" as Views
database "Derived NATS KV views" as KV
database "Optional rebuildable SQL indexes" as SQL
component "Artifact reference service\nPLAN-12" as Artifact
database "Required event store\nPLAN-13" as History
component "Surrounding runtime controls\nPLAN-14" as Control
Kernel --> Bus : published information only (PLAN-05)
Adapters <--> Bus
Runtime <--> Bus
Runtime --> Assembly : constructs scoped instances
Assembly *-- Private : owns instance
Assembly ..> Independent : references reusable package
Bus <--> Work
Bus <--> State
State --> Records : NATS storage contracts
Records --> Views : scoped replay
Views --> KV : NATS KV API
Views --> SQL : local index
Views <--> Bus
Bus <--> Artifact
Bus <--> History
History --> Records
Bus <--> Control
@enduml
```

### Proposed contract ownership

| Proposed contract / component | Owning phases | Recorded patterns |
| --- | --- | --- |
| Plugin construction, nested lifecycle, scoped context | P02–P04 | PLAN-01, PLAN-03, PLAN-04, PLAN-05 |
| Client, worker, vendor and UI interfaces | P06, P07, P11 | PLAN-02 |
| Provider and eligible-work policy selection | P05, P08, P10 | PLAN-06, PLAN-15 |
| Shared envelopes and NATS communication | P01–P12 | PLAN-07, PLAN-08, PLAN-11 |
| NATS-owned records, durable intent and duplicate handling | P01, P04, P05, P10 | PLAN-09, PLAN-10, PLAN-13 |
| Scoped replay, derived KV and optional SQL indexes | P04, P07, P12 | PLAN-04, PLAN-13 |
| Artifact exchange, event history, authorized controls | P04, P07, P10, P12 | PLAN-12, PLAN-13, PLAN-14 |

Implementation symbols and files will be registered in the owning phases. The proposal is [docs/planning/2026-10-09/implementation-plan.md](../docs/planning/2026-10-09/implementation-plan.md).

STATE-01 updates only the planned destination. Configuration/registry KV records have their own owner; task-summary KV and SQL views are derived. Same-stream atomic persistence does not make cross-stream transfers, projection updates or tool actions atomic. Separate hubs preserve origin-task and receiver-execution authority. Historical FED diagrams above remain unchanged.


### ADD-01: Existing implementations through reviewed boundaries

This proposal refines PLAN-02. Historical FED diagrams above remain unchanged. Existing behavior stays available until its owning phase proves compatibility and migration. Replacing implementation does not authorize removing capability.

```mermaid
flowchart LR
  Existing["Existing harness, hub plugins, dashboard and tools"] --> Boundary["Retained or extracted code behind PLAN-02 interfaces"]
  Boundary --> Contracts["Scoped NATS contracts"]
  Tests["Existing assertions and new behavior fixtures"] --> Compare["Baseline and candidate evidence"]
  Existing --> Compare
  Boundary --> Compare
  Compare --> Gate["Owning phase review before cutover"]
```

See [component preservation](../docs/planning/2026-10-09/component-preservation.md) for concrete source ownership, tests, gains and migration requirements. This is a verification and migration view; it introduces no new pattern catalog entry.

### LOCAL-01: Planned automatic startup and status

This refines planned PLAN-02 client interfaces and PLAN-14 status/control boundaries. Existing implementation diagrams remain historical. Bootstrap coordination runs before NATS is available and grants no general kernel write access.

```mermaid
flowchart LR
  Client["Installed client startup adapter: PLAN-02"] --> Inspect["Resolve owned instance and local Docker context"]
  Inspect -->|"Healthy compatible instance"| Status["Scoped status through NATS: PLAN-14"]
  Inspect -->|"Absent or stopped"| Compose["Single startup owner: Docker Compose"]
  Compose --> Ready["Bounded readiness and persistence checks"]
  Ready --> Status
  Status --> Views["Same instance and authorized hub details in terminal and dashboard"]
```

P02 verifies bootstrap with explicit later-service fixtures; P06 verifies actual client launch; P07 verifies dashboard consistency; P10 verifies real hub visibility; P12 repeats the packaged workflow. The current plan defines conflict, timeout and recovery handling. No new pattern catalog entry or implemented relationship is claimed.

## October 9 baseline repairs: current work reservation boundary

The diagrams above are preserved as design history. This current detail revises FED-02, FED-04, FED-06, FED-07, FED-10 and FED-16; it does not mark the planned platform phases implemented.

```mermaid
sequenceDiagram
  participant O as Origin work plugin
  participant N as NATS / JetStream
  participant R as Receiving work plugin
  participant W as Local worker
  O->>O: Commit pending task and v3 offer outbox together
  O->>N: Publish versioned offer
  N->>R: Deliver or redeliver
  R->>R: Commit attributed blocked task and claim outbox together
  R->>N: Claim with offer digest and execution identity
  N->>O: Deliver claim
  O->>O: Commit one selected executor and grant outbox together
  O->>N: Publish grant
  N->>R: Deliver matching grant
  R->>R: Validate origin/offer/execution; become ready
  R->>W: Local claim and execution
  W->>R: Done or failed
  R->>R: Terminal state and durable return intent commit together
  R->>N: Retry stable result from outbox after any restart
  N->>O: Deliver result
  O->>O: Validate selected executor, grant, task/repository and content digest
```

An origin or receiver outage delays the exchange without selecting another executor. V2 work consumers use a different exact subject and cannot consume v3 offers. Same-peer nodes are distinct execution identities; the peer credential remains the authenticated principal. Schema migration 5 and snapshot publication are detailed in `docs/planning/2026-10-09/governance-repairs.md`.

## P00 runtime and account refinement — proposed

This detail supports PLAN-02/03/04/05/07/08/09/10/12/13/14. It remains a proposal in `docs/planning/2026-10-09/delivery/decisions/`; the bounded runtime spike proves only client wire interoperability. Existing implementation and historical diagrams above remain unchanged.

```mermaid
flowchart TB
  Host["Client hook / owned launcher: PLAN-02"] --> Compose["Selected local Compose project"]
  Compose --> Broker["NATS infrastructure"]
  subgraph Protected["Protected account and fixed release assembly: PLAN-03"]
    Boot["Boot plugin"] <--> Internal["Internal NATS subjects: PLAN-07"]
    Lifecycle["Kernel lifecycle plugin"] <--> Internal
    Status["Kernel status plugin"] <--> Internal
  end
  Status -->|"Exported information only: PLAN-05"| App["Scoped application NATS accounts"]
  Clients["Python / TypeScript SDK clients: PLAN-04"] <--> App
  Owners["Ordinary domain owner plugins"] <--> App
  Owners -->|"Conditional complete record: PLAN-09/10"| Records["Project JetStream ledger: PLAN-13"]
  Records --> Views["Rebuildable KV / SQL views"]
  Owners --> Artifacts["Immutable artifact references: PLAN-12"]
  App <--> Export["Agreement-scoped federation account"]
  Export <-->|"Leaf link; explicit exports"| Partner["Independent hub / persistence domain"]
```

No application arrow enters the protected account. The broker is shared infrastructure, while account permissions and domain-owner validation enforce distinct boundaries. A leaf link does not merge persistence or ownership. Proposed separate protected processes add lifecycle overhead; P02 must measure it. No Go implementation replaces current Python business logic through this diagram.
