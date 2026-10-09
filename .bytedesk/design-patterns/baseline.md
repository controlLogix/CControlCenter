# Enterprise baseline 1.1.0

These are ADAG's plugin baseline requirements proposed through the founding interview and implemented uniformly. Pattern authors and framework vendors do not mandate this policy. Architecture is always selected through each project's interview. No rule prescribes a topology, framework, cloud, or pattern quota. DP011 prescribes the shared frontend component structure for web and desktop presentation code.

| ID | Mandatory outcome | Review evidence |
| --- | --- | --- |
| DP001 | Architecture follows recorded capabilities, constraints, alternatives and an explicit decision. | Decision record and boundaries in source. |
| DP002 | Components have cohesive responsibilities, explicit ownership and public contracts; dependencies respect chosen boundaries. | Representative calls/imports, API/event/state contracts, ownership. |
| DP003 | External effects have explicit failure, consistency and resource-bound behavior. | Applicable timeout/retry/idempotency/backpressure/cancellation paths; transaction semantics. |
| DP004 | Trust boundaries validate inputs and authorize operations; secrets stay outside source and sensitive data outside diagnostics. | Boundary code, identity flow, secret configuration and logging review. |
| DP005 | Relevant behavior and contracts are tested; build and test outcomes are recorded honestly. | Actual test files and run evidence; characterization before consequential refactoring. |
| DP006 | Operators/users can identify failures and recover; quality targets are measurable. | Diagnostics, health/recovery guidance and performance/recovery targets appropriate to the workload. |
| DP007 | A clone builds independently with declared dependencies and recorded toolchains; artifacts have identities and versions. | Manifests, lockfiles where the ecosystem provides them, CI and release metadata. |
| DP008 | Changes preserve agreed public and persistence contracts or include an intentional migration path. | Compatibility tests, schema/API changes and migration/rollback design. |
| DP009 | Web/desktop flows handle loading, empty, failure, cancellation and accessible interaction as applicable. Desktop host privileges and persistence ownership are explicit. | UI interaction tests, accessibility checks and process/host boundary code. Required for web/desktop surfaces only. |
| DP010 | CODESYS execution is bounded, lifecycle/state ownership is explicit, and target/library compatibility is recorded and compiled when the toolchain exists. | ST/exports, task configuration, build diagnostics, exact target/compiler/library profile. Required for CODESYS surfaces only. |
| DP011 | Reusable frontend UI is atomized into `src/components/{atoms,molecules,organisms,templates}` with strict downward dependencies; pages/screens/features own routing, application state, data and services. | Component paths, imports, public contracts, focused tests, accessibility evidence, and composition-root code. Required for web/desktop surfaces only. |

DP003 and DP004 still apply to a local component: document why there are no remote effects/trust boundaries and show local validation/resource bounds. DP001–DP008 cannot be disabled. DP009 and DP011 apply to web/desktop surfaces; DP010 applies to CODESYS. Applicability is checked in code review and by deterministic structure checks where possible.

Strict uniform rules coexist with incremental adoption. Only unchanged legacy source may carry scheduled debt; any touched file with a confirmed unresolved violation must be repaired before passing. This intentionally uses a conservative file-level change boundary rather than pretending to prove whether a line edit affects a finding. Keep refactoring slices focused.

The deterministic gate checks the completeness/freshness of review evidence and remediation provenance. It cannot prove the truth of an architectural judgment or replace compiler, behavioral, security, accessibility, load or controller tests. An unavailable toolchain is an explicit verification gap, not a fabricated pass or a rule waiver.
