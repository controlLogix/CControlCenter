# agentmux

Drive other coding-agent CLIs (codex, claude, any REPL) from Claude Code, as
long-lived tmux panes you can also attach to and watch.

## Why this shape

tmux has no native Windows port. The only genuine native alternative is
WezTerm's mux (`wezterm cli send-text` / `get-text`), which would mean adopting
a whole terminal emulator with weak headless support. WSL Ubuntu 24.04 already
had tmux 3.4, so the harness runs there.

The agents run as **native Linux processes** in WSL, not Windows `.exe` files
through interop. A Windows console TUI inside a Linux pty has unreliable
redraws and key handling; a Linux binary in a Linux pty does not. The tradeoff
is that the WSL `codex` has its own `~/.codex` — separate login, separate
`config.toml`, separate MCP servers from the Windows install.

## Layout

The checkout directory goes on the **user** `PATH`, so `agentmux.cmd` is callable
from any shell. The harness and its audit history live together in one directory;
the WSL launcher and the `agentmux` skill are both pointed at it.

| Path | What |
| --- | --- |
| `agentmux.sh` | The harness. Canonical source. |
| `agentmux.cmd` | Windows entry point, on `PATH`. Forwards to WSL. |
| `install.sh` | Portable installer. Discovers the checkout, node and tmux at run time and generates `~/.local/bin/agentmux`. Assumes no username, distro, drive letter or node version. |
| `link-windows-state.sh` | Shares `~/.codex` and the claude config dir with the Windows installs. `--check` / `--apply` / `--revert`. Resolves `CLAUDE_CONFIG_DIR` rather than assuming `~/.claude`, and keeps the two path-bearing plugin files per-OS so sharing cannot break Windows plugins. |
| `ANALYSIS_2026-09-18.md` | What this is, how to use it, and the reliability caveats. **Read before trusting a relayed answer.** |
| `dashboard/` | **Controls Control Center (CCC)** — the operations console. `python3 dashboard/server.py`, then open 127.0.0.1:8787. See the table below. |
| `taskmgmt/` | Jira + Confluence, auth setup, and field tools. `atlassian.py` (REST client), `task.py` (CLI used by the harness and the dashboard reaper), `setup_atlassian.py` and `setup_auth.py` (non-echoing credential setup), `bootp_probe.py` (privileged, read-only BOOTP listener). |
| `~/.local/bin/agentmux` (WSL) | Launcher. Strips CRs at run time, so editing the `.sh` from Windows cannot break it. |
| `~/.agentmux/logs/<name>.log` (WSL) | Full scrollback per agent, via `pipe-pane`. |
| `~/.agentmux/run/<name>.*` (WSL) | Per-agent pane id, cli, cwd, start time. |
| `audit_2026-09-17/` | The 2026-09-17 hardening audit — workflow journals, reconstructed results, `FINAL_REPORT.md`, batch/argv probe scripts, and `*.baseline-run1` copies of the pre-audit files. |
| `wsl-agent-teams/` | Adjacent WSL2 + tmux agent-teams work: setup notes and the `~/.claude` symlink hardening journals. |

tmux runs on a dedicated server socket (`-L agentmux`), so it never collides
with an interactive tmux session.

## Authentication

Every CLI can be reached several ways, and which one is right is a property of the
machine rather than of agentmux. Methods are declared in `dashboard/auth.json` and
organised in **two levels**:

- **Providers** own their *shared* attributes. An AWS region and a Bedrock API key
  belong to Bedrock, not to each CLI that uses it, so configuring
  `--provider bedrock` once serves both codex and claude.
- **Methods** are one `(cli, provider)` pairing plus only what is specific to it —
  a model id, and for codex a gateway URL.

```
python3 taskmgmt/setup_auth.py --list                  # everything and its state
python3 taskmgmt/setup_auth.py --provider bedrock      # shared: region + API key
python3 taskmgmt/setup_auth.py codex-bedrock           # this method: gateway + model
python3 taskmgmt/setup_auth.py --verify codex-bedrock  # prove codex accepts it

agentmux spawn dev --cli codex --auth codex-bedrock    # or omit --auth for the default
```

| CLI | Methods |
| --- | --- |
| codex | ChatGPT OAuth (default), OpenAI API key, **AWS Bedrock**, any OpenAI-compatible endpoint |
| claude | Anthropic OAuth (default), Anthropic API key, **AWS Bedrock**, Google Vertex AI |
| grok | xAI device-code login (default), xAI API key |

### codex on Bedrock

**A gateway is mandatory, and one ships here.** Measured against a live key in
us-west-2:

| Endpoint | Result |
| --- | --- |
| `POST /openai/v1/chat/completions` | **200** — works |
| `POST /openai/v1/responses` | **404** *"model doesn't support this API"* |

codex 0.155.0 speaks only the Responses API — it rejects `wire_api = "chat"` outright.
So the two ends are one API generation apart, and `taskmgmt/bedrock_gateway.py` bridges
them: stdlib only, loopback only, Responses in, Bedrock Chat Completions out, with SSE
streaming translated both ways.

```
bash <(tr -d '\r' < dashboard/start_gateway.sh)          # gateway on 127.0.0.1:4000
bash <(tr -d '\r' < dashboard/setup_bedrock_codex.sh)    # configure codex-bedrock
agentmux spawn dev --cli codex --auth codex-bedrock
```

Verified working: the agent completes turns **and uses tools** — `Ran wc -l < README.md
→ 365`, a real tool call routed through Bedrock and back.

**The model is switchable** in Settings → Authentication. `dashboard/test_models.py` calls
every candidate through the gateway (streaming and not) and writes the ones that work to
`bedrock_models.json`; the dropdown offers only those. That matters because Bedrock has two
inference types and the id form differs:

| Form | Models |
| --- | --- |
| bare id (ON_DEMAND) | `openai.gpt-oss-120b-1:0`, `-20b-1:0`, `-safeguard-120b`, `-safeguard-20b` |
| `us.` prefix (INFERENCE_PROFILE) | `us.openai.gpt-6-astra`, `gpt-5.6-terra`, `-luna`, `-sol` |

All eight verified. A changed model applies to agents spawned from then on; a running agent
keeps the one it started with. `agentmux` passes it explicitly as `-m`, so switching it
never requires regenerating the codex profile, and `spawn --model X` still wins.

Two translations that are not obvious, and were both wrong first time:

- **codex groups tools under `{type:"namespace", tools:[…]}`**, which Chat Completions
  has no concept of. Dropping those groups left the agent with **no tools at all** — it
  could talk but not read a file. They are flattened, keeping each inner name exactly as
  declared, because codex matches the returned call by name. `tools=17` in the gateway
  log where it was 0. `web_search` is server-hosted and genuinely has no equivalent, so
  it is dropped *and logged*.
- **gpt-oss on Bedrock emits its chain of thought inline** as
  `<reasoning>…</reasoning>` in the message content rather than a separate field, so
  codex rendered it as the answer. Stripped with a state machine, not a regex, because a
  tag can be split across two streaming deltas.

A Bedrock API key is a bearer token, so no SigV4 signing is needed. The gateway binds
**127.0.0.1 only** — a process holding a cloud credential must not listen on a routable
address — and reads the key from its environment, never argv, never a log.

Claude Code needs no gateway: it speaks to Bedrock natively.

Where things live, and why:

| Path | Mode | Holds |
| --- | --- | --- |
| `dashboard/auth.json` | tracked | the manifest. No user, drive letter, region, model or URL — nothing machine-specific. |
| `~/.agentmux/auth.json` | 0600 | non-secret settings and the active method per CLI |
| `~/.agentmux/env` | 0600 | **secrets only** |

Secrets are entered with `getpass`: never echoed, never a command argument, never
printed back to confirm. agentmux *sources* the env file into each pane instead of
interpolating it into the tmux command, so a key never appears in `ps`, in
`pane_start_command`, or in shell history. The dashboard may read the settings file
and display it; it reads the env file only for variable **names**, and reports a
secret as `set` or `not set` — never a value, a length, or a prefix.

Selecting a method is possible from Settings → Authentication. **Entering a
credential is not**: those commands are shown with a "your terminal" tag and the
server never runs them.

## Controls Control Center (`dashboard/`)

Python 3 **stdlib only**, bound to **127.0.0.1 only**. A left activity bar
switches seven views: Terminals, Message Queue, Task Board, Journal, Ticket
Reviewer, IIOT Field, Settings.

The Ticket Reviewer reads real Jira issues and can comment on or transition them.
Those two endpoints are the only ones that write to a system outside this machine,
so the UI confirms first and there is deliberately **no dry-run mode** on them — a
client-supplied "pretend" flag reintroduces the did-it-actually-happen ambiguity
this codebase has already been bitten by three times. Until Atlassian is
configured the view says so and shows the setup commands, rather than rendering an
empty list that reads as "no tickets".

| Path | What |
| --- | --- |
| `server.py` | HTTP + SSE. Routing, the static allowlist, agent metadata, the resource probe engine, the Jira reaper, the Control Center and MQTT endpoints. |
| `ccstore.py` | SQLite store at `~/.agentmux/cc.db` — epics, tasks, journal, messages, devices. WAL, `foreign_keys` on, a new connection per request (the server is threaded). |
| `mqtt.py` | Minimal MQTT 3.1.1 client on stdlib sockets: CONNECT, PUBLISH QoS 0, a bounded SUBSCRIBE poll. **No TLS and no credentials** — deliberately, since no secret may travel from the browser. |
| `index.html` / `app.js` / `style.css` | The console. Terminals are read-only: the page never sends a keystroke to an agent and cannot spawn or kill one. |
| `themes.json` | **Theme manifest.** Adding a theme is a data change here — no CSS and no JS. Applied by writing tokens onto `documentElement`, so there is no stylesheet swap and no flash. |
| `resources.json` | **Resource manifest** driving the Resources section of Settings. Adding an MCP server, a CLI or an addon is a data change here. The backend runs only the probes it declares; a request can name an id but never supply a command. |
| `SPEC_CC.md` | The Control Center contract: roles, brand, schema, and what "done" means. |
| `auth.json` | **Auth manifest** — providers and their shared attributes, plus one method per `(cli, provider)` pairing. See Authentication above. |
| `fitmatrix.js` | Readability matrix for the terminal grid. Loaded only with `?fit=1`. See Terminal text fitting below. |
| `smoke.sh` | 79 checks: static allowlist, endpoint guards, traversal, theme consistency, body caps, the full status vocabularies, delete + cascade, DB round-trips. |
| `test_mqtt.py` | 56 checks: MQTT framing against a stub broker started in-process, the concurrency cap, and the BOOTP parser. |
| `test_gateway.py` | 31 checks: namespace flattening, message/tool translation, and the reasoning filter including tags split across deltas. No network. |
| `test_models.py` | Calls every candidate Bedrock model through the gateway and records which id form works. Writes `bedrock_models.json`, the source for the model picker. |
| `test_snapshot.py` | 18 checks: the SSE snapshot is CRLF-framed with autowrap disabled, asserted on the bytes the server sends. Guards the staircase bug. |
| `test_tickets.py` | 48 checks: Jira request shaping via `atlassian.py`'s dry-run (Cloud v3 vs Server v2, ADF bodies), the not-configured path, and the write-endpoint guards. **No live Jira call.** |
| `test_auth.py` | 54 checks: provider/method configuration in an isolated HOME, codex accepting the generated profile, and that no secret reaches the API. |
| `restart.sh` | Restart the server; `--fresh-db` drops `cc.db` first. |
| `seed_queue.py` | Writes sample agent traffic into `~/.agentmux/queue/` for exercising the Message Queue view. |
| `show_auth.py` | Prints `/api/auth` as a tree. Debugging aid for the auth grouping. |
| `run_tests.sh` | Restarts the server and runs every suite; non-zero if any fails. |
| `syntax_check.sh` | Parses every shell and Python file in the repo. |
| `start_gateway.sh` / `setup_bedrock_codex.sh` | Bring up the Bedrock gateway; configure `codex-bedrock`. |
| `check_key_exposure.sh` | Reports every location holding a Bedrock key, by fingerprint — never the value. |
| `test_stream_slots.sh` | Proves the SSE slot pool cannot be exhausted by repeated page loads. |
| `verify_model_switch.sh` | Proves the model chosen in Settings reaches a newly spawned agent. |
| `purge_test_rows.py` | Removes rows the suites leave in `cc.db`. Exact-name matches only; never touches the journal. |

Run both suites (from the repo root, inside WSL):

```
bash <(tr -d '\r' < dashboard/restart.sh)
bash <(tr -d '\r' < dashboard/smoke.sh)     # 54
python3 dashboard/test_mqtt.py              # 56
python3 dashboard/test_auth.py              # 54
```

### The snapshot must be CRLF-framed

When a stream opens, the backend sends the pane's current rendered screen from
`tmux capture-pane -p -e` before any log bytes — a mid-stream byte tail cannot
reconstruct alternate-screen state, so this is what makes TUI agents render at all.

`capture-pane` separates pane rows with a **bare LF**. A terminal treats LF as "down
one row", not "down one row and back to column 1" — CR does that. These terminals use
`convertEol: false` deliberately, because the live log stream carries real CRLF from
the agent and converting it would corrupt that. The result was that every snapshot row
started at whatever column the previous row ended on: a staircase, with long lines
running off the right edge, wrapping, and leaving orphan tails like `ng to read` down
the left margin. It looked like an intermittent streaming fault, because appended log
bytes always rendered correctly.

`framed_snapshot()` in `server.py` normalises to CRLF and disables autowrap (`ESC[?7l`)
around the payload, restoring it afterwards for the live output that follows. Autowrap
matters because `capture-pane` emits exactly one line per pane row: a row reaching the
last column would otherwise wrap and push every later row down, dropping the last rows
off the bottom.

Two consequences worth keeping in mind:

- **A geometry change re-snapshots.** `term.resize()` alone makes xterm reflow the
  buffer it already holds, re-wrapping text that tmux wrapped at a different width and
  splitting lines irrecoverably. tmux's screen is the authority, so the stale buffer is
  discarded and a fresh capture requested (debounced, since a drag emits a burst).
- `test_snapshot.py` asserts the framing on the bytes the server sends, so it holds
  regardless of browser behaviour.

### Free placement — static panes you arrange yourself

`LAYOUT: free — drag to place` hands the arrangement to you. Panes are absolutely
positioned, dragged by their header, sized by the bottom-right grip, and the placement is
remembered across reloads.

**A window resize never moves them.** That is the point: the chrome reshapes and the text
stays readable, but a layout you arranged by hand is not reshuffled underneath you. The
`sort` button is the only thing that rearranges, and it only runs when you press it. A pane
parked beyond a now-smaller window stays reachable — the canvas scrolls to it rather than
yanking it back.

Verified across 1500x940 → 2000x1250 → 880x600 with seven hand-placed panes: every
position and size byte-identical, fonts unchanged, all seven streaming.

Two things this needs that are easy to undo by accident: `applyLayoutPrefs` must not clear
cell heights in free mode (they are part of the placement), and `applyContentHeight` must
yield to it ('fit content' would otherwise override a hand-sized pane). And the canvas
extent comes from a **spacer element**, not `min-width` on the grid — a min-width makes the
scroll container's own box that wide, defeating its `overflow: auto`, and a pane past the
edge then becomes unreachable.

### One connection for every pane

A browser allows only about six concurrent HTTP/1.1 connections per host — six in Firefox
by default — and an SSE stream holds one open for its lifetime. With seven panes the
seventh could never connect, so two panes traded places about once a second, each showing
"disconnected — retrying" half the time. The two alternated perfectly complementarily,
which is what identified it: a *global* resource, not a per-agent fault.

`/api/stream-all` multiplexes every agent over one connection, tagging each frame:

```
event: snapshot   data: {"agent": "build", "b64": "..."}
event: chunk      data: {"agent": "build", "b64": "..."}
event: gone       data: {"agent": "build"}
```

Verified: 7/7 streaming, **0 flaps in 16s, one connection**. The per-agent endpoint is kept
— it is what `test_snapshot.py` exercises and is still right for a single pane.

Slots are also bounded per agent now. A reload opens a fresh EventSource per pane while the
old ones are still established, and the server cannot tell a client has gone until it next
writes; seven panes over two reloads exhausted all sixteen slots and three panes sat at
HTTP 503 rendering nothing — indistinguishable from a dead agent. Each agent now holds at
most one stream, so the ceiling is the agent count, not the reload count.
`test_stream_slots.sh` proves 28 opens across 7 agents leaves every stream available.

### Interface scale, and responsiveness

`UI 100%` in the title bar scales the **chrome** — bars, headers, panels — via
`--ui-scale`. Terminal text is deliberately excluded: a page-wide zoom cancels itself
out, because zoom shrinks the CSS-pixel width a cell reports (709 → 459 at 1.5), so
auto-fit picks a proportionally smaller font and zoom scales it back to the same visual
size, costing columns for nothing. Terminal text has exactly one owner: the ribbon's
text controls.

The layout also degrades rather than clipping: under 900px the activity bar drops to
icons and the ribbon's labels go; under 680px the brand collapses to the badge; on a
short window the ribbon scrolls; and below 420px tall the whole shell scrolls. A cell
never renders smaller than `MIN_USEFUL_CELL` (130px) — five agents in a short window
used to get ~17px of terminal each, one row of text, which reads as an idle agent
rather than a cramped one. Below that floor the grid scrolls instead.

### Terminal text fitting

A terminal is built at the **agent's** geometry (200x49 is typical) and must never be
resized away from it: TUI agents emit absolute cursor addressing — one grok log has
12,460 `ESC[row;colH` moves — and any other grid scrambles the screen. So a
200-column pane has to be displayed inside a cell that might be 300px wide.

The first implementation applied a CSS `scale()` transform. That resamples
already-rendered glyphs, so at three or more columns the text was not merely small, it
was blurry mush. **The fix is to size the font, not transform the pixels**: xterm
re-renders at whatever size it is given, so glyphs stay crisp while the grid stays
200x49.

**One control sets the size.** `Text` in the ribbon is either `auto` — fit the whole
pane into the cell, never below `min` — or an explicit size, used exactly, with the cell
scrolling to reach the rest. `min` is greyed out unless `Text` is `auto`, because it
means nothing otherwise.

That replaced three controls (a max, a min, and an auto/fixed mode) in which the one
labelled "max" did nothing in the default configuration: with a 200-column pane in a
709px cell the width-derived size is ~6.4px, so it always clamped up to the minimum and
the cap never bound. Changing "max font size" from 10 to 20 produced 7px either way,
while the control labelled "min" was the only real lever. A control that reads as the
font size must change the font size.

The guarantee, in every configuration:

- text is never smaller than the **legibility floor** (`min Npx` in the ribbon);
- if the whole pane cannot fit at the floor, the cell **scrolls** and the header says
  what fraction is visible (`7px · 57/98 cols`, amber) — a readable window on a pane
  beats an unreadable whole;
- when fitting every row would require illegible text, the height constraint is
  dropped rather than clamped: fewer rows at a readable size, and a scrollbar.

`auto` columns means the widest layout at which a whole pane still fits above the
floor, computed from the actual viewport — not the old hardcoded cap of 2.

Three things here are deliberate and easy to undo by accident:

1. **Metrics are measured from `.xterm-screen`, never `.xterm`.** `.xterm` fills its
   container, so its width is the *cell's* width; dividing that by columns yields "the
   width a character would need to fit", which is circular. `.xterm-screen` is sized by
   xterm to cols x rows cells, so it is the real grid.
2. **Never use `host.scrollWidth` to decide whether text is clipped.** It includes
   xterm's hidden IME textarea, which follows the cursor and can sit ~40px past the
   last character.
3. **Metrics are stored as ratios per 1px of font**, and the refinement loop is
   bounded and never revisits a size. Measuring at the current size to choose the next
   size is a feedback loop; four earlier attempts did that and every one ratcheted.

Run the matrix — 240 configurations (columns x row height x text mode x floor), all
asserted in a real browser:

```
open http://127.0.0.1:8787/?fit=1     # then, in the console:
await fitMatrix()                     # -> { configurations, paneChecks, failed: 0 }
await fitProbe('3', 'fill', 'fit', '7')   # one configuration, in numbers
```

Agents talk to each other by appending newline-delimited JSON to
`~/.agentmux/queue/<agent>.jsonl` (`{at, sender, recipient, kind, body, ref}`,
`kind` one of `plan|request|reply|status|finding|error`). The backend merges
those files with the `messages` table by timestamp; the orchestrator's plan is
just `kind: "plan"`, which is what lets the view pin it.

**BOOTP is not served here.** Binding UDP 67/68 needs root and this server runs
unprivileged, so the IIOT view names `taskmgmt/bootp_probe.py` instead of
pretending. That probe listens and reports only — it never answers a request,
because a second DHCP responder on a live plant network is an outage.

## Commands

```
agentmux spawn <name> [--cli codex|claude|shell|<cmd>] [--cwd DIR] [--model M]
agentmux send   <name> <text...>      type text + Enter
agentmux key    <name> <keys...>      tmux key names only, no text, no Enter
agentmux read   <name> [--lines N]    current pane, ANSI stripped
agentmux tail   <name> [--lines N]    full scrollback log
agentmux wait   <name> [--timeout S] [--quiet S]
agentmux ask    <name> <text...>      send -> wait for idle -> print pane
agentmux list
agentmux kill   <name> | --all
agentmux attach <name>                prints the command to watch it live
agentmux exec   <text...> [--cwd DIR] headless one-shot codex exec, no tmux
```

`--cwd` accepts Windows paths (`C:\path\to\repo`) and translates them.

### Permissions: unrestricted by default

Spawned `codex` and `claude` agents run with the provider's master permission
bypass. The posture is carried in each provider's own config, not as a CLI flag:

| CLI | Where it lives |
| --- | --- |
| codex | the `yolo` profile in `$CODEX_HOME/yolo.config.toml` (`approval_policy = "never"`, `sandbox_mode = "danger-full-access"`), used via `codex --profile yolo` |
| claude | `permissions.defaultMode: bypassPermissions` in a dedicated `CLAUDE_CONFIG_DIR` at `~/.agentmux/claude-config` |

`AGENTMUX_NO_BYPASS=1` spawns a sandboxed pane instead. `shell` and a bare
passthrough command string are never rewritten.

Two things this does **not** do:

- It does not suppress first-run or account-level modals. Measured: codex still
  shows its directory-trust dialog, and a rate-limit "switch model?" prompt with
  the *accept* option preselected. Use `key` for those — never `send`, which
  appends Enter and actuates whatever has focus.
- It does not reduce risk relative to passing the flags directly. Config is where
  the setting belongs, but the blast radius is the same — and if `~/.claude` and
  `~/.codex` are shared with a Windows install (see `link-windows-state.sh`), that
  radius includes the Windows profile.

The claude config dir deliberately drops `hooks` from the agent's copy: a shared
`settings.json` may carry SessionEnd hooks, and a spawned agent must not fire the
operator's cleanup on exit.

## The two modes

**`ask` / `spawn`** — interactive TUI in a pane. The agent keeps its context
across turns, and you can `attach` and watch or take over. Use for anything
conversational or long-running.

**`exec`** — headless `codex exec`, one shot, deterministic full output, no
tmux. Use when you want a clean machine-readable answer and no session state.

## Idle detection

`wait` and `ask` sample the pane every 1.5s, strip ANSI, and hash it. When the
hash is unchanged for 5s straight the agent is considered idle. Working agents
animate a spinner, so "unchanged" is a reliable busy/idle signal.

Tune per call with `--quiet S` / `--timeout S`, or globally with
`AGENTMUX_QUIET_MS`, `AGENTMUX_TIMEOUT_S`, `AGENTMUX_POLL_MS`.

Raise `--quiet` for agents that pause mid-thought (long tool calls); lower it
for snappy round-trips. A `timeout` exit is code 2, and the agent keeps
running — call `read` again later rather than re-asking.

## Examples

```bash
# a reviewer parked on the repo
agentmux spawn rev --cli codex --cwd C:\path\to\repo
agentmux ask rev "summarise what modbus-forge does" --timeout 180

# follow-up keeps the pane's context
agentmux ask rev "now list its external dependencies"

# watch it work
agentmux attach rev

# one-shot, no session
agentmux exec "list the POUs under my-project" --cwd C:\path\to\repo

agentmux kill --all
```

## Gotchas

- **Multi-line prompts** are sent with bracketed paste, so newlines do not
  submit early. Single-line prompts go literally.
- **`read` shows the viewport**, not history — TUI agents use the alternate
  screen, so scrolled-off output is not in `capture-pane`. Use `tail` for the
  full log.
- **Backslashes do not survive the Windows -> `wsl.exe` argv hand-off.**
  `agentmux.cmd` works around this: it re-quotes each argument and rewrites
  only drive-letter paths (`C:\x` -> `C:/x`), leaving prompt text alone. A
  prompt containing a double quote will still confuse batch — for anything
  elaborate, drive the harness from WSL directly:
  `wsl -d Ubuntu -- bash -lc 'agentmux ask rev "..."'`
- **Editing `agentmux.sh` from Windows** produces CRLF. The launcher strips CRs
  at run time, so this is handled — but do not invoke the `.sh` directly with
  `bash agentmux.sh`, go through `agentmux`.
- **WSL codex is a separate install** from the Windows one. `codex login` must
  be run once inside WSL; the Windows `~/.codex/config.toml` and its MCP servers
  do not apply.
- Files under `/mnt/c` are slower than the WSL filesystem. Fine for source
  trees, avoid for build output.

## Status and history

Start here when picking this up again:

- `STATUS_CCC_2026-09-20.md` — current state, open items, and the tooling traps
  that will otherwise be rediscovered the hard way
- `STATUS_CCC_2026-09-19.md` — the rebrand phase (theme system, seven views, store)
- `PENDING_USER_ACTION.md` — everything that needs the operator, urgency-ordered
- `RESUME.md` — the harness as of 2026-09-18; superseded for the dashboard
