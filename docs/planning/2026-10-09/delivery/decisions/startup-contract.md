# LOCAL-01 implementation contract

Status: recommendation for P00 review. Automatic Compose start/reuse is an accepted requirement. The version matrix and deadlines below are proposed qualification targets; the stack is not implemented by this document.

## L01. Installation, ownership and selection

Install a signed/versioned Agentmux client package, a host launcher and an explicitly enrolled profile. A launch hook runs only after the host trusts/enables it. Disabled hooks, missing enrollment and unsupported versions produce a clear setup state; installation alone cannot bypass the host's trust controls.

The profile contains a generated instance ID, owning OS user identity, local or remote mode, stable Compose project name, release/config digest, selected Docker context/endpoint fingerprint, credential references and permitted organization/project selection. It lives outside the current repository. Changing directory or opening a second project cannot create another stack. Installation preserves all user-authored host settings and records the exact managed entries for upgrade/uninstall.

Local mode binds one profile to one approved local Docker context. Resolve an explicit context and verify its endpoint before any mutation. Reject an unexpected `DOCKER_HOST`, `DOCKER_CONTEXT`, TCP/SSH daemon, endpoint change or ownership mismatch; do not silently use the ambient default. A remote-hub profile uses authenticated hub access and does not start local Compose. Changing mode/context is an explicit configuration operation with existing-work checks.

Compose resources carry instance/profile/release labels; an open port or matching project name alone is not identity. Use authenticated application identity plus owned resource inspection to choose reuse. Other users' containers, different releases or unexpected volume labels are conflicts. Ports are assigned during enrollment/configuration and reused; conflicts are reported, not bypassed by starting a second stack.

Use a user-scoped local file lock around bootstrap inspection/start, keyed by instance ID and context identity. On the initial Unix/WSL targets, use an OS advisory lock held on an open file description; metadata carries an attempt UUID for diagnostics. Process exit releases the lock. PID, wall-clock timeout or a stale file alone never authorizes stealing it. After acquisition, inspect actual containers and application state again. NATS cannot coordinate this step because it may not be running yet.

## L02. Startup state machine and deadlines

`unconfigured -> inspecting -> waiting-for-owner | starting | reusing | conflict -> checking-readiness -> ready | degraded | failed`

1. Resolve the profile, installation integrity, host mode and worker-recursion marker. A managed worker calls status/attach only and cannot initiate nested stack startup.
2. Inspect the selected local daemon with a five-second call limit. Missing Docker, unavailable daemon and insufficient privilege are distinct errors. Do not install privileged software or change Docker settings from an ordinary launch.
3. Acquire the bootstrap lock or wait up to 30 seconds for the active owner's result. Lock timeout reports `starting_elsewhere` with its attempt ID; it does not start competing services.
4. Reuse a compatible authenticated healthy instance without pulling, recreating, migrating or restarting services. If stopped/absent, start only the configured pinned Compose project with `up -d --wait` and an explicit wait timeout. No automatic `down -v`, prune, force-recreate or in-place release upgrade.
5. Validate NATS identity/connectivity and required persistence, protected assembly status, then required surrounding services. Container `running` is not application readiness. Partial readiness reports each service's observed state. Broker read/write readiness probes use their own disposable scoped health record, not business records.
6. Return one versioned summary and release the lock. Interactive adapters render it; protocol adapters keep stdout protocol-clean. Closing the client does not stop the shared stack.

Proposed budgets: warm reuse/status returns within two seconds normally with a five-second hard probe limit; warm-broker runtime readiness target ten seconds; cold start with images already cached has a 60-second deadline; an allowed pinned-image download has a separate 180-second deadline and visible progress. First enrollment/preparation is explicit and may pre-pull images. A cold launch with uncached images must report download progress/failure rather than masquerade as warm reuse. Do not chain unbounded retries.

The adapter's interactive launch wait budget is ten seconds. If boot is still progressing, return `starting` with an attempt ID and retain a launcher-owned background operation only on hosts where its lifecycle is qualified. Subsequent status refresh observes the same operation. The owning helper must hold the lock while starting and survive hook-process exit; an unsupported detached-helper mode requires a synchronous qualified launcher with its documented timeout. A timeout must never print `ready`. No silently orphaned startup process is an acceptable implementation.

Compose's `--wait` waits for running/healthy services; the application probe is an additional requirement. [Docker Compose up](https://docs.docker.com/reference/cli/docker/compose/up/). Compose v5.6.0 is the current candidate pin from the [official release](https://github.com/docker/compose/releases/tag/v5.6.0); it is not installed/qualified in this WSL environment. P02 must lock the actual tested version and image digests.

## L03. Host support matrix

| Host | Planned launch integration | Status output | Evidence still required |
| --- | --- | --- | --- |
| Claude Code | Installed command `SessionStart` hook for new/resumed sessions, with an idempotent attach path for repeated events. | Host-supported user-visible notification/summary plus a bounded context record. Never assume extra model context proves the user saw it. | Actual startup, resume, cold/warm/concurrent launch and stdout behavior on supported Linux/macOS/WSL versions. Local CLI version observed: 2.1.295. |
| Codex CLI | Installed command `SessionStart` hook. Use the launcher directly, not an MCP-tool hook that depends on a connection that may not exist yet. | Supported system message/summary plus status tool/resource. | Actual trusted/enabled plugin hook, disabled-hook diagnostics and host-visible output. Local CLI version observed: 0.147.0; existing local hooks.json contains SessionStart, but this is not an Agentmux-hook test. |
| Pi | Extension `session_start` handler invokes launcher; no process startup from the extension factory. | TUI status/widget when available; structured result in noninteractive modes. | Pin/test the selected Pi version (v1.1.0 is the candidate release), reload/resume, RPC/JSON modes and cleanup without stopping shared services. |
| Claude Desktop chat/MCP | Local stdio MCP launcher may ensure/attach when that host actually starts the configured server; provide status resource/tool and a qualified app launcher where needed. | MCP protocol only on stdout; status resource/tool and host-supported notification. | Prove startup timing and visible summary on the actual Desktop version. Lazy MCP connection does not satisfy app-launch automation. Until proved, do not advertise direct Desktop-launch automation; retain the installed-launcher path and qualify it. |
| Other terminal clients | Host-specific adapter or installed `agentmux launch <client>` entry point. | Same summary contract rendered by the adapter. | A launcher must truly run on the advertised entry path. A manual status command is not automatic startup. |

Claude Code documents SessionStart and hook output; Codex documents SessionStart and warns that MCP-tool hooks can run before server readiness. Pi documents `session_start` for long-lived resources and separates TUI from noninteractive output. These are implementation leads, not proof of our integration. [Claude hooks](https://code.claude.com/docs/en/hooks), [Codex hooks](https://developers.openai.com/codex/hooks), [Pi extensions](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md).

On Windows, the installed adapter names the selected WSL distribution and invokes Linux paths through `wsl.exe --exec` with argument arrays. Runtime state, file locks and native tools live in that distro's Linux filesystem. Windows-side terminal/Desktop discovery uses an explicit adapter to that profile; it must not accidentally create a Windows-native stack or duplicate the WSL one. Docker Desktop WSL integration or an approved local Linux daemon is a prerequisite. The current distro reports Docker unavailable; no configuration was changed during P00.

## L04. Status contract

P01 will publish a schema for this field contract and success/failure fixtures. Required envelope fields: `schemaVersion`, `observationId`, `observedAt`, `sourceRevision`, `startupAttemptId`, `disposition` (`started`, `reused`, `starting`, `remote`, `unconfigured`, `failed`), authenticated caller scope and an explicit error list.

`instance` includes stable ID/name, installed/running version, local/remote mode, Compose project, approved context display name/fingerprint, permitted endpoint/dashboard links, readiness (`ready`, `degraded`, `not_ready`, `unknown`) and per-service observations. Do not return credential paths, tokens, broker management keys or private machine paths.

`persistence` includes backend/profile, observed server/domain identity where allowed, readiness, storage pressure, replication health when known and observation time. `work` contains only authorized active/project/reserved counts and their source cursor; use unknown when they cannot be read. A zero is an observed count, not the fallback for an error.

`hubs` separates inventory visibility from individual state. Use `inventoryState: known | unavailable | forbidden` plus the caller's visible entries. A known empty list means none configured in that scope. Each entry reports hub ID/display name, allowed organization/project scope, configured link state, application federation readiness, trust state, observation timestamp/age and permitted reservation summary. `connected`, `disconnected`, `stale`, `unknown` and `not_configured` are distinct. Do not expose hidden hubs through total counts or diagnostics. A connected leaf socket is not evidence of approved trust, application health or free capacity.

The same status service supplies terminal refresh and the AG-UI adapter. Start and reuse have the same field semantics. As phases add features, unsupported fields report unavailable explicitly; fixtures cannot make a not-yet-built federation service look connected. Render a concise summary such as: “Reused local hub Ryan-dev, version X. Ready. Dashboard: … . One visible partner disconnected; two tasks remain reserved. Observed 4 seconds ago.” Values must come from the authenticated observation.

## L05. Verification and ownership

P02 owns profile/context checks, Compose identity, lock recovery, helper lifecycle, timeouts and persistence readiness. P06 owns actual startup hooks, visible output, worker recursion, supported host versions and user-setting preservation. P07 owns dashboard agreement with the same status. P10 supplies real scoped hub state and disconnected reservations. P12 repeats packaged fresh-user/upgrade/recovery tests on every advertised combination.

FAIL-55 through FAIL-62 remain mandatory: concurrent launches, misleading readiness/identity, incompatible or partial stacks, Docker/context failures, unauthorized/stale hub status, host-hook and protocol-output behavior, and persistent-data recovery. Add cases for a killed lock owner, PID reuse, hook timeout during image download, unknown remote context, port collision and a worker with forged recursion metadata. The recursion marker is an optimization; actual bootstrap authorization still applies.

The current evidence establishes only source research, CLI version observations, local hook-event presence and the Docker availability gap. No cold/warm/concurrent Compose or host startup test has run. P00 review approves the contract; the owning implementation phases must prove it.
