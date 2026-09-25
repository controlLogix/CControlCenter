# A Kanban board, a ticket you can actually read, and gh without a second login

## Context

The Board view renders epics as cards with a row per task. Each row shows five things:
key, a status `<select>`, title, assignee, delete. That is all.

Meanwhile `GET /api/board/board` already returns, for every task and on every load:
body, acceptance criteria, labels, blockedBy, evidence, commits, touches, comments,
links, actor, session, branch, worktree, blockedReason, parkedReason, priority,
estimate, rank, parent, sprint, capability, goalDoc, triagedBy, jira_key, type,
triageMissing, hasAnswer. **All of it is fetched and discarded.**

Eight read endpoints and thirteen write endpoints have **zero frontend callers**:
`entity`, `history`, `why`, `graph`, `doctor`, `find`, `next`, `sprint`, and the writes
`create`, `update`, `acceptance`, `label`, `dep`, `evidence`, `commit`, `touch`,
`comment`, `link`, `triage`, `state`, `override`.

So this is genuinely a UI change. The backend already answers every question a deep
ticket view needs to ask, and already accepts every edit it needs to make.

Three outcomes:

1. **A Kanban tab** beside Tasks and Atlassian — the same cards in status columns, with
   drag between them.
2. **A detail panel** that shows a card in full and can edit it, opened from either
   layout.
3. **The GitHub tab working in WSL** without signing in a second time.

## Decisions taken

| | |
|---|---|
| Kanban placement | A third tab under Board. The epic list stays exactly as it is. |
| Columns | All six statuses, always visible — `backlog open in_progress blocked parked done` |
| The `done` column | Capped by recency (~20) with a "show all" expander |
| Detail panel | Full edit: body, acceptance, status, labels, assignee, evidence, commits, comments, links, deps |
| Jira | Stays shallow — show `jira_key`, link out. No new Jira backend. |
| gh | Stop re-authenticating. No new features. |

---

## 1. gh: the symlink cannot work, and does not need to

**Measured on this machine, not assumed.**

The Windows token is in the **Windows Credential Manager**, not in a file:

- `gh auth status` marks both accounts `(keyring)` — gh's own word for the OS secret store.
- `hosts.yml` is **128 bytes** and contains **no `oauth_token` key**. It is an
  account-name index: `github.com:` → `git_protocol`, `users: {nicholas-klute_adag: {}, controlLogix: {}}`.
- `cmdkey /list` shows three `gh:github.com:*` targets.

Linux `gh` cannot read DPAPI. Symlinking `~/.config/gh` → the Windows config dir would
share `config.yml` and two account names **and no credential**. This repo already knows
the distinction — `link-windows-state.sh` shares `~/.codex` wholesale because codex's
auth is a file, and explicitly refuses to share the claude login because *"Windows keeps
its login in the Windows credential store (DPAPI), which Linux cannot read."* gh is in
the claude column.

A second obstacle even if the first vanished: `/mnt/c` mounts 9p/drvfs **without
`metadata`**, so every file there reads `0777` from Linux and `chmod` is a silent no-op.
gh refuses group/world-readable config.

### What works instead

`gh.exe` is already on the WSL PATH through interop and already uses the Windows
credential. Verified:

```
gh api --include user           HTTP/2.0 200 OK
X-Oauth-Scopes: gist, read:org, repo, workflow      ← superset of SCOPES
login: nicholas-klute_adag
gh pr list (from a /mnt/c cwd)  []                  ← works; empty is the true answer
gh.exe api rate_limit           438 ms
```

The dashboard reports "gh is not installed" for one reason: `shutil.which("gh")` on
POSIX does not try `.exe`, while `shutil.which("gh.exe")` finds it immediately.

**The change is two lookups.**

- `dashboard/github_auth.py:70-71` — `gh_path()` returns `shutil.which("gh")`. Fall back
  to `shutil.which("gh.exe")`.
- `dashboard/github_panel.py:149` — the same `shutil.which('gh')` guard, and its
  remediation string hardcodes `sudo apt install gh`, which is wrong advice on a box
  where the Windows binary is right there.

Both modules already invoke gh as a bare `'gh'` through `subprocess`, so they need the
resolved path threaded rather than the literal.

**Three things to get right, not two:**

- **The login flow must stop offering what it cannot do.** `github_auth.py:38-43` gates
  `can_login` on `import pty`, and the device-code flow scrapes a Linux PTY. Driving
  `gh.exe` through a Linux pty will not work. When the resolved binary is `gh.exe`,
  `can_login` must be **false** with a message naming the real remedy — sign in on the
  Windows side, where it already is — rather than a flow that hangs.
- **Latency.** 438 ms versus ~50 ms native. `github_panel` caches 30 s including
  failures, and `github_auth.account()` is **not cached** — every `/api/github/auth` GET
  spawns one. The frontend polls that every 2 s during a login. With login disabled the
  poll does not run, but the account card is still a fresh interop call per load.
- **`gh.exe` reads stdin.** `create_issue` passes the body via `--body-file -`. That is
  correct and must stay; but every *other* call needs stdin closed, or it will consume
  whatever the caller's stdin happens to be. This bit twice while investigating.

**Alternative, stated so it is a choice and not an oversight:** `apt install gh`
(2.45.0 is available) gives a native Linux gh at ~50 ms — and a **second login** to
maintain. That is exactly what you asked to avoid, so interop is the recommendation.

---

## 2. The Kanban tab

**A new file, `dashboard/kanban.js`, not code added to `app.js`.** That is not a style
preference — it is the only way to avoid the tightest constraint in the repo.

`dashboard/test_frontend_board.sh` executes a **source slice** of `app.js`
(`const EPIC_STATUSES =` → `const JOURNAL_KINDS =`, lines 2808-3172) inside a `vm`
whose global set is exactly: `document.createElement`, `el`, `els.{boardList,boardStamp}`,
`window.confirm`, `say`, `collapsible`, `liveAgents`, `markAgent`, `refreshLiveMarks`,
`rememberOpen`, `localStorage`, `CSS.escape`, `getJSON`, `post`. Any new global —
`setTimeout`, `requestAnimationFrame`, `document.getElementById`, `fetch` — breaks
**every test in that file**. Its fake `getJSON` asserts `path === 'api/board/board'`, so
a second fetch fails immediately; its fake `post` throws for anything outside
status/delete/move.

A separate script pays none of that, and the pattern is established: `runs.js`,
`chatter.js`, `teams.js`, `agents.js` all register into existing views from outside.

### The four-file wiring

1. `dashboard/index.html:301` — a third `.subtab[data-panel="kanban"]`, and a
   `<div id="viewKanban" class="panel" role="tabpanel" hidden>` in the `.panels` block.
   Panel names must match `/^[a-z][a-z0-9]*$/` — `kanban`, never `kanBan`.
2. `dashboard/index.html:543-551` — `<script src="kanban.js">` **before** `app.js`;
   `ccc:ready` is dispatched synchronously.
3. `dashboard/kanban.js` — `registerPanel('board', 'kanban', load, 0)` from a
   `ccc:ready` listener. Poll 0, matching the other two board panels.
4. `dashboard/server.py:2374` — add `"/kanban.js"` to the static allowlist tuple, or it
   returns a JSON 404 and the browser refuses it under nosniff.

### Columns and the `done` cap

Six columns from `STATUSES` minus `deleted`. Every column renders even when empty —
otherwise the workflow is invisible and you cannot drag into a column that is not there.
An empty column gets a thin dashed placeholder, not a collapsed gap.

`done` is capped at the 20 most recent by `closed` (falling back to `updated`), with a
`… 61 more · show all` expander. The live board is 81 done against 2 open; an uncapped
column is a scroll bar with a board attached.

The container is its own class — **`.kanban`, not `.board`** —
because `test_frontend_collapse.sh:29` asserts `.board { … align-items: start … }`
survives in that same CSS block.

### Drag between columns

The existing row already does the hard half: `dataTransfer.setData('text/plain', key)`.
A column drop handler swaps only the destination call:

```js
post('api/board/status', { id, status: column, actor: 'dashboard' })
```

Two details that decide whether this feels trustworthy:

- **The card must carry `data-status`.** Today status lives only inside the `<select>`'s
  selected option, so there is no way to short-circuit a drop onto the column a card is
  already in — it would round-trip to the server to learn nothing.
- **Do not move the card optimistically.** `in_progress` and `done` are gated; a
  refusal is a 409. Moving the card and then snapping it back reads as a bug. Mark the
  card busy, await the post, and re-render on success — the same
  disable-then-revert discipline `statusSelect` already uses at `app.js:2828-2838`.

## 3. The detail panel

**A right-hand drawer over the board**, not a modal and not an expanding row. A modal
hides the board you were reasoning about; an expanding row reflows a column mid-drag.
The drawer is opened from a card in the Kanban *and* from a row in the existing list,
so both layouts get it.

### What it loads

Four reads, all existing, all already unused by the frontend:

| Call | Gives |
|---|---|
| `GET /api/board/entity?id=X` | the full card **including `body`** — the list payload strips it |
| `GET /api/board/history?id=X&limit=200` | the timeline: every status change, edit, label, dep, evidence, comment, with actor and time |
| `GET /api/board/why?id=X` | why it is not startable — `{startable, reasons[], chain[], roots[]}` |
| `GET /api/board/roster?id=X` | the agents assigned to it, and the gaps from the last recruit |

### What it edits

Every one of these already has an endpoint and a gate:

| Field | Write |
|---|---|
| body, title, assignee, priority, estimate, sprint, branch… | `update{patch}` — unknown keys are rejected server-side with a named field |
| status | `status{status,reason}` — `reason` is what fills `blockedReason`/`parkedReason` |
| acceptance | `acceptance` — three shapes: `{text}` append, `{index,done}` tick, `{remove:true,index}` drop |
| labels | `label{label,present}` |
| evidence / commits | `evidence{ref}` / `commit{ref}` — append-only |
| comments | `comment{text}` |
| links / deps | `link{type,target,present}` / `dep{blockedBy,present}` |

**The acceptance index is 1-BASED.** `ccboard.py` validates `1..200`. A `forEach`
index passed straight through ticks the wrong criterion, and on a card with four
criteria that is a silent wrong answer rather than an error. Write the `+1` once, at
the point the row is built, and put a test on the boundary.

Most writes return the full entity, so the drawer can re-render from the response
without a second fetch. Three do not: `status` returns `{id,from,to,…,entity:{…}}`
(nested), and `move`/`delete` return neither. Normalise that in one helper rather than
at each call site.

### Surfacing a refused gate — the most common thing an operator will hit

Moving a card to `in_progress` or `done` runs a gate. A refusal is **HTTP 409 with
`{error, missing:[{field, hint}]}`**, where each hint is the exact command that fills
the gap (`agentmux task ac TM-014 "…"`).

Today none of that reaches the screen, and the reason is one line:

```js
// dashboard/app.js:2615
if (!res.ok) throw new Error(payload.error || `HTTP ${res.status}`);
```

`post()` discards the payload before any caller can see it. The fix is additive and
backward-compatible — nothing reads these today:

```js
const err = new Error(payload.error || `HTTP ${res.status}`);
err.status = res.status;
err.payload = payload;
throw err;
```

`post` sits at `app.js:2608`, **outside** the tested slice, so this does not disturb
`test_frontend_board.sh` — though that file's fake `post` should learn the same shape
if a test exercises the hint path.

Then the drawer can render "cannot close: missing evidence, acceptance" with the two
commands that fix it, instead of a sentence the operator has to interpret.

## 4. How this gets built

You asked for the CCC to run it. Three runs, because each is independently useful and
independently reviewable:

| Run | Card | Why it is separate |
|---|---|---|
| 1 | gh interop | Two lookups plus the login-flow honesty fix. Touches nothing the other two touch, and unblocks the GitHub tab immediately. |
| 2 | Kanban tab | New file, new tab, drag between columns. Test updates are its own responsibility. |
| 3 | Detail panel | The largest, and it benefits from the Kanban existing first so it has two callers to satisfy. |

### The roster needs two definitions first

`.agentmux/agents/` holds `netcap-dev`, `netcap-lead`, `netcap-reviewer` — all
specialised for pcap parsing and PNG encoding — plus `ccc-orchestrator`. Nothing there
is a frontend agent.

The five smoke orchestrations spawned bare `codex`/`grok` and that worked. For this,
**write two definitions instead**, because the constraints here are not obvious and a
persona carries them into every run without being re-briefed each time:

- `ccc-frontend-dev` (codex) — vanilla JS only, no framework; `window.CCC` is the API;
  a new view script must be added to `server.py`'s static allowlist or it 404s under
  nosniff; theme colours are derived with `color-mix` from existing tokens because
  every theme must define the full token list.
- `ccc-frontend-reviewer` (grok) — verifies by running the frontend suites, not by
  reading; knows that `test_frontend_board.sh` executes a *source slice* of `app.js` in
  a `vm` with a minimal global set, so an added `setTimeout` or `document.getElementById`
  breaks every test in the file.

`hr-recruiter` exists for authoring these.

### Monitoring, and the thing to watch for

Each run stops at the operator gate, so nothing merges without you reading the diff.
The specific failure to expect: **a green suite that is green because a test was
loosened rather than a defect fixed.** The board tests assert by *index* — `<select>`
0 is the epic, 1 is the task; delete-button 0 is the epic, 1 is the task — so a
plausible-looking "fix" is to relax the index. When reviewing, check that any changed
assertion got *stronger* or was replaced by something stronger, and that each survives
a deliberate mutation.

## Files

**New** — `dashboard/kanban.js` (the tab and the drawer; the drawer is exported on
`window.CCC` or a module-local registry so `app.js`'s list rows can open it),
`dashboard/test_frontend_kanban.sh`, plus CSS appended to `dashboard/style.css`.

**Modified** — `dashboard/index.html` (one subtab, one panel div, one script tag),
`dashboard/server.py` (one allowlist entry), `dashboard/app.js` (the `post()` error
shape at 2615; a `data-status` attribute and an "open" affordance on `.task-row`),
`dashboard/github_auth.py` + `dashboard/github_panel.py` (the gh lookup).

**Unchanged, and worth stating:** `ccboard.py`, `ccstore.py`, and every board endpoint.
No schema change, no new endpoint, no migration.

## The test updates this forces

Four assertions will go red. Each is doing its job; each needs a deliberate change,
not a loosening.

| File:line | Asserts | Becomes |
|---|---|---|
| `test_frontend_tabs.sh:154` | board tabs `['boardtasks','tickets']` | `['boardtasks','kanban','tickets']` |
| `test_frontend_tabs.sh:506-518` | `registered.panels` is exactly three pairs | add `['board','kanban']` |
| `test_e2e.mjs:499` | the same two tab labels | add `Kanban` in position |
| `test_frontend_board.sh:120,131` | `<select>` index 0=epic 1=task; delete index 0=epic 1=task | unchanged **if** the list row's new "open" affordance is a `<button class="cbtn">`, which would shift the delete index — use a distinct class and assert by class, not index |

That last row is the trap. The honest fix is to make those assertions select by class
rather than by ordinal, which is strictly stronger and stops the next person hitting it.

**New tests, each of which must be able to fail:**

- Six columns render, including empty ones, and every one is a drop target.
- `done` shows 20 of 81 and the expander reveals the rest.
- A drop posts `status` with the destination column, and a drop on the card's own
  column posts **nothing**.
- A 409 with `missing:[{field,hint}]` renders both hints; a 409 without `missing`
  still renders the message.
- Acceptance tick sends **index 1** for the first criterion. Mutate the `+1` away and
  this must go red.
- `entity` is fetched once per open, not per render.
- gh: `gh_path()` finds `gh.exe` when `gh` is absent, and `can_login` is false in that
  case.

## Verification

1. `bash <(tr -d '\r' < dashboard/run_tests.sh)` — must still end **all suites passed**,
   nothing skipped. e2e now runs inside WSL against the Linux Playwright at `~/pw`.
2. Open Board → Kanban. Six columns; `done` shows 20 with an expander; empty columns
   are visible and outlined.
3. Drag a card from `open` to `in_progress` on a card with no acceptance criteria.
   It must **refuse**, name the missing fields, give the `agentmux task ac` command, and
   leave the card where it was.
4. Add an acceptance criterion in the drawer, tick the **first** one, and confirm via
   `python3 taskmgmt/task.py show <key>` that the first is ticked and not the second.
5. Open the same card from the Tasks list — the drawer must open identically.
6. Settings → GitHub: the account card shows `nicholas-klute_adag` with scopes
   `gist, read:org, repo, workflow`, and the sign-in control is absent with a message
   pointing at the Windows session rather than offering a device login.
7. Re-run each new test with its implementation line mutated, and confirm it goes red.

## Risks, in the order they are likely to bite

1. **The index-based board assertions.** Adding any control to `.task-row` shifts an
   ordinal and breaks tests that look unrelated to the change. This is the most likely
   source of a confusing red.
2. **The 1-based acceptance index.** An off-by-one here ticks the wrong criterion and
   nothing errors — the card just quietly says something untrue.
3. **Optimistic drag.** If the card moves before the server agrees, every gated
   transition looks broken. The discipline is: busy, await, re-render.
4. **e2e first-match selectors.** `test_e2e.mjs:782` resolves `#viewBoard [data-agent]`
   with `page.$` — **first match in DOM order**. A Kanban that renders an agent name
   earlier than the list does changes which node is asserted.
5. **gh latency.** 438 ms per interop call, and `account()` is uncached. Acceptable, but
   if the GitHub tab feels slow this is why, and a small cache is the answer rather than
   abandoning interop.
6. **Theme tokens.** Every theme must define the full token list. A new column colour
   must be `color-mix`ed from `--accent` / `--state-*`, or it is undefined outside
   cc-dark and the Kanban looks broken on every other theme.
