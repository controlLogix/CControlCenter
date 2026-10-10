# Agentmux orchestration plugin

This newly maintained local package restores nine existing Agentmux workflows. It is not recovered upstream source. Read PROVENANCE.md for the original-source gap.

Use Python 3 and `/bin/sh` in a Linux/macOS process or an explicitly selected WSL process. Bind `AGENTMUX_REPO` to the absolute trusted Agentmux checkout containing taskmgmt/coordination.py, dispatch.py and setup_auth.py. Set AGENTMUX_DASHBOARD to the intended local dashboard (the runtime defaults to loopback port 8787). The package may be copied to a directory with spaces; it does not depend on its checkout location.

The nine skills cover definition creation, inspection, editing and removal; team composition, dispatch and collection; configuration and diagnosis. Roster MCP offers read-only agent_roster and team_roster. Discovery does not require a running dashboard. Hooks check relevant shell/edit requests; they are defense in depth, not authentication or universal shell containment. The live-definition check is hook-only: direct HTTP definition mutations do not enforce that check. The server retains its existing identity, checksum and other checks, but they do not replace the hook guard. A hook's preflight lookup cannot eliminate a later race.

For disposable compatibility tests set AGENTMUX_PLUGIN_ROOT to this package. The existing dashboard/test_orchestration_plugin.py and dashboard/test_plugin_skills.py must run without skips. Validate packaging in a private host configuration; no personal installation or marketplace publication is implied.

Windows-owned AI clients remain Windows-owned. A native Windows host cannot be assumed to execute these POSIX hook commands or translate runtime paths. That host path is unqualified; use an explicitly selected WSL process for package execution. Metadata validation is not inference or cross-host execution evidence. P06 framework qualification remains separate.

Do not put credentials in package files, tool output or skill examples. Runtime setup commands may change provider configuration only within the requested work. This package does not override repository no-merge rules or product approval policy.
