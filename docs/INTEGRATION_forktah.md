# Forktah integration: coord-e2e and voice-cli

Written 2026-09-24. Forktah (`gtownarmy-design/Forktah`) is our fork of CControlCenter
(`controlLogix/CControlCenter`). This branch adds two projects from the same workstation,
and turns one of them into a Claude Code plugin.

## The rule

Where an incoming project and CControlCenter both do the same job, **CControlCenter's
version wins** and the incoming copy is removed. Anything CControlCenter does not already
do is kept whole.

## What came in

| Source | Now at | How |
|---|---|---|
| `coord-e2e` (Agent Roll Call, the four-agent coordination test app) | `e2e/roll-call/` | `git subtree add`, history kept |
| `voice-cli` (Voice CLI 1.0.0, local Whisper push-to-talk for Windows) | `voice-cli/` | `git subtree add`, history kept |
| n/a (new) | `plugins/voice-cli/` and `.claude-plugin/marketplace.json` | voice-cli as a Claude Code plugin |

Only committed source came across. Voice CLI's build outputs (`dist/`, `build/`, the
bundled models) are ignored by its own `.gitignore` and stay on the build machine.

## Duplication map

| Incoming item | What it did | CControlCenter equivalent | Outcome |
|---|---|---|---|
| `coord-e2e/orchestration/four-agent-e2e.json` | agent-orchestration (`ao-topology`) workflow: four agents, stages, gates | agent definitions in `.agentmux/agents/` plus `agentmux spawn --agentdef` and `agentmux run` | **Replaced** by `rollcall-lead`, `rollcall-dev`, `rollcall-imager`, `rollcall-reviewer` |
| `coord-e2e/.claude/skills/agent-verbiage` | shared message words: BRIEF, CLAIM, TOUCH, PROGRESS, ASK, DELIVER, REVIEW, REVISE, ACCEPT, CLOSE, HANDOFF, DONE | agentmux's own coordination primitives (table below) | **Replaced** |
| Board mirror to the workstation forum (`tm comment TM-001`) | run events copied to a machine-wide ticket board | `agentmux journal` and the Control Center's board | **Removed** from the brief and personas |
| `.bytedesk/agent-orchestration/runs/` in `.gitignore` | ignored ao run state | agentmux keeps run state in `~/.agentmux/` | **Removed** |
| The Roll Call app (`server/`, `web/`, `test/`) | a static four-card page and its tests | none. The Terminals view shows live panes; Roll Call is a fixed test product | **Kept**, and its suite joined the gate |
| Voice CLI (the app) | speech to text into any window | none | **Kept whole** |
| Voice CLI's "planned ByteDesk plugin" | a future agent integration named in its README and API docstring | none | **Built** as `plugins/voice-cli`, and both mentions now point at it |

### Old word, new primitive

| agent-verbiage | agentmux |
|---|---|
| BRIEF | `agentmux run assign <run> --worker W --reviewer R --brief T`, then `agentmux post W --kind request` |
| CLAIM / TOUCH | `agentmux claim <path>` … `agentmux release <path>` |
| PROGRESS | `agentmux post <lead> --kind status` |
| ASK | `agentmux post <lead> --kind request`, answered with `--kind reply` |
| DELIVER | `agentmux run submit` |
| REVIEW APPROVE / CHANGES | `agentmux run verdict <job> --pass` / `--fail --reason-file F` (reviewer only) |
| REVISE | `agentmux post <worker> --kind finding` |
| ACCEPT, CLOSE, DONE | `agentmux run complete <run>` (refuses until every job is verified), then `run teardown` |
| HANDOFF | `agentmux journal handoff "<what is left>"` |

## Effect on dispatch

The four `rollcall-*` definitions are in the repository roster, so `choose_roster` can see
them. Two things keep existing behaviour unchanged:

- The lead is the first `role: lead` by name, and `netcap-lead` sorts before
  `rollcall-lead`, so every dispatch keeps the same lead.
- For an unlabelled card, workers also tie-break by name, so `netcap-dev` is still chosen.

A card labelled with a `rollcall-*` capability (`svg`, `javascript`, `web`, …) now recruits
the matching definition. That is the capability matching working as intended.

Checked with `agentdefs.load_all` (no problems, seven repo definitions) and `choose_roster`
on an unlabelled card and on an `svg`-labelled one.

## The gate

Two suites were added to `dashboard/run_tests.sh`, and both follow its scoring rule: exit 0
and a last line ending `failed 0`.

- `dashboard/test_roll_call.sh` wraps `node --test` in `e2e/roll-call/`. It fails on a
  missing summary, and on a run where no tests were found.
- `plugins/voice-cli/tests/test_voice_mcp.py` has 17 checks. It drives the real MCP
  server over stdio against a stub that enforces the app's guards: loopback Host, no Origin,
  bearer token. The gate reaches it through `dashboard/test_voice_mcp.py`, because
  `test_residue.sh` stubs every `dashboard/test_*` when it tests the runner. A suite
  registered by a path outside `dashboard/` would run for real inside that fixture and fail it.

Voice CLI's own pytest suite, 36 tests, needs Windows (WASAPI, SendInput, the tray). Run it
from `voice-cli/` with `uv run pytest`. It is not in the WSL gate.

## Not integrated

The workstation's ticket-board scripts were out of scope for this branch, as was the board
itself. They duplicate CControlCenter's board, dispatch, pool and agentmux: plugin patches,
WSL lead and reviewer keepalive, dashboard keepalive, and the `tm` WSL link. Nothing on
that machine was retired by this integration.
