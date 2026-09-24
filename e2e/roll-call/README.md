# Agent Roll Call

A tiny web app that shows the four agents of a coordinated run, one card each: avatar, name,
role and provider. No dependencies, no build step, no external requests.

Requires Node.js 18 or newer (tested on 22).

## Run

```sh
node server/index.js            # http://localhost:4173
PORT=8080 node server/index.js  # any other port
```

Open the printed URL. The page fetches `/api/agents` and renders the cards. It works down to
360px wide and follows the system light/dark setting (`prefers-color-scheme`).

## Test

```sh
node --test
```

Run from the repository root. The tests start the server on a random port and cover
`/api/health`, `/api/agents`, static files, 404s and path-traversal rejection (plain and
URL-encoded `..`, encoded slashes and backslashes).

## API

| Route | Response |
|---|---|
| `GET /api/health` | `{ "ok": true }` |
| `GET /api/agents` | Array of 4 `{ id, name, role, provider, avatar }`; `avatar` is `/avatars/<id>.svg` |
| anything else | Static file from `web/`, `404` if missing, `403` on `..` traversal, `400` on malformed paths |

## Layout

```
server/index.js   HTTP server (exports createServer for tests)
web/              index.html, app.js, style.css
web/avatars/      <id>.svg + manifest.json, drawn by the imager agent
test/             node:test suite
```

If an avatar file is missing, the card shows a neutral lettered placeholder in the same
square frame, so the layout does not shift.

## Run it as an agentmux team

The app is also the product of an end-to-end coordination exercise: four agents rebuild it from
`BRIEF.md`. The agents are defined in the repository roster, `.agentmux/agents/rollcall-*.md`:

| Definition | Role | CLI | Owns |
|---|---|---|---|
| `rollcall-lead` | lead | claude | the brief and the definition of done; writes no code |
| `rollcall-dev` | worker | claude | `server/`, `web/*.html,js,css`, `test/`, `README.md` |
| `rollcall-imager` | worker | grok | `web/avatars/` |
| `rollcall-reviewer` | reviewer | grok | the gate: `run verdict`; never edits |

From the repository root, inside WSL:

```sh
R=$(agentmux run start "Rebuild e2e/roll-call from BRIEF.md")
for a in lead dev imager reviewer; do
  agentmux spawn rollcall-$a --agentdef rollcall-$a --cwd "$PWD/e2e/roll-call"
done
agentmux run assign "$R" --worker rollcall-dev    --reviewer rollcall-reviewer --brief "server, page, tests, README per BRIEF.md"
agentmux run assign "$R" --worker rollcall-imager --reviewer rollcall-reviewer --brief "four SVG avatars + manifest per BRIEF.md"
agentmux run status "$R"      # one line per job
agentmux run complete "$R"    # refuses until the reviewer has passed every job
agentmux run teardown "$R"
```

Coordination uses agentmux's own primitives: `claim`/`release` before editing, `post --kind
request|reply|finding|status` between agents, `journal` for decisions, `run submit` from a worker
and `run verdict --pass|--fail` from the reviewer.
