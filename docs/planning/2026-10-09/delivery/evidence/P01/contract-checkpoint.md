# P01 initial executable contract checkpoint

This checkpoint adds isolated version 1 schemas, independent Python and TypeScript clients, and a cross-language fixture harness. Existing hub, dashboard, CLI and federation callers are unchanged. P01-T01/T02/T03 remain in progress.

The retained conformance result passes 12 tests and 286 subcases on the recorded local environment. Exact source bytes, built JavaScript, runtime versions and build-source comparisons are in `conformance-result.json`; no seed or request body is retained. The exact 1 MiB frame check is retained in `frame-boundary-after.json`.

Codex separately reran 13 Python unit tests and eight TypeScript unit tests in WSL. The first TypeScript invocation lacked the documented AGENTMUX_CONTRACT_EXAMPLES setting and failed two setup checks; the corrected invocation supplied both schema and example paths and passed all eight. Twenty existing governance tests passed before these isolated additions; their result is retained separately.

Review corrected container-depth parity, TypeScript's unbounded pending input, unsigned outer-envelope substitution, and the one-byte newline accounting difference. Schema compilation now uses bounded caches keyed by exact trusted bundle content, with changed-byte invalidation tests. Earlier conformance and boundary-reproduction outputs were observed but their temporary JSON reports were lost; they are not represented as retained evidence. The final persistent report is the verification source.

The source inventory now assigns all new contract/client/test files to HUB-01/HUB-26. The mechanical surface checker includes TypeScript while retaining its test-file exclusions. No existing assertion, component, baseline blob or pattern history was removed.

Still required before P01 acceptance: full named domain payload contracts and lifecycle/delivery semantics; actual NATS persistence and two-hub failure fixtures; preserved component assertions and CI rejection checks; macOS/Linux/WSL qualification. Supplied-key signature verification is not enrollment, transport authentication, current-grant authorization or durable replay protection. No phase advancement or merge is claimed.
