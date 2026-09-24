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
