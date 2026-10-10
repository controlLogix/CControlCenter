---
name: agent-edit
description: Change an existing Agentmux agent definition while preserving fields and guarding against stale or live-worker edits.
---

# agent-edit

Run commands through the installed package launcher:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/skills/agent-config/scripts/runtime.py" COMMAND ARGS...
```

Set `AGENTMUX_REPO` to the absolute trusted runtime checkout and `AGENTMUX_DASHBOARD` to the intended local dashboard. Below, `coordination`, `dispatch` and `setup-auth` name the launcher COMMAND, not shell aliases. Use the current runtime caller identity; preserve its refusals and stderr. Linux/macOS or explicitly selected WSL execution is required; native Windows hook execution is not qualified.

Fetch `coordination agents NAME --json`. Preserve all fields the user intends to retain: `coordination agentdef SCOPE NAME` replaces the entire definition, not selected fields. Pass the fetched `--checksum VALUE` and all desired fields; an empty list flag clears that list.

Use the existing caller identity. Do not edit Claude-owned definitions or definitions used by attached/detached workers. A stale checksum requires a fresh read and reconciliation with the requested change, not an unchecked retry. Keep the server refusal and fix hints visible. Read back the accepted definition; do not bypass a refusal with direct file edits.

Before mutation inspect the intended dashboard's `/api/agents` live roster for matching `agentdef` entries in attached or detached state. Use a host where this package's hook executes. If the live lookup fails or the guard is unavailable, refuse the mutation until the guard is available. The server checks checksum and identity; it does not enforce the live-worker check. Do not bypass the hook with raw HTTP.

Example request: Change reviewer description without losing its tools.

Start with `coordination agents reviewer --json` through the launcher. Use its complete returned fields and checksum in agentdef; show the accepted description and preserved tool list. A stale checksum is a refusal, not success.

Nearby request: Create another definition belongs to agent-new.
