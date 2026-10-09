# P00 decisions for review

These are concrete engineering recommendations prepared on October 9, 2026. Ryan's existing requirements remain binding. Proposed implementation choices below are awaiting the P00 review; no Nick approval or phase advancement is recorded.

| Record | Scope | Task |
| --- | --- | --- |
| [Runtime and deployment](runtime-and-deployment.md) | Language comparison, protected assembly, SDKs, identity, execution, UI, capacity and data policy | P00-T02 |
| [Storage contract](storage-contract.md) | NATS authority, records, retention, access, recovery and qualification profiles | P00-T05 |
| [Automatic startup](startup-contract.md) | Instance ownership, Compose, host hooks, readiness, status and time limits | P00-T07 |

P00-T04 still needs the versioned manifest/context schemas, state machines and migration-owner contracts. These documents constrain that work. P00-T01 still needs maintainer review of the public entry points and behavioral inventory. The tracker keeps all of these tasks and the P00 gate open until the required work and review are complete.

The bounded [runtime comparison](../spikes/runtime/README.md) is executed evidence. Design proposals, performance targets and platform targets are not test results. No Jev token, provider inference, industrial device action, live user hub or Docker setting was used or changed by this preparation.
