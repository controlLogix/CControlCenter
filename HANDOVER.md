# EP-015 / EP-016 handover

Written 2026-09-23. Read the assessment at the bottom before deciding anything about
deployment; the summary above it is what shipped, not what is safe.

## What this was

Agent definitions become first-class, editable objects — global ones shared across repos,
repo-specific ones committed with the code — enforced at launch, assembled into lead-led
teams with a worktree each, editable and hireable from the dashboard. Plus a marketplace
plugin wrapping the workflow as nine skills, and (EP-016) a dashboard that folds its topics
and shows real task keys.

- Architecture: https://claude.ai/artifact/TDiV2FDxYyzs9kdeTtdn4P
- Contracts: `docs/CONTRACTS_agents.md`, with its own amendments table
- Plan and wave schedule: `~/.claude/plans/starry-foraging-haven.md`
- Sandbox limitation: `docs/TM-068-sandbox-dispatch.md`

The work was **dogfooded**: real `agentmux` panes did the building, three at a time,
coordinated through the board, with the full gate green between waves.

## Final state

| | |
| --- | --- |
| EP-015 | **28/28 done** (23 planned, 5 added from defects found during verification) |
| EP-016 | **4/4 done** |
| Gate | **31 suites, all green** — 941 assertions at baseline, ~1,500 now |
| Plugin | 9 skills, hooks, MCP server; `claude plugin validate --strict` passes |
| Eval | `--ablation with-without` run: 9 trigger cases, mean **Δ +0.56** |
| End-to-end | Complete, evidence at `tmp/TM-066/evidence.md` |
| Residue | No worker panes, no claims held |
| Commits | 18 in agentmux (**unpushed**), 5 in the marketplace (**unpushed**) |

## The gate was red before any of this started

Five defects, all from one shift — the board addresses work by KEY, the compatibility
surface by integer row id. Fixed in `7a28a35`.

1. **`id` meant two different things.** `POST /api/epics` answered with the key; `GET`
   returned the integer, as it always had. smoke.sh interpolates that value into JSON
   unquoted, so a key produced a malformed body and the server said "invalid JSON object".
2. **Three dropdown entries 400'd on click.** `app.js` still offered `archived`, `todo`,
   `cancelled` after the board retired them. The test written to catch exactly this could
   not, because it repeated the same stale list. smoke.sh now reads the vocabulary from the
   **served** `app.js`.
3. **`STATUS_MIGRATION` was never applied to input**, though the module comment said it was.
4. **Soft delete reported success twice** and cascades counted already-deleted children.
5. **A stale fixture read as a broken security guard** — no `key` in the response, so the
   CLI died on `KeyError` and the suite scored the identity guard as broken. It was fine.

## Decisions I made without you

| Decision | Why |
| --- | --- |
| Pane-name suffix is the **role**, not the agent name (`62e152c`) | The original banned hyphens in names so the suffix could carry one — but four of the five definitions that must load unchanged are hyphenated, and the filename must equal the name. The two requirements contradicted each other. |
| `description` cap 280 → 2048 | 280 was my guess. `hr-recruiter` is 320 and Claude Code's own descriptions run longer. A loader that refuses what Claude Code writes is wrong. |
| Definition **and** team CLI verbs live in `coordination.py` (ADR-0001) | Skills were told to drive a CLI that did not exist. `coordination.py` is already the CLI over the board's HTTP API and turns refusals into the board's own message plus fix hints. |
| Sandboxed postures **refuse dispatch** rather than auto-upgrading | See the assessment. Quietly escalating to `unrestricted` would have defeated decision 7 while looking like a fix. |
| Collapsible topics are **declarative** | You asked for modular. A `data-collapse-key` attribute plus one init pass means adding a topic is HTML and nothing else. |
| EP-016 is its own epic | Your UI request is not "configurable agents"; separating it keeps EP-015's accounting honest. |

## Five defects that only end-to-end verification could find

All 31 suites passed throughout. Each tested its own piece correctly. These are what the
pieces failed to do **together**:

1. **No CLI for definitions** (TM-064). Skills were specified to drive a CLI; only HTTP
   existed. The worker refused to invent verbs and blocked.
2. **No CLI for teams** (TM-065). Same gap, my scoping miss — I fixed it for definitions and
   did not extend the reasoning to teams.
3. **Roster inference was never implemented** (TM-067). `choose_roster` returned only a lead.
   A lead may only hire an *approved* name, no worker was ever proposed, so no lead could
   ever hire one. The central loop was unreachable. I never filed a card for it.
4. **Sandboxed postures cannot coordinate** (TM-068). See the assessment.
5. **Rubrics no agent could pass** (TM-069). Two eval cases scored 0.00 in *both* arms.

## Where the workers were better than the brief

- **TM-040 refused to build** on a contract whose two requirements contradicted each other,
  and blocked rather than guessing. That forced the C1/C5 amendment before three cards built
  on a broken premise.
- **TM-047 improved on my atomic-write recipe.** I specified `umask(0o077)`, copied from
  `set_auth_setting`. It used `tempfile.mkstemp`, noting umask is process-global and this
  server is threaded. **`set_auth_setting` still has that race** — worth a card.
- **TM-049 added a sixth hire bound** I had written only as a warning: refuse unless the
  listener is on `127.0.0.1`, read from the server's own bound address.
- **TM-063 corrected my suggested fix.** I proposed hashing collapse keys; it capped count
  and serialised size instead, noting "digests alone still accumulate forever".
- **TM-068 chose to refuse rather than escalate**, and said so in writing.

## Defects I caught in review

Four of one family — a suite that exists but does not integrate with the gate, and therefore
protects nothing: `cd "$(dirname "$0")/.."` (twice — `$0` is `/dev/fd/63` under this repo's
invocation, so it lands in `/dev`); `node` missing from the non-login WSL PATH; two suites
never registered; one suite that passed five tests and printed unittest's `OK`, which the
runner scores as failure.

Plus: a node fallback hardcoding my username in a tracked file; an ambiguous
`hr-recruiter (claude)` where the parenthetical was the scope and `claude` is equally a valid
cli; 2048-character descriptions printed inline in a list; 2,862 lines of eval traces staged
for commit under gitignored `tmp/`; and a worker that committed its own work directly,
bypassing review.

## Operational findings about the harness

- **Dispatch must run inside WSL.** Under Windows Python, `AGENTMUX_HOME` resolves to
  `C:\Users\Nick\.agentmux`, so the brief is written where the pane cannot see it and
  `status` reports `0/3` while a worker is running.
- **A worker running the full gate blacks out the board for everyone.** `run_tests.sh`
  repoints the *live, shared* server. For those minutes `tasks` reports "no open tasks" and a
  known epic reports "not found". Now C0 in the contracts.
- **The dashboard caches Python modules.** A worker's change to `agentdefs.py` has no effect
  until the server restarts — so a live HTTP check between gate runs can be testing stale code.
- **A freshly-booting codex pane swallows its brief.** The send "succeeds" and the courier
  queue stays empty. Verify with `agentmux read <pane> --lines 3`.
- **The codex update modal is real.** `agentmux send` refuses to press Enter into it, because
  the default option runs `npm install` and killed a pane once.
- **Claims are advisory and self-made claims outlive their worker.** `release_all` sweeps
  claims made after dispatch and collect reported "claims released", yet one survived and
  blocked a card for twenty minutes. **Root cause not established.**
- **`claude` is not on the WSL PATH**, so no worker can run `claude plugin eval`. Workers
  author; the orchestrator runs anything needing that CLI.

## What the eval actually measured

Nine trigger cases, `--ablation with-without`, three runs per arm, $4.94:

| Skill | Δ |
| --- | --- |
| agent-config, agent-edit, agent-new, agent-remove | **+1.00** |
| agent-doctor | **+0.57** |
| team-compose, team-dispatch, team-merge | **+0.33** |
| agent-roster | **0.00** |

`agent-doctor` first scored **0.00** and was falsely condemned by a conjunctive rubric where
four-of-five requirements scored the same as none. Repairing the rubric revealed +0.57. Had I
believed the first number, I would have "fixed" a working skill.

`agent-roster` had the same broken rubric, and after repair its delta is still **zero**. It
adds nothing a bare agent does not already do.

**Caveat that belongs beside these numbers:** three runs per arm is a small sample, and
`agent-roster-trigger` has scored −0.33, 0.00 and 0.00 against three different rubrics. An
eval number measures the *skill-and-rubric pair*. The delta is the trustworthy part.

18 of the 27 authored cases (the near-miss and workflow sets) have **never been run**.

## Production-readiness assessment

**Do not deploy this as a multi-user or network-reachable system.** What follows is true,
not cautious.

**The dashboard port is unauthenticated.** `127.0.0.1:8787` has no authentication of any
kind. `read_cc_body`'s Origin allowlist stops a *browser* on another origin and nothing else
— a non-browser client omits the header and is treated as same-origin, which is exactly how
the test suite drives it. **Any local process that can open a socket can call every endpoint**,
including `agentdef`, `agentdrop` and `hire`.

**The hire bounds are defence in depth, not authentication.** All six are real — name-only
body, approved-roster requirement, two config flags both defaulting off, a two-slot
semaphore, posture clamped by `AGENTMUX_NO_BYPASS`, and refusal unless bound to `127.0.0.1`.
Together they reduce the exposure from "spawn arbitrary argv as you" to "start a definition a
human already approved, at its declared posture, two at a time". That is a genuine reduction
and it is **not** a security boundary. A security review will ask about this first, and the
honest answer is that the bounds assume every local process is trusted.

**The posture ladder does not work for dispatched workers.** Decision 7 was that tool and
permission limits are enforced at launch. They are — for hand-spawned panes. A *dispatched*
worker cannot be sandboxed at all: `codex --sandbox` denies `/tmp`, where the tmux socket
lives, so the worker cannot claim, journal, attach evidence or prove identity. TM-068 makes
dispatch **refuse** such a posture rather than silently upgrade it, which keeps the limitation
visible instead of hidden. But the practical position is: **every dispatched worker runs
unrestricted**, and that is not a configuration choice you can currently make differently.

**Identity is not a security boundary either**, and `coordination.py` already says so: every
agent runs unrestricted with full filesystem access and could set `$AGENTMUX_AGENT` or write
the ledger directly. It prevents mistakes, not attacks.

**What is genuinely solid**: the board's gates and refusals, the claim interlock for honest
actors, the test gate at 31 suites, atomic definition writes with checksum guards, the
dispatch→collect lifecycle including lead-last reaping and orphan parking, and the merge step
refusing a dirty tree or a branch it did not create.

**What is thin**: the end-to-end loop has been exercised **once**, on a trivial card, with a
clean merge by construction. Conflict handling, multi-worker teams, and the WIP interaction
between leads and panes are implemented and unit-tested but not proven under real load.

**Known-weak, in priority order**

1. Unauthenticated port — architectural, out of EP-015's scope, needs a token or a reverse proxy
2. Dispatched workers cannot be sandboxed (TM-068 limitation)
3. `set_auth_setting`'s `umask` race in a threaded server
4. The claim leak whose root cause is not established
5. `agent-roster` skill shows no measurable value
6. 18 eval cases never run
7. `choose_roster` picks the first lead by name — one added definition changes every dispatch

## Things I changed on your machine

- `dashboardMayHire` was set **true** for the end-to-end pass and **restored to false**.
- The codex update modal was answered "skip until next version" so it would not interrupt
  twenty-odd panes. That writes a small codex preference.
- Two e2e agent definitions were created and **dropped**; their worktrees and branches were
  pruned. The roster is back to the original five.
- Twelve `claude-eval-*` temp directories were removed — the eval tool warns they contain
  agent-written content it could not seal on Windows.
- **Nothing has been pushed.** 18 commits in agentmux and 5 in the marketplace are local.
