# P00 inventory review

Prepared October 9, 2026 against `c513ffa0565936916b342ae8ad7a8dc837b4d6e8`. P00-T01 is in verification. Mechanical ownership and source checks pass; maintainer review of public entry points and behavioral completeness remains required before P00 acceptance.

The frozen comparison baseline remains `df46e94570fadf78ef67a75a692dd48b968a10f7`. Do not replace that baseline with a later fixed source merely to obtain passing comparisons. Intended defect corrections retain their explicit old-failure/new-pass evidence.

## Inventory evidence

`python docs/planning/2026-10-09/verify-component-coverage.py` passed. It checked 338 baseline Git blobs plus six additional governed files, 93 components, 198 behavior checks, 37 functional groups, 99 phase criteria and 62 failure scenarios. [inventory-check.json](inventory-check.json) retains the output.

The [file inventory](../../../component-inventory.json) records every path and component owner. The [surface index](../../../source-surface-index.json) records declarations and literal HTTP paths from non-vendor source with fingerprints. The [preservation matrix](../../../component-preservation.md) records behavior, reuse and future checks. Together they provide the review set; a count or declaration parser cannot establish runtime parity.

## Surface review map

| Surface to review | Existing source/component ownership | Required retained behavior |
| --- | --- | --- |
| Terminal commands and process lifecycle | `agentmux.sh`, `agentmux.cmd`, HAR-01 through HAR-06, HAR-09 through HAR-14 | Launch, attach, observe/input, cleanup/archive, auth, identities/claims, board/team, dispatch/pool/worktrees, review and courier behavior. Platform and terminal differences remain explicit. |
| Agent definitions and package content | HAR-07/HAR-08, DASH-05, HUB-09 | Parsing, roster selection, bundled instructions and plugin dispatch. Preserve declared identities and behavior when wrapping/extracting. |
| Hub commands, storage and transports | HUB-01 through HUB-07, HUB-14 | Names/addresses, local server and adoption, CLI verbs, store ownership/recovery, tmux transport, screen profiles and receipts. Current local SQLite is a baseline, not the approved future shared authority. |
| Federation and shared capabilities | HUB-08 through HUB-25, DASH-09 | Existing core bridge and JetStream federation, configuration/trust, messages, work, boards, knowledge, code, quarantine/audit, MCP, enrollment and demos. Keep origin-owned work and the repaired reservation/result boundary. |
| Dashboard and operator workflows | DASH-01 through DASH-13, DASH-28 through DASH-35 | Existing ten-view shell and terminal grid, guarded HTTP actions, feed, board, agents, teams, run review, hub/federation, auth, resources and external integrations. An observational terminal stream does not make all dashboard actions read-only. |
| Industrial and vendor tools | DASH-14 through DASH-27, REPO-09 | Modbus TCP/serial, MQTT, scanning, PROFINET, BOOTP/DHCP, EtherNet/IP/Logix, ADS/EtherCAT, CODESYS and PCAP analysis. Preserve the existing capabilities as plugin work; launch platform choices do not retire them. |
| External providers and systems | HAR-04/HAR-15/HAR-16, DASH-10/DASH-11/DASH-13/DASH-32 | Provider auth and gateway behavior, GitHub and Atlassian read/write guards. Repository tracking instead of Jira is a project delivery choice; the product integration stays in scope. |
| Evaluations, tests and historical evidence | HAR-17 through HAR-22, HUB-24 through HUB-26, DASH-29 through DASH-33 | Workloads, fixtures, orchestration demos, correlation/determinism checks, offline/live broker tests, browser checks and residue isolation. Preserve expected assertions and label old reports with source/environment. |
| Instructions, CI, packaging and contracts | REPO-01 through REPO-09, HAR-05/HAR-06, DASH-34 | Plain English, branch/merge restrictions, pattern history, CI checks, Git/privacy rules, versions/guides, host compatibility, vendor notices and historical references. |

The precise phase ownership is in the component manifests; this table groups overlapping surfaces for review and does not create new owners or omit the detailed records.

## Open review questions and boundaries

1. Maintainers must review dynamic CLI branches, generated/configured routes, plugin-discovered actions and provider/version assumptions against the complete manifests. The mechanical index explicitly does not prove that dynamic behavior is complete. No newly discovered unmapped file was found by the current validator; behavioral completeness is still awaiting review.
2. P00-T02/T07 must resolve the supported native macOS/Linux and WSL versions and startup hooks. Actual host qualification belongs to P06/P12. Existing Windows compatibility files remain inventoried.
3. P00-T04/T05 must define replacement authority and migration contracts before storage or execution owners change. Current SQLite, legacy socket/bridge and HTTP behavior remain the comparison source.
4. Broader runtime comparisons and missing hardware/provider environments remain with their phase owners. Current 20-test governance results and historical broker/dashboard results are listed in [the preflight](preflight.md); no blanket runtime pass is claimed.

P00-GATE requires the review outcome and any discovered gap to have an owner before advancing. This checkpoint changes documentation and delivery tracking only; no product capability or stored identity is removed.
