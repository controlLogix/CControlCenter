# Component preservation and planned gains

**Status: static inventory checked during P00; full baseline/candidate qualification remains open.** The [live task board](implementation-status.md) records current work. The [P00 preflight](delivery/evidence/P00/preflight.md) and [baseline defect reconciliation](delivery/evidence/P00/baseline-findings.md) distinguish executed focused tests, retained historical results and missing environments. No phase acceptance is implied.

ADD-01 accounts for **338 baseline files**, **36 additional governed files**, **93 components**, and **198 behavior checks**. The [exact inventory](component-inventory.json) pins file ownership and Git blob identities. The [source surface index](source-surface-index.json) lists code declarations and literal HTTP paths for review. File coverage does not prove runtime correctness or complete behavioral coverage.

## Required preservation rule

Keep all current functionality available. Prefer retaining, wrapping, extracting or extending working code. Each replacement needs a recorded technical reason and equivalent behavior tests. The component records below propose an implementation approach; they do not authorize source deletion, a capability reduction, a narrower supported environment or production cutover. Codex reviews every proposed implementation or migration change against the full user scope; autonomous delivery does not authorize capability reduction or weaker verification. Correcting a defect requires an explicit intended-behavior change and a regression test.

Every changed component needs passing baseline and candidate comparisons, migration/recovery evidence, and evidence of its added capability before its phase advances. New functionality cannot compensate for an unrelated regression. Historical reports and skipped environments cannot count as current passes. All check statuses below remain `not-run`; actual results belong in a completed phase gate record.

The same preservation rule applies to later Jev and sandboxing phases even when their main feature is new. They must verify their affected callers, UI, stored data and client behavior. Dependencies can require checks from components owned by another phase.

## What each reuse decision means

| Decision | Required treatment |
| --- | --- |
| retain | Keep implementation and behavior; update only necessary contracts or packaging. |
| wrap | Expose current implementation through the new interface, with explicit authority and lifecycle. |
| extract | Move proven logic into an owned module/plugin while preserving behavior and tests. |
| extend | Add capability to existing implementation; demonstrate the old workflow still works. |
| replace | Document why reuse cannot meet a concrete requirement; retain equivalent intended behavior and migrate safely. |
| retain-evidence | Preserve provenance and history; do not treat historical results as current qualifications. |

## Component index

| Component | Owning phase | Reuse approach | Files | Checks |
| --- | --- | --- | ---: | ---: |
| [DASH-01 — Existing dashboard shell, ten views, terminal grid and preferences](#dash-01) | P07 | extract | 13 | 3 |
| [DASH-02 — HTTP routing, request guards and terminal stream server](#dash-02) | P04 | extract | 2 | 2 |
| [DASH-03 — Conversation feed and guarded sends](#dash-03) | P05 | extract | 4 | 2 |
| [DASH-04 — Task board, Kanban, records and policy](#dash-04) | P05 | extract | 8 | 3 |
| [DASH-05 — Agent definition registry and editor](#dash-05) | P03 | extract | 7 | 2 |
| [DASH-06 — Team roster proposal, approval and hiring](#dash-06) | P05 | extract | 6 | 2 |
| [DASH-07 — Run progress, review, diffs and completion gate](#dash-07) | P05 | extract | 3 | 2 |
| [DASH-08 — Hub observation panel](#dash-08) | P07 | wrap | 3 | 2 |
| [DASH-09 — Federation panel and operator actions](#dash-09) | P10 | wrap | 3 | 2 |
| [DASH-10 — Provider authentication settings and diagnostics](#dash-10) | P06 | wrap | 5 | 2 |
| [DASH-11 — GitHub observations, login and constrained writes](#dash-11) | P06 | wrap | 4 | 2 |
| [DASH-12 — Resource manifest and fixed diagnostic probes](#dash-12) | P06 | extend | 1 | 2 |
| [DASH-13 — Atlassian ticket view and action regression contract](#dash-13) | P06 | retain-evidence | 1 | 2 |
| [DASH-14 — IIOT view and Modbus TCP tag table](#dash-14) | P11 | extract | 4 | 3 |
| [DASH-15 — Modbus serial RTU transport](#dash-15) | P11 | wrap | 2 | 2 |
| [DASH-16 — Bounded legacy MQTT request endpoints](#dash-16) | P11 | wrap | 3 | 2 |
| [DASH-17 — MQTT topic monitor and publication UI](#dash-17) | P11 | extract | 2 | 2 |
| [DASH-18 — Private IPv4 scan and network observation UI](#dash-18) | P11 | wrap | 2 | 2 |
| [DASH-19 — PROFINET expected stations and imported comparison](#dash-19) | P11 | wrap | 1 | 2 |
| [DASH-20 — Privileged PROFINET DCP tool](#dash-20) | P11 | wrap | 2 | 2 |
| [DASH-21 — Passive BOOTP/DHCP observation tool](#dash-21) | P11 | wrap | 1 | 2 |
| [DASH-22 — EtherNet/IP explicit messaging library](#dash-22) | P11 | wrap | 2 | 2 |
| [DASH-23 — Rockwell Logix fragmented tag access](#dash-23) | P11 | wrap | 2 | 2 |
| [DASH-24 — ADS state, symbol and memory access](#dash-24) | P11 | wrap | 2 | 2 |
| [DASH-25 — TwinCAT EtherCAT diagnostics and confirmed state requests](#dash-25) | P11 | wrap | 2 | 2 |
| [DASH-26 — CODESYS target management and runtime actions](#dash-26) | P11 | wrap | 3 | 3 |
| [DASH-27 — Classic PCAP analyzer, PNG rendering and reproducible fixture](#dash-27) | P11 | wrap | 8 | 2 |
| [DASH-28 — Dashboard restart and OS startup integration](#dash-28) | P12 | extend | 3 | 2 |
| [DASH-29 — Isolated dashboard test runner and residue checks](#dash-29) | P01 | retain | 10 | 2 |
| [DASH-30 — Real browser dashboard workflow suite](#dash-30) | P07 | extend | 2 | 2 |
| [DASH-31 — Harness, coordination, lifecycle and plugin regressions located under dashboard](#dash-31) | P01 | retain-evidence | 18 | 2 |
| [DASH-32 — Bedrock gateway differential and HTTP contract evidence](#dash-32) | P06 | retain-evidence | 2 | 2 |
| [DASH-33 — Operator diagnostics, demos and fixture maintenance](#dash-33) | P06 | retain | 7 | 2 |
| [DASH-34 — Vendored terminal, MQTT and OUI dependencies](#dash-34) | P12 | retain | 18 | 2 |
| [DASH-35 — Existing branding and session-state assets](#dash-35) | P07 | retain | 8 | 2 |
| [DASH-36 — Historical dashboard build specifications](#dash-36) | P00 | retain-evidence | 2 | 2 |
| [HAR-01 — Provider launch, session entry and top-level command compatibility](#har-01) | P06 | extract | 1 | 2 |
| [HAR-02 — Terminal input, observation and modal helpers](#har-02) | P06 | extract | 2 | 3 |
| [HAR-03 — Lifecycle cleanup, archives and Claude credential convergence](#har-03) | P06 | extract | 1 | 3 |
| [HAR-04 — Provider authentication, key entry and operator permission setup](#har-04) | P06 | extend | 4 | 3 |
| [HAR-05 — Installation and Windows-to-WSL state compatibility](#har-05) | P12 | extend | 3 | 3 |
| [HAR-06 — macOS command compatibility helpers](#har-06) | P06 | retain | 5 | 2 |
| [HAR-07 — Agent definition parsing and roster selection](#har-07) | P03 | extract | 1 | 2 |
| [HAR-08 — Bundled personas and workflow instructions](#har-08) | P03 | retain | 14 | 2 |
| [HAR-09 — Claims, local identity, warrants and journal](#har-09) | P04 | extract | 2 | 3 |
| [HAR-10 — Board, task, epic and team command compatibility](#har-10) | P05 | wrap | 2 | 3 |
| [HAR-11 — Dispatch, worker pool, team worktrees and collection](#har-11) | P05 | extract | 2 | 3 |
| [HAR-12 — Run ledger, submission review, objections and completion](#har-12) | P05 | extract | 2 | 3 |
| [HAR-13 — Courier, post, virtual inbox and backlog recovery](#har-13) | P05 | extract | 2 | 3 |
| [HAR-14 — Notifications and originating-terminal feedback](#har-14) | P05 | extract | 1 | 2 |
| [HAR-15 — Jira and Confluence clients, scripts and setup](#har-15) | P06 | wrap | 3 | 3 |
| [HAR-16 — Bedrock Responses-to-Chat gateway](#har-16) | P06 | wrap | 1 | 2 |
| [HAR-17 — Recovered Bedrock reference artifact](#har-17) | P01 | retain-evidence | 2 | 2 |
| [HAR-18 — Small orchestration acceptance workloads and their tests](#har-18) | P01 | retain | 14 | 2 |
| [HAR-19 — Historical communication extraction tools](#har-19) | P01 | retain-evidence | 6 | 2 |
| [HAR-20 — Communication correlation, spot checks and determinism history](#har-20) | P01 | retain-evidence | 5 | 2 |
| [HAR-21 — Recorded orchestration demonstration results](#har-21) | P01 | retain-evidence | 22 | 2 |
| [HAR-22 — Historical test-gate isolation evidence](#har-22) | P01 | retain-evidence | 1 | 2 |
| [HUB-01 — Protocol names and local addresses](#hub-01) | P01 | retain | 10 | 2 |
| [HUB-02 — Local hub server, identity, lifecycle and legacy adoption](#hub-02) | P05 | extract | 2 | 3 |
| [HUB-03 — Hub store, work ownership, messaging and recovery](#hub-03) | P04 | extract | 1 | 3 |
| [HUB-04 — Hub CLI and federation command client](#hub-04) | P06 | wrap | 1 | 2 |
| [HUB-05 — Terminal transport abstraction and tmux backend](#hub-05) | P06 | wrap | 1 | 2 |
| [HUB-06 — CLI screen profiles and guarded terminal input](#hub-06) | P06 | extract | 2 | 2 |
| [HUB-07 — Native client receipt scanning and hold evidence](#hub-07) | P06 | retain | 1 | 2 |
| [HUB-08 — Existing core-NATS bridge](#hub-08) | P10 | wrap | 1 | 2 |
| [HUB-09 — Existing federation plugin contract and package structure](#hub-09) | P03 | extend | 3 | 2 |
| [HUB-10 — Federation runtime, supervision, control and observations](#hub-10) | P10 | extract | 1 | 3 |
| [HUB-11 — Federation configuration, trust and repository identity](#hub-11) | P01 | extend | 3 | 2 |
| [HUB-12 — Federation guard and outbound secret filtering](#hub-12) | P04 | extend | 2 | 2 |
| [HUB-13 — Privileged remote-work host hook](#hub-13) | P11 | wrap | 2 | 2 |
| [HUB-14 — Federation outbox, idempotency, audit and quarantine ledger](#hub-14) | P04 | extract | 1 | 2 |
| [HUB-15 — NATS connection, storage layout and administration API](#hub-15) | P02 | extend | 2 | 2 |
| [HUB-16 — Federation messages and handoffs plugin](#hub-16) | P10 | extract | 1 | 2 |
| [HUB-17 — Federated work distribution and result plugin](#hub-17) | P10 | extend | 1 | 3 |
| [HUB-18 — Shared board plugin and local mirror](#hub-18) | P10 | extend | 1 | 2 |
| [HUB-19 — Shared knowledge, offline search, capture and notifications](#hub-19) | P10 | extract | 1 | 3 |
| [HUB-20 — Git code sharing and verified fetch plugin](#hub-20) | P10 | extract | 1 | 2 |
| [HUB-21 — Stdio MCP gateway](#hub-21) | P06 | wrap | 1 | 2 |
| [HUB-22 — Federation dependency manifests](#hub-22) | P12 | retain | 2 | 1 |
| [HUB-23 — NATS deployment, account enrollment and credentials](#hub-23) | P10 | extend | 5 | 3 |
| [HUB-24 — Local live demo, sample repositories and scoring](#hub-24) | P01 | retain-evidence | 5 | 3 |
| [HUB-25 — Cross-user federation walkthrough and live-agent demo](#hub-25) | P10 | retain-evidence | 2 | 2 |
| [HUB-26 — Hub regression suites and federation test harness](#hub-26) | P01 | retain | 31 | 3 |
| [REPO-01 — Repository instructions and writing rules](#repo-01) | P00 | extend | 3 | 1 |
| [REPO-02 — Design-pattern governance and recorded history](#repo-02) | P01 | extend | 13 | 1 |
| [REPO-03 — Continuous integration workflows](#repo-03) | P01 | extend | 2 | 1 |
| [REPO-04 — Git text, binary and privacy rules](#repo-04) | P12 | extend | 2 | 1 |
| [REPO-05 — Product version and main user guide](#repo-05) | P12 | extend | 2 | 1 |
| [REPO-06 — Harness contracts and known operational limits](#repo-06) | P06 | extend | 3 | 1 |
| [REPO-07 — Hub, federation and transport specifications](#repo-07) | P10 | extend | 3 | 1 |
| [REPO-08 — Historical handover and reference screenshots](#repo-08) | P07 | retain-evidence | 6 | 1 |
| [REPO-09 — Vendor documentation references](#repo-09) | P11 | extend | 1 | 1 |

## Coverage and evidence limits

All four source reviews use code, tests, configuration and available repository documentation. Vendored code is assigned to its consuming dependency component and reviewed for integration, version and license obligations; this is not a line-by-line vendor security audit. Binary fixtures, images and recovered bytecode are inventoried and preserved, not represented as decompiled or newly executed evidence. Ignored machine state, external vendor tools, installed client plugins and live accounts require separate deployment inventories in P00/P06/P11/P12.

P00 must reconcile maintainers’ workflows with the declared entry points. Missing, ambiguous and dynamically contributed behaviors block the affected implementation boundary until they have a record. The validator prevents unowned files and broken references, but reviewers still decide whether each behavior list and test is sufficient.

## Detailed component records

<a id="dash-01"></a>
### DASH-01 — Existing dashboard shell, ten views, terminal grid and preferences

**Owner:** P07. **Approach:** extract. **Baseline groups:** BASE-17, BASE-10, BASE-36.

**Current behavior**

- Navigation contains Terminals, Status, Board, Runs, Hub, Federation, Organization, IIOT, GitHub and Settings; registered views, panels and cards control visible-view polling.
- Terminals reuse xterm instances across roster polls, receive one shared SSE connection with snapshots/chunks/gone events, reconnect after errors, and retain a single-agent stream fallback. Stale or malformed roster observations do not fabricate termination.
- The ribbon composes launch commands for an operator; it does not send terminal keystrokes. Pane resizing is an explicit opt-in write. Grid/free placement, focus, follow, row height, text size, minimum font and UI scale affect presentation.
- Browser localStorage retains layout, placements, tabs, collapsible cards, feed filters and imported themes. Themes can be validated, imported and exported.
- Status combines feed, message queue, journal and chatter; current filtered rows export to CSV/JSON. Board and Organization have nested tabs. Settings exposes themes, resources, provider methods and Atlassian setup.

**Reuse:** Keep the running dashboard available. Extract existing rendering, fit, preferences and interaction behavior into the required component tiers one view at a time; connect each migrated feature to authorized AG-UI projections. Retain xterm through a component wrapper. Do not create a competing replacement dashboard.

**Added functionality or operating benefit**

- Project/user-scoped views and explicit stale/rebuild state from NATS-backed records.
- AG-UI/CopilotKit integration, accessible reusable components and independently loaded domain contributions.
- Versioned preference import with deliberate migration from local browser settings.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-01-C01 | All ten views and their subtabs remain reachable; refresh, switching, collapse and hidden-view behavior preserve state and avoid unintended probes. | [test_frontend_tabs.sh](../../../dashboard/test_frontend_tabs.sh), [test_frontend_collapse.sh](../../../dashboard/test_frontend_collapse.sh), [test_frontend.sh](../../../dashboard/test_frontend.sh), [test_e2e.mjs](../../../dashboard/test_e2e.mjs) | Isolated dashboard home and port; Node DOM fixtures, then Playwright browser on supported macOS/Linux/WSL hosts. No live user state. |
| DASH-01-C02 | Terminal snapshots, chunks, reconnect, generation changes, malformed rosters and multiple viewers preserve correct output without restarting agents; resizing occurs only when opted in. | [test_snapshot.py](../../../dashboard/test_snapshot.py), [test_stream_slots.sh](../../../dashboard/test_stream_slots.sh), [test_frontend.sh](../../../dashboard/test_frontend.sh) | Isolated dashboard home and port; Node DOM fixtures, then Playwright browser on supported macOS/Linux/WSL hosts. No live user state. |
| DASH-01-C03 | Theme import/export, unsafe-color rejection, layout/focus/follow/free positions and filtered CSV/JSON export have old/new fixture parity. | [test_themes.sh](../../../dashboard/test_themes.sh), [test_theme_import.sh](../../../dashboard/test_theme_import.sh), [test_frontend_tabs.sh](../../../dashboard/test_frontend_tabs.sh) | Isolated dashboard home and port; Node DOM fixtures, then Playwright browser on supported macOS/Linux/WSL hosts. No live user state. |

**Migration and compatibility checks**

- Record every view, subtab, terminal command and preference key before moving it; move one view behind configuration and compare old/new fixtures.
- Keep resize and any existing dashboard mutation in the action inventory; policy changes need an explicit decision, not omission during an observer-focused redesign.
- Preserve unknown/stale/ended distinctions, source IDs, theme tokens and opt-in geometry behavior.

**Known limits and review gaps**

- Current frontend is vanilla JavaScript and xterm, with no AG-UI/CopilotKit implementation.
- Some comments still describe the entire page as read-only even though current board, review and integration actions mutate state.
- Shape/DOM fixture checks do not prove real browser accessibility or complete end-to-end parity.

**Files**

- [dashboard/index.html](../../../dashboard/index.html)
- [dashboard/app.js](../../../dashboard/app.js)
- [dashboard/style.css](../../../dashboard/style.css)
- [dashboard/themes.json](../../../dashboard/themes.json)
- [dashboard/fitmatrix.js](../../../dashboard/fitmatrix.js)
- [dashboard/test_frontend.sh](../../../dashboard/test_frontend.sh)
- [dashboard/test_frontend_tabs.sh](../../../dashboard/test_frontend_tabs.sh)
- [dashboard/test_frontend_collapse.sh](../../../dashboard/test_frontend_collapse.sh)
- [dashboard/test_frontend_post.sh](../../../dashboard/test_frontend_post.sh)
- [dashboard/test_themes.sh](../../../dashboard/test_themes.sh)
- [dashboard/test_theme_import.sh](../../../dashboard/test_theme_import.sh)
- [dashboard/test_snapshot.py](../../../dashboard/test_snapshot.py)
- [dashboard/test_stream_slots.sh](../../../dashboard/test_stream_slots.sh)

<a id="dash-02"></a>
### DASH-02 — HTTP routing, request guards and terminal stream server

**Owner:** P04. **Approach:** extract. **Baseline groups:** BASE-17, BASE-18, BASE-23.

**Current behavior**

- Loopback HTTP server routes board CRUD/gates, runs/review/diff, hub and federation, auth settings, Jira actions, Modbus, both MQTT paths, scans, PROFINET import, GitHub actions, resources, feeds, agents and terminal streams.
- Host/Origin, method, content type, body length, name/path, timeout and concurrency checks protect local routes; stream generations and bounded slots handle reconnects.
- Legacy epics/tasks/journal/messages/devices/status/delete routes coexist with richer board operations. Board writes include create/update/status/move/delete, acceptance/labels/dependencies/evidence/commits/touched paths/comments/links/triage/state/config, plus agent/team/CODESYS/chatter actions.
- Static asset handling and explicit script-load errors let operators diagnose a stale server serving an incomplete UI.

**Reuse:** Retain guarded routes as compatibility adapters while moving each operation to its declared owner over NATS. Reuse validators and response fixtures; keep one authoritative writer. Replace the single local-operator identity assumption with authenticated user/project context.

**Added functionality or operating benefit**

- Authenticated per-project access across snapshots, streams, artifacts and writes.
- Scoped command contracts, explicit operation IDs and controlled HTTP compatibility deprecation.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-02-C01 | Inventory every GET/POST route and board operation; compare accepted inputs, refusals, response shape and side effects against the owning NATS command before route cutover. | [test_host_guard.py](../../../dashboard/test_host_guard.py), [test_board.py](../../../dashboard/test_board.py), [test_fed_panel.py](../../../dashboard/test_fed_panel.py), [test_hub_panel.py](../../../dashboard/test_hub_panel.py), [test_field_panels.py](../../../dashboard/test_field_panels.py) | Python and/or Node offline fixtures in temporary directories; no provider, broker or hardware calls. |
| DASH-02-C02 | Direct requests, guessed IDs, hostile Host/Origin, malformed bodies and unauthorized streaming cannot cross users/projects; preserve legacy bounded error behavior. | [test_host_guard.py](../../../dashboard/test_host_guard.py), [test_frontend_post.sh](../../../dashboard/test_frontend_post.sh) | Isolated dashboard home and port; Node DOM fixtures, then Playwright browser on supported macOS/Linux/WSL hosts. No live user state. |

**Migration and compatibility checks**

- Preserve legacy route clients until a documented compatibility change is accepted.
- Move domain writes out of server.py by endpoint group; do not wrap unsafe existing operator attribution as authenticated authority.
- Preserve stream path, generation, timeout, log-file validation and body-size contracts or approve their replacements.

**Known limits and review gaps**

- Host/Origin checks are not authenticated user sessions or tenant authorization.
- server.py combines many domains; passing one route suite cannot establish coverage of all operations.
- Existing route actions are retained requirements; their launch-time placement in dashboard versus another client still needs explicit policy approval.

**Files**

- [dashboard/server.py](../../../dashboard/server.py)
- [dashboard/test_host_guard.py](../../../dashboard/test_host_guard.py)

<a id="dash-03"></a>
### DASH-03 — Conversation feed and guarded sends

**Owner:** P05. **Approach:** extract. **Baseline groups:** BASE-09, BASE-10, BASE-17.

**Current behavior**

- Chatter merges bounded courier, delivery and receipt history with stable message identities, thread/card/agent filters and explicit unconfirmed states.
- The panel can send through the existing CLI guard, with recipient/text/reference and visible send outcomes; cursor adoption alone is not delivery.
- Notifications and feed rationing retain critical notices even when one source floods the feed.

**Reuse:** Reuse feed merging, receipt distinctions, filtering and guarded-send fixtures in a conversation owner; expose the same activity through the dashboard's authorized interface.

**Added functionality or operating benefit**

- Durable NATS conversation identity and project visibility.
- Consistent transport receipt, execution and accepted-result distinctions.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-03-C01 | Merge retries, dropped/dead messages, partial records and adopted cursors without inventing delivery; preserve thread filters and export rows. | [test_chatter.py](../../../dashboard/test_chatter.py), [test_notify.py](../../../dashboard/test_notify.py) | Python and/or Node offline fixtures in temporary directories; no provider, broker or hardware calls. |
| DASH-03-C02 | Unauthorized or modal-blocked sends are refused; uncertain sends remain visible and replaying history does not send again. | [test_chatter.py](../../../dashboard/test_chatter.py) | Python and/or Node offline fixtures in temporary directories; no provider, broker or hardware calls. |

**Migration and compatibility checks**

- Migrate queue cursors, pending/dead letters and journal references once with sender and scope.
- Preserve send controls or explicitly move them to a supported client with reviewed workflow equivalence.

**Known limits and review gaps**

- Current local sender attribution is not multi-user authentication; courier history may lack exact message IDs.

**Files**

- [dashboard/chatter.js](../../../dashboard/chatter.js)
- [dashboard/chatter_feed.py](../../../dashboard/chatter_feed.py)
- [dashboard/test_chatter.py](../../../dashboard/test_chatter.py)
- [dashboard/test_notify.py](../../../dashboard/test_notify.py)

<a id="dash-04"></a>
### DASH-04 — Task board, Kanban, records and policy

**Owner:** P05. **Approach:** extract. **Baseline groups:** BASE-04, BASE-05, BASE-15, BASE-16, BASE-17.

**Current behavior**

- cc.db stores stable never-reused EP/TM/ADR/SP/CAP identifiers, state/history, dependencies, labels, evidence, acceptance items, comments, commits and touched paths.
- Board/epic layout and Kanban status columns support create, edit, move, delete, details and status changes; stale writes and refusal reasons are surfaced.
- Domain gates enforce readiness, evidence, actor/dependency/WIP checks and recorded overrides; soft deletion preserves identifier history.
- Legacy store also retains device records and bounded queue ingestion; request adapters expose journal/messages/status and old epics/tasks paths.

**Reuse:** Extract the existing domain rules and validation into task/planning owners, retaining their fixtures and UI behaviors. Migrate cc.db records into authoritative NATS records under STATE-01; retain SQL only as an optional rebuildable query view.

**Added functionality or operating benefit**

- Multi-user optimistic concurrency and explicit project scope.
- Replayable history and shared task state without direct database access.
- Atomic Design board components using existing interaction semantics.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-04-C01 | Import all five entity types, relationships, deleted IDs, criteria, history, device records and queue references twice without loss or duplicate effects. | [test_board.py](../../../dashboard/test_board.py) | Python and/or Node offline fixtures in temporary directories; no provider, broker or hardware calls. |
| DASH-04-C02 | Current create/edit/status/move/delete/detail/drag interactions and refusal messages match authorized target behavior, including in-progress edits across refresh. | [test_frontend_board.sh](../../../dashboard/test_frontend_board.sh), [test_frontend_drawer.sh](../../../dashboard/test_frontend_drawer.sh), [test_frontend_kanban.sh](../../../dashboard/test_frontend_kanban.sh) | Isolated dashboard home and port; Node DOM fixtures, then Playwright browser on supported macOS/Linux/WSL hosts. No live user state. |
| DASH-04-C03 | Missing evidence/dependencies, excessive WIP, unauthorized overrides and stale mutations cannot bypass owner rules. | [test_board.py](../../../dashboard/test_board.py) | Python and/or Node offline fixtures in temporary directories; no provider, broker or hardware calls. |

**Migration and compatibility checks**

- Fence legacy writes before target ownership; reconcile open work and stable IDs.
- Preserve task/run/hub/shared-board identities separately.
- Retain lower-level legacy routes until dependent CLI paths migrate.

**Known limits and review gaps**

- Current store is local SQLite; migration is planned, not implemented.
- Schema import alone would not prove gate, override, drag/drop or edit-state parity.

**Files**

- [dashboard/ccboard.py](../../../dashboard/ccboard.py)
- [dashboard/ccstore.py](../../../dashboard/ccstore.py)
- [dashboard/kanban.js](../../../dashboard/kanban.js)
- [dashboard/kanban.css](../../../dashboard/kanban.css)
- [dashboard/test_board.py](../../../dashboard/test_board.py)
- [dashboard/test_frontend_board.sh](../../../dashboard/test_frontend_board.sh)
- [dashboard/test_frontend_drawer.sh](../../../dashboard/test_frontend_drawer.sh)
- [dashboard/test_frontend_kanban.sh](../../../dashboard/test_frontend_kanban.sh)

<a id="dash-05"></a>
### DASH-05 — Agent definition registry and editor

**Owner:** P03. **Approach:** extract. **Baseline groups:** BASE-02, BASE-17.

**Current behavior**

- Lists repository/user Agentmux and compatible Claude definitions with parse problems, duplicate detection, scopes and unsupported fields.
- Inline editing and deletion use checksums, validated paths, atomic file replacement and audit attribution; stale changes are rejected.
- CLI and dashboard consume matching definition behavior.

**Reuse:** Reuse parser, checksums, diagnostics and edit fixtures; wrap definition management as a scoped plugin service and migrate only the UI composition.

**Added functionality or operating benefit**

- Versioned definition provenance and explicit host capability compatibility.
- User/project identity for edits with preserved conflict behavior.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-05-C01 | Read and import every supported scope; duplicate, invalid, unknown-key and collision cases remain explicit. | [test_agentdefs.py](../../../dashboard/test_agentdefs.py), [test_boardagents.py](../../../dashboard/test_boardagents.py) | Python and/or Node offline fixtures in temporary directories; no provider, broker or hardware calls. |
| DASH-05-C02 | Concurrent editing has one winner; canceled/invalid/stale edits preserve original files, permissions and audit identity; CLI and UI remain consistent. | [test_agentcli.py](../../../dashboard/test_agentcli.py), [test_frontend_agents.sh](../../../dashboard/test_frontend_agents.sh), [test_boardagents.py](../../../dashboard/test_boardagents.py) | Isolated dashboard home and port; Node DOM fixtures, then Playwright browser on supported macOS/Linux/WSL hosts. No live user state. |

**Migration and compatibility checks**

- Preserve source path, checksum, scope precedence, model/auth/posture/tools/capabilities/role/limits.
- Do not reinterpret advisory host fields as enforced permissions.

**Known limits and review gaps**

- Current dashboard actor is a fixed local label; host formats do not have identical authority.

**Files**

- [dashboard/boardagents.py](../../../dashboard/boardagents.py)
- [dashboard/agents.js](../../../dashboard/agents.js)
- [dashboard/agents.css](../../../dashboard/agents.css)
- [dashboard/test_boardagents.py](../../../dashboard/test_boardagents.py)
- [dashboard/test_agentdefs.py](../../../dashboard/test_agentdefs.py)
- [dashboard/test_agentcli.py](../../../dashboard/test_agentcli.py)
- [dashboard/test_frontend_agents.sh](../../../dashboard/test_frontend_agents.sh)

<a id="dash-06"></a>
### DASH-06 — Team roster proposal, approval and hiring

**Owner:** P05. **Approach:** extract. **Baseline groups:** BASE-03, BASE-06, BASE-17.

**Current behavior**

- Builds candidate rosters with capability gaps, stages member decisions and commits approved proposals; displays live/retired membership and configuration.
- Recruit, approve, retire and hire operations use board history, approval state, bounded hire slots and definition lookup; live members cannot be casually retired.
- CLI requests preserve refusal details and do not silently retry hires.

**Reuse:** Reuse roster approval, capacity checks, transition rules and staged UI decisions in orchestration plugins. Wrap execution requests in the new worker contract instead of duplicating the roster engine.

**Added functionality or operating benefit**

- Explicit user/project grants, operation IDs and recoverable launch outcomes.
- Better lead selection and capabilities without unrestricted-posture assumptions.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-06-C01 | Proposal/recruit/approve/reject/retire remain atomic and idempotent; existing hired members and unsaved decisions survive refresh. | [test_boardteams.py](../../../dashboard/test_boardteams.py), [test_frontend_teams.sh](../../../dashboard/test_frontend_teams.sh) | Isolated dashboard home and port; Node DOM fixtures, then Playwright browser on supported macOS/Linux/WSL hosts. No live user state. |
| DASH-06-C02 | Hire requires approved current membership, capacity and supported execution posture; a lost reply cannot launch a second worker. | [test_boardteams.py](../../../dashboard/test_boardteams.py), [test_teamcli.py](../../../dashboard/test_teamcli.py), [test_sandbox_coordination.py](../../../dashboard/test_sandbox_coordination.py) | Python and/or Node offline fixtures in temporary directories; no provider, broker or hardware calls. |

**Migration and compatibility checks**

- Migrate roster IDs, approval actor/version, live-worker binding and retired history.
- Keep hire/retire actions in the scope decision and preserve an equivalent supported path.

**Known limits and review gaps**

- Known lead-selection and unrestricted-posture constraints need correction; importing the UI does not solve them.

**Files**

- [dashboard/boardteams.py](../../../dashboard/boardteams.py)
- [dashboard/teams.js](../../../dashboard/teams.js)
- [dashboard/teams.css](../../../dashboard/teams.css)
- [dashboard/test_boardteams.py](../../../dashboard/test_boardteams.py)
- [dashboard/test_teamcli.py](../../../dashboard/test_teamcli.py)
- [dashboard/test_frontend_teams.sh](../../../dashboard/test_frontend_teams.sh)

<a id="dash-07"></a>
### DASH-07 — Run progress, review, diffs and completion gate

**Owner:** P05. **Approach:** extract. **Baseline groups:** BASE-07, BASE-15, BASE-17.

**Current behavior**

- Lists runs and job attempts with blocking explanations, responsible worker/reviewer, escalation, stale liveness and bounded diffs.
- Supports approve/request changes with notes; binds approvals to evidence digests and shows approval drift as stale.
- Collapsed run summaries poll separately from opened job/diff details; drafts and expanded-card preferences survive refresh.

**Reuse:** Reuse run folding, blocking explanations, review states and scoped diff behavior; move authoritative acceptance to the run owner and progressively refit the view.

**Added functionality or operating benefit**

- Durable attempt/review evidence and multi-user authorization.
- Explicit submitted, accepted, cancellation-confirmed and unknown states.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-07-C01 | Old and migrated fixtures give the same blocking worker/reviewer, escalation, retry ceiling and missing-agent state. | [test_runsview.py](../../../dashboard/test_runsview.py), [test_runcards.py](../../../dashboard/test_runcards.py) | Python and/or Node offline fixtures in temporary directories; no provider, broker or hardware calls. |
| DASH-07-C02 | Approve/request changes, notes, bounded submitted-file diffs and stale approval invalidation work after reconnect; viewing cannot complete a run. | [test_runsview.py](../../../dashboard/test_runsview.py) | Isolated dashboard home and port; Node DOM fixtures, then Playwright browser on supported macOS/Linux/WSL hosts. No live user state. |

**Migration and compatibility checks**

- Preserve run/job/attempt IDs, sidecar links, base commits, submitted paths, review actors and digest binding.
- A completed run must not implicitly close a board card or authorize merge.

**Known limits and review gaps**

- Historical run gaps include incomplete submission binding; no current browser test result is claimed.

**Files**

- [dashboard/runs.js](../../../dashboard/runs.js)
- [dashboard/runsview.py](../../../dashboard/runsview.py)
- [dashboard/test_runsview.py](../../../dashboard/test_runsview.py)

<a id="dash-08"></a>
### DASH-08 — Hub observation panel

**Owner:** P07. **Approach:** wrap. **Baseline groups:** BASE-11, BASE-17.

**Current behavior**

- Shows agents, work states/claimers, work detail, status counts and an incremental bell/delivery event feed.
- Uses bounded read-only Unix-socket verbs; neither browser nor adapter opens hub.db. Missing/stale sockets become explicit unavailable responses.

**Reuse:** Retain the panel's read-only behavior and event/detail semantics; adapt its backend contract to authorized NATS and then AG-UI incrementally.

**Added functionality or operating benefit**

- Multiple authorized hubs and project-scoped subscriptions.
- Snapshots/cursors for reconnect and visible missing history.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-08-C01 | Agents/work filters/detail/counts/events match the existing socket fixtures through the new transport. | [test_hub_panel.py](../../../dashboard/test_hub_panel.py) | Python and/or Node offline fixtures in temporary directories; no provider, broker or hardware calls. |
| DASH-08-C02 | Hub unavailable, timeout, malformed or missing history yields explicit state; no observation can claim/post/cancel work. | [test_hub_panel.py](../../../dashboard/test_hub_panel.py) | Isolated dashboard home and port; Node DOM fixtures, then Playwright browser on supported macOS/Linux/WSL hosts. No live user state. |

**Migration and compatibility checks**

- Preserve work identities, event sequence cursors and source hub.
- Keep unavailable distinct from an empty healthy hub.

**Known limits and review gaps**

- Current adapter assumes local Unix sockets and a local operator; remote access requires new authorization.

**Files**

- [dashboard/hub.js](../../../dashboard/hub.js)
- [dashboard/hub_panel.py](../../../dashboard/hub_panel.py)
- [dashboard/test_hub_panel.py](../../../dashboard/test_hub_panel.py)

<a id="dash-09"></a>
### DASH-09 — Federation panel and operator actions

**Owner:** P10. **Approach:** wrap. **Baseline groups:** BASE-13, BASE-14, BASE-17.

**Current behavior**

- Shows peers/trust, quarantined items, shared-board/findings/code contribution cards, audit and kill-switch status.
- Allowlisted actions approve/deny quarantine, kill/revoke/resume federation and move shared cards; arguments are validated and sent through the local hub.

**Reuse:** Reuse current panel grouping, allowlist and error behavior; route actions to explicitly authorized federation owners and reuse the view within registered UI contributions.

**Added functionality or operating benefit**

- Cross-organization scope, bilateral grants and reservation-aware operation results.
- Origin/executor separation and visible unknown acknowledgment state.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-09-C01 | Read panels and all five action verbs preserve allowed input and refusal behavior under authenticated actors. | [test_fed_panel.py](../../../dashboard/test_fed_panel.py) | Python and/or Node offline fixtures in temporary directories; no provider, broker or hardware calls. |
| DASH-09-C02 | Ten-view navigation includes Federation; unavailable federation and optional plugin errors do not break core views; revoked users cannot act via direct HTTP. | [test_fed_panel.py](../../../dashboard/test_fed_panel.py), [test_e2e.mjs](../../../dashboard/test_e2e.mjs) | Isolated dashboard home and port; Node DOM fixtures, then Playwright browser on supported macOS/Linux/WSL hosts. No live user state. |

**Migration and compatibility checks**

- Preserve quarantine IDs, shared-card IDs/statuses, audit records, kill/revoke meaning and source ownership.
- Changing dashboard command scope must explicitly account for all current operator actions.

**Known limits and review gaps**

- Existing local hub treats the dashboard as operator; this is not a multi-user trust model.
- test_e2e.mjs still asserts nine navigation views and omits Federation; source inspection finds a stale test contract, not a recorded test failure.

**Files**

- [dashboard/fed.js](../../../dashboard/fed.js)
- [dashboard/fed_panel.py](../../../dashboard/fed_panel.py)
- [dashboard/test_fed_panel.py](../../../dashboard/test_fed_panel.py)

<a id="dash-10"></a>
### DASH-10 — Provider authentication settings and diagnostics

**Owner:** P06. **Approach:** wrap. **Baseline groups:** BASE-19, BASE-20, BASE-17.

**Current behavior**

- Manifest separates provider-shared configuration from per-method settings and lists eight Codex/Claude/Grok authentication methods.
- Settings shows configured/missing state, setup commands, active-method selection and nonsecret model/endpoint changes; credentials remain outside browser entry.
- Auth-tree and key-exposure diagnostics report safe status; model-switch verification checks launch configuration against actual CLI output.

**Reuse:** Retain manifest semantics, terminal setup and secret-redaction rules; wrap configuration in scoped provider/client services and reuse the Settings interactions.

**Added functionality or operating benefit**

- Versioned provider capability declarations and project/user selection.
- Safe diagnostics with explicit unsupported methods and unavailable prerequisites.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-10-C01 | Each method retains shared-versus-method settings, validation and missing-credential behavior without showing secrets. | [test_auth.py](../../../dashboard/test_auth.py) | Python and/or Node offline fixtures in temporary directories; no provider, broker or hardware calls. |
| DASH-10-C02 | An approved actual-client test shows that selecting a model/method affects a newly launched worker; a stored preference alone cannot pass. | [verify_model_switch.sh](../../../dashboard/verify_model_switch.sh) | Supported host and installed provider CLI; separate approval and account/billing scope for live provider use. |

**Migration and compatibility checks**

- Migrate credential references separately from values; preserve active selections, file modes and config versions.
- Keep diagnostics off shared raw logs and mark unavailable configurations honestly.

**Known limits and review gaps**

- README/gateway setup references exceed the shipped manifest in places; maintain repair/retire decisions.
- The exposure script reads local credential locations; inventory only here, not executed.

**Files**

- [dashboard/auth.json](../../../dashboard/auth.json)
- [dashboard/show_auth.py](../../../dashboard/show_auth.py)
- [dashboard/test_auth.py](../../../dashboard/test_auth.py)
- [dashboard/verify_model_switch.sh](../../../dashboard/verify_model_switch.sh)
- [dashboard/check_key_exposure.sh](../../../dashboard/check_key_exposure.sh)

<a id="dash-11"></a>
### DASH-11 — GitHub observations, login and constrained writes

**Owner:** P06. **Approach:** wrap. **Baseline groups:** BASE-21, BASE-17.

**Current behavior**

- Shows configured repositories, branch/dirty/ahead-behind state, PR/check and workflow observations through local Git and gh.
- Supports device-flow login status/cancel/logout and constrained repository/issue creation; gh owns credentials.
- Validates fixed arguments and records actor/confirmation; Windows gh discovery and native precedence have dedicated fixtures.

**Reuse:** Reuse Git/gh parsing, constrained operations and UI controls behind workspace/provider contracts; preserve login and creation workflows unless explicitly changed.

**Added functionality or operating benefit**

- Scoped external actions and durable operation/outcome records.
- Clear freshness provenance and project-specific repository visibility.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-11-C01 | Configured repositories, partial failures, detached heads and missing auth preserve accurate display and redacted errors. | [test_github_panel.py](../../../dashboard/test_github_panel.py) | Python and/or Node offline fixtures in temporary directories; no provider, broker or hardware calls. |
| DASH-11-C02 | Login/cancel/logout and repository/issue creation retain target, confirmation and fixed-argv validation; lost replies require reconciliation before retry. | [test_github_panel.py](../../../dashboard/test_github_panel.py) | Offline subprocess fixtures, then separately approved actual GitHub account/host qualification. |

**Migration and compatibility checks**

- Preserve configured paths, Git remote identity, gh credential ownership and API-limit state.
- Local tracking refs remain labeled as potentially stale; do not silently fetch or merge.

**Known limits and review gaps**

- Current display is not proof of fresh remote state; writes are local-operator actions, not tenant-scoped.

**Files**

- [dashboard/github.js](../../../dashboard/github.js)
- [dashboard/github_panel.py](../../../dashboard/github_panel.py)
- [dashboard/github_auth.py](../../../dashboard/github_auth.py)
- [dashboard/test_github_panel.py](../../../dashboard/test_github_panel.py)

<a id="dash-12"></a>
### DASH-12 — Resource manifest and fixed diagnostic probes

**Owner:** P06. **Approach:** extend. **Baseline groups:** BASE-23, BASE-36.

**Current behavior**

- Settings resources load a committed manifest of named dependencies, status probes and operator setup hints; server resolves fixed check definitions.
- Requests cannot provide arbitrary probe argv. Missing tool/auth state is exposed separately from configured selections.

**Reuse:** Keep manifest-driven fixed probes and setup hints; expand them into versioned plugin health contributions with scoped execution.

**Added functionality or operating benefit**

- Plugin-specific prerequisites and supported-version diagnostics.
- Portable macOS/Linux/WSL setup guidance without machine-specific paths.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-12-C01 | Every declared check resolves to a reviewed command, produces bounded nonsecret status and reports missing tools without arbitrary request-supplied execution. | [smoke.sh](../../../dashboard/smoke.sh), [test_no_inherited_stdin.py](../../../dashboard/test_no_inherited_stdin.py) | Python and/or Node offline fixtures in temporary directories; no provider, broker or hardware calls. |
| DASH-12-C02 | The Settings view preserves resources, refresh and setup guidance when optional plugins are absent. | [test_e2e.mjs](../../../dashboard/test_e2e.mjs) | Isolated dashboard home and port; Node DOM fixtures, then Playwright browser on supported macOS/Linux/WSL hosts. No live user state. |

**Migration and compatibility checks**

- Inventory current manifest IDs and their command/environment dependencies.
- Preserve configured/unavailable/unknown distinctions and bounded cache/refresh behavior.

**Known limits and review gaps**

- Manifest and UI checks are not evidence that each external dependency works on all platforms.

**Files**

- [dashboard/resources.json](../../../dashboard/resources.json)

<a id="dash-13"></a>
### DASH-13 — Atlassian ticket view and action regression contract

**Owner:** P06. **Approach:** retain-evidence. **Baseline groups:** BASE-22, BASE-17.

**Current behavior**

- Current server/app routes show Jira tickets and transitions, post comments and change ticket state; setup/configuration remains operator-owned.
- The assigned test file covers the dashboard integration contract; shared route/rendering code is assigned to DASH-01 and DASH-02, while taskmgmt implementation is in the runtime audit.

**Reuse:** Carry ticket display/action fixtures into the extracted Atlassian plugin and keep existing UI actions explicit in the migration matrix.

**Added functionality or operating benefit**

- Scoped account/project/issue grants and uncertain-write reconciliation.
- Freshness and partial-service failure shown without losing local work.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-13-C01 | Ticket read/filter/transition/comment routes preserve current validation, errors and browser behavior through the new owner. | [test_tickets.py](../../../dashboard/test_tickets.py) | Offline Jira/Confluence fixtures and isolated dashboard; separate real-service qualification. |
| DASH-13-C02 | Retries following a lost comment/transition response cannot silently duplicate or apply an unintended transition. | [test_tickets.py](../../../dashboard/test_tickets.py) | Python and/or Node offline fixtures in temporary directories; no provider, broker or hardware calls. |

**Migration and compatibility checks**

- Preserve issue keys, local task links, setup hints and external account references.
- Do not treat local rollback or worker cleanup as reversing external transitions.

**Known limits and review gaps**

- This component has test ownership, not exclusive implementation ownership; shared app/server code is mapped elsewhere.
- Existing tests need additional operation-identity cases in the target.

**Files**

- [dashboard/test_tickets.py](../../../dashboard/test_tickets.py)

<a id="dash-14"></a>
### DASH-14 — IIOT view and Modbus TCP tag table

**Owner:** P11. **Approach:** extract. **Baseline groups:** BASE-24, BASE-27, BASE-17.

**Current behavior**

- IIOT contains Modbus, PROFINET DCP, MQTT, Ethernet scanner and CODESYS cards with explicit setup/privilege hints; their UI contributions must remain independently usable.
- Modbus TCP implements reads 1–4 and writes 5/6/15/16 with confirmation, actor, durable intent and target binding.
- A persisted table supports up to 64 tags on one configured endpoint, zero-based addresses, scaling, numeric types and high/low word order; a background poller reports stale values and connection errors.
- The shared IIOT script also edits expected PROFINET stations and imports observed snapshots; the protocol comparison module is mapped in DASH-20.

**Reuse:** Extract protocol/poller code as the Modbus child plugin and reuse validation, tag-table shape and UI workflows. Migrate the existing IIOT shell to registered domain slots rather than replacing its functions.

**Added functionality or operating benefit**

- Scoped tool identities, NATS observations and per-target permission checks.
- Stable evidence/artifact references and project-specific saved configurations.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-14-C01 | TCP reads, writes, scaling, types, word order, malformed frames, persistence and stale values match current fixtures. | [test_modbus_poll.py](../../../dashboard/test_modbus_poll.py) | Python offline fixtures in temporary directories; no hardware, network service or provider calls. |
| DASH-14-C02 | Wrong/currently changed targets, missing confirmation, failed intent journaling and transport loss prevent unsafe writes or produce unknown outcomes without automatic retry. | [test_modbus_poll.py](../../../dashboard/test_modbus_poll.py) | Offline wire/intent fixtures first; separately approved target device, interface, privileges and installed vendor tools for live qualification. |
| DASH-14-C03 | All five IIOT cards and existing configuration/import actions remain visible; absent optional plugins give useful status and never start scans on mere page load. | [test_field_panels.py](../../../dashboard/test_field_panels.py), [test_e2e.mjs](../../../dashboard/test_e2e.mjs) | Isolated dashboard plus Node DOM fixtures and Playwright browser on supported hosts. |

**Migration and compatibility checks**

- Migrate saved tag endpoint/table, actor/intents and journal references with units and zero-based addresses intact.
- Preserve one-endpoint and tag limits until a separately accepted capacity enhancement.
- Map Modbus write UI and endpoint separately from read subscription permission.

**Known limits and review gaps**

- Sequential reads are not atomic process snapshots.
- Source and mock fixtures are not physical-device qualification; some field UI remains in the shared app.

**Files**

- [dashboard/iiot.js](../../../dashboard/iiot.js)
- [dashboard/modbus_poll.py](../../../dashboard/modbus_poll.py)
- [dashboard/test_modbus_poll.py](../../../dashboard/test_modbus_poll.py)
- [dashboard/test_field_panels.py](../../../dashboard/test_field_panels.py)

<a id="dash-15"></a>
### DASH-15 — Modbus serial RTU transport

**Owner:** P11. **Approach:** wrap. **Baseline groups:** BASE-24.

**Current behavior**

- RTU reuses the tag-table protocol over pyserial, CRC framing, configured baud/parity/stop bits, silent intervals and request deadlines.
- Canonical-port locking serializes local clients; actor/confirm/journal/target controls precede writes.

**Reuse:** Wrap the existing transport inside the Modbus package; retain wire, timing, port-alias and target-binding tests.

**Added functionality or operating benefit**

- Declared serial/USB/WSL capabilities and scoped device access.
- Consistent unknown-outcome and evidence contracts across TCP/RTU.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-15-C01 | CRC, fragmentation, inter-frame timing, stale-input flushing, serial settings and port aliases preserve current behavior. | [test_modbus_rtu.py](../../../dashboard/test_modbus_rtu.py) | Python offline fixtures in temporary directories; no hardware, network service or provider calls. |
| DASH-15-C02 | Failed journal/open, missing confirmation, target change and lost write replies cannot become silent success or automatic retry. | [test_modbus_rtu.py](../../../dashboard/test_modbus_rtu.py) | Offline wire/intent fixtures first; separately approved target device, interface, privileges and installed vendor tools for live qualification. |

**Migration and compatibility checks**

- Preserve serial settings, target identity, table configuration and timing units.
- Explicitly qualify USB forwarding and serial adapter support per host.

**Known limits and review gaps**

- Needs pyserial and suitable RS-485 hardware; local locking does not stop another physical bus master.

**Files**

- [dashboard/modbus_rtu.py](../../../dashboard/modbus_rtu.py)
- [dashboard/test_modbus_rtu.py](../../../dashboard/test_modbus_rtu.py)

<a id="dash-16"></a>
### DASH-16 — Bounded legacy MQTT request endpoints

**Owner:** P11. **Approach:** wrap. **Baseline groups:** BASE-25.

**Current behavior**

- Legacy /api/mqtt/publish and /api/mqtt/subscribe use a bounded standard-library MQTT 3.1.1 connection with topic/payload validation and timed collection.
- Current constants allow 4 MiB packet reads, 4096-byte outgoing payloads and bounded subscription messages; historical comments describing a 64 KiB packet cap are stale.
- The stub broker exercises simple CONNECT/PUBLISH/SUBSCRIBE/PING behavior for isolated tests.

**Reuse:** Keep compatibility endpoints and validation while wrapping operations in the MQTT plugin. Share proven transport code with the monitor only after equivalence tests and a documented endpoint decision.

**Added functionality or operating benefit**

- Authenticated target/topic grants and operation identity.
- Clear distinction between publishing a message and confirming a device effect.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-16-C01 | Legacy payload/topic limits, packet framing, bounded subscribe and error responses remain unchanged or explicitly versioned. | [test_mqtt.py](../../../dashboard/test_mqtt.py) | Python offline fixtures in temporary directories; no hardware, network service or provider calls. |
| DASH-16-C02 | A local broker fixture covers publish/subscribe/reconnect without contacting a plant broker; rejected or unknown effects remain visible. | [test_mqtt.py](../../../dashboard/test_mqtt.py) | Isolated loopback stub broker; no external equipment. |

**Migration and compatibility checks**

- Inventory every legacy endpoint consumer before replacement.
- Preserve effective HTTP and protocol limits and mark stale documentation separately.

**Known limits and review gaps**

- The handwritten client is limited and does not provide the monitor's TLS/auth/QoS behavior.
- Broker delivery cannot prove equipment execution.

**Files**

- [dashboard/mqtt.py](../../../dashboard/mqtt.py)
- [dashboard/test_mqtt.py](../../../dashboard/test_mqtt.py)
- [dashboard/stub_broker.py](../../../dashboard/stub_broker.py)

<a id="dash-17"></a>
### DASH-17 — MQTT topic monitor and publication UI

**Owner:** P11. **Approach:** extract. **Baseline groups:** BASE-25, BASE-17.

**Current behavior**

- One persistent Paho MQTT 3.1.1 session maintains a topic tree with last value, age, count, QoS/retain and a bounded arrival log.
- UI supports broker/filter configuration, connect/stop/clear, topic inspection, filters and publication with QoS 0/1/2 and retain.
- Credentials/TLS configuration come from a private operator file keyed by broker; the browser receives status rather than secret values.
- Limits are 2000 topics, 1000 messages, 2048 displayed bytes per value and 16 topic filters; truncation, overflow and disconnected age remain visible.

**Reuse:** Reuse monitor state machine, bounded buffers, secret lookup and topic UI within a MQTT child package. Expose project-scoped NATS observations rather than making every viewer create its own session.

**Added functionality or operating benefit**

- Shared scoped monitoring without duplicate sessions from additional viewers.
- Owner-enforced broker/topic/action grants, clearer effective publication limits.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-17-C01 | Topic tree, inspect, arrival order, retain/QoS, limits, truncation and reconnect/stale labels match existing tests and targeted new monitor fixtures. | [test_mqtt.py](../../../dashboard/test_mqtt.py), [test_field_panels.py](../../../dashboard/test_field_panels.py), [test_e2e.mjs](../../../dashboard/test_e2e.mjs) | Isolated dashboard plus Node DOM fixtures and Playwright browser on supported hosts. |
| DASH-17-C02 | Stop/clear/publish retain intended distinctions; browser inputs never inject credential values, and publication authorization is bound to current broker/topic. | [test_mqtt.py](../../../dashboard/test_mqtt.py), [test_field_panels.py](../../../dashboard/test_field_panels.py) | Offline Paho fixtures and isolated TLS/QoS broker; later declared broker-version qualification. |

**Migration and compatibility checks**

- Preserve broker/session configuration, user preferences and credential references without copying secrets into shared records.
- Retain one-session bounds unless a separately reviewed multi-session capability is enabled.
- Reconcile HTTP body limits with monitor publication limits explicitly.

**Known limits and review gaps**

- Library capability is broader than configured protocol; current monitor explicitly selects MQTTv311.
- UI confirmation alone is not an actor/target-bound authorization system.

**Files**

- [dashboard/mqtt.js](../../../dashboard/mqtt.js)
- [dashboard/mqtt_monitor.py](../../../dashboard/mqtt_monitor.py)

<a id="dash-18"></a>
### DASH-18 — Private IPv4 scan and network observation UI

**Owner:** P11. **Approach:** wrap. **Baseline groups:** BASE-26, BASE-17.

**Current behavior**

- Scans an explicitly entered private IPv4 range using bounded TCP connects and selected industrial ports; exposes start/stop, progress, results and CSV export.
- Enriches observations with local neighbor/MAC/OUI data, using Linux/macOS tables and a Windows ARP fallback under WSL.
- Caps include 1024 hosts, 16 ports, 64 workers and 300 seconds; UI preferences retain range/port choices.

**Reuse:** Reuse scanner validation, cancellation, bounds, OS-specific neighbor parsing and result display. Wrap it in a network-tool package with explicit scope and observation provenance.

**Added functionality or operating benefit**

- Project-bound scan grants and durable evidence references.
- Clear source/time/uncertainty for inferred service labels and neighbor data.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-18-C01 | Invalid ranges/ports and oversized requests are rejected; cancellation, progress, CSV and platform neighbor parsing remain consistent. | [test_field_panels.py](../../../dashboard/test_field_panels.py) | Python offline fixtures in temporary directories; no hardware, network service or provider calls. |
| DASH-18-C02 | Viewing results or reconnecting a dashboard cannot begin another scan; unavailable neighbor data does not invent identity. | [test_field_panels.py](../../../dashboard/test_field_panels.py), [test_e2e.mjs](../../../dashboard/test_e2e.mjs) | Isolated dashboard plus Node DOM fixtures and Playwright browser on supported hosts. |

**Migration and compatibility checks**

- Preserve configured ports, saved preferences, labels, address bounds, cancellation and audit events.
- Keep raw neighbor/vendor observations distinct from discovered verified device identity.

**Known limits and review gaps**

- A listening port is a hint, not equipment type proof.
- WSL network topology can prevent useful layer-2 identity; actual interface qualification is separate.

**Files**

- [dashboard/netscan.js](../../../dashboard/netscan.js)
- [dashboard/netscan.py](../../../dashboard/netscan.py)

<a id="dash-19"></a>
### DASH-19 — PROFINET expected stations and imported comparison

**Owner:** P11. **Approach:** wrap. **Baseline groups:** BASE-27, BASE-17.

**Current behavior**

- Validates and persists expected station names, addresses and device data, then compares them against an imported observed snapshot.
- Reports missing/unexpected/mismatched/duplicate observations and supports JSON-lines input from the privileged DCP helper; this module sends no raw DCP frames.

**Reuse:** Reuse the schema/parser/reconciliation engine and shared IIOT controls as the read/import part of the PROFINET package.

**Added functionality or operating benefit**

- Immutable source/time/version references for observations.
- Scoped expected-state edits and comparison views across teams.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-19-C01 | Expected/observed fixtures retain station-name/IP validation and all missing/extra/conflict results after migration. | [test_field_panels.py](../../../dashboard/test_field_panels.py), [test_pn_dcp.py](../../../dashboard/test_pn_dcp.py) | Python offline fixtures in temporary directories; no hardware, network service or provider calls. |
| DASH-19-C02 | Importing malformed, stale or partial evidence is explicit and cannot start device traffic. | [test_field_panels.py](../../../dashboard/test_field_panels.py), [test_pn_dcp.py](../../../dashboard/test_pn_dcp.py) | Isolated dashboard plus Node DOM fixtures and Playwright browser on supported hosts. |

**Migration and compatibility checks**

- Preserve expected schema, last imported snapshot, record identity and comparison meaning.
- Map schema-save and snapshot-import actions as actual writes to project state.

**Known limits and review gaps**

- Observed snapshots may be stale; a match is not a live assurance or control authorization.

**Files**

- [dashboard/profinet.py](../../../dashboard/profinet.py)

<a id="dash-20"></a>
### DASH-20 — Privileged PROFINET DCP tool

**Owner:** P11. **Approach:** wrap. **Baseline groups:** BASE-28.

**Current behavior**

- Linux raw-socket helper emits JSON lines for Identify; permanent Set operates on one explicit unicast MAC and one name or complete IP setting.
- Set reads current values, requires exact MAC confirmation via terminal, durably records intent before sending and records denied/unknown outcomes without blind retry.
- Validates interface, source/response framing, privilege, target and supported blocks.

**Reuse:** Keep the wire/parser and intent code; expose a separately privileged tool capability with target-bound approval rather than elevating the dashboard.

**Added functionality or operating benefit**

- Remote tool-host declarations for physical interface access.
- Owner-side permission enforcement independent of optional client hooks.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-20-C01 | Identify/Get/Set frame vectors, VLAN parsing, malformed data, target validation and expected-state rechecks retain current behavior. | [test_pn_dcp.py](../../../dashboard/test_pn_dcp.py) | Python offline fixtures in temporary directories; no hardware, network service or provider calls. |
| DASH-20-C02 | Missing privilege, wrong MAC, changed current value, failed fsync, bad acknowledgment and interruption refuse or record unknown state without retry. | [test_pn_dcp.py](../../../dashboard/test_pn_dcp.py) | Offline wire/intent fixtures first; separately approved target device, interface, privileges and installed vendor tools for live qualification. |

**Migration and compatibility checks**

- Preserve exact command options, JSON-line output, journal contents and one-target limits.
- Keep read discovery and permanent writes as separately granted operations.

**Known limits and review gaps**

- Needs Linux AF_PACKET and an actual interface on the target segment; WSL NAT does not provide that automatically.

**Files**

- [taskmgmt/pn_dcp.py](../../../taskmgmt/pn_dcp.py)
- [dashboard/test_pn_dcp.py](../../../dashboard/test_pn_dcp.py)

<a id="dash-21"></a>
### DASH-21 — Passive BOOTP/DHCP observation tool

**Owner:** P11. **Approach:** wrap. **Baseline groups:** BASE-29.

**Current behavior**

- Listens on privileged UDP ports 67/68 for BOOTP/DHCP requests, parses options and prints observations within a time bound.
- The dashboard describes its explicit privileged invocation; it never answers requests or assigns addresses.

**Reuse:** Retain the passive listener and parser in a separately scoped diagnostics plugin; make observations available through evidence references.

**Added functionality or operating benefit**

- Explicit interface/privilege diagnostics and structured observation provenance.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-21-C01 | Offline packets cover valid/truncated BOOTP/DHCP options, malformed lengths, interface selection and timeout behavior. | New fixture/review needed; no existing test claimed | Python offline fixtures in temporary directories; no hardware, network service or provider calls. |
| DASH-21-C02 | A controlled capture proves the plugin only listens and never emits offers, leases or replies. | New fixture/review needed; no existing test claimed | Approved isolated network namespace/capture fixture, then declared host qualification. |

**Migration and compatibility checks**

- Preserve CLI options, JSON/text outputs and passive-only behavior.
- Do not convert this existing observation capability into an address-assignment service.

**Known limits and review gaps**

- No dedicated tracked BOOTP test file was identified in this assigned tree; new parser/passivity fixtures are required.
- UDP binding privilege and interface access vary by host.

**Files**

- [taskmgmt/bootp_probe.py](../../../taskmgmt/bootp_probe.py)

<a id="dash-22"></a>
### DASH-22 — EtherNet/IP explicit messaging library

**Owner:** P11. **Approach:** wrap. **Baseline groups:** BASE-30.

**Current behavior**

- Standard-library synchronous EtherNet/IP explicit TCP session handles identity/CIP requests and basic symbolic atomic Logix reads/writes.
- Writes require confirmation, named actor and durable audit intent before transmission; failed/unknown results are recorded.
- No cyclic I/O, connected messaging, UDP or chassis/backplane routing is implemented.

**Reuse:** Retain framing, session, paths, validation and tests as the common EtherNet/IP transport used by vendor plugins.

**Added functionality or operating benefit**

- Scoped tool invocation and shared operation/evidence contracts.
- Versioned device-family support declarations.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-22-C01 | Identity/session, atomic data types, paths, framing, malformed/oversized replies and close behavior match current vectors. | [test_enip.py](../../../dashboard/test_enip.py) | Python offline fixtures in temporary directories; no hardware, network service or provider calls. |
| DASH-22-C02 | Unauthorized or unjournaled writes never reach transport; timeout remains unknown with no unsafe retry. | [test_enip.py](../../../dashboard/test_enip.py) | Offline wire/intent fixtures first; separately approved target device, interface, privileges and installed vendor tools for live qualification. |

**Migration and compatibility checks**

- Preserve protocol and numeric type semantics, actor/target audit records and public Python entry points.
- This library has no current dashboard route; adding a panel is an enhancement, not claimed parity.

**Known limits and review gaps**

- Source and fake sockets do not establish controller-family compatibility.

**Files**

- [dashboard/enip.py](../../../dashboard/enip.py)
- [dashboard/test_enip.py](../../../dashboard/test_enip.py)

<a id="dash-23"></a>
### DASH-23 — Rockwell Logix fragmented tag access

**Owner:** P11. **Approach:** wrap. **Baseline groups:** BASE-30.

**Current behavior**

- Extends EtherNet/IP data access with symbolic and version-gated instance paths, fragmented reads/writes, structures with explicit size and read-modify-write masks.
- Tracks partial/rejected/unknown outcomes, exact byte offsets/type constraints and durable target-bound write intent.

**Reuse:** Reuse protocol logic and manual-vector fixtures in a Rockwell child package; wrap language-neutral tools around the existing implementation.

**Added functionality or operating benefit**

- Declared controller/version capabilities and scoped tag access.
- Consistent evidence for partially completed writes.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-23-C01 | Existing atomic/fragmented/structure/mask vectors, offset behavior and version constraints remain equivalent. | [test_logix.py](../../../dashboard/test_logix.py) | Python offline fixtures in temporary directories; no hardware, network service or provider calls. |
| DASH-23-C02 | Journal failure, missing actor/confirmation, partial transfers and lost replies never become automatic replay or full success. | [test_logix.py](../../../dashboard/test_logix.py) | Offline wire/intent fixtures first; separately approved target device, interface, privileges and installed vendor tools for live qualification. |

**Migration and compatibility checks**

- Preserve type descriptors, BOOL bit positions, structure-size requirements and path-version rules.
- Retain library use separately from any future UI/API contribution.

**Known limits and review gaps**

- This is not the licensed Windows Logix Designer SDK and does not provide full UDT discovery or chassis routing.

**Files**

- [dashboard/logix.py](../../../dashboard/logix.py)
- [dashboard/test_logix.py](../../../dashboard/test_logix.py)

<a id="dash-24"></a>
### DASH-24 — ADS state, symbol and memory access

**Owner:** P11. **Approach:** wrap. **Baseline groups:** BASE-31.

**Current behavior**

- AMS/TCP client reads device/state/index/symbol data through preconfigured source/target NetIds and existing return routes.
- Confirmed writes, read-write and write-control operations require actor/intent journaling; symbol handles are acquired/released per call.
- The diagnostic CLI exposes reads; explicit Python methods expose confirmed control.

**Reuse:** Reuse parser, route guidance, handle lifecycle, journal and tests in an ADS child package with owner-enforced target/action grants.

**Added functionality or operating benefit**

- Explicit route/host support diagnostics and scoped value/control tools.
- Evidence identifying source/target and uncertain cleanup.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-24-C01 | Read/write/read-write/control and symbol lifetime fixtures retain framing/size checks, route errors and cleanup behavior. | [test_ads.py](../../../dashboard/test_ads.py) | Python offline fixtures in temporary directories; no hardware, network service or provider calls. |
| DASH-24-C02 | Confirmation/journal failure prevents network writes; transport loss and failed handle release remain explicit. | [test_ads.py](../../../dashboard/test_ads.py) | Offline wire/intent fixtures first; separately approved target device, interface, privileges and installed vendor tools for live qualification. |

**Migration and compatibility checks**

- Preserve NetIds, port, index groups/offsets, types, journal and unknown-outcome semantics.
- Do not silently install AMS routes or add CLI write commands.

**Known limits and review gaps**

- The client never configures routes; remote cleanup cannot be guaranteed after disconnection.

**Files**

- [dashboard/ads.py](../../../dashboard/ads.py)
- [dashboard/test_ads.py](../../../dashboard/test_ads.py)

<a id="dash-25"></a>
### DASH-25 — TwinCAT EtherCAT diagnostics and confirmed state requests

**Owner:** P11. **Approach:** wrap. **Baseline groups:** BASE-32.

**Current behavior**

- Reads a configured TwinCAT EtherCAT master's state, configured slaves, available link/port counters and diagnostic values through ADS.
- Unknown mappings remain unavailable; snapshots are sequential and topology changes are detected.
- Also contains request_state for a known configured slave: validates desired state/address, uses ADS actor/confirmation and durable intent, and records write outcomes.

**Reuse:** Retain both read diagnostics and the existing explicit state-request capability in the TwinCAT child package. Preserve scope separation; do not lose the write method because the baseline title says diagnostics.

**Added functionality or operating benefit**

- Owner-controlled grants for state changes and source-timed observations.
- Clear versioned availability for diagnostic fields.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-25-C01 | Full/empty/changed topology, short/excess responses and unavailable slave data preserve exact known/unknown behavior. | [test_ecat_diag.py](../../../dashboard/test_ecat_diag.py) | Python offline fixtures in temporary directories; no hardware, network service or provider calls. |
| DASH-25-C02 | INIT/PREOP/BOOT/SAFEOP/OP requests require the configured slave, actor, confirmation and successful journal before transmission; unknown results never retry automatically. | [test_ecat_diag.py](../../../dashboard/test_ecat_diag.py) | Offline wire/intent fixtures first; separately approved target device, interface, privileges and installed vendor tools for live qualification. |

**Migration and compatibility checks**

- Preserve device NetId distinction, configured slave addresses and state enumeration.
- Inventory both Python and CLI entry points before packaging.

**Known limits and review gaps**

- Requires an existing reachable TwinCAT master; this does not implement EtherCAT real-time control or an EtherCAT master.

**Files**

- [dashboard/ecat_diag.py](../../../dashboard/ecat_diag.py)
- [dashboard/test_ecat_diag.py](../../../dashboard/test_ecat_diag.py)

<a id="dash-26"></a>
### DASH-26 — CODESYS target management and runtime actions

**Owner:** P11. **Approach:** wrap. **Baseline groups:** BASE-33, BASE-17.

**Current behavior**

- Shows operator-configured Linux SL x86-64 targets, measured runtime/platform/version/gateway state and actionable unavailable status.
- Supports prepare/confirm for start/stop/reset, boot-app, install and update through SSH/external MCP, with expiring single-use tokens and repeated target binding checks.
- Backups and committed operation audit precede applicable writes; concurrent actions are locked and there is no background SSH polling or automatic write retry.

**Reuse:** Reuse inventory validation, preparation tokens, target rechecks, backup and transport routines behind a CODESYS child contract; preserve existing controls as a registered domain view.

**Added functionality or operating benefit**

- Portable tool discovery and declared MCP/runtime/version support.
- Scoped remote tool execution with evidence and recoverable unknown outcomes.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-26-C01 | Empty/wrong/unreachable targets, missing gateway, changed platform/app identity and redacted MCP errors preserve current read and disabled-control behavior. | [test_codesys_panel.py](../../../dashboard/test_codesys_panel.py) | Python offline fixtures in temporary directories; no hardware, network service or provider calls. |
| DASH-26-C02 | Each existing action requires fresh target-bound confirmation, backup/audit success and one-use token; canceled/expired/replayed requests cannot mutate. | [test_codesys_panel.py](../../../dashboard/test_codesys_panel.py) | Offline wire/intent fixtures first; separately approved target device, interface, privileges and installed vendor tools for live qualification. |
| DASH-26-C03 | Existing target cards, confirmation/cancel/error workflows and no-background-probe behavior survive UI extraction. | [test_codesys_panel.py](../../../dashboard/test_codesys_panel.py), [test_e2e.mjs](../../../dashboard/test_e2e.mjs) | Isolated dashboard plus Node DOM fixtures and Playwright browser on supported hosts. |

**Migration and compatibility checks**

- Migrate inventory, package/version expectations and backup/evidence references while keeping secrets separate.
- Preserve machine/project/gateway/runtime binding and operation IDs.
- Replace hardcoded Node discovery with qualified host capabilities.

**Known limits and review gaps**

- Current adapter is scoped to configured Linux SL targets and external tooling; it does not prove Windows IDE or every manufacturer/runtime compatibility.

**Files**

- [dashboard/codesys.js](../../../dashboard/codesys.js)
- [dashboard/codesys_panel.py](../../../dashboard/codesys_panel.py)
- [dashboard/test_codesys_panel.py](../../../dashboard/test_codesys_panel.py)

<a id="dash-27"></a>
### DASH-27 — Classic PCAP analyzer, PNG rendering and reproducible fixture

**Owner:** P11. **Approach:** wrap. **Baseline groups:** BASE-34.

**Current behavior**

- Streams Ethernet/VLAN classic pcap in either byte order and micro/nanosecond timestamps; rejects invalid lengths and unsupported linktypes.
- Summarizes protocol packet/original-frame-byte counts, top five source talkers and bounded timeline; renders a labeled 1000x900 PNG with exact values.
- Caps individual payload allocation at 16 MiB, unique talkers at 10000 and timeline at 60 bins; supports empty/unordered captures.
- Committed deterministic 18-packet fixture and generator support byte-order, count and PNG structure checks.

**Reuse:** Retain analyzer, PNG code and fixture as a portable offline evidence tool plugin; expose inputs/outputs through scoped artifact references without rewriting the parser.

**Added functionality or operating benefit**

- Project artifact permission and immutable source/output digests.
- Optional dashboard artifact preview using the existing rendering output.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-27-C01 | Both byte orders/timestamp formats, exact protocol bytes/talkers, malformed lengths, empty/long timelines and PNG chunks reproduce baseline fixtures. | [test_nettraffic.py](../../../nettraffic/test_nettraffic.py) | Python offline fixtures in temporary directories; no hardware, network service or provider calls. |
| DASH-27-C02 | Plugin and direct/module CLI return the same summaries and bounded failures; a changed or unauthorized capture cannot be silently reused. | [test_nettraffic.py](../../../nettraffic/test_nettraffic.py) | Python offline fixtures in temporary directories; no hardware, network service or provider calls. |

**Migration and compatibility checks**

- Keep CLI/module entry points, units, output dimensions, deterministic fixture and historical test provenance.
- Treat input as a stable file and preserve source capture identity; do not add live capture implicitly.

**Known limits and review gaps**

- No pcapng, stream reassembly or IPv6 extension traversal; source README results are historical and were not rerun.

**Files**

- [nettraffic/README.md](../../../nettraffic/README.md)
- [nettraffic/__init__.py](../../../nettraffic/__init__.py)
- [nettraffic/analyze.py](../../../nettraffic/analyze.py)
- [nettraffic/fixtures/sample.pcap](../../../nettraffic/fixtures/sample.pcap)
- [nettraffic/make_fixture.py](../../../nettraffic/make_fixture.py)
- [nettraffic/pcap.py](../../../nettraffic/pcap.py)
- [nettraffic/png.py](../../../nettraffic/png.py)
- [nettraffic/test_nettraffic.py](../../../nettraffic/test_nettraffic.py)

<a id="dash-28"></a>
### DASH-28 — Dashboard restart and OS startup integration

**Owner:** P12. **Approach:** extend. **Baseline groups:** BASE-36, BASE-17.

**Current behavior**

- restart.sh starts the local dashboard and validates the serving process/home; systemd and launchd entries arrange startup.
- macOS templates use install-time placeholders; the committed systemd example contains a machine-specific /mnt/c/Dev/agentmux path.
- The restart script also has an explicit fresh-database option that must not be mistaken for an ordinary update.

**Reuse:** Reuse startup and readiness checks while replacing hardcoded path assumptions with install-time configuration; package the existing dashboard entry point alongside the evolving platform.

**Added functionality or operating benefit**

- Portable native macOS/Linux and Windows-via-WSL lifecycle.
- Versioned install/update/rollback and actionable diagnostics.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-28-C01 | Install/start/stop/restart on each supported host preserves the intended home/port and reports only verified readiness. | [test_residue.sh](../../../dashboard/test_residue.sh) | Disposable macOS launchd, Linux systemd and WSL installations; no live operator service. |
| DASH-28-C02 | Update/rollback never selects another home or deletes state; fresh-database behavior requires its explicit action and preserves recovery evidence. | [test_residue.sh](../../../dashboard/test_residue.sh) | Disposable deployment with fixture data and backup/restore. |

**Migration and compatibility checks**

- Preserve operator launch behavior, configuration/environment and log locations or provide versioned migration.
- Remove machine-specific paths and resolve one runtime home/socket consistently.
- Keep database reset separate from normal restart.

**Known limits and review gaps**

- Committed service examples are not proof of clean install on the new support matrix.

**Files**

- [dashboard/restart.sh](../../../dashboard/restart.sh)
- [dashboard/ccc-dashboard.service](../../../dashboard/ccc-dashboard.service)
- [dashboard/ccc-dashboard.plist](../../../dashboard/ccc-dashboard.plist)

<a id="dash-29"></a>
### DASH-29 — Isolated dashboard test runner and residue checks

**Owner:** P01. **Approach:** retain. **Baseline groups:** BASE-37, BASE-36.

**Current behavior**

- Runner creates a temporary Agentmux home and its own free port, isolates suite processes, and checks that the operator dashboard PID/home was not changed.
- Shared test helpers, deliberate failability checks and residue snapshots guard against false-green assertions and persistent-state damage.
- Smoke and syntax suites cover endpoint/asset basics and scripts; some suites create fixture records or throwaway workers and are not passive reads.
- Persistent residue manifests hash bytes/modes without printing contents; continuously changing pane/courier logs have an explicit coverage boundary.

**Reuse:** Keep the existing runner and behavioral assertions as baseline evidence. Add target contract suites to the same promotion process without weakening assertions to match new code.

**Added functionality or operating benefit**

- Machine-readable pass/fail/skip, exact environment/version and evidence links.
- Targeted old/new parity checks and explicit destructive-fixture isolation.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-29-C01 | Deliberate broken assertions and known-old code cause failure; a missing prerequisite is skipped/blocked explicitly rather than counted as pass. | [test_testlib.sh](../../../dashboard/test_testlib.sh), [check_test_failability.sh](../../../dashboard/check_test_failability.sh), [test_residue.sh](../../../dashboard/test_residue.sh) | Static checks and Python/Node/shell fixtures in a disposable checkout; no live operator state. |
| DASH-29-C02 | Full fixture runs preserve the live dashboard/home and scoped persistent state; cancellation stops child writers before cleanup. | [test_residue.sh](../../../dashboard/test_residue.sh), [check_test_residue.sh](../../../dashboard/check_test_residue.sh) | Disposable supported host with shell/process tools; operator state is observed only by permitted safe metadata. |

**Migration and compatibility checks**

- Preserve named regression intent, fixtures, isolation rules and historical outcomes with version attribution.
- Do not use broad test runs against user services while establishing baseline.
- Record newly uncovered coverage gaps separately from existing six architecture findings.

**Known limits and review gaps**

- No suite was executed for this audit.
- Runner comments about leasing the usual port are older than the current separate-port implementation; actual code governs.

**Files**

- [dashboard/run_tests.sh](../../../dashboard/run_tests.sh)
- [dashboard/suite_server.py](../../../dashboard/suite_server.py)
- [dashboard/testlib.sh](../../../dashboard/testlib.sh)
- [dashboard/test_testlib.sh](../../../dashboard/test_testlib.sh)
- [dashboard/check_test_failability.sh](../../../dashboard/check_test_failability.sh)
- [dashboard/check_test_residue.sh](../../../dashboard/check_test_residue.sh)
- [dashboard/residue_state.py](../../../dashboard/residue_state.py)
- [dashboard/test_residue.sh](../../../dashboard/test_residue.sh)
- [dashboard/syntax_check.sh](../../../dashboard/syntax_check.sh)
- [dashboard/smoke.sh](../../../dashboard/smoke.sh)

<a id="dash-30"></a>
### DASH-30 — Real browser dashboard workflow suite

**Owner:** P07. **Approach:** extend. **Baseline groups:** BASE-17, BASE-37.

**Current behavior**

- Playwright suite launches an isolated dashboard and Firefox, fails on console/page errors and checks navigation, IIOT card rendering, interaction, theme/layout and related workflows.
- Shell launcher provides a separate ephemeral home/port and manages browser-test prerequisites.

**Reuse:** Retain existing browser scenarios and extend them with explicit per-view/action/preference parity and authorized AG-UI reconnect cases. Review stale expected fixtures before establishing baseline.

**Added functionality or operating benefit**

- All ten current views covered, including Federation.
- Multiple users/viewers, permission revocation, keyboard/accessibility and old/new visual comparisons.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-30-C01 | Correct the source-level nine-versus-ten-view mismatch using the actual current navigation contract, then record an honest baseline browser result before changing dashboard implementation. | [test_e2e.mjs](../../../dashboard/test_e2e.mjs), [test_e2e.sh](../../../dashboard/test_e2e.sh) | Pinned Playwright/Firefox with temporary home/port on a supported host. |
| DASH-30-C02 | Each existing screen/action has an old/new scenario or a named approved workflow change; no view disappears because a new layout omits its test. | [test_e2e.mjs](../../../dashboard/test_e2e.mjs), [test_e2e.sh](../../../dashboard/test_e2e.sh) | Baseline and target isolated dashboards using equivalent fixture records. |

**Migration and compatibility checks**

- Preserve meaningful assertions and compare behavior rather than merely updating selectors.
- Record browser version, viewport, fixture and implementation commit for each run.
- Keep browser suite prerequisites separate from offline shape/DOM tests.

**Known limits and review gaps**

- Static mismatch: the current suite expects nine views while index.html includes Federation as the tenth.
- No browser suite execution or visual qualification was performed in this audit.

**Files**

- [dashboard/test_e2e.mjs](../../../dashboard/test_e2e.mjs)
- [dashboard/test_e2e.sh](../../../dashboard/test_e2e.sh)

<a id="dash-31"></a>
### DASH-31 — Harness, coordination, lifecycle and plugin regressions located under dashboard

**Owner:** P01. **Approach:** retain-evidence. **Baseline groups:** BASE-01, BASE-03, BASE-06, BASE-07, BASE-08, BASE-09, BASE-37.

**Current behavior**

- Tests cover unknown argument refusal, work claims/dependencies/journals, courier delivery, dispatch/unwind, evidence retention and credential repair.
- Other checks cover idle/reap/kill lifecycle, inbox traversal, fake-provider launch, modal send guard and subprocess stdin isolation.
- Run tests retain reviewer-only verdicts, completion gates, objection/escalation, warrants, card linkage and locking; cooperative coordination failures distinguish unknown liveness from an empty roster.
- Plugin tests cover host registration, roster-gated hires, direct/raw mutation guards, MCP discovery and relocatable skill launchers.

**Reuse:** Retain all these tests as behavioral evidence for the runtime components audited elsewhere. Port their invariants into the owning P03–P06 contracts as those components move, without dropping files because they live in the dashboard folder.

**Added functionality or operating benefit**

- Explicit target implementations and per-host test matrices.
- Crash/duplicate/unknown-outcome cases connected to phase gates.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-31-C01 | Every assigned regression is mapped to an owning runtime capability and either rerun against target adapters or superseded by an equivalent accepted test. | [test_launch.sh](../../../dashboard/test_launch.sh), [test_dispatch.py](../../../dashboard/test_dispatch.py), [test_orchestration_plugin.py](../../../dashboard/test_orchestration_plugin.py), [test_plugin_skills.py](../../../dashboard/test_plugin_skills.py), [test_run.sh](../../../dashboard/test_run.sh) | Static checks and Python/Node/shell fixtures in a disposable checkout; no live operator state. |
| DASH-31-C02 | Claim/liveness/lock, guard, stdin and evidence-retention assertions still fail under deliberately broken behavior; scope and identity cannot be satisfied by changing a test expectation. | [test_coordination.sh](../../../dashboard/test_coordination.sh), [test_courier.py](../../../dashboard/test_courier.py), [test_runlock.py](../../../dashboard/test_runlock.py), [test_sandbox_coordination.py](../../../dashboard/test_sandbox_coordination.py), [test_warrant.py](../../../dashboard/test_warrant.py), [test_evidence_archive.sh](../../../dashboard/test_evidence_archive.sh), [test_inbox_guard.sh](../../../dashboard/test_inbox_guard.sh), [test_modal_guard.sh](../../../dashboard/test_modal_guard.sh), [test_no_inherited_stdin.py](../../../dashboard/test_no_inherited_stdin.py), [test_argguard.sh](../../../dashboard/test_argguard.sh), [test_idle.sh](../../../dashboard/test_idle.sh), [test_lifecycle.sh](../../../dashboard/test_lifecycle.sh), [test_runcards.py](../../../dashboard/test_runcards.py) | Per-test temporary homes and fake/live prerequisites declared separately; actual CLI/tmux qualification only on supported hosts. |

**Migration and compatibility checks**

- Carry all fixtures and assertions into P01 baseline inventory, with each script's side effects and dependencies declared.
- Source location does not change functional ownership; link these tests to runtime audit components.
- Preserve prior historical results separately from new baseline results.

**Known limits and review gaps**

- These files test much more than the dashboard; static inventory does not certify their assertions or every host integration.
- Some scripts need tmux or live subprocesses; none were run here.

**Files**

- [dashboard/test_argguard.sh](../../../dashboard/test_argguard.sh)
- [dashboard/test_coordination.sh](../../../dashboard/test_coordination.sh)
- [dashboard/test_courier.py](../../../dashboard/test_courier.py)
- [dashboard/test_dispatch.py](../../../dashboard/test_dispatch.py)
- [dashboard/test_evidence_archive.sh](../../../dashboard/test_evidence_archive.sh)
- [dashboard/test_idle.sh](../../../dashboard/test_idle.sh)
- [dashboard/test_inbox_guard.sh](../../../dashboard/test_inbox_guard.sh)
- [dashboard/test_launch.sh](../../../dashboard/test_launch.sh)
- [dashboard/test_lifecycle.sh](../../../dashboard/test_lifecycle.sh)
- [dashboard/test_modal_guard.sh](../../../dashboard/test_modal_guard.sh)
- [dashboard/test_no_inherited_stdin.py](../../../dashboard/test_no_inherited_stdin.py)
- [dashboard/test_orchestration_plugin.py](../../../dashboard/test_orchestration_plugin.py)
- [dashboard/test_plugin_skills.py](../../../dashboard/test_plugin_skills.py)
- [dashboard/test_run.sh](../../../dashboard/test_run.sh)
- [dashboard/test_runcards.py](../../../dashboard/test_runcards.py)
- [dashboard/test_runlock.py](../../../dashboard/test_runlock.py)
- [dashboard/test_sandbox_coordination.py](../../../dashboard/test_sandbox_coordination.py)
- [dashboard/test_warrant.py](../../../dashboard/test_warrant.py)

<a id="dash-32"></a>
### DASH-32 — Bedrock gateway differential and HTTP contract evidence

**Owner:** P06. **Approach:** retain-evidence. **Baseline groups:** BASE-20, BASE-37.

**Current behavior**

- Gateway tests compare reconstructed source against preserved bytecode with fake upstream responses and streaming/tool/error cases.
- The separate verification helper starts two gateway servers and a fake Bedrock service to exercise actual HTTP routing, aliases, body handling and failures.

**Reuse:** Retain differential and HTTP fixtures while making a named repair/retire decision for the existing gateway and missing setup paths; do not assume a new provider wrapper already covers its behavior.

**Added functionality or operating benefit**

- Explicit compatibility coverage and safe authenticated exposure where retained.
- Honest source/bytecode/runtime-version evidence and failure accounting.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-32-C01 | Supported gateway request, streaming, tool and error cases have equivalent target behavior or an approved compatibility change. | [test_gateway.py](../../../dashboard/test_gateway.py) | Static checks and Python/Node/shell fixtures in a disposable checkout; no live operator state. |
| DASH-32-C02 | HTTP alias/body/error cases pass against isolated local servers; unsupported bytecode/Python combinations remain explicit skips. | [verify_gateway_e2e.py](../../../dashboard/verify_gateway_e2e.py) | Compatible Python for preserved bytecode plus isolated loopback ports/fake upstream; no AWS calls. |

**Migration and compatibility checks**

- Preserve recovered-source provenance, supported endpoint semantics and missing-entrypoint decisions.
- Do not treat mocks as real Bedrock account compatibility.

**Known limits and review gaps**

- Bytecode comparison depends on compatible Python; helper intentionally is not part of every runner invocation.

**Files**

- [dashboard/test_gateway.py](../../../dashboard/test_gateway.py)
- [dashboard/verify_gateway_e2e.py](../../../dashboard/verify_gateway_e2e.py)

<a id="dash-33"></a>
### DASH-33 — Operator diagnostics, demos and fixture maintenance

**Owner:** P06. **Approach:** retain. **Baseline groups:** BASE-17, BASE-37.

**Current behavior**

- Stream status/slot probes inspect terminal SSE capacity; ruler and geometry tools deliberately alter test panes to measure legibility.
- Protocol demonstration walks existing coordination/run guards; seed_queue writes historical orchestration messages for display.
- purge_test_rows identifies known fixture rows and asks before deleting; it is a maintenance tool with real mutation risk, not a read-only audit.

**Reuse:** Keep useful diagnostics as explicit operator tools with scoped targets and documented side effects. Bind test-only helpers to disposable environments; retain historical sample meaning.

**Added functionality or operating benefit**

- Portable CLI diagnostic commands and clear dry-run/target reporting.
- Versioned fixture seeding and safe cleanup boundaries.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-33-C01 | Diagnostics report unavailable streams/capacity accurately and cannot silently target the wrong dashboard home or port. | [test_stream_slots.sh](../../../dashboard/test_stream_slots.sh), [test_residue.sh](../../../dashboard/test_residue.sh) | Disposable dashboard and named throwaway terminal sessions. |
| DASH-33-C02 | Seed/geometry/purge helpers require explicit fixture targets; previews and fixture matching preserve unrelated records and user panes. | [test_residue.sh](../../../dashboard/test_residue.sh) | Disposable home and database containing both known fixture and unrelated sentinel rows. |

**Migration and compatibility checks**

- Inventory hardcoded loopback ports and home assumptions before packaging.
- Preserve exported messages, ruler/geometry intent and confirmation behavior.
- Demos remain demonstrations, not passing automated test evidence.

**Known limits and review gaps**

- Helpers can mutate panes or stored records; none were run.
- Legacy fixed ports and fixture-name cleanup rules need explicit isolation review.

**Files**

- [dashboard/demo_protocol.sh](../../../dashboard/demo_protocol.sh)
- [dashboard/probe_slots.py](../../../dashboard/probe_slots.py)
- [dashboard/purge_test_rows.py](../../../dashboard/purge_test_rows.py)
- [dashboard/seed_queue.py](../../../dashboard/seed_queue.py)
- [dashboard/seed_ruler.sh](../../../dashboard/seed_ruler.sh)
- [dashboard/setgeom.sh](../../../dashboard/setgeom.sh)
- [dashboard/stream_status.sh](../../../dashboard/stream_status.sh)

<a id="dash-34"></a>
### DASH-34 — Vendored terminal, MQTT and OUI dependencies

**Owner:** P12. **Approach:** retain. **Baseline groups:** BASE-17, BASE-25, BASE-26, BASE-36.

**Current behavior**

- Committed xterm JavaScript/CSS and fit addon render terminal output without a runtime package download.
- Paho MQTT 2.1.0 supplies the monitor implementation, with client/enums/matcher/packet types/properties/reason codes/publish/subscribe helpers and typing marker.
- Compressed OUI table enables offline vendor lookup; vendor README records package purpose and Paho wheel hash/license metadata.

**Reuse:** Keep pinned dependencies available for offline startup and reuse their current integration. Any version/package-source replacement requires license/provenance review and dependent terminal/MQTT/scan parity checks.

**Added functionality or operating benefit**

- SBOM, verifiable package hashes and reproducible offline distribution.
- Documented patch/update policy and complete redistribution notices.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-34-C01 | An offline installation includes every needed vendor module, terminal asset and OUI table, and basic terminal/monitor/lookup fixtures work without downloads. | [test_e2e.mjs](../../../dashboard/test_e2e.mjs), [test_mqtt.py](../../../dashboard/test_mqtt.py), [test_field_panels.py](../../../dashboard/test_field_panels.py) | Network-disabled disposable install plus isolated broker fixtures. |
| DASH-34-C02 | Each vendored upgrade is checked against recorded source/version/hash/license and reruns dependent behavior; removed metadata or notices cannot silently disappear. | New fixture/review needed; no existing test claimed | Static distribution manifest and license/provenance review; no legal certification claim. |

**Migration and compatibility checks**

- Preserve vendor paths/import resolution until consumers migrate.
- Review license-text completeness: paho/LICENSE.txt references epl-v20/edl-v10 files that are not present in this assigned tracked vendor tree.
- Keep OUI registry provenance and override semantics; vendor lookup is not authoritative device identification.

**Known limits and review gaps**

- This is dependency inventory and integration review, not a full security audit of minified or third-party source.
- README comments about an older MQTT cap do not override current mqtt.py constants.

**Files**

- [dashboard/vendor/README.md](../../../dashboard/vendor/README.md)
- [dashboard/vendor/addon-fit.js](../../../dashboard/vendor/addon-fit.js)
- [dashboard/vendor/oui.tsv.gz](../../../dashboard/vendor/oui.tsv.gz)
- [dashboard/vendor/paho/LICENSE.txt](../../../dashboard/vendor/paho/LICENSE.txt)
- [dashboard/vendor/paho/__init__.py](../../../dashboard/vendor/paho/__init__.py)
- [dashboard/vendor/paho/mqtt/__init__.py](../../../dashboard/vendor/paho/mqtt/__init__.py)
- [dashboard/vendor/paho/mqtt/client.py](../../../dashboard/vendor/paho/mqtt/client.py)
- [dashboard/vendor/paho/mqtt/enums.py](../../../dashboard/vendor/paho/mqtt/enums.py)
- [dashboard/vendor/paho/mqtt/matcher.py](../../../dashboard/vendor/paho/mqtt/matcher.py)
- [dashboard/vendor/paho/mqtt/packettypes.py](../../../dashboard/vendor/paho/mqtt/packettypes.py)
- [dashboard/vendor/paho/mqtt/properties.py](../../../dashboard/vendor/paho/mqtt/properties.py)
- [dashboard/vendor/paho/mqtt/publish.py](../../../dashboard/vendor/paho/mqtt/publish.py)
- [dashboard/vendor/paho/mqtt/py.typed](../../../dashboard/vendor/paho/mqtt/py.typed)
- [dashboard/vendor/paho/mqtt/reasoncodes.py](../../../dashboard/vendor/paho/mqtt/reasoncodes.py)
- [dashboard/vendor/paho/mqtt/subscribe.py](../../../dashboard/vendor/paho/mqtt/subscribe.py)
- [dashboard/vendor/paho/mqtt/subscribeoptions.py](../../../dashboard/vendor/paho/mqtt/subscribeoptions.py)
- [dashboard/vendor/xterm.css](../../../dashboard/vendor/xterm.css)
- [dashboard/vendor/xterm.js](../../../dashboard/vendor/xterm.js)

<a id="dash-35"></a>
### DASH-35 — Existing branding and session-state assets

**Owner:** P07. **Approach:** retain. **Baseline groups:** BASE-17.

**Current behavior**

- SVGs provide the current CCC brand/favicon/wordmark variants and attached/detached/stale session indicators.
- CurrentColor and inline-versus-file handling allow theme-aware rendering.

**Reuse:** Reuse existing assets while decomposing visual components; product naming changes require explicit design approval rather than incidental replacement during architecture work.

**Added functionality or operating benefit**

- Accessible names and tested light/dark/contrast behavior in the new component wrappers.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-35-C01 | Brand and state symbols render at expected sizes in all supported themes without losing state labels or relying only on color. | [test_themes.sh](../../../dashboard/test_themes.sh), [test_e2e.mjs](../../../dashboard/test_e2e.mjs) | Browser visual/accessibility fixture. |
| DASH-35-C02 | Offline distribution includes all referenced assets; stale/missing asset errors remain visible. | [smoke.sh](../../../dashboard/smoke.sh) | Disposable offline dashboard install. |

**Migration and compatibility checks**

- Preserve file references, SVG titles, state meaning and theme inheritance until revised deliberately.

**Known limits and review gaps**

- Byte/source inspection here did not include rendered visual qualification.

**Files**

- [dashboard/assets/logo-ccc-16.svg](../../../dashboard/assets/logo-ccc-16.svg)
- [dashboard/assets/logo-ccc-24.svg](../../../dashboard/assets/logo-ccc-24.svg)
- [dashboard/assets/logo-ccc-wordmark.svg](../../../dashboard/assets/logo-ccc-wordmark.svg)
- [dashboard/assets/logo-ccc.svg](../../../dashboard/assets/logo-ccc.svg)
- [dashboard/assets/logo.svg](../../../dashboard/assets/logo.svg)
- [dashboard/assets/state-attached.svg](../../../dashboard/assets/state-attached.svg)
- [dashboard/assets/state-detached.svg](../../../dashboard/assets/state-detached.svg)
- [dashboard/assets/state-stale.svg](../../../dashboard/assets/state-stale.svg)

<a id="dash-36"></a>
### DASH-36 — Historical dashboard build specifications

**Owner:** P00. **Approach:** retain-evidence. **Baseline groups:** BASE-17, BASE-37.

**Current behavior**

- Original build spec documents the initial terminal dashboard, local-only/security assumptions, endpoint expectations and team responsibilities.
- Control Center spec records expansion to multiple views, persistence, themes, integrations and older verification notes.

**Reuse:** Keep these documents as historical design/evidence. Reconcile them against current routes and code in the new component inventory; add superseding decisions without deleting history.

**Added functionality or operating benefit**

- Traceable reasons for changed transport, identity, UI structure and persistence.
- Clear distinction between original intent, implemented behavior and future contracts.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| DASH-36-C01 | Conflicting historical constraints are flagged against current code; no capability is dropped solely because an older spec omitted it. | New fixture/review needed; no existing test claimed | Static checks and Python/Node/shell fixtures in a disposable checkout; no live operator state. |
| DASH-36-C02 | Historical test counts remain dated evidence, while the current baseline and target status remain not-run until actually executed. | New fixture/review needed; no existing test claimed | Static checks and Python/Node/shell fixtures in a disposable checkout; no live operator state. |

**Migration and compatibility checks**

- Preserve document provenance and links while adding current applicability notes.
- Record which original constraints still hold and which approved decisions supersede them.

**Known limits and review gaps**

- SPEC.md says dashboard read-only and SPEC_CC.md describes earlier MQTT/Modbus choices; these are not complete descriptions of current behavior.

**Files**

- [dashboard/SPEC.md](../../../dashboard/SPEC.md)
- [dashboard/SPEC_CC.md](../../../dashboard/SPEC_CC.md)

<a id="har-01"></a>
### HAR-01 — Provider launch, session entry and top-level command compatibility

**Owner:** P06. **Approach:** extract. **Baseline groups:** BASE-01, BASE-19, BASE-36.

**Current behavior**

- spawn starts named tmux sessions for Codex, Claude, Grok, shell and passthrough commands. It records CLI, working directory, model/authentication method, posture, role, persona and pane metadata.
- Validates names and arguments, holds a spawn lock, translates Windows paths, chooses a usable Node path, and prepares Claude configuration before launch.
- Codex launch uses --no-daemon to avoid inherited identity from a shared daemon; web search is opt-in. Claude bounded modes require reported CLI support and constrain builtin tools and MCP configuration. Grok bounded postures are refused.
- exec runs a one-shot Codex command with explicit cwd/model, rejects unknown flags and closes inherited stdin. attach prints an attach command. hub forwards to hub/cli.py; version/--version includes VERSION and Git state; help and aliases remain discoverable.

**Reuse:** Keep the existing launch and validation logic behind execution/client plugin contracts, with the current command entrypoints as compatibility callers. Extract by provider only after matching observable behavior with fixtures.

**Added functionality or operating benefit**

- Versioned provider capability declarations and structured launch results distinguish rejected, running and outcome-unknown launches.
- Scope each session to an authenticated user/project and retain logical session identity across transport reconnect.
- Replace implicit unrestricted defaults with an explicit supported execution profile and owner-checked authorization; preserve deliberate authorized execution.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HAR-01-C01 | Exercise spawn validation, quoting, same-name races, missing CLI, persona handling, cwd/model/auth selection, posture rejection and a lost launch reply without a second worker. | [test_launch.sh](../../../dashboard/test_launch.sh), [test_argguard.sh](../../../dashboard/test_argguard.sh), [test_sandbox_coordination.py](../../../dashboard/test_sandbox_coordination.py), [test_agentcli.py](../../../dashboard/test_agentcli.py) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |
| HAR-01-C02 | Preserve exec stdin isolation, exit status, attach instructions, hub forwarding, help aliases and version/dirty attribution. | [test_no_inherited_stdin.py](../../../dashboard/test_no_inherited_stdin.py), [test_argguard.sh](../../../dashboard/test_argguard.sh) | Isolated shell/tmux fixtures and native Windows-to-WSL argument tests; actual supported provider versions for launch qualification. |

**Migration and compatibility checks**

- Map every existing flag, environment override and exit status before changing CLI parsing.
- Carry existing named-session metadata into an explicit legacy session generation; do not infer a new process from a reused name.
- Keep the old harness callable until the mapped provider operations pass and operator setup guides describe any changed defaults.

**Known limits and review gaps**

- No provider or tmux session was launched in this review.
- Legacy posture and environment checks reduce mistakes but do not establish multi-user or hostile-code isolation.
- CLI feature flags and startup behavior need version-specific qualification.

**Files**

- [agentmux.sh](../../../agentmux.sh)

<a id="har-02"></a>
### HAR-02 — Terminal input, observation and modal helpers

**Owner:** P06. **Approach:** extract. **Baseline groups:** BASE-01, BASE-09.

**Current behavior**

- send rejects visible modals unless explicitly forced; it handles multiline bracketed paste and large single-line input with bounded extra Enter attempts.
- key validates named keys and single printable characters and adds no implicit Enter. read/tail strip terminal noise and reject unknown flags; ask combines send/wait/read with a bounded default output and --all escape hatch.
- wait uses observed busy markers and quiet-screen fallback, with explicit timeout and dead-agent exits. These observations do not establish task acceptance.
- unblock only answers the recognized Codex update prompt and leaves trust, consent, account and unknown prompts to a person.
- clear-modals.sh is a separate multi-pass helper with --all and --dry-run. Unlike unblock, it accepts recognized bypass/directory-trust and generic yes/no prompts. Its readiness check is a terminal-text heuristic.

**Reuse:** Extract terminal capture and input handling as provider-specific operations while keeping existing command names. Retain the separate modal helper entrypoint; require an explicit reviewed policy for each automatic answer before enabling it in a new client.

**Added functionality or operating benefit**

- Attach session generation, actor, approval scope and delivery identifiers to input operations.
- Use supported client events when available and mark terminal-derived observations as uncertain.
- Separate consent decisions from mechanical update-dismissal policy, with target/version rechecks immediately before input.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HAR-02-C01 | Preserve literal input, multiline handling, large-paste behavior, key validation, bounded read/ask output and unknown-flag errors. | [test_modal_guard.sh](../../../dashboard/test_modal_guard.sh), [test_argguard.sh](../../../dashboard/test_argguard.sh), [test_launch.sh](../../../dashboard/test_launch.sh) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |
| HAR-02-C02 | Verify unblock refuses trust/account/consent prompts and compare clear-modals behavior using captured prompt fixtures; changed default selection or target generation must not cause an unintended answer. | [test_modal_guard.sh](../../../dashboard/test_modal_guard.sh) | Captured prompt fixtures plus isolated tmux clients on each supported provider version; add explicit clear-modals fixtures because the existing modal suite is not complete coverage of this helper. |
| HAR-02-C03 | Keep wait timeout/death/quiet outcomes distinct from execution and acceptance, including missing or changed busy markers. | [test_lifecycle.sh](../../../dashboard/test_lifecycle.sh), [test_launch.sh](../../../dashboard/test_launch.sh) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |

**Migration and compatibility checks**

- Preserve tunable send/quiet/read settings with their source and supported range.
- Pending text and partially submitted messages need an explicit reconciliation record before switching delivery paths.
- Document any new consent requirement as a behavior change; source removal or loss of manual key control is not authorized.

**Known limits and review gaps**

- Terminal text can change between observation and input.
- clear-modals.sh currently has broader authority than unblock; do not treat both as the same safe automatic behavior.
- No captured prompt or live-provider suite ran during this review.

**Files**

- [agentmux.sh](../../../agentmux.sh)
- [clear-modals.sh](../../../clear-modals.sh)

<a id="har-03"></a>
### HAR-03 — Lifecycle cleanup, archives and Claude credential convergence

**Owner:** P06. **Approach:** extract. **Baseline groups:** BASE-01, BASE-16, BASE-19.

**Current behavior**

- list reports sessions and stale metadata. kill closes named sessions, performs optional Jira/Confluence close-out and sidecar cleanup. reap handles dead sessions and rechecks liveness plus spawn timestamp after slow external calls.
- idle uses a configurable timeout, skips attached sessions and sessions without this home's ownership marker, and refuses action when tmux is unavailable. The detached watchdog closes inherited descriptors and ends when its home or sessions disappear.
- Logs are archived before same-name reuse, with collision suffixes, per-agent counts and an aggregate size limit; failed archive moves append rather than truncate. Pruning avoids following links.
- Claude mirrors are archived after credential files are removed. Credential convergence adopts a newer valid refresh file atomically into the shared owner store and repairs mirror links under a lock.

**Reuse:** Reuse the cleanup ordering, generation checks, archive retention and credential-convergence rules as separate execution/evidence/secret-owner operations. Keep the current implementation while new lifetime ownership is verified.

**Added functionality or operating benefit**

- Use explicit session generations and project ownership rather than same-name sidecars as cross-user authority.
- Bind cleanup to task reservations and immutable evidence references; retain logs before process termination where required.
- Move provider secret coordination behind a dedicated scoped secret facility without copying token values into NATS records.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HAR-03-C01 | Exercise kill/reap/idle with attached sessions, foreign homes, disappeared homes, failed tmux queries, failed kills and same-name respawn during external close-out. | [test_idle.sh](../../../dashboard/test_idle.sh), [test_lifecycle.sh](../../../dashboard/test_lifecycle.sh), [test_residue.sh](../../../dashboard/test_residue.sh) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |
| HAR-03-C02 | Re-spawn repeatedly without truncating evidence; verify archive collisions, retention bounds, link handling, credential exclusion and recovery after an archive failure. | [test_evidence_archive.sh](../../../dashboard/test_evidence_archive.sh), [test_lifecycle.sh](../../../dashboard/test_lifecycle.sh) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |
| HAR-03-C03 | Use synthetic credential files to verify refreshed-token convergence and owner-only permissions without disclosing values, including concurrent cleanup and spawn. | [test_auth.py](../../../dashboard/test_auth.py), [test_evidence_archive.sh](../../../dashboard/test_evidence_archive.sh) | Isolated local POSIX homes with synthetic credentials; actual provider refresh behavior separately qualified. |

**Migration and compatibility checks**

- Inventory existing logs, archives, config mirrors and stale sidecars before cutover; preserve their generation and retention intent.
- Do not copy inherited idle defaults into connected-hub reservation logic: process idleness does not free accepted remote work.
- Retain credential ownership and refresh continuity across upgrade and rollback.

**Known limits and review gaps**

- Existing lifecycle cleanup may perform external ticket transitions; new owner policy must not equate process exit with accepted work.
- Same-user filesystem protection is not a product-wide security boundary.
- Credential refresh compatibility remains version-dependent and was not tested here.

**Files**

- [agentmux.sh](../../../agentmux.sh)

<a id="har-04"></a>
### HAR-04 — Provider authentication, key entry and operator permission setup

**Owner:** P06. **Approach:** extend. **Baseline groups:** BASE-19, BASE-23, BASE-36.

**Current behavior**

- setup_auth.py reads the committed provider/method manifest, validates typed settings, distinguishes provider-wide and method-specific values, preserves legacy v1 settings, writes private files atomically, and generates Codex profiles.
- Provides configure, verify, select and list flows with missing-credential diagnostics and operator-terminal secret input.
- enter-key.sh reads an xAI key without terminal echo, writes the legacy env file at mode 0600 and prints only length/prefix metadata. It currently overwrites that file and relies on shell env syntax.
- verify-grok.sh inspects local setup and makes a live xAI request when run; it records a historical unsupported Codex-to-xAI tool route rather than treating authentication as compatibility.
- add-allow-rule.py is an operator helper that checks or inserts a fixed Claude Bash permission rule, backs up settings and verifies that unrelated parsed settings do not change. Its rule contains a hardcoded Ubuntu/Nick path.

**Reuse:** Retain the manifest-driven setup and private-write helpers. Fold the single-purpose key and permission helpers into scoped setup commands with compatibility entrypoints and explicit migration notices.

**Added functionality or operating benefit**

- Use credential references and typed input rather than shell-sourced secrets; preserve existing env entries during migration.
- Make permission-rule proposals use discovered paths and require operator action for the exact rule.
- Separate offline setup checks from explicitly invoked live provider compatibility checks, with supported-version results.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HAR-04-C01 | Verify v1/v2 settings preservation, provider/method separation, private writes, missing fields, invalid model/endpoint input and configuration selection using synthetic secrets. | [test_auth.py](../../../dashboard/test_auth.py), [check_key_exposure.sh](../../../dashboard/check_key_exposure.sh) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |
| HAR-04-C02 | Verify legacy key-entry migration preserves unrelated env entries and special characters and never exports secret values into logs, process arguments or shared records. | [test_auth.py](../../../dashboard/test_auth.py), [check_key_exposure.sh](../../../dashboard/check_key_exposure.sh) | Isolated terminal fixtures with synthetic values; add direct enter-key compatibility cases. |
| HAR-04-C03 | Preview and apply a generated permission rule against a temporary user settings fixture, preserving other values and backups; default diagnostic paths perform no live inference. | New fixture/review needed; no existing test claimed | Offline temporary homes on Windows/WSL/macOS/Linux; any live Grok check is separately authorized and capped. |

**Migration and compatibility checks**

- Preserve active provider/method selections, _v1_settings, user profiles and credential references.
- Keep existing secrets in their owner facility; migrate values locally without adding them to ordinary NATS state.
- Do not silently run verify-grok.sh or modify the real user's permission settings during import.

**Known limits and review gaps**

- The legacy key helper overwrites env and prints a key prefix; these behaviors require explicit improvement, not literal duplication.
- verify-grok.sh contains dated model/client assumptions and Linux-specific utilities.
- No secret file or live account was accessed.

**Files**

- [taskmgmt/setup_auth.py](../../../taskmgmt/setup_auth.py)
- [enter-key.sh](../../../enter-key.sh)
- [verify-grok.sh](../../../verify-grok.sh)
- [add-allow-rule.py](../../../add-allow-rule.py)

<a id="har-05"></a>
### HAR-05 — Installation and Windows-to-WSL state compatibility

**Owner:** P12. **Approach:** extend. **Baseline groups:** BASE-36, BASE-19.

**Current behavior**

- install.sh finds the checkout, modern Bash, tmux, Python and Node, creates a CRLF-tolerant launcher, diagnoses Windows npm shims and optionally generates a macOS launchd configuration.
- agentmux.cmd translates drive-letter paths before forwarding arguments to the WSL harness, but currently hardcodes Ubuntu and /home/nick.
- link-windows-state.sh supports check/apply/revert, backups and Windows-home discovery. It links reusable state while keeping path-bearing Claude plugin indexes, IDE and shell state local to each OS; it translates paths in local copies.

**Reuse:** Extend the existing installer and state-sharing procedures, keeping reversible migration and entrypoint compatibility. Retain the command launcher until a portable replacement passes the same quoting and exit-status checks.

**Added functionality or operating benefit**

- Discover or explicitly select the WSL distribution and home; preserve native macOS/Linux operation.
- Add pinned prerequisites and local/team broker profiles, update/rollback/uninstall and actionable setup diagnostics.
- Preserve existing client settings and separate Windows/WSL path-bearing registries during plugin installation.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HAR-05-C01 | Exercise clean install, paths with spaces, CRLF source, old/missing Bash/Python/Node, foreign npm shims, launchd generation, update and uninstall without overwriting unrelated settings. | [test_launch.sh](../../../dashboard/test_launch.sh), [test_lifecycle.sh](../../../dashboard/test_lifecycle.sh) | Fresh macOS/Linux/WSL fixture homes and a native Windows launcher test; add dedicated installer cases. |
| HAR-05-C02 | Verify check is read-only and apply/revert restores backups while OS-specific plugin paths remain local; ambiguous Windows-home discovery must require an explicit target. | New fixture/review needed; no existing test claimed | Synthetic Windows/WSL profiles and plugin indexes; no real credential stores. |
| HAR-05-C03 | Round-trip spaces, backslashes, quotes, empty/dash-prefixed arguments and subprocess exit status through the Windows entrypoint. | [test_argguard.sh](../../../dashboard/test_argguard.sh) | Native cmd/PowerShell to a disposable WSL distribution; new launcher-specific fixtures are required. |

**Migration and compatibility checks**

- Record installed launcher/service locations, discovered distro/home and state-link targets before changes.
- Version and retain backups; rollback must preserve changes made after installation rather than replacing entire user profiles.
- Keep repository checkout paths and platform-local plugin caches distinct from portable package identity.

**Known limits and review gaps**

- Current launcher path and some fallback discovery assumptions are machine-specific.
- The installer warns that the Windows entrypoint can lose exit status; the audit did not execute it.
- Linking whole client state across OS versions requires explicit support tests.

**Files**

- [install.sh](../../../install.sh)
- [agentmux.cmd](../../../agentmux.cmd)
- [link-windows-state.sh](../../../link-windows-state.sh)

<a id="har-06"></a>
### HAR-06 — macOS command compatibility helpers

**Owner:** P06. **Approach:** retain. **Baseline groups:** BASE-36, BASE-37.

**Current behavior**

- Provides a file-descriptor-only flock shim with exclusive/shared/unlock/nonblocking/timeout behavior, a setsid shim with fork/wait handling, a timeout wrapper with TERM then kill and exit 124, and tac via tail -r.
- Scripts select these helpers only on macOS; the standalone harness includes equivalent inline helpers because tests copy it alone.
- Python helper shebangs avoid a test's stub python3 on PATH.

**Reuse:** Retain the portable helpers and their documented limited contracts. Share implementations only after standalone-copy and fixture expectations remain valid.

**Added functionality or operating benefit**

- Add explicit parity fixtures for supported helper forms across macOS and GNU environments.
- Report unsupported options clearly and pin platform prerequisites used by packaged execution.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HAR-06-C01 | Verify inherited descriptor lock lifetime, contention timeout, child exit/signal propagation, timeout escalation and reversed-line output. | [test_testlib.sh](../../../dashboard/test_testlib.sh), [test_runlock.py](../../../dashboard/test_runlock.py), [test_no_inherited_stdin.py](../../../dashboard/test_no_inherited_stdin.py) | macOS and Linux/WSL subprocess fixtures; add direct shim conformance cases. |
| HAR-06-C02 | Ensure native Linux tools retain priority and fixtures that stub PATH cannot replace the intended shim interpreter. | [test_testlib.sh](../../../dashboard/test_testlib.sh), [test_residue.sh](../../../dashboard/test_residue.sh) | Isolated macOS and Linux PATH fixtures. |

**Migration and compatibility checks**

- Keep existing supported flags and exit statuses; document any consolidation of inline and directory copies.
- Do not advertise full GNU command equivalence.

**Known limits and review gaps**

- These are partial utility implementations, not general replacements for GNU tools.
- No subprocess compatibility tests ran.

**Files**

- [compat/README.md](../../../compat/README.md)
- [compat/bin/flock](../../../compat/bin/flock)
- [compat/bin/setsid](../../../compat/bin/setsid)
- [compat/bin/tac](../../../compat/bin/tac)
- [compat/bin/timeout](../../../compat/bin/timeout)

<a id="har-07"></a>
### HAR-07 — Agent definition parsing and roster selection

**Owner:** P03. **Approach:** extract. **Baseline groups:** BASE-02, BASE-03.

**Current behavior**

- Parses constrained Markdown frontmatter into AgentSpec with identity, CLI/model/auth, posture, tools, capabilities, role, worktree policy, max instances, persona and source checksum.
- Discovers repository/user .agentmux/agents and compatible .claude/agents directories, diagnoses unknown keys, validates bounds, refuses nonregular/symlink inputs and reserves invalid duplicate names instead of silently selecting another definition.
- choose_roster considers task type, touched directories, acceptance count, dependency depth, capability labels and configured caps. It selects a deterministic lead, proposes workers/reviewers and reports missing capabilities.
- Non-Claude named tool restrictions are reported as advisory rather than enforced.

**Reuse:** Extract the parser and deterministic roster rules into definition/team plugins. Keep Markdown import and checksums as compatibility features, translating to versioned manifests without losing original source text.

**Added functionality or operating benefit**

- Declare independent and parent-owned package identity while retaining explicit source provenance.
- Use project-approved lead and member selection instead of automatically choosing the first alphabetical lead.
- Keep capability eligibility deterministic before any optional Jev ranking, and distinguish desired tools from enforceable host capabilities.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HAR-07-C01 | Import all supported definition fields, duplicate names, malformed/oversized input, unknown keys, symlink/FIFO replacement and stale checksums without silently accepting a different persona. | [test_agentdefs.py](../../../dashboard/test_agentdefs.py), [test_boardagents.py](../../../dashboard/test_boardagents.py), [test_agentcli.py](../../../dashboard/test_agentcli.py) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |
| HAR-07-C02 | Preserve roster caps, bug reviewer preference, deep-dependency behavior, capability tie-breaks and gaps; prevent unrelated bundled personas from becoming a project's lead. | [test_agentdefs.py](../../../dashboard/test_agentdefs.py), [test_boardteams.py](../../../dashboard/test_boardteams.py), [test_teamcli.py](../../../dashboard/test_teamcli.py) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |

**Migration and compatibility checks**

- Keep original path/scope/checksum and unsupported-field diagnostics on repeated imports.
- Do not convert advisory tools into a claimed security boundary.
- Preserve approved rosters independently of future definition edits; show when a definition revision changes.

**Known limits and review gaps**

- The current lead selection is alphabetical and can choose an unrelated project persona.
- Persona prose does not enforce permission or model diversity.
- Parser and roster tests were read as regression references, not run.

**Files**

- [taskmgmt/agentdefs.py](../../../taskmgmt/agentdefs.py)

<a id="har-08"></a>
### HAR-08 — Bundled personas and workflow instructions

**Owner:** P03. **Approach:** retain. **Baseline groups:** BASE-02, BASE-03, BASE-07.

**Current behavior**

- Fourteen Markdown definitions include the eight Agora role profiles, a catalog lead, three inventory scanners, the CCC orchestrator and a nettraffic reviewer.
- Profiles contain capabilities, CLI, role, posture, worktree and instance declarations, plus project-specific territory, claim/journal, evidence and review instructions.
- The CCC orchestrator describes a narrow warrant, independent review, operator approval and escalation. Scanner/catalog profiles describe bounded discovery and one-file ownership. Agora profiles retain the older ticket aliases and project-specific acceptance instructions.
- Several profiles contain local paths, current ticket numbers and unrestricted posture; they are existing user/project content, not universal product defaults.

**Reuse:** Retain every profile as source-backed configuration. Import them as opt-in project packages or examples with original text and revisions; do not activate every bundled profile for every project.

**Added functionality or operating benefit**

- Show applicability, host support, permissions and stale machine-specific references before adoption.
- Use package-scoped roles and approved project membership with clear independent-child ownership.
- Keep examples usable while allowing administrators to supply updated paths and bounded execution profiles.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HAR-08-C01 | Load all fourteen profiles, preserve fields and persona text, report incompatible/missing client capabilities and keep each profile's project scope. | [test_agentdefs.py](../../../dashboard/test_agentdefs.py), [test_boardagents.py](../../../dashboard/test_boardagents.py), [test_plugin_skills.py](../../../dashboard/test_plugin_skills.py) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |
| HAR-08-C02 | Verify default enrollment does not recruit a scanner or Agora lead into an unrelated project, and edits do not silently alter an approved team. | [test_boardteams.py](../../../dashboard/test_boardteams.py), [test_teamcli.py](../../../dashboard/test_teamcli.py) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |

**Migration and compatibility checks**

- Preserve original persona files and checksums; record any transformed path or field as a derived value.
- Map old task aliases and example project names without importing them as live work.
- Require explicit project adoption for profiles that request network or filesystem scanning.

**Known limits and review gaps**

- The definitions contain historical workflow instructions and machine-specific paths that need user review.
- Different CLI labels alone do not prove different model behavior.
- No persona was launched or installed.

**Files**

- [.agentmux/agents/agora-brain.md](../../../.agentmux/agents/agora-brain.md)
- [.agentmux/agents/agora-defect.md](../../../.agentmux/agents/agora-defect.md)
- [.agentmux/agents/agora-lead.md](../../../.agentmux/agents/agora-lead.md)
- [.agentmux/agents/agora-perf.md](../../../.agentmux/agents/agora-perf.md)
- [.agentmux/agents/agora-release.md](../../../.agentmux/agents/agora-release.md)
- [.agentmux/agents/agora-review.md](../../../.agentmux/agents/agora-review.md)
- [.agentmux/agents/agora-ui.md](../../../.agentmux/agents/agora-ui.md)
- [.agentmux/agents/agora-unreal.md](../../../.agentmux/agents/agora-unreal.md)
- [.agentmux/agents/catalog-lead.md](../../../.agentmux/agents/catalog-lead.md)
- [.agentmux/agents/ccc-orchestrator.md](../../../.agentmux/agents/ccc-orchestrator.md)
- [.agentmux/agents/netcap-reviewer.md](../../../.agentmux/agents/netcap-reviewer.md)
- [.agentmux/agents/scan-dev.md](../../../.agentmux/agents/scan-dev.md)
- [.agentmux/agents/scan-host.md](../../../.agentmux/agents/scan-host.md)
- [.agentmux/agents/scan-user.md](../../../.agentmux/agents/scan-user.md)

<a id="har-09"></a>
### HAR-09 — Claims, local identity, warrants and journal

**Owner:** P04. **Approach:** extract. **Baseline groups:** BASE-08, BASE-10, BASE-07.

**Current behavior**

- claim/release/claims use resource names, staged publication, atomic links and inode-generation locks to avoid deleting or replacing another claim during races.
- Identity resolution checks the pane environment against an explicit actor and live tmux sessions; unavailable tmux is reported as unknown rather than an empty session set.
- An expiring private orchestrator warrant permits the named pane to use only the consulted orchestration verbs. Issuance separates its secret from the general worker env; revocation precedes process termination.
- orchestrator start/stop/status resolves the CLI from its definition, avoids a second live orchestrator, issues/revokes warrants and records a request. journal and coordination announcements retain actor, kind, subject, body and resource interest.

**Reuse:** Reuse claim conflict rules, identity diagnostics, journal vocabulary and warrant scope as contract fixtures. Move authoritative ownership into scoped domain operations; retain filesystem claims only for the legacy path during a fenced transition.

**Added functionality or operating benefit**

- Authenticate user/project/session identities across NATS instead of treating writable environment variables as authority.
- Record claim generations and operation identifiers in durable owner records, preserving resource conflict semantics.
- Separate expiring local presence/leases from accepted or acceptance-unknown remote reservations.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HAR-09-C01 | Exercise concurrent claim replacement/release, path/name collisions, stale generation, expiry, force policy and unavailable tmux without losing another actor's claim. | [test_coordination.sh](../../../dashboard/test_coordination.sh), [test_sandbox_coordination.py](../../../dashboard/test_sandbox_coordination.py) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |
| HAR-09-C02 | Reject forged actor flags, worker use of orchestrator-only verbs, expired/wrong-pane warrants and a reserved orchestrator name; verify revocation before stop and secret exclusion from ordinary workers. | [test_warrant.py](../../../dashboard/test_warrant.py), [test_argguard.sh](../../../dashboard/test_argguard.sh), [test_coordination.sh](../../../dashboard/test_coordination.sh) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |
| HAR-09-C03 | Preserve journal and targeted/broadcast coordination records through repeated import without executing historical announcements. | [test_coordination.sh](../../../dashboard/test_coordination.sh), [test_courier.py](../../../dashboard/test_courier.py) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |

**Migration and compatibility checks**

- Map each active claim to its source resource, holder, generation and project before admission moves to the new owner.
- Import journal timestamps and actor provenance without granting current authority to historical identities.
- Do not carry the test-only identity bypass into production authentication.

**Known limits and review gaps**

- Existing identity and warrants are cooperative safeguards under a shared OS user, not hostile-code isolation.
- One local orchestrator limit must become an explicit scoped policy for multiple users/projects.
- No concurrency or warrant tests ran.

**Files**

- [taskmgmt/coordination.py](../../../taskmgmt/coordination.py)
- [agentmux.sh](../../../agentmux.sh)

<a id="har-10"></a>
### HAR-10 — Board, task, epic and team command compatibility

**Owner:** P05. **Approach:** wrap. **Baseline groups:** BASE-04, BASE-05, BASE-03, BASE-15.

**Current behavior**

- tasks and task expose new/add/show/edit, start/done/block/todo/park/backlog, acceptance criteria, labels, dependencies, evidence/commit/touched-path attachment, comments, links, assignment, move, why and next.
- epic exposes new/status/use/list; board exposes config, doctor, history, find, triage and recorded overrides. The underlying coordination CLI also exposes generic entity creation and sprint commitments.
- roster/recruit/approve/retire/hire reach the existing board team API; definition listing/update/drop are also available through coordination.
- Wrappers bind actor values rather than allowing repeated --agent/--holder/--by flags to replace the caller. Task todo maps to the board's open state, and block/park reasons are retained.

**Reuse:** Keep command names, output contracts and board validation behavior through a compatibility caller that invokes the new owning plugins over NATS. Reuse existing validation and formatting where appropriate instead of designing a second task model.

**Added functionality or operating benefit**

- Expose one declared command registry to CLI and MCP with discoverable verbs and versioned errors.
- Carry all entity kinds and their relationships into retained owner records and rebuildable views.
- Apply the same readiness, WIP, override and project authorization decisions to every entrypoint.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HAR-10-C01 | Exercise every task/epic/board/team verb and status shorthand, including reason forwarding, actor spoof rejection, unavailable board errors and unsupported fields. | [test_agentcli.py](../../../dashboard/test_agentcli.py), [test_teamcli.py](../../../dashboard/test_teamcli.py), [test_board.py](../../../dashboard/test_board.py), [test_boardteams.py](../../../dashboard/test_boardteams.py) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |
| HAR-10-C02 | Import EP/TM/ADR/SP/CAP records with labels, links, criteria, comments, commits, paths, deletion history and assignments twice without lost relationships or duplicate effects. | [test_board.py](../../../dashboard/test_board.py), [test_coordination.sh](../../../dashboard/test_coordination.sh) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |
| HAR-10-C03 | Preserve readiness/WIP/override and approved roster behavior across CLI and new NATS/MCP callers; unknown or stale revisions cannot bypass the owner. | [test_board.py](../../../dashboard/test_board.py), [test_dispatch.py](../../../dashboard/test_dispatch.py), [test_boardteams.py](../../../dashboard/test_boardteams.py) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |

**Migration and compatibility checks**

- Maintain explicit source identity mappings rather than treating board tasks, run jobs, hub work and shared cards as one ID.
- Freeze/fence legacy writes at cutover; do not make both HTTP-backed and NATS-backed commands authoritative.
- Keep script-visible statuses and diagnostics compatible or document a versioned change before rollout.

**Known limits and review gaps**

- Current commands depend on dashboard HTTP and local actor conventions.
- This mapping includes direct coordination entrypoints; it does not claim every one already has a top-level shell alias.
- No board data was imported or changed.

**Files**

- [taskmgmt/coordination.py](../../../taskmgmt/coordination.py)
- [agentmux.sh](../../../agentmux.sh)

<a id="har-11"></a>
### HAR-11 — Dispatch, worker pool, team worktrees and collection

**Owner:** P05. **Approach:** extract. **Baseline groups:** BASE-03, BASE-06, BASE-05.

**Current behavior**

- dispatch chooses ready work from board policy, refuses a foreign board, reads the complete brief, resolves an agent definition and performs spawn, claims, board start and delivery with unwind paths.
- Dry-run reports the selected worker without launching. If direct brief delivery meets a modal, it queues the brief; failure to deliver or queue triggers withdrawal.
- Collection checks real process state, preserves busy workers, collects members before the lead, integrates approved worktrees and leaves submitted work for review rather than marking the card done.
- Pool cycles collect before refill, reread configuration, respect WIP/global agent capacity and expose start/stop/status/once/loop behavior.
- Worktree creation/integration and teardown preserve dirty/conflicted/unmerged work; an orphaned team is parked instead of silently redispatched.

**Reuse:** Extract the proven selection, brief, collection and worktree logic behind task/execution/workspace contracts. Keep the legacy dispatch path isolated until state transitions and failure handling match.

**Added functionality or operating benefit**

- Commit dispatch intent and operation identifiers before external launch, reconciling uncertain replies without a second worker.
- Use scoped execution profiles that permit coordination without requiring unrestricted workers.
- Add fair multi-user/project capacity policy while preserving explicit team membership and branch ownership.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HAR-11-C01 | Inject failures before/after spawn, claim, board start, direct send and queued fallback; verify no silent lost task, leaked claim or duplicate worker. | [test_dispatch.py](../../../dashboard/test_dispatch.py), [test_launch.sh](../../../dashboard/test_launch.sh), [test_courier.py](../../../dashboard/test_courier.py) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |
| HAR-11-C02 | Exercise dry-run, collect-before-refill, disabled pool, live capacity changes, busy member preservation, failed kill, orphan parking and restart recovery. | [test_dispatch.py](../../../dashboard/test_dispatch.py), [test_boardteams.py](../../../dashboard/test_boardteams.py) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |
| HAR-11-C03 | Verify branch/worktree ownership, dirty/conflicted work preservation, member integration and cleanup across multiple repositories. | [test_dispatch.py](../../../dashboard/test_dispatch.py), [test_boardteams.py](../../../dashboard/test_boardteams.py), [test_teamcli.py](../../../dashboard/test_teamcli.py) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |

**Migration and compatibility checks**

- Preserve briefs, pool settings/state, approved rosters, worktree locations, branches and unresolved collection outcomes.
- Reconcile every in-flight task and process before switching the dispatch owner.
- Review any change to cleanup-triggered external ticket writes separately from local task rollback.

**Known limits and review gaps**

- Dispatch currently refuses bounded postures and AGENTMUX_NO_BYPASS; the target must remove that limitation through explicit host capabilities.
- Worker idleness and attached evidence are not equivalent to acceptance.
- No workers, worktrees or pool processes were created.

**Files**

- [taskmgmt/dispatch.py](../../../taskmgmt/dispatch.py)
- [agentmux.sh](../../../agentmux.sh)

<a id="har-12"></a>
### HAR-12 — Run ledger, submission review, objections and completion

**Owner:** P05. **Approach:** extract. **Baseline groups:** BASE-07, BASE-15, BASE-16.

**Current behavior**

- run start/assign/submit/verdict/status/complete/teardown maintain append-only events, job state and sidecars with per-run locking.
- Submission histories and verdict files are retained, rejected work requires a reason, assigned identities constrain submission/review and a worker cannot verify its own job.
- Three failed reviews escalate rather than granting a fourth self-service attempt. Completion uses independent review and required operator approval, checks open board cards, and reports run completion separately from card status.
- Objections, notices, approval files and file-drift checks retain the reason work cannot complete. Forced completion captures evidence; teardown is scoped to ledger members, rejects invalid/open runs without explicit force and supports keeping agents.

**Reuse:** Reuse the event fold, gate decisions, archived review text and teardown scope as the run plugin's starting point. Translate persistence to versioned durable records while retaining original ledgers and readable evidence.

**Added functionality or operating benefit**

- Bind each submission, verdict and approval to immutable repository/commit/artifact identities across repositories.
- Check changed evidence at review and acceptance boundaries, using durable revisions and operation IDs.
- Persist completion intent and reservations so restart/replay cannot fabricate review or repeat teardown effects.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HAR-12-C01 | Verify assigned identities, self-review rejection, required rejection reason, resubmission history, three-failure escalation and concurrent assign/submit/verdict/complete transitions. | [test_run.sh](../../../dashboard/test_run.sh), [test_runlock.py](../../../dashboard/test_runlock.py), [test_warrant.py](../../../dashboard/test_warrant.py) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |
| HAR-12-C02 | Exercise missing/stale approval, changed evidence, objections and linked open board cards; retain distinct submitted, verified, completed and accepted outcomes. | [test_runsview.py](../../../dashboard/test_runsview.py), [test_runcards.py](../../../dashboard/test_runcards.py), [test_run.sh](../../../dashboard/test_run.sh) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |
| HAR-12-C03 | Reject premature/invalid teardown, preserve forced evidence and unrelated sessions, honor keep-agents and retain courier/dashboard service operation. | [test_run.sh](../../../dashboard/test_run.sh), [test_lifecycle.sh](../../../dashboard/test_lifecycle.sh), [test_evidence_archive.sh](../../../dashboard/test_evidence_archive.sh) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |

**Migration and compatibility checks**

- Import event sequence, job IDs, submission/verdict attempts, sidecars, approvals and notices with source digests.
- Never infer acceptance from COMPLETE alone or combine a run ID with a board card by title.
- Historical imports and view rebuilds must not trigger notification, merge, teardown or worker launch.

**Known limits and review gaps**

- Submission hashes are not fully rechecked at every verdict/completion boundary; file-list completeness and multi-repository binding need stronger checks.
- Different agent identities do not prove independent models.
- No gate or review test ran.

**Files**

- [taskmgmt/run.py](../../../taskmgmt/run.py)
- [agentmux.sh](../../../agentmux.sh)

<a id="har-13"></a>
### HAR-13 — Courier, post, virtual inbox and backlog recovery

**Owner:** P05. **Approach:** extract. **Baseline groups:** BASE-09, BASE-10.

**Current behavior**

- post appends typed messages to a sender outbox; inbox reads or clears a recipient's inbox. Supported kinds include plan/request/reply/status/finding/error/claim/release.
- Courier exposes start/stop/status/once/watch/dead/requeue. Initial legacy outboxes are adopted at EOF unless explicitly replayed; later new outboxes start at zero.
- Cursors retain device/inode/offset; replaced/truncated files reset visibly, partial trailing lines wait for completion and oversized records cannot block an outbox forever.
- Input checks reject linked/nonregular files and malformed records. Pending traffic preserves recipient order without blocking other recipients, bounded retry/backoff ends in a retained dead letter, and virtual recipients receive inbox files.
- Delivery never forces a modal and courier-generated errors are not addressed back into a failure loop.

**Reuse:** Reuse parsing, cursor, retry, ordering and virtual-recipient rules as compatibility contracts. Import pending and dead-letter records into the messaging owner's durable channels once, then fence the old courier.

**Added functionality or operating benefit**

- Use durable message IDs and explicit delivered/received/acknowledged/processed/accepted states.
- Expose per-recipient backlog and failure reasons through authorized events without using notifications as prompt input.
- Recover interrupted cutover and unknown delivery outcomes without automatically typing duplicate instructions.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HAR-13-C01 | Verify initial EOF adoption, later outbox creation, rotation/truncation, partial/oversized/malformed lines and symlink/hardlink rejection. | [test_courier.py](../../../dashboard/test_courier.py), [test_inbox_guard.sh](../../../dashboard/test_inbox_guard.sh) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |
| HAR-13-C02 | Exercise recipient ordering, backlog limits, exponential retry, virtual inbox delivery, dead-letter requeue and no forced modal or courier error loop. | [test_courier.py](../../../dashboard/test_courier.py), [test_modal_guard.sh](../../../dashboard/test_modal_guard.sh) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |
| HAR-13-C03 | Migrate active cursors, pending rows and dead letters with replay/duplicate fixtures; distinguish clear/read from explicit execution acceptance. | [test_courier.py](../../../dashboard/test_courier.py), [test_inbox_guard.sh](../../../dashboard/test_inbox_guard.sh), [test_coordination.sh](../../../dashboard/test_coordination.sh) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |

**Migration and compatibility checks**

- Retain original queue files, consumed offsets, pending attempt counts, dead-letter reasons and unresolved inbox entries.
- Assign stable import IDs and a cutover boundary; only one delivery path may act on each logical message.
- Keep legacy and hub receipt semantics distinct until the owner reconciles them.

**Known limits and review gaps**

- The source has filesystem and hub delivery paths with different receipt meanings.
- Terminal send success does not prove client processing.
- No queued message was delivered, cleared or requeued.

**Files**

- [taskmgmt/courier.py](../../../taskmgmt/courier.py)
- [agentmux.sh](../../../agentmux.sh)

<a id="har-14"></a>
### HAR-14 — Notifications and originating-terminal feedback

**Owner:** P05. **Approach:** extract. **Baseline groups:** BASE-10.

**Current behavior**

- Provides bounded notifications to Windows/macOS desktop surfaces, a tmux status bar and a configured external command; it returns channel-specific results.
- Configured command text is split once; message data is sent on stdin with shell disabled, rather than interpolated into executable text.
- tmux target resolution is checked before display-message because that command can report success for a nonexistent target. Child tools use closed stdin where appropriate.
- No desktop, no configured channels and delivery failure remain different outcomes; every configured channel is attempted.

**Reuse:** Reuse channel-specific delivery and safe payload handling inside notification plugins. Retain the durable notice owner and originating-session routing rather than implementing notices as terminal keystrokes.

**Added functionality or operating benefit**

- Scope subscriptions and notification preferences by user/project and bind messages to durable notice IDs.
- Add deduplication, acknowledgment and escalation without suppressing mandatory review/failure events.
- Treat externally configured commands as explicit trusted contributions with bounded execution.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HAR-14-C01 | Verify shell metacharacters remain data, child stdin cannot consume the caller's input, missing targets are not reported delivered and all configured channels receive bounded payloads. | [test_notify.py](../../../dashboard/test_notify.py), [test_no_inherited_stdin.py](../../../dashboard/test_no_inherited_stdin.py) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |
| HAR-14-C02 | Verify missing desktop/configuration, timeout, command failure and repeated notices preserve useful status and required durable evidence. | [test_notify.py](../../../dashboard/test_notify.py), [test_chatter.py](../../../dashboard/test_chatter.py) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |

**Migration and compatibility checks**

- Import notification preferences and destination identity separately from private command credentials.
- Replay notice state without replaying old external notifications.
- Preserve origin-terminal association when the observer disconnects.

**Known limits and review gaps**

- Desktop delivery is platform/session dependent.
- Configured external commands can have side effects and require explicit trust.
- No notification was sent.

**Files**

- [taskmgmt/notify.py](../../../taskmgmt/notify.py)

<a id="har-15"></a>
### HAR-15 — Jira and Confluence clients, scripts and setup

**Owner:** P06. **Approach:** wrap. **Baseline groups:** BASE-22, BASE-19.

**Current behavior**

- Atlassian client supports Cloud API-token/basic authentication and Server/DC bearer authentication, HTTPS verification, bounded requests, empty 204 responses and user-facing HTTP error hints.
- Jira operations include creation, search, comments, workflow transition listing and selected transitions; Confluence supports page lookup and versioned upsert.
- task.py offers whoami/create/comment/done/report/transitions for shell lifecycle hooks, with dry-run request shapes, machine-readable key/URL stdout and separate diagnostics.
- Log-to-comment/report paths validate names, resolve within the log directory, refuse hardlinked files, cap input and strip ANSI escapes.
- setup_atlassian.py collects secrets without echo and writes configuration privately through a temporary file and rename; it preserves a chosen home override.

**Reuse:** Wrap the existing HTTP and payload transformations in explicit Jira/Confluence tool plugins. Keep the script interface for legacy spawn/cleanup callers until their operations migrate to the new owner.

**Added functionality or operating benefit**

- Bind external mutations to actor, project/space, operation intent and current approval.
- Reconcile lost replies before retrying issue/page creation or workflow changes.
- Separate local task acceptance and process cleanup from remote ticket transitions.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HAR-15-C01 | Preserve Cloud/Server headers, Jira/Confluence payloads, transitions, dry-run output and 401/403/404/timeout diagnostics using mocked HTTP. | [test_tickets.py](../../../dashboard/test_tickets.py) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |
| HAR-15-C02 | Verify log exports enforce path/link/size checks and strip control sequences while preserving useful evidence. | [test_tickets.py](../../../dashboard/test_tickets.py) | Isolated macOS, Linux and WSL fixtures; pinned NATS server and clients for the target implementation. |
| HAR-15-C03 | Exercise creation/update lost replies and duplicate operations; local rollback or cleanup must not unconditionally replay an external transition. | [test_tickets.py](../../../dashboard/test_tickets.py), [test_lifecycle.sh](../../../dashboard/test_lifecycle.sh) | Mock services and isolated homes first; supported Jira/Confluence deployment versions require separately approved service tests. |

**Migration and compatibility checks**

- Keep external issue/page IDs, selected transition rules, project/space settings and associated agent/run provenance.
- Move credential references separately from configuration; never place tokens in shared history.
- Record unresolved side effects before switching lifecycle hooks to a new tool owner.

**Known limits and review gaps**

- External side effects cannot be rolled back with a local state change.
- The CLI's transition selection is name/regex based and needs deployment-specific compatibility fixtures.
- No external service request was made.

**Files**

- [taskmgmt/atlassian.py](../../../taskmgmt/atlassian.py)
- [taskmgmt/task.py](../../../taskmgmt/task.py)
- [taskmgmt/setup_atlassian.py](../../../taskmgmt/setup_atlassian.py)

<a id="har-16"></a>
### HAR-16 — Bedrock Responses-to-Chat gateway

**Owner:** P06. **Approach:** wrap. **Baseline groups:** BASE-20.

**Current behavior**

- Translates selected Responses input items into Chat Completions messages and flattens nested function-tool namespaces to a bounded depth while reporting unsupported tool types.
- Maps output text, tool calls, usage and streaming events back to Responses shapes; the text filter handles reasoning tags split across chunks and preserves short or malformed-tag output.
- Reads the Bedrock bearer credential from the environment, limits request size, uses an upstream timeout and binds a threaded HTTP server to loopback.
- Uses a static model list and local logging; loopback callers are not authenticated. Source was reconstructed and retains intentional compatibility details documented beside the functions.

**Reuse:** Retain the translation implementation and differential fixtures inside a provider compatibility plugin. Add a scoped local caller boundary before exposing it to multiple users; do not rewrite wire transformations without evidence.

**Added functionality or operating benefit**

- Declare exact supported input/tool/event/model capabilities and explicit unsupported outcomes.
- Authenticate/scoped-route callers without exposing a shared cloud credential to arbitrary local or remote requests.
- Add upstream cancellation/timeout and usage provenance where supported, preserving outcome-unknown reporting.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HAR-16-C01 | Preserve message/tool translation, namespace depth, duplicate-tool handling, short replies, split tags, malformed tags, tool streaming, usage and error framing. | [test_gateway.py](../../../dashboard/test_gateway.py) | Offline Python HTTP/stream fixtures; CPython 3.12 for the preserved-bytecode differential subset. |
| HAR-16-C02 | Verify request limits, loopback exposure and logs with synthetic credentials; new multi-user access rules deny unrelated users/projects. | [test_gateway.py](../../../dashboard/test_gateway.py), [check_key_exposure.sh](../../../dashboard/check_key_exposure.sh) | Isolated HTTP fixtures; actual Bedrock endpoint/model tests are separately approved. |

**Migration and compatibility checks**

- Keep reconstructed source provenance and preserved bytecode reference intact.
- Inventory missing setup/probe scripts and unsupported authentication-manifest paths before claiming a supported end-to-end Bedrock setup.
- Preserve configured region/model and secret references without assuming old live compatibility remains current.

**Known limits and review gaps**

- The shipped manifest/setup paths do not establish complete Bedrock support.
- The gateway implements a subset of the APIs and accepts loopback requests without a client credential.
- No network request or model inference ran.

**Files**

- [taskmgmt/bedrock_gateway.py](../../../taskmgmt/bedrock_gateway.py)

<a id="har-17"></a>
### HAR-17 — Recovered Bedrock reference artifact

**Owner:** P01. **Approach:** retain-evidence. **Baseline groups:** BASE-20, BASE-37.

**Current behavior**

- README records loss/reconstruction provenance, the reason the bytecode has a .bin suffix and the role of the original CPython 3.12 artifact in differential checks.
- The retained bytecode is reference evidence rather than a normal import cache. Its SHA-256 was read as FEDBA136C42822AED1E8BCB430C2F6EBA48B63C392D2CC1A3B6DA1487A83400F.

**Reuse:** Preserve the reference bytes and provenance unchanged. Use the original differential cases when changing the compatibility plugin and report interpreter-dependent skips.

**Added functionality or operating benefit**

- Register source/runtime version and artifact digest alongside compatibility evidence.
- Keep separate results for source-only fixtures, bytecode comparison and approved live provider tests.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HAR-17-C01 | Verify the archived digest and ensure packaging/cleanup does not delete or overwrite the reference. | [test_gateway.py](../../../dashboard/test_gateway.py) | Read-only artifact inspection; no bytecode execution required for inventory. |
| HAR-17-C02 | Run the differential suite only in its supported interpreter and report incompatible interpreter skips separately. | [test_gateway.py](../../../dashboard/test_gateway.py) | Isolated CPython 3.12; no credentials or network. |

**Migration and compatibility checks**

- Retain the .bin file and README through reorganizations with old-to-new path mapping.
- Do not count historical reconstruction evidence as target release qualification.

**Known limits and review gaps**

- The binary was hashed and its documented role inspected; it was not executed or independently decompiled in this audit.

**Files**

- [taskmgmt/recovered/README.md](../../../taskmgmt/recovered/README.md)
- [taskmgmt/recovered/bedrock_gateway.cpython-312.pyc.bin](../../../taskmgmt/recovered/bedrock_gateway.cpython-312.pyc.bin)

<a id="har-18"></a>
### HAR-18 — Small orchestration acceptance workloads and their tests

**Owner:** P01. **Approach:** retain. **Baseline groups:** BASE-37.

**Current behavior**

- Seven small implementations and seven paired unittest modules cover IPv4 usable-host counts, eight-character digests, duration formatting, English ordinals, bounded shortening, byte formatting and filename slugs.
- Fixtures include IPv4 /31 and /32 behavior, invalid/IPv6 inputs, numeric and suffix boundaries, ellipsis length, binary units and empty/punctuation slug fallback.
- digest8 and its test explicitly preserve a known collision and explain why eight hexadecimal characters cannot guarantee uniqueness for arbitrary bytes.

**Reuse:** Retain these small workloads and their expected results as orchestration/evidence acceptance fixtures. Preserve the intentionally unmet digest uniqueness criterion so a passing suite is not misreported as satisfying an impossible requirement.

**Added functionality or operating benefit**

- Run the same work examples through legacy and target workflows with traceable task, evidence and acceptance records.
- Capture tests that can fail, version/host metadata and total cost/time when later evaluating agent productivity.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HAR-18-C01 | Run each paired test module unchanged as the source baseline and verify target orchestration attaches the actual result and source revision. | [test_cidr.py](../../../orchtest/test_cidr.py), [test_digest8.py](../../../orchtest/test_digest8.py), [test_durations.py](../../../orchtest/test_durations.py), [test_ordinal.py](../../../orchtest/test_ordinal.py), [test_shorten.py](../../../orchtest/test_shorten.py), [test_sizes.py](../../../orchtest/test_sizes.py), [test_slug.py](../../../orchtest/test_slug.py) | Offline Python unittest environment on supported platforms. |
| HAR-18-C02 | Verify the digest collision remains a reported limitation rather than accepted collision-free behavior, even when the regression test passes. | [test_digest8.py](../../../orchtest/test_digest8.py) | Offline Python; owner-side acceptance fixture for an impossible or unmet criterion. |

**Migration and compatibility checks**

- Keep all seven source/test pairs, original task associations where available and historical evidence semantics.
- Do not replace small examples with bigger demos that hide the specific edge cases.

**Known limits and review gaps**

- These are bounded example workloads, not a production benchmark or cryptographic library.
- No unittest was run during this audit.

**Files**

- [orchtest/cidr.py](../../../orchtest/cidr.py)
- [orchtest/digest8.py](../../../orchtest/digest8.py)
- [orchtest/durations.py](../../../orchtest/durations.py)
- [orchtest/ordinal.py](../../../orchtest/ordinal.py)
- [orchtest/shorten.py](../../../orchtest/shorten.py)
- [orchtest/sizes.py](../../../orchtest/sizes.py)
- [orchtest/slug.py](../../../orchtest/slug.py)
- [orchtest/test_cidr.py](../../../orchtest/test_cidr.py)
- [orchtest/test_digest8.py](../../../orchtest/test_digest8.py)
- [orchtest/test_durations.py](../../../orchtest/test_durations.py)
- [orchtest/test_ordinal.py](../../../orchtest/test_ordinal.py)
- [orchtest/test_shorten.py](../../../orchtest/test_shorten.py)
- [orchtest/test_sizes.py](../../../orchtest/test_sizes.py)
- [orchtest/test_slug.py](../../../orchtest/test_slug.py)

<a id="har-19"></a>
### HAR-19 — Historical communication extraction tools

**Owner:** P01. **Approach:** retain-evidence. **Baseline groups:** BASE-09, BASE-10, BASE-37.

**Current behavior**

- Four separate extractors read orchestrator transcripts, raw pane logs, client receipt records and courier/queue/run/claim/journal snapshots.
- They preserve source references, normalized body hashes, sender/recipient, message paths and explicit timestamp basis. Extracted records distinguish typed input, visible arrival, actual client receipt, pending input, modal/death/busy states and courier outcomes.
- Snapshot cutoffs, indexed log lengths, sorted output and a fixed historical timezone prevent growing source logs from silently changing the analysis.
- README documents source locations and schema; generated out/ files are ignored. Paths and some source-version assumptions are specific to the original workstation.

**Reuse:** Preserve the historical scripts and schema as evidence. Derive a separately versioned diagnostic/evaluation tool only when needed, using explicit authorized input paths and target event schemas.

**Added functionality or operating benefit**

- Keep raw-source attribution and confidence/freshness when mapping new NATS/client events into comparable outcomes.
- Add synthetic portable input fixtures so future debugging does not depend on the original user's directories.
- Separate terminal observations from client receipts and accepted work in dashboards and evaluation reports.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HAR-19-C01 | Feed portable synthetic transcript/pane/receipt/courier snapshots and compare normalized records, cutoff handling, partial logs, timezone uncertainty and missing-source diagnostics. | New fixture/review needed; no existing test claimed | Offline Python fixtures; new extraction tests are required. Historical raw snapshots are not assumed available. |
| HAR-19-C02 | Verify input paths remain read-only, generated data stays under an explicit output directory and imported historical observations trigger no message delivery. | New fixture/review needed; no existing test claimed | Offline fixture directories and a filesystem write audit. |

**Migration and compatibility checks**

- Retain original scripts, schema and historical paths as provenance; new tooling must not overwrite historical outputs.
- Do not scan current private client logs merely because an old script contains a path.
- Carry source offsets, hashes, time basis and uncertain identity mappings through later evidence imports.

**Known limits and review gaps**

- The tools were reviewed statically, including constants and main extraction paths; the historical raw snapshot was not reloaded.
- Heuristic pane timing and fuzzy rendering matches do not establish exact receipt or acceptance.
- Scripts contain machine-specific paths and are not ready as general product services.

**Files**

- [analysis/comms-2026-09/README.md](../../../analysis/comms-2026-09/README.md)
- [analysis/comms-2026-09/.gitignore](../../../analysis/comms-2026-09/.gitignore)
- [analysis/comms-2026-09/extract_transcripts.py](../../../analysis/comms-2026-09/extract_transcripts.py)
- [analysis/comms-2026-09/extract_panes.py](../../../analysis/comms-2026-09/extract_panes.py)
- [analysis/comms-2026-09/extract_receipts.py](../../../analysis/comms-2026-09/extract_receipts.py)
- [analysis/comms-2026-09/extract_courier.py](../../../analysis/comms-2026-09/extract_courier.py)

<a id="har-20"></a>
### HAR-20 — Communication correlation, spot checks and determinism history

**Owner:** P01. **Approach:** retain-evidence. **Baseline groups:** BASE-09, BASE-37.

**Current behavior**

- Correlation joins intent, pane, receipt and courier observations using agent/body/time evidence and classifies received, typed-not-submitted, into-modal, deferred-then-received, dead-lettered, lost-silent, wrong-recipient, truncated, duplicated or unknown.
- Spot checks use a fixed sample seed, inspect raw source references and preserve reviewer agreement/disagreement notes.
- Two committed judgment datasets retain first-pass disagreements and the later interpretation; determinism.sh regenerates derived correlation/spot-check outputs twice and compares hashes.

**Reuse:** Keep both judgment histories and existing correlation rules as historical evidence. Add target-specific adapters and portable fixtures alongside them when evaluating new messaging behavior; never rewrite old judgments as current proof.

**Added functionality or operating benefit**

- Use the outcome taxonomy to compare delivery reliability before and after changes.
- Require known source coverage before classifying missing receipts as loss, and preserve unknown results.
- Record analysis version, thresholds and sample provenance for repeatable before/after evaluation.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HAR-20-C01 | Use synthetic matching and nonmatching sources to check wrong recipients, clock skew, truncation, duplicates and missing-source unknowns; compare both judgment passes without deleting disagreements. | New fixture/review needed; no existing test claimed | Offline Python with portable fixture records; add direct correlation regression cases. |
| HAR-20-C02 | Verify repeated analysis yields identical derived hashes on a frozen input set while retaining prior judgment files. | [determinism.sh](../../../analysis/comms-2026-09/determinism.sh) | An isolated copy of a frozen dataset; this script writes derived outputs and is not a read-only command. |

**Migration and compatibility checks**

- Retain source references and both judgment passes with their original names and hashes.
- Run new analysis in a new output location, not against the preserved historical judgment files.
- Do not interpret a deterministic analysis result as proof of semantic correctness.

**Known limits and review gaps**

- The committed JSON structures were inspected but every referenced raw source was not available or rechecked.
- determinism.sh mutates derived output and the current judgment file, so it was not run.
- Correlation uses historical heuristic windows rather than exact distributed tracing.

**Files**

- [analysis/comms-2026-09/correlate.py](../../../analysis/comms-2026-09/correlate.py)
- [analysis/comms-2026-09/spotcheck.py](../../../analysis/comms-2026-09/spotcheck.py)
- [analysis/comms-2026-09/determinism.sh](../../../analysis/comms-2026-09/determinism.sh)
- [analysis/comms-2026-09/spotcheck.judgments.json](../../../analysis/comms-2026-09/spotcheck.judgments.json)
- [analysis/comms-2026-09/spotcheck.pass1.judgments.json](../../../analysis/comms-2026-09/spotcheck.pass1.judgments.json)

<a id="har-21"></a>
### HAR-21 — Recorded orchestration demonstration results

**Owner:** P01. **Approach:** retain-evidence. **Baseline groups:** BASE-37, BASE-01, BASE-09.

**Current behavior**

- Twenty-one JSON records capture calibration, team, cross-repository and swarm demonstrations with agents, work, errors, timelines, verification, checks, statistics and pane tails.
- The scoreboard preserves failures and reports 14 of 21 runs error-free under its E1–E6 definition; the stored JSON result flags agree with that historical total.
- Records expose modal blocks, failed/submitted bell events, outstanding acknowledgments and terminal death alongside work completion.

**Reuse:** Retain every recorded run and the scoreboard unchanged. Use their scenarios and failure examples to define target regressions, keeping new runs in separate versioned records.

**Added functionality or operating benefit**

- Add source/client/broker versions, environment, per-stage outcome and task acceptance evidence to new runs.
- Compare matched legacy/target scenarios without treating old runs or a green aggregate count as current release proof.
- Track recovery effort and accepted result quality as well as time and delivery counts.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HAR-21-C01 | Verify the 21 records remain parseable, every scoreboard row resolves to its original record and failures are retained rather than filtered. | New fixture/review needed; no existing test claimed | Read-only JSON/Markdown evidence inventory; new validation may run offline. |
| HAR-21-C02 | Repeat calibration/team/cross-repository/swarm scenarios in an isolated environment with pinned supported clients and explicit recording of all failed/skipped checks. | [orchestrate.py](../../../hub/demo/orchestrate.py) | Disposable repositories and hub/tmux environments; live agents and paid providers only when separately authorized. |

**Migration and compatibility checks**

- Keep original run IDs, timestamps, source evidence and pass/fail flags; imports must not create live work.
- Place future records under new IDs with source version and environment attribution.
- Preserve pane-tail privacy controls when showing historical results to team viewers.

**Known limits and review gaps**

- These are historical demonstrations, not a reliability estimate for the target platform.
- JSON metadata and result flags were read; no provider claims inside results were reverified.
- No live orchestration was run.

**Files**

- [evals/orchestrations/20260929-221859-calib.json](../../../evals/orchestrations/20260929-221859-calib.json)
- [evals/orchestrations/20260929-222043-team.json](../../../evals/orchestrations/20260929-222043-team.json)
- [evals/orchestrations/20260929-225538-team.json](../../../evals/orchestrations/20260929-225538-team.json)
- [evals/orchestrations/20260929-225924-crossrepo.json](../../../evals/orchestrations/20260929-225924-crossrepo.json)
- [evals/orchestrations/20260929-230317-team.json](../../../evals/orchestrations/20260929-230317-team.json)
- [evals/orchestrations/20260929-230742-swarm.json](../../../evals/orchestrations/20260929-230742-swarm.json)
- [evals/orchestrations/20260929-230935-swarm.json](../../../evals/orchestrations/20260929-230935-swarm.json)
- [evals/orchestrations/20260929-231132-crossrepo.json](../../../evals/orchestrations/20260929-231132-crossrepo.json)
- [evals/orchestrations/20260929-232307-crossrepo.json](../../../evals/orchestrations/20260929-232307-crossrepo.json)
- [evals/orchestrations/20260930-140310-team.json](../../../evals/orchestrations/20260930-140310-team.json)
- [evals/orchestrations/20260930-142203-team.json](../../../evals/orchestrations/20260930-142203-team.json)
- [evals/orchestrations/20261002-094245-calib.json](../../../evals/orchestrations/20261002-094245-calib.json)
- [evals/orchestrations/20261002-094337-team.json](../../../evals/orchestrations/20261002-094337-team.json)
- [evals/orchestrations/20261002-094624-crossrepo.json](../../../evals/orchestrations/20261002-094624-crossrepo.json)
- [evals/orchestrations/20261002-094942-swarm.json](../../../evals/orchestrations/20261002-094942-swarm.json)
- [evals/orchestrations/20261002-095139-calib.json](../../../evals/orchestrations/20261002-095139-calib.json)
- [evals/orchestrations/20261002-095252-team.json](../../../evals/orchestrations/20261002-095252-team.json)
- [evals/orchestrations/20261002-095629-crossrepo.json](../../../evals/orchestrations/20261002-095629-crossrepo.json)
- [evals/orchestrations/20261002-095926-swarm.json](../../../evals/orchestrations/20261002-095926-swarm.json)
- [evals/orchestrations/20261002-100423-swarm.json](../../../evals/orchestrations/20261002-100423-swarm.json)
- [evals/orchestrations/20261002-100651-swarm.json](../../../evals/orchestrations/20261002-100651-swarm.json)
- [evals/orchestrations/SCOREBOARD.md](../../../evals/orchestrations/SCOREBOARD.md)

<a id="har-22"></a>
### HAR-22 — Historical test-gate isolation evidence

**Owner:** P01. **Approach:** retain-evidence. **Baseline groups:** BASE-37, BASE-36.

**Current behavior**

- The recorded five-run exercise verifies that the test gate used a private dashboard/home while operator board reads and a write continued.
- It preserves the first failed residue assertion and the later four passing runs, explaining why the older test expected an operator-server restart and how the regression was corrected.
- The documented failure modes include suite failure, signals, failed server start, differing homes and a changed operator listener.

**Reuse:** Retain this evidence and carry its isolation assertions into the new test harness before running platform or broker failure drills.

**Added functionality or operating benefit**

- Add per-run broker domains/accounts, ports, homes, repository worktrees and cleanup ownership to the same isolation contract.
- Ensure failure drills cannot stop an operator's dashboard, consume real queued work or alter real credentials.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HAR-22-C01 | Verify normal/failure/signal/startup-error paths clean only the test resources and never restart or rewrite the operator's service/home. | [test_residue.sh](../../../dashboard/test_residue.sh), [check_test_residue.sh](../../../dashboard/check_test_residue.sh), [run_tests.sh](../../../dashboard/run_tests.sh) | Disposable test homes/services with a separate sentinel operator service. |
| HAR-22-C02 | Deliberately swap the sentinel listener or leave a test resource and verify the gate fails with evidence. | [test_residue.sh](../../../dashboard/test_residue.sh), [check_test_failability.sh](../../../dashboard/check_test_failability.sh) | Isolated process/port fixtures; no production dashboard or user state. |

**Migration and compatibility checks**

- Preserve the historical report; new test results require fresh run IDs and exact source versions.
- Carry operator/test resource separation into NATS integration tests before enabling them in CI.

**Known limits and review gaps**

- The old five-run result is retained evidence, not a new execution result.
- No dashboard or service was started or stopped.

**Files**

- [evals/gate_isolation/2026-10-01_TM-223.md](../../../evals/gate_isolation/2026-10-01_TM-223.md)

<a id="hub-01"></a>
### HUB-01 — Protocol names and local addresses

**Owner:** P01. **Approach:** retain. **Baseline groups:** BASE-11, BASE-15.

**Current behavior**

- Validates bounded lowercase protocol parts, suggests normalized names and changes them only when explicitly accepted.
- Builds and parses repo-role-agent session names; supports agent, role, cross-repository group, team and virtual addresses.
- Maps current local addresses to core-NATS subjects; direct-agent subjects are independent of the sending node.

**Reuse:** Keep the existing parsers and their refusal cases as the compatibility baseline. Reuse their fixtures in language-neutral contracts; place transport-specific subject mapping behind the compatibility interface.

**Added functionality or operating benefit**

- Add organization, project, instance and generation identity without silently changing existing human-facing aliases.
- Define versioned translation between legacy addresses and authorized NATS operations.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HUB-01-C01 | Round-trip every supported address form; preserve invalid-name suggestions, explicit normalization and refusal of malformed or wildcard-bearing identity tokens. | [test_hub_offline.py](../../../hub/tests/test_hub_offline.py) | Pinned Python and SQLite with FTS5 on native macOS/Linux and Linux filesystems in WSL; isolated temporary homes. |
| HUB-01-C02 | Translate legacy aliases to new identities without collisions across projects or agent generations; compare local and remote recipient selection. | [test_hub_offline.py](../../../hub/tests/test_hub_offline.py) | Pinned Python and SQLite with FTS5 on native macOS/Linux and Linux filesystems in WSL; isolated temporary homes. Two contract SDKs and isolated NATS. |

**Migration and compatibility checks**

- Store the original session/address as an alias with source hub and generation.
- Preserve the difference between role broadcast, first-claim work and team-lead addressing; never infer an organization from a legacy unscoped name.

**Known limits and review gaps**

- Current name and subject grammar is not a tenant security boundary.

**Files**

- [hub/names.py](../../../hub/names.py)

<a id="hub-02"></a>
**P01 isolated additions:** `contracts/v1/README.md`, `contracts/v1/schemas/common.schema.json`, `contracts/v1/schemas/ingress-attestation.schema.json`, `contracts/v1/schemas/message-envelope.schema.json`, `contracts/v1/schemas/operation-context.schema.json`, `contracts/v1/schemas/owner-record.schema.json`, `contracts/v1/schemas/plugin-context.schema.json`, `contracts/v1/schemas/plugin-manifest.schema.json`, `contracts/v1/schemas/protected-assembly.schema.json`. These additions preserve the legacy entry points; full phase qualification remains open.

### HUB-02 — Local hub server, identity, lifecycle and legacy adoption

**Owner:** P05. **Approach:** extract. **Baseline groups:** BASE-09, BASE-10, BASE-11, BASE-16.

**Current behavior**

- An asyncio server sends Store operations to one database executor and blocking process/terminal work to a separate I/O pool.
- Newline JSON over a private Unix socket identifies callers using peer UID and process ancestry; loopback TCP uses hashed operator/agent tokens and ignores caller-supplied impersonation.
- Implements repository and team registration, role overrides, spawn/adopt/kill, inbox/ack, claims, heartbeat, release, cancel, event/mail subscriptions and operator shutdown.
- Adopts a running legacy session without renaming its terminal; imports courier backlog using inode/offset identities and records unresolved recipients.
- Runs doorbell, terminal liveness, receipt/hold-alert, lease, backup and pruning loops; kill/reap calls the harness to clean dashboard sidecars.
- Subscriptions and operator inbox peeks do not claim that an agent received or acknowledged mail; work-result notices also reach the parent holder.

**Reuse:** Extract current routing, lifecycle, delivery and migration logic into owning plugins, retaining a legacy edge adapter during transition. Preserve commands and observed outcomes; route new internal exchanges through NATS. Existing business behavior does not belong in the protected boot kernel.

**Added functionality or operating benefit**

- Replace same-user ancestry as the product-wide identity basis with enrolled scoped callers.
- Separate process death, input receipt, work completion and accepted result; add durable recovery for lifecycle effects.
- Provide bounded authorized event replay and safe cancellation with explicit unknown outcomes.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HUB-02-C01 | Compare every dispatch branch and CLI-visible response/error with captured legacy fixtures, including subscribe framing, operator/agent restrictions and unknown verbs. | [test_hub_offline.py](../../../hub/tests/test_hub_offline.py) | Pinned Python and SQLite with FTS5 on native macOS/Linux and Linux filesystems in WSL; isolated temporary homes. Unix sockets, loopback TCP and Bash. |
| HUB-02-C02 | Rehearse adoption, repeated courier import, unavailable recipients, spawn failure and restart with live agents; preserve one session and one imported message. | [test_hub_offline.py](../../../hub/tests/test_hub_offline.py) | Pinned Python and SQLite with FTS5 on native macOS/Linux and Linux filesystems in WSL; isolated temporary homes. tmux and the installed harness. |
| HUB-02-C03 | Check doorbell-in-flight boundaries, held-input alerts, no-live-lead notices, kill/reap sidecar cleanup and busy-worker behavior on each claimed client. | [test_hub_offline.py](../../../hub/tests/test_hub_offline.py), [smoke_shell.sh](../../../hub/demo/smoke_shell.sh) | Pinned Python and SQLite with FTS5 on native macOS/Linux and Linux filesystems in WSL; isolated temporary homes. tmux; separately qualified agent CLIs. |

**Migration and compatibility checks**

- Import repo/role/team configuration and source aliases before changing routing.
- Fence the former domain writer and record the cutover point; old and new listeners must not both authorize work.
- Preserve pending courier cursors, dead letters, delivery receipt stages, brief-file hashes, open leases and work relationships.
- Migrate token references privately; do not copy secret values into shared NATS records. Preserve the user-selected socket/home and local WSL placement.

**Known limits and review gaps**

- Current socket identity assumes a cooperative local account; it is not multi-user isolation.
- Some loops call broad hub/store methods and must be separated without changing visible behavior.
- Known baseline result-staging and other federation blockers remain owned by P01.

**Files**

- [hub/__init__.py](../../../hub/__init__.py)
- [hub/server.py](../../../hub/server.py)

<a id="hub-03"></a>
### HUB-03 — Hub store, work ownership, messaging and recovery

**Owner:** P04. **Approach:** extract. **Baseline groups:** BASE-08, BASE-09, BASE-11, BASE-15, BASE-16.

**Current behavior**

- Four SQLite migrations define repositories/aliases/paths/groups, agents and legacy names, teams, message kinds/messages/FTS/deliveries, work/parent links, resource claims, audit events and two outbox families.
- Uses WAL, foreign keys, BEGIN IMMEDIATE and one writing connection; rejects Windows-mounted/9p paths for hub.db and takes a backup before schema upgrades.
- Supports sender-scoped idempotent posts, ordered inboxes, explicit receipt/ack/dead states, role/group broadcast and terminal-generation protections.
- Claims work by priority and declared capabilities/CLI, renews leases, releases/blocks/returns results, tracks parent waiting, cancels open children and scopes resource claims by repository.
- Maintains local and federated work identities, source placeholders, event-tail pagination, online backup/rotation and pruning that retains undelivered mail.

**Reuse:** Reuse the domain rules, schema inventory, source IDs and regression assertions. Extract storage access behind owners. Keep the SQLite reader and migration path until parity and recovery pass; build optional SQL query views from authoritative NATS records under STATE-01.

**Added functionality or operating benefit**

- Use conditional owner-side NATS commits and durable operation identity for shared records.
- Retain source ID relationships while separating task ownership, execution attempts and accepted results.
- Add replay/checkpoint recovery without repeating tool effects and fix the recorded backup collision.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HUB-03-C01 | Re-run messaging, work, ownership, FTS, parent/child, cross-process claim, per-repository resource claim, retention and backup fixtures against the legacy store and equivalent target contracts. | [test_hub_offline.py](../../../hub/tests/test_hub_offline.py) | Pinned Python and SQLite with FTS5 on native macOS/Linux and Linux filesystems in WSL; isolated temporary homes. Real NATS for target storage. |
| HUB-03-C02 | Import all schema families twice and compare IDs, counts, bodies/hashes, parent links, flags, audit order and unresolved work; rebuild query indexes without dispatching commands. | [test_hub_offline.py](../../../hub/tests/test_hub_offline.py) | Pinned Python and SQLite with FTS5 on native macOS/Linux and Linux filesystems in WSL; isolated temporary homes. Representative versioned legacy databases and NATS records. |
| HUB-03-C03 | Exercise backup-name collision, pre-migration backup, interrupted cutover, retention gaps and reverse migration after new writes; preserve remote reservations. | [test_hub_offline.py](../../../hub/tests/test_hub_offline.py) | Pinned Python and SQLite with FTS5 on native macOS/Linux and Linux filesystems in WSL; isolated temporary homes. P04/P10/P12 recovery environments. |

**Migration and compatibility checks**

- Export all tables, plugin-owned tables, relevant brief files and schema/application versions consistently; a hub.db copy alone is not a complete platform backup.
- Preserve both nats_outbox and fed_outbox plus fed_seen, fed_audit, fed_quarantine and fed_state; do not restart their delivery as new operations.
- Carry original W IDs, parent/task keys, source node/peer and flags separately from target task/attempt IDs.
- Current local lease expiry may return local work; it must not release an accepted or acceptance-unknown remote reservation.
- After NATS-era commands, rollback requires verified reverse migration and reconciliation, not simply restoring an old SQLite backup.

**Known limits and review gaps**

- STATE-01 changes the authority provider; preserving functionality does not require preserving SQLite as the shared authority.
- Known baseline backup and federation defects require focused regression evidence before progress.
- The existing SQL transaction boundary cannot be assumed across NATS streams, projections and external effects.

**Files**

- [hub/store.py](../../../hub/store.py)

<a id="hub-04"></a>
### HUB-04 — Hub CLI and federation command client

**Owner:** P06. **Approach:** wrap. **Baseline groups:** BASE-11, BASE-12, BASE-36.

**Current behavior**

- Offers daemon lifecycle, identity/status, inbox/ack, work create/list/show/cancel/claim/release/heartbeat, repo/team setup, spawn/adopt/kill, courier import and event subscription.
- Uses Unix sockets or token-authenticated TCP selected by environment; prints human guidance or structured --json results.
- Discovers federation commands from fed_verbs, parses typed/positional arguments including stdin bodies, supports know aliases, and adds the current checkout.
- Creates a federation virtual environment from pinned requirements, chooses an interpreter and starts the hub with a private log.

**Reuse:** Retain command names, argument behavior and output fixtures as a compatibility layer. Translate calls into the new authorized owners through NATS; keep current entry points usable until their replacements qualify.

**Added functionality or operating benefit**

- Add portable enrollment/setup, version negotiation and explicit unsupported capabilities.
- Make client disconnect and ambiguous replies recoverable using durable operation identity.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HUB-04-C01 | Capture and compare help, command parsing, aliases, stdin/body-file, JSON results, refusals and unavailable-hub messages across all commands. | [test_hub_offline.py](../../../hub/tests/test_hub_offline.py), [test_fed_unit.py](../../../hub/tests/test_fed_unit.py) | Pinned Python and SQLite with FTS5 on native macOS/Linux and Linux filesystems in WSL; isolated temporary homes. Bash and a pinned CLI installation. |
| HUB-04-C02 | Check Unix and TCP authentication, --as behavior, long-lived subscriptions and disconnect/reconnect without duplicated work. | [test_hub_offline.py](../../../hub/tests/test_hub_offline.py) | Pinned Python and SQLite with FTS5 on native macOS/Linux and Linux filesystems in WSL; isolated temporary homes. NATS and supported client/WSL-to-desktop arrangements. |

**Migration and compatibility checks**

- Record command and output compatibility changes individually; do not silently reinterpret done as final acceptance.
- Preserve user environment/configuration and secure token-file references.
- Fence old command writers during cutover while allowing an authorized adapter to reach the new owner.

**Known limits and review gaps**

- Existing tests cover representative API calls, not every CLI argument combination; a complete captured command fixture is still required.

**Files**

- [hub/cli.py](../../../hub/cli.py)

<a id="hub-05"></a>
### HUB-05 — Terminal transport abstraction and tmux backend

**Owner:** P06. **Approach:** wrap. **Baseline groups:** BASE-01, BASE-09.

**Current behavior**

- Defines abstract terminal enumeration, liveness, handle, mode, screen capture, text/buffer/key input, output mark and kill operations.
- The tmux implementation uses literal text or stdin-loaded bracketed paste, validates abstract keys and separates copy/dead modes.
- Uses pipe-pane log growth as an output signal; includes scripted FakeTransport for offline delivery tests.

**Reuse:** Keep the current abstraction and tmux backend as the first execution adapter. Expose scoped plugin operations around them; reuse FakeTransport for deterministic contract tests.

**Added functionality or operating benefit**

- Add instance/generation binding, cancellation and declared backend capabilities.
- Permit other qualified backends without changing delivery or task contracts.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HUB-05-C01 | Preserve literal text, large/multiline buffer, abstract-key refusal, copy mode, dead pane and handle-mismatch behavior using fake and actual tmux fixtures. | [test_hub_offline.py](../../../hub/tests/test_hub_offline.py) | Pinned Python and SQLite with FTS5 on native macOS/Linux and Linux filesystems in WSL; isolated temporary homes. tmux. |
| HUB-05-C02 | Verify cancellation and reconnect never send input to a reused pane handle or kill an unrelated session; preserve output-log progress signals. | [test_hub_offline.py](../../../hub/tests/test_hub_offline.py) | Pinned Python and SQLite with FTS5 on native macOS/Linux and Linux filesystems in WSL; isolated temporary homes. tmux and target execution adapter. |

**Migration and compatibility checks**

- Keep socket selection, actual adopted terminal names, handle/PID generation and log references distinct from stable agent identity.
- Do not stop shared transport infrastructure when one plugin instance is removed.

**Known limits and review gaps**

- Only tmux is currently a real implementation; FakeTransport does not prove another backend or native Windows support.

**Files**

- [hub/transport.py](../../../hub/transport.py)

<a id="hub-06"></a>
### HUB-06 — CLI screen profiles and guarded terminal input

**Owner:** P06. **Approach:** extract. **Baseline groups:** BASE-01, BASE-09.

**Current behavior**

- Codex, Claude, Grok and shell profiles recognize readiness, busy markers, paste placeholders, startup timing, modals and doorbell text.
- Delivery records resolved/mode/modal/ready/typed/submitted stages, validates handles, exits copy mode, defers busy/booting panes and blocks unknown or login prompts.
- Known menu choices use labels where available; stale submitted text is retried without retyping, retries are spaced, and a newly appearing modal prevents Enter.
- Shell doorbells use an executable inbox command; agent-client profiles have distinct measured timing behavior.

**Reuse:** Extract these existing profiles and delivery mechanics into the terminal client adapter; retain their screen fixtures and detailed receipt stages.

**Added functionality or operating benefit**

- Version profiles by supported client releases; surface unsupported screens rather than inventing success.
- Apply explicit task/client policy to any automatic trust or permission consent before input is sent.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HUB-06-C01 | Compare every existing scripted screen case, including non-modal update banners, reordered consent choices, unknown prompts, busy state, boot state and unsubmitted paste recovery. | [test_hub_offline.py](../../../hub/tests/test_hub_offline.py) | Pinned Python and SQLite with FTS5 on native macOS/Linux and Linux filesystems in WSL; isolated temporary homes. |
| HUB-06-C02 | On each supported real client version, check receipt stages, interruption, changed prompts and bounded retries without accidental update, exit or extra task execution. | [test_hub_offline.py](../../../hub/tests/test_hub_offline.py) | Pinned Python and SQLite with FTS5 on native macOS/Linux and Linux filesystems in WSL; isolated temporary homes. tmux and approved provider accounts. |

**Migration and compatibility checks**

- Preserve selected profile and stage evidence for active deliveries.
- Treat existing auto-consent behavior as a separately reviewed policy decision; do not grant new permissions merely to reproduce a screen fixture.

**Known limits and review gaps**

- Screen recognition is version-sensitive and does not prove that a model received, executed or accepted work.

**Files**

- [hub/profiles.py](../../../hub/profiles.py)
- [hub/deliver.py](../../../hub/deliver.py)

<a id="hub-07"></a>
### HUB-07 — Native client receipt scanning and hold evidence

**Owner:** P06. **Approach:** retain. **Baseline groups:** BASE-09, BASE-10.

**Current behavior**

- Parses supported Codex, Claude and Grok JSONL user-turn formats; ignores assistant text and Claude sidechains.
- Tails by inode/offset, starts existing files at EOF, handles partial lines and rotated/truncated files, and joins split Grok chunks.
- Matches hub doorbells to recipient sessions and returns source file/offset evidence for the hub's received/held states.

**Reuse:** Reuse the format parsers and fixtures as an optional receipt capability of each client adapter. Keep provenance and receipt semantics explicit.

**Added functionality or operating benefit**

- Bind receipt evidence to enrolled client/session generations and declared read scope.
- Add client-version qualification and an honest unavailable state when a host exposes no usable log.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HUB-07-C01 | Preserve each user-turn format, EOF priming, assistant exclusion, split chunks, partial lines and one-time incremental observations. | [test_hub_offline.py](../../../hub/tests/test_hub_offline.py) | Pinned Python and SQLite with FTS5 on native macOS/Linux and Linux filesystems in WSL; isolated temporary homes. |
| HUB-07-C02 | Test log rotation and session reuse together with a pending bell so old or quoted content cannot acknowledge a different operation. | [test_hub_offline.py](../../../hub/tests/test_hub_offline.py) | Pinned Python and SQLite with FTS5 on native macOS/Linux and Linux filesystems in WSL; isolated temporary homes. Representative supported client logs. |

**Migration and compatibility checks**

- Carry pending delivery identity and source cursor policy through adapter restart; do not rescan history as new acknowledgments.
- Preserve privacy and local log paths as scoped references rather than exporting whole client conversations.

**Known limits and review gaps**

- Native logs cover only supported observable formats; they do not expose all conversation events or hidden reasoning.

**Files**

- [hub/receipts.py](../../../hub/receipts.py)

<a id="hub-08"></a>
### HUB-08 — Existing core-NATS bridge

**Owner:** P10. **Approach:** wrap. **Baseline groups:** BASE-13.

**Current behavior**

- Provides a small standard-library NATS text client with bounded connect/INFO timeout, subscriptions, queue groups, publish and reconnect backoff.
- Routes direct messages, dynamically subscribed role work and results between a single operator's hubs.
- Drains nats_outbox after socket writes and uses store-level idempotency for incoming message/work records.

**Reuse:** Keep the legacy bridge isolated as a compatibility boundary while the supported NATS client and durable federation path qualify. Reuse routing and timeout fixtures; preserve old queued obligations before any retirement.

**Added functionality or operating benefit**

- Move new shared work to authenticated, durable, versioned NATS contracts and separate acceptance from result receipt.
- Provide deliberate coexistence or drain/cutover rules for core bridge and JetStream federation.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HUB-08-C01 | Re-run two-node direct messaging and role-work/result round trips; preserve address translation and bounded failure on a silent endpoint. | [test_hub_offline.py](../../../hub/tests/test_hub_offline.py), [test_nats_federation.py](../../../hub/tests/test_nats_federation.py) | Pinned Python and SQLite with FTS5 on native macOS/Linux and Linux filesystems in WSL; isolated temporary homes. Isolated real NATS and two hubs. |
| HUB-08-C02 | Stop either bridge during publish or result receipt, migrate pending nats_outbox records, and prove no obligation is lost or dispatched twice. | [test_nats_federation.py](../../../hub/tests/test_nats_federation.py) | Isolated macOS/Linux/WSL hubs, pinned Python federation dependencies, nsc, Git and a real NATS server; use separate test accounts and stores. |

**Migration and compatibility checks**

- Identify which flow owns each work item when both nats_url and federation are configured; preserve nats:federated placeholders and node:work origin IDs.
- Drain or import pending bridge messages before disabling subscriptions; map subjects and operation IDs explicitly.
- Any retirement requires a reviewed record, passing comparison and recovery evidence; no file removal is approved by this inventory.

**Known limits and review gaps**

- writer.drain is not a JetStream durable acknowledgment.
- The current client does not implement the target authenticated/TLS/JetStream feature set; its source comments do not establish end-to-end exactly-once execution.

**Files**

- [hub/bridge.py](../../../hub/bridge.py)

<a id="hub-09"></a>
### HUB-09 — Existing federation plugin contract and package structure

**Owner:** P03. **Approach:** extend. **Baseline groups:** BASE-13, BASE-14.

**Current behavior**

- Defines Param and Verb metadata, required/positional/type/help fields and operator-only flags reused by CLI/MCP.
- Defines plugin name, envelope handlers, prefixed tables, start/connect/tick/envelope/local-event/revoke hooks and dashboard panels.
- Current built-ins are Python PLUGIN instances loaded into one process; empty package initializers preserve import paths.

**Reuse:** Use the existing plugin contract as the migration input, not a blank slate. Map Param/Verb to versioned contribution schemas, handles/on_envelope to authorized NATS subscriptions, lifecycle hooks to supervision, panel to registered UI contributions, and tables/context access to owned storage contracts.

**Added functionality or operating benefit**

- Add language-neutral manifests and SDKs, scoped PluginContext/OperationContext, nested independent/private children and dependency/version checks.
- Prevent direct access to another plugin's database, connection or mutable current-user state; keep ordinary capabilities outside the protected boot kernel.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HUB-09-C01 | Run each of the five built-in plugins through a compatibility adapter and compare its verbs, parameters, events and panel data with the existing registry. | [test_fed_unit.py](../../../hub/tests/test_fed_unit.py), [test_fed_live.py](../../../hub/tests/test_fed_live.py) | Isolated macOS/Linux/WSL hubs, pinned Python federation dependencies, nsc, Git and a real NATS server; use separate test accounts and stores. |
| HUB-09-C02 | Qualify two language SDKs for lifecycle cleanup, nested ownership, scope narrowing, duplicated handlers and dependency failure while preserving the built-in workflows. | New fixture/review needed; no existing test claimed | P03 plugin conformance harness, two SDK languages and isolated NATS. |

**Migration and compatibility checks**

- Maintain a one-to-one mapping for every existing hook/verb/panel/table contribution and record any unsupported field.
- Preserve trusted installed extension entry points until a reviewed adapter or migration is available; detect unsupported modules explicitly.
- A broader new framework does not authorize replacing working built-in business logic without an evidenced reason.

**Known limits and review gaps**

- The current context exposes the hub/store and is not a security sandbox or language-neutral process contract.
- New conformance and nested-plugin tests do not exist yet.

**Files**

- [hub/fed/__init__.py](../../../hub/fed/__init__.py)
- [hub/fed/plugin.py](../../../hub/fed/plugin.py)
- [hub/fed/plugins/__init__.py](../../../hub/fed/plugins/__init__.py)

<a id="hub-10"></a>
### HUB-10 — Federation runtime, supervision, control and observations

**Owner:** P10. **Approach:** extract. **Baseline groups:** BASE-13, BASE-14, BASE-16.

**Current behavior**

- Loads five built-ins or configured module plugins, registers their verbs/routes and initializes prefixed tables.
- Connects/reconnects JetStream, binds per-peer/node message/share durables, invokes plugin hooks, stages audited outbox records and acknowledges ingested envelopes.
- Tracks presence/capability advertisements, shared-repository aliases, counters, last errors, peers and composite dashboard panels.
- Offers share/unshare/trust/status/peers/quarantine/approve/deny/audit/gate/kill/resume operations; kill state persists locally and revoke withdraws unsent work and notifies connected peers.

**Reuse:** Extract transport/lifecycle, policy, collaboration and observation responsibilities around the existing runtime. Retain core verbs, plugin hooks and data contracts through adapters; improve the recorded unsafe boundaries instead of reproducing them.

**Added functionality or operating benefit**

- Add durable revocations, explicit scoped trust agreements, independent hub domains, origin-owned acceptance and disconnected reservation recovery.
- Replace raw shared context with injected scoped handles and authenticated operation context.
- Add supervised failure states and authorized AG-UI observations from the same recorded events.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HUB-10-C01 | Compare plugin loading, verb schemas, reconnect callbacks, counters, presence, peer alias resolution and composite panels for all configured built-ins. | [test_fed_unit.py](../../../hub/tests/test_fed_unit.py), [test_fed_live.py](../../../hub/tests/test_fed_live.py) | Isolated macOS/Linux/WSL hubs, pinned Python federation dependencies, nsc, Git and a real NATS server; use separate test accounts and stores. |
| HUB-10-C02 | Capture legacy durable positions and outbox/seen/quarantine/kill state, interrupt publish/ingest/revoke, then resume or migrate without duplicate effects or lost pending review. | [test_fed_live.py](../../../hub/tests/test_fed_live.py) | Isolated macOS/Linux/WSL hubs, pinned Python federation dependencies, nsc, Git and a real NATS server; use separate test accounts and stores. Partition and fault injection. |
| HUB-10-C03 | Run existing same-peer multi-node and subject/type/result-binding regressions plus three independent hubs; preserve accepted and uncertain reservations while disconnected. | [test_fed_live.py](../../../hub/tests/test_fed_live.py) | Isolated macOS/Linux/WSL hubs, pinned Python federation dependencies, nsc, Git and a real NATS server; use separate test accounts and stores. P01 defect fixtures and P10 independent domains. |

**Migration and compatibility checks**

- Map msg_<peer>_<node>, share_<peer>_<node> and work_<from>_<rid>_<role> consumer names/ack positions explicitly.
- Preserve policy/primary-node settings and the meaning of killed, withdrawn, held, approved and denied states.
- Translate envelope IDs and pending result obligations before changing streams/accounts; never equate a historical result with newly approved work.
- Preserve legacy panel contributions via the UI adapter until equivalent authorized views pass.

**Known limits and review gaps**

- Current revocation notices use transient core NATS and can be missed by disconnected peers.
- Known baseline transaction, subject/dispatch, same-peer and result-binding findings remain unresolved.
- Current runtime is central-circle federation, not independent leaf-node authority.

**Files**

- [hub/fed/runtime.py](../../../hub/fed/runtime.py)

<a id="hub-11"></a>
### HUB-11 — Federation configuration, trust and repository identity

**Owner:** P01. **Approach:** extend. **Baseline groups:** BASE-13, BASE-15, BASE-16.

**Current behavior**

- Reads/writes federation TOML with explicit opt-in, plugin list, connection/credential references, capture/notification settings and per-repository/per-peer policy.
- Normalizes Git remotes into stable r-prefixed repository IDs, maps different local repo names, supports board prefixes and default approve trust.
- Defines v2 envelope identity, message types, subject grammar and type-to-plane mappings.

**Reuse:** Retain the existing repository identity and configuration fixtures. Wrap the v2 envelope at a versioned boundary; extend rather than silently reinterpret fields.

**Added functionality or operating benefit**

- Add organization/project/task/delegation/attempt/operation/schema/trace identity and deterministic subject/type/recipient validation.
- Translate broad circle trust into explicit scoped agreements and managed credential references.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HUB-11-C01 | Round-trip configuration and permissions, compare remote URL forms and local aliases, preserve sharing defaults and reject malformed IDs/envelopes. | [test_fed_unit.py](../../../hub/tests/test_fed_unit.py) | Pinned Python and SQLite with FTS5 on native macOS/Linux and Linux filesystems in WSL; isolated temporary homes. |
| HUB-11-C02 | Reject mismatched plane/type/recipient/account and unsupported versions; translate valid legacy envelopes without losing sender, source node, repository or original ID. | [test_fed_unit.py](../../../hub/tests/test_fed_unit.py), [test_fed_live.py](../../../hub/tests/test_fed_live.py) | Isolated macOS/Linux/WSL hubs, pinned Python federation dependencies, nsc, Git and a real NATS server; use separate test accounts and stores. New versioned contract fixtures. |

**Migration and compatibility checks**

- Preserve rid mappings rather than recomputing them with a changed normalization rule during import.
- Import per-peer trust, wildcard defaults, shared repo peer lists, board prefixes, capture, primary and notify settings with a reviewable diff.
- Keep secrets outside ordinary shared configuration records; map paths to private provider references.

**Known limits and review gaps**

- Current envelope validation is incomplete for the new trust model; AMX-BASE-001 remains active.
- Legacy normalizations and local names are compatibility identifiers, not proof that two independently administered projects may share data.

**Files**

- [hub/fed/config.py](../../../hub/fed/config.py)
- [hub/fed/policy.py](../../../hub/fed/policy.py)
- [hub/fed/envelope.py](../../../hub/fed/envelope.py)

<a id="hub-12"></a>
### HUB-12 — Federation guard and outbound secret filtering

**Owner:** P04. **Approach:** extend. **Baseline groups:** BASE-13, BASE-14.

**Current behavior**

- Outbound guards verify sharing, recursively scrub string values, block private keys/nkey seeds/NATS credentials and enforce payload size.
- Inbound guards compare subject sender with envelope sender, check sharing/trust, quarantine privileged remote work and distinguish informational planes.
- Wraps remote text as attributed data; audit records receive redaction kinds rather than secret values.

**Reuse:** Reuse pure guard/filter functions and their fixtures as the starting policy implementation. Keep their checks at the owning boundaries and expand coverage for new account/project contracts.

**Added functionality or operating benefit**

- Add complete subject/type/target binding and per-project authorization before dispatch.
- Separate semantic Jev advice from deterministic authorization; evaluate derived data and artifact export separately from text filtering.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HUB-12-C01 | Preserve clean payloads and nested filtering; confirm blocked keys never publish and redacted secret values do not appear in audit or diagnostics. | [test_fed_unit.py](../../../hub/tests/test_fed_unit.py), [test_fed_live.py](../../../hub/tests/test_fed_live.py) | Isolated macOS/Linux/WSL hubs, pinned Python federation dependencies, nsc, Git and a real NATS server; use separate test accounts and stores. |
| HUB-12-C02 | Exercise every trust level, unshared repository, spoofed sender, inconsistent envelope plane and privileged-work condition through real broker identities. | [test_fed_unit.py](../../../hub/tests/test_fed_unit.py), [test_fed_live.py](../../../hub/tests/test_fed_live.py) | Isolated macOS/Linux/WSL hubs, pinned Python federation dependencies, nsc, Git and a real NATS server; use separate test accounts and stores. |

**Migration and compatibility checks**

- Record guard policy versions alongside migrated decisions and pending quarantine entries.
- Do not automatically broaden auto/flag/approve/deny grants during account changes.
- Keep previously attributed remote content marked as remote data after UI or storage migration.

**Known limits and review gaps**

- Pattern-based filtering can miss new secret formats and cannot scrub the Git content behind a code pointer.
- Remote-data framing is model guidance; it does not enforce authorization.
- Existing guard defects require P01 repairs before target parity can claim safe equivalence.

**Files**

- [hub/fed/guard.py](../../../hub/fed/guard.py)
- [hub/fed/redact.py](../../../hub/fed/redact.py)

<a id="hub-13"></a>
### HUB-13 — Privileged remote-work host hook

**Owner:** P11. **Approach:** wrap. **Baseline groups:** BASE-35.

**Current behavior**

- Claude Code PreToolUse recognizes selected PCM import, CODESYS write/force/script and PROFINET/BOOTP/PCM600 command surfaces.
- Queries fed_gate for current remote-origin work and denies selected privileged calls without privileged approval.
- Denies on unavailable hub when federation is enabled; emits the host's permission-denial structure.

**Reuse:** Keep the current hook as one host adapter and regression fixture. Move authoritative target/action/grant checks into the owning tool plugin so other clients receive the same protection.

**Added functionality or operating benefit**

- Add host/version capability declarations and explicit equipment-operation authority.
- Preserve the distinction between approving remote work and approving a privileged action.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HUB-13-C01 | Preserve harmless-tool allowance, privileged remote-work denial, approved-work behavior and federation-enabled hub-failure denial. | [test_fed_unit.py](../../../hub/tests/test_fed_unit.py) | Pinned Python and SQLite with FTS5 on native macOS/Linux and Linux filesystems in WSL; isolated temporary homes. Mocked hook input; real Claude hook qualification separately. |
| HUB-13-C02 | Invoke each owned industrial operation through CLI, MCP and dashboard paths and show that bypassing an optional host hook cannot bypass endpoint authorization. | New fixture/review needed; no existing test claimed | P04/P06/P11 tool-owner fixtures and supported host versions; simulators before controlled hardware. |

**Migration and compatibility checks**

- Import approval provenance and bind it to the exact task/attempt/target/action; do not copy a boolean into a general permission.
- Preserve hook installation/configuration without overwriting unrelated user hooks.

**Known limits and review gaps**

- Name matching covers only recognized surfaces and is not universal enforcement or a complete ABB/PCM600 adapter.

**Files**

- [hub/fed/hooks/__init__.py](../../../hub/fed/hooks/__init__.py)
- [hub/fed/hooks/privileged_gate.py](../../../hub/fed/hooks/privileged_gate.py)

<a id="hub-14"></a>
### HUB-14 — Federation outbox, idempotency, audit and quarantine ledger

**Owner:** P04. **Approach:** extract. **Baseline groups:** BASE-13, BASE-16.

**Current behavior**

- Records unique message IDs, ordered pending outbox records, attempts/errors/sent/withdrawn state and persistent seen IDs.
- Hashes and sizes inbound/outbound payloads for audit with decisions/reasons and peer/repository/subject attribution.
- Stores held envelopes, approval/denial actor/time and persistent local runtime state.

**Reuse:** Reuse record semantics, identifiers and transaction-intent behavior behind a storage-owner interface. Keep the SQLite ledger reader for import and compare all fields with new NATS-backed records.

**Added functionality or operating benefit**

- Make operation outcomes and unsent intent recoverable after crash, deduplication-window expiry and restore.
- Retain audit/quarantine history independently from work-queue acknowledgments and derived views.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HUB-14-C01 | Import pending, sent, failed and withdrawn outbox entries plus seen IDs twice; no duplicate dispatch or revival of withdrawn work is allowed. | [test_fed_live.py](../../../hub/tests/test_fed_live.py) | Isolated macOS/Linux/WSL hubs, pinned Python federation dependencies, nsc, Git and a real NATS server; use separate test accounts and stores. Versioned legacy ledger fixtures. |
| HUB-14-C02 | Compare audit hashes, decisions, order and quarantine approval provenance before and after restart, cutover and query-view rebuild. | [test_fed_unit.py](../../../hub/tests/test_fed_unit.py), [test_fed_live.py](../../../hub/tests/test_fed_live.py) | Isolated macOS/Linux/WSL hubs, pinned Python federation dependencies, nsc, Git and a real NATS server; use separate test accounts and stores. Recovery fixtures. |

**Migration and compatibility checks**

- Preserve original envelope IDs, payload hashes, sequence/source identity, attempt errors and approval actors.
- Quarantine records retain the original envelope and the policy under which they were held; new policy must revalidate release.
- Do not expire unresolved operations or seen IDs merely because the broker's duplicate window elapsed.

**Known limits and review gaps**

- Existing integration tests cover parts of this behavior; complete ledger migration/fault fixtures are still required.
- The ledger alone cannot repair a caller that commits business state and outbox intent separately.

**Files**

- [hub/fed/ledger.py](../../../hub/fed/ledger.py)

<a id="hub-15"></a>
### HUB-15 — NATS connection, storage layout and administration API

**Owner:** P02. **Approach:** extend. **Baseline groups:** BASE-13, BASE-16, BASE-36.

**Current behavior**

- Uses lazy nats-py loading, credential files, optional custom CA, explicit connection timeout/retry policy and bounded close handling.
- Declares AM_MSG, AM_WORK and AM_SHARE retention, duplicate window, am_board revision history and expiring am_presence.
- Provisioning creates/updates file-backed replicated streams and creates missing KV buckets; admin push publishes account JWT changes through the system account.

**Reuse:** Reuse the supported client wrapper, central layout declaration and provisioning entry points. Version storage profiles and make new lifecycle/authorization limits explicit.

**Added functionality or operating benefit**

- Add local/team/independent-domain profiles and qualify required NATS APIs in P01 before production use.
- Add storage limits, freshness, checkpoint, backup and artifact contracts under STATE-01.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HUB-15-C01 | Provision an isolated installation twice; verify exact stream subjects, retention, replicas, duplicate window and KV history/TTL, then compare the approved target profile. | [test_fed_live.py](../../../hub/tests/test_fed_live.py) | Isolated macOS/Linux/WSL hubs, pinned Python federation dependencies, nsc, Git and a real NATS server; use separate test accounts and stores. |
| HUB-15-C02 | Test absent dependencies, wrong CA/endpoint, missing credentials, revoked account and interrupted provisioning with bounded and actionable failure. | [test_fed_live.py](../../../hub/tests/test_fed_live.py) | Isolated macOS/Linux/WSL hubs, pinned Python federation dependencies, nsc, Git and a real NATS server; use separate test accounts and stores. TLS and system-account test credentials. |

**Migration and compatibility checks**

- Capture old stream/consumer/bucket names, policies, revisions and outstanding work before changing layouts.
- Do not let a routine upgrade alter retention or replicas without recorded migration/recovery evidence.
- Existing KV buckets are not automatically reconciled by provision; detect policy differences explicitly.
- Never run test reset or stream deletion against customer data.

**Known limits and review gaps**

- Current layout has no Object Store, independent domain configuration or complete storage qualification.
- Pinning a server/client version does not prove atomicity, durability or recovery promises.

**Files**

- [hub/fed/conn.py](../../../hub/fed/conn.py)
- [hub/fed/admin.py](../../../hub/fed/admin.py)

<a id="hub-16"></a>
### HUB-16 — Federation messages and handoffs plugin

**Owner:** P10. **Approach:** extract. **Baseline groups:** BASE-13.

**Current behavior**

- Parses peer/operator, peer/repository/role and peer/repository/role/agent addresses.
- Publishes note/request/reply/handoff messages with sender identity, task/code references and optional automatic handoff capture.
- Translates repository names through rid/presence, frames remote data, supplies reply pointers and falls back to an operator when a target is absent.
- Uses envelope-based local idempotency and primary-node behavior to avoid treating every node as the operator's inbox.

**Reuse:** Retain parsing, translation, message formatting and fallback logic in a collaboration plugin. Replace direct hub/store calls with scoped messaging and lookup contracts.

**Added functionality or operating benefit**

- Add durable delivery/receipt status across independent hubs and authorize every source/recipient project.
- Bind messages to enrolled identities and operation generations.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HUB-16-C01 | Compare direct, role and operator delivery, peer-local alias replies, code-linked handoffs, missing-recipient fallback and trust framing. | [test_fed_live.py](../../../hub/tests/test_fed_live.py) | Isolated macOS/Linux/WSL hubs, pinned Python federation dependencies, nsc, Git and a real NATS server; use separate test accounts and stores. |
| HUB-16-C02 | Deliver duplicates across nodes and after reconnect; preserve one intended local message and original task/code/ref provenance. | [test_fed_live.py](../../../hub/tests/test_fed_live.py) | Isolated macOS/Linux/WSL hubs, pinned Python federation dependencies, nsc, Git and a real NATS server; use separate test accounts and stores. Same-peer multi-node and partition fixtures. |

**Migration and compatibility checks**

- Preserve envelope IDs, local fed:<id> idempotency keys, message kinds, sender/target mapping and pending recipient state.
- Keep old reply addresses usable through explicit aliases for the supported compatibility window.

**Known limits and review gaps**

- Current primary-node and multi-node behavior needs explicit target ownership tests; source comments are not proof of correct cross-node delivery.

**Files**

- [hub/fed/plugins/messages.py](../../../hub/fed/plugins/messages.py)

<a id="hub-17"></a>
### HUB-17 — Federated work distribution and result plugin

**Owner:** P10. **Approach:** extend. **Baseline groups:** BASE-13, BASE-15.

**Current behavior**

- Creates a local fed:pending origin placeholder and stages work by publisher/repository/role.
- Pulls shared durable work only for locally available role capacity and allowed publishers; keeps requirements, priority and task_key.
- Ingests attributed remote work, handles local self-pickup, returns done/failed results, reports pending/incoming items and cancels unclaimed work on revoke.

**Reuse:** Reuse capability/capacity routing, task metadata and existing happy-path fixtures. Extend the current work plugin around explicit offer/accept/reserve/execute/result/acceptance records; repair known provenance and result boundaries first.

**Added functionality or operating benefit**

- Bind delegation to executor, project/repository, task version and attempt; origin keeps final acceptance.
- Preserve accepted or acceptance-unknown work during disconnection and require explicit reassignment.
- Allow receiving-hub automation only within approved rules; Jev may rank eligible options without granting authority.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HUB-17-C01 | Compare role capacity, requirements, priority, task links, incoming/outgoing lists, creator notices and revocation of unclaimed work. | [test_fed_live.py](../../../hub/tests/test_fed_live.py) | Isolated macOS/Linux/WSL hubs, pinned Python federation dependencies, nsc, Git and a real NATS server; use separate test accounts and stores. |
| HUB-17-C02 | Inject all six relevant baseline/future failure boundaries: mismatched subject/type, split provenance, completion-before-publication, same-peer consumption, wrong executor/result and lost acceptance acknowledgment. | [test_fed_live.py](../../../hub/tests/test_fed_live.py) | Isolated macOS/Linux/WSL hubs, pinned Python federation dependencies, nsc, Git and a real NATS server; use separate test accounts and stores. P01 regression fixtures and P10 fault injection. |
| HUB-17-C03 | Disconnect a receiving hub after acceptance, continue allowed work and reconcile after reconnect or older-origin restore without overlapping execution. | New fixture/review needed; no existing test claimed | Three actual hubs across two test organizations with independent persistence and leaf links. |

**Migration and compatibility checks**

- Map W IDs, origin_id, env, rid, origin_peer, claimed_by, fed_flags and task_key explicitly; retain legacy IDs as source identities.
- Migrate work consumer ack positions with local ready/claimed/pending state and result outbox intent as one checked cutover set.
- Preserve already accepted obligations even when policy expires; quarantining historical results must not erase the reservation.
- Record the deliberate behavior change: receiving-worker done is a submitted result until the origin accepts it.

**Known limits and review gaps**

- AMX-BASE-002–005 identify existing provenance, result and multi-node defects; parity must preserve intended capability rather than reproduce those defects.
- The current workqueue is not the target reservation/acceptance protocol.

**Files**

- [hub/fed/plugins/work.py](../../../hub/fed/plugins/work.py)

<a id="hub-18"></a>
### HUB-18 — Shared board plugin and local mirror

**Owner:** P10. **Approach:** extend. **Baseline groups:** BASE-14, BASE-15.

**Current behavior**

- Stores cards under <rid>.card.<KEY> in am_board and mints prefix-specific sequence keys with compare-and-set.
- Provides add/list/show/move/assign/comment/claim, with title/body/labels/assignee/comments/history and a local-board source link.
- Watches KV into p_board_cards for offline reads, ignores stale revisions, marks deletions, filters denied peers and notifies a newly assigned recipient.
- Reads local TM cards through the current dashboard endpoint and contributes shared-board rows/actions to the dashboard.

**Reuse:** Reuse card operations, CAS conflict handling, data shapes, mirror rules and assignment notices. Route local-card lookup and writes through authorized owning plugins while adapting the existing view contribution.

**Added functionality or operating benefit**

- Add explicit board ownership and project access, retained history beyond bounded KV revisions and documented offline freshness.
- Keep shared-board cards distinct from origin tasks and execution attempts while linking them.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HUB-18-C01 | Compare key minting, simultaneous comments, claim conflicts, status validation, assignments and notification translation across differing local repository names. | [test_fed_live.py](../../../hub/tests/test_fed_live.py) | Isolated macOS/Linux/WSL hubs, pinned Python federation dependencies, nsc, Git and a real NATS server; use separate test accounts and stores. |
| HUB-18-C02 | Rebuild offline mirrors from retained source state including deleted cards and stale revisions; retain comments, history and local TM links without emitting assignment notices again. | [test_fed_live.py](../../../hub/tests/test_fed_live.py) | Isolated macOS/Linux/WSL hubs, pinned Python federation dependencies, nsc, Git and a real NATS server; use separate test accounts and stores. Snapshot, retention-gap and replay fixtures. |

**Migration and compatibility checks**

- Import am_board card keys and sequence counters, card revisions, p_board_cards tombstones and observed watermark together.
- Never renumber SH/custom-prefix keys or collapse board done into accepted work.
- Replace the local HTTP card lookup with a NATS owner contract while preserving --from semantics and explicit unavailable-card errors.
- Any move away from the shared central-board write model needs a separate ownership decision and conflict migration plan before cutover.

**Known limits and review gaps**

- KV history is bounded and card history is truncated to 50 entries; missing historical data must be reported, not reconstructed as fact.
- Existing direct bucket permissions do not provide the planned project authorization.

**Files**

- [hub/fed/plugins/board.py](../../../hub/fed/plugins/board.py)

<a id="hub-19"></a>
### HUB-19 — Shared knowledge, offline search, capture and notifications

**Owner:** P10. **Approach:** extract. **Baseline groups:** BASE-14.

**Current behavior**

- Publishes explicit title/body/tags/ref findings with author, source, repository and trust attribution.
- Indexes p_knowledge_items and FTS5 for ranked offline search with snippets, recent/show views and dashboard rows.
- Automatically captures local completed-work results, handoffs and returned federated results when capture is enabled.
- Notifies live agents of new findings using a one-line pointer and idempotent notice; marks a peer's findings withdrawn on revoke.

**Reuse:** Keep the knowledge record schema, explicit capture triggers, search behavior and notification controls. Extract database access into an authorized projection/index service; keep SQL FTS as a rebuildable option where it remains useful.

**Added functionality or operating benefit**

- Add scoped source provenance, authorization-aware search and controlled onward sharing.
- Allow optional Jev classification/selection without replacing lexical search, hiding mandatory notices or exporting unapproved data.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HUB-19-C01 | Compare explicit share, ranked multiword search/snippets, recent/show, differing local repo names, trust/withdrawn flags and the panel. | [test_fed_live.py](../../../hub/tests/test_fed_live.py) | Isolated macOS/Linux/WSL hubs, pinned Python federation dependencies, nsc, Git and a real NATS server; use separate test accounts and stores. SQLite FTS5 for the current projection. |
| HUB-19-C02 | Trigger each auto:work, auto:handoff and auto:result path; verify capture=false and notify_findings=false, one-line notices and duplicate/replay suppression. | [test_fed_live.py](../../../hub/tests/test_fed_live.py) | Isolated macOS/Linux/WSL hubs, pinned Python federation dependencies, nsc, Git and a real NATS server; use separate test accounts and stores. New targeted capture/notification fixtures. |
| HUB-19-C03 | Rebuild the search index from retained authorized records with the same IDs and queryable bodies; revocation must constrain later access and derived use. | New fixture/review needed; no existing test claimed | P04/P10 retained-record and projection recovery environment. |

**Migration and compatibility checks**

- Preserve finding IDs, author/source/ref/tags, timestamps, trust/untrusted/withdrawn state and existing local-repository mapping.
- Do not treat imported historical completion/handoff records as fresh auto-capture or notification triggers.
- Keep capture and notification settings distinct and preserve user choices.
- Retain existing FTS query semantics or document and approve any relevance change with comparison fixtures.

**Known limits and review gaps**

- Current live test exercises explicit share, auto-work and notification, but does not cover every capture setting or source trigger.
- Retaining a local withdrawn marker does not undo previously exported knowledge.

**Files**

- [hub/fed/plugins/knowledge.py](../../../hub/fed/plugins/knowledge.py)

<a id="hub-20"></a>
### HUB-20 — Git code sharing and verified fetch plugin

**Owner:** P10. **Approach:** extract. **Baseline groups:** BASE-14.

**Current behavior**

- Validates a checkout by its shared remote/rid, resolves a commit, pushes refs/agentmux/<peer>/<slug> and sends metadata rather than file contents.
- Records sha/base/files/stat/log/note/author, optionally sends a handoff, lists shares and contributes fetch actions.
- Checks inbound ref namespace and SHA shape; fetches into the requested matching checkout and rejects a moved ref when its SHA differs.
- Provides review/switch command suggestions; it does not merge the shared work.

**Reuse:** Reuse Git operations, checkout proof, pointer schema and SHA verification behind a scoped workspace/artifact plugin. Replace direct calls to the messages plugin with a NATS contribution contract.

**Added functionality or operating benefit**

- Authorize source export before Git push, record durable publication intent and reconcile a pushed ref whose metadata publish failed.
- Bind evidence to immutable commit/artifact identity and preserve origin review authority.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HUB-20-C01 | Compare share/list/handoff/fetch, wrong checkout, invalid address and moved-ref rejection using isolated bare remotes. | [test_fed_live.py](../../../hub/tests/test_fed_live.py) | Isolated macOS/Linux/WSL hubs, pinned Python federation dependencies, nsc, Git and a real NATS server; use separate test accounts and stores. Isolated Git remotes; no customer repositories. |
| HUB-20-C02 | Interrupt before/after Git push and metadata publication; reconcile the same share without duplicate export or claiming that a local rollback removed remote content. | New fixture/review needed; no existing test claimed | P04/P10 Git effect-intent and recovery fixtures. |

**Migration and compatibility checks**

- Retain share IDs, ref namespace, full sha/base and source/rid mapping, fetched state and reachable Git content.
- Import pointers without fetching, pushing, checking out or merging as a side effect.
- Do not substitute an Object Store upload for the existing Git workflow without an explicit behavior and compatibility decision.

**Known limits and review gaps**

- Text redaction cannot scrub referenced Git history; force-pushed refs are detected only when fetched.
- Current publication performs Git push before the final metadata guard/staging step and needs explicit repair.

**Files**

- [hub/fed/plugins/code.py](../../../hub/fed/plugins/code.py)

<a id="hub-21"></a>
### HUB-21 — Stdio MCP gateway

**Owner:** P06. **Approach:** wrap. **Baseline groups:** BASE-12.

**Current behavior**

- Implements newline JSON-RPC initialize/ping/tools-list/tools-call and returns MCP tool content/errors.
- Exposes fixed agent tools plus dynamically generated non-operator federation tools, keeping CLI/hub verbs authoritative.
- Transforms required capabilities for work creation, adds cwd and relies on the hub caller identity instead of asserting its own.

**Reuse:** Retain the existing gateway and tool names as an adapter to scoped owners. Reuse registry-driven discovery and protocol fixtures; version any schema change.

**Added functionality or operating benefit**

- Add explicit external-client enrollment beyond process ancestry and host capability/version qualification.
- Expose portable Jev and Agentmux plugins through the same authorized operation contracts where supported.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HUB-21-C01 | Preserve tool names/schemas, required arguments, operator-tool exclusion, notification handling and JSON-RPC/tool error behavior. | [test_fed_unit.py](../../../hub/tests/test_fed_unit.py) | Pinned Python and SQLite with FTS5 on native macOS/Linux and Linux filesystems in WSL; isolated temporary homes. |
| HUB-21-C02 | Run the same scoped reference workflow from each supported client host; verify a caller cannot gain another user's authority through MCP arguments or cwd. | New fixture/review needed; no existing test claimed | P06 actual client/version support matrix and scoped test identities. |

**Migration and compatibility checks**

- Maintain tool-name aliases and schema compatibility; do not silently expose formerly operator-only verbs.
- Retain user MCP configuration and migrate only the approved server entry/credential references.

**Known limits and review gaps**

- Current MCP support is a minimal fixed protocol implementation; broad Desktop/CLI interoperability is not yet qualified.
- MCP tool availability does not imply conversation/event/compaction visibility.

**Files**

- [hub/fed/mcp.py](../../../hub/fed/mcp.py)

<a id="hub-22"></a>
### HUB-22 — Federation dependency manifests

**Owner:** P12. **Approach:** retain. **Baseline groups:** BASE-36, BASE-37.

**Current behavior**

- Pins nats-py and nkeys directly and constrains their recorded transitive Python dependencies.
- The lock header records historical interpreter/test context; hub fed setup consumes both files.

**Reuse:** Keep the reproducible dependency inputs and historical version attribution. Extend packaging checks when SDKs or NATS features change.

**Added functionality or operating benefit**

- Add repeatable supported-host installation, dependency integrity/license inventory and version-qualified NATS features.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HUB-22-C01 | Install from the declared manifests in clean supported environments and record resolved versions; distinguish incompatible interpreter or missing packages from test failures. | New fixture/review needed; no existing test claimed | P02/P06/P12 clean Python environments with permitted package access. |

**Migration and compatibility checks**

- Preserve old lock files with the migration/release record so legacy recovery can reproduce the prior runtime.
- Qualify upgrades before enabling new protocol/storage features.

**Known limits and review gaps**

- The header's historical test statement is not evidence that this audit ran or passed those tests.

**Files**

- [hub/requirements.txt](../../../hub/requirements.txt)
- [hub/requirements.lock](../../../hub/requirements.lock)

<a id="hub-23"></a>
### HUB-23 — NATS deployment, account enrollment and credentials

**Owner:** P10. **Approach:** extend. **Baseline groups:** BASE-13, BASE-16, BASE-36.

**Current behavior**

- circle.sh provisions an operator, SYS/circle accounts, admin and peer users, signing material, scoped subject permissions, JWT revocation/push and generated Helm/server configuration.
- up.sh provisions kind or the current Kubernetes context, self-signed CA/server TLS secret, pinned Helm chart, streams/KV and replica count.
- values.yaml enables clustered file-backed JetStream, PVCs, full JWT resolver and monitoring; leaf/WebSocket/MQTT ports are currently disabled.
- kind.yaml/nodeport.yaml expose a local TLS client port; credential/signing-key material lives in private generated directories.

**Reuse:** Retain and extend the deployment/enrollment tooling as a documented existing installation path. Add the approved local/team/leaf profiles incrementally and keep generated secrets outside source and ordinary shared state.

**Added functionality or operating benefit**

- Support independent organization accounts/domains and explicit scoped leaf links.
- Separate tenant/project permissions, improve upgrade/backup diagnostics and qualify real supported topology versions.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HUB-23-C01 | Reproduce the existing test-circle and clustered deployment, peer add/revoke, JWT push, TLS validation and stream provisioning before comparing the target installer. | [test_fed_live.py](../../../hub/tests/test_fed_live.py) | Isolated macOS/Linux/WSL hubs, pinned Python federation dependencies, nsc, Git and a real NATS server; use separate test accounts and stores. Optional disposable kind/Kubernetes, Helm, OpenSSL and kubectl. |
| HUB-23-C02 | Migrate an existing circle with active consumers and queued work to the approved topology; verify identity mapping, denied cross-project reads/writes and preservation of accepted work. | New fixture/review needed; no existing test claimed | P10 disposable old/new installations, independent organizations and leaf links. |
| HUB-23-C03 | Restore private signing/credential references and persistent broker data in a recovery drill without widening permissions or republishing historical work. | New fixture/review needed; no existing test claimed | P12 isolated backup/restore environment. |

**Migration and compatibility checks**

- Inventory operator/account/user public identities, signing-key custody, revocations, peer ACLs, credentials/CA references and resolver claims before enrollment changes.
- Preserve AM_* and KV_* records, durable consumers/ack positions, storage paths and replica/retention settings; no destructive reprovisioning.
- Current broad $JS.API permissions and am_board writes require a reviewed restrictive mapping, not a blind copy into the multi-user product.
- Keep the current central-circle deployment supported during migration; record whether it remains a topology option or is retired only after approval.

**Known limits and review gaps**

- Cluster creation targets the selected Kubernetes context when --no-kind is used; these scripts are not run by this audit.
- Existing source config has no leaf links or independent organization authority.
- Existing tests do not prove every peer API permission is sufficiently restricted for the new product.

**Files**

- [deploy/nats/circle.sh](../../../deploy/nats/circle.sh)
- [deploy/nats/up.sh](../../../deploy/nats/up.sh)
- [deploy/nats/values.yaml](../../../deploy/nats/values.yaml)
- [deploy/nats/kind.yaml](../../../deploy/nats/kind.yaml)
- [deploy/nats/nodeport.yaml](../../../deploy/nats/nodeport.yaml)

<a id="hub-24"></a>
### HUB-24 — Local live demo, sample repositories and scoring

**Owner:** P01. **Approach:** retain-evidence. **Baseline groups:** BASE-01, BASE-09, BASE-37.

**Current behavior**

- Builds throwaway calc/report Git fixtures, demonstrates shell delivery/ack/claim/death and checks harness sidecar cleanup.
- Runs calibration, team decomposition, cross-repository and mixed-client swarm scenarios with provider CLIs.
- Scores E1–E6 for terminal work state, delivery/bell failures, liveness, acknowledgments and repository verification; preserves reports/pane tails and generates a scoreboard.
- Drains in-flight mail before scoring and cancels unfinished demo work to limit contamination across runs.

**Reuse:** Keep scenarios, fixtures, scoring meanings and historical output formats. Adapt calls to the new owners and add evidence/acceptance checks without rewriting old results.

**Added functionality or operating benefit**

- Add exact source/dependency/environment identity, true origin acceptance and per-repository artifact validation.
- Run supported-host comparisons in isolated workspaces with clearly labeled provider substitutions.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HUB-24-C01 | Execute the shell smoke on a disposable home; preserve delivery/claim/death and sidecar cleanup observations. | [smoke_shell.sh](../../../hub/demo/smoke_shell.sh) | Pinned Python and SQLite with FTS5 on native macOS/Linux and Linux filesystems in WSL; isolated temporary homes. tmux and harness; no model needed. |
| HUB-24-C02 | Compare all four orchestration scenarios and E1–E6 against baseline and target; add explicit acceptance checks and keep failed/skipped outcomes. | [orchestrate.py](../../../hub/demo/orchestrate.py) | Pinned Python and SQLite with FTS5 on native macOS/Linux and Linux filesystems in WSL; isolated temporary homes. tmux, isolated repos and approved real provider accounts/budget. |
| HUB-24-C03 | Regenerate scoreboard from copied historical fixtures and verify totals/failed-check attribution without overwriting original reports. | New fixture/review needed; no existing test claimed | Offline copied report fixtures. |

**Migration and compatibility checks**

- Retain historic report IDs and meaning of checks; new checks need a versioned score schema.
- Move machine-specific paths to declared configuration while preserving sample workflow behavior.
- Do not run reset-capable demos against user projects or the normal hub home.

**Known limits and review gaps**

- Demo scripts reset sample repositories and may launch paid agents; none were executed.
- The old demo README has machine-specific paths and historical test counts, not current qualification evidence.
- E1 done and six passing demo checks do not alone establish accepted work or production reliability.

**Files**

- [hub/demo/README.md](../../../hub/demo/README.md)
- [hub/demo/orchestrate.py](../../../hub/demo/orchestrate.py)
- [hub/demo/scoreboard.py](../../../hub/demo/scoreboard.py)
- [hub/demo/setup_repos.sh](../../../hub/demo/setup_repos.sh)
- [hub/demo/smoke_shell.sh](../../../hub/demo/smoke_shell.sh)

<a id="hub-25"></a>
### HUB-25 — Cross-user federation walkthrough and live-agent demo

**Owner:** P10. **Approach:** retain-evidence. **Baseline groups:** BASE-13, BASE-14, BASE-37.

**Current behavior**

- Sets up three isolated hub homes and differently named clones for nick/alice/mallory, then demonstrates presence, shared board, code handoff, work return, knowledge, guards and kill/resume.
- Can launch real Claude sessions with MCP on two hubs; the shell wrapper manages up/run/live/down/dashboard and operator commands.
- The deterministic walkthrough acts through operator --as rather than proving independently enrolled users; live mode explicitly configures bypass and disables other settings sources.

**Reuse:** Preserve the narrated workflow and expected collaboration artifacts as a compatibility scenario. Add a separately qualified cross-organization version with explicit users and scoped execution.

**Added functionality or operating benefit**

- Demonstrate independent leaf/domain operation, origin acceptance, partitions and durable reservations.
- Replace demo-specific broad bypass assumptions with the product's approved execution profile for release evidence.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HUB-25-C01 | Compare the full deterministic walkthrough against isolated baseline and target systems, including shared card/code/finding/ref identities and guard decisions. | [demo.py](../../../hub/fed/demo.py) | Isolated macOS/Linux/WSL hubs, pinned Python federation dependencies, nsc, Git and a real NATS server; use separate test accounts and stores. Disposable demo homes and Git remotes. |
| HUB-25-C02 | Run a separately authorized real-client demonstration and verify origin evidence/acceptance after a receiving-hub disconnect; report provider and host limitations. | [demo.py](../../../hub/fed/demo.py) | P06/P10 approved real client accounts and budget, isolated homes, two organizations and leaf links. |

**Migration and compatibility checks**

- Keep old demonstrations/results labeled as central-circle evidence; do not relabel them as independent-organization qualification.
- Keep demo reset logic isolated; prevent a test helper from deleting customer streams, KV buckets or data.
- Preserve user normal agent configuration and unrelated tmux sessions during demo setup/teardown.

**Known limits and review gaps**

- Current up/reset paths delete demo data and, for kind, reset configured streams/buckets; none were run.
- Current live success detection is narrower than proof of a correct accepted artifact.
- Existing names are sample identities, not a real multi-user trust boundary.

**Files**

- [hub/fed/demo.py](../../../hub/fed/demo.py)
- [deploy/nats/demo.sh](../../../deploy/nats/demo.sh)

<a id="hub-26"></a>
### HUB-26 — Hub regression suites and federation test harness

**Owner:** P01. **Approach:** retain. **Baseline groups:** BASE-37.

**Current behavior**

- Offline tests cover names, messages/FTS/idempotency, claims/leases/team children, delivery profiles, receipt logs, backup/retention, actual socket/TCP API, courier import and subscriptions.
- Core-NATS tests start two hubs and check direct delivery and work/result distribution.
- Federation unit tests cover config, rid/envelopes, guards/redaction, MCP and privileged hooks.
- Federation live tests and Circle/Person helpers provide real JWT users, optional TLS/kind, shared Git remotes and three hub homes for presence, spoofing, sharing, work, board CAS, knowledge, code and revoke.
- Harnesses directly seed stores and use operator impersonation for deterministic agents; missing prerequisites cause skips.

**Reuse:** Retain the tests and embedded fixtures. Run them as baseline evidence, then reuse behavioral assertions against compatibility adapters and target contracts; append focused missing-failure cases without deleting old history.

**Added functionality or operating benefit**

- Add complete per-component parity evidence, exact environment/source digests and independently administered hub/worker fixtures.
- Distinguish deterministic mocked agents, live brokers and actual provider clients; add current blocker regressions and migration rehearsals.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| HUB-26-C01 | Run all existing suites in their declared environments, recording every pass/fail/skip and known baseline failure; do not import old counts as a new result. | [test_hub_offline.py](../../../hub/tests/test_hub_offline.py), [test_nats_federation.py](../../../hub/tests/test_nats_federation.py), [test_fed_unit.py](../../../hub/tests/test_fed_unit.py), [test_fed_live.py](../../../hub/tests/test_fed_live.py) | Pinned Python and SQLite with FTS5 on native macOS/Linux and Linux filesystems in WSL; isolated temporary homes. Bash; real NATS/nsc/nats-py/Git for broker suites; disposable kind only when requested. |
| HUB-26-C02 | Run a mapped target comparison for each owning component and retain old failing cases until fixed or disproved with evidence. | [test_hub_offline.py](../../../hub/tests/test_hub_offline.py), [test_nats_federation.py](../../../hub/tests/test_nats_federation.py), [test_fed_unit.py](../../../hub/tests/test_fed_unit.py), [test_fed_live.py](../../../hub/tests/test_fed_live.py) | P01 verification harness plus each component's target environment. |
| HUB-26-C03 | Check fixture isolation, cleanup, account boundaries and repeatability; a skipped broker suite cannot satisfy a phase's live gate. | New fixture/review needed; no existing test claimed | P01 harness validation in disposable local and cluster test installations. |

**Migration and compatibility checks**

- Map each old test/assertion to a target case or approved behavior change; preserve original requirement/failure labels.
- Record configuration and runtime digests separately for old and new evidence.
- Do not run Circle.reset against any shared deployment that contains customer or unrelated work.

**Known limits and review gaps**

- All checks in this file are not-run; this is static source review, not a test report.
- Some legacy suites use real process/broker environments and have platform/dependency requirements; the word offline in a filename is not a guarantee of no services.
- No existing suite establishes exhaustive target parity, worker containment or independent-hub ownership.

**Files**

- [hub/tests/__init__.py](../../../hub/tests/__init__.py)
- [hub/tests/fedharness.py](../../../hub/tests/fedharness.py)
- [hub/tests/test_hub_offline.py](../../../hub/tests/test_hub_offline.py)
- [hub/tests/test_nats_federation.py](../../../hub/tests/test_nats_federation.py)
- [hub/tests/test_fed_unit.py](../../../hub/tests/test_fed_unit.py)
- [hub/tests/test_fed_live.py](../../../hub/tests/test_fed_live.py)

<a id="repo-01"></a>
**P01 isolated additions:** `sdk/python/README.md`, `sdk/python/agentmux_contracts/__init__.py`, `sdk/python/agentmux_contracts/__main__.py`, `sdk/python/agentmux_contracts/attestation.py`, `sdk/python/agentmux_contracts/validation.py`, `sdk/python/agentmux_contracts/wire.py`, `sdk/python/pyproject.toml`, `sdk/python/requirements.lock`, `sdk/python/tests/test_contracts.py`, `sdk/typescript/README.md`, `sdk/typescript/package-lock.json`, `sdk/typescript/package.json`, `sdk/typescript/src/cli.ts`, `sdk/typescript/src/index.ts`, `sdk/typescript/src/test.ts`, `sdk/typescript/test-examples.json`, `sdk/typescript/tsconfig.json`, `tests/contracts/README.md`, `tests/contracts/run.py`, `tests/contracts/test_conformance.py`, `tests/contracts/vectors/valid-examples.json`. These additions preserve the legacy entry points; full phase qualification remains open.

### REPO-01 — Repository instructions and writing rules

**Owner:** P00. **Approach:** extend. **Baseline groups:** Repository-wide governance/support.

**Current behavior**

- AGENTS.md carries the feature-branch restriction and autonomous Codex delivery review rule. Both root agent instruction files link the shared plain-language rules.
- Both root instruction files include the branch restriction, autonomous Codex delivery review, final branch acceptance, fast-test workflow and repository task tracking. The latest user instruction supersedes the previous Ryan/Nick delivery gates; their historical wording remains in Git history. This supersedes the original audit note that CLAUDE.md lacked the restriction; its original text remains in `component-audit-repository.json` review history. Actual supported-host instruction loading belongs to P06-T01 and remains unqualified.

**Reuse:** Retain root entry files and the shared writing rules. Extend their links as implementation contracts gain evidence.

**Added functionality or operating benefit**

- Consistent contributor and agent instructions for every language and plugin.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| REPO-01-C01 | Each supported agent host loads or receives the shared rules, autonomous Codex review and the no-merge restriction; add missing host-specific instruction links before qualification. | New fixture/review needed; no existing test claimed | Static instruction review and supported agent sessions |

**Migration and compatibility checks**

- Do not overwrite user instructions while installing plugins; preserve managed markers and user-authored sections.

**Known limits and review gaps**

- Static root-file review does not prove tool-specific instruction loading. REPO-01-C01 must pass with actual supported host versions in P06; installation and upgrades must preserve user-authored settings.

**Files**

- [AGENTS.md](../../../AGENTS.md)
- [CLAUDE.md](../../../CLAUDE.md)
- [.claude/rules/plain-language.md](../../../.claude/rules/plain-language.md)

<a id="repo-02"></a>
### REPO-02 — Design-pattern governance and recorded history

**Owner:** P01. **Approach:** extend. **Baseline groups:** BASE-37.

**Current behavior**

- Pinned catalog, baseline rules, project scope, registry, diagrams and source-digest review records form the existing governance gate.
- Six active baseline findings remain recorded; current backend scope is not a qualification of the future frontend.

**Reuse:** Retain checker, approved sources and historical records. Extend registry entries and change declared product surfaces explicitly when the frontend is introduced.

**Added functionality or operating benefit**

- Evidence for reused components and future plugin boundaries stays traceable.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| REPO-02-C01 | The gate rejects stale reviews, missing pattern evidence and unresolved findings; prior records remain readable. | [check.mjs](../../../.bytedesk/design-patterns/check.mjs) | Node and Git; read-only checker |

**Migration and compatibility checks**

- Never reset adoption or erase findings to admit the new design; qualify new web surfaces before release.

**Known limits and review gaps**

- Current check fails on six recorded baseline findings.

**Files**

- [.bytedesk/design-patterns/README.md](../../../.bytedesk/design-patterns/README.md)
- [.bytedesk/design-patterns/agent-rules.md](../../../.bytedesk/design-patterns/agent-rules.md)
- [.bytedesk/design-patterns/baseline.md](../../../.bytedesk/design-patterns/baseline.md)
- [.bytedesk/design-patterns/catalog.json](../../../.bytedesk/design-patterns/catalog.json)
- [.bytedesk/design-patterns/check.mjs](../../../.bytedesk/design-patterns/check.mjs)
- [.bytedesk/design-patterns/frontend-rules.md](../../../.bytedesk/design-patterns/frontend-rules.md)
- [.bytedesk/design-patterns/project.json](../../../.bytedesk/design-patterns/project.json)
- [.bytedesk/design-patterns/remediation.json](../../../.bytedesk/design-patterns/remediation.json)
- [.bytedesk/design-patterns/review.json](../../../.bytedesk/design-patterns/review.json)
- [.context/design-patterns-diagrams.md](../../../.context/design-patterns-diagrams.md)
- [.context/design-patterns.md](../../../.context/design-patterns.md)
- [.claude/rules/design-patterns.md](../../../.claude/rules/design-patterns.md)
- [.claude/rules/frontend-components.md](../../../.claude/rules/frontend-components.md)

<a id="repo-03"></a>
### REPO-03 — Continuous integration workflows

**Owner:** P01. **Approach:** extend. **Baseline groups:** BASE-37.

**Current behavior**

- CI performs syntax, selected hub/federation and dashboard suites, plus pattern governance.
- A green selected job does not prove the tmux, browser, broker or hardware matrices.

**Reuse:** Retain existing jobs and assertions; add isolated compatibility and migration jobs without replacing them with narrower tests.

**Added functionality or operating benefit**

- Baseline and candidate comparisons on supported platforms with explicit skip reasons.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| REPO-03-C01 | Deliberately failing an existing assertion blocks the relevant gate; skipped environments cannot count as passes. | [tests.yml](../../../.github/workflows/tests.yml), [design-patterns.yml](../../../.github/workflows/design-patterns.yml) | CI with declared Node, Python and supported OS jobs |

**Migration and compatibility checks**

- Preserve test identities, environment requirements and logs across pipeline changes.

**Files**

- [.github/workflows/design-patterns.yml](../../../.github/workflows/design-patterns.yml)
- [.github/workflows/tests.yml](../../../.github/workflows/tests.yml)

<a id="repo-04"></a>
### REPO-04 — Git text, binary and privacy rules

**Owner:** P12. **Approach:** extend. **Baseline groups:** BASE-16, BASE-36.

**Current behavior**

- LF rules protect sourced shell scripts; explicit binary rules protect recovered bytecode, captures and images.
- Ignore rules keep credentials, machine state, downloaded vendor manuals, caches and presentation locks out of source control.

**Reuse:** Retain rules and add narrowly scoped entries only when new outputs require them.

**Added functionality or operating benefit**

- New plugins and release packaging preserve binary fixtures and exclude private state.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| REPO-04-C01 | A fresh supported-platform checkout preserves binary digests and executable shell line endings; packaging excludes private runtime files. | New fixture/review needed; no existing test claimed | Git checkout and release-package inspection on macOS, Linux and WSL |

**Migration and compatibility checks**

- Keep source fixtures, agent definitions and license records versioned; never run text conversion over captures or recovered bytecode.

**Files**

- [.gitattributes](../../../.gitattributes)
- [.gitignore](../../../.gitignore)

<a id="repo-05"></a>
### REPO-05 — Product version and main user guide

**Owner:** P12. **Approach:** extend. **Baseline groups:** BASE-01, BASE-19, BASE-36.

**Current behavior**

- The version file identifies the release; README lists entry points, installation, authentication and operational workflows.

**Reuse:** Preserve working commands while updating examples to the qualified plugin product. Keep compatibility instructions during transition.

**Added functionality or operating benefit**

- A new user can complete existing workflows and the added team workflow from published instructions.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| REPO-05-C01 | Every advertised command and setup method resolves to shipped code or an explicit supported replacement. | [test_launch.sh](../../../dashboard/test_launch.sh), [test_auth.py](../../../dashboard/test_auth.py) | Clean supported host with documented prerequisites |

**Migration and compatibility checks**

- Label historical setup gaps rather than copying them into a supported product claim.

**Files**

- [VERSION](../../../VERSION)
- [README.md](../../../README.md)

<a id="repo-06"></a>
### REPO-06 — Harness contracts and known operational limits

**Owner:** P06. **Approach:** extend. **Baseline groups:** BASE-01, BASE-02, BASE-03, BASE-06.

**Current behavior**

- Documents preserve agent definition schemas, roster/worktree conventions and dispatch sandbox limitations.
- Older contract text says the full gate repoints the live dashboard; current test runner uses an isolated server.

**Reuse:** Retain amendment history; add dated corrections tied to code and link versioned replacement contracts.

**Added functionality or operating benefit**

- Instructions match actual isolation and supported client capabilities.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| REPO-06-C01 | Run every advertised workflow in isolated fixtures; stale operational warnings are corrected with code evidence. | [test_sandbox_coordination.py](../../../dashboard/test_sandbox_coordination.py), [run_tests.sh](../../../dashboard/run_tests.sh) | Supported client/tmux test host; isolated data root |

**Migration and compatibility checks**

- Do not treat old documentation as current test evidence; preserve source and amendment dates.

**Known limits and review gaps**

- These documents contain historical claims requiring reconciliation with current implementation.

**Files**

- [docs/CONTRACTS_agents.md](../../../docs/CONTRACTS_agents.md)
- [docs/TM-068-sandbox-dispatch.md](../../../docs/TM-068-sandbox-dispatch.md)
- [docs/USING_THE_HARNESS.md](../../../docs/USING_THE_HARNESS.md)

<a id="repo-07"></a>
### REPO-07 — Hub, federation and transport specifications

**Owner:** P10. **Approach:** extend. **Baseline groups:** BASE-11, BASE-12, BASE-13, BASE-14.

**Current behavior**

- Current verb, envelope, identity, account and terminal-delivery contracts document the existing installed system.

**Reuse:** Retain old contract versions; add an explicit old-to-new command, event, permission and state mapping.

**Added functionality or operating benefit**

- Operators can move from shared-circle deployments to independent hubs without losing delivery evidence.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| REPO-07-C01 | Every documented public verb and protocol field has a retained contract or reviewed migration entry. | [test_hub_offline.py](../../../hub/tests/test_hub_offline.py), [test_fed_unit.py](../../../hub/tests/test_fed_unit.py), [test_fed_live.py](../../../hub/tests/test_fed_live.py) | Isolated hub and NATS environments; pinned clients |

**Migration and compatibility checks**

- Keep prior behavior and topology decisions attributed to their version; publish mixed-version compatibility limits.

**Files**

- [docs/PROTOCOL.md](../../../docs/PROTOCOL.md)
- [docs/FEDERATION.md](../../../docs/FEDERATION.md)
- [docs/TRANSPORT.md](../../../docs/TRANSPORT.md)

<a id="repo-08"></a>
### REPO-08 — Historical handover and reference screenshots

**Owner:** P07. **Approach:** retain-evidence. **Baseline groups:** BASE-17, BASE-37.

**Current behavior**

- Handover and five screenshots preserve prior UI, implementation decisions and reported test outcomes.

**Reuse:** Retain original evidence with dates; add current before/after captures using controlled fixture data.

**Added functionality or operating benefit**

- Reviewers can compare navigation, controls and meaningful display states across migration.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| REPO-08-C01 | Each retained screenshot has provenance; new screenshots use the exact candidate and contain no private operator data. | New fixture/review needed; no existing test claimed | Static review and isolated browser captures |

**Migration and compatibility checks**

- Do not overwrite historical screenshots or turn old reported test counts into current pass claims.

**Files**

- [HANDOVER.md](../../../HANDOVER.md)
- [docs/images/board.png](../../../docs/images/board.png)
- [docs/images/iiot.png](../../../docs/images/iiot.png)
- [docs/images/runs-view.png](../../../docs/images/runs-view.png)
- [docs/images/settings-orchestration.png](../../../docs/images/settings-orchestration.png)
- [docs/images/status-feed.png](../../../docs/images/status-feed.png)

<a id="repo-09"></a>
### REPO-09 — Vendor documentation references

**Owner:** P11. **Approach:** extend. **Baseline groups:** BASE-30.

**Current behavior**

- Vendor links distinguish open Logix data-access protocols from licensed Windows engineering SDKs.

**Reuse:** Retain references and redistribution limits; version references when qualified adapters change.

**Added functionality or operating benefit**

- Tool prerequisites and supported operations remain accurate for industrial plugins.

**Behavior checks — baseline and candidate not run**

| Check | Required comparison | Existing evidence to reuse | Environment |
| --- | --- | --- | --- |
| REPO-09-C01 | Each claimed vendor operation has a source/tool version and simulator or hardware evidence, with redistribution rights checked. | New fixture/review needed; no existing test claimed | Vendor documentation review and approved integration environment |

**Migration and compatibility checks**

- Do not bundle ignored vendor manuals or imply an SDK integration from a protocol library.

**Files**

- [docs/vendor/README.md](../../../docs/vendor/README.md)

## Review sequence

1. P00 records Codex review of the inventory, public contracts and intended behavior, with independent subagent findings resolved before advancement.
2. P01 runs baseline checks and adds missing fixtures before consequential refactoring.
3. Each owning phase proves its existing behaviors and specific gains on isolated candidate environments.
4. P04/P10/P12 prove state, delivery, credential and deployment migration at the relevant boundaries.
5. P12 requires a release disposition for every component and every required check. No missing or skipped evidence can be labeled a pass.
6. Deleting a legacy path requires a separate reviewed change after successful migration and acceptance.

## Scoped P01 baseline repair update, October 9

Ryan authorized autonomous repair of all six governance findings. HUB-03 retains the store API while adding schema migration 5 and collision-safe snapshots. HUB-17 gains origin-owned reservations and bound v3 results over NATS. HUB-26 owns the added `hub/tests/test_governance.py` and expanded real-broker tests. The source index preserves its previous hashes/declarations in history and records the reviewed current code. The inventory now covers 338 baseline files plus two added files (340 total), still across 93 components and 198 future comparison checks. See [repair evidence](governance-repairs.md); these targeted results do not qualify every planned replacement or phase.
