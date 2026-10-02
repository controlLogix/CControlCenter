# Hub demo

This folder runs real multi-agent orchestrations (claude, codex and grok together) on
the messaging hub, and scores each run. Design: [`docs/PROTOCOL.md`](../../docs/PROTOCOL.md)
and [`docs/TRANSPORT.md`](../../docs/TRANSPORT.md). Why it exists:
`C:\Dev\findings\2026-09-30_agentmux_communication_failures.md`.

All commands run inside WSL, from `/mnt/c/Dev/agentmux`.

## 1. Watch the hub come up (about 1 minute, no LLM involved)

```bash
bash hub/demo/smoke_shell.sh
```

A shell agent is spawned. The hub rings it, the pane runs `agentmux hub inbox --ack`
itself, and the test then checks four things:
- a direct message is acknowledged
- a role item is claimed and finished
- a killed agent is marked dead

The run ends with `SMOKE PASS`.

## 2. Run an orchestration (3–10 minutes)

```bash
python3 hub/demo/orchestrate.py team        # claude lead decomposes; codex implements; grok reviews
python3 hub/demo/orchestrate.py crossrepo   # report's lead gets calc's worker (another repo) to build what it needs
python3 hub/demo/orchestrate.py swarm       # 3 workers of 3 CLIs race for 4 role items (first claim wins)
python3 hub/demo/orchestrate.py calib       # one codex worker, one item
python3 hub/demo/scoreboard.py              # all runs so far -> evals/orchestrations/SCOREBOARD.md
```

The work happens in two throwaway repos, `~/hubdemo/calc` and `~/hubdemo/report`. They
are reset at the start of every run.

**Watching a run:** in a second WSL terminal, run any of these:

```bash
agentmux hub status                 # agents, delivery states, work states
agentmux hub work list              # every item: who claimed it, what state it is in
agentmux hub events | tail -30      # the audit trail: every bell, modal answer, claim, ack
agentmux attach <session>           # watch one agent's pane live (detach: Ctrl-b d)
```

## 3. What a run proves

Each report in `evals/orchestrations/<run>.json` scores six checks:

| Check | Meaning | Failure class it guards |
|---|---|---|
| E1 | every top-level item ended `done` | work lost or stranded |
| E2 | no delivery ended `dead` | C4, C9 |
| E3 | no doorbell failed: nothing was left unsubmitted, and no identity mismatch occurred | C1, C8 |
| E4 | no agent blocked on a modal, and none died | C2, C5 |
| E5 | every message to a live agent was acknowledged | C10 |
| E6 | the repos' tests pass and the feature works | the work itself |

The report also lists:
- every modal the hub answered, and with which keys
- extra Enters
- bell outcomes
- the last 25 lines of every pane

## 4. Things to try by hand

```bash
agentmux hub start
agentmux hub repo add calc ~/hubdemo/calc --group demo
agentmux hub spawn calc worker w1 --cli codex             # session: calc-worker-w1
agentmux hub spawn calc worker w2 --cli claude            # a second holder of the same role
agentmux hub work add --to role:calc/worker --title "Add calc.cube" --body "Add cube(x) with a test; commit."
agentmux hub work list                                    # exactly one of w1/w2 claims it
agentmux hub post --to role:calc/worker --kind note "FYI to every calc worker"
agentmux hub post --to agent:calc-worker-w1 --kind request "just you"
agentmux hub inbox                                        # the operator's own inbox (results come back here)
agentmux hub kill calc-worker-w1                          # its claimed work returns to the queue
agentmux hub spawn calc worker My-Worker --cli codex      # refused: hyphen reserved, suggests my_worker
```

## 5. Offline tests

```bash
python3 -m unittest discover -s hub/tests -t . -v
```

There are 59 tests. They cover:
- names and addresses
- ordering and idempotency
- first-claim across 8 processes
- leases and dead-agent recovery
- team decomposition
- per-repo claims
- every delivery guard, each against scripted screens: update menu, codex's non-modal
  update banner, login, unknown prompt, copy-mode, busy, booting, paste placeholder,
  stale line, handle mismatch, and menu-by-label with "No, exit" preselected
- a real hub over its socket and over token-authenticated TCP, including `subscribe`
- receipts from codex, claude and grok logs, and the hold alert
- backups, retention, and a backup before every migration
- courier retirement, legacy adoption, and `agentmux post` routed through the hub
- **two hubs federating through a real `nats-server`** (`test_nats_federation.py`,
  skipped if `nats-server` is not installed)

## 6. Federation (NATS)

```bash
nats-server -a 127.0.0.1 -p 4222 &                  # installed at ~/.local/bin/nats-server
printf 'node = "ws1"\nnats_url = "nats://127.0.0.1:4222"\n' >> ~/.agentmux/hub/config.toml
agentmux hub stop; agentmux hub start
agentmux hub status --bridge                        # connected, role subjects served
agentmux hub work add --to role:calc/worker --title "..." --federate   # exactly one hub on the network takes it
```

## 7. From Windows (TCP)

Set `tcp_port = 8790` in `~/.agentmux/hub/config.toml`, then run this in PowerShell:

```powershell
$env:AGENTMUX_HUB_URL = "tcp://127.0.0.1:8790"
$env:AGENTMUX_HUB_TOKEN_FILE = "\\wsl.localhost\Ubuntu\home\nick\.agentmux\hub\operator.token"
python C:\Dev\agentmux\hub\cli.py status
```
