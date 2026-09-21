# CC — Control Center

Rebrand and overhaul of the agentmux dashboard into a multi-view operations
console. **This pass is a rough-in**: real architecture, real persistence, real
endpoints, and honest placeholders only where a protocol genuinely cannot work
unprivileged.

| Role | Agent | Owns |
| --- | --- | --- |
| Orchestrator + frontend | claude | theme system, logo, activity bar, view shell, all view UIs, this spec |
| Backend + data | codex | SQLite store, API endpoints, MQTT client, device registry |
| Reviewer | grok | correctness + security review of the whole pass |

Standing constraints from the existing dashboard, all still binding:

- Python 3 **stdlib only**. No pip.
- Bind **127.0.0.1** only.
- **No secret is ever entered through the browser.** Credentialed actions are
  displayed as commands with a "your terminal" tag.
- Terminals stay read-only; the page never sends keystrokes to an agent.
- Any mutating endpoint repeats the `/api/resize` guards: POST only,
  `Content-Type: application/json` required (415), cross-origin `Origin`
  rejected (403), bounded body, validated inputs.
- Nothing from the backend is interpolated as HTML in the frontend.

## Brand

**CC — Control Center.** Valve-era Steam: flat dark slate panels, tight 1px
borders, low-chroma greys, dense information. Modernised — no gradients, no
bevels, no gloss. Accent is a **thin light orange** (Half-Life 2 / Orange Box),
used sparingly: active nav item, focus ring, key values, one-pixel rules. Orange
is an accent, never a fill.

Palette (the `cc-dark` theme):

| Token | Value | Use |
| --- | --- | --- |
| `--bg` | `#1b2027` | app background |
| `--panel` | `#22272e` | panels, bars |
| `--panel-2` | `#171b21` | wells, terminals |
| `--line` | `#2f363f` | 1px borders |
| `--text` | `#d8dee6` | body |
| `--muted` | `#8b949e` | secondary |
| `--accent` | `#ff9b4c` | thin light orange accent |
| `--accent-dim` | `#c2762f` | hover/pressed |
| `--safe` | `#7fb069` | ok |
| `--warn` | `#e0af68` | warning |
| `--danger` | `#e06c75` | error |

## Theme system — claude

Themes become **data**, selectable in Settings, persisted in `localStorage`.

- `themes.json` in `dashboard/`: `{ id, name, dark, tokens: { "--bg": "…" } }`.
- A theme is applied by writing tokens onto `document.documentElement.style`.
  No stylesheet swapping, no flash.
- Ship `cc-dark` (default), `cc-light`, and `classic-dark` (the current palette,
  so nothing is lost).
- Adding a theme must be an edit to `themes.json` only.
- `themes.json` must be added to the static allowlist in `server.py`.

## Shell — claude

Replace the top tab bar with a **left activity bar**, VS Code in spirit but
compact: 44px wide, icon-only, tooltip on hover, 1px orange left-edge marker on
the active item.

Views, in order:

| Icon | View | Contents |
| --- | --- | --- |
| terminals | **Terminals** | the existing live xterm grid, unchanged |
| queue | **Message Queue** | agent-to-agent traffic and the orchestrator's plan |
| board | **Task Board** | epics and tasks, persisted locally |
| journal | **Journal** | append-only operational log |
| tickets | **Ticket Reviewer** | Jira issues, review and transition |
| iiot | **IIOT Field** | device registry, MQTT, BOOTP, Modbus |
| settings | **Settings** | theme picker, **Resources** (moved here), config |

The Resources tab moves into Settings as a section. `resources.json` stays the
manifest and keeps its existing security model.

## Local store — codex

`~/.agentmux/cc.db`, SQLite via stdlib `sqlite3`. Purpose is **archival project
management**: it must survive session restarts and be queryable later.

Schema, minimum:

```sql
epics(id INTEGER PK, key TEXT UNIQUE, title TEXT NOT NULL, status TEXT NOT NULL
      DEFAULT 'open', jira_key TEXT, created_at TEXT, updated_at TEXT, notes TEXT)
tasks(id INTEGER PK, epic_id INTEGER REFERENCES epics(id) ON DELETE CASCADE,
      title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'todo',
      agent TEXT, jira_key TEXT, created_at TEXT, updated_at TEXT)
journal(id INTEGER PK, at TEXT NOT NULL, kind TEXT NOT NULL, agent TEXT,
        subject TEXT, body TEXT)
messages(id INTEGER PK, at TEXT NOT NULL, sender TEXT NOT NULL, recipient TEXT,
         kind TEXT NOT NULL, body TEXT, ref TEXT)
devices(id INTEGER PK, name TEXT NOT NULL, kind TEXT NOT NULL, address TEXT,
        port INTEGER, protocol TEXT, meta TEXT, created_at TEXT)
```

Rules:
- `PRAGMA journal_mode=WAL`, `foreign_keys=ON`.
- Open a **new connection per request** — the server is threaded and a sqlite3
  connection is not shareable across threads by default.
- Timestamps ISO-8601 with offset, generated server-side. Never trust a client clock.
- Every write goes through a parameterised statement. No string interpolation
  into SQL, ever.
- Schema created idempotently on first use; record `PRAGMA user_version` so a
  later migration has something to branch on.

## Message queue — codex + claude

This finally implements the filesystem messaging we designed and never built.

- Agents append newline-delimited JSON to `~/.agentmux/queue/<agent>.jsonl`.
  One object per line: `{at, sender, recipient, kind, body, ref}`.
- `kind` is one of `plan | request | reply | status | finding | error`.
- Backend tails those files, merges by timestamp, and also serves rows persisted
  in `messages`. Same hardening as the log streamer: regular files only, reject
  `st_nlink > 1`, validated names, size caps.
- `GET /api/messages?limit=&since=` returns merged, newest-last.
- The orchestrator's plan is just `kind: "plan"` from sender `orchestrator`, so
  the view can pin it.

## IIOT Field — codex

Rough-in, and **honest about privilege**:

- **Device registry** — CRUD over the `devices` table. Real and complete.
- **MQTT** — a minimal MQTT 3.1.1 client on stdlib TCP: CONNECT, SUBSCRIBE,
  PUBLISH, and a bounded recent-message buffer. No TLS in this pass; say so.
- **BOOTP — cannot work unprivileged.** Binding UDP 67/68 needs root and this
  process runs as uid 1000. Do **not** fake it. The view shows the requirement
  and the exact privileged command to run; the backend exposes a read-only
  parse of any captured output. Anything else would be a lie in the UI.
- **Modbus** — this machine has a `modbus` MCP server. Prefer routing Modbus
  reads through an agent rather than reimplementing the protocol here.

## Done means

All seven items below are met. Verified with 233 checks across four suites plus
browser checks with the console open (`node --check` passes on runtime errors, which
is how a duplicated token that broke the whole script on load got through once).

1. **Done.** CC theme is the default; switching works from Settings and persists.
2. **Done.** The left activity bar switches all seven views; Terminals still streams.
3. **Done.** `cc.db` is created; epics/tasks/journal/messages/devices round-trip,
   and epics/tasks/devices can also be deleted (journal deliberately cannot).
4. **Done.** `/api/messages` merges the per-agent queue files with DB rows by
   timestamp, and the orchestrator's plan is pinned.
5. **Partly, and stated as such.** MQTT connect/subscribe/publish is verified
   against a stub broker started in-process — there is no broker on this machine, so
   no live-broker claim is made. BOOTP states its privilege requirement instead of
   pretending, and `taskmgmt/bootp_probe.py` is the listen-only privileged helper.
6. **Done.** Resources renders inside Settings, alongside a new Authentication
   section.
7. **Done.** The security suite still passes and every new mutating endpoint
   (`/api/delete`, `/api/auth/select`, both MQTT routes) carries the same guards:
   POST only, JSON content type required, cross-origin `Origin` rejected, bounded
   body, validated input.

## Added after this spec was written

- **Authentication** as a provider/method manifest (`auth.json`): shared attributes
  on the provider, method-specific ones per method, `--auth` on spawn, and a
  collapsible Settings section. See the Authentication section of the README.
- **Deletion** and a full status vocabulary on the board — see
  `STATUS_CCC_2026-09-19.md` items 13 and 14 for why both were gaps.
- **A Ticket Reviewer that reviews.** Reads real Jira issues, lists transitions on
  demand, comments and transitions. The two write endpoints are the only ones that
  touch a system outside this machine: the UI confirms first, and there is no
  dry-run mode on them. `taskmgmt/atlassian.py` is executed for the first time by
  `test_tickets.py` (48 checks). The **live** path is still unverified — no
  credentials here, and a test must not write to a real tracker.

## What is still a user action

Nothing in this spec is blocked on code. These need a human:

- `codex mcp login atlassian` and `python3 taskmgmt/setup_atlassian.py` — until then
  the Atlassian resource correctly reads MISSING and the Ticket Reviewer has no Jira
  to talk to.
- WSL `claude` `/login`. Windows keeps its login in DPAPI, which Linux cannot read,
  so no symlink can share it.
- A Bedrock gateway, if codex is to use Bedrock. Claude Code needs none.
