# Orchestration you can start from either side

## Context

Today there is exactly one orchestrator: a human — or a Claude Code session acting
for one — at a terminal typing `agentmux run start`. That worked in the live test
on 2026-09-24: run `bdae05` opened, `netcap-dev` built the `nettraffic` package,
`netcap-reviewer` found a real defect cross-model, a second job fixed it, the gate
opened at 2/2, agents were torn down.

It also showed the two gaps this closes.

**You have to be here.** Nothing orchestrates unless a session is open. The
dashboard watches; it cannot act.

**The run and the board do not talk.** `run complete bdae05` closed the run and
said nothing about `TM-083`, which sat `open` with five unticked acceptance
criteria until it was noticed by eye; `EP-021` stayed open behind it. Two correct
gates with no wire between them.

Outcome: start an orchestration from a session as now, **or** from the CCC, where
an LLM agent in its own pane orchestrates autonomously — opening runs, spawning
worker and reviewer, briefing them, collecting verdicts, completing runs and
closing cards. An on/off switch in Settings, a Runs view to watch it, and a way
for it to reach you when it needs you.

## Decisions taken

| | |
|---|---|
| What orchestrates on the CCC | An LLM agent in its own tmux pane, not a policy loop |
| Autonomy | Full, including ticking acceptance and closing cards |
| The setting | On/off for the CCC orchestrator; sessions unaffected |
| Scope | Configurable — `goal` (default), `epic`, `queue` |
| Three failed reviews | Park the card, stop touching it, surface it; never force |
| Watching | A new **Runs** entry in the rail |
| Notifications | Dashboard always; desktop toast by default; command hook for anything else |

---

## 1. Authority — the blocking problem

`taskmgmt/coordination.py::orchestrator_identity` proves orchestrator-ness by the
**absence** of `$AGENTMUX_AGENT`:

```python
env = os.environ.get("AGENTMUX_AGENT")
if env and (not allow_test_identity or os.environ.get("AGENTMUX_TRUST_IDENTITY") != "1"):
    raise IdentityError(f"identity: {verb} is the orchestrator's to call, and this is the {env!r} pane. ...")
```

Every pane sets that variable, so an orchestrator agent in a pane is refused by
`run start`, `assign`, `complete` and `teardown`. Naming the pane `orchestrator`
does not help — `resolve_identity` routes that name back here with
`allow_test_identity=False`, which always raises. `AGENTMUX_TRUST_IDENTITY=1` is
the test-only bypass and RULE #-0.7 forbids it in the harness or a brief.

### The fix: a warrant — a positive credential that narrows the refusal

A negative test is not extensible: there is no value you can put in the
environment meaning "yes, more so". So the credential is added as a **second,
narrowing condition on the existing refusal**, never a replacement — otherwise
refusal stops being the default.

**Two files**, both `0600` under `$AGENTMUX_HOME`:

- `orchestrator.warrant` — JSON: `version`, `agent` (the one pane it authorises),
  `secret` (64 hex), `issued_at`, `expires_at`, `issued_by`, `cli`.
- `orchestrator.env` — one line, `AGENTMUX_ORCHESTRATOR_WARRANT=<secret>`, sourced
  into **that pane only**.

> **Correction to an earlier draft of this plan.** The secret must *not* go in
> `$AGENTMUX_HOME/env`. `agentmux.sh:611` sources that file into **every** pane, so
> it would hand the credential to every worker and leave only the name binding
> standing. A separate file, sourced only when the warrant's `agent` equals the
> pane name, is the fix.

`orchestrator_warrant()` (new, in `coordination.py`, directly above the guard it
narrows) returns the warranted name or `None`, and never raises. All must hold:
env secret present and `^[0-9a-f]{64}$`; warrant is a regular file, not a symlink,
`st_nlink == 1`, owned by us, `mode & 0o077 == 0` (the same check `agentmux.sh`
already applies to `$ROOT/env`); `version == 1`; `secrets.compare_digest` on the
secret; `agent` matches `NAME_PATTERN`, equals `$AGENTMUX_AGENT`, **and is not the
literal string `orchestrator`**; `expires_at` in the future.

**The reserved name is load-bearing.** `resolve_identity` routes
`who == "orchestrator"` straight into `orchestrator_identity` with
`allow_test_identity=False`. A warrant naming `orchestrator` would therefore let a
pane acquire the *virtual* identity and turn `test_coordination.sh:372` red.
Reserved on both sides — the guard rejects it and `orchestrator start` refuses to
mint it. That existing test should be **strengthened**: run it again with such a
warrant present and assert it is still refused, or the rule is untested and will
later be deleted as redundant.

**One changed line** in `orchestrator_identity`, ordered so the legacy
`AGENTMUX_TRUST_IDENTITY` bypass short-circuits before any filesystem access and
the existing message text is unchanged up to an appended hint — every suite
substring-matches `"orchestrator's to call"`:

```python
if env and not (allow_test_identity and os.environ.get("AGENTMUX_TRUST_IDENTITY") == "1") \
        and orchestrator_warrant() != env:
```

**`resolve_identity` is not touched.** Verdicts, submits, claims, journal writes
and every board write go through it and will never consult the warrant. That is
the containment: **the warrant buys exactly four verbs** — `run start`, `assign`,
`complete`, and `teardown` (which gets it free, because `agentmux.sh:1301` already
calls the Python function rather than reimplementing the check in shell).

**Expiry is the dead-man's switch.** Default 8 hours. A forgotten warrant
self-revokes.

**Deny `--force` to a warranted caller** in `cmd_complete`. Two lines. Without
them the entire verification gate is one flag deep for an agent that decides it
has waited long enough, and "FORCED" in a ledger is only a control if someone
reads ledgers.

**Audit:** add `"via": coordination.orchestrator_pane()` to the `start`/`assign`/
`complete` events. `fold()` ignores unknown keys. Without it the ledger cannot
distinguish an operator-driven run from an autonomous one at all.

### Why not the dashboard-as-proxy alternative

Having the server process (no `$AGENTMUX_AGENT`) run the verbs on the pane's
behalf sounds safer and is **weaker**: port 8787 is unauthenticated on loopback, so
a worker pane would not need a warrant, a name or a file — it would need `curl`. It
also forks the implementation, giving one gate two paths to drift between, and puts
a subprocess-spawning verb on an unauthenticated port. Rejected.

### No new role

Do **not** add an `orchestrator` value to `--role`. `dispatch.ROLES` and
`WORKER_RE` are card-scoped and the orchestrator is not. The name
`ccc-orchestrator` does not match `WORKER_RE`, so `key_of_worker()` returns `None`
and `dispatch`/`collect`/`pool` ignore it for free. Spawn it as `--role lead`.
This removes the five-file vocabulary change an earlier draft proposed.

**The honest limit**, in RULE #-0.7's own register: this is not a security
boundary. Every agent runs unrestricted, so any of them can read the warrant. It
stops *mistakes* — a worker pane wandering into `run complete`, a verdict
attributed to the wrong agent — which is what actually goes wrong. The rule file
should gain a sentence naming the warrant explicitly, so nobody later cites it as
authentication.

### What must remain impossible — the test list

Existing negatives stay green **unedited** (suites use a throwaway
`AGENTMUX_HOME`, so no warrant is in scope and every refusal is byte-identical):
`test_run.sh:247-256`, `:263-272`, `:194`, `:196`, `:302-317`, `:176`;
`test_coordination.sh:356-370`, `:381-389`.

New block in `test_run.sh`, `--- the dashboard orchestrator's warrant ---`:

1. valid warrant for `ccc-orchestrator`, but `AGENTMUX_AGENT=worker-x` with the
   correct secret → refused *(name binding)*
2. warrant file present, secret **absent** from env → refused *(the file alone is
   not authority)*
3. wrong secret → refused *(`compare_digest` is real)*
4. mode `0644` → refused *(the permission check is not decorative)*
5. `expires_at` in the past → refused *(the dead-man's switch is real)*
6. warrant minted under a different `AGENTMUX_HOME` → refused
7. **paired positive**, without which none of the above discriminate: correct
   name + secret + `0600` + unexpired → `start`, `assign`, `complete` all succeed
   and the `start` event carries `"via": "ccc-orchestrator"`
8. `complete --force` from a warranted pane → refused; from outside a pane → fine
9. **with a valid warrant in scope**, a worker still cannot verdict its own job —
   proves the warrant does not leak past the four verbs into `resolve_identity`
10. orchestrator + `verdict --by rev-a` → refused; and without `--by` → refused as
    `is reviewed by rev-a`. Both routes closed.
11. orchestrator + `claim --holder rev-a` → refused. The warrant confers no
    delegation.

---

## 2. The orchestrator agent

A definition at `.agentmux/agents/orchestrator.md` (`role: orchestrator`,
`worktree: none`, `max_instances: 1`), whose persona carries the operating loop:
read scope → pick work → open run → spawn worker + cross-model reviewer → brief
from the card's own body and acceptance criteria → wait → collect verdict → on
pass, tick acceptance with evidence and close the card → complete the run → tear
down → next.

Reuse `taskmgmt/dispatch.py` wholesale rather than reimplementing: `pick()`,
`dispatch_one()` (spawn → claim → start → brief, with rollback), `collect_one()`,
`write_brief()`. That sequence is already correct and tested (`test_dispatch.py`).

**Scope** (`orchestratorScope`): `goal` — one stated request, one run, stop when
done (default); `epic` — every task in a nominated epic; `queue` — keep pulling
from `/api/board/dispatchable` until switched off.

**Escalation.** On the third failed verdict, `run.py` already calls
`record_notice(..., "blocked", ...)`. The orchestrator parks the card, releases
claims, stops touching it, notifies, and — in `epic`/`queue` scope — carries on
with unrelated work. It never uses `run complete --force`.

---

## 3. Settings

Board config, following the existing pattern: add to `DEFAULT_CONFIG` in
`dashboard/ccboard.py`, register in the matching bucket, and it is seeded,
validated, audited and served for free.

| key | type | default |
|---|---|---|
| `orchestratorEnabled` | bool | `False` |
| `orchestratorAgent` | name (new `CONFIG_NAMES` bucket, `""` allowed) | `""` |
| `orchestratorScope` | choice `goal`/`epic`/`queue` — reuse the `autoReady` precedent | `"goal"` |
| `orchestratorNotify` | bool | `True` |
| `orchestratorNotifyCommand` | string | `""` |

Add `ORCHESTRATOR_KEYS` mirroring `DISPATCH_KEYS` so `doctor` can ask for this
policy without knowing the names.

**Deliberately not configurable:** `orchestratorCli`, model and posture. Those come
from the on-disk definition via `agentdefs.resolve()`, because `hire`'s fifth bound
is *"Only id and name are read from the wire… resolve the current definition from
disk"* — a config key that overrides the definition makes that bound decorative.
Nor `orchestratorWip`: concurrency is already bounded by the run gate's `BLOCKING`
states, `dispatchWip` and the slot semaphore, and a fourth number that can disagree
with the other three is a bug generator. One orchestrator at a time is an
*invariant*, enforced against `live_agents()`, derived and never stored.

**Do not reuse `dashboardMayHire`** as the gate. Hiring a roster member onto a card
and starting an orchestrator are different acts; one switch for two means you
cannot have one without the other.

**UI:** a `settings:orchestration` card, inserted **between `settings:auth` and
`settings:resources`** — insert, never reorder, since the order is asserted; and it
sits beside `auth` because both are "what this machine is permitted to do". Built
with the `teams.js` `SETTINGS`-array pattern driving `window.CCC.settingEditor`.
Registered via `registerCard('settings', …)` from the new `runs.js`, so **`app.js`
and `teams.js` do not change at all**.

The card also renders a **preconditions checklist** with the existing
`settingList` idiom — listener is loopback · `orchestratorEnabled` · definition
resolves · role is `lead` · none already running — so you can see exactly why the
start control is absent rather than guessing. Plus the resolved definition
read-only (`netcap-lead · codex · unrestricted`), and the terminal equivalents with
copy buttons, as the Auth card already does.

Data source: `GET /api/board/meta`, which already carries `config` and is far
lighter than `/api/board/board`.

**Start.** The dispatch strip's *"no button here on purpose"* comment is right and
stays — but read what it forbids: a **pool**, an unbounded loop with nobody in the
room. `boardteams.hire` already proves the other case: a single, named, bounded,
operator-initiated spawn can be a click if it is fenced. The control therefore
lives on the Runs view, not the dispatch strip and not in Settings (a settings card
that starts a process is a category error), inside a collapsed `<details>` — the
pattern already tested for the GitHub write forms — with a textarea for the request
and a `window.confirm` naming the real resolved agent, cli and posture.

Seven bounds: five from `hire` verbatim, plus **`spec.role == "lead"`** (refuse a
worker or reviewer definition as orchestrator) and **one live orchestrator**
(refuse if already in `live_agents()`; a `TmuxUnavailable` refuses too — unknown
liveness is not permission). Only `request` is read from the wire.

**Stop** is the warrant. Turning the setting off unlinks
`orchestrator.warrant` first, then the env file, then kills the pane — revocation
before anything else, so a pane surviving the kill is already powerless. There is
deliberately **no force-complete control anywhere**: a page that can force-complete
launders a failed review into a closed run, which is precisely what `run.py` exists
to prevent.

---

## 4. Watching it — the Runs view

Runs have **no HTTP surface at all**; nothing in `dashboard/` reads
`~/.agentmux/runs/`. Two read-only GETs, routed in the **shared** block beside
`/api/feed` so POST returns 405 rather than falling through to 404 — the mistake
that block's own comment records. Not under `/api/board/…`, whose op regex is
`[a-z]{1,16}` with no slash.

- `GET /api/runs?limit=N` — per run: id, request, complete/forced, jobs,
  verified/total, what blocks completion, stale map.
- `GET /api/runs/<6hex>` — `cmd_status --json` verbatim, plus per-job sidecar
  **presence** (`brief: bool, submission: bool, verdicts: int`).

Three non-negotiables:

1. **Import `run.fold` / `load_events` / `derive_stale`. Never re-implement the
   fold** — two folds of an append-only log is two answers to what happened.
2. **Validate the id with `run.valid_run()` before any path join.**
3. `derive_stale` raises `TmuxUnavailable`; catch it and return `stale: null`
   (unknown), never `{}` (none). A row claiming everyone is alive because tmux was
   unreachable is the exact lie `stale` exists to prevent.

**Do not serve `submission.md` or `verdict-N.md` bodies in v1** — unbounded
agent-authored text. Presence counts answer the question without owning that
surface. **The server never writes `events.jsonl`**: `append_event` is `O_APPEND`
sized to `EVENT_MAX` for atomicity, and a second writer with different size
discipline breaks the guarantee the whole design rests on.

A new `viewRuns` in the rail — your call over the alternative of a fifth Status
tab. The trade-off, recorded: a rail entry costs a nav button, an icon and
`showView` plumbing, and takes the rail to eight; it buys room for the job table,
which a Status tab would cramp.

What a watcher sees per run: a summary chip line (`a3f19c · open · 3/5 verified`,
with `COMPLETE (FORCED)` as an error chip because a forced completion is the most
important thing about a run); a **blocking line in prose**, which is the question
operators actually have — *"Blocking: a3f19c/2 submitted, waiting on
netcap-reviewer · a3f19c/4 rejected, attempt 2 of 3"*; then a job table of
job/state/worker/reviewer/attempts/last/flags. Attempts render `2/3` against a
`maxAttempts` served in the payload — `tries=2` means nothing without the ceiling,
and `MAX_ATTEMPTS` must not be hardcoded in JS. Verified rows say *verified by
netcap-reviewer · 14:22:07*. Claims come free from `all_claims()`.

**Worker and reviewer cells are `markAgent(...)`** — that is the whole reuse of
`7f2b944`, and why the marking system is decoupled from rendering: a finished agent
goes plain on the next tick without this panel re-rendering.

Poll split: the list endpoint already folds, so the 5s poll renders every summary
and blocking line from `GET /api/runs` alone; `GET /api/runs/<id>` is fetched only
for cards the operator has **open**. No SSE — the pane is already streamed, and
clicking the name drops you in it.

### The feed — the cheapest win here

`FEED_SOURCES` already contains `"run"`, `FEED_SOURCE_LABELS` already maps
`run: 'runs'`, and **Settings → Feed already shows a "runs" checkbox with nothing
behind it.** Adding a server block makes an existing control mean something, with
zero frontend change.

Emit only state changes that change what a human should do: `start` (info),
`verdict` pass (info), `verdict` fail (**warn**), third failure/escalation
(**error**), `forced` (**error**), `complete` (info).

Excluded on purpose: `assign`, `working` and `submit` — high volume, nothing to act
on, and they would drown journal and chatter at the 200-line cap. Also excluded:
derived staleness, which is computed at read time and would re-emit with a fresh
timestamp on every poll, permanently pinning itself to the top of the feed.

---

## 5. Getting your attention

The spine exists and dead-ends. `run.py::record_notice` journals **and** calls
`notify_orchestrator()`, writing a `notify-failed` event if either leg fails — its
docstring names the bug it was written for: *"The one message whose entire purpose
is to reach a human was the one that could vanish silently."* That notice lands in
`~/.agentmux/inbox/orchestrator.jsonl`, and **nothing reads it but the
`agentmux inbox` CLI.**

Four tiers; only the first is unconditional.

1. **In the dashboard — always.** Inbox entries become a read surface: a badge on
   the rail and rows in the Status feed. No config, works whenever it is open.
2. **Desktop toast — on by default** (`orchestratorNotify`). Verified: WSL reaches
   the WinRT toast API through `powershell.exe` interop. BurntToast is *not*
   installed, so use raw WinRT and keep the no-dependency posture.
3. **Anywhere else — `orchestratorNotifyCommand`.** A command run with the subject
   and body on stdin. You wire ntfy, Pushover, Slack, email — whatever you already
   use. The repo gains no transport and no dependency.
4. **Reaching a Claude session.** The orchestrator posts to the inbox and chatter,
   where a live session reads it. Stated precisely because it matters: **the
   orchestrator cannot itself push to the Claude app** — `PushNotification` is a
   tool a *session* holds, not something an arbitrary process can call. It leaves a
   message a session picks up, and that session can then notify you. With the
   dashboard closed and no session open, tiers 2 and 3 are what reach you.

**What warrants interrupting you:** escalations (three failed reviews, a card
parked, an agent dead mid-job) and a whole orchestration finishing. Nothing else —
not per-job progress, not spawns, not passing verdicts. A notification you did not
need is annoying in a way that accumulates.

---

## 6. Closing the loop the EP-021 failure exposed

`run complete` knows the task key on every job and says nothing about it. Make it
report cards still open, and have the orchestrator close them: tick acceptance,
attach evidence, `POST /api/board/status done`. Board writes take a free-text
`actor` with no identity check, so this needs no new mechanism — the orchestrator
acts as `actor: "orchestrator"` and every write is audited in `board_history`.

---

## 7. The operator gate — added after the plan was approved

**You asked for this mid-build and it changes the autonomy model**, so it is recorded
here rather than left in the code: *"before the orchestrator completes orchestration,
it should allow me to review the changes... once I give the confirmation, he can close
it."*

Autonomy is now **full up to completion**, not through it. The orchestrator opens runs,
spawns, briefs, collects verdicts and fixes rejections without you; at the point where
it would declare the work finished, it stops and asks.

**Why this is the right place for the stop.** A reviewer verdict answers *"was the job
done as briefed"*. It cannot answer *"was that the right job"*, because the same
orchestrator wrote the brief the reviewer checked against — so an orchestrator that
misreads what you wanted produces a run where every job passes review and the whole
thing is wrong. This is the risk the approved plan already flagged under *Acceptance
becomes self-asserted*; the gate is the answer to it.

**It is enforced, not asked for.** `run.py::approval_blocks_completion` is consulted by
`cmd_complete` inside the same lock as the verification gate, so a persona that
"forgets" cannot complete anyway.

- The decision lives in `APPROVAL.json` (0600) in the run directory, and also lands in
  the ledger as a `review` event via `append_event`.
- **`--force` does not override it.** `--force` exists for a run whose agents died,
  which is an accident; completing over a stated human objection is a decision, and no
  flag on that command should be able to make it.
- **The approval pins bytes.** It records `digest()` of every submitted file, and
  completion re-digests. Work changed after you approved it is not approved: the view
  shows `approval out of date` and the gate refuses. Without this, "approved" only ever
  meant "approved something".
- **Approval is not a substitute for review.** A run with an unverified job cannot be
  approved at all — the two gates are not interchangeable.
- **A run nobody reviewed by hand still completes.** The gate refuses a decision that
  was *made and defied*; it does not demand a browser click from you completing your
  own run at a terminal. There, you are the approval.

**The medium is the Runs view**, which is why it was already phase 1. The review block
shows the diff of exactly the files the run submitted, measured from the commit the run
started at — which meant recording a `base` on the `start` event, because `git diff
HEAD` goes empty the moment a worker commits and would have shown you nothing. Files
the run *created* are rendered too, via `--no-index`; most runs create rather than edit,
and without that the eight new files of the `nettraffic` run would have been reviewed
blind. Approve, or request changes with a reason the orchestrator can act on.

## Verification

1. Turn on **Settings → Orchestration**; confirm the Runs view shows the
   orchestrator pane and `agentmux list` shows it live.
2. Start an orchestration against a scoped goal. Watch Runs show the run open, job
   assigned, worker and reviewer spawned, submission, verdict, gate opening.
3. Confirm the card closes — acceptance ticked, evidence attached, status `done`,
   epic rolled up. The `EP-021` failure, not repeated.
4. Turn the setting off mid-run; confirm it stops and the run is intact, not
   orphaned. Confirm the token is revoked and orchestrator verbs refuse again.
5. Force three review failures on one job; confirm the card parks, nothing is
   force-completed, and a notification arrives.
6. Pull the network from the notify command; confirm the `notify-failed` event
   lands in the ledger rather than the message vanishing.
7. Suites green, with the identity negatives unchanged: `test_run.sh`,
   `test_coordination.sh`, `test_dispatch.py`, `test_board.py`, `test_e2e.sh`
   (its settings-card assertion gains `settings:orchestration`),
   `test_frontend_teams.sh`.

## Files

The pattern, once: a new capability here is a config bucket in `ccboard.py`, a
store-shaped module beside `boardteams.py`, a route arm in `server.py`, markup in
`index.html`, one self-registering view script, and a test per layer.

**Authority** — `taskmgmt/coordination.py` (new `orchestrator_warrant()`, one
changed line in `orchestrator_identity`, `WARRANT` constant; `resolve_identity`
untouched) · `taskmgmt/run.py` (`via` on events, `--force` denied to warranted
callers) · `agentmux.sh` (drop `--by` from `cmd_run` start/complete, source
`orchestrator.env` in `cmd_spawn`, new `cmd_orchestrator start|stop|status`).

**Dashboard** — `dashboard/ccboard.py` (config keys + `CONFIG_NAMES` +
`ORCHESTRATOR_KEYS`) · `dashboard/boardorch.py` (**new**, sibling of
`boardteams.py`, reusing its `HireForbidden`/`HireUnavailable` so the existing
403/503 ladder needs no widening) · `dashboard/server.py` (two GETs, one POST, feed
block) · `dashboard/index.html` (settings card, rail entry, `runs.js` **above**
`app.js` — that ordering is load-bearing) · `dashboard/runs.js` (**new**, modelled
on `teams.js`) · `dashboard/style.css`.

**Unchanged, and worth stating:** `dashboard/app.js` and `dashboard/teams.js`.
`registerCard` is why.

**Tests** — `test_run.sh` (the warrant block) · `test_coordination.sh` (strengthen
the reserved-name case) · `test_board.py` (config bounds) · `test_boardorch.py`
(**new**, mirroring `test_boardteams.py`: each bound refuses independently) ·
`test_e2e.mjs` (settings-card key list) · `test_frontend_tabs.sh` (rail count) ·
a `runs.js` frontend test · `run_tests.sh` registration.
`test_frontend_teams.sh` is **unchanged**.

## Risks, flagged not argued

- **Acceptance becomes self-asserted.** The orchestrator that briefs the work also
  ticks its acceptance criteria. The reviewer verdict is the only independent
  signal, and it covers only jobs the orchestrator chose to `assign` — work it
  never assigns is never reviewed and can still be ticked done. This is the sharp
  edge of full autonomy and where I'd expect the first surprise.
- **`--force` denied to warranted callers is load-bearing.** Without it the gate is
  one flag deep, and "FORCED" in a ledger is only a control if someone reads
  ledgers.
- **`teardown` will kill tmux sessions from inside a pane** for the first time,
  bounded to names in a ledger written by the same orchestrator.
- **Nothing counts turns or spend.** `expires_at` is the only wall clock.
- **The warrant is readable by every unrestricted agent on the box.** RULE #-0.7's
  existing sentence must be extended to name it, so nobody later cites it as
  authentication.

## Sequencing

Each phase is independently useful and independently shippable.

1. **Runs view + `GET /api/runs`.** Pure read. Makes today's session-driven runs
   visible immediately, and you need it to watch anything later.
2. **Notifications.** Give `record_notice` its way out — feed, badge, toast,
   command hook. Useful for manual runs too.
3. **`run complete` reports open cards.** Small; closes the EP-021 gap on its own.
4. **Authority + the `orchestrator` role.** The identity change and its tests.
5. **The orchestrator agent and its Settings card.** The autonomous part, last,
   on top of a surface you can already watch and a channel that can already
   reach you.
