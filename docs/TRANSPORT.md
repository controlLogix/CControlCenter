# agentmux terminal transport

Status: **implemented** (`hub/transport.py`, `hub/profiles.py`, `hub/deliver.py`), and
exercised by `hub/tests/test_hub_offline.py` and the live orchestrations in
`evals/orchestrations/`. This covers how a message physically reaches an agent CLI.
Naming, storage, routing and acknowledgment are in [`PROTOCOL.md`](PROTOCOL.md).

## 1. Why this layer exists

Every failure class in
`C:\Dev\findings\2026-09-30_agentmux_communication_failures.md` that happened at
the terminal falls into one of two shapes:
- **a keystroke sent without reading the screen first:** Enter into a modal (C2), text
  into a booting TUI (C5), keys into copy-mode (C7)
- **success reported without reading the screen after:** Enter that arrived before a
  paste finished assembling (C1), `sent` meaning only that tmux accepted the bytes (C10)

The old path (`cmd_send`) read the screen once, for a modal. It then typed the *whole
message* and trusted exit code 0.

The new path follows one rule: **read, act, read.** And it types only one short, fixed
line.

## 2. Three layers, three files

| Layer | File | Knows about | Does not know about |
|---|---|---|---|
| Transport | `hub/transport.py` | bytes, keys, panes, terminal modes | any CLI's screen, any message |
| CLI profile | `hub/profiles.py` | what one CLI's screen means | tmux, messages |
| Delivery | `hub/deliver.py` | the stage sequence and its evidence | retry policy (the hub owns that) |

### 2.1 Transport interface

```python
class Transport:
    list() -> [session]
    alive(session) -> bool
    handle(session) -> (pane_id, pane_pid) | None
    mode(handle) -> 'normal' | 'copy' | 'dead'
    capture(handle) -> str                  # visible screen, ANSI stripped, wrapped lines joined
    send_text(handle, text)                 # single line, literal, no submit
    send_buffer(handle, text)               # large or multi-line: load-buffer + paste-buffer -p
    send_key(handle, key)                   # abstract key vocabulary only (section 4)
    leave_mode(handle)
    output_mark(session) -> int | None      # grows exactly when the pane prints
    kill(session)
```

**Implementations:**
- `TmuxTransport`, over `tmux -L $AGENTMUX_SOCKET`.
- `FakeTransport`, with scripted screens, used by the offline tests.

Another backend (Orca, ConPTY, a headless SDK agent) implements the same ten methods.

**`output_mark` is the liveness signal** (R-LIVE-1): the size of the pane's pipe-pane
log. It replaces tmux `#{session_activity}`, which went hours stale on panes that were
working and got live agents killed (C4).

### 2.2 CLI profiles

Each profile defines:

| Field | Example (codex) |
|---|---|
| `ready` | `^\s*›\s?` (the idle composer) |
| `busy` | `esc to interrupt\|…` (claude also matches `✻ Verbing…`, `… (12s)`, `Press up to edit queued`) |
| `placeholder` | `[Pasted Content …]`, `[Pasted text #n +N lines]`, `[N lines pasted]` |
| `modals` | an ordered list of (kind, pattern, safe answer or **None**) |
| `boot_s` | the minimum time after spawn before "ready" is believed |
| `doorbell` | the one line the hub ever types |

**The modal table is the harness's memory of hostile defaults.** Every entry exists
because a screen like it was seen:

| CLI | Modal | Safe answer | Why |
|---|---|---|---|
| codex | Update available | `2` (Skip) | option 1 is preselected and runs `npm install -g`, then exits. It killed panes on 09-20 and 09-29 |
| codex | directory trust | `Enter` | accept is preselected, and only after positive identification |
| codex | sign in | **None** | needs a person |
| claude | bypass consent | `Down Enter` | the default "No, exit" killed an agent on 09-22 |
| claude | folder trust / effort / theme | `Enter` | the preselected answer is safe |
| claude | Not logged in / login method | **None** | 9 pasted briefs landed in a logged-out claude |
| grok | trust the contents | `y` | letter-keyed |
| all | any other prompt shape (the `modal_text` regex) | **None** | an unrecognized prompt is never typed into |

**None means blocked:**
- The hub marks the agent `blocked`, notifies `virtual:operator` once, and retries every
  30 seconds.
- It never guesses.

## 3. The delivery sequence (`deliver_line`)

```
resolved   handle(session) matches the registered handle (else refuse: R-ID-2, C8)
mode       copy-mode -> leave_mode, re-check (C7); dead -> report dead
booting    now - started < profile.boot_s -> defer (C5)
modal      settle; known-safe modal -> answer, re-read (up to 4 passes); other modal -> blocked (C2)
ready      settle; busy -> defer; no prompt -> defer
           our own line already in the composer (or a placeholder) -> Enter only, never retype (C1)
           other text in the composer (often a TUI hint) -> C-u first, and record it
typed      send_text; settle; verify the text or a placeholder is visible
           a modal appeared while typing -> C-u, blocked (never Enter into it)
submitted  poll up to 6s: the text is gone from the composer and no placeholder remains;
           halfway through, re-send Enter (at most 3 total). That is the C1 cure.
```

- **`settle`** re-captures until the screen is still for 0.6 s. A TUI in the middle of
  a redraw shows a screen that is about to change.
- **The Receipt** records each stage as `ok`, `unverified`, or a reason. It also records
  modal answers, the Enter count, and elapsed time.
- **The hub writes the Receipt** into the `events` table (`entity = 'bell'`), so every
  keystroke the hub ever sent has an audit row.

## 4. Abstract keys

The key names are:

`Enter Escape Tab BTab Space BSpace Up Down Left Right Home End PageUp PageDown C-c C-u C-d`,
plus any single printable character, for numbered menus.

`send_key` refuses anything else. tmux types an unknown key name as literal text and
still exits 0 (`Dowm` was typed once).

## 5. The doorbell strategy

**The hub never types a message body into a pane.** It types exactly one short, fixed
line per profile:

```
[hub] 2 new message(s), 1 claimable work item(s) for calc-worker-codex_1. Run: agentmux hub inbox --ack
agentmux hub inbox --ack  # [hub] 2 message(s), 1 claimable for calc-worker-smoke_sh      (shell profile)
```

The agent then **pulls** its messages through the hub, which is the receipt and, with
`--ack`, the acknowledgment. This removes three failure classes by construction:
- **C6 (size and escaping).** The typed line is at most 150 ASCII characters: no `;`,
  no `\`, no `!`, no newline. Bodies of any size, including large ones stored as brief
  files, travel through the socket.
- **C1 (paste placeholder).** A line this short never becomes a paste placeholder.
- **C11 in its "reply when read" form.** Reading is a command with visible output, not
  an instruction the model might answer instead of acting on.

**Re-ring:**
- A bell repeats when new mail or work arrives.
- When mail stays unacked, it repeats every `bell_every_s` (90 s).
- A delivery attempt counts only when a bell was **submitted** and the mail still sat
  unacked. Deferrals for busy or blocked panes never use up attempts. An earlier draft
  did, and a busy agent's mail would have died in 18 minutes.

### 5.1 The other strategies, for the eval record

| Strategy | What | Status |
|---|---|---|
| S1 | full body via `send-keys -l` (the old `cmd_send`) | retired from the hub; C1, C6 |
| S2 | full body via `load-buffer` + `paste-buffer -p` | available as `strategy='buffer'`; fixes C6, still exposed to C1 |
| S3 | doorbell line plus pull | **default** |
| S4 | brief file on disk plus a pointer line | used for bodies over `inline_max` (4 KiB), with the pointer delivered through S3 |

## 6. Evidence

| Evidence | Where |
|---|---|
| Offline guard tests | `hub/tests/test_hub_offline.py` class `Deliver`: update modal answered with `2` (never Enter), login blocks with zero keys sent, unknown prompt blocks, copy-mode left first, busy and booting defer with zero keys, placeholder gets a second Enter, a stale line is resubmitted and not retyped, a handle mismatch is refused |
| Live runs | `evals/orchestrations/*.json`. Each report lists every bell outcome, every modal answer and the extra-Enter count, and scores E1–E6 |
