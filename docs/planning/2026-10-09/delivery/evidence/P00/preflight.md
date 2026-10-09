# P00 source-preservation preflight

Reviewed October 9, 2026 by Codex. Source candidate: `c513ffa0565936916b342ae8ad7a8dc837b4d6e8`. This completes preparation for P00 documentation and contract work. It does not accept P00, authorize P01, or qualify a future runtime.

## Scope and existing behavior

P00 owns the five files below through DASH-36 and REPO-01. Codex owns the preparation and evidence; Ryan and Nick retain the plan review required by P00-GATE. The complete repository inventory and later component owners remain in `component-inventory.json` and its four manifests.

| Component and files | Existing behavior and preservation decision | Verification owner |
| --- | --- | --- |
| DASH-36: `dashboard/SPEC.md`, `dashboard/SPEC_CC.md` | Retain both historical specifications. The original spec calls the dashboard read-only, yet also describes resize. The Control Center spec explicitly permits guarded mutations while keeping terminal streams read-only. Current code includes task/board writes, team actions, settings, ticket comments/transitions, Modbus writes and MQTT publication. Preserve these capabilities and their request guards; an older spec cannot remove them. | P00-T01 compares historical statements with the current surface; P07-GATE and P11-GATE qualify their future implementations. |
| REPO-01: `AGENTS.md`, `CLAUDE.md` | Retain both host entry files and shared links. Both now require the feature branch, Ryan/Nick demonstration and final merge approval, local fast testing, and ongoing repository task updates. The earlier manifest statement about missing CLAUDE.md restrictions is superseded with its original text retained in review history. | P00-T06 static review; P06-T01 and P06-GATE qualify actual host delivery/loading. |
| REPO-01: `.claude/rules/plain-language.md` | Retain the common writing rules, exact technical syntax and the distinction between public ISO guidance and a conformity claim. Link to one common rule set instead of duplicating divergent copies. | P00 static review; P06 host checks; all implementation reviews. |

The source fingerprints are in [source-checks.json](source-checks.json). The review inspected `dashboard/server.py` dispatch and guards; it did not invoke any operator action or access a running hub's records.

## Affected callers and surrounding contracts

| Surface | Existing owner | Required preservation and future check |
| --- | --- | --- |
| HTTP reads, guarded POST actions and terminal streams | DASH-02/P04; DASH-01/P07 | P04 request/identity fixtures must retain host, origin, body and method guards while adding user authorization. P07 must retain existing views/actions and read-only terminal observation. The operator's terminal remains a primary interaction surface. |
| Board, feed, team hiring and run acceptance | DASH-03 through DASH-07/P03/P05 | Preserve task/run IDs, links, roles, ownership and explicit review. Compare legacy assertions before replacing persistence or dispatch. |
| Provider and external-system actions | DASH-10 through DASH-13/P06; DASH-14 through DASH-26/P11 | Preserve guarded actions and capability-specific permissions. The choice not to use Jira for this implementation does not remove the product's existing Atlassian integration. |
| CLI and agent-host instruction loading | HAR-01, HAR-02, HAR-04/P06; HAR-05/P12 | P06 validates each advertised host hook, status output and instruction delivery. P12 verifies upgrades preserve user-authored configuration. Static root-file presence alone does not prove host loading. |
| Governance and component coverage | REPO-02, REPO-03/P01 | Retain pattern history and existing assertions. Run source coverage and pattern checks after edits. New entry points must have an owner before refactoring. |
| Delivery records and generated views | P00 tracker, owned planning assets | Keep tasks.json authoritative, retain task IDs/history, and regenerate the board/detail view. Planning status is separate from product runtime storage and cannot approve a phase or merge by itself. |

## Baseline, limits and safe scope

The frozen behavioral baseline is `df46e94570fadf78ef67a75a692dd48b968a10f7`. The current inventory covers 338 baseline files and six later governed files, 93 components, 198 behavior checks and all 37 functional groups. The validator checks ownership, pinned Git blobs, source fingerprints and references. It does not prove that every dynamic route, configuration or behavior has been exercised.

The original repair reproduction used `5ee428b8152ef3ac3f5036b8e1a930b1eec31d4e`. The five repaired runtime files have identical Git blobs at that commit and the frozen baseline. The old failing logs and final repair logs still match their recorded hashes. All eight recorded repair runtime/test files remain unchanged in the current source.

Current execution: `./hub/tests/local.ps1 hub.tests.test_governance` passed 20 tests with no skips in Ubuntu WSL, Python 3.14.4. The recorded runner duration was 1.706 seconds; this excludes WSL startup. [The result](governance-result.json) and [test log](governance-tests.log) are retained. Earlier full-suite results (119 hub tests and nine selected dashboard tests) remain historical evidence on their recorded source; they were not rerun for these documentation changes.

Native macOS, all supported terminal hosts, Docker Compose startup, future leaf-node topology, replicated persistence, vendor equipment and Ryan/Nick's real instances remain unqualified. P00-T02/T07 must resolve exact host/version and environment requirements. These gaps block claims or changes that depend on those environments; they do not block safe inventory and contract preparation. No runtime, data writer, configuration installer or host integration changes in this checkpoint.

## Reuse, migration and rollback

Retain historical documents and extend current instructions. The alternative of replacing the historical specs with one new document would discard provenance; use superseding notes instead. The alternative of duplicating all host rules increases drift; retain shared rules and verify delivery per host. No removal, reduced behavior or data migration is approved here.

Preserve `BASE-*`, component/check IDs, phase/task IDs, finding IDs and existing evidence references. Corrected audit statements carry their previous text in history. Documentation rollback uses a normal reviewed Git revert on the feature branch; do not erase task history or overwrite user configuration. Product rollback remains phase-specific. In particular, old software must not write a store containing active v3 reservations; the existing repair recovery procedure still applies.

## Assigned candidate and gain checks

| Owner task/gate | Evidence required later |
| --- | --- |
| P00-T01 / P00-GATE | Full inventory and public-entry-point review, explicit unknowns, baseline attribution, maintainer review. File counts alone are insufficient for phase acceptance. |
| P00-T02, T04, T05, T07 / P00-GATE | Alternatives and consequences for runtime/SDK, authority, state machines, persistence and LOCAL-01. Link every accepted decision to its implementation and failure cases; obtain required plan review. |
| P01-T02, T04, T06 / P01-GATE | Preserve baseline defect assertions, add missing contract fixtures, record fault boundaries and exact candidate evidence. [Baseline findings](baseline-findings.md) assigns each repaired invariant to its replacing task. |
| P04-T01/T02/T06 / P04-GATE | Authorization and NATS-state migration/rebuild comparisons; no loss of IDs, provenance, reservations or recoverable effects. |
| P05-T01/T04/T08 / P05-GATE | Existing orchestration assertions plus new owner acceptance, repository version and artifact evidence. |
| P06 / P06-GATE | Real host instructions and startup hooks, concurrent launch/reuse, safe configuration updates, startup diagnostics and supported host versions. REPO-01-C01 remains open until this evidence exists. |
| P07 / P07-GATE | Existing dashboard workflows and guarded controls plus AG-UI/CopilotKit interactions and reconnect behavior. |
| P10 / P10-GATE | Remote reservation, disconnected execution, reconnect and wrong-executor protections on the new topology. |
| P11/P12 gates | Existing tool actions in allowed test environments; packaging/upgrades preserve local settings and recovery paths. |

DASH-36-C01/C02 receive this static reconciliation as evidence. Their future candidate comparisons and REPO-01-C01 are not reported as runtime passes. P00-T06 is a preparation task; its completion does not depend on those future implementations already existing.
