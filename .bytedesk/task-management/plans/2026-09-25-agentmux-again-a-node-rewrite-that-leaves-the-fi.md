# agentmux again: a Node rewrite that leaves the field untouched

## Context

The product is called **Controls Control Center** on screen and **agentmux** everywhere
else. `dashboard/server.py:2441` already prints `agentmux dashboard: http://127.0.0.1:...`
while `dashboard/index.html:6` still says `<title>Controls Control Center</title>`. The
rename was started and abandoned; `dashboard/app.js.prerebrand.bak` is the fossil.

What exists today, measured rather than remembered:

| | |
|---|---|
| Backend | `dashboard/server.py`, 2,456 lines, Python stdlib `ThreadingHTTPServer`, 83 handlers |
| Frontend | `app.js` 172 KB + 11 module files, `style.css` 72 KB, one `index.html` 32 KB |
| Build step | None. No `package.json`, no bundler, no framework |
| Views | terminals, status, board, runs, organization, iiot, github, settings |
| Test net | 59 `test_*.py`, 37 `*.sh`, one Playwright `test_e2e.mjs` |
| Field protocols | `enip.py`, `logix.py`, `profinet.py`, `modbus_rtu.py`, `modbus_poll.py`, `ecat_diag.py`, `codesys_panel.py`, `netscan.py`, `mqtt.py`, `ads.py` |
| Bind | `server.py:2434` binds `127.0.0.1` only |
| Host | Windows, i9-14900K, RTX 4090, 64 GB, Node v24.14.0 present. Tailscale not on PATH |

Two facts in that table are load-bearing and shape everything below.

**The loopback bind is not incidental.** `server.py:1822` states the mutation design
works *because* the server binds loopback only. The IIOT view writes Modbus registers,
writes Logix tags and forces CODESYS values. Any remote-access design that weakens the
bind without replacing the auth model puts writes to live equipment on a network.

**The field protocol modules have no replacements.** npm has adequate Modbus and MQTT and
a thin EtherNet/IP package. It has nothing for PROFINET DCP, nothing for EtherCAT
diagnostics, and nothing for the CODESYS integration. `logix.py:1-13` is written against
1756-PM020I and explicitly scopes out the Logix Designer SDK as licensed and .NET-only.
Those files are the expensive, hardware-validated part of this repo.

The ask is a rebrand, a Node rewrite, a right-side blade, YAML-configured modes, an
overhauled IIOT tab with deeper Rockwell support, an investing tab, and remote access.

---

## Decisions taken

Captured from the design interview on 2026-09-25.

| Question | Decision |
|---|---|
| Rebrand scope | Live surfaces only. UI strings, logos, favicon, docs, agent definitions. History untouched |
| UI rewrite | Full rewrite, frontend and backend both Node |
| Frontend stack | React + Vite + TanStack Router. No SSR framework |
| Field protocols | Stay Python. A sidecar process behind the Node API |
| Voice CLI | **Scrapped entirely.** No STT, no TTS, no wake word |
| The blade | Right-side slide-out, text agent console. Configurable and modular from Settings and from within the blade |
| Blade behaviour | Persists across view changes, pins and reflows as well as overlays, responses interruptible, confirmations render as cards inside it |
| Blade authority | Navigate and dictate, run agents and read status, and initiate trades and industrial writes behind a second explicit confirmation |
| Modes | YAML profiles. A mode switches views, MCP servers, agents, theme, layout and session policy |
| Mode set | Investing, Research, PLC. Music production was a typo and is dropped. Extensible by adding a YAML file |
| Research mode | Durable session state, background agents, findings written as artifacts, every claim source-captured |
| Rockwell | Layered. pycomm3 for Logix tag work, `enip.py` retained for device-neutral CIP and the write audit, node-opcua for vendor-neutral reads |
| Charts | TradingView widget, overlaid with broker data |
| Fidelity | Full Playwright browser automation including order placement, with typed confirmation, kill switch and dry-run default |
| Remote access | Tailscale **serve**, tailnet only. Never Funnel |
| Agent coordination | Node **observes**. WSL tmux and `agentmux.sh` remain authoritative and are not modified |
| Host split | Node API and Python sidecar on Windows. Agents stay in WSL |
| Sequencing | Foundation first: rebrand, then backend, then modes and blade, then features |

## Non-goals

Recording these so they are not relitigated mid-build.

- **No voice anything.** Dropped after the stack was specified. If it returns it is a new plan.
- **No music production mode.**
- **No Tailscale Funnel**, no public internet exposure, no port forwarding.
- **No Logix Designer SDK / Studio 5000 automation.** `logix.py:3-4` rules it out and that stands.
- **No porting field protocols to TypeScript.** PROFINET DCP and EtherCAT diagnostics stay Python permanently.
- **No rewriting history.** ADRs, `events.jsonl`, `audit_2026-09-17/`, `.backup-2026-09-18/` and the dated `STATUS_CCC_*.md` files keep the old name. They are a record of what was decided when.
- **No change to how agents actually run.** WSL tmux coordination is not ported, wrapped or replaced.

---

## Architecture

```
Windows host
|
+-- agentmux-web        React 19 + Vite + TanStack Router
|                       dev on :5173, production bundle served by the API
|
+-- agentmux-api        Node 24 + TypeScript              :8787
|     owns    HTTP, session auth, CSRF, SSE fan-out, mode resolution,
|             board / runs / organization / github / settings
|     proxies /api/field/*  ->  field sidecar
|     reads   cc.db and .bytedesk/task-management (read-only for agent state)
|     opcua   node-opcua client for vendor-neutral reads
|
+-- agentmux-field      Python 3 sidecar                   :8788, loopback only
|     owns    modbus_poll, modbus_rtu, profinet, ecat_diag, enip, logix,
|             pycomm3, codesys_panel, netscan, mqtt, ads, probe_slots
|     owns    the Playwright Fidelity session
|     unchanged protocol logic behind a thin HTTP shell
|
+-- cc.db, .bytedesk/task-management/     canonical, unchanged

WSL Ubuntu  -- NOT MODIFIED BY THIS PLAN
+-- tmux panes running codex / claude
+-- agentmux.sh coordination, warrants, claims
```

### Three contracts, stated once

**1. Node to Python.** HTTP and JSON on `127.0.0.1:8788`, shared secret in a header,
sidecar never binds anything but loopback. Every write endpoint keeps the existing
typed-confirmation, non-empty actor and durable JSONL intent record described in
`enip.py:8-9`. The Node API adds no write path that bypasses that.

**2. Node to WSL.** Read-only. The API reads `cc.db` and the task store and renders
them. Dispatch invokes the same entry points the CLI already uses. The API never writes
tmux state, never mints a claim key, never becomes a second scheduler. A startup guard
asserts this: if the API can observe a coordination lock it does not own, it logs and
declines rather than proceeding.

**3. Web to Node.** SSE for anything live, REST for mutations, session cookie plus CSRF
token. This is what replaces the loopback assumption at `server.py:1822`, and it must
land before the bind is widened in Phase 6, not after.

---

## Phase 0 - Rebrand

Deliberately small on the old UI, since Phase 3 replaces it. The point is that the
product does not contradict itself during the months the old UI is still serving.

**Change:**

- `dashboard/index.html:6` title, `:7` favicon href, `:40` comment, `:43` aria-label, `:53` the brand span
- `dashboard/assets/logo-ccc.svg`, `logo-ccc-16.svg`, `logo-ccc-24.svg`, `logo-ccc-wordmark.svg` to `logo-agentmux*.svg`
- `window.CCC_SCRIPT_ERRORS` at `index.html:20,24` and every reader in `app.js`
- `.agentmux/agents/ccc-frontend-dev.md`, `ccc-frontend-reviewer.md`, `ccc-orchestrator.md`
- `dashboard/BRIEF_review_ccc.md`, `dashboard/REVIEW_CCC_FINDINGS.md`
- `README.md`, `docs/`

**Leave alone:** every ADR, `events.jsonl`, `index.json`, `audit_2026-09-17/`,
`.backup-2026-09-18/`, the five dated `STATUS_CCC_*.md` files at repo root.

**Open sub-decision.** `ccstore.py`, `ccboard.py` and the `cc.db` filename are referenced
by 35 files, and ADR-0001 names `cc.db` as the canonical store by that name. These are
internal identifiers, not live surfaces. Recommendation: leave them, and add one line to
the ADR index noting CCC was the former product name. Renaming the database file means a
migration for no user-visible gain.

**Housekeeping while here.** Repo root contains two directories literally named
`C:UsersNickAppDataLocalTemptmp57mb63qvbackups` and
`C:UsersNickAppDataLocalTemptmpzmeefxalbackups` - a script that lost its path separators.
Inspect and delete.

**Acceptance.** `grep -ril "control.center\|\bCCC\b" dashboard/ docs/ README.md .agentmux/`
returns nothing. All 37 shell frontend tests still pass. Favicon renders in a fresh profile.

---

## Phase 1 - Node backend and Python sidecar

The riskiest phase, because 83 handlers have to move without anyone noticing.

**1.1 Extract the field library.** Add `field/app.py`, a thin HTTP shell that imports the
existing protocol modules unchanged. `server.py` keeps importing them directly. Two
consumers, one library, zero change to protocol logic. This is the step that makes the
sidecar real without touching anything that talks to hardware.

**1.2 Scaffold the API.** Node 24, TypeScript, Fastify, Zod request and response schemas,
SSE via a shared broker. Bind `127.0.0.1:8788` for now.

**1.3 Port handlers with a differ.** For each of the 83 handlers, write a contract test
that issues the same request to `server.py` and to the Node API and diffs the JSON. That
harness is what replaces the 59 Python tests during migration - it is the single most
important artifact of this phase and should be built before the second handler is ported.

**1.4 Auth.** Session cookie, CSRF token, per-request actor. Industrial writes keep their
own typed confirmation on top; the session is not sufficient authority to move equipment.

**Acceptance.** Every ported route is byte-identical to `server.py` under the differ for a
recorded corpus of requests. `server.py` still boots and still passes its own suite. The
sidecar answers a Modbus read with the same payload the monolith does.

---

## Phase 2 - Modes and the blade shell

**Mode profiles.** `modes/*.yaml`, one file per mode, hot-reloaded.

```yaml
id: plc
title: PLC
theme: agentmux-dark
views:   [terminals, iiot, board, runs, organization, settings]
default_view: iiot
mcp:     [codesys_rt, modbus, drawio]
agents:  [plc-dev, plc-test-engineer, senior-reviewer]
skills:  [codesys-mcp, codesys-oop, paste-guide, hmi-test]
blade:
  default_state: pinned
  panels: [conversation, runs, confirmations]
session:
  durable: false
```

`investing.yaml` swaps in the investing view, the market data and Fidelity MCPs, and a
research-oriented agent set. `research.yaml` sets `session.durable: true` and enables
background agents plus the artifact writer. A fourth mode later is one file, no code.

**The blade.** Right-side, three states: hidden, overlay, pinned. Pinned reflows the main
content rather than covering it, which matters for terminals and charts. Conversation
state survives view changes. Streaming responses are interruptible. Trade tickets and PLC
write confirmations render as cards inside the blade with press-to-commit, never as
browser dialogs.

**Configurable and modular** per the decision: the panel list comes from the mode YAML,
is overridable in Settings, and is rearrangeable from a control inside the blade itself.
Per-user overrides persist server-side so the layout follows you across devices on the
tailnet.

**Acceptance.** Switching modes changes the left rail, the loaded MCP set and the agent
roster with no reload. A new mode YAML appears in the switcher without a code change.
Blade state survives navigation and a page refresh.

---

## Phase 3 - View migration

Order chosen so each view teaches the next, cheapest first:

1. **Settings** - smallest surface, proves forms, validation and persistence
2. **Organization** - agents and teams, proves list and detail patterns
3. **Board** and **Kanban** - proves drag, optimistic update and SSE reconciliation
4. **Runs** - proves the live-streaming pattern end to end
5. **Status** - feed, queue, journal, chatter; four subtabs of mostly-solved patterns
6. **GitHub** - external API, caching, auth surface
7. **Terminals** - xterm.js, the hardest, and the one most likely to need WSL care
8. **IIOT** - deliberately last, because Phase 4 rewrites it anyway

`server.py` is deleted only when the last view is migrated and the differ has been green
for a full week of real use.

---

## Phase 4 - IIOT and Rockwell

Three libraries, each doing the job it is actually best at.

**pycomm3, in the field sidecar.** Delivers exactly what `logix.py:9-13` documents as
missing: tag browsing, UDT template discovery, member layout decoding, structure read and
write without the caller guessing a layout.

**`enip.py`, retained.** Device-neutral CIP for non-Logix equipment, and the durable
JSONL intent log that every write funnels through. Keeping this is what stops pycomm3
from introducing an unaudited write path.

**node-opcua, in the API.** One vendor-neutral read client across CODESYS and Rockwell
together, which is what makes a single live tag table across mixed gear possible.

**UI.** Device tree from the segment scanner, live tag table with explicit value age on
every row - `iiot.js:11-13` is right that an unaged number is the most dangerous thing
this panel can show, and the rewrite must not lose that. Writes go through a ticket with
typed confirmation, and the ticket renders in the blade.

**Acceptance.** Browse a live Logix controller's tags without a hand-supplied instance ID.
Read a UDT member by name. Every write in a session appears in the JSONL audit with actor
and timestamp. A stale value is visibly stale.

---

## Phase 5 - Investing

**Charts.** TradingView Advanced Chart widget, with positions and signals overlaid. Trade
view and chart view as a split the user controls.

**Fidelity session.** Playwright in the field sidecar. Chromium is already vendored at
`tmp/TM-039-browser/`. A session manager handles login and 2FA and keeps the session warm.
Scrapes balances, positions, order history.

**Order pipeline.** Ticket built from research, then `dry-run` by default which renders
the exact order without submitting, then typed confirmation, then submit, then read-back
verification, then a durable JSONL audit record. A kill switch file disables submission
entirely and is **enabled by default** on first install.

**Credentials.** Windows DPAPI or the OS keyring. Never a file in the repo, never an
environment variable in a script.

**Stated plainly, once.** Automating Fidelity's web UI is against their terms of service,
breaks whenever they change the UI, and a defect here spends real money. The decision to
do it anyway is recorded above and is yours. The dry-run default, the kill switch and the
typed confirmation are the mitigations; they are not optional parts of this phase.

**Acceptance.** Positions match the Fidelity UI. A dry-run order renders the correct
ticket and submits nothing. With the kill switch on, no code path can submit. Every
submitted order has an audit record and a read-back confirmation.

---

## Phase 6 - Remote access

- Install Tailscale on the Windows host
- `tailscale serve` only. The API binds loopback plus the tailnet interface, nothing else
- Session auth is required on the tailnet exactly as it is on loopback. Tailnet membership is not authorization
- A startup guard refuses to boot if `tailscale funnel status` reports an active funnel on the API port
- The Python sidecar stays loopback-only and is never exposed, even on the tailnet

**Acceptance.** The dashboard is reachable from your phone on the tailnet and from nowhere
else. `curl` from an off-tailnet host cannot reach it. The funnel guard trips in a test.

---

## Risks

| Risk | Mitigation |
|---|---|
| 83 handlers ported by hand, silent behaviour drift | The Phase 1.3 differ, built before the second handler moves |
| The 37 shell frontend tests die with the old UI | Port them to Playwright against the React app as each view migrates, not at the end |
| Field regressions from the sidecar extraction | Phase 1.1 changes no protocol logic. `server.py` keeps importing the same modules and its suite keeps passing |
| Node becomes a second agent scheduler by accident | Contract 2 plus the startup guard. Any change adding a write path to WSL state is out of scope by definition |
| pycomm3 opens an unaudited write path | All writes route through the existing `enip.py` intent log regardless of which library performs them |
| Fidelity UI change breaks orders silently | Read-back verification after every submit; dry-run default; alert on selector failure rather than retry |
| A voice-free blade still triggers a live trade or PLC write | Typed confirmation on every one, rendered as a card, with the kill switch above it |
| Tailnet widening lands before the auth rewrite | Phase 6 depends on Phase 1.4. Sequencing is the control |

## Open questions

Not blocking Phase 0 or 1, needed before Phase 5.

1. Which market-data provider backs the non-TradingView data - fundamentals, options chains, news?
2. Does the investing mode need tax-lot and cost-basis tracking, or is Fidelity's own view sufficient?
3. For research mode, where do artifacts land - `.bytedesk/task-management/research/` as the existing skill does, or a new tree?
4. Does `cc.db` get renamed, per the Phase 0 open sub-decision?
