# agentmux: the Node rewrite, planned against what is actually on disk

## Context

The product is called **Controls Control Center** on screen and **agentmux** everywhere
else. `dashboard/server.py:2441` prints `agentmux dashboard: http://127.0.0.1:...` while
`dashboard/index.html:6` still reads `<title>Controls Control Center</title>`. A rename
was started and abandoned.

The repo is five days old and has moved fast — 79 commits, ~24 a day — through three
arcs: capability (protocol clients, seven views), orchestration (cross-model agent runs),
and most recently reliability (`6afd65b`, the dashboard-takeover marker). The trajectory
has turned from "add capability" to "stop it lying to me". This plan is the decision to
rebuild on that footing rather than keep extending a 2,456-line stdlib monolith.

The ask: a rebrand, a Node rewrite, a right-side agent blade, YAML-configured modes, an
overhauled IIOT tab with deeper Rockwell support, an investing tab, and remote access.

An earlier draft exists at
`.bytedesk/task-management/plans/2026-09-25-agentmux-again-a-node-rewrite-that-leaves-the-fi.md`.
**This supersedes it.** Several of its measured facts were wrong and three of its
architectural decisions have been reversed — recorded below rather than silently
corrected, because those numbers were used to size the work.

---

## 1. What changed since the draft

### 1.1 Three decisions reversed

| Was | Now | Why |
|---|---|---|
| Node API + Python sidecar both on **Windows** (ADR-0021 D3) | **API in WSL, field sidecar on Windows** | `cc.db` is at `/home/nick/.agentmux/cc.db` on ext4; `restart.sh:2` launches the server *inside WSL*; `server.py:907` shells `tmux -L agentmux` as a **local binary** — a Windows API would need `wsl.exe` interop for every one of those calls; and `taskmgmt/coordination.py:51` POSTs to `127.0.0.1:8787` from WSL, which only reaches a WSL-side listener under NAT. Meanwhile **no field module uses raw sockets**; only serial Modbus RTU and plant-NIC proximity want Windows, and `modbus_rtu.py:97-98` says so itself. |
| `cc.db` canonical; migrating the board to `.bytedesk` explicitly rejected (ADR-0001) | **`.bytedesk/task-management/` canonical for board entities; `cc.db` keeps runs, claims, journal, auth, devices, terminals, roster, chatter** | ADR-0001's objection was that CCC concepts have no schema upstream. The split answers it: only epics, tasks, acceptance, evidence and ADRs move. The no-pip rule that forced `ccboard.py` to reimplement the plugin dies with `server.py` anyway. |
| "Node observes" (ADR-0022 D2), blade runtime unspecified | **The API embeds the Claude Agent SDK** with its own MCP clients and key, **and may dispatch orchestrator jobs** — through the same `agentmux.sh` / `taskmgmt` entry points an operator types, never by writing coordination state | There is no agent runtime in this repo. The agents are `codex`/`claude` CLIs in tmux panes and MCP servers are per-CLI, so `mcp: [codesys_rt, modbus, drawio]` in a mode file means nothing without a runtime. ADR-0022 D2 is **refined, not reversed**: WSL still owns execution. |

Today's interview was auto-captured as
`.bytedesk/task-management/adrs/ADR-0023-host-split-use-api-in-wsl-field-on-windows.md`.
It carries all three reversals, is filed under the wrong epic, restates each *question*
rather than the decision, and **supersedes ADR-0001 and ADR-0021 D3 without saying so.**

### 1.2 Baseline facts the draft got wrong

| Draft said | Actually | Effect |
|---|---|---|
| 59 `test_*.py` | **39** (31 `dashboard/`, 7 `orchtest/`, 1 `nettraffic/`) | — |
| 37 shell tests | **24** strict `test_*.sh`. 37 was every `.sh` in `dashboard/` | — |
| "37 shell frontend tests" as the gate | **9** (`test_frontend*.sh`) | Over-stated 4x; the replacement is tractable |
| Rebrand touches 35 files | **62 real source files** | Phase 0 is ~2x the draft |
| — | **18 of those are tests that assert the brand string** | Source + assertions must land in one commit |
| — | **5 are binary PNGs** in `docs/images/` | Re-captured, not edited |
| Swap `logo-ccc*.svg` | **The mark is inline SVG at `index.html:42-52`**; the assets are favicon-only | Swapping files changes nothing visible |
| `CCC_SCRIPT_ERRORS` is the runtime contract | **It is the smallest of four**, plus **12 `ccc.*` localStorage keys** | A naive rename **silently wipes every operator's themes, board layout and view state** |
| 38 `/api/board/<op>` ops retire | **40 ops** (`BOARD_READS` 15 + `BOARD_WRITES` 25 at `server.py:1223-1230`); **28 retire, 12 move** — agents/roster/codesys/chatter read cc.db tables that stay | Phase 1 shrinks less than hoped |
| 43 route literals | **45** — `/api/modbus/tags` and `/api/modbus/write` are single-quoted at `:2270` | — |
| 10 field protocol modules | **11** — the draft missed `mqtt_monitor.py` (**517 lines**, largest) | It carries the only non-stdlib dependency |
| — | **Paho is vendored, not pip'd** (`vendor/README.md`, sha256-pinned; `mqtt_monitor.py:58-71`) | The no-pip rule is honoured by vendoring. The one real pip dep is **pyserial** (`modbus_rtu.py:86-88`, lazy) |
| `netscan.py` has no test | **It is covered** by `test_field_panels.py:392-455` (guards, sweep, OUI, `under_wsl`). The module with **no dedicated test is `mqtt_monitor.py`** | Retarget the test task |
| Node v24.14.0 present | That is **Windows**. WSL has **nvm's v24.21.0 installed but unreachable** — `command -v node` is `none` in both login and non-interactive shells | Phase 1.0 is *activate and pin*, not install |
| Junk dirs need inspecting | Both **completely empty** | Zero-risk `rmdir` |
| `server.py` is the server | **`taskmgmt/bedrock_gateway.py`** is a second in-repo HTTP server (port 4000, tested at `run_tests.sh:273`) | Out of scope, but the premise was false |
| `server.py:1822` justifies the design on loopback | True but **scoped to the MQTT endpoint**. The real doc is **`allowed_origins()` at `:1099-1113`** | Phases 1.4 and 6 are written against the latter |
| `logix.py` names missing "tag browsing" | It does not. The gaps are **instance-ID sourcing** (`:6-7`) and template/member decoding (`:10-11`) | Phase 4's AC must name the real gap |
| `iiot.js:11-13` | Runs to **`:14`**; quoting 11-13 truncates mid-clause | — |
| `tmp/TM-039-browser/` is a Phase 5 asset | **Untracked, gitignored, 676 MB of Linux Chromium.** Never in git history | A disk item, not a repo item — and useless once the broker is on Windows |
| — | **`app.js.prerebrand.bak` is 39 KB vs today's 172 KB** | Not a rollback path |

### 1.3 Findings the draft never had

These change the design, not just the sizing.

1. **The repo is PUBLIC.** `gh repo view` → `controlLogix/CControlCenter`, `isPrivate: false`, and `.bytedesk/task-management/` is committed. **No investing artifact may ever land in the tree.** The draft's open question 3 proposed exactly that.
2. **Every MCP server on this machine is a Windows process** (`~/.claude.json`: `modbus` is `npx modbus-mcp`, `word` is an `.exe`, `codesys_rt` must sit beside the IDE). The API is in WSL. `mcp:` in a mode file **cannot** resolve to a WSL stdio spawn — a Linux `modbus-mcp` sees different NICs and no COM ports, and there is no Linux `codesys_rt`. This is the largest gap in the blade spec.
3. **`agentmux.sh` grants orchestrator authority by omission.** `${AGENTMUX_AGENT:-orchestrator}` at `:1194,1320,1329,1356,1465,1516,1541,1552`, and `cmd_dispatch|collect|pool` (`:1296,1301,1306`) refuse when it *is* set. **A Node process shelling `agentmux.sh` with an inherited environment IS the orchestrator**, with `run complete --force` and `claim --for <agent>` live.
4. **The plugin store breaks live locks across the WSL/Windows boundary.** `store.mjs staleLock()` decides liveness with `process.kill(pid, 0)`; a WSL Node reading a lock written by a Windows Node gets `ESRCH` and breaks it. The plugin's own comment records the cost: *"8 concurrent creates produced 8 files with 7 distinct ids."*
5. **Renaming the GitHub repo would brick the task store**, and pinning `boardId` does **not** prevent it. `store.mjs write()` refuses any doc whose `board` ≠ the store identity, and `boardIdentity()` at `:753-757` returns **git first** — `gitBoardId()` reads `git remote get-url origin`, lowercases `owner/repo`, and the config `boardId` is consulted only when git yields nothing. So a rename changes the identity regardless of the pin. What the pin buys is **detection**: with `stored` set, a mismatch is reported as `drifted: true` instead of surfacing as an unexplained refusal. The actual mitigations are (a) don't rename the GitHub repo — the rebrand is scoped to live surfaces and does not require it, or (b) if it is renamed, rewrite `board:` in every doc in the same change.
6. **`/mnt/c` is 9p — inotify never fires.** `fs.watch` on `modes/`, `events.jsonl` or the repo silently does nothing. `$AGENTMUX_HOME` is ext4, where it works. The two halves need different watch strategies.
7. **`~/.agentmux/env` is sourced into every agent pane** (`agentmux.sh:669`). The blade's API key must not go there — that hands it to every worker.
8. **There were three write journals, not two** — and this plan said two. `enip.py:213`, `logix.py:99` and **`ads.py:85`**, which kept `~/.agentmux/ads-writes.jsonl` with the same shape and the same guarantees and which nothing outside that module pointed at. That is exactly the failure a shared journal exists to prevent: a survey careful enough to be written into a plan still missed one of three. **Done** — see TM-026. None of the three files had ever existed, so no live industrial write has been performed from this repo.
9. **`events.jsonl` is mostly hook telemetry** — 226 `subagent_stop`, 115 `notification`, 51 `git_link_unattributed` versus 24 `create` / 4 `update`. A naive event-sourced board projection over it is a trap.
10. **There are two spec files**, neither mentioned by the draft: `dashboard/SPEC.md` (endpoints, port, the 403 rule) and `dashboard/SPEC_CC.md` (product, brand, constraints).

### 1.4 Bookkeeping to fix alongside

- **All 23 ADRs are `status: proposed` with an empty `## Consequences`.** ADR-0021 D2 reverses ADR-0017 D3 (voice) with no link; ADR-0023 supersedes ADR-0001 and ADR-0021 D3 with no link.
- **`EP-001` means two different things** — `cc.db`: "Controls Control Center rebrand"; `.bytedesk`: "Configurable agents, teams…", which `cc.db` records separately as `EP-015`, done. **`ADR-0001` collides too.**
- **`EP-001`'s `plan:` field is one pointer rotating between four plans.** The rewrite has no epic.
- The companion plan `2026-09-25-a-dashboard-takeover-that-repairs-itself.md` **is already shipped** at `6afd65b`. It composes: its three files are off-limits here, and its hardened gate is what every phase takes acceptance from.

---

## 2. Non-goals

- **No voice anything** (ADR-0021 D2). If it returns it is a new plan.
- **No music production mode** — a typo; PLC replaced it.
- **No Tailscale Funnel**, no public exposure, no port forwarding.
- **No Logix Designer SDK / Studio 5000 automation.** `logix.py:3-4` rules it out.
- **No porting field protocols to TypeScript.** They stay Python permanently.
- **No rewriting history.** ADRs, `events.jsonl`, `audit_2026-09-17/`, `.backup-2026-09-18/`, the five `STATUS_CCC_*.md` keep the old name.
- **No change to how agents run.** `agentmux.sh`, `run_tests.sh`, `suite_server.py` are not modified.
- **No rewrite of `taskmgmt/bedrock_gateway.py`.**
- **No independent tax-lot or cost-basis engine.** Fidelity is books-and-records.

---

## 3. Architecture

```
WSL Ubuntu  (where cc.db and tmux already live)
|
+-- agentmux-api      Node 24 + TypeScript + Fastify + Zod        :8787
|     owns    HTTP, session auth, CSRF, one multiplexed SSE bus,
|             mode resolution, runs / organization / github /
|             settings / terminals / status
|     hosts   the blade's agent loop (Claude Agent SDK + MCP clients)
|     reads   cc.db (runs, claims, journal, auth, devices, roster, chatter)
|     reads   .bytedesk/task-management/  (board projection, in-process)
|     opcua   node-opcua, read-only by construction
|     serves  the agentmux-web production bundle
|     proxies /api/field/*  -> field sidecar        (Windows)
|     proxies /api/broker/* -> broker               (Windows)
|     proxies /mcp/<name>   -> MCP bridge           (Windows)
|
+-- agentmux-web      React 19 + Vite + TanStack Router (dev on Windows, :5173)
+-- tailscaled        userspace mode + `tailscale serve`   (Phase 6)
+-- tmux -L agentmux  codex / claude panes           NOT MODIFIED
+-- agentmux.sh       coordination, warrants, claims  NOT MODIFIED
+-- cc.db             /home/nick/.agentmux/cc.db, ext4, WAL

        |  HTTP + JSON + per-service shared secret, 127.0.0.1 (mirrored mode)
        v

Windows host
|
+-- agentmux-field    Python 3.12    :8788   loopback only
|     enip, logix, pycomm3, profinet, ecat_diag, ads, modbus_poll,
|     modbus_rtu (COM), mqtt, mqtt_monitor, codesys_client, netscan
|     + mcp_bridge: launches the Windows MCP servers, exposes them
|       as MCP Streamable HTTP at /mcp/<name>
|     + secrets: DPAPI / Credential Manager
|
+-- agentmux-board    Node   :8790   loopback only
|     the ONLY writer to .bytedesk/task-management/ (lock-safety, §1.3.4)
|     mounts the plugin's own transport-free router
|
+-- agentmux-broker   Python + Playwright   :8789   loopback only
      the Fidelity session. Separate process by design (Phase 5)
```

### 3.1 Prerequisite A — Node in WSL

Measured: `/home/nick/.nvm/versions/node/v24.21.0` **exists**, but `command -v node`
returns **none** in both login and non-interactive shells — nvm is installed and never
sourced. The only `npm` reachable is `/mnt/c/Program Files/nodejs/npm`, the Windows one
through interop, which would build native modules for the wrong platform.

**Phase 1.0:** pin `AGENTMUX_NODE` to an absolute nvm path, repeating the discovery
`dashboard/test_e2e.sh:24-30` already does, and add a `prestart` guard that refuses to
run when `node` resolves under `/mnt/c`. A day of confusion turned into one clear line.

### 3.2 Prerequisite B — mirrored networking

No `.wslconfig` exists, so WSL2 is in NAT mode. Windows→WSL works (verified: the
dashboard answers HTTP 200 from a Windows curl). **WSL→Windows does not work on
`127.0.0.1`** — it needs the host gateway (`172.30.112.1` today), which changes on every
restart. So "the sidecar binds loopback only" and "the API is in WSL" cannot both hold.

**Decided:** enable mirrored networking.

```ini
# %USERPROFILE%\.wslconfig
[wsl2]
networkingMode=mirrored
```

Supported here (WSL 2.3.26.0 ≥ 2.0.0, Windows 10.0.26200 ≥ 22H2). After it, `127.0.0.1`
means the same on both sides, all three Windows services stay genuinely loopback-bound,
and `netscan.py`'s documented WSL degradation is repaired — `netscan.py:186-201` names
mirrored mode as the case where the Linux path is correct.

Costs, to verify in a timeboxed spike before committing: it is a **global** networking
change, brings WSL traffic under Windows Firewall, and has historically disturbed VPN
split-tunnel and Docker Desktop — and `docker-desktop` is an installed distro here.
Rollback is deleting the file and `wsl --shutdown`.

**Fallback if rejected:** the services bind the `vEthernet (WSL)` address with a firewall
rule scoped to the WSL subnet, and the API re-resolves the gateway on every connection
failure. If that path is taken, **stop calling it loopback-only in the docs** — say
"loopback plus the WSL adapter", or someone will later rely on a property the system
does not have.

### 3.2a What 9p does and does not do — measured, not assumed

An earlier draft of this plan justified the host split partly on "SQLite over the 9p
boundary is a corruption hazard". **That claim is not supported by measurement and has
been removed.** Tested 2026-09-25, four concurrent writers × 300 committed inserts each,
WAL + `foreign_keys=ON` + `timeout=5` — the settings `ccstore.connection()` uses:

| Scenario | Result |
|---|---|
| 4 WSL processes, database on **ext4** | 1200/1200 rows, 0 busy/locked, `integrity_check: ok` |
| 4 WSL processes, database on **`/mnt/c` (9p)** | 1200/1200 rows, 0 busy/locked, `integrity_check: ok`, same wall-clock |
| **2 Windows + 2 WSL processes, same file on 9p** | **1200/1200 rows, all four writers present, `integrity_check: ok`** |

So cross-OS concurrent SQLite writing did not lose a row or corrupt anything here. The
host split still stands — on `tmux` locality, the inbound `coordination.py` POST path,
and COM ports for the field half — **none of which depend on the SQLite claim.** Phase
1.2's guidance is unchanged and now has evidence behind it: WAL plus `busy_timeout`
genuinely does absorb the overlap.

Stated honestly, because one probe is not a proof: this covers short transactions on a
small database with no crash injection. It does **not** clear long transactions, WAL
checkpoint contention, or a process killed mid-write. And it is a different thing from
the 9p failure this repo *has* measured — **transient EIO under gate load**, which is
real, is why the gate runs from an ext4 clone, and is what `netscan.py` was killed by.

### 3.3 The task store sits across the mount

`.bytedesk/task-management/` is canonical but lives on 9p at `/mnt/c/Dev/agentmux/…`,
while the API is in WSL. Three consequences:

- **`bin/tm` is a Node shim** and fails in WSL with exit 127 today (same missing-Node
  cause). Even with Node pinned, it resolves its plugin root from `homedir()`.
- **inotify does not fire on 9p**, so `events.jsonl` cannot be watched from WSL.
- **`store.mjs` will break live locks across the boundary** (§1.3.4).

**So:** the API **reads** the store directly and in-process — the files are plain
markdown, `index.json` and append-only `events.jsonl`, reads are lock-free, and a
subprocess per board read is the wrong shape for a server. Liveness is a **500 ms `stat`
+ read-from-offset poll**, reusing `stream_all`'s existing offset + `(st_dev, st_ino)`
identity pattern with reset on rotation or truncation. **All writes** go through
`agentmux-board` on Windows, which mounts the plugin's own transport-free router
(`dashboard-api.mjs handleWrite`) — so the 28 retiring handlers are *mounted, not
reimplemented*. That is the highest-leverage decision in Phase 1.

### 3.4 Dependency policy: vendoring, not pip

`SPEC_CC.md:16` says stdlib-only, no pip. The repo honours it by **vendoring** — paho is
in `dashboard/vendor/`, sha256-pinned, with `vendor/README.md` recording why: *"plant-side
boxes where `sudo apt install` is somebody else's change request and outbound PyPI is
often blocked."* Nine of eleven protocol modules are genuinely stdlib-only.

The rule being protected is not "stdlib only", it is **"the sidecar installs from a
clone, with no network and no pip."** That property survives. Replace §16 with
**ADR-0024, "Sidecar dependency policy: vendored wheels, pinned by hash"**: pure-Python
`py3-none-any` wheels only, extracted under `field/vendor/`, URL + sha256 + version +
licence recorded, a `check_vendor.sh` asserting hashes and the absence of any
`.so`/`.pyd`/`.dll`, and a **falsifiable** test that each package imports with
`site-packages` stripped from `sys.path` — otherwise the vendoring is decorative.
pycomm3 qualifies; verify zero transitive deps as an AC. pyserial stays the one genuine
pip dependency, in the sidecar's venv, already degrading gracefully.

**The Node half is governed differently, and say so**: `npm ci` against a committed
lockfile, `--omit=dev` in production, `npm audit` in CI. The no-network constraint was a
property of the plant-side Python box; the API runs in WSL next to a package manager.

### 3.5 `SPEC_CC.md`: which standing constraints survive

`SPEC_CC.md:14-24` lists six as "all still binding". Two change, four must not.

| Constraint | Disposition |
|---|---|
| `:16` stdlib only, no pip | **Narrowed** → ADR-0024 (§3.4) |
| `:17` Bind 127.0.0.1 only | **Changed in Phase 6 only, and gated.** With `tailscale serve` the API in fact **keeps** binding loopback; Tailscale owns the only tailnet listener |
| `:19` No secret entered through the browser | **Survives.** Drives the blade key store (§5.6) and the Fidelity 2FA design (§7.2) |
| `:20` Terminals read-only, never send keystrokes | **Survives.** The tmux argv allowlist excludes `send-keys`; `agentmux send` is a separate, confirmed orchestrator verb |
| `:21-23` Resize guards on every mutating endpoint | **Survives, and gets cheaper** — Fastify + Zod give it by construction. One shared route wrapper so no handler can opt out |
| `:24` Nothing interpolated as HTML | **Survives.** React escapes by default; ban `dangerouslySetInnerHTML` by lint, not discipline |

**Brand continuity.** `SPEC_CC.md:26-33` specifies the look — Valve-era Steam, flat dark
slate, tight 1px borders, dense information, no gradients, **thin light orange accent used
sparingly, never a fill**. The draft treated the rewrite as visually greenfield. It is
not: `style.css` is 72 KB of that identity and should be **ported to design tokens in
Phase 3, not redesigned**. The rebrand changes the name, not the look.

**New: `docs/SPEC_WEB.md`** replaces the frontend half. Ten rules, each with its evidence —
the two load-bearing ones being **exactly one SSE connection per tab**, multiplexed by
topic (forced by the measured 6-connection cap at `server.py:1974-1992`), and **server
time, never client time, for anything that reads as freshness**.

---

## 4. Contracts

**1. API → Windows services.** HTTP + JSON on `127.0.0.1`, a **distinct shared secret per
service** (compromise of one must not grant another), each service bound to loopback and
nothing else, asserted by a boot test that enumerates listening sockets.

Every field write preserves the `enip.py:8-11` posture verbatim: `confirm=True`, a
**nonempty actor**, a durable JSONL intent **fsync'd before transmission**, then
`success|rejected|unknown` — and **an unknown outcome is investigated, never automatically
retried**. This is enforced in code, not documented: `enip.py:240-243` raises before
anything reaches the wire.

Two consequences the draft missed:
- **Three journals existed** (`enip.py:213`, `logix.py:99`, `ads.py:85` — this plan
  said two) and **none of the files existed on disk** — no live industrial write has
  ever happened. **Done (TM-026):** `dashboard/writejournal.py` unifies them into
  `field-writes.jsonl` with a `transport` field, `intent()` fsync'd before
  transmission, one `classify()` for the rejected/unknown/partial decision, and a
  census test that fails when a client that writes to equipment does not journal
  through it. **Modbus joined too (TM-026 AC 6)** — and answering that question turned
  up a defect: a Modbus device exception response is the device *refusing*, and it was
  being recorded as `unknown`, which sends somebody out to the panel for nothing and
  dilutes `unknown` until the real ones stop getting attention.
- **The journal follows the sidecar to Windows.** Keep it there: the record must be
  durable at the instant of the write, and routing that one append across 9p puts the
  audit trail on the least reliable path in the system. The API drains
  `GET /field/journal?since=<seq>` on a timer and mirrors into `cc.db` for display;
  `/health` reports `journal_lag`.

**2. API ↔ WSL coordination.** Asymmetric, and the draft named only half.

- *Outbound:* read-only for state. The API **may dispatch**, but only by invoking the
  entry points an operator types, through **one chokepoint** (§5.5).
- *Inbound — this already exists and must keep working.* `taskmgmt/coordination.py:51`
  POSTs to `http://127.0.0.1:8787`. Node must take 8787 so the default never changes, and
  **`POST /api/journal` must accept a request with no `Origin` header** (`server.py:1128`
  passes an absent Origin) or every `agentmux claim` breaks. After auth lands,
  `coordination.py` reads `$AGENTMUX_HOME/api-token` and sends a bearer — ~10 lines, one
  change site shared with `run.py` and `dispatch.py`.
- *The startup guard.* The draft's version — "if the API can observe a coordination lock
  it does not own, it logs and declines" — is **wrong on three counts**: claims are
  observable *by design* (`agentmux claims --json` exists for it); the API must never
  *own* a claim, so "a lock it does not own" is every lock that exists; and it samples
  once at boot a value that changes continuously. It trips on the first dispatch and is
  silent when it matters. Replaced by G1–G5 (§5.5).

**3. Web → API.** SSE for anything live on **one multiplexed connection per tab**, REST
for mutations, session cookie plus CSRF. Be clear what this is: the codebase says in
three places — `boardteams.py:141`, `server.py:1380`, and two earlier plans — **"Port 8787
is unauthenticated; the Origin allowlist only stops a browser."**

**Verified against the live dashboard, 2026-09-25**, rather than taken from the comment:

```
GET  /api/agents        no auth, no origin           -> 200
GET  /api/board/board   no auth, no origin           -> 200
POST /api/board/create  Origin: https://evil.example -> 403   (the guard works...)
POST /api/board/create  no Origin header at all      -> 400 {"error": "missing kind"}
```

That last line is the point. With **no `Origin` header** a mutating request passes the
guard completely and reaches payload validation — it failed on the body, not on
authorization. Any local process can write to the board with no credential at all.

That is acceptable *only* because the bind is loopback. Phase 1.4 is not hardening an
auth model; it is the first one, and Phase 6 must not widen the bind until it lands.

**4. Blade → everything.** Two keys, and neither alone moves anything. **`PreToolUse` is
enforcement; `canUseTool` is the UI.** The SDK documents that an allow rule or a
permissive mode *skips `canUseTool` entirely*, so the safety property must not rest on
it. The hook denies any dangerous call not carrying a one-shot commit token bound to
`(sessionId, toolUseId, paramsHash)`; the card mints nothing itself.

### Two facts that make the strangler cheap

- **`server.py --port` already exists** — `:2422` says why: "so a test can bring up a REAL
  server without taking 8787".
- **The origin check is already port-derived.** `:1102-1105` records that the literal
  appeared in two places and was replaced by the server's own bound port.

So Phase 1.3 is: **Node takes 8787**, `server.py` runs on `--port 8788`, Node
reverse-proxies un-ported routes. One URL, the old UI keeps working, and **the proxy is
the corpus recorder** — every request the browser, the e2e suite and `coordination.py`
already make flows through it, so the differ corpus writes itself.

**The one detail that will cost a day if missed:** a proxied POST arrives at `server.py`
carrying `Origin: http://127.0.0.1:8787` while it is bound to 8788, and `read_cc_body`
403s it. **The proxy must strip `Origin` on forward** (safe — Node has already run the
origin and CSRF checks; `server.py` treats absent as same-origin). Add
`X-Forwarded-Origin` for the record.

One interaction to respect: **`run_tests.sh:17-21` leases 8787 for a suite run.** Reuse
`suite_server.py`'s takeover mechanism rather than inventing a second one.

---

## 5. Phases

### Phase 0 — Rebrand

Deliberately small on the old UI, since Phase 3 replaces it. The point is that the
product stops contradicting itself meanwhile. **Rule: a rename and its assertions land in
one commit, always.**

| # | Task | Acceptance |
|---|---|---|
| **0.0** | **Pin `boardId`** in `.bytedesk/task-management/config.json` → `"controllogix/ccontrolcenter"`, and **decide the repo-rename question** | `boardIdentity().stored` non-null; an existing epic still writes. Note the pin makes a rename **detectable** (`drifted: true`), not survivable — git wins at `:753-757`. So either record that the GitHub repo is *not* renamed, or plan the `board:` rewrite across every doc as part of that rename (§1.3.5) |
| 0.1 | Hygiene: `rmdir` the two empty junk dirs; `git rm` `app.js.prerebrand.bak` and two other `.bak`s; gitignore and delete `tmp/` (681 MB, untracked Linux Chromium) | `du -sh tmp` < 10 MB; gate green |
| 0.2a | `window.CCC` → `window.AGENTMUX`, `ccc:ready` → `agentmux:ready`, `window.CCCOpenCard` — 11 source + 6 test files, one commit | gate + e2e green. A miss here means **every view module fails to register and panels render blank** |
| 0.2b | `CCC_SCRIPT_ERRORS` → `AGENTMUX_SCRIPT_ERRORS` — `index.html:20,24`, `app.js:3883-3884`, `test_frontend_tabs.sh:555,561` | The load-failure banner still fires on a deliberately broken script. `:555` asserts listener-before-scripts ordering — keep it |
| 0.2c | **12 `ccc.*` localStorage keys → `agentmux.*` with a read-through migration** | A browser with pre-existing keys **keeps its theme, board layout and collapse state** after reload. Theme *values* `cc-dark`/`cc-light` are **not** renamed — renaming them resets themes even after the key migration |
| 0.2d | CSS keyframes `ccc-live-pulse`, `ccc-arrive` | gate green |
| 0.3 | Three `git mv` of `.agentmux/agents/ccc-*.md` **plus `agentmux.sh:2241 ORCH_DEFAULT_AGENT`** (and `:2230,:2352`), one commit | The orchestrator resolves its definition. Renaming the files alone **breaks orchestration silently** |
| 0.4 | The visible brand: `index.html:6,7,40,42-52,43,53` (two tokens on `:53`), asset renames, `style.css:2`, **`server.py:1209,1336` user-visible error strings**, docstrings, `/tmp/ccc-server.log` → `agentmux` (with `test_residue.sh:204`) | Visual check + gate. `:38-41` is a load-bearing comment explaining why `currentColor` forbids `<img src>` — rewrite it, don't delete it |
| 0.5 | **Re-capture the 5 PNGs.** Create `dashboard/capture_docs.{mjs,sh}` reusing `test_e2e.sh`'s `find_playwright()`; seed a throwaway home so shots aren't of an empty product | All five newer than the 0.4 commit; none shows the old wordmark. **Kept out of `run_tests.sh`** — 450 KB of binary churn per gate run is repo poison |
| 0.6 | Prose: `README.md`, `docs/CONTRACTS_agents.md`, `SPEC.md`; `SPEC_CC.md` → `docs/SPEC_field.md` + `docs/SPEC_WEB.md` | link check |

**Leave alone:** every ADR (an ADR saying "CCC" records what was decided *then* —
supersede, never edit), `events.jsonl` (append-only, being written by hooks right now),
`audit_2026-09-17/`, `.backup-2026-09-18/`, the five `STATUS_CCC_*.md` **and
`.gitignore:25` which ignores them**, `ccstore.py`/`ccboard.py`/`cc.db` identifiers, and
the false positives: `docs/vendor/1756-pm020_-en-p.pdf`, `test_tickets.py`'s `CCC-1` Jira
key, `test_coordination.sh`'s `CCC-42`, `test_runsview.py`'s `"cccccc"` run id.

**Acceptance** — run from an **ext4 clone, not `/mnt/c`** (measured 2026-09-25: 10 suites
fail on 9p under gate load, all pass on ext4):

```bash
git grep -nIi -e 'control.center' -e '\bccc\b' -e 'CCC_' -e 'window\.CCC' -e 'ccc[:.\-]' -- \
  ':!docs/vendor' ':!STATUS_CCC_*.md' ':!audit_2026-09-17' ':!.backup-2026-09-18' \
  ':!.bytedesk/task-management/events.jsonl' ':!.bytedesk/task-management/adrs' \
  ':!.bytedesk/task-management/plans' ':!*.png' ':!wsl-agent-teams' ':!taskmgmt/recovered' \
  | grep -vE 'project = CCC|CCC-1|CCC-42|"CCC"|cccccc|"username": "ccc"' \
  | grep -vE 'ccstore|ccboard|cc\.db|SPEC_CC|cc-dark|cc-light'     # must print nothing
git grep -c 'STATUS_CCC' -- .gitignore                              # must be 1
bash <(tr -d '\r' < dashboard/run_tests.sh)                         # all suites passed
```

---

### Phase 1 — Node backend, field sidecar, the differ, auth, store migration

The riskiest phase. Ordered so the gate is green at every commit.

**1.0 Node in WSL.** Pin `AGENTMUX_NODE` to the absolute nvm path; `prestart` refuses a
`/mnt/c` node. *AC:* `$AGENTMUX_NODE -v` → v24.x from a non-interactive shell.

**1.1 Extract the field library — one copy, two importers.** The invariant is that
there is never a second copy: two copies drift within a week and the differ then compares
a module against its own stale twin.

**Sequenced in two steps, and the order was changed after starting it (2026-09-25).**

- **1.1a — stand the shell up where the modules already are.** `field/app.py` imports
  the protocol modules from `dashboard/` via one `sys.path` line, and `server.py` keeps
  importing them exactly as today. This is the plan's own "two consumers, one library"
  with no move at all. **Done** — see TM-018.
- **1.1b — then `git mv` into `field/protocols/`**, at which point that same single
  `sys.path` line is the only thing that follows them.

The move was originally written as step one. Doing it first churns ~13 test files —
`test_enip.py:16` is a bare `import enip` relying on Python putting the script's own
directory on `sys.path` — for no functional gain while the sidecar does not yet exist.
Standing the shell up first makes the sidecar real, testable and committable on its own,
and leaves the reorganisation as a pure rename with a green gate either side of it.

- **`codesys_panel.py` splits** (473 lines; it imports `ccboard` + `ccstore`, so it is not
  a field module and cannot move whole). Client half → `field/protocols/codesys_client.py`;
  `targets`/`plcstate`/`bootapp`/`journal` stay API-side. Budget a day; not in the draft.
- **`netscan.py` needs a Windows test first.** `running_under_wsl()` at `:202` *inverts*
  once the module runs on Windows, and `neighbour_table()` shells `ip neigh`/`arp` whose
  Windows output uses dash-separated MACs (`:213`). Test against recorded output from
  both hosts **before** the move.
- **`mqtt_monitor.py` has no dedicated test** — write one: the `paho is None` path, TLS
  assembly, reconnect-visible-not-silent, and the >64 KB retained payload that was the
  reason Paho replaced `mqtt.py`.
- HTTP surface one-to-one with today's endpoints so the Node layer is a pure rename and
  the differ works on byte-identical bodies. Same `read_cc_body` guards. Stateful
  singletons move with their resume-on-start behaviour, persisting to `%LOCALAPPDATA%`,
  **not** `$AGENTMUX_HOME` (which is WSL-side).
- **No route takes a raw CIP service, class, instance or attribute.** No
  `generic_message` passthrough. This is the real audit boundary (§8, Phase 4).

**1.2 Scaffold the API.** npm workspaces (not pnpm — symlinked `node_modules` interacts
badly with 9p; not Turbo — three packages). Fastify 5, Zod, TS strict.

**SQLite driver: `node:sqlite` (built-in).** No native build, no node-gyp, no ABI
mismatch when the same checkout is opened from both OSes. *Rejected* `better-sqlite3`:
faster, but needs a toolchain and a rebuild per Node minor — the exact dependency posture
`vendor/README.md` exists to avoid.

Open exactly as `ccstore.connection()` does (`:105-136`): `WAL`, `foreign_keys=ON`,
`busy_timeout=5000`. Three rules while Python and `tm` are concurrent writers:
**Node never runs DDL** (Python owns migrations for the whole strangler; Node asserts
`user_version == 2` and refuses otherwise); **Node never creates the file**; **one
connection, short transactions, `IMMEDIATE` for writes.** Port `ccstore.py:108-113`'s
path safety verbatim — refuse a symlink `cc.db`, refuse `st_nlink != 1`.

**tmux:** `execFile("tmux", ["-L","agentmux", ...])`, argv array, `shell: false`, 5 s
timeout. Port `stream_superseded` and the `BoundedSemaphore(16)` rule — `server.py:50,76`
records the measured failure (seven panes over two reloads exhausted sixteen slots).
**SSE frame format stays `data: <base64>\n\n`** byte-identical.

**1.3 The differ.** Strangler topology as in §4. What is differ-able, and what is not:

| Class | Method |
|---|---|
| Pure reads over cc.db / filesystem (~24 shapes) | **Full JSON diff**, both servers on separate copies of a frozen cc.db. Where the differ earns its keep |
| tmux reads | Differ-able **only against a fixture tmux server** — pane geometry and `client_activity` change between two live calls |
| cc.db writes (17) | **Shadow-write differ**: `Connection.backup()` to freeze (no `sqlite3` CLI in WSL), copy to two homes, replay, diff **response JSON *and* a canonical DB dump**. Normalise timestamps, `board_history.id`, uuid4 — as a **whitelist**, so an unnormalised field that drifts is a finding, not noise |
| SSE | **Not differ-able.** Transcript differ over N seconds against a fixture pane, plus a golden-file test of the framing bytes |
| tmux mutation (`/api/resize`) | Fixture tmux, assert on `list-panes` after |
| Stateful singletons (modbus poller, mqtt monitor) | **Not differ-able** — two pollers on one RTU line is bus contention. Contract tests against `stub_broker.py` and a fake transport |
| Hardware writes | **Never differ against live hardware.** Recorded-wire-transcript tests; the existing Python unit tests remain the oracle |
| External effects (github, jira) | Differ the **built argv / URL / body**, never the call. `atlassian.py` already has `dry_run=True` |

**The harness exists before the second handler moves**: `/api/epics` moves first *with*
it, and nothing else moves until the differ reports zero diffs across the corpus.

**1.4 Auth.** Sessions table added by a **Python migration** (one schema owner).
**Login without a secret in the browser**, preserving `SPEC_CC.md:19`: the API prints a
one-time bootstrap URL to the terminal (the jupyter pattern), single-use, 10-minute
expiry. **No password field, ever** — *rejected* because it violates the posture and
creates a credential store the repo deliberately does not have. Cookie
`__Host-agentmux_sid`, `HttpOnly`, `SameSite=Lax`. CSRF double-submit with
`timingSafeEqual`, **keeping the Origin allowlist as defence in depth** with
`allowed_origins()`'s exact semantics. Machine clients (`coordination.py`, `run.py`,
`dispatch.py`) use a bearer token at `$AGENTMUX_HOME/api-token`, 0600 — no cookie,
therefore no CSRF check.

**A behaviour change worth naming:** today the 17 board writes take `actor` from the
**request body** (`server.py:1424`) — client-asserted identity. After 1.4 the server takes
it from the session and **overrides** the body. The differ will flag this on every write,
so **1.4 lands after the write-path baseline is green**, with the expected-diff list
checked in.

**Industrial writes keep their own gate on top.** Auth authorises the *request*; the typed
confirmation authorises the *shot*. Two independent gates; do not collapse them.

**1.5 Board-store migration.** Write through the plugin's `store.mjs create()`, which
accepts an explicit id, runs inside `withLock`, stamps `board`, patches `index.json` and
logs the event. *Rejected `bin/tm`*: 2,467 lines gated by `requireEpic`,
`requireAcceptance`, `wipLimit: 3` — a bulk import would be refused row by row.
*Rejected raw file writes*: skips the frontmatter contract, the atomic rename, and the
tool-call-markup guard. There is **no counter file** — `nextId` derives from filenames, so
importing `TM-001..093` makes the next key `TM-094` automatically.

| Namespace | Resolution |
|---|---|
| Epics | cc.db `EP-nnn` → **`EP-(nnn+100)`**. An offset is a pure function, mechanically reversible, and every cross-reference rewrites with one regex whose inverse is exact |
| **`EP-015` ≡ bytedesk `EP-001`** | **Merge, do not import.** Same body of work; two records is the drift the store exists to prevent |
| cc.db `EP-001` (CCC rebrand) | → `EP-101`, status `done` |
| Tasks | `TM-001..093` keep their keys — bytedesk has zero tasks |
| cc.db `ADR-0001` | → `ADR-0024`. bytedesk `ADR-0001` gets a **supersede** pointing at ADR-0023 |
| **`activeEpic` disagrees today** — cc.db says `EP-023`, `config.json` says `EP-001` | Resolve explicitly to the mapped key; do not let one silently win |

**Census verified directly against `cc.db`, 2026-09-25** — the migration is sized on
these, so they were worth checking rather than inheriting: 21 tables, `user_version=2`,
WAL. 93 tasks (84 done, 2 open, **7 deleted**), 23 epics (9 done, 6 open, 3 in_progress,
1 blocked, **4 deleted**), 254 acceptance, 130 comments, 111 touches, 77 evidence, 874
history, 61 labels, 33 deps, 14 commits, 6 roster, 4 devices, 1 ADR, 2,283 journal.

Two things that check surfaced, which this plan did not address:

- **Eleven soft-deleted entities** — 4 epics and 7 tasks with `status: deleted`. The
  migration says "23 epics → 22 + 1 merge" and silently assumes they all travel. Decide
  explicitly: the plugin *has* a deleted concept (`tm_task_update` carries `delete` and
  `restore`), so they *can* migrate as tombstones. Recommendation: **migrate them**.
  Keys are never reused, so dropping them leaves holes that look like data loss to
  anyone auditing the sequence later, and a tombstone is cheaper than that question.
- **`board_counters` has 3 rows** and does not travel. The plugin derives `nextId` from
  filenames (`store.mjs:716-730`), so nothing needs syncing — but cc.db must stop minting
  once the migration lands, or the two stores start issuing the same key. That is the
  one-writer rule ADR-0001 was right about, and it survives ADR-0001's reversal.

**874 history rows:** do **not** inject into `events.jsonl` — it is a live log,
`rotateEvents` keeps one generation, and 874 synthetic rows are ~15% of it. Instead
archive verbatim to `events.0-ccdb.jsonl`, fold a per-entity digest into each doc under
`## History (imported from cc.db)` where a human actually looks, and emit **one** live
`import` event. *Rejected* naming it `events.1.jsonl` — `rotateEvents` would overwrite it.

**2,262 journal rows and the cross-store link:** the real finding is that **there is
nothing to link today** — `ccstore.py:61-63` has no entity key. Add nullable
`journal.entity_key`, backfill by regex through the migration map, report the unmatched
count, and give each doc `journalRef: "agentmux://journal?entity=TM-042"` — one-way,
resolvable only by the app that owns both stores, and honest that the plugin cannot read
SQLite.

**Idempotent and reversible:** dry run into `TM_ROOT=/tmp/tm-dry` first; `map.json` and a
`manifest.jsonl` of `{id, path, sha256}`; rollback deletes the manifest paths and restores
`index.json`; re-run skips on matching sha and **refuses, naming the row**, on a
mismatch — never blind-upsert. Pre-flight all 116 bodies for tool-call markup, since
`write()` throws on it and cc.db bodies were written by agents. **cc.db is never mutated
by the migrator**; retiring the board tables is a separate later commit.

**Retirement:** 28 ops retire; **12 move and stay on cc.db** —
`/api/{agents,teams,codesys,chatter}/*`. Any later work assuming they retire is wrong.

---

### Phase 2 — Modes and the blade

**2.1 Mode YAML.** `modes/<id>.yaml` plus one `modes/_registry/mcp.yaml`. Validated with
**Zod `.strict()`** in `packages/shared` (one source for the runtime validator *and* the
TS type *and* structured `issue.path`), parsed with **`yaml` (eemeli)** so `parseDocument`
carries line/column — a diagnostic reads `modes/plc.yaml:7:16 — default_view "iiotx" is
not in views`. `{merge: false, maxAliasCount: 0}`.

```yaml
version: 1
id: plc                    # must equal the filename stem
title: PLC
theme: agentmux-dark
views: [terminals, iiot, board, runs, organization, settings]
default_view: iiot         # must be a member of views
mcp:    [codesys_rt, modbus, drawio]
agents: [plc-dev, plc-test-engineer, senior-reviewer]
skills: [codesys-mcp, codesys-oop, paste-guide, hmi-test]
blade:
  default_state: pinned    # hidden | overlay | pinned
  width: 420
  panels: [conversation, runs, confirmations]
  permission:
    default_mode: default  # bypassPermissions is REJECTED by the schema
  orchestrator:
    enabled: true
    verbs: [list, read, tail, claims, tasks, journal, post, spawn, send, dispatch, collect]
session:
  durable: false           # research: true + background_agents + artifact_writer
```

The MCP registry is **host-aware, which is the whole point** (§1.3.2): each server
declares `host: windows|wsl`, its command, and a **`write_tools:` list**. That list is not
documentation — every name in it is auto-added to the confirmation-required set and is
never eligible for `allowedTools`.

**2.2 Invalid files are never fatal.** A console that will not start because of a YAML
typo is worse than one that starts degraded and says so. The bad mode is **quarantined**;
a previously-good compiled snapshot stays live; `GET /api/modes` returns
`{modes, diagnostics}` and Settings renders them. If the **active** mode goes invalid the
user is not switched out — a banner reads *"plc.yaml has been invalid since 14:03 —
running the last good version (loaded 09:12)."* If **zero** modes compile, boot into a
compiled-in `fallback`: all views, blade hidden, no MCP, no orchestrator verbs.

**2.3 Hot reload is a poll, and says so.** `modes/` is on 9p, so `fs.watch` would ship and
never fire. 1 s `readdir` + `stat` (~6 stats, sub-millisecond), 250 ms debounce (editors
write-truncate-then-write, and a mid-write read is a guaranteed parse error), compile,
then **atomically swap behind one reference** — never mutate a live mode.
`$AGENTMUX_HOME/modes/<id>.yaml` (ext4) overrides the repo copy and *can* use `fs.watch`;
the loader probes the filesystem and **reports which mechanism is in force**.

**A live blade session does not silently change permission.** Blade config is captured at
session creation; a mode change shows a card — *"The plc mode changed. Apply to this
conversation?"* — and accepting restarts `query()` with `resume: <sdkSessionId>`, so the
conversation survives but the tool surface is re-derived. Auto-applying would mean a
session that was safe when opened is not safe now.

**2.4 Resolving `mcp:`, `agents:`, `skills:` from WSL** — the section the draft most needed.

- **`agents:`** → `.agentmux/agents/<name>.md` frontmatter + body → the SDK's
  `AgentDefinition`. Two distinct roles that must not be conflated: an in-process **blade
  subagent**, and a **dispatch target** (`agentmux spawn --agentdef`).
  **`posture: unrestricted` must never map to `permissionMode: 'bypassPermissions'`** —
  posture is a *pane* concept, and a subagent inherits the parent's mode. Hard-code to
  `undefined` and assert it.
- **`skills:`** → the API materializes `$AGENTMUX_HOME/modes/<id>/.claude/skills/` on
  **ext4** and runs the query with that `cwd` and `settingSources: ['project']` —
  deliberately **not `'user'`**, so a mode is a complete, reproducible description rather
  than depending on the operator's personal skill set. Search order: repo
  `.agentmux/skills/` → `$AGENTMUX_HOME/skills/` → the Windows root. **Copy, fingerprinted
  by content hash — not symlink**, which would reintroduce a 9p read per skill load. A
  materialized SKILL.md containing `C:\` or `powershell.exe` earns a **warning**
  diagnostic, not a block — `wsl-cli` legitimately reaches Windows through interop.
- **`mcp:`** → `host: wsl` passes straight through as stdio. **`host: windows` is not
  launched by the API** — it is launched by `agentmux-field`'s new `mcp_bridge` and exposed
  as **MCP Streamable HTTP** at `http://127.0.0.1:8788/mcp/<name>` with the shared secret.
  *Rejected running Windows stdio through interop*: CRLF on stdout corrupts JSON-RPC
  framing, argv quoting is the minefield the `wsl-cli` skill exists for, the child's
  cwd/PATH is Windows-shaped, and `interrupt()` cannot reliably kill a Windows process
  tree from Linux.

**2.5 The orchestrator boundary — and the correct guard.**

**One chokepoint:** `packages/api/src/orchestrator/exec.ts`. Absolute binary paths from
config (never a PATH lookup), `execFile` with an argv array and **`shell: false`**, a
**clean environment** that **deletes `ANTHROPIC_API_KEY`** and every other secret, a
per-verb argv Zod schema, a timeout, and one journal record plus one `blade_actions` row
per invocation.

**Identity is the control the draft missed.** Because `AGENTMUX_AGENT` unset ⇒
orchestrator, and `dispatch|collect|pool` refuse when it *is* set:

- Reads and low-risk writes run with **`AGENTMUX_AGENT=blade`**. An attempt to escalate to
  `dispatch` is then **refused by `agentmux.sh` itself** — defence in depth using the
  existing guard rather than around it.
- `AGENTMUX_AGENT` is unset **only** while holding a valid commit token for an
  `orchestrator_dispatch` card.
- Register `blade` as a virtual queue address (the system already supports these —
  `inbox` exists for `orchestrator`).

| Tier | Verbs |
|---|---|
| **Free** (`AGENTMUX_AGENT=blade`) | `agentmux list / read / tail / claims / tasks / run status / inbox`; `agentmux journal` (append-only, attributable); `agentmux post` (queueing is not delivery); `tm board / next / show / find / log / events / why / graph / doctor / standup / export`; `tm comment` |
| **Behind a committed card** | `agentmux spawn / kill / dispatch / collect / pool` → `orchestrator_dispatch`; `agentmux send / key` → `orchestrator_send` (**`--force` never in the allowlist**); `tm start/done/park/block/assign/label/move/…` → `board_write` |
| **Forbidden outright** | `agentmux claim` / `release` in any form — **especially `claim --for <agent>`**, which is impersonation, and a crashed API would leave a lease nobody releases. `run start|assign|submit|verdict|complete|teardown` — runs belong to the orchestrator, `verdict` to the reviewer, and the human gate already has a UI path recorded as `operator (dashboard)`. `courier`, `reap`, `board config`, `tm override/config/reindex`, `TM_ENFORCE=off`. **Any direct write under `$AGENTMUX_HOME`** (`claims/ queue/ run/ dispatch/ *.warrant`) — refused by the single filesystem-write helper, not by intention. Any `tmux send-keys / new-session / kill-session / respawn-pane` |

**The replacement startup guard — G1–G5.** Four refuse to boot; the fifth, closest to the
original intent, **reports**:

- **G1 Singleton.** `flock` on `$AGENTMUX_HOME/api.lock` plus the port bind. Two APIs on
  one home is the actual second-scheduler hazard — the legitimate kernel of the draft's
  idea: a lock the API *should* own and does not.
- **G2 Not impersonating.** `AGENTMUX_AGENT` must be unset or exactly `blade`. If it names
  a live session, the API was launched from inside an agent pane and every verb would be
  attributed to that worker.
- **G3 Write-surface self-test.** Call the filesystem-write helper against each forbidden
  prefix with a probe path, in-process, before the HTTP server binds; require every one
  refused, then check for residue. This **tests the invariant** instead of sampling
  unrelated state.
- **G4 Allowlist integrity.** Every exposed verb has an entry and an argv schema; every
  `requires_commit` entry maps to a card kind; no entry names a forbidden verb. This is
  what catches a future edit adding `run complete` to a mode's `orchestrator.verbs`.
- **G5 Environment hygiene — report, never refuse.** Record `courier status`,
  `pool status`, the presence of an orchestrator warrant; surface in Settings as *"who
  else is coordinating right now"*. If the pool is live, the dispatch card warns *"the
  pickup loop is running; it may take this card before you do"* — which is useful,
  whereas refusing to start is not.

**2.6 The Agent SDK integration.** `@anthropic-ai/claude-agent-sdk` — the harness, not the
Messages-API tool runner, not Managed Agents.

- **Streaming input mode is non-negotiable**: `prompt` is an `AsyncIterable`, because a
  string prompt cannot accept a second user message mid-turn, and both barge-in and
  follow-ups need that. Capture `session_id` from the `system/init` message — it is what
  `resume` needs.
- Transcripts under `CLAUDE_CONFIG_DIR=$AGENTMUX_HOME/claude-config` — **ext4, and the
  directory already exists** — which also keeps blade transcripts out of the operator's
  personal Claude Code history.
- **Transport: SSE server→client, POST client→server. WebSocket rejected** — four reasons,
  the decisive one being that **WS handshakes are not subject to CORS**, so staying on
  HTTP means `allowed_origins()`'s model covers the entire surface instead of needing a
  second one. Barge-in needs no socket: `POST /api/blade/:id/interrupt` on loopback is
  sub-millisecond.
- **Exactly one SSE connection per tab**, multiplexed by topic
  (`blade,board,runs,status,terminals,modes,prefs`). Forced by the measured
  6-connection cap. Every event carries a monotonic `seq`; reconnect uses `Last-Event-ID`
  against a bounded ring, which is what makes "survives a refresh" true rather than
  aspirational.
- **Deferral is why confirmations are durable.** Use the SDK's `PreToolUse` `defer`
  decision when a card outlives a bounded window or the last SSE consumer disconnects:
  persist the card, let the query end, resume on commit. That is what makes a PLC write
  confirmation survive the operator closing the laptop lid.
- **API key storage.** *Rejected `~/.agentmux/env`* — it is 0600 but **sourced into every
  agent pane**, which would hand the key to every codex and claude worker; that is exactly
  the failure `check_key_exposure.sh` was written after. **Primary: DPAPI on Windows,
  fetched from the field sidecar at boot** over the existing authenticated channel, held
  **in memory only** and injected per-query via the SDK's `env` option — never
  `process.env`, so it cannot leak into the children the chokepoint spawns. Fallback:
  `systemd-creds` in WSL. `GET /api/blade/config` reports `{keySource, fingerprint}` —
  the presence-not-value pattern `auth_snapshot()` already uses. Note also: claude.ai
  login is not permitted for third-party products, so this is an API-key integration
  billed to the operator's key — stated to stop someone helpfully wiring OAuth.

**2.7 The confirmation card — one typed shape, six kinds.**
`industrial_write | trade | orchestrator_dispatch | orchestrator_send | board_write |
file_write`. One shape because the audit, expiry, dry-run and did-the-params-change
questions are identical for a PLC write and a trade; the kind-specific part is the shape
of `target` and `dryRun.rendering`, and that is data, not a type.

Carries: `actor` in **three layers** (authenticated human / origin / proposing agent /
mode); `action` with the canonical tool input verbatim **and a `paramsHash`**; `dryRun`
with **before and after read back live where the protocol allows** and an explicit
`readBackAt` (null ⇒ the UI must say *"no current value"*); `requirement` (typed phrase,
hold-to-commit ms); `expiry`; **`killSwitch` stated on the card, not merely enforced**;
and `audit` refs.

- **`paramsHash` is load-bearing.** `canUseTool` may return `updatedInput`. If the card
  could commit an input other than the one rendered, the dry-run is decoration. The hash
  binds render to execution and the hook re-checks it at the moment of execution.
- **The typed phrase is derived, never "yes"** — `MCU-PLC:bDoorOpen=TRUE`,
  `BUY 100 AAPL LIMIT 189.50`, `TM-114`. It encodes target *and* value, so muscle memory
  cannot commit a different write. **Typing is reserved for the kinds that cost money or
  move equipment**; requiring a phrase for a status change trains the operator to type
  phrases, which is precisely how the phrase stops being read.
- Commit checks in order, each a distinct 4xx: exists → not expired → not decided → kill
  switch clear → **hash matches** → phrase matches → session actor equals
  `actor.operator`.
- **Never a browser dialog.** Enforced by lint plus a grep test over the built bundle.

**2.8 Blade UI.** CSS grid `--rail | 1fr | --blade`; pinned reflows, overlay is
`position: fixed` with a backdrop. **Nothing measures the viewport** — everything uses
`ResizeObserver` on its own container, and **the refit debounces to `transitionend`, not
per frame**: `fitmatrix.js` records four earlier attempts that all oscillated, every one
because a measurement taken at the current size fed the choice of the next size. A pinned
blade animating its column would reproduce that exactly.

| State | Lives | Why |
|---|---|---|
| Conversation, tool calls, results | **Server** — SDK transcript + `blade_sessions` | The only resumable copy. The browser must never be the source of truth for a conversation that could have moved a PLC |
| Pending confirmations | **Server** — `blade_confirmations` | A deferred card surviving the tab closing is the point |
| Attached session id, blade state, width, scroll, draft | **Client** — `sessionStorage`/`localStorage` | Per-tab, cheap, wrong to sync |
| Panel order and visibility | **Server, per user** — `user_prefs` | "Layout follows you across devices on the tailnet" |

**Panel config precedence:** built-in default → mode YAML → Settings override → in-blade
arrangement, where **the last two are the same store and the same row** — two places to
change one thing that can disagree is a bug, not a feature. A chip shows which level is
in force; "Reset to mode default" deletes the row. Writes are `If-Match` on an etag so two
tabs cannot clobber, and broadcast on `prefs.changed`.

---

### Phase 3 — View migration

Order: **Settings → Organization → Board/Kanban → Runs → Status → GitHub → Terminals →
IIOT**, IIOT last because Phase 4 rewrites it.

**Test replacement.** The nine `test_frontend*.sh` are grep assertions over `app.js` — the
file says so itself. They are not portable, **but the bugs they encode are.** Replace by
class: **Vitest + RTL** for logic (tab memory, collapse memory, optimistic move,
vocabulary), **Playwright** for anything about *load order, layout or box* (exactly the
distinction `test_e2e.mjs:1-13` draws, and it is right), and **a repo-level grep test**
kept in shell for source invariants (no `innerHTML`, no `confirm(`, no `new EventSource`
outside the bus, no `fetch(` outside the api client).

**Enforcement:** a view's old shell test is deleted **in the same commit that lands its
React replacement** — never before, never batched. `run_tests.sh` gains a `MIGRATED_VIEWS`
list and the loop at `:250` skips a migrated view's shell test and runs the new suite, so
the total assertion count never silently drops. That makes "not at the end" enforceable.

| View | The hard part |
|---|---|
| **Settings** | Encode the secret-presence contract **in the type** (`{present: boolean, value?: never}`) so round-tripping a secret is a compile error, not a review catch. New Modes and Blade sections. Feed prefs stay browser-local *deliberately* — decide per key and say which |
| **Organization** | The **content-hash** conflict guard (not mtime — 9p granularity is coarse) and its structured `missing[].hint`; atomic rename on a 9p write target |
| **Board / Kanban** | **Read from an in-process projection**, not `tm --json` per request (a Node spawn plus a full store read over 9p is 200-400 ms). Build at boot from `index.json` + frontmatter, keep current by **polling `events.jsonl`** with `stream_all`'s offset + inode pattern. **Filter by event kind and reconcile on the unknown** (§1.3.9) — re-read the named entity, or rebuild; never silently drop. Drag → optimistic with a client `opId` → reconcile on whichever of the response or the SSE event arrives first. **The gate may refuse**: roll back and render the refusal **with the verb that fixes it**, which is what `ccboard.Refused.missing` gives today. **Serialize writes per task id** — `tm` is a process |
| **Runs** | **The draft mis-describes this.** `runs.js:22-23` states outright *"There is no SSE, because the pane is already streamed"* — it polls at 5 s. Treat live streaming as **new work**. `$AGENTMUX_HOME/runs` is **ext4**, so the API genuinely can `fs.watch` and push. Keep `attention()` feeding badge *and* sort from **one selector** — the comment says they must not disagree. The review gate stays an operator action in the view, not a blade card: a human reads a diff |
| **Status** | The badge must stay honest **while hidden** — model as a store subscription, not a component effect. Keep "clear on screen only" and its wording verbatim. Chatter stays in `cc.db` — it is agent conversation, not task state |
| **GitHub** | The device-flow state machine. **Do not widen the write surface** — push/merge/force-push/delete are deliberately absent, and the port must record that as a decision |
| **Terminals** | **xterm as a `useRef` island, created once, never re-created by render** — the React translation of invariant #2 and the single thing most likely to be got wrong. Move to `@xterm/xterm` (vendoring existed only because there was no build step). **Port `fitmatrix.js` as a Playwright spec** — an exhaustive matrix asserting `legible/capped/stable/crisp/predicted`; it is the most valuable frontend test in the repo. **No CSS transform on a terminal** — it resamples glyphs into mush. **The terminals route is never unmounted** while the app is open (use `hidden` keepalive) — the React translation of the `viewScroll` bug. Port `open_log` verbatim: regular files only, reject `st_nlink > 1`, `O_NOFOLLOW`, size caps |
| **IIOT** | A **faithful minimal port that Phase 4 replaces** — not a redesign. Keep every honesty affordance; route writes through `industrial_write` cards; stop. Building the device tree twice is the waste the ordering exists to avoid |

**The tmux-write question, answered.** ADR-0022 says "Node observes", and `/api/resize`
writes tmux. That is not a violation, and the distinction must be written down because it
is the one people will get wrong:

- **Coordination state** — which agents exist, who holds what: `new-session`, `send-keys`,
  claims, run sidecars, the queue. **The API never writes these.**
- **Display geometry** — how wide the pane the browser is rendering happens to be:
  `set-option window-size manual`, `resize-window`. Nothing any other agent reads. The
  terminal equivalent of scrolling.

So **keep the resize write**, state the rule as *"the API writes tmux display geometry and
nothing else"*, and enforce it with an **argv allowlist** on the `tmux()` helper, asserted
by a G3-style boot self-test. Left as "observes", someone will delete the resize path and
the grid goes back to being illegible.

**Terminals is also the view that proves ADR-0023 was right**: with the API inside WSL,
`tmux -L agentmux` is a local socket and `capture-pane` a local process. On Windows every
one of those is an interop round trip.

**One dev-loop consequence** not to discover mid-phase: `node_modules` and Vite's dep
cache on `/mnt/c` are painfully slow from WSL. Run Vite for `agentmux-web` **from
Windows** (where the repo natively lives) proxying `/api` to the WSL API — which works
today via localhost forwarding. Production is a `dist/` the API serves, so the split is
dev-only.

**The deletion gate for `server.py`** — all six, not "when the last view is migrated":

1. Every view has a React implementation in the production bundle, and all nine shell
   tests are deleted alongside their replacements.
2. The differ has been green over the recorded corpus for **14 consecutive days of real
   use** — not a week; a week contains no monthly cron and may contain no weekend idle.
3. **`coordination.py`'s POST to `127.0.0.1:8787` succeeds against the Node API**, verified
   by running the real CLI from WSL and asserting the row lands. This is the one inbound
   write path and the easiest to break silently.
4. Every `8787` hardcode inventoried and either working or retired (40 code hits).
5. The **protocol** Python tests still pass against the sidecar. Only the HTTP-layer tests
   retire.
6. A tagged commit and a `dashboard/` archive branch.

Then delete in **one commit, one PR**, differ report attached. A half-deleted dispatcher
is worse than either end state. `ccstore.py`, `ccboard.py` and `cc.db` do **not** die with
it — only the board tables retire.

---

### Phase 4 — IIOT and Rockwell

**The invariant everything follows from:**

> **The API never writes to field equipment. Only the sidecar does.**

node-opcua in the API is constructed read-only with no write path (`check_api_readonly.sh`
proves it); pycomm3 in the sidecar reaches the wire only through an audited wrapper;
`enip.py` keeps the journal.

**4.1 Unify the write journal** — prerequisite, because there are two today (§1.3.8).
`field/writejournal.py` with `intent(record) -> Handle` / `Handle.settle(outcome)`, one
`field-writes.jsonl` carrying `transport`, **fsync before returning**, and
**fail-closed**.

**Correction, checked 2026-09-25:** an earlier draft of this plan said that posture
"exists but is nowhere tested". That is **wrong**, and the existing tests are the
specification to preserve rather than duplicate:

- `enip.py:230-236` already does `flush()` + `os.fsync()`, so the intent is genuinely
  durable, not merely written.
- `test_enip.py:196` `test_intent_is_durable_before_send_and_timeout_closes` patches
  `request` with a side effect that **reads the journal off disk at the moment of
  transmission** and asserts the `intent` row is already there with the right value.
  That is a direct proof of both ordering and durability.
- `test_enip.py:177` `test_write_guards_prevent_network` sets
  `journal.side_effect = OSError` and then asserts `request.assert_not_called()` — the
  fail-closed invariant, tested.
- `test_enip.py:217` `test_failure_audit` covers CIP error → `rejected` and disconnect →
  `unknown`.

`logix.py` — the *second* journal — is covered even harder, and it is the stronger
specification of the two:

- `test_logix.py:288` patches `connect` with `side_effect=AssertionError('network
  used')`, so a guard failure that reached the wire fails the test by construction.
- `:302-303` patches `_journal` with `OSError('disk full')` and requires the write to
  raise — fail-closed, again.
- `:314` patches `logix.os.fsync` with `wraps=` and asserts it was **actually called**.
  That is durability checked at the syscall, not inferred from the code.

So 4.1 is a **refactor that must not lose these**, not a gap to fill. Port all of them
onto the unified journal and keep them passing — including the fsync-was-called
assertion, which is the one most easily dropped in a rewrite because it looks like an
implementation detail and is in fact the whole guarantee. If any of these can be made to
pass against a journal that writes after transmission, the refactor is wrong.

A one-shot migrator merges the two legacy files in timestamp order; a test asserts
nothing writes the old paths afterwards.

**4.2 Vendor pycomm3** under ADR-0024 (§3.4).

**4.3 What pycomm3 actually closes** — mapped to `logix.py`'s verbatim gaps:

| `logix.py` gap | pycomm3 |
|---|---|
| "callers supply an instance ID obtained from the controller" (`:6-7`) | `LogixDriver.tags` — each entry carries `instance_id`, `tag_type`, `data_type`, `dim` |
| "template discovery/member layout decoding is not included" (`:10-11`) | For a struct, `data_type` contains `template` (`structure_handle`, `structure_size`, `member_count`) and `internal_tags` — member → `{offset, data_type, bit, array}` |
| "the caller must supply the handle and element size… not guess a UDT layout" (`:11-12`) | `read('UDT.Member')` returns a dict keyed by member name; `write(('UDT', {...}))` resolves handle and size from the cached template |
| "version 21 or later… callers supply" | `get_plc_info().revision.major`, read once on connect. No caller types a version again |
| `enip.py:4` "No routing through a chassis/backplane" | `LogixDriver('10.1.2.3/bp/1')` |

Plus `CIPDriver.discover()` — **UDP broadcast ListIdentity** giving vendor, product code,
revision, serial and device *state* that a TCP sweep cannot; and multi-service batching,
which `enip.py:4` explicitly lacks.

**4.4 The audit seam — five layers, honest about which are real.**

1. **One journal, one module** (a real change) — §4.1.
2. **A single import site** (a tripwire, enforced by CI): `field/rockwell.py` is the only
   file permitted to `import pycomm3`, asserted by `check_field_writes.sh` following the
   existing `check_key_exposure.sh` pattern.
3. **A capability wrapper** (defence in depth, **not** a boundary): `AuditedLogixSession`
   never hands out a driver and rebinds `driver.write`/`generic_message` to a raiser.
   **State plainly: Python has no private.** A caller reaching for the mangled attribute
   gets through. This layer exists to catch *our own future mistakes*, which is the actual
   threat model — nobody is attacking a loopback sidecar from inside itself.
4. **The process boundary — the real boundary.** The sidecar exposes **no route taking a
   raw CIP service, class, instance or attribute**, and no `generic_message`. The only
   write route takes a server-minted, single-use, expiring `ticketId`. That is what holds.
5. **The proof tests.** A **whitelist test** enumerating public callables and asserting
   the write-capable set is *exactly* `{write_tag, write_member, write_struct}` — a new
   method fails until someone classifies it, and this is the test that survives future
   authors. Plus ordering (journal-intent precedes driver-write), gate tests
   (`confirm=False`, empty actor, bad ticket → **nothing written, driver never called**),
   fail-closed, bypass, and outcome mapping (CIP status → `rejected`; timeout → `unknown`,
   **with no retry path exposed**).

**Keep `logix.py` as a verification oracle**, not dead code: a cross-check test reads the
same tag through both decoders against one fake CIP server and asserts identical values
for every type in `logix.ATOMIC_TYPES`. Two independent decoders agreeing is stronger
evidence than either alone, and it converts a sunk cost into a regression asset.

**4.5 node-opcua — a strictly optional feed.** Rockwell's embedded OPC UA server is
firmware- and SKU-dependent, and ADR-0019 already records that it needs configuring on the
Rockwell side first. **Acceptance: the tag table is fully functional, including writes,
with zero OPC UA endpoints configured.** `SignAndEncrypt`/`Basic256Sha256` default; a
downgraded endpoint is recorded and badged, never the default.

**4.6 The merge — where this phase earns its keep.** `iiot.js:11-14` is right, and the
two-host split makes its current implementation *wrong*: `iiot.js:93` computes staleness as
`Date.now() - receivedAt`, i.e. **browser clock minus server clock**. In the target that
becomes browser (possibly a phone on the tailnet) minus WSL minus Windows, and WSL2 clock
drift after host sleep is a recurring bug class. Age is the one number on this panel that
must not be wrong.

> **Rule: `ageMs` and `stale` are authored at the source, never by subtracting two clocks.**

The canonical row carries `value`, three-valued `quality`, `ageMs`, `observedAtIso`,
`expectedIntervalMs`, `staleAfterMs`, `stale`, `feedId`. The browser renders
`ageMs + (performance.now() - snapshotArrivedAt)` for a smooth tick and **never computes
staleness itself**. Modbus already does this server-side (`modbus_poll.py:245`) — add
`ageMs` to the same expression. OPC UA uses `sourceTimestamp` over `serverTimestamp` and
maps `StatusCode` to three values — **do not flatten OPC UA's quality model into a
boolean**.

- Transport is **SSE from the sidecar**, not a snapshot the API polls — polling a poller
  doubles the latency you are trying to measure.
- **Never reconcile two sources into one number.** One physical point on both Modbus and
  OPC UA is **two rows**, linked, with disagreement highlighted. Averaging or
  fresher-wins is the same class of lie as an unaged number: it puts a value on screen
  that no device produced.
- **Feed-level staleness is its own banner.** Forty chips greying at once is one
  connectivity fact, and rendering it as forty trains the operator to ignore chips.

**4.7 UI.** Device tree merged from netscan + `CIPDriver.discover()` + OPC UA
`getEndpoints()`, each contribution labelled with its origin; promotion writes the existing
`cc.db devices` table, no new schema. Tag table virtualized, **with a render-invariant test
that fails if any row renders without a non-empty age element** — the mechanical
enforcement of `iiot.js:11-14`, so it cannot be lost to a refactor the way a comment can.
Writes go ticket → typed phrase → submit → intent **and read-back** displayed. On
`unknown`: *"Unknown outcome — investigate at the equipment. Do not retry."* and **no
retry button is rendered.** Not disabled — **not rendered**.

**4.8 Tests.** `test_netscan.py` targeting only what `test_field_panels.py:392-455` does
*not* cover: `_parse_arp` across Linux `ip neigh`, Linux `arp -an` and **Windows `arp -a`
dash-separated MACs**; the **WSL fallback branch** (the most consequential untested branch,
and the one `netscan.py:186-201` spends fifteen lines justifying); `check_ports(None)`
returning a copy; a raising journal callback **not** aborting the scan (`:352-356` swallows
it deliberately, and that is load-bearing). Plus `test_mqtt_monitor.py` (§Phase 1.1).

---

### Phase 5 — Investing

**5.0 The artifact boundary comes first, because the repo is PUBLIC** (§1.3.1). No
investing artifact — research pack, position, balance, account number, order record —
goes anywhere under the repo. All of it lives in `%LOCALAPPDATA%\agentmux\broker\` and
`$AGENTMUX_HOME/investing/`. `check_no_financial_artifacts.sh` greps the working tree for
account-number patterns, `SUBMIT_DISABLED` and `broker-orders.jsonl`, and fails the suite
if any appear. This is the largest unmitigated risk in the draft, whose open question 3
proposed putting research packs in the committed tree.

**5.1 `agentmux-broker` is a third process on Windows.** **Not** in the field sidecar:
the process that can write to a PLC must not also be the process that can spend money.
Four reasons — blast radius (Chromium rendering fidelity.com plus third-party assets in
the same tree as the CIP write path is an unforced error); independent lifecycles
(restarting the browser session must not stop field polling while someone is watching a
line); credential scope; and a kill switch that can mean "stop the process".

**Windows, not WSL**, despite the vendored Linux Chromium (which is untracked scratch and
gets deleted): DPAPI/Credential Manager are Windows; **2FA needs a human at a real
window**, and a headed Chromium on Windows is a native window on the desktop the operator
is sitting at, whereas WSL adds a WSLg failure mode to the most human-in-the-loop step in
the system; and the profile stays on NTFS rather than 9p.

**5.2 2FA — the decided answer: persistent profile, manual re-login.**
`chromium.launchPersistentContext(userDataDir)` — **not `storageState`** — so cookies,
IndexedDB and the device-trust token all survive. A remembered device turns the
overwhelming majority of sessions into password-only, which is worth more than any clever
automation. On expiry the broker **alerts and does not re-auth**; the operator logs in by
hand in that profile. This holds `SPEC_CC.md:19` completely — no secret ever touches the
dashboard.

- **Do not store a 2FA secret. Do not implement Symantec VIP token generation.** If it is
  ever proposed, that is a new ADR.
- **Failure locks, it does not retry.** Two failed password attempts → `LOCKED`, manual
  clear only. Locking out a real brokerage account is strictly worse than a broken panel,
  and a retry loop against a login form is how that happens.
- **Keepalive** is jittered 8-12 min, market hours ± 30 min, **only while investing mode
  is active**. A fixed-interval poller running 24/7 is both rude and trivially
  fingerprinted.

**5.3 Selector drift — alert, never retry.** A versioned `broker/selectors.json` mapping
logical names to locators, each with a `probe` and a `lastVerified`. On a miss:
`SelectorDrift` → screenshot + DOM snapshot → journal record → session `DEGRADED` →
**kill switch armed** → blade alert. **Never a fallback locator, never "click the next
likely button."** On an order form, guessing which button is Place Order is how you submit
something nobody authorised.

**5.4 The order pipeline.**

```
research → OrderTicket (Zod) → server-side guardrails → DRY RUN (default)
  → typed confirmation (hash-bound, 90 s) → kill switch disarmed?
    → intent record (fsync, BEFORE the click) → submit (idempotency-keyed)
      → read-back verification → terminal record
```

- **Guardrails are server-side and configured in a file, not overridable from the blade**:
  max notional, max % of portfolio, max orders/day, allow/denylist, require-limit outside
  RTH, churn guard. Each returns pass/fail **with a reason**, and the reasons render.
- **Two distinct dry runs, because conflating them is dangerous.** `local` (**default**)
  makes **zero** browser calls and renders the exact ticket. `preview` (opt-in, per ticket)
  drives Fidelity's own Preview Order page to capture its cost and margin estimate, then
  navigates away — **never clicks Place Order.** A "dry run" that silently drives a live
  order form is not what most people mean by dry run, so the UI labels them differently.
- **Intent before transmission**, same discipline and same words as `enip.py:8-11`:
  `submitted | rejected | unknown`, and **unknown means investigate, never auto-retry.**
- **Read-back** by Fidelity's confirmation number, falling back to
  `(symbol, side, qty, submittedAt ± 120 s)`. A mismatch arms the switch and **attempts no
  automatic cancel** — an auto-cancel is another unconfirmed order action taken by
  software that has just demonstrated it does not know what it did. Offer a one-click
  "open Fidelity in a real browser at the Orders page" instead.

**5.5 The kill switch is stronger than "a file that exists at install."** Present =
disabled; created by the installer. Beyond that: checked **inside the broker**, on disk,
**re-read immediately before the click**, never cached and never trusted from the API.
Disarming requires a typed phrase **and sets an expiry**, and it **re-arms automatically**
on expiry (60 min), process restart, any `SelectorDrift`, any verification mismatch, any
`unknown` outcome, and any guardrail change. So the default is not "on at install" — it is
**on unless recently and deliberately disarmed**. Walking away from the desk re-arms it.

**5.6 Credentials.** Windows Credential Manager via `ctypes` → `advapi32` (preferred over
a raw DPAPI blob because the OS gives a UI to inspect and revoke, and revocability matters
more than blob simplicity), DPAPI as the documented fallback. Both are `ctypes` against
system DLLs — **no new dependency**. A sentinel-credential test exercises every route and
greps every response body.

**5.7 Charts.** TradingView Advanced Chart widget, overlaid with entry markers, cost-basis
line and open-order levels; a user-controlled trade/chart split with a persisted ratio.
**The ticket's price inputs never come from the iframe** — it is cross-origin, a display
surface, and reading a number out of it is neither reliable nor auditable. Prices come
from the provider or are typed, and the ticket records which.

**5.8 Build against paper execution first.** An `ExecutionVenue` interface with an
**Alpaca paper** adapter: free, a real order lifecycle, no ToS exposure, and it exercises
read-back, guardrails, idempotency, the kill switch and the audit record end-to-end with
no money and no Fidelity contact. Fidelity becomes one adapter behind an interface that
already has a proven consumer. This is not a hedge on the decision — it is how you get the
first live order right.

**5.9 ToS and financial risk — the recorded decision, stated once.**

> Automating Fidelity's web UI is contrary to their terms of service. Fidelity may detect
> it and may restrict or close the account. It will break without notice when the UI
> changes. A defect here spends real money, and **unlike every other write path in this
> project, the transaction cannot be reversed by writing the old value back.**
>
> ADR-0019 records that this was chosen over the recommended read-only option. That
> decision stands and is not reopened. The ADR records the mitigations as **non-optional**:
> dry-run default, kill switch on by default, typed confirmation. This plan adds
> read-back verification and server-side guardrails as mandatory rather than optional.

---

### Phase 6 — Remote access

**6.1 Run `tailscaled` inside WSL**, userspace networking, with `tailscale serve`:

```bash
tailscaled --tun=userspace-networking --state=/var/lib/tailscale/tailscaled.state
tailscale up --hostname=agentmux
tailscale serve --bg --https=443 http://127.0.0.1:8787
```

Why here rather than on Windows: **the tailnet boundary and the API boundary become the
same boundary** — nothing crosses hosts to serve a remote request, and the funnel guard
runs in the same process tree as the thing it guards. The **Windows host's networking is
untouched**, which on a machine that talks to live equipment matters. Userspace mode is
sufficient; what it costs is subnet routing and exit-node behaviour, neither of which is
wanted. *Rejected `netsh portproxy`*: WSL's eth0 changes every boot, so an invisible
forwarder would need rewriting at startup and fails silently in front of an API whose
authentication is the thing under test.

**6.2 The API keeps binding loopback.** With `serve`, Tailscale terminates TLS on the
tailnet address and proxies to `127.0.0.1` — so there is **exactly one listener on the
tailnet and it is Tailscale's**, which already checks node identity before a byte reaches
us. This is strictly better than "bind loopback plus the tailnet interface", and the phase
goal should be restated that way.

**6.3 `allowed_origins()` is the premise this phase invalidates.** Over `serve` the
browser's `Origin` is `https://agentmux.<tailnet>.ts.net` — different scheme, host and
port — so the existing derivation returns the wrong answer and **every mutating request
from the phone is rejected as a forbidden origin.** The replacement is an explicit
three-entry list whose third element, `serveOrigin`, is resolved **at boot from the local
Tailscale daemon, never from the request**, and is absent when serve is unconfigured.
**Port the doc-comment's reasoning forward, not just the code** — its actual point is
*derive the guard from what the server really is*, and what the server really is now has
two faces. Losing that reasoning would be the worst outcome of this phase; someone would
read the extension as a weakening and delete it.

**6.4 Auth parity, and strip the identity headers.** Same session, CSRF, expiry and
lockout on the tailnet as on loopback; a test asserts the middleware has **no
origin-conditional branch**. **Strip `Tailscale-User-*` unconditionally at the first
hook**: `serve` injects them, but it connects over loopback, so the API cannot distinguish
a serve-proxied request from a direct local one by socket alone and a local client could
forge them. Stripping eliminates the forgery class at the cost of tailnet identity in the
audit record — the right trade for v1. If that identity is wanted later, the safe way is a
**second loopback listener that only `serve` proxies to**, with a per-listener trust flag —
not trusting a header on the shared one.

**6.5 The funnel guard — detection is not prevention.** Two controls, only one of which is
a control. **Prevention:** remove the funnel node attribute in the tailnet policy file — a
node without it cannot enable Funnel at all. **Detection:** at boot, refuse on **any**
funnel config for this node (not merely one on the API port — Funnel on 443 with a path
prefix still reaches the API), **and re-check on a 60 s timer**, exiting non-zero on
detection. A funnel enabled at 3pm is exactly the event a boot-only guard sleeps through.

**6.6 The Windows services are never exposed.** `tailscale serve status --json` is parsed
at boot and any handler targeting 8788, 8789 or 8790 is a **boot failure**, not a warning.

---

## 6. Risk register

| # | Risk | Mitigation | Phase |
|---|---|---|---|
| R1 | **WSL→Windows unreachable** — no `.wslconfig`, NAT mode | Mirrored networking as a startup-asserted prerequisite; pre-designed fallback, honestly labelled | 1 |
| R2 | **Repo rename bricks every task-store entity** — and the `boardId` pin does not stop it, since git wins at `store.mjs:753-757` | Don't rename the GitHub repo (the rebrand doesn't need it); if it is renamed, rewrite `board:` across every doc in the same change. The pin makes the mismatch *detectable* (`drifted: true`) rather than an unexplained refusal | 0 |
| R3 | **`ccc.*` storage rename wipes operator state** | Read-through migration; theme *values* untouched | 0 |
| R4 | **Agent-file rename breaks orchestration silently** | `ORCH_DEFAULT_AGENT` in the same commit as the `git mv` | 0 |
| R5 | **Cross-namespace lock breaking corrupts the store** — `process.kill(pid,0)` across the boundary | All writes through `agentmux-board` on Windows; the API reads only | 1 |
| R6 | Proxied writes 403 on Origin | Strip `Origin` on forward; `X-Forwarded-Origin` for the record | 1 |
| R7 | Node unreachable in WSL despite nvm | Pin an absolute path; `prestart` refuses a `/mnt/c` node | 1 |
| R8 | **The API becomes a second orchestrator by inheriting an environment** | Single chokepoint, clean env, `AGENTMUX_AGENT=blade`, guards G2/G4 | 2 |
| R9 | **`canUseTool` silently skipped by an allow rule** — the documented trap | Enforcement in `PreToolUse`, never the callback; no `write_tools` name may appear in any mode's allow list, schema-enforced | 2 |
| R10 | API key leaks into a spawned pane | In memory only, injected via the SDK `env`; the chokepoint deletes it from every child env; **never `~/.agentmux/env`**, which is sourced into every pane | 2 |
| R11 | `fs.watch` ships and never fires on 9p | Poll on 9p, watch on ext4, chosen by a boot probe; `/api/modes` reports which | 2 |
| R12 | **MCP names resolve to the wrong server, silently** | Host-aware registry + Windows bridge; `/api/modes` reports each server's host and a live `tools/list` digest | 2 |
| R13 | Six-connection cap returns | One module-singleton bus; a Playwright test counts `text/event-stream` under strict-mode double-mount | 3 |
| R14 | Terminal re-creation destroys scrollback; fit oscillation returns | `useRef` island, route never unmounted, debounce to `transitionend`, the `stable` assertion in the ported fit matrix | 3 |
| R15 | Nine shell tests die with the old UI | Per-view replacement in the same commit, enforced by `MIGRATED_VIEWS` | 3 |
| R16 | **Value age computed across two or three clocks** | `ageMs` and `stale` authored at the source; render-invariant test; a test that fakes a 10-minute client skew and requires unchanged verdicts | 4 |
| R17 | **pycomm3 opens an unaudited write path** | Five layers, of which the real one is: no raw-CIP route in the sidecar. Whitelist + ordering + fail-closed tests | 4 |
| R18 | OPC UA never becomes available | Strictly optional feed; AC requires a working tag table with zero endpoints | 4 |
| R19 | Two sources disagree about one point | Two rows, linked, disagreement highlighted. No averaging, no fresher-wins | 4 |
| R20 | **Financial data committed to a public repo** | Everything outside the tree; `check_no_financial_artifacts.sh` in the suite | 5 |
| R21 | Fidelity UI change breaks orders silently | Selector registry with probes; drift → capture + arm + alert; **never a fallback locator** | 5 |
| R22 | A defect places a real trade | Two independent gates; local dry-run default; server-side guardrails; paper venue first | 5 |
| R23 | Order submitted, outcome unknown | Intent before the click with an idempotency key; read-back; **no auto-retry, no auto-cancel** | 5 |
| R24 | Brokerage account locked by a retry loop | Two failures → `LOCKED`, manual clear; no automated password retry anywhere | 5 |
| R25 | **`allowed_origins()`'s premise silently invalidated** → every remote write fails, or the guard gets deleted to "fix" it | Explicit allowlist with `serveOrigin` at boot; the reasoning carried forward and reviewed | 6 |
| R26 | Funnel enabled after boot | Policy-file prevention **plus** a 60 s re-check that exits | 6 |
| R27 | `Tailscale-User-*` forged over loopback | Stripped unconditionally; never used for authorization | 6 |
| R28 | Mirrored mode breaks VPN or Docker Desktop | Timeboxed spike first; documented, exercised rollback | 1 |
| R29 | **9p EIO under gate load — confirmed live, not theoretical.** `netscan.py:257` called `Path(candidate).exists()` on `/mnt/c/Windows/System32/ARP.EXE`; `Path.exists()` re-raises any errno that is not ENOENT/ENOTDIR/EBADF/ELOOP, so a 9p stat under load raised `OSError: [Errno 5]` out of a function documented "Never fatal" and killed whole scans — 3 of 6 e2e runs. Fixed, 0 of 6 after | Gate runs from an ext4 clone. **And: never call `Path.exists()` on a `/mnt/c` path without a try/except** — treat every 9p filesystem call as able to raise | all |

---

## 7. The four open questions, answered

**Q1 — Market data.** A `MarketDataProvider` interface with two adapters and one named
rejection. Any method may return `NotSupported`, and the UI renders *"not available from
<provider>"* — **a missing number must look missing**. **Alpaca free tier** is primary, and
the reason is execution, not data: its **paper-trading API** is the legitimate venue for
§5.8. **Polygon.io Options Starter** when options chains are actually needed; until then
`getOptionChain` returns `NotSupported`. Fundamentals and news deferred. **Reject
yfinance/Yahoo scraping** — the project is already carrying ToS risk at Fidelity, and a
second unofficial scrape multiplies fragility for no capability gain.

**Q2 — Tax lots.** **No independent tracking in v1.** Fidelity is books-and-records; its
basis is what appears on the 1099-B including wash-sale adjustments across the whole
account. A second computed basis would eventually disagree with the tax form, would be an
attractive but wrong number to size from, and pulls the project into wash sales, corporate
actions and specific identification — a product, not a feature. **Mirror Fidelity's
position-level basis and unrealized P/L**, which sizing genuinely needs, and **link to**
its lot-selection UI rather than reimplementing it. ADR-0025. **Revisit trigger:** trading
the same symbol repeatedly inside 30 days.

**Q3 — Research artifacts.** Reuse the existing tree, add a gitignored sibling, and carve
out finance entirely. Finished packs stay at
`.bytedesk/task-management/research/<date>-<slug>.md` — the existing `enhance-research`
skill already writes exactly that, so no second vocabulary. **Durable session state** goes
to `research/sessions/<id>/`, **gitignored**, following the reasoning already written in
that `.gitignore` for `planner/`: *"one machine's unfinished thinking."* **Source capture
stores the bytes, not just the URL** — `{url, fetchedAt, sha256, contentType, storedAs}`
with the response on disk, because a URL alone is not source capture: the page changes and
the citation quietly becomes a claim about a document that no longer exists. **Financial
research does not go here at all** (§5.0).

**Q4 — Rename `cc.db`.** **Yes, to `agentmux.db`** — but the **data file only, not the
modules**, and in Phase 1 alongside the store migration so one script handles shape and
name together. "cc" is the last load-bearing trace of the old name on a path **the product
creates on every fresh install**; ADR-0017 scoped the rebrand to live surfaces, and a file
manufactured on a new machine in 2027 is a live surface. The cost is bounded:
`ccstore.py:30` is the single definition and `*.db` is gitignored. Name it generically
because the board is leaving and what remains is not a board. **Migration is
copy-verify-keep**: open both, use the SQLite backup API, `PRAGMA integrity_check`, and
only on `ok` rename the original to `cc.db.migrated-<date>` — never delete the operator's
only copy. **Do not rename `ccstore.py`/`ccboard.py` in the same change**: ~10 files import
them, half those tables are about to retire, and churning every import in the commit that
migrates the data doubles the blast radius of a bad afternoon.

---

## 8. Verification

```bash
# ---- Environment prerequisites -------------------------------------------
powershell -c "Get-Content $env:USERPROFILE\.wslconfig"        # networkingMode=mirrored
powershell -c "Start-Job { python -m http.server 9999 --bind 127.0.0.1 }"
wsl.exe -e curl -sf http://127.0.0.1:9999/ && echo "WSL -> Windows loopback OK"
wsl.exe -d Ubuntu -e bash -lc '$AGENTMUX_NODE -v'              # v24.x, NOT from /mnt/c

# ---- Phase 0 --------------------------------------------------------------
# (the two greps and run_tests.sh from the Phase 0 acceptance block, from an ext4 clone)
bash <(tr -d '\r' < dashboard/capture_docs.sh)                 # 5 PNGs, manual review

# ---- Phase 1 --------------------------------------------------------------
python3 field/app.py --print-key
curl -sf -H "X-AgentMux-Field-Key: $(cat ~/.agentmux/field.key)" \
     http://127.0.0.1:8788/health | python3 -m json.tool
node -e 'const{DatabaseSync}=require("node:sqlite");const d=new DatabaseSync(process.env.HOME+"/.agentmux/cc.db");
         console.log(d.prepare("PRAGMA user_version").get(), d.prepare("PRAGMA journal_mode").get())'
npm run differ -- --record --corpus tools/differ/corpus/$(date +%F).jsonl
npm run differ -- --replay --all                               # 0 diffs
npm run differ -- --sse --seconds 20                           # 0 frame diffs
TM_ROOT=/tmp/tm-dry node tools/migrate/ccdb-to-tm.mjs --dry-run --report
node tools/migrate/verify.mjs          # 23 epics -> 22 + 1 merge; 93 tasks; 254 AC; 77 evidence
node tools/migrate/ccdb-to-tm.mjs      # second run: "0 created, 117 skipped"

# THE inbound path — easiest to break silently
wsl.exe -d Ubuntu -e bash -lc \
  'cd /mnt/c/Dev/agentmux && python3 taskmgmt/coordination.py journal note "gate check"'
curl -s localhost:8787/api/journal | jq '.[0]'

# ---- Phase 2: the four decisive tests -------------------------------------
npm run -w packages/api test -- guard
#   G5 WITH THREE LIVE CLAIMS HELD BY OTHERS -> BOOTS, reports, does NOT decline
#   (the regression test for the draft's broken guard)
npm run -w packages/api test -- hooks.dangerous
#   mcp__modbus__write_register denied with the tool BARE in allowedTools
#   AND permissionMode 'bypassPermissions' -> must STILL be denied
npm run -w packages/api test -- confirm
#   expired 409 | wrong phrase 400 | MUTATED paramsHash 409 | kill switch 423 | one-shot
npm run -w packages/api test -- orchestrator
#   dispatch without a token refused BY agentmux.sh's own message;
#   ANTHROPIC_API_KEY absent from every child env

# ---- Phase 3 --------------------------------------------------------------
npx playwright test e2e/fit-matrix.spec.ts        # legible/capped/STABLE/crisp/predicted
npx playwright test e2e/sse-single.spec.ts        # exactly one text/event-stream
npx playwright test e2e/terminals-scroll.spec.ts  # scrollTop across view switch + pin/unpin
diff <(curl -s localhost:8787/api/board | jq -S .) \
     <(node .bytedesk/task-management/bin/tm export json | jq -S .)

# ---- Phase 4 --------------------------------------------------------------
bash dashboard/check_field_writes.sh    # rockwell.py is the sole pycomm3 importer
bash dashboard/check_vendor.sh          # hashes, no binaries, licences
python3 -c "import sys; sys.path=[p for p in sys.path if 'site-packages' not in p]; \
            sys.path.insert(0,'field/vendor'); import pycomm3; print(pycomm3.__file__)"
npm --prefix packages/api test -- tagTable.skew.test.ts   # 10-min client skew changes nothing
npm --prefix packages/web test -- TagRow.age-invariant.test.tsx

# ---- Phase 5: three independent proofs that a dry run submits nothing -----
pytest agentmux-broker/test_dryrun.py::test_local_dryrun_makes_no_browser_calls
#   Playwright double counts EVERY attribute access; assert counter == 0
pytest agentmux-broker/test_dryrun.py::test_preview_never_clicks_place
#   patched Locator.click RAISES if the locator equals selectors['order.placeButton']
#   -> the test fails if it ever happens; it cannot pass by accident
pytest agentmux-broker/test_dryrun.py::test_journal_has_dry_run_and_no_intent

pytest agentmux-broker/test_killswitch.py::test_broker_side_check_is_authoritative
#   API check stubbed to ALLOW -> the broker must still refuse
pytest agentmux-broker/test_killswitch.py -k "rearm_on_"
bash check_no_financial_artifacts.sh
git ls-files | grep -iE 'broker-orders|SUBMIT_DISABLED|positions\.json' && echo FAIL || echo clean

# ---- Phase 6 --------------------------------------------------------------
wsl.exe -e tailscale serve status --json | jq '.'      # exactly one handler -> 8787
bash check_serve_targets.sh                            # fails if 8788/8789/8790 is a target
wsl.exe -e tailscale funnel 443 on; wsl.exe -e node packages/api/dist/main.js; echo "exit=$?"
wsl.exe -e tailscale funnel 443 off                    # expect non-zero + the named config
curl -sk -o /dev/null -w '%{http_code}\n' https://agentmux.<tailnet>.ts.net/api/field/tags  # 401
# from OFF the tailnet:
curl -sv --max-time 5 https://agentmux.<tailnet>.ts.net/ ; nmap -Pn -p 8787-8790 <lan-ip>
```

---

## 9. What has actually been built — session of 2026-09-25

Branch `phase-0-rebrand`. Gate: **all suites passed**, 2,055 assertions across 55
suites, from an ext4 clone. Baseline before any of this was **2 suites failing**.

### Bugs found and fixed

All pre-existing. Listed because the pattern matters more than the individual fixes:
**every one of them made the gate say something untrue**, which is the failure mode that
compounds as features land on top.

| | Bug | Why it mattered |
|---|---|---|
| **TM-012** | `test_frontend_post.sh` had no nvm discovery (exit 127, zero assertions); `test_frontend.sh` **silently skipped** its `node --check app.js` and still reported "passed 12, failed 0" | A green gate while a real check never ran — during a phase that rewrites `app.js` heavily. 12 → 13 assertions is the proof it runs |
| **TM-013** | The e2e scanner failed **3 of 6 runs** with a bare `OSError` | A ~60% flake makes "all suites passed" a matter of luck. Root cause: `Path.exists()` re-raises EIO, out of a function documented "Never fatal". **0 of 6** after |
| **TM-014** | Seven python suites counted a skip as a pass — and so did the **gate**, via `0:OK *` matching `OK (skipped=1)` | Three instances of one defect family. Latent, but four sibling suites already had it right |
| **TM-015** | `test_launch.sh` failed its *teardown*, not its assertions, only under load | The shape that teaches people to re-run the gate until it goes green |
| **TM-016** | The failability meta-gate **could not accept a python suite at all** | It covered 5 of 54 suites. Both Phase 0 regression tests are now standing guarantees rather than one-off manual proofs |
| **TM-017** | The SSE slot-exhaustion guard has no automated test | Filed, not fixed — it belongs in Phase 3's Playwright work (R13) |
| **TM-019** | The 9p SQLite justification did not survive measurement | See §3.2a. The decision stands on other grounds; the reason was wrong |

### Built beyond the task list

- `scripts/node-env.sh` — resolves nvm's Node, refuses the `/mnt/c` one, discovers
  `TM_PLUGIN_ROOT`. `bin/tm` now runs from WSL, which it could not at all.
- `field/app.py` + 13 tests — the sidecar shell, verified on **both** hosts.
- `dashboard/capture_docs.{sh,mjs}` — repeatable doc screenshots via the existing e2e
  harness, deliberately out of `run_tests.sh`.
- `docs/wsl-networking.md` — the measured NAT facts, the procedure, the rollback.

### Corrections to this plan, made while doing the work

Four claims in this document turned out to be wrong and are fixed in place: the
`boardId` pin does not survive a repo rename; `mqtt_monitor.py` vendors paho rather
than pip-installing it; the `enip`/`logix` write posture is *thoroughly* tested already;
and SQLite over 9p is not the hazard the host split was justified with.

---


---

### Phase 4 — later the same day

Gate: **all suites passed**, 2,176 assertions across 64 suites, from the ext4 clone.
Phases 4.1 through 4.4 are done; 4.5 (node-opcua) waits on Phases 1-3, and 4.7 (the
merged device tree) is not started.

| | What | Why it mattered |
|---|---|---|
| **TM-025** | The panel computed value age as `Date.now()/1000 - last_good` — a browser clock minus a server one — and rendered a *clock reading* rather than an age | The age is the one number on this panel that must not be wrong, and one computed across two clocks is worse than none: it still looks authoritative. `age_ms` is now measured at the source; the client adds only monotonic elapsed time |
| **TM-026** | **Three** write journals, not the two this plan surveyed. `ads.py` kept its own, and nothing pointed at it | Unified into `writejournal.py`. A census test now fails when a client that writes to equipment does not journal through it — so a fourth cannot start quietly the way the third did |
| **TM-027** | The gate gave two different verdicts on two adjacent commits. Three suites read `/mnt/c` and hit 9p EIO; one reported `passed -1` | A gate that flakes is a gate that gets re-run until it goes green. `ninep.py` keeps "not there" and "could not find out" apart, and the runner no longer prints a count that cannot be true |
| **TM-028** | pycomm3 vendored and wrapped | Closes exactly the gaps `logix.py` names in its own docstring. `check_vendor.sh` verifies the bytes **offline**, because the boxes this policy exists for cannot reach PyPI |
| **TM-029** | The sidecar's first write route, and the ticket that had to exist first | The route cannot say *what* to write. A replayed request can only redo a write that was already authorised, once |
| **TM-030** | Four different faults printed the same word, and one stale tag greyed forty chips | Forty chips greying at once is one connectivity fact rendered forty times, which teaches the operator that the chips mean nothing |

Also: `test_mqtt_monitor.py` for the largest protocol module — scoped to what
`test_field_panels.py` does **not** already cover, and proved by **mutation** rather
than by `check_test_failability`, because it passes against every version of that
module in the repo's history and inventing a base would make the gate say something
untrue.

### Four more corrections to this plan, from doing the work

1. **Three write journals, not two** (§1.3.8). `ads.py:85` was missed.
2. **`text eol=lf` was the wrong pin for vendored code.** pycomm3 ships one file with
   CRLF; normalising it broke the hash that pins the dependency. Vendored bytes are
   `-text`. The repo now has both forms, and the distinction is written down: one makes
   a file *parseable*, the other makes it *identical*.
3. **The audit journal must honour `AGENTMUX_HOME`.** It did not, so a suite run left
   21 rows in the operator's real `field-writes.jsonl`. `ccstore.py:17-21` records this
   exact bug being found once already.
4. **A Modbus device exception was being recorded as `unknown`.** It is a refusal: the
   device said so and nothing changed. Every time `unknown` is used for something known,
   it means less.

### Three of my own mistakes, recorded because the shape repeats

Each one made a test pass while checking less, which is the failure mode this project
is least able to detect:

- A check for `generic_message` **grepped** the source, and every file that matters
  mentions it in prose — explaining why the escape hatch is closed is what those
  docstrings are for. Rewritten to parse.
- `Path.home()` replacing a hardcoded `/home/nick` looked like a plain improvement, but
  `setUp` relocates `HOME` into a fixture — so the check would have validated the files
  it had just written itself, and passed.
- `field/vendor/** text eol=lf`, added to protect the manifest, was the thing that broke
  it.


## 10. How this gets executed

Three pieces of bookkeeping first, or the board will lie about what is happening.

1. **Open a dedicated epic.** The rewrite has none, `requireEpic: true` is set, and
   `EP-001`'s single `plan:` pointer is rotating between four plans while its `.bytedesk`
   title describes work `cc.db` records as done.
2. **Resolve the `EP-nnn` and `ADR-nnnn` collisions before Phase 1.5**, not during it.
   Migration without re-keying silently merges unrelated work.
3. **Write the supersession links.** ADR-0023 supersedes ADR-0001 and ADR-0021 D3;
   ADR-0021 D2 already reverses ADR-0017 D3. All 23 ADRs are `proposed` with empty
   Consequences. An ADR trail that records only the first answer is worse than none.

`wipLimit` is 3 and `dispatch.enabled` is `false`. Turning the pool on is a separate
decision — the phases are written to work either way, but **Phase 1.3 wants a human
reading differ output**, not a worker closing cards on it.
