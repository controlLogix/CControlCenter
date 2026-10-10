---
name: team-compose
description: Propose and approve an Agentmux task team from existing definitions. Use for roster composition, not worker launch.
---

# team-compose

Run commands through the installed package launcher:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/skills/agent-config/scripts/runtime.py" COMMAND ARGS...
```

Set `AGENTMUX_REPO` to the absolute trusted runtime checkout and `AGENTMUX_DASHBOARD` to the intended local dashboard. Below, `coordination`, `dispatch` and `setup-auth` name the launcher COMMAND, not shell aliases. Use the current runtime caller identity; preserve its refusals and stderr. Linux/macOS or explicitly selected WSL execution is required; native Windows hook execution is not qualified.

Read the task with `coordination task-show KEY --json`, then `coordination agents --json`. Use `coordination recruit KEY --json` to ask the runtime for its deterministic roster; inspect `coordination roster KEY --json` for gaps and member status.

Approve authorized members using `coordination approve KEY --member NAME --member OTHER --json`. Approval is product policy, not implied by delivery autonomy. When the configured teamRequireApproval policy is false, recruitment can already approve members; report that actual status without inventing a separate approval. Uncovered capabilities and capacity limits remain explicit. Do not disable policy to obtain a roster. Composition does not hire workers.

Example request: Propose a team for TM-042, but do not launch it.

Start with `coordination recruit TM-042 --json` through the launcher. Report roster names, roles, gaps and proposed/approved state. Do not turn the request into hiring.

Nearby request: Start an approved member belongs to team-dispatch.
