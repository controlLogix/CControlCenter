---
name: agent-new
description: Create an Agentmux agent definition with its role, tools and enforced posture. Use for a new definition, not to launch a worker.
---

# agent-new

Run commands through the installed package launcher:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/skills/agent-config/scripts/runtime.py" COMMAND ARGS...
```

Set `AGENTMUX_REPO` to the absolute trusted runtime checkout and `AGENTMUX_DASHBOARD` to the intended local dashboard. Below, `coordination`, `dispatch` and `setup-auth` name the launcher COMMAND, not shell aliases. Use the current runtime caller identity; preserve its refusals and stderr. Linux/macOS or explicitly selected WSL execution is required; native Windows hook execution is not qualified.

Read `coordination agents --json` first to find name collisions and discovery problems. Create in a writable `repo` or `global` scope with `coordination agentdef SCOPE NAME --description TEXT --role ROLE --posture POSTURE` plus the intended fields. Definitions in the Claude-owned scope are read-only.

Choose posture deliberately; omitted posture defaults to workspace-write. An unsupported enforced posture must fail, never silently widen. Tool lists accept separate arguments. Authentication fields name a configured method, never a credential. Send no checksum for creation. Read the created definition back with `coordination agents NAME --json`. Let server validation explain refusals; do not write definition files to bypass it.

Example request: Create a read-only reviewer named reviewer in this repository.

Start with `coordination agentdef repo reviewer --description "Reviews changes" --role reviewer --posture read-only` through the launcher. The returned definition and readback show repo scope, reviewer role and read-only posture. A collision stops creation.

Nearby request: Launch the existing reviewer belongs to team-dispatch, not definition creation.
