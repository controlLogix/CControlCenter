# EP-015 / EP-016 handover

*Draft — completed at the end of the run. Sections marked TBD are filled once the
remaining cards close and the end-to-end pass runs.*

## What this was

Agent definitions become first-class, editable objects — global ones shared across repos,
repo-specific ones committed with the code — enforced at launch, assembled into lead-led
teams with a worktree each, editable and hireable from the dashboard. Plus a marketplace
plugin wrapping the workflow as skills, and (EP-016) a dashboard that folds its topics and
shows real task keys.

Architecture: https://claude.ai/artifact/TDiV2FDxYyzs9kdeTtdn4P
Contracts: `docs/CONTRACTS_agents.md` (carries its own amendments table)
Plan and wave schedule: `~/.claude/plans/starry-foraging-haven.md`

The work was **dogfooded**: real `agentmux` panes did the building, coordinated through the
board, three at a time, with the gate green between waves.

## The gate was red before any of this started

The suite had been failing since the board store landed, and nobody had noticed because the
failures were in two suites that had quietly stopped testing anything. Five defects, all
traced to one shift — the board addresses work by KEY, the compatibility surface by integer
row id.

1. **`id` meant two different things.** `POST /api/epics` answered with the key
   (`"EP-014"`), because `ccboard.entity()` sets `id` to the key; `GET /api/epics` still
   returned the integer, as `ccstore.read()` always has. smoke.sh interpolates that value
   into JSON unquoted, so a key string produced a malformed body and the server answered
   "invalid JSON object". Every assertion after the first create fell over.
   Fixed with `_legacy_id()` and `_epic_by_ref()`; `_resolve_key` now takes either address.

2. **Three dropdown entries 400'd on click.** `app.js` still offered `archived`, `todo` and
   `cancelled` after the board store retired them. This is exactly the breakage the comment
   above those lists warns about, and the test written to catch it could not — because it
   repeated the same stale list. smoke.sh now reads the vocabulary from the **served**
   `app.js`, which is the only version of that check that can detect the drift it exists for.

3. **`STATUS_MIGRATION` was never applied to input**, though `ccstore`'s own note said it
   was. It only ever migrated rows already in the database, so a caller still saying `todo`
   was refused by a vocabulary nobody told it had changed.

4. **Soft delete reported success twice.** The row survives, so a second delete re-stamped
   `closed_at` and told the caller it had removed something it had not. An epic's cascade
   also counted children already deleted. Now a repeat delete is 404 and only live children
   cascade — which needed the legacy ladder to catch `ccboard.NotFound` as well as
   `ccstore`'s, or the refusal surfaced as a 500 and read as "the server broke".

5. **A stale test fixture read as a broken security guard.** `test_coordination.sh`'s HTTP
   fixture predated keys and returned no `key`, so `cmd_task_add` and `cmd_task_status` died
   on a `KeyError`. The suite scored that as "failed for the wrong reason" — the identity
   guard had been correct the whole time.

Commit `7a28a35`. Result: 96 assertions in smoke.sh, 53 in test_coordination.sh, green.

## Decisions I made without you

| Decision | Why |
| --- | --- |
| **Pane-name suffix is the ROLE, not the agent name** (contract amendment `62e152c`) | The original banned hyphens in names so the suffix could carry one — but four of the five definitions that must load unchanged are hyphenated, and the filename must equal the name, so no normalisation satisfied both. Roles are a closed vocabulary with no hyphens, so the grammar stays unambiguous. Cost: a pane name says what part it plays, not which definition it runs; recoverable from `board_roster` and the `.agentdef` sidecar. |
| **`description` cap 280 → 2048** | 280 was my arbitrary guess. `hr-recruiter` is 320, and Claude Code's own agent descriptions run longer. A loader that refuses data Claude Code itself writes is wrong; the list view truncates instead. |
| **Definition and team CLI verbs live in `coordination.py`** (ADR-0001, TM-064/TM-065) | The skills were told to drive a CLI that did not exist. `coordination.py` is already the CLI over the board's HTTP API and already turns refusals into the board's own message plus fix hints. A skill shelling `curl` would hide refusals behind status codes; a top-level `agentmux` verb would put board logic in the shell harness, which is the split this codebase keeps. |
| **Collapsible topics are declarative** (EP-016) | You asked for modular. A `data-collapse-key` attribute plus one init pass means adding a topic is HTML and nothing else; `collapsible()` stays for JS-built cards on the same storage. |
| **EP-016 is its own epic** | Your UI request is not "configurable agents". Keeping it separate leaves EP-015's accounting honest. |

## Findings about the harness itself

These are not code defects in the feature; they are things the dogfooding exposed.

- **Dispatch must run inside WSL.** Under Windows Python, `AGENTMUX_HOME` resolves to
  `C:\Users\Nick\.agentmux`, so the brief is written to a Windows path while the pane,
  claims and `cc.db` live in WSL. The worker is pointed at a file it cannot see, and
  `status` reports `0/3` while a worker is genuinely running.
- **A worker running the full gate blacks out the board for everyone.** `run_tests.sh`
  repoints the *live, shared* server. For those minutes `tasks` reports "no open tasks", a
  known epic reports "not found", and a `task-new` lands in a store about to be deleted.
  Nothing warns you. Now C0 in the contracts: workers run their own suite; the gate is the
  orchestrator's.
- **A freshly-booting codex pane swallows its brief.** The send "succeeds", the courier
  queue stays empty, and the pane sits at its banner. Verify with
  `agentmux read <pane> --lines 3`.
- **The codex update modal is real and dangerous.** `agentmux send` refuses to press Enter
  into it, because the default option runs `npm install` and killed a pane once. The brief
  is queued instead.
- **Claims are advisory, and self-made claims outlive their worker.** Two cards needed files
  my `touches` lists omitted, so workers claimed them by hand — and those claims survived
  `collect`, blocking later cards for a full 30-minute TTL. **`release_all` already sweeps
  claims made after dispatch, and collect reported "claims released", yet one survived.
  Root cause not established.** Manual remedy: `agentmux release <path> --for <dead-worker>`.

## Where the workers were better than the brief

Worth recording, because it argues for reviewing rather than just gating.

- **TM-040 refused to build.** It read the frozen contract against the definitions it was
  told to load, found the two requirements contradicted each other, blocked the card and
  wrote nothing. That forced the C1/C5 amendment before three cards built on a broken premise.
- **TM-057 and TM-058 both refused to invent CLI commands** that the contract implied but
  did not define. The second was my scoping miss: TM-064 covered definitions, and I did not
  extend the same reasoning to teams.
- **TM-047 improved on the contract's atomic-write recipe.** I specified `umask(0o077)`,
  copied from `set_auth_setting`. The worker used `tempfile.mkstemp` instead and left the
  reason: umask is process-global and this server is threaded. **`set_auth_setting` still
  has that race.** Out of scope here; worth a card.
- **TM-049 added a sixth hire bound** I had written only as a warning: hire refuses unless
  the listener is on `127.0.0.1`, wired from the server's own bound address.
- **TM-063 corrected my fix.** I suggested hashing collapse keys or capping the map; it
  capped both count and serialised size, noting "digests alone still accumulate forever".

## Defects caught in review

Four of the same family — a suite that exists but does not meet the gate's conventions, and
therefore does not protect anything:

- `cd "$(dirname "$0")/.."` in two suites. Every `.sh` here runs as
  `bash <(tr -d '\r' < file)`, so `$0` is `/dev/fd/63` and that `cd` lands in `/dev`.
- `node` missing from the non-login WSL PATH, taking the gate with it.
- Two suites written but **never registered** in `run_tests.sh` — decoration, as that file
  says of itself.
- A suite that passed five tests and printed unittest's `OK`, which the runner scores as a
  failure because it matches the last line against `failed 0`.

Plus: a node fallback hardcoding my username in a tracked file, which `install.sh` exists to
avoid; an ambiguous `hr-recruiter (claude)` where the parenthetical was the scope and
`claude` is equally a valid cli; and 2048-character descriptions printed inline in a list.

## TBD — filled at completion

- Final card counts and commits
- Plugin eval results (`claude plugin eval --ablation with-without`)
- End-to-end pass evidence
- Production-readiness assessment
