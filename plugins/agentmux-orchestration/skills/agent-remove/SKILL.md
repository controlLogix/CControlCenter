---
name: agent-remove
description: Remove an authorized Agentmux agent definition with checksum and live-worker protection. Does not kill a worker.
---

# agent-remove

Run commands through the installed package launcher:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/skills/agent-config/scripts/runtime.py" COMMAND ARGS...
```

Set `AGENTMUX_REPO` to the absolute trusted runtime checkout and `AGENTMUX_DASHBOARD` to the intended local dashboard. Below, `coordination`, `dispatch` and `setup-auth` name the launcher COMMAND, not shell aliases. Use the current runtime caller identity; preserve its refusals and stderr. Linux/macOS or explicitly selected WSL execution is required; native Windows hook execution is not qualified.

Read `coordination agents NAME --json` to establish scope, checksum and the actual definition being removed. For authorized deletion use `coordination agentdrop SCOPE NAME --checksum VALUE`. This unlinks the definition; it is not a soft delete or a worker stop.

The runtime verifies caller identity and checksum; the hook refuses a definition used by attached/detached workers. Claude-owned scope is read-only. If the definition changes, reread it and assess the requested deletion again. Do not retry through unlink or another endpoint. Report the runtime result and remaining discovery problems.

Before mutation inspect the intended dashboard's `/api/agents` live roster for matching `agentdef` entries in attached or detached state. Use a host where this package's hook executes. If the live lookup fails or the guard is unavailable, refuse the mutation until the guard is available. The server checks checksum and identity; it does not enforce the live-worker check. Do not bypass the hook with raw HTTP.

Example request: Remove the unused repo reviewer definition.

Start with `coordination agents reviewer --json` through the launcher. After checking live use and authorization, pass the fetched checksum to agentdrop; report the actual deletion or refusal.

Nearby request: Stop its running pane is not definition removal.
