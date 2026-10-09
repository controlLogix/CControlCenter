# Controlled worker and provider fixtures

`fake_execution.py` supplies a reusable `FakeProvider`, `FakeWorker` and immutable `ResponsePlan`. These are in-memory test helpers, not product services, provider adapters or substitutes for real NATS tests. They run no external tools and require no model token.

Create a provider and worker, then call `worker.start(operation, input_text, ResponsePlan(...), timeout=5)`. The provider records actual admission and keeps a callback supplied by the worker. Advance its integer clock with `provider.advance(ticks)`. Execution completion queues a response; `provider.deliver(operation)` invokes that callback. Completion and delivery are separate so tests can deliver different operations in any order. No sleeps or wall-clock races are needed.

| Control | Observable behavior |
| --- | --- |
| `output` and `delay` | At the configured tick the provider records completion and queues the chosen text. |
| `deliver(operation)` | Delivers one queued response through the actual callback; choosing operation order simulates reordered delivery. |
| Worker `timeout` and `poll_timeouts()` | Expired admitted work becomes unknown. The provider can still complete. No automatic retry is issued. A callback at or after the deadline also leaves the outcome unknown, even without polling. |
| Provider `available = False` before dispatch | Records non-admission, creates no provider request and returns unavailable to the worker. |
| `drop_reply=True` | Provider completion occurs but its response is lost. Worker timeout is unknown, not unavailable. |
| `cancel_confirmed=True` | A running provider stops and queues cancellation. The worker retains cancellation intent until explicit reconciliation observes the stop. |
| `cancel_confirmed=False` | The provider cannot confirm a stop and can later complete. Neither a callback nor reconciliation erases pending cancellation. |
| `worker.reconcile(operation)` | Explicitly observes provider state without resubmitting work. This trusted fixture lookup has no production authentication or durable authority. |

Provider and worker histories record separate inputs, outputs, deliveries and observations. Snapshots and delivered values are copied so test callers cannot change recorded output by mutating a returned object. Histories contain synthetic fixture data; callers must not put secrets or private reasoning in them.

Duplicate dispatch is deliberately rejected. Production durable duplicate handling is qualified by the existing recovery, storage and leaf fixtures. This helper does not claim persistence, restart recovery, current grant validation, concurrency safety, external side-effect fencing or final hub acceptance. It keeps late results separate from accepted observations and preserves unresolved cancellation; owners remain responsible for authorization and durable reconciliation.

Run `python tests/contracts/run.py --match ControlledExecution` with the prepared SDK environment to capture the existing runner's source-bound evidence. The normal contract suite also discovers these tests automatically. Hand-authored expected histories cover success, delay, reordered callbacks, timeout before completion, response exactly at the deadline, unavailable before dispatch, lost replies, confirmed and unconfirmed cancellation, immutable returned observations and invalid controls.
