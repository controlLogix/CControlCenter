# Agent Roll Call

A tiny, dependency-free web app that shows the four agents of a coordinated run
(conductor, developer, imager, reviewer) as cards with avatar, name, role and provider.
The spec is in [BRIEF.md](BRIEF.md).

Requires Node.js 18 or newer. There is nothing to install.

## Run

```sh
node server/index.js            # http://localhost:4173
PORT=8080 node server/index.js  # any other port
```

Open the printed URL. The page fetches `/api/agents` and renders one card per agent.
If an avatar file in `web/avatars/` is missing, the card shows a neutral placeholder instead.

## API

| Route | Response |
|---|---|
| `GET /api/agents` | JSON array of 4 agents: `{ id, name, role, provider, avatar }`, with `avatar` = `/avatars/<id>.svg` |
| `GET /api/health` | `{ "ok": true }` |

Every other path is served statically from `web/`. Unknown paths return `404`;
paths containing a `..` segment (literal or percent-encoded) return `400`.

## Test

From the repository root:

```sh
node --test
```

The tests in `test/api.test.js` start the server on a random port and cover both API routes,
serving the page, the 404, and path-traversal rejection. They do not need the avatars to exist.

## Layout

```
server/index.js    HTTP server (API + static files from web/)
server/agents.js   the four agents
web/index.html     page
web/app.js         fetches /api/agents and renders the cards
web/style.css      layout (works at 360px) and dark mode via prefers-color-scheme
web/avatars/       <id>.svg avatars and manifest.json (made by the imager agent)
test/api.test.js   node --test suite
```
