---
name: team-merge
description: Collect completed Agentmux team work into its lead integration worktree, preserving conflicts and review status. Not a release-branch merge.
---

# team-merge

Run commands through the installed package launcher:

```sh
python3 "${CLAUDE_PLUGIN_ROOT}/skills/agent-config/scripts/runtime.py" COMMAND ARGS...
```

Set `AGENTMUX_REPO` to the absolute trusted runtime checkout and `AGENTMUX_DASHBOARD` to the intended local dashboard. Below, `coordination`, `dispatch` and `setup-auth` name the launcher COMMAND, not shell aliases. Use the current runtime caller identity; preserve its refusals and stderr. Linux/macOS or explicitly selected WSL execution is required; native Windows hook execution is not qualified.

Inspect `coordination task-show KEY --json`, `coordination roster KEY --json` and `dispatch status --json`. When collection is authorized, use `dispatch collect KEY`. There is no merge subcommand.

Collection can reap panes, release claims, merge member branches and remove proven-integrated worktrees. It is not a read-only status query. The runtime requires completion evidence and guards integration branch identity, clean trees and managed member branches. Working or idle is not completion. Conflicts and unresolved cleanup preserve work for recovery; do not force-delete branches to make collection succeed.

A submitted result remains for review; collect never closes the card. Report the returned working/idle/submitted/parked/unresolved outcome and evidence. This workflow does not authorize merging this repository rearchitecture branch into main or another release branch.

Example request: Collect the completed TM-042 team work.

Start with `dispatch collect TM-042` through the launcher. Report actual collection outcome and evidence; parked/unresolved means recovery remains. Submitted does not mean reviewed or done.

Nearby request: Merge a release PR into main is outside this workflow.
