# Brief: Agent Roll Call

A tiny web app that exists to test four agents working together. The product is small on purpose;
the coordination is what is being tested.

## What to build

- **Backend** (`server/`): a dependency-free Node.js HTTP server (`node server/index.js`, port from
  `PORT`, default 4173).
  - `GET /api/agents` returns JSON: an array of exactly 4 agents, each
    `{ id, name, role, provider, avatar }`, where `avatar` is a path under `/avatars/`.
  - `GET /api/health` returns `{ "ok": true }`.
  - Everything else is served statically from `web/`. Unknown paths return 404, and path traversal
    (`..`) is rejected.
- **Frontend** (`web/`): `index.html` + `app.js` + `style.css`, no build step and no external
  requests. It fetches `/api/agents` and renders one card per agent: avatar, name, role, provider.
  It works at 360px wide and has a dark mode (`prefers-color-scheme`).
- **Avatars** (`web/avatars/`): one generated image per agent, named `<id>.png` (or `.jpg`), made with
  the xAI Images API, with `web/avatars/manifest.json` recording provenance. The API may not return
  squares, so the frontend shows each avatar in a square frame (`object-fit: cover`) that is readable at 96px:
  - `conductor`: orchestrator, Claude
  - `developer`: full-stack developer, Claude
  - `imager`: image generator, Grok
  - `reviewer`: final reviewer, Grok
- **Tests**: `node --test` covers both API routes, the 404, and path-traversal rejection.
- **README.md**: how to run it and test it.

## Done means

1. `node --test` passes.
2. `node server/index.js` serves the page, which shows 4 cards with 4 avatars.
3. The reviewer has sent `REVIEW APPROVE` and the conductor has sent `ACCEPT` for each deliverable.

## Out of scope

Frameworks, package installs, databases, auth, deployment.
