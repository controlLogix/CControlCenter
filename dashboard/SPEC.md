# agentmux dashboard — build spec

A small local web dashboard showing live agentmux agents. Built by three agents
working from this one contract.

| Role | Agent | Owns |
| --- | --- | --- |
| Orchestrator + frontend | claude | `index.html`, `app.js`, `style.css`, this spec, integration |
| Backend + images | codex | `server.py`, `assets/*.svg` |
| Analyst + reviewer | grok | review of everything; no files |

## Hard constraints

- **Read-only.** The dashboard must never write to, kill, or spawn an agent. It
  reads state only. No `tmux kill-session`, no writes under `~/.agentmux/run/`.
- **Localhost only.** Bind `127.0.0.1`. Never `0.0.0.0`.
- **Stdlib only.** Python 3 standard library. No pip installs.
- **Never print secrets.** `~/.agentmux/env` may hold API keys. Do not read,
  echo, or serve it. Never serve any file outside `dashboard/`.
- Port **8787**.

## Data source

Agent state lives in `~/.agentmux/run/<name>.<ext>`:

| File | Contents |
| --- | --- |
| `<name>.cli` | `codex` / `claude` / `grok` / `shell` / passthrough string |
| `<name>.cwd` | working dir |
| `<name>.perms` | `UNRESTRICTED` / `sandboxed` / `n/a` |
| `<name>.launch` | effective launch command line |
| `<name>.started` | ISO-8601 start time |
| `<name>.pane` | tmux pane id (e.g. `%3`) |

Live sessions come from `tmux -L agentmux list-sessions -F '#{session_name}'`.
Attached vs detached from `tmux -L agentmux list-clients -t '=<name>'` (non-empty
= attached).

**An agent may be in `run/` but dead** (harness cleans up on kill, but not if a
pane dies on its own). Report those as `state: "stale"` — do not assume
`run/` implies alive.

## API contract — backend MUST match exactly

`GET /api/agents` → `200 application/json`

```json
{
  "generated_at": "2026-09-18T21:00:00-05:00",
  "tmux_server": true,
  "agents": [
    {
      "name": "rev",
      "cli": "codex",
      "perms": "UNRESTRICTED",
      "cwd": "/mnt/c/path/to/repo",
      "launch": "codex --profile yolo",
      "started": "2026-09-18T20:00:00-05:00",
      "state": "detached",
      "uptime_seconds": 3600
    }
  ]
}
```

- `state` is one of `attached` | `detached` | `stale`.
- `tmux_server` is `false` when no tmux server is running (then every `run/`
  entry is `stale`).
- Missing field → `null`, never a crash and never the string "None".
- `uptime_seconds` is an integer, or `null` if `started` is unparseable.
- Unknown route → `404` JSON `{"error":"not found"}`. Never a stack trace.

`GET /` → `index.html`. `GET /app.js`, `/style.css`, `/assets/<file>.svg` → the
file with a correct `Content-Type`. Path traversal (`..`, absolute paths,
symlinks out of the tree) must be rejected with `403`.

## Images — codex

Four hand-written SVGs in `assets/`, no raster, no external fonts, each ≤ 2 KB:

| File | Purpose |
| --- | --- |
| `logo.svg` | 32×32 mark for the header |
| `state-attached.svg` | 12×12 filled dot |
| `state-detached.svg` | 12×12 hollow ring |
| `state-stale.svg` | 12×12 dot with a slash |

Use `currentColor` so the frontend can theme them via CSS. No `<image>`, no
embedded base64, no scripts inside the SVG.

## v2 — live terminal grid (supersedes the table layout)

The table is replaced by an **X-by-Y grid of live terminals**, one cell per
agent, so every agent's output is watchable at once. `xterm.js` renders each
cell; the backend streams via **SSE**.

`xterm.js` 5.5.0 is **vendored** in `vendor/` (`xterm.js`, `xterm.css`,
`addon-fit.js`). Serve those from `/vendor/<file>`. Still no CDN at runtime.

### Streaming endpoint — codex

`GET /api/stream/<name>?tail=<bytes>` → `200 text/event-stream`

Source is the agent's `pipe-pane` log at `~/.agentmux/logs/<name>.log`, which is
append-only and holds **raw ANSI** — exactly what xterm.js wants. Do not strip
escapes.

- **Payload MUST be base64.** SSE is line-delimited text; agent output contains
  CR, LF and control bytes that would corrupt the framing. Emit
  `data: <base64 of the raw chunk>\n\n`. The frontend decodes and writes to
  xterm.
- On connect, send at most the **last `tail` bytes** (default 16384, cap 262144)
  so a 500 KB log does not blow up the browser, then follow the file for
  appends.
- Send `event: eof` when the agent's session disappears, then close.
- Send a comment heartbeat (`: ping\n\n`) every 15s so idle connections and
  proxies do not drop.
- Handle **truncation/rotation**: if the file shrinks, reset to offset 0 rather
  than looping forever.
- `<name>` MUST be validated against `^[A-Za-z0-9_.-]{1,64}$` and rejected with
  400 otherwise. Never build a path from an unvalidated name. Unknown agent or
  missing log → 404 JSON.
- Threading is required (`ThreadingHTTPServer`) since each stream holds a
  connection. Cap concurrent streams at 16; beyond that return 503.

## v4 — pane size driven by the browser cell (opt-in)

Measured problem: panes are 200x49; a 2-column cell holds ~111 terminal columns
and a 3-column cell ~73. Building the terminal at 200 cols and scaling it down is
geometrically correct but gives ~2.4px per character. The only way to get correct
AND readable is to make the **agent's pane** match the cell.

This is the **first mutating endpoint** in the dashboard. It is **opt-in** from the
ribbon and **off by default**, because:

- It writes to the agent's environment. A TUI will redraw; some agents lay out
  differently at different widths.
- It changes what `agentmux read` / `capture-pane` returns for that agent, which
  is audit finding **D26**. The harness and the dashboard would be sharing one
  mutable geometry.

### `POST /api/resize/<name>` — codex

Body: `{"cols": <int>, "rows": <int>}` → `200 {"ok":true,"cols":C,"rows":R}`

- `<name>` validated by the existing `NAME_PATTERN` before any use.
- `cols` clamped to `20..400`, `rows` to `5..200`; non-integer or out-of-range →
  `400` JSON. Never pass an unvalidated value to tmux.
- Pane id comes from `~/.agentmux/run/<name>.pane` and MUST match `^%[0-9]+$`
  before use. Run `tmux -L agentmux resize-pane -t <pane> -x C -y R`.
- If the requested size equals the current size, return `200` without calling
  tmux (the frontend debounces, but do not trust it).
- `GET`/`HEAD` on this path → `405`. It must not be triggerable by an `<img>` or
  a stylesheet.

**CSRF is the real risk here**, because any page in the browser can reach
`127.0.0.1`. Two mandatory guards:

1. **Require `Content-Type: application/json`.** A cross-origin `fetch` with that
   content type forces a CORS preflight, which this server does not answer, so
   the request never arrives. A plain HTML form cannot send that content type.
2. **Reject a cross-origin `Origin` header.** Absent is allowed (same-origin
   fetch may omit it); present and not `http://127.0.0.1:8787` /
   `http://localhost:8787` → `403`.

Do not add permissive CORS headers. Do not accept form encoding.

### Security, restated for v2

Streaming pane logs is a **new exposure**: those logs contain relayed prompt
text. Mitigations that are mandatory:

- Bind `127.0.0.1` only — unchanged.
- Serve logs **only** via `/api/stream/<name>` for a validated name. Never
  expose `~/.agentmux/logs/` as a directory, and never serve `~/.agentmux/env`.
- Reject a `name` that resolves, after joining, outside `~/.agentmux/logs/`.

### Frontend — claude

Single page, no build step, no framework, no CDN.

- Auto-layout: columns = `ceil(sqrt(n))`, rows to fit; recompute on resize and
  when the agent set changes.
- One `xterm.js` instance per agent, fitted to its cell via `addon-fit`.
- Each cell has a header: agent name, cli, state dot, permissions badge.
- Keep polling `/api/agents` every 3s for the agent set; terminals stream
  independently over SSE.
- Reuse an existing terminal when an agent persists across polls — do **not**
  tear down and recreate, or scrollback is lost on every poll.
- Terminals are **read-only** (no stdin wired). This dashboard never sends
  keystrokes to an agent.
- Must survive `[]`, a 500, malformed JSON, and an SSE drop (reconnect with
  backoff).

## Done means

1. `python3 server.py` starts, binds 127.0.0.1:8787, no traceback.
2. `curl -s localhost:8787/api/agents` returns schema-valid JSON.
3. Page renders live agents, and still renders with zero agents.
4. Traversal attempt (`/../../../etc/passwd`) returns 403, not file contents.
5. grok's review has no unresolved correctness or security finding.
