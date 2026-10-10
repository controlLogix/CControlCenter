---
name: team-dispatch
description: Dispatch a ready Agentmux task or hire an approved team member through existing policy checks.
---

# team-dispatch

Run commands through the installed package launcher:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/skills/agent-config/scripts/runtime.py" COMMAND ARGS...
```

Set `AGENTMUX_REPO` to the absolute trusted runtime checkout and `AGENTMUX_DASHBOARD` to the intended local dashboard. Below, `coordination`, `dispatch` and `setup-auth` name the launcher COMMAND, not shell aliases. Use the current runtime caller identity; preserve its refusals and stderr. Linux/macOS or explicitly selected WSL execution is required; native Windows hook execution is not qualified.

Inspect `coordination task-show KEY --json` and `coordination roster KEY --json`. For a ready task use `dispatch dispatch KEY --dry-run`, then the authorized `dispatch dispatch KEY`. For an additional approved member use only `coordination hire KEY --name NAME --json`.

Hire accepts only task key and definition name: no cwd, model, cli, argv or actor overrides. The server resolves the definition and enforces dispatchEnabled, dashboardMayHire, approval, posture and capacity. A 403/409/503 is a refusal to explain, not a reason to change settings or retry raw HTTP. `dispatch status --json` reports progress. Launching spends resources and can invoke an AI provider; scope and authorization must cover that work.

Example request: Hire the approved reviewer for TM-042.

Start with `coordination hire TM-042 --name reviewer --json` through the launcher. Report the returned member state or exact refusal; do not add configuration overrides.

Nearby request: Choose a team without launching belongs to team-compose.
