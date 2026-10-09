# P01 real shell smoke

The unchanged `hub/demo/smoke_shell.sh` passed on candidate `fba373a06a7b356b49fc778b96be5d6e5ae387b6` under WSL. The complete run, including snapshot creation and cleanup, took 25.291 seconds. No product source or test assertion changed.

The native snapshot came from `git archive` of that exact commit. An independent Git blob comparison verifies all 403 recorded source hashes; the tested files remained unchanged. `shell-smoke-source-check.json` also verifies the saved log and execution harness hashes and records interpreter/tmux/bash versions. The candidate had advanced after the initial source inspection; the executed snapshot's commit, not that earlier observation, is authoritative.

## Observed behavior

- A real hub starts and spawns `calc-worker-smoke_sh` in a real tmux pane using only the shell CLI.
- The pane executes the welcome and direct-message doorbells and acknowledges both messages. Two independent delivery records reach `acked`, with corresponding received/acked events.
- The original smoke's operator-authorized `--as` calls claim and finish its role work. Events preserve `ready`, `claimed` and `done`; the result is `smoke ok`. This is not an LLM-generated implementation or autonomous provider claim.
- Killing the agent produces `dead` and `kill` events. No matching agent sidecar remains.
- The result notification to the fixture's virtual operator remains queued. The smoke does not assert that an absent operator has acknowledged it, and this report does not convert it into an acknowledged delivery.

## Isolation and cleanup

The environment supplies private HOME, Agentmux state, Codex/Claude directories and TMUX_TMPDIR. A private `~/.local/bin/agentmux` wrapper, also selected through AGENTMUX_BIN, executes the snapshot's agentmux.sh. The shell wrapper invokes Bash with `--noprofile --norc`; no operator startup file is loaded. No provider credentials are inherited. The private hub configuration explicitly disables TCP and NATS, and both demo repositories are created below the private HOME. No reset of an existing repository is requested.

The smoke kills its own agent. The evidence harness then stops the owned hub through its private socket, closes only sockets under the private tmux directory, confirms there are no processes with that exact owned environment, and removes the disposable root. No fallback process termination was needed. `cleanupComplete` is true, no remaining owned PID is recorded and the owned root is gone. Tokens generated inside the fixture are removed with it; saved observations exclude token fields and message bodies.

This supports the bounded HUB-24-C01 shell demonstration and its delivery, claim, death and sidecar checks. It does not prove NATS federation, multi-hub orchestration, live dashboard parity, native macOS execution, model-provider behavior, the four provider-backed demo scenarios or P01 acceptance. The earlier completed preservation suites were not rerun.
