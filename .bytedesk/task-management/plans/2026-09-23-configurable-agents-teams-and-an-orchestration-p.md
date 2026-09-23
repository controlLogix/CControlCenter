# Configurable agents, teams, and an orchestration plugin

## Context

agentmux has **no concept of an agent**. Every `spawn` is an ad-hoc tuple of five
flags, and the entire task→agent selection logic is one line —
`taskmgmt/dispatch.py:309`:

```python
cli = cli or cfg.get("dispatchCli") or "codex"
```

One global default CLI. No persona, no capability, no team. `dispatchReviewCli`
(`dashboard/ccboard.py:120`) is declared, validated and exposed — and read by nothing.
Meanwhile `~/.claude/agents/*.md` holds a real roster (plc-dev, senior-reviewer,
plc-test-engineer, scheduler, hr-recruiter) that agentmux cannot see, and
`hr-recruiter` already implements "author a new agent definition" by hand.

Two outcomes:

1. **Agent definitions as first-class, editable objects** — global ones shared across
   repos, repo-specific ones committed with the code — created and removed from the
   dashboard, and actually enforced at launch.
2. **A publishable plugin** wrapping the workflow as skills, hooks and MCP tools, so the
   same orchestration works in any repo rather than only where agentmux is checked out.

## Decisions taken (do not relitigate)

| # | Decision |
| --- | --- |
| 1 | A definition is **role + launch recipe in one**: persona, tool/permission limits, cli/auth/model. |
| 2 | **Always a lead.** Every dispatch spawns a lead agent that recruits its workers. |
| 3 | Approval: **infer → propose → human approves the roster once**; the lead hires within it. |
| 4 | Storage: **markdown + YAML frontmatter**, global `~/.agentmux/agents/`, repo `<repo>/.agentmux/agents/`. |
| 5 | Global/repo **name collision is an error**, validated at creation. |
| 6 | **One roster** — agentmux also reads `.claude/agents/*.md` and fills in launch defaults. |
| 7 | Tool and permission limits are **enforced at launch**, not just described in prose. |
| 8 | Teams get **a git worktree each; the lead merges**. |
| 9 | The dashboard **may hire** — the read-only-actions rule is relaxed, but bounded. |
| 10 | Plugin ships **skills + hooks + MCP tools**, published to our `adaggroup` marketplace. |
| 11 | **Full skill-creator eval loop on every skill.** |

### One decision needs your confirmation

Decision 5 says a global/repo name collision is an error. `.claude/agents/` is a *third*
source it did not rule on. Making it an error too means adopting decision 6 turns every
pre-existing `.claude/agents/reviewer.md` into a board-breaking error on first load.
**Recommendation:** `.agentmux` vs `.agentmux` same name → error (as decided);
`.agentmux` shadows `.claude` with the shadowing *reported in the UI* → not an error.

## Risks accepted, and how they are bounded

- **Decision 9 vs "the page reports, the CLI acts"** (`app.js:2312`, `server.py:1099`).
  Port 8787 is unauthenticated; `read_cc_body`'s Origin allowlist stops a *browser* on
  another origin and nothing else — a non-browser client omits the header and is treated
  as same-origin (exactly how `test_board.py:505` drives it). **Any local process that
  can open a socket can hire.** The five bounds in §A6 reduce that to "start a definition
  a human already approved, at its declared posture, two at a time" — real defence in
  depth, not authentication. It must be commented in that tone, and `dashboardMayHire`
  must hard-fail if the server ever binds off `127.0.0.1`.
- **Decision 8 moves conflict from claim time to merge time.** Namespacing member claims
  is *required* (two members in different worktrees must not falsely block each other on
  the same repo-relative path), but it converts a cheap refusal into an expensive merge
  conflict the lead absorbs. Mitigations: partition `touches` by top-level directory in
  the proposal, keep `teamMaxWorkers` at 2, report conflicts as board comments.
- **Decision 2 doubles pane count per card.** Bounded by per-role WIP (§A6) and a cheap
  default model for leads.

---

# Part A — agent definitions in agentmux

Build against the **live** dispatcher: `taskmgmt/dispatch.py` + `dashboard/ccboard.py`
over `~/.agentmux/cc.db`. The `.bytedesk/task-management/` store in this repo is an empty
husk and its own ADR-0001 says cc.db stays canonical.

## A1. The definition format

YAML frontmatter + markdown body, where **the body is the persona**. A superset of
`.claude/agents/*.md`, so those load unchanged.

| field | req | default | notes |
| --- | --- | --- | --- |
| `name` | yes | — | `[a-z][a-z0-9-]{0,31}`, no `.` (tmux target separator, `agentmux.sh:464`); filename stem must equal it |
| `description` | yes | — | ≤280 chars; drives inference |
| `role` | no | `worker` | `lead`/`worker`/`reviewer`/`researcher` |
| `cli` | no | board `dispatchCli` | must match `ccboard.CLI_RE` |
| `model` / `auth` | no | CLI default / active method | `auth` is a method id from `auth.json`, **never a credential** |
| `posture` | no | `workspace-write` | `read-only`/`workspace-write`/`unrestricted` |
| `tools.allow` / `.deny` | no | `[]` | **claude-only**; degrades with a visible warning |
| `capabilities` | no | `[]` | ≤16 tags, matched against labels and paths |
| `worktree` | no | per role | `per-member`/`integration`/`none` |
| `maxInstances` | no | `1` | 1–8 copies per team |
| `scope` | — | **derived** | authoring it is a rejection |

`posture` defaults to `workspace-write`, **not** today's `unrestricted`, deliberately: a
definition that says nothing should tighten, not loosen. Defaults are chosen so a
`.claude/agents/*.md` carrying only `name`/`description`/`tools`/`model` loads clean —
that is decision 6 working for free.

```markdown
---
name: reviewer
description: Reads a diff and finds what is wrong with it. Never edits.
role: reviewer
cli: claude
posture: read-only
tools:
  allow: [Read, Grep, Glob, Bash(git diff:*)]
  deny: [Write, Edit, NotebookEdit]
capabilities: [review, security]
worktree: none
---

You review, you do not fix. Answer three questions per file: does it do what the
card asked, what does it break, what did it leave half-done. Write findings as a
board comment. If you want a change made, say which file and line — do not make it.
```

**Search order:** `<repo>/.agentmux/agents/` → `~/.agentmux/agents/` → `<repo>/.claude/agents/`
→ `~/.claude/agents/`. `.gitignore:50` says "Runtime state and logs belong in ~/.agentmux,
never here" — add a line clarifying `<repo>/.agentmux/agents/` is tracked *definition*, or
the next reader deletes it.

## A2. `taskmgmt/agentdefs.py` (new, ~300 lines)

Standalone — imports nothing from ccboard/server, so dispatch, server and tests all use it.
`load_all()` returns `{agents, errors, shadowed, collisions, rejected}`.

Validation copies the `themes.json` philosophy (`app.js:2057-2093`): allowlist the declared
keys and **name every rejection** rather than silently dropping it. An unknown key still
loads the file, with `rejected:["swarmSize"]` attached; a bad `name` or missing
`description` does not load and lands in `errors[]` with its path and reason. All three
lists reach the UI verbatim.

Hardening — these files are read by a server and rendered in a browser: 64 KiB cap, `*.md`
only, reject symlinks (same posture as `read_field()`, `server.py:817`), cap the listing at
200 files, reject control characters, **filename stem must equal `name`** (otherwise the
collision check is bypassed by naming two files differently). Import `yaml` *lazily* inside
the parse function and degrade to an error — `server.py` imports no yaml today and a
top-level import would take the whole dashboard down on a machine that lacks it.

## A3. Launch enforcement (`agentmux.sh`)

New `cmd_spawn` flags in the arg loop at `agentmux.sh:445-454` (which dies on any unknown
flag, so this change is required, not optional): `--persona-file`, `--posture`, `--tools`,
`--deny-tools`, `--agentdef`, `--role`. Validate each with the same `grep -Eq` discipline as
`--task` (`:466-484`) — these reach the pane environment inside single quotes.

**`claude_config_dir()` (`agentmux.sh:91-148`) currently writes one shared
`$ROOT/claude-config` and regenerates it on every spawn — two concurrent spawns already
race on it.** Teams make that race routine, so per-agent config dirs
(`$ROOT/claude-config/<agent>/`) are a bug fix as much as a feature. Keep the existing
prove-it check at `:139-144` and generalise it: grep the written file for the posture it
claims and `die` if absent. Add a GC pass pruning dirs with no live pane.

| posture | codex | claude | grok |
| --- | --- | --- | --- |
| `unrestricted` | `--dangerously-bypass-approvals-and-sandbox` | `bypassPermissions` (today) | `--permission-mode bypassPermissions` |
| `workspace-write` | `--sandbox workspace-write` | `acceptEdits` + denies | verify at implementation |
| `read-only` | `--sandbox read-only` | `default` + deny Write/Edit/Bash | verify at implementation |

Two hard rules:

- **A posture that cannot be enforced fails the spawn — it never silently downgrades.**
  This inverts the existing refusal at `:141`: never *report* a posture you did not
  *achieve*. Consequence: some definitions cannot run on some CLIs, and the UI must say
  which. Named tool allowlists are claude-only; on codex/grok they are recorded with a
  `degraded` marker and restated as prose in the persona.
- **`AGENTMUX_NO_BYPASS=1` (`:495`) becomes a ceiling**, clamping any requested posture
  down and logging the clamp. A definition must never escape the machine-wide brake.

Persona is a *file*, never inlined into the tmux command: copied to
`$RUNDIR/<name>.persona` at 0600, delivered as `CLAUDE.md` in the per-agent config dir for
claude, and prepended to the brief for everything (the portable path). New sidecars
`.agentdef`, `.posture`, `.tools`, `.role`, `.team` beside the existing eight
(`:591-612`); `.perms` keeps its current two values so existing readers do not break. Add
each to `FIELDS` at `server.py:84` to inherit `read_field()`'s hardening.

## A4. The dispatch seam (`taskmgmt/dispatch.py`)

Replace lines 307-309 with `roster = agentdefs.choose_roster(task, cfg, repo_root=REPO,
cli_override=cli)`, lead first. **Stage 1 contract: with no definitions on disk it returns
exactly one spec resolving `cli` identically to today** — byte-identical behaviour, which
is what makes it safe to ship first.

**Naming that survives `collect`.** Three things move together or `collect` stops reaping:

```python
WORKER_RE = re.compile(r"(ep|tm|adr|sp|cap)-([0-9]{3,9})(?:-([a-z][a-z0-9]{0,15}))?")
def member_name(key, role=None): return key.lower() if not role else "%s-%s" % (key.lower(), role)
def worker_name(key): return key.lower()          # the LEAD — unchanged, still round-trips
def role_of_worker(name): ...                      # group(3) or "lead"
```

The suffix **must start with a letter**. Without that, `tm-042-7` is ambiguous with key
`TM-0427` and `key_of_worker` silently attributes a member to the wrong card. Longest name
`tm-999999999-researcher` is 23 chars, inside the 64 limit.

**Claims — the fix is smaller than expected.** `coordination.py:73 flatten()` does
`resource.replace("/", "%2F")` and `RESOURCE_PATTERN` (`:55`) is `[A-Za-z0-9_./-]{1,200}`,
so `/` is already legal: **a worktree-namespaced claim validates with zero changes to
`coordination.py`.**

- The **lead claims the card's full `touches` set unnamespaced**, exactly as today — so
  `dispatchable()`'s greedy disjoint pass (`ccboard.py:1665`) and `busy_paths()` (`:1677`)
  keep computing over the same namespace and the queue math does not regress.
- **Members claim inside their worktree namespace**: `wt/tm-042-dev/dashboard/app.js`.
- Anything outside a worktree (`~/.agentmux`, shared state) is claimed unnamespaced by
  every member, preserving cross-team protection.

Worktrees live **outside the repo** (`~/.agentmux/worktrees/tm-042/{lead,dev}`, branches
`am/tm-042` and `am/tm-042/dev`) so member trees never appear in repo listings and never
get committed. The lead gets an integration worktree too — merging into the operator's
dirty checkout is unacceptable.

**`collect` fans out, lead last.** `collect_one` becomes
`members = [n for n in live_agents() if key_of_worker(n) == key]`. All workers finished →
leave the lead alive, post "merge now". Lead finished with evidence → release every claim
(namespaced and not), reap all panes, drop member worktrees. **Lead dead with members alive
→ kill members and park the card** — an orphaned worker with no one to merge it accumulates
branches, holds claims and consumes slots. `collect_all()` (`:482`) needs no change because
`tasks.agent` keeps naming the lead only.

Persona and team context inject into `write_brief()` (`:189`) — it is a list of strings.
Members get `## Your team` naming the others, their branches, and "do not edit outside your
worktree". `BRIEF_MAX=8192` still applies: **truncate the persona, never the acceptance
criteria or the claim list** — a truncated claim list is actively dangerous.

## A5. Roster inference and approval

One new child table in `NEW_TABLES` (`ccboard.py:168`), keyed on `entity_key` like every
other (`:193-216`), which inherits history/comments/evidence for free. A new `KINDS` entry
would mean touching `KEY_RE`, `board_counters`, payload builders and the board view — a
huge blast radius for something never independently addressable.

```sql
CREATE TABLE IF NOT EXISTS board_roster (
  id INTEGER PRIMARY KEY, entity_key TEXT NOT NULL,
  member TEXT NOT NULL, role TEXT NOT NULL, definition TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'proposed',   -- proposed|approved|rejected|hired|finished
  branch TEXT, worktree TEXT, at TEXT, approved_by TEXT, approved_at TEXT)
```

plus a unique index on `(entity_key, member)`. `migrate()` (`:256`) picks it up unchanged.
Every transition goes through `_record()` (`:383`), so approval lands in `board_history`
and appears in the task inspector with no extra work. Member branch/worktree pairs live
here; `tasks.worktree`/`tasks.branch` (`:240`) stay scalar and keep naming the lead.

Inference is deterministic and read-only — no LLM. Signals: distinct top-level dirs in
`touches`, acceptance count, `area:`/`needs:` labels matched against `capabilities`,
`blockedBy` depth, task `type`. Clamped by `teamMaxWorkers` and each definition's
`maxInstances`. An unmatched capability produces a visible `gap` entry rather than a silent
drop.

**`teamRequireApproval` (default true) must not stall the pool**: a card with no approved
roster dispatches as a **solo lead** rather than blocking. That is the difference between a
feature and a queue that stops.

## A6. HTTP and UI

**`/api/agents` is already taken** — it returns the live pane snapshot (`server.py:1887`).
Definitions go under `/api/board/<op>`, which inherits `board_endpoint`'s entire
except-ladder (`:1056-1067`), `read_cc_body`'s guards (`:922`) and the read/write verb
split. **Op names are `[a-z]{1,16}`** (`:1798`) — one lowercase word, no digits, no hyphens.

Extend the tuples at `server.py:1026-1028`:

```python
BOARD_READS  = (..., "agents", "roster")
BOARD_WRITES = (..., "agentdef", "agentdrop", "recruit", "approve", "hire")
```

Handlers are new `if op ==` branches in `board_read` (`:1069`) / `board_write` (`:1110`).
File writes use the atomic idiom from `set_auth_setting` (`:1246-1256`): `umask(0o077)` →
`.tmp` → `chmod 0600` → `os.replace`. Refuse writes outside the two agent dirs; refuse
`scope: claude` writes entirely (those files belong to Claude Code). Cross-scope collision
raises `ccboard.Refused` → 409 with a `missing` hint naming the other file.

**`hire` — the five bounds.** The comment at `server.py:1103` is being deliberately broken
and must be rewritten to say so:

1. **Name-only.** Body is `{id, name}`, both through `key_field`/`NAME_RE`. No argv, cwd,
   cli, model or flags ever cross the wire; the server re-resolves the definition from disk.
2. **Must be `approved`** for that card, else 409.
3. **Off by default** — requires both `dispatchEnabled` and `dashboardMayHire`.
4. **Bounded concurrency** — a `BoundedSemaphore(2)` like `MQTT_SLOTS` (`:72`); exhausted → 503.
5. **Posture ceiling** — takes the definition's posture, clamped by `AGENTMUX_NO_BYPASS`.

New config keys in `DEFAULT_CONFIG` (`ccboard.py:110-121`) with typed bounds:
`teamMaxAgents` (1–32, default 8), `teamMaxWorkers` (0–8, default 2),
`teamRequireApproval` (true), `dashboardMayHire` (**false**). And claim the dead
`dispatchReviewCli` (`:120`) as the default cli for reviewer-role definitions — free slot,
zero migration.

**Per-role WIP.** `dispatched_now()` (`dispatch.py:407`) cannot report a role, so a
4-member team would eat the whole WIP as if it were 4 cards. Add `dispatched_detail()` and
express the old function in terms of it (so `pool_status()` at `:617` is unchanged), then
count two things in `pool_once()`: **leads against `dispatchWip`** (which keeps its current
meaning — cards in flight, no config migration) and **panes against `teamMaxAgents`**.

**UI** is five mechanical edits: `els.views` (`app.js:48-57`), `VIEW_LOADERS` (`:1920`), a
nav button (`index.html:50-82`), a `<section id="viewAgents" class="view pad" hidden>`
(`:93-423`) — and **no `VIEW_POLL_MS` entry**, because definitions are files a human edits
and polling them is noise. `loadAgents()` copies `loadIiot()` (`:2893`) almost verbatim;
create handler copies `:2953-2970`; reuse `el()` (`:1606`, `textContent` only — descriptions
and personas are user-authored), `getJSON`/`post` (`:2147`/`:2156`), `say()` (`:2174`),
`deleteButton()` (`:2297`), `collapsible()` (`:2639`), `settingEditor()` (`:2656`). Paths
are relative. No modal system — `window.confirm` plus inline `<details>`.

`errors`/`collisions`/`shadowed` render **first, above the list**, in a warn block naming
both paths and a one-line remedy. Roster approval lives on the **board** view's task
inspector, not the agents view — that is where a human already is when deciding about a
card. New CSS grids need `align-items: start`; leave `.view.pad { zoom: 1 }` alone. Both
are asserted by `test_frontend.sh`.

---

# Part B — the `agentmux-orchestration` plugin

## B1. Where it goes

Our marketplace is **already cloned and registered**: `adaggroup` →
`C:\theWork\ADAG-CSAI\marketplace`, remote `github.com/adag-CSAI/marketplace.git`,
registered with `source: "directory"` — **working-tree edits are live immediately**, no
reinstall to test. No clone step needed.

```
C:\theWork\ADAG-CSAI\marketplace\
  .claude-plugin/marketplace.json      <- append one catalog entry
  plugins/agentmux-orchestration/
    .claude-plugin/plugin.json         <- model on plugins/codesys-dev (validates clean)
    skills/<name>/SKILL.md   hooks/   .mcp.json   bin/   lib/   commands/   evals/
```

`docs/PUBLISH_TO_MARKETPLACE.md` binds us to five invariants; two bite here: **the catalog
entry must exist before the first publish** (the workflow bumps, never creates), and
**entry `version` must equal plugin `version`** or `scripts/check-marketplace.mjs` fails
the build. Vendor into `plugins/` rather than pointing at a source repo — both repos are
private, and a remote source would need every user to have read on two.

## B2. Skills

All four groups. Budget: ~80–170 always-on tokens per skill description, so eight skills is
roughly 1k always-on.

| skill | does |
| --- | --- |
| `agent-new` | Create a definition — absorbs what `hr-recruiter` does today, adding launch fields and cross-scope name validation. |
| `agent-roster` | The merged roster across all four scopes, with collisions and shadowing named. |
| `agent-edit` / `agent-remove` | Change or retire; refuses while a live worker uses it. |
| `team-compose` | Infer and propose a roster for a card. |
| `team-dispatch` | Approve, hire the lead, watch, collect. |
| `team-merge` | The lead's integration step: review each worktree, merge, surface conflicts, attach evidence. |
| `agent-config` | Read/set dispatch config — WIP, poll, enabled, per-role caps. |
| `agent-doctor` | Validate every definition, check auth methods resolve, report what this host can actually launch. |

Frontmatter follows the marketplace convention: `name`, a `description` carrying explicit
trigger phrases, `user-invokable: true`, `argument-hint`, `allowed-tools` where it shells
out. (Note: `user-invocable` appears in 40 files in the wild and is an inert misspelling —
do not copy it.)

## B3. Hooks and MCP

Copy the `task-management` dispatcher shape exactly: `hooks/hooks.json` → one
`${CLAUDE_PLUGIN_ROOT}/hooks/am-hook.sh <event>` shim → one entrypoint in `bin/`. Matchers
are regex alternations covering both Claude and Codex tool names
(`Edit|Write|MultiEdit|apply_patch`) so the plugin works cross-harness. **The
`PreToolUse:Bash` hook must bail in its first three lines** before spawning anything — it
fires on every Bash call and latency there is felt on every command.

Gates: refuse a hire with no approved roster; refuse a definition edit while a live worker
runs it; warn when a definition names an auth method that does not resolve on this host.

MCP server exposes the roster programmatically — `agent_list`, `agent_create`,
`agent_remove`, `team_propose`, `team_approve`, `team_status` — declared in `.mcp.json`
with `${CLAUDE_PLUGIN_ROOT}`.

## B4. Evals — full loop on every skill

Two formats exist. Use the **native first-party one**, confirmed present
(`claude plugin eval --help`): `evals/<case>/case.yaml` (or `prompt.md` +
`graders/*.md`). Nothing on this machine has adopted it yet, so scaffold the first case
with `claude plugin eval init --bare <case>` rather than hand-writing it.

Default ablation is `with-without`, which runs a no-plugin baseline arm and reports the
delta — exactly the baseline-vs-with-skill comparison the full loop wants, for free.
Graders marked `with-only` (e.g. `tool_used: Skill`) act as a fired-indicator rather than
scoring.

Use `skill-creator` for **authoring and iteration** (draft → test prompts → grade →
rewrite → repeat, then `improve_description.py` to tune triggering); use the native suite
as the **repeatable gate**. Per skill: at least three cases — one clear trigger, one
near-miss that must *not* fire it, one full workflow — with `--threshold` set once pass
rates are known.

---

# Staging

Each stage ships independently and leaves `run_tests.sh` green.

| Stage | Delivers | Useful alone because |
| --- | --- | --- |
| **1** | `agentdefs.py`; `GET /api/board/agents`; read-only Agents view; `choose_roster` returning one spec. | Dispatch stops being "codex for everything" — a matching card gets that definition's cli/model/auth, and the whole roster (including `.claude/agents`, collisions, rejections) is visible. With zero definitions, behaviour is byte-identical to today. |
| **2** | Spawn flags; per-agent `claude_config_dir`; posture ladder; fail-closed; new sidecars; persona in the brief. | A `read-only` reviewer genuinely cannot write, and the shared-config-dir race is fixed. |
| **3** | `agentdef`/`agentdrop` write ops; atomic writes; collision-as-409; create/edit/delete UI. | No more hand-editing YAML to add an agent. |
| **4** | `board_roster`; `propose_roster`; `recruit`/`approve`/`roster` ops; approval UI; four config keys. | You can see and approve what *would* be hired, and tune inference, before anything can spawn a team. **This is what de-risks stage 5.** |
| **5** | `WORKER_RE`/`role_of_worker`/`member_name`; `collect` fan-out lead-last; `dispatched_detail` + two-counter pool; worktrees; namespaced claims. | Approved teams run and are collected correctly; the lead still merges by hand. |
| **6** | Lead merge + conflict-as-comment; worktree teardown; `hire` with all five bounds; rewritten honesty comment. | The full loop, from the page. |

**Stage 5 carries the risk.** Do not start it until stage 4 has been used in anger.

# Verification

Conventions here are strict and unforgiving:

- `dashboard/run_tests.sh` is the gate, run as `bash <(tr -d '\r' < dashboard/run_tests.sh)`
  — the CR strip is the invocation convention for every `.sh` in this repo. It swaps
  `AGENTMUX_HOME` to a tempdir in the **server** process and restores it in an EXIT trap.
- A suite must print its summary **last**, ending `failed 0` — the runner reads the final
  line. A trailing `store: <path>` line once made a passing suite read as failed
  (`test_board.py:606-608`).
- New `dashboard/test_agentdefs.py` copies the isolation preamble at `test_board.py:41-48`
  (set `AGENTMUX_HOME` **before** importing ccboard/ccstore/server — import order is
  load-bearing) and the harness at `:505-523` (`ThreadingHTTPServer(("127.0.0.1", 0), …)`,
  port 0 so it runs beside the live dashboard). Register it in `run_tests.sh:155-177` — a
  suite nothing invokes is decoration, as that file says about `test_board.py` itself.
- Endpoint checklist from `test_board.py:525-603`, for every new op: 200 + expected keys;
  gate refusal 409 **with hints**; wrong verb 405; unknown op 404/405 and **never 500**;
  missing `application/json` 415; unknown name 404; malformed name 400; over-long query 400.

Per-stage specifics worth naming:

- **1** — collision makes *both* entries unusable; `.claude` same-name is `shadowed`, not an
  error; a `.claude` file with only name/description/tools/model loads with defaults filled;
  symlink refused; missing PyYAML degrades to an error rather than an import crash.
- **2** — `--posture read-only` on grok refuses rather than launching; `AGENTMUX_NO_BYPASS=1`
  clamps `unrestricted`; the written settings.json actually contains the claimed mode; the
  persona file is 0600 and never appears in the tmux command line.
- **5** — the ambiguity regression: `key_of_worker("tm-042-dev") == "TM-042"` **and
  `key_of_worker("tm-0427") == "TM-0427"`**; `worker_name`/`key_of_worker` still round-trip
  for every `KINDS` prefix; `wt/tm-042-dev/dashboard/app.js` passes `RESOURCE_PATTERN`,
  flattens distinctly, and does not conflict with an unnamespaced claim on the same file;
  a dead lead with live members parks the card.
- **6** — a body carrying `cli`/`cwd`/`argv` has those fields **ignored, asserted
  explicitly**; 403 when `dashboardMayHire` is false; slot exhaustion 503.
- **Plugin** — `claude plugin validate plugins/agentmux-orchestration --strict`, then
  `claude plugin details` to check always-on token cost, then `claude plugin eval
  --ablation with-without`.
- **End to end** — create a definition in the browser → approve a roster → the pool
  dispatches a lead → the lead hires → worktrees merge → `collect` reaps everything →
  `agentmux list` is empty and no claim is left behind.

# Open risk to watch

**Idle detection does not generalise to teams.** `collect_one`'s `agentmux wait` logic
(`dispatch.py:436-448`) distinguishes working / idle-with-evidence / idle-without. For a
lead, "idle" may mean *waiting for its workers*, which is indistinguishable from stuck.
Proposed rule: **a lead idle while any worker is live is `working`, never `idle`.** This is
the most likely source of a team that hangs holding its slots.
