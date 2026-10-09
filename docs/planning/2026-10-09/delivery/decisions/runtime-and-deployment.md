# Runtime and deployment decisions

Status: recommended for Codex P00 review. This refines the main plan's open choices without claiming product implementation or approving a scope reduction. Ryan's protected-kernel, language-neutral, NATS, platform, federation and additive-migration requirements remain unchanged.

## D01. Runtime and initial SDKs

Recommend Go for the small launcher, protected boot assembly and generic process supervision. Start ordinary plugin SDKs in Python and TypeScript. Keep existing Python domain/tool implementations behind their new interfaces and retain compatible Bash/tmux entry points during migration. Language-neutral JSON contracts over NATS are the public boundary; a Go interface is not the plugin ABI.

| Option | Concrete benefit | Cost and reason for the recommendation |
| --- | --- | --- |
| Go foundation | The spike built one dependency-locked NATS executable for Linux and macOS, amd64 and arm64, with CGO disabled. The Linux/amd64 executable ran without a separate Python/Node interpreter. | Adds a language to the repository and requires SDK conformance across languages. Cross-compilation is not native host qualification. Use it for the narrow foundation, not as a reason to rewrite domain code. |
| Python foundation | Reuses the current hub, tests and existing NATS dependency lock. Its request/reply client passed the same wire check. | Requires a managed interpreter/environment for host bootstrap, or additional packaging. Retain it for existing business and industrial implementations. This remains a viable fallback if the Go foundation creates disproportionate maintenance cost. |
| TypeScript/Node foundation | Fits UI and many client extensions. Strict compilation and its NATS client passed the wire check. | Requires a Node runtime and package deployment for the host launcher. Use it for SDK/client/UI work where the ecosystem helps; no measured speed disadvantage is asserted. |

Executed comparison: three clients exchanged the same UTF-8 JSON object with a Python service through a disposable token-protected Core NATS server. All three succeeded and returned nonzero for an absent service. Go built four targets; only Linux/amd64 ran. [Source, locked dependencies, results and limits](../spikes/runtime/README.md) are retained. This does not test lifecycle, cancellation, JetStream transactions, security isolation, performance or a complete SDK.

Proposed initial pins: Go 1.27.2 and nats.go 1.54.0; Python 3.14.4 and the existing `hub/requirements.lock` including nats-py 2.16.0; Node 22.22.1, TypeScript 7.0.2 and `@nats-io/transport-node` 3.4.0. NATS Server 2.15.0 is the foundation test candidate. Pin container images by digest when building the P02 package. Do not float production dependencies at `latest`. The Go client release requires Go 1.26 or newer; our tested toolchain satisfies that minimum. [NATS Go release](https://github.com/nats-io/nats.go/releases/tag/v1.54.0), [official Go download metadata](https://go.dev/dl/?mode=json).

P01 must prove the complete shared schemas and required SDK features with independent implementations. If a client lacks a storage feature, the owning service can expose the required domain contract over NATS; ordinary plugin authors need not recreate raw JetStream transaction logic. Do not silently emulate an unproven storage guarantee.

## D02. Protected assembly and process layout

The launcher is a bounded infrastructure prerequisite: resolve owned configuration, coordinate local startup, invoke Compose, and verify the protected assembly's identity. It does not schedule user work or become a second internal message bus.

The protected kernel consists of release-owned boot, kernel-lifecycle, internal-communication and exported-status plugins. Their manifests and compatibility set are shipped as one protected assembly. They have fixed approved membership; customers extend surrounding contracts rather than replacing the kernel. Prefer separate supervised processes for the initial protected plugins so their NATS permissions and crash boundaries can be tested directly. Use normal executables, not Go's platform-specific dynamic plugin mechanism. The extra processes cost memory and startup coordination; measure that overhead in P02 before introducing an in-process optimization.

Ordinary lifecycle, identity, policy, state, scheduling, providers, clients, UI and Jev remain outside the protected assembly. Their dependencies are an explicit directed graph. Missing optional packages mark those capabilities unavailable; they do not prevent the protected kernel from reaching its own ready state. Hosted auth and Jev are never boot prerequisites. Required domain owners can still keep application readiness false.

Protected internal subjects are in a separate account. External packages only receive exported status. Ordinary plugin administration cannot publish kernel commands or replace its release manifest. A host administrator can stop/update the installed product; this is a deployment privilege, not a public kernel mutation interface. Recovery starts from a known release and preserved data, not from arbitrary downloaded boot code.

P03 uses immutable PluginContext and per-operation OperationContext. Inheritance means supplying scoped defaults and compatible handles through SDK construction, not copying a parent's whole environment. Effective child grants are the intersection of package declarations, parent delegation and current policy. Nested private packages and independent packages have explicit ownership/lifetime rules. Shared borrowed services are not disposed by a child.

Proposed new code layout: `platform/launcher`, `platform/kernel`, `platform/runtime`, `contracts`, `sdk/python`, `sdk/typescript`, `plugins`, `deploy/compose`, and `tests/contracts`. The migrated dashboard adds `src/components/{atoms,molecules,organisms,templates}` with orchestration in screens/features. Existing files move only when ADD-01 checks and compatible entry points are ready. This layout does not authorize bulk source movement in P00.

## D03. Audience, workflow and dashboard controls

Use the existing proposed 20-developer team profile to size initial tests, with the same contracts in solo mode. Treat market positioning and pricing as product-review questions, not reasons to drop the industrial extensions or solo experience.

The first proof workflow changes a fixture repository, runs its tests, returns a reviewable diff and evidence, and waits for owner acceptance. It performs no merge, deployment or device write. The federation proof repeats that workflow in both directions between two independently enrolled, agent-operated real hub instances. An industrial reference workflow reads approved exported project/configuration data and proposes a change; real vendor/tool qualification remains P11.

Keep existing dashboard work creation, board/team actions, approvals and guarded run controls. The older suggestion to make it observation-only or to move all existing work creation out of the dashboard is not adopted. Agent clients remain the primary conversational interface. AG-UI carries authorized application events and supported commands at the UI boundary; CopilotKit and Atomic Design provide the UI structure. Internal UI-service traffic uses NATS. Display persisted plans, decisions, messages, tool events and evidence; do not invent or expose private model reasoning as an agent conversation.

## D04. Identity, enrollment and execution

Local setup creates one user-owned profile, stable hub/device identity, and a local identity provider plugin. Credentials live in an OS secret provider or a protected local store referenced by the profile. A fresh installation needs explicit enrollment; merely opening an arbitrary repository cannot enroll a new organization or accept partner trust.

For self-hosted teams, select Keycloak 26.8.0 as the first external OIDC qualification target. Keep its adapter outside the protected kernel. Use authorization code with PKCE for browser sign-in and the provider's device authorization endpoint for supported terminal flows. Validate issuer, audience, nonce/state, expiry and current membership. Map an external user by the stable `(issuer, subject)` pair; email and display name are mutable attributes, never identity keys. The separate local identity plugin continues to support explicitly enrolled solo installations without a hosted sign-in dependency.

This version is a candidate for P04 integration tests, not a claim of qualified support. Pin the actual tested distribution/container digest and configuration, test both browser and terminal flows, and record logout, expiry, revocation, key rotation and account-linking behavior before advertising compatibility. Official references checked for this decision: [Keycloak downloads](https://www.keycloak.org/downloads) and [OIDC endpoints and flows](https://www.keycloak.org/securing-apps/oidc-layers).

Alternatives considered: connecting only to a customer's existing enterprise OIDC provider would reduce installation work but would leave the reference team environment dependent on an external account and provider-specific behavior. Building a new Agentmux password service would add password storage, recovery and authentication maintenance unrelated to orchestration. Keycloak provides a self-hosted reference provider while the adapter contract keeps other enterprise OIDC providers possible; each additional provider needs its own qualification. Its costs are a separately operated service, upgrades, backup and configuration management.

The external identity provider owns its authentication data and may require its own database. That storage is outside Agentmux business authority: tasks, reservations, grants, membership decisions and orchestration evidence remain owned by Agentmux's NATS-backed domains. Do not turn the IdP database into a hidden SQL task store or query it as an Agentmux authorization shortcut. Account linking and membership changes are explicit owner operations with provenance. Device and plugin credentials remain distinct from human login; services validate effective actor/delegation as well as broker identity. Use NATS NKeys/JWT account/user credentials for broker enrollment, rotation and scoped permissions. This resolves the earlier deferred first-provider choice; runtime qualification remains P04 work.


Trusted installed plugins run with administrator-reviewed capabilities. This does not make task code or other users trusted. Team workers use dedicated containers with only the assigned workspace and short-lived scoped credentials, no Docker socket, no host home mount and a controlled network profile. Host-native tools use a separately enrolled execution adapter under a dedicated OS identity or host. A Git worktree is workspace organization, not an isolation boundary. P04 proves file/credential separation; P14 adds hostile third-party plugin containment. A customer-admin-installed plugin remains trusted until that later promise is qualified.

A revocation observed by a hub stops admitting new actions under the revoked grant. An isolated receiver can continue only within its previously issued offline grant. Revocation or grant expiry never means its old effects are known to have stopped; reserve the task until reconciliation or an explicit reassignment decision with recorded uncertainty. Hardware actions that cannot be fenced require their own policy and human handling.

## D05. Deployment and capacity qualification

Qualification targets: Linux amd64/arm64, native macOS amd64/arm64, and Windows through WSL2. Start native Linux fixtures with Ubuntu 24.04 LTS and the current Ubuntu 26.04 WSL environment. Use macOS 15 and 26 as candidate host test targets; actual host availability, vendor support and OS/runtime compatibility must be confirmed before advertising them. The current evidence runs only on WSL amd64. The legacy Windows compatibility paths remain preserved under ADD-01.

| Profile | Proposed test load | Storage topology and fault boundary |
| --- | --- | --- |
| Solo | 1 user, 2 projects, 4 active attempts | One local Compose stack and R1 file-backed JetStream. A destroyed disk requires backup restore; no high-availability claim. |
| Team | 20 users, 10 projects, 40 active attempts | R3 across three independent qualified hosts. Three containers on one laptop test process failures only. |
| Federation | 3 hubs across 2 organizations, up to 40 attempts each | Independent persistence domains; scoped partner links and reconnect tests. Sleeping developer laptops are not the team's availability layer. |
| Growth | 200 users, 10 hubs, up to 400 attempts overall | Later benchmark after launch profiles pass; not a launch service promise. |

Retain the main plan's proposed targets: metadata-query p95 below 250 ms; visible updates within 2 seconds; 10,000-event view replay within 5 seconds; warm-broker runtime readiness within 10 seconds. Use 4 KiB representative metadata records, 64 KiB stress records, and a 16 GiB/8-logical-CPU/SSD reference host as a starting fixture. Reserve worker resources separately from the broker/runtime. Report actual hardware, network delay, payload distribution and variance. P12 includes the 24-hour soak; the tiny runtime comparison provides no capacity evidence.

## D06. Provider, Jev and external-data policy

Default each project to explicitly selected provider destinations and budgets. No fallback to another hosted provider or partner hub may widen data access. Installations may reference customer-owned credentials; ordinary logs, status and shared records contain references and redacted diagnostics. A provider outage is a reported unavailable capability, not permission to change destinations.

Jev is optional and unavailable until configured and qualified. Exact authorization/eligibility rules precede semantic scoring; the owner revalidates before durable action. Record model/definition/version, permitted input provenance, usage, outcome, fallback and accepted-result measurements. No-Jev operation uses deterministic policies or human review. A semantic result never grants permission, releases reservations or accepts a task. Live eval spend and sample disclosure are separate explicit decisions before P08; the offered API token is not needed in P00.

## Required review and exit evidence

P00 review must accept or revise D01-D06 and the linked storage/startup records. Record alternatives and reasons, including any changed platform/capacity target. P01 verifies executable contracts and persistence behavior; P02 proves boot; P03 proves nesting and context; P04 proves identities/state/execution separation. Later provider, hardware and market decisions have named phase deadlines and cannot be hidden in a release claim. Codex records the engineering review and advancement decision; this recommendation itself does not pass a phase gate. No Ryan/Nick delivery approval is required.
