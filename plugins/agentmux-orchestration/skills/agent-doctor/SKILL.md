---
name: agent-doctor
description: Diagnose Agentmux board, definition and dispatch readiness without silently repairing policy or starting providers.
---

# agent-doctor

Run commands through the installed package launcher:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/skills/agent-config/scripts/runtime.py" COMMAND ARGS...
```

Set `AGENTMUX_REPO` to the absolute trusted runtime checkout and `AGENTMUX_DASHBOARD` to the intended local dashboard. Below, `coordination`, `dispatch` and `setup-auth` name the launcher COMMAND, not shell aliases. Use the current runtime caller identity; preserve its refusals and stderr. Linux/macOS or explicitly selected WSL execution is required; native Windows hook execution is not qualified.

Use `coordination doctor --strict` for errors and warnings, `coordination agents --json` for definition problems and `dispatch status --json` for running work. A missing runtime binding, unreachable dashboard, unsupported posture or missing host hook is a failed prerequisite, not readiness.

Report the exact failing boundary and a bounded remedy. The strict doctor exits nonzero on errors; preserve that signal. Do not change policy, install a provider, read credentials or start work merely to diagnose. Distinguish package discovery from actual host hook execution and real-provider qualification.

Example request: Explain why this Agentmux installation is not ready.

Start with `coordination doctor --strict` through the launcher. Report errors, warnings and exit status; tie remedies to observed failures. No policy or provider setup changes.

Nearby request: Change an approved setting belongs to agent-config.
