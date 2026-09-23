# Build order: configurable agents, teams, and the orchestration plugin

## Context

The architecture is settled and recorded in the artifact
(https://claude.ai/artifact/TDiV2FDxYyzs9kdeTtdn4P). This document is the
**execution plan**: what gets built, in what order, by which pane, and what must be
true before each step starts.

The work is dogfooded — real `agentmux` panes doing the build, coordinated through
the board — so RULE #-0.7 applies throughout: claim before editing, declare
dependencies, journal every step, use the task board. Every task lands on the board
first.

**The governing constraint is file contention, not the stage list.** Claims are
all-or-nothing on a flattened path, so two panes can never hold the same file. Part A
touches a small number of very large files over and over, which serialises it far more
than "six stages" suggests. Part B is in a different repo and is genuinely parallel
from the first minute.

## Decisions carried in from the interview

All six stages plus the plugin this round. Dogfooded with agentmux panes, every task on
the board. Waves of **3** (the board's existing `dispatchWip`/`wipLimit`, left alone —
three full CLI processes writing to the repo is a real limit, not a formality). The
plugin builds in parallel and is dogfooded too.

**Name collisions are a hard error in every scope**, including `.claude/agents`. This
was the one open question and it turns out to cost nothing: there are no collisions
today. `~/.claude/agents/` holds five definitions (hr-recruiter, plc-dev,
plc-test-engineer, scheduler, senior-reviewer); `~/.agentmux/agents/` and both
repo-local directories do not exist yet. Strict from day one, nothing to rename.

## Verified starting state

| Fact | Value |
| --- | --- |
| Board | `cc.db`, live. Active epic **EP-012 — and it is `done`**, so this work needs a new epic (next minted: EP-014, TM-038). |
| Earlier hook's "EP-001" | The bytedesk husk store, **not** `cc.db`. Ignore it; file against the real board. |
| Board config | `dispatchEnabled true`, `dispatchWip 3`, `wipLimit 3`, `requireEpic true`, `requireOnCreate ["body","acceptance"]`, `autoReady "label"`. |
| Readiness | `agent_readiness()` (`ccboard.py:786`) needs body + acceptance + epic + no veto label. A task created with `--body` and `--ac` under an epic is ready automatically. |
| Claims | None active. |
| Panes | `claude` and `codex` live, detached, both `cwd=/mnt/c/Dev/agentmux` — hand-spawned, **not** dispatched workers (names don't match `WORKER_RE`). |
| marketplace repo | Clean, on `main`. |
| agentmux repo | **Dirty — 547 insertions across 12 files**, including every file this build touches. |

# Wave 0 — preflight (me, before any pane starts)

1. **Commit the existing work.** Reviewed: `git diff` scanned for credential material,
   three hits, all prose and filenames — no values. Safe. Commit the 12 modified files
   as their own commit so panes start from a clean `HEAD` and a bad pane reverts with
   `git checkout <file>` without touching your work.
2. **Open the epic.** `coordination.py epic-new "<title>" --body "<why>" --active` —
   the `--active` flag makes it the epic new tasks file into, so this is one command,
   not two. Every `task-new` then inherits it; `requireEpic` is on, so this is not
   optional, and EP-012 being `done` means there is no usable epic until this runs.
3. **File every task** (§Task DAG below) with `task-new --body --ac`, then `task-touch`
   **every** path. This matters more than it looks: `dispatchable()`'s greedy disjoint
   pass (`ccboard.py:1665`) treats a card with **no** recorded touches as overlapping
   rather than safe, so an untouched card silently refuses to run beside anything.
4. **Freeze the interface contracts** (§Contracts) into the repo before any pane starts.
   Parallel panes implementing against an unwritten API diverge.
5. Add `.agentmux/agents/` clarification to `.gitignore` — line 50 currently says
   "Runtime state and logs belong in ~/.agentmux, never here", which reads as an
   instruction to delete the repo-local definitions directory.

# Contracts to freeze first

Three parallel tasks in Wave 1–2 depend on these. Write them down before spawning.

```python
# taskmgmt/agentdefs.py
def load_all(repo_root=None) -> dict:
    """{"agents": [AgentDef], "errors": [{path, reason}],
        "collisions": [{name, paths: [..]}], "rejected": [{path, keys: [..]}]}"""

AgentSpec = namedtuple(...)   # frozen; the only thing dispatch and spawn consume
#   name role cli model auth posture tools_allow tools_deny persona worktree definition

def resolve(name, repo_root=None) -> AgentSpec      # raises Collision / NotFound
def choose_roster(task, cfg, repo_root=None, cli_override=None) -> [AgentSpec]
```

`GET /api/board/agents` returns `load_all()` verbatim plus a per-agent `scope` field
(`repo` / `global` / `claude`). `board_roster` columns are fixed as specified in the
architecture. **Stage-1 contract on `choose_roster`: with no definitions on disk it
returns exactly one spec whose `cli` resolves identically to today** — that is what
makes Wave 1 shippable with zero behaviour change.

# File contention map

This is why the schedule looks the way it does.

| File | Stages that edit it |
| --- | --- |
| `dashboard/server.py` | 1, 2, 3, 4, 6 |
| `dashboard/app.js` | 1, 3, 4 |
| `taskmgmt/dispatch.py` | 1, 2, 5, 6 |
| `dashboard/ccboard.py` | 4, 5, 6 |
| `agentmux.sh` | 2, 5 |
| `taskmgmt/agentdefs.py` (new) | 1, 3, 4 |
| marketplace repo | Part B only — **zero overlap with Part A** |

Four of the six stages want `server.py`, and three want `app.js` and `dispatch.py`.
Stages therefore cannot run as units. The DAG below slices by **file ownership**, so
each task owns its files outright for its duration.

# Task DAG

Sized for one pane each: one coherent change, testable, 1–3 files.

| # | Task | touches | blockedBy |
| --- | --- | --- | --- |
| T1 | Loader: parse, validate, collide, shadow-free strict scopes | `taskmgmt/agentdefs.py`, `dashboard/test_agentdefs.py` | — |
| T2 | Spawn flags + posture ladder + per-agent claude config dirs + new sidecars | `agentmux.sh` | — |
| T3 | Plugin scaffold: manifest, catalog entry, dir structure | marketplace repo | — |
| T4 | Board read op `agents` + `agentdef`/`agentdrop` writes, **and the `FIELDS` extension for T2's sidecars** | `dashboard/server.py` | T1 |
| T5 | Agents view: markup, loader, CRUD handlers, `.warn` block | `dashboard/app.js`, `dashboard/index.html`, `dashboard/style.css` | T1 |
| T6 | Plugin skills: the eight SKILL.md bodies | marketplace repo | T3 |
| T7 | Dispatch seam `choose_roster` + persona into `write_brief` | `taskmgmt/dispatch.py` | T1 |
| T8 | `board_roster` table, indexes, four config keys | `dashboard/ccboard.py` | — |
| T9 | Plugin hooks + MCP server | marketplace repo | T3 |
| T10 | Inference `propose_roster` + `recruit`/`approve`/`roster` ops | `taskmgmt/agentdefs.py`, `dashboard/server.py` | T4, T8 |
| T11 | Approval UI on the task inspector | `dashboard/app.js` | T5, T8 |
| T12 | Plugin evals: cases + graders per skill | marketplace repo | T6 |
| T13 | Teams: name grammar, `collect` fan-out, two-counter pool | `taskmgmt/dispatch.py` | T7, T10 |
| T14 | Worktree create/teardown + namespaced claims | `agentmux.sh`, `taskmgmt/dispatch.py` | T13 |
| T15 | Lead merge + conflict-as-comment | `taskmgmt/dispatch.py` | T14 |
| T16 | `hire` endpoint with the five bounds | `dashboard/server.py` | T10, T13 |
| T17 | Docs + README, register suites in the gate | `README.md`, `dashboard/run_tests.sh` | T15, T16 |

Acceptance criteria per task come from the architecture's per-stage test list; each task
carries 2–4 concrete, checkable ones.

# Wave schedule

Each wave is at most three concurrent panes with disjoint `touches`.

| Wave | Panes | Why it's safe |
| --- | --- | --- |
| **1** | T1 · T2 · T3 | New file, a shell script, a different repo. Nothing overlaps. |
| **2** | T4 · T5 · T6 | `server.py` / frontend trio / marketplace. All need T1's contract, which is frozen. |
| **3** | T7 · T8 · T9 | `dispatch.py` / `ccboard.py` / marketplace. |
| **4** | T10 · T11 · T12 | T10 holds `agentdefs.py` + `server.py`; T11 holds `app.js`; T12 marketplace. |
| **5** | T13 · (T16 waits) | T13 owns `dispatch.py` alone. Wave narrows — this is the serial spine. |
| **6** | T14 · T16 | T14 holds `agentmux.sh` + `dispatch.py`; T16 holds `server.py`. |
| **7** | T15 → T17 | Sequential tail. |

**Part B runs ahead independently.** T3 → T6 → T9 → T12 is a complete four-task chain
in the marketplace repo with no dependency on Part A except the CLI surface names, which
the contracts fix at Wave 0. One pane can own the whole plugin from Wave 1 and finish
around Wave 4.

**Where the schedule collapses:** Waves 5–7. `dispatch.py` is wanted by T13, T14 and T15
in sequence and cannot be split without breaking `collect`. Expect the last third of the
build to be effectively single-pane.

**Highest-risk task: T13.** The name grammar, `collect` fan-out and the WIP recount must
land together — the suffix must start with a letter or `tm-042-7` is ambiguous with card
`TM-0427`, and a half-applied change stops `collect` reaping every dispatched worker,
including the panes building this. It gets a dedicated wave and a green gate before T14.

# Dogfooding protocol

Per task, per RULE #-0.7:

1. `python3 taskmgmt/dispatch.py dispatch <KEY>` — claims the card's touches, sets
   `in_progress` through the gate, writes the brief, spawns the pane and points it at
   the brief.
2. The pane journals what it does and attaches evidence to the card.
3. `python3 taskmgmt/dispatch.py collect` — reconciles; it never closes a card.
4. I run the gate, review the diff, and close the card.

Between waves the gate must be green. A pane that goes wrong is reverted with
`git checkout <its touched files>` — which is safe only because of Wave 0 step 1.

**Bootstrapping caveat:** the team features being built do not exist while they are being
built. Waves are coordinated by hand (and by claims), not by a lead agent. Only from
Wave 5 could the harness start dispatching its own teams, and it should not be trusted to
until T13's gate is green.

# Verification

Per-task: the architecture's stage checklist. Per-wave and before merge:

- `bash <(tr -d '\r' < dashboard/run_tests.sh)` green — the CR strip is the invocation
  convention for every `.sh` here. It swaps `AGENTMUX_HOME` to a tempdir **in the server
  process** and restores it in an EXIT trap.
- New suites print their summary **last**, ending `failed 0`, and are registered in
  `run_tests.sh:155-177` — a suite nothing invokes is decoration.
- `test_agentdefs.py` copies the isolation preamble at `test_board.py:41-48` (set
  `AGENTMUX_HOME` **before** importing ccboard/ccstore/server) and the port-0 harness at
  `:505-523`.
- Every new board op satisfies the checklist at `test_board.py:525-603`: 409 with hints,
  405 on the wrong verb, unknown op 404 and **never 500**, 415 without a JSON content type.
- The ambiguity regression asserted explicitly: `tm-042-dev` → `TM-042` **and**
  `tm-0427` → `TM-0427`.
- A hire body carrying `cli`/`cwd`/`argv` has those fields ignored — asserted, not assumed.
- Plugin: `claude plugin validate plugins/agentmux-orchestration --strict`, then
  `claude plugin details` for always-on token cost, then `claude plugin eval
  --ablation with-without`.
- End to end: create a definition in the browser → approve a roster → the pool dispatches
  a lead → it hires → worktrees merge → `collect` reaps everything → `agentmux list` is
  empty and `claims` shows none held.

# Open risk carried forward

Idle detection does not generalise to teams. For a lead, "idle" may mean *waiting for its
workers*, indistinguishable from stuck. Rule to implement in T13: **a lead idle while any
worker is live is `working`, never `idle`.** Most likely source of a team that hangs
holding its slots.
