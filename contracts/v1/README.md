# Agentmux version 1 contracts

These contracts are the separate P01 implementation path. The existing hub and federation protocols continue using their own decoders and namespaces. A matching version number does not make legacy v2/v3 traffic compatible with this format.

The JSON Schema identifiers begin with `urn:agentmux:contract:1:`. Every wire object with a schema version declares `1.0.0`. Resolve schema references locally from this package; an incoming message cannot supply a schema URL to download. `common` supplies referenced definitions only; callers must select a concrete message/object schema, never use the definitions document as an admission check. Closed infrastructure objects reject unknown fields. Payload and state extension slots still require a registered domain-specific schema before a production owner executes them.

The initial Python and TypeScript libraries implement strict JSON parsing, schema checks, canonical bytes and Ed25519 attestations independently. The cross-language harness verifies interoperability rather than calling one library from both clients. This package is under implementation; it is not a complete plugin SDK or production domain service.

## Bytes and identity

Decode UTF-8 strictly and reject duplicate object keys, including escaped spellings of the same key. Comments, trailing commas, invalid Unicode and non-finite numbers are invalid. Preserve Unicode without normalization. Canonical bytes follow RFC 8785 JCS; exact large integers and decimals belong in domain-defined strings. Counters and revisions use the safe-integer range in the shared schema.

Hash the canonical domain payload. Sign canonical attestation claims, excluding the signature wrapper. The claims bind the operation, source, contract, message kind and destination. Verify the full envelope as well as the signature: an attacker must not be able to change an unsigned outer caller or destination while retaining valid inner claims.

Verification receives an already trusted public key and expected audience from its caller. It never treats a key in a message as trusted or retrieves caller-selected key URLs. Production owners must resolve the exact enrolled issuer/key revision, authenticate the ingress credential, enforce current grants and use durable operation identities. Signature validity alone supplies none of those permissions. Broker credentials and attestation signing keys are separate.

## Compatibility and remaining work

P00 draft schemas and model evidence remain in the planning package as history. These promoted schemas do not rewrite those records. Incompatible schema changes require a new contract major version and explicit negotiation; producer and consumer fixtures must demonstrate every advertised compatible change.

P01 still requires named domain payload schemas, lifecycle and delivery semantics, a real NATS persistence spike, two-hub fault cases, CI rejection checks and supported-platform evidence before its gate. Later phases implement plugin construction, enrollment, domain execution and real runtime authorization. No existing source, stored identity or user action is retired by adding these files.
