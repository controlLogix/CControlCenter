# P00 engineering decision acceptance

Codex accepts D01-D06, S01-S05, L01-L05 and the 0.1 contract package as the design basis for implementation. Review date: October 9, 2026. Reviewed source: `b067e98e8a051c33d7df2e7facfe26d9f747239a`. This decision completes the four scoped decision tasks; P00 advancement requires the separate gate record and verified push.

## Review outcome

- Runtime: use the narrow Go foundation with Python and TypeScript SDKs; retain current domain implementations. The recorded three-client comparison supports this choice without establishing production performance or platform support. Rewriting domain behavior in Go would add migration risk without evidence of benefit.
- Context and nesting: retain the protected four-plugin assembly, independent/private child declarations, immutable scoped context and per-operation authority. Process and wire boundaries preserve language neutrality. Shared unrestricted broker credentials would defeat the declared isolation and are rejected.
- Authority: NATS-backed owner ledgers are the source of shared business state, including configuration. KV and optional SQLite indexes are projections. The earlier split configuration write was rejected because its two commits could disagree. Owner transition, provenance and effect intent share a record; no cross-stream atomicity is claimed.
- Caller binding: an enrolled ingress signs canonical claims; domain owners verify identity, scope, content, audience and current grants. Plain caller identity references were rejected as insufficient proof. JCS avoids an ad hoc serialization format. Cross-language cryptographic tests remain mandatory P01 work.
- Recovery: disconnected accepted work remains reserved. Reassignment is explicit, uses a new epoch, and requires fencing or documented acceptance of unresolved effects. The model does not claim that an epoch stops a physical action. Cancellation and outcome uncertainty remain visible until reconciled.
- Launch: use an enrolled user profile, selected local Docker context, process-held lock, pinned Compose resources, authenticated reuse and bounded readiness checks. A port check or container-running state cannot establish readiness. Keep supported host launch paths explicit; lazy Desktop MCP startup alone does not satisfy app-launch automation.
- Identity and data: local identity remains separate from the initial Keycloak OIDC qualification target. External IdP storage does not become a shared task store. Provider destinations and budgets remain explicit. Jev is optional; it cannot grant authority or silently change disclosure destinations.
- Preservation: all 29 requirements have phase owners. The migration contract includes legacy tables, already-authoritative federation KV, CLI receipts, search projections, credentials and cross-domain events. No runtime source, user configuration or live data changed in this decision pass.

Independent subagent review found the split configuration authority and missing caller binding; both were corrected and re-reviewed with no remaining blocking design contradiction. Contract review also corrected migration omissions and reconciled reassignment wording with the model. Codex reviewed these findings and the final files rather than relying on a completion label.

## Evidence and limits

The contract report records 93 passing draft shape/model checks and source hashes. The runtime spike records three successful NATS clients, three absent-service failures and four Go build targets; only Linux/amd64 was executed. The source inventory and dynamic-dispatch review retain their own precise scope. Existing baseline defect evidence remains bound to unchanged runtime blobs. These results qualify the planning decisions and do not claim complete runtime security or migration parity.

| Required future proof | Owner and deadline |
| --- | --- |
| Canonical bytes, real signatures, SDK compatibility, competing writes and two-hub contract behavior | P01 before its gate |
| Real Compose boot, resource identity, locks, deadlines and readiness | P02 before its gate |
| Plugin construction, dependency/nesting and scoped service lifetimes | P03 before its gate |
| Real enrollment, issuer rotation, Keycloak flows, storage migration and execution isolation | P04 before its gate |
| Agent-client startup paths and all advertised host combinations | P06 and packaged qualification in P12 |
| Jev credentials, spend limits and approved evaluation data | P08 before live evaluation |
| Disconnected partner work, restoration and scope reconciliation | P10 before its gate |
| Industrial hardware/vendor versions and permitted test fixtures | P11 before claiming tool support |
| R3 independent hosts, backup/restore objectives, native macOS, performance and soak | P12 before its gate |

Missing implementation environments remain qualification gaps. They do not establish a pass and cannot be waived at those phases. The P00 deliverable is the reviewed contract and assigned verification; no unresolved design choice above prevents P01 from starting after the gate.

Rollback for this planning change is a reviewed feature-branch revert that preserves history. Product cutover rollback must follow the migration contracts; no data cutover occurred here. No merge is authorized.
