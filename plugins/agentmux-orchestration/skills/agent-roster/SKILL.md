---
name: agent-roster
description: Inspect Agentmux agent definitions, personas and discovery problems. Use for available agent capabilities, not live worker status or team approval.
---

# agent-roster

Run commands through the installed package launcher:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/skills/agent-config/scripts/runtime.py" COMMAND ARGS...
```

Set `AGENTMUX_REPO` to the absolute trusted runtime checkout and `AGENTMUX_DASHBOARD` to the intended local dashboard. Below, `coordination`, `dispatch` and `setup-auth` name the launcher COMMAND, not shell aliases. Use the current runtime caller identity; preserve its refusals and stderr. Linux/macOS or explicitly selected WSL execution is required; native Windows hook execution is not qualified.

Use `coordination agents --json` to list definitions and problems. Use `coordination agents NAME --json` for the full persona and checksum; list results omit persona. A duplicate name makes both definitions unusable: report the collision rather than selecting one.

These are definitions, not running workers. `/api/agents` is the live pane roster; `coordination roster KEY --json` is a task team. Keep those meanings separate. Report scope, capabilities, posture and limitations without exposing authentication secrets. This workflow makes no changes.

Example request: Which definitions can review this repository?

Start with `coordination agents --json` through the launcher. Report matching roles/capabilities and discovery problems; fetch a selected name to show its full details. No files change.

Nearby request: Which workers are running needs live status, not this definition list.
