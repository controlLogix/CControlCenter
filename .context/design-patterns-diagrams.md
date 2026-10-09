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
