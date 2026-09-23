# Agent Roll Call

A tiny web app that lists the four agents in this run — one card per agent with its avatar, name,
role and provider. It exists to test four agents working together (see [BRIEF.md](BRIEF.md)).

Plain Node.js (built-in modules only): no dependencies, no install step, no build step.
Requires Node 18 or newer.

## Run

```sh
node server/index.js            # http://localhost:4173
PORT=8080 node server/index.js  # any other port
```

Open the printed URL. The page fetches `/api/agents` and renders the cards; it works down to
360px wide and follows the system light/dark setting. If an avatar in `web/avatars/` is missing,
the card shows a neutral placeholder with the agent's initial instead.

## API

| Route | Response |
|---|---|
| `GET /api/agents` | JSON array of 4 agents: `{ id, name, role, provider, avatar }`, `avatar` = `/avatars/<id>.svg` |
| `GET /api/health` | `{ "ok": true }` |
| anything else | a static file from `web/`, or `404` |

Paths containing `..` (including percent-encoded forms) are rejected with `403`.

## Test

```sh
node --test
```

The tests start the server on a free port and cover both API routes, static files, the 404, and
path-traversal rejection.

## Layout

```
server/index.js   HTTP server (API + static files)
web/              index.html, app.js, style.css
web/avatars/      one SVG per agent (drawn separately by the imager agent)
test/             node:test suite
```
