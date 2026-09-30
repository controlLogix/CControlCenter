# agentmux messaging protocol and hub

Status: **implemented for one machine**, in `hub/` (`store.py`, `server.py`, `cli.py`,
`names.py`), and exercised by `hub/tests` and by live orchestrations
(`evals/orchestrations/SCOREBOARD.md`). Requirement IDs (`R-*`) link to failure classes in
`C:\theWork\git\findings\2026-09-30_agentmux_communication_failures.md`.

**Built:**
- naming and the normalizer
- the home layout (`hub/`, `roles/`, `repos/<repo>/{agents,roles,teams}`)
- the hub.db schema and PRAGMAs
- first claim, lease sweeping, dead-agent lease return, team decomposition
- idempotency keys, ordering, attempts and dead letters
- identity by process ancestry
- the transactional NATS outbox (written, not yet drained)

**Designed, not built yet:**
- the `subscribe` stream (agents are rung by the doorbell instead)
- the 127.0.0.1 TCP listener for Windows tools
- per-agent tokens for non-local callers
- hourly online backups
- adopting legacy sessions
- the courier retirement and archive steps of section 10
- the NATS bridge

The terminal side (how bytes reach a CLI) is specified separately in
[`TRANSPORT.md`](TRANSPORT.md). This document covers what happens before and after that:
naming, storage, routing, leases, acknowledgment, and the path to the network.

---

## 1. Goals and non-goals

**Goals**
- One protocol for sending messages and distributing jobs between agents. It must not be
  tied to a team, a repo, or the agentmux checkout.
- Work can be addressed to an **explicit agent**, a **role** (the first eligible holder to
  claim it wins), or a **team** (its lead decomposes it).
- **At-least-once delivery with acknowledgment.** Nothing is dropped silently, and every
  message ends in a terminal state: `acked` or `dead`, with a reason.
- One central home per machine, organized by repo and then agent.
- Ready for the network: addresses and verbs map directly onto NATS subjects, so a leaf
  node can join later without a schema or naming change.

**Non-goals for now**
- A network transport. NATS is designed for here but not built.
- Replacing the board. `cc.db` stays with the dashboard, and the hub refers to cards by
  task key.
- Backends other than tmux. The transport interface keeps that door open.

---

## 2. Naming

### 2.1 Parts

| Part | Rule | Examples |
|---|---|---|
| `repo` | `[a-z0-9_]{1,32}`. Registered in the hub, unique per node. | `agora`, `agentmux`, `the_work` |
| `role` | `[a-z0-9_]{1,24}`. Must resolve to a role definition (§4). | `lead`, `reviewer`, `worker`, `researcher` |
| `agent` | `[a-z0-9_]{1,32}`. Unique within `(repo, role)`. | `codex_1`, `agora_rev_2` |
| `team` | `[a-z0-9_]{1,32}`. Unique per repo. | `tm_210`, `web` |
| `node` | `[a-z0-9_]{1,32}`. One per machine, set in `hub/config.toml`. | `nick_ws` |

**Hyphen is never allowed inside a part.** It is only the separator, which is what makes
every name reversible without asking the registry. `R-NAME-1` `[trace pending: C8]`

### 2.2 Session name

```
<repo>-<role>-<agent>          e.g.  agora-reviewer-codex_1
```

- This is the tmux session name, the directory key, and the identity the hub
  authenticates.
- **Registration is the only way to get one.** The hub gives out session names;
  `agentmux spawn` asks the hub for a name and never makes one up itself. A second
  registration of a live name is refused. A dead name can be reused only after its
  deliveries and leases have been reassigned (§6.4). `R-NAME-2` `[C8, C4 stale sidecars]`

### 2.3 Normalizer

`normalize(s)` works in this order:
1. NFKD, then drop combining marks
2. lowercase
3. replace each run of anything outside `[a-z0-9]` with `_`
4. trim `_` from both ends
5. truncate to the part's maximum length
6. reject an empty result

It is **suggestive, never silent**:
- `agentmux repo add` and `spawn` print the normalized form and refuse input that changed,
  unless `--accept-normalized` is passed.
- A human always sees the name that will be used.

| Input | Result |
|---|---|
| `my-repo` | `my_repo`, suggested and refused without `--accept-normalized` |
| `Agora Rev #2` | `agora_rev_2` |
| `TM-210` | `tm_210` |

### 2.4 Addresses

| Kind | Form | Meaning |
|---|---|---|
| direct | `agent:<repo>/<role>/<agent>` | exactly one registered session |
| role | `role:<scope>/<role>` | any eligible holder of the role within scope. Scope is `<repo>`, `group:<group>`, or `*` |
| team | `team:<repo>/<team>` | the team's lead (§5.3) |
| virtual | `virtual:<name>` | a recipient with no pane, such as `orchestrator`. Only its inbox is read. `[C9: replies to orchestrator undeliverable]` |

Legacy flat names (`nfl-lead`, `tm-209-worker2`) are accepted as **aliases** during
migration (§10). The alias is resolved once, at `post` time, and the stored target is
always canonical.

---

## 3. Home layout

The canonical home is `~/.agentmux` inside WSL (`/home/nick/.agentmux`, on ext4).
`C:\Users\Nick\.agentmux` is a directory symlink to
`\\wsl.localhost\Ubuntu\home\nick\.agentmux`, so Windows tools can read briefs and logs.
**Windows processes never open `hub/`**; they reach the hub over its TCP port (§7.1). The
hub refuses to start if `hub.db` resolves to a 9P or drvfs mount. `R-HOME-1`
`[C12: brief written to a home the pane cannot see]`

```
~/.agentmux/
  hub/                              owned by agentmux-hub. Nothing else opens these files.
    hub.db  hub.db-wal  hub.db-shm
    hub.sock                        unix socket API, mode 0600
    hub.pid  hub.lock  hub.log
    config.toml                     node, retention, tcp port, nats (disabled)
  roles/<role>.toml                 global role definitions
  groups/<group>.toml               named repo sets, e.g. adag_plc = [agora, bms_sim, falcon]
  repos/<repo>/
    repo.toml                       slug, remote aliases, checkout paths, default branch
    roles/<role>.toml               per-repo override of a global role (§4.2)
    teams/<team>.toml               lead, members, default routing
    agents/<role>-<agent>/          session name minus the repo part
      agent.toml                    definition: cli, model, auth, posture, capabilities, persona file
      persona.md
      run/                          transport handle, launch line, started, pid (hub-written)
      logs/pane.log                 transport output capture
      cli/                          per-agent CLI config dir (claude CLAUDE_CONFIG_DIR, codex CODEX_HOME)
      briefs/<work_id>.md           large payloads (§6.6)
  board/cc.db                       dashboard board, unchanged schema
  archive/legacy-<yyyymmdd>/        flat pre-protocol dirs, moved only when no live agent uses them
```

**Why this is collision-free:**
- Every path that belongs to an agent sits under `repos/<repo>/agents/<role>-<agent>/`,
  whose key is the unique session name.
- Nothing belonging to an agent lives in a directory shared across repos.
- Claims, queues and cursors move into `hub.db`, keyed by `(repo, …)`.

This replaces the flat `claims/<path>.json` files, which collided across repos.
`R-HOME-2`

---

## 4. Roles

### 4.1 Definition

```toml
# ~/.agentmux/roles/reviewer.toml
name         = "reviewer"
description  = "Reviews a submission against its acceptance criteria"
capabilities = ["review", "python", "bash"]
may_claim    = ["review"]          # work kinds this role may first-claim
max_active   = 1                   # concurrent work items per holder
lease_s      = 900                 # default lease for claimed work
cli          = "claude"            # default; agent.toml may override
posture      = "restricted"
```

### 4.2 Resolution

1. Look for `repos/<repo>/roles/<role>.toml`. If it exists, it wins, field by field. It is
   an overlay, not a replacement.
2. Otherwise use `roles/<role>.toml`.
3. If neither exists, the name is unknown: registration is refused.

The hub resolves roles at registration and **snapshots the result into the agent row**,
so a later edit to a role never silently changes a running agent.
`agentmux role reload <session>` applies a change deliberately.

---

## 5. Routing work

A **work item** is a unit of dispatched work. It usually points at a board card
(`task_key`), but it doesn't have to.

### 5.1 Direct (`agent:`)
- The item is offered only to that session.
- If the session is dead when the item is created, the item is refused (by default,
  `--queue-if-dead` overrides) rather than parked forever. `[C4]`

### 5.2 Role (`role:<scope>/<role>`), where the first claim wins
- The item waits in state `ready`. Any live agent that holds `role` within `scope` and has
  capacity (`max_active`) may claim it.
- A claim is one atomic statement (§8.4). **Exactly one claimant wins.** Losers get
  `taken` and move on.
- When there are more ready items than claimers, they are taken by priority, then by
  creation time.
- **Doorbell:** on creation, the hub rings every eligible idle holder (TRANSPORT §5).
  Each one that wakes calls `claim`. Only one succeeds.
- **Requirements:** `requirements` (JSON) can narrow eligibility by capabilities, CLI or
  model. For example `{"capabilities": ["codesys"], "cli": ["claude"]}`.

### 5.3 Team (`team:<repo>/<team>`), where the lead decomposes
1. The item goes to the team's lead as a direct item of kind `decompose`.
2. The lead creates child items (`parent_id` set) that target roles scoped to the team:
   `role:team:<repo>/<team>/<role>`. This is a team-local role scope.
3. The parent moves to `waiting_children` and completes when all its children reach a
   terminal state and the lead closes it.
4. If the lead is dead, the item is offered to `role:team:…/lead` if the team has more
   than one lead holder. Otherwise it goes `blocked` with the reason `no live lead`, and
   the operator is notified. It is never dropped.

### 5.4 Choosing a target from an epic or task

`agentmux dispatch <task_key>` reads the card and chooses, in this order:
1. an explicit `route:` field on the card or its epic (`agent:…`, `role:…`, `team:…`)
2. the epic's default team, if one is set
3. a role derived from the card type (`review` → `reviewer`, `bug`/`feature` → `worker`),
   scoped to the card's repo

The chosen route is written back to the card as a comment, so the operator can see why.

---

## 6. Messages and delivery

### 6.1 Envelope

```json
{
  "id":        "01J9Z3K8V4Q2W7N6X5B0C1D2E3",
  "idem_key":  "tm_210:review:attempt1",
  "from":      "agent:agora/lead/codex_1",
  "to":        "role:agora/reviewer",
  "kind":      "request|reply|note|claim|release|handoff|decompose|result|control",
  "ref":       "TM-210",
  "work_id":   null,
  "body":      "text, or empty when body_ref is set",
  "body_ref":  "repos/agora/agents/reviewer-codex_1/briefs/01J9Z3K8.md",
  "body_sha":  "sha256 of the body bytes",
  "created":   "2026-09-30T02:11:04.512Z",
  "expires":   null,
  "v":         1
}
```

- **`id`** is a ULID: time-ordered, and unique without coordination, which the NATS layer
  needs.
- **`idem_key`** is optional. A second `post` with the same `(from, idem_key)` returns
  the original `id` and creates nothing. `R-MSG-1` `[C13 duplicate delivery, C1 re-sends]`
- **Kinds come from one table** (`message_kinds` in hub.db), not four hardcoded lists.
  `R-MSG-2` `[C9: stale courier silently dropped new kinds, bug #38]`

### 6.2 Delivery states (per recipient)

```
queued ──► offered ──► typed ──► submitted ──► received ──► acked
   │           │          │           │            │
   └───────────┴──────────┴───────────┴────────────┴──► dead (reason)
                    retry (backoff) ◄── nack / lease expiry / verify failure
```

| State | Set by | Meaning |
|---|---|---|
| `queued` | hub | durable, not yet attempted |
| `offered` | hub | the transport was asked to deliver it (a doorbell or a push) |
| `typed` | transport | bytes are in the input box, verified by capture |
| `submitted` | transport | submit was verified: the input box is clear and the CLI went busy, or the placeholder is gone |
| `received` | transport | the CLI's own session log shows the user turn |
| `acked` | recipient | the agent called `ack <id>` |
| `dead` | hub | attempts exhausted, expired, or refused, with a verbatim reason |

- **`acked` is the only success.** The transport stages are recorded evidence, not
  success. `R-DLV-1` `[C1, C5, C10: "sent" meant only that tmux accepted keys]`
- **A stage the transport cannot verify is recorded as `unverified`,** never assumed.
  `R-DLV-2`
- **Redelivery:** a delivery that is not acked within `ack_timeout_s` (default 300, per
  kind) is redelivered. The recipient dedups by `id` (§6.3). `R-DLV-3`

### 6.3 Receiver contract
- `agentmux inbox` (or the MCP or hook equivalent) returns unacked messages oldest first.
- The agent calls `ack <id>` once it has **read** the message. That is receipt, not
  completion.
- Work completion is a separate verb, `done <work_id>`.
- A redelivered message still in view is ignored when its `id` has already been acked.
- The hub keeps a per-recipient acked-id set in the `deliveries` table.

### 6.4 Ordering

Messages for one recipient are delivered **in `id` order**. A message never overtakes an
earlier one that is still pending for the same recipient, whether that one is being
retried or deferred. `R-DLV-4` `[C9: retry overtook earlier message, ORCHESTRATION_RESULT.md]`

### 6.5 Liveness and dead recipients
- **What counts as alive:** `alive` means the transport handle exists **and** the agent
  has heartbeated within `2 × heartbeat_s`. Heartbeats come from the transport's
  output-activity signal, **not** from tmux `session_activity`.
  `R-LIVE-1` `[C4: watchdog killed live agents on a stale metric]`
- **When a recipient dies:**
  - its pending direct deliveries stay `queued`, with `last_error = recipient not live`
  - its claimed work leases expire and go back to `ready` (§8.4)
  - the operator is notified once per recipient, not once per message

  `R-LIVE-2`
- **No watchdog kills an agent that holds a lease, or has acked a message within its
  idle window.** Every kill writes a `kill` event naming who killed it and why. `R-LIVE-3`

### 6.6 Large payloads
- A body over `inline_max` (default 4 KiB) is written to the recipient's `briefs/` file,
  and the envelope carries `body_ref` plus `body_sha`.
- The transport never types more than a bounded doorbell or pointer line.
- The recipient verifies the `sha` on read.

`R-DLV-5` `[C6: >16 KB degrades to bare Enter, D04; C1 long single line becomes placeholder]`
The eval phase settles `inline_max` per CLI (TRANSPORT §6).

---

## 7. Hub API

### 7.1 Transports for the API itself
- **Unix socket** `hub/hub.sock`, for all WSL clients.
- **TCP on `127.0.0.1:<port>`** (off by default), for Windows tools and the dashboard.
  Clients authenticate with the per-agent token issued at registration (§9).
- Both carry the same framing: newline-delimited JSON request and response, plus a
  `subscribe` stream.

### 7.2 Verbs

| Verb | Request | Response |
|---|---|---|
| `register` | repo, role, agent hint, cli, transport handle | session name, token, resolved role |
| `resolve` | address or alias | canonical target(s), liveness |
| `post` | envelope (without id) | id (the same id for a repeated idem_key) |
| `subscribe` | session, kinds | stream of envelopes and doorbells |
| `inbox` | session, limit | unacked envelopes |
| `ack` / `nack` | id(s), reason | ok |
| `claim` | session, scope filter | a work item or `none` |
| `heartbeat` | session, work ids | lease renewals |
| `release` | work id, outcome (`done`/`failed`/`returned`) | ok |
| `deliver_report` | delivery id, stage, evidence | ok (the transport writes stages) |
| `status` | — | counts by state, dead letters, live agents |

**Every verb is idempotent where it can be**: `ack`, `release` and `register` with the
same token return the same result.

---

## 8. hub.db

### 8.1 Connection and PRAGMAs
- SQLite 3.45.1 is present in WSL, so everything listed below is available.
- The hub keeps one writer connection, used by a single asyncio writer task that drains
  a queue, and N read-only connections.
- **PRAGMAs:**

```sql
PRAGMA application_id = 0x414D5548;   -- 'AMUH'
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;          -- durable at checkpoint; WAL gives crash safety
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
PRAGMA wal_autocheckpoint = 1000;
PRAGMA temp_store = MEMORY;
-- periodic: PRAGMA wal_checkpoint(TRUNCATE); PRAGMA optimize;
```

- **Every write transaction is `BEGIN IMMEDIATE`,** so lock contention shows up at
  `BEGIN` and never as a mid-transaction `SQLITE_BUSY`.
- **Migrations** are numbered SQL files applied under `user_version`, each inside its own
  transaction.
- **Online backup** (`sqlite3.Connection.backup`) runs every hour and before every
  migration. The last 24 are kept.

### 8.2 Change detection without polling the tables
- The writer task pushes to subscribers directly after commit.
- Out-of-process readers, such as the dashboard, use `PRAGMA data_version`, which is cheap
  and changes on any commit by another connection, to know when to re-query.

### 8.3 Schema (initial)

```sql
CREATE TABLE repos (
  repo TEXT PRIMARY KEY CHECK (repo GLOB '[a-z0-9_]*' AND length(repo) BETWEEN 1 AND 32),
  title TEXT, default_branch TEXT, created TEXT NOT NULL
) STRICT;
CREATE TABLE repo_aliases (alias TEXT PRIMARY KEY, repo TEXT NOT NULL REFERENCES repos) STRICT;  -- normalized remotes, legacy names
CREATE TABLE repo_paths  (repo TEXT NOT NULL REFERENCES repos, path TEXT NOT NULL, kind TEXT NOT NULL, PRIMARY KEY (repo, path)) STRICT;
CREATE TABLE groups      (grp TEXT NOT NULL, repo TEXT NOT NULL REFERENCES repos, PRIMARY KEY (grp, repo)) STRICT;

CREATE TABLE agents (
  session   TEXT PRIMARY KEY,                       -- <repo>-<role>-<agent>
  repo      TEXT NOT NULL REFERENCES repos,
  role      TEXT NOT NULL,
  agent     TEXT NOT NULL,
  cli       TEXT NOT NULL,
  role_snapshot TEXT NOT NULL CHECK (json_valid(role_snapshot)),
  transport TEXT NOT NULL,                          -- 'tmux'
  handle    TEXT,                                   -- e.g. tmux pane id %42
  token_sha TEXT NOT NULL,
  state     TEXT NOT NULL CHECK (state IN ('starting','ready','busy','blocked','dead')),
  last_seen TEXT, created TEXT NOT NULL,
  UNIQUE (repo, role, agent)
) STRICT;
CREATE TABLE legacy_names (legacy TEXT PRIMARY KEY, session TEXT NOT NULL) STRICT;

CREATE TABLE teams (repo TEXT NOT NULL, team TEXT NOT NULL, lead_role TEXT NOT NULL DEFAULT 'lead', PRIMARY KEY (repo, team)) STRICT;
CREATE TABLE team_members (repo TEXT NOT NULL, team TEXT NOT NULL, session TEXT NOT NULL REFERENCES agents, PRIMARY KEY (repo, team, session)) STRICT;

CREATE TABLE message_kinds (kind TEXT PRIMARY KEY, ack_timeout_s INTEGER NOT NULL DEFAULT 300, max_attempts INTEGER NOT NULL DEFAULT 12) STRICT;

CREATE TABLE messages (
  id TEXT PRIMARY KEY,                              -- ULID
  sender TEXT NOT NULL, target TEXT NOT NULL,       -- canonical address
  kind TEXT NOT NULL REFERENCES message_kinds,
  ref TEXT, work_id TEXT, body TEXT, body_ref TEXT, body_sha TEXT NOT NULL,
  idem_key TEXT, created TEXT NOT NULL, expires TEXT,
  meta TEXT CHECK (meta IS NULL OR json_valid(meta)),
  UNIQUE (sender, idem_key)
) STRICT;
CREATE VIRTUAL TABLE messages_fts USING fts5(body, content='messages', content_rowid='rowid');

CREATE TABLE deliveries (
  message_id TEXT NOT NULL REFERENCES messages,
  recipient  TEXT NOT NULL,                         -- session or virtual:<name>
  state TEXT NOT NULL CHECK (state IN ('queued','offered','typed','submitted','received','acked','dead')),
  attempts INTEGER NOT NULL DEFAULT 0, next_at TEXT, last_error TEXT,
  evidence TEXT CHECK (evidence IS NULL OR json_valid(evidence)),  -- per-stage verified/unverified + captures
  updated TEXT NOT NULL,
  PRIMARY KEY (message_id, recipient)
) STRICT;
CREATE INDEX deliveries_live ON deliveries (recipient, message_id) WHERE state NOT IN ('acked','dead');
CREATE INDEX deliveries_due  ON deliveries (next_at) WHERE state IN ('queued','offered');

CREATE TABLE work_items (
  id TEXT PRIMARY KEY, parent_id TEXT REFERENCES work_items,
  task_key TEXT,                                    -- cc.db card key, soft reference
  repo TEXT NOT NULL REFERENCES repos,
  target TEXT NOT NULL,                             -- agent:/role:/team: address
  target_kind TEXT GENERATED ALWAYS AS (substr(target, 1, instr(target, ':') - 1)) VIRTUAL,
  requirements TEXT CHECK (requirements IS NULL OR json_valid(requirements)),
  priority INTEGER NOT NULL DEFAULT 100,
  state TEXT NOT NULL CHECK (state IN ('ready','claimed','waiting_children','blocked','done','failed','cancelled')),
  claimed_by TEXT, lease_until TEXT, attempts INTEGER NOT NULL DEFAULT 0,
  blocked_reason TEXT, created TEXT NOT NULL, updated TEXT NOT NULL
) STRICT;
CREATE INDEX work_ready ON work_items (target, priority, created) WHERE state = 'ready';
CREATE INDEX work_leased ON work_items (lease_until) WHERE state = 'claimed';

CREATE TABLE claims (                               -- file/resource claims, replacing claims/*.json
  repo TEXT NOT NULL, path TEXT NOT NULL, holder TEXT NOT NULL, work_id TEXT,
  lease_until TEXT NOT NULL, created TEXT NOT NULL,
  PRIMARY KEY (repo, path)
) STRICT;

CREATE TABLE events (                               -- append-only audit; written by triggers
  seq INTEGER PRIMARY KEY, at TEXT NOT NULL, entity TEXT NOT NULL, entity_id TEXT NOT NULL,
  event TEXT NOT NULL, actor TEXT, detail TEXT CHECK (detail IS NULL OR json_valid(detail))
) STRICT;

CREATE TABLE nats_outbox (                          -- transactional outbox; empty until the bridge exists
  seq INTEGER PRIMARY KEY, subject TEXT NOT NULL, payload TEXT NOT NULL, created TEXT NOT NULL, sent TEXT
) STRICT;
```

**Triggers:**
- `AFTER UPDATE OF state ON deliveries`, and the same on `work_items`, insert into
  `events`. The audit trail cannot be skipped by a code path that forgets to log.
- `messages_fts` stays in sync through insert and delete triggers.

### 8.4 The first-claim statement

```sql
BEGIN IMMEDIATE;
UPDATE work_items
   SET state = 'claimed', claimed_by = :session, attempts = attempts + 1,
       lease_until = strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '+' || :lease_s || ' seconds'),
       updated = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
 WHERE id = (SELECT id FROM work_items
              WHERE state = 'ready' AND target IN (SELECT value FROM json_each(:eligible_targets))
                AND (requirements IS NULL OR hub_meets(requirements, :agent_caps) = 1)
              ORDER BY priority, created LIMIT 1)
RETURNING *;
COMMIT;
```

- `:eligible_targets` is every role address the caller satisfies: repo, groups, `*`, and
  team.
- `hub_meets` is a Python function registered on the connection.
- **Expiring leases:** a sweeper runs every 5 s, sets expired `claimed` items back to
  `ready` (up to `max_attempts`, then `failed`), and releases their `claims` rows.

---

## 9. Identity

- **As built, local identity is process ancestry** (`hub/server.py` `identify`). The
  unix socket gives the hub the caller's pid (`SO_PEERCRED`), and the hub walks
  `/proc/<pid>/stat` parent links until it reaches a registered agent's pane pid.
  - A caller inside a tmux pane that is not registered is `unregistered`, and may
    neither act as the operator nor use `--as`.
  - A caller outside every pane is the operator.
  - Nothing the caller says about itself is consulted.
- **Tokens (below) are the design for callers the kernel cannot vouch for:** TCP, and
  later NATS.
- **The token, not the environment, is the identity.**
  - At registration the hub issues a per-agent token. The transport injects it into the
    agent's own process environment, and stores it in `agents/<…>/run/token` (mode 0600).
  - Every verb carries the token. The hub maps token to session.
  - `$AGENTMUX_AGENT` is kept for display only and is **never trusted**.

  `R-ID-1` `[C8: the codex shared daemon made every agent's shell report agora-image; resolve_identity could not see it]`
- **The transport handle is cross-checked on `deliver_report`.** A report for a pane
  whose handle doesn't match the registered session is refused and logged as an
  `identity` event. `R-ID-2` `[C8: D11 stale pane id]`
- The orchestrator is a registered agent (`<repo>-lead-orchestrator` or
  `virtual:orchestrator`), with the same token rules. No special warrant file.

---

## 10. Migration from the flat layout

1. The hub starts with an empty `hub.db`. The courier stays in charge until step 4.
2. **New spawns** register with the hub and get protocol names and a directory under
   `repos/`.
3. **Live legacy agents are never renamed.**
   - `agentmux hub adopt <legacy-name> --repo R --role X` creates an `agents` row with a
     protocol session name and a `legacy_names` alias. The tmux session keeps its old
     name until it exits.
   - The alias resolves both ways.
4. **Courier retirement:**
   - The hub imports outboxes from each cursor onward. Outbox files become read-only.
   - `agentmux post` switches to `hub post`.
   - The courier daemon stops.
5. **Archive:** when `agentmux list` shows no legacy agent, move the flat directories
   (`run/`, `queue/`, `courier/`, `inbox/`, `claims/`, `dispatch/`, `logs/`) to
   `archive/legacy-<date>/`. Take a backup first, and move rather than delete.
6. **Windows home:** back up `C:\Users\Nick\.agentmux`, including its old `cc.db`, to
   `archive/`, then replace it with the directory symlink.

---

## 11. Network readiness (NATS, later)

| Protocol | NATS |
|---|---|
| direct `agent:R/X/A` | subject `am.<node>.R.X.A` |
| role `role:S/X` | subject `am.work.S.X`, JetStream work-queue stream, consumer group `X`. A work queue delivers each message to exactly one consumer, which is the same rule as first claim. |
| team `team:R/T` | subject `am.team.R.T` |
| doorbell | core NATS (not persisted), `am.bell.<node>.<session>` |
| ack | JetStream ack on the delivery. The hub mirrors it into `deliveries`. |
| leaf node | each machine runs a hub plus a NATS leaf. The hub bridges through `nats_outbox` (written in the same transaction as the state change) and a subscriber that writes inbound envelopes into local `messages`. |

**The invariant that keeps this cheap later:** every part token is `[a-z0-9_]`, so no
address ever needs escaping to become a subject.

---

## 12. Requirement index

| ID | Requirement | Class |
|---|---|---|
| R-NAME-1 | Parts `[a-z0-9_]`, hyphen is the separator only | C8 |
| R-NAME-2 | The hub gives out session names; a live duplicate is refused | C8, C4 |
| R-HOME-1 | The hub refuses a 9P/drvfs db path; Windows uses the API | C12 |
| R-HOME-2 | Every agent path sits under its repo and session key; claims are keyed by (repo, path) | cross-repo claim collision |
| R-MSG-1 | `idem_key` dedup on post | C1, C13 |
| R-MSG-2 | One kinds table | C9 |
| R-DLV-1 | Only `acked` counts as success | C1, C5, C10 |
| R-DLV-2 | Unverifiable stages are recorded as unverified | C10 |
| R-DLV-3 | Redeliver until acked, dedup by id | C1, C5 |
| R-DLV-4 | Per-recipient ordering, including retries | C9 |
| R-DLV-5 | Large bodies go by file reference; the transport types only bounded lines | C6, C1 |
| R-LIVE-1 | Liveness from output activity and heartbeat, never session_activity | C4 |
| R-LIVE-2 | A dead recipient's deliveries are held and its leases returned; one notification | C4 |
| R-LIVE-3 | Never kill an agent holding a lease; every kill is an event | C4 |
| R-ID-1 | Token identity; the environment is display-only | C8 |
| R-ID-2 | The transport handle is cross-checked | C8 |
| R-EVID-1 | Never destroy delivery evidence: keep pane logs across respawn and CLI homes across teardown, and archive them rather than delete them. **Not built:** the hub still spawns through `agentmux spawn`, which truncates the log (`agentmux.sh` spawn) and whose `claude_config_gc` deletes claude homes | C14 |
| R-QUEUE-1 | Treat a CLI's internal input queue as not received: only the CLI's own session log (or the agent's `inbox`/`ack`) counts. Built through ack; the CLI-log receipt is not built | C15 |

`[trace pending]`: counts and evidence refs are added from Phase A output.
