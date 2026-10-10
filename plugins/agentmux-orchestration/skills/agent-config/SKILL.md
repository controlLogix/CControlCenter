---
name: agent-config
description: Inspect or change Agentmux runtime settings, or invoke its existing provider setup and verification commands. Not a general terminal configuration skill.
---

# agent-config

Run commands through the installed package launcher:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/skills/agent-config/scripts/runtime.py" COMMAND ARGS...
```

Set `AGENTMUX_REPO` to the absolute trusted runtime checkout and `AGENTMUX_DASHBOARD` to the intended local dashboard. Below, `coordination`, `dispatch` and `setup-auth` name the launcher COMMAND, not shell aliases. Use the current runtime caller identity; preserve its refusals and stderr. Linux/macOS or explicitly selected WSL execution is required; native Windows hook execution is not qualified.

Read `coordination config --json` or `coordination config NAME`. Apply only the requested setting change with `coordination config NAME VALUE`; the runtime validates types and caller identity. Explain changes to approval, hiring, dispatch or posture before an authorized mutation. Never turn off a gate as an error workaround.

For provider setup use `setup-auth --list`, `setup-auth --verify METHOD` or, when explicitly requested, `setup-auth METHOD` / `setup-auth --select METHOD`. These are existing runtime commands; setup and selection can change provider configuration. Do not collect, copy or print credential values. Report the method identifier and verification result. Keep private test homes separate from the operator installation.

Example request: Show dispatchEnabled without changing it.

Start with `coordination config dispatchEnabled` through the launcher. Report the returned typed value. Do not infer permission to enable dispatch.

Nearby request: Diagnose why a worker failed belongs to agent-doctor unless a specific setting change is requested.
