# Communication-failure analysis, 2026-09

Phase A of the plan "the agentmux messaging protocol and hub". This folder holds the
mining tools and their outputs. Everything here runs **read-only** against a snapshot and
the original logs. Nothing writes under `~/.agentmux`, and nothing sends to a pane.

## Inputs

| Input | Location (WSL) |
|---|---|
| Snapshot of queue, courier, inbox, runs, dispatch, claims, journal, `.idle.log`, sidecars, and `cc.db` backups | `/home/nick/agentmux-comms-snapshot/20260929-215601/` |
| Pane logs, indexed in `logs.index.tsv` and read in place | `/home/nick/.agentmux/logs/*.log` |
| Codex session logs | `~/.codex/{sessions,logs_2.sqlite,history.jsonl}`, and the pre-09-29 copy at `/mnt/c/Users/Nick/.codex` |
| Claude session logs | `~/.claude-wsl/projects`, `~/.agentmux/claude-config/*/` |
| Grok session logs | `~/.grok/sessions`, `~/.grok/logs/unified.jsonl` |
| Claude Code transcripts (the orchestrator's side) | `/mnt/c/Users/Nick/.claude/projects/*` |

## Extractors

There is one extractor per source group. Each one:
- is a stdlib-only Python 3.12 script, run in WSL with `wsl.py py`
- is deterministic: sorted output, and no "now" in any record
- writes into `out/`

| Script | Output |
|---|---|
| `extract_transcripts.py` | `out/transcripts.jsonl` |
| `extract_panes.py` | `out/panes.jsonl` |
| `extract_receipts.py` | `out/receipts.jsonl` |
| `extract_courier.py` | `out/courier.jsonl` |

## Common record schema (one JSON object per line)

```json
{
  "src":      "transcripts|panes|receipts|courier",
  "type":     "<see below>",
  "t":        "2026-09-27T23:36:04Z",
  "t_basis":  "utc|local-cdt|file-mtime|unknown",
  "agent":    "<recipient or pane name, as written at the time>",
  "sender":   "<sender, or null>",
  "path":     "send|ask|key|post|courier|dispatch|unblock|clear-modals|null",
  "prefix":   "<first 80 chars of the message body, whitespace collapsed, ANSI stripped>",
  "body_sha": "<sha1 hex of the full normalized body, or null>",
  "body_len": 1234,
  "detail":   { "any": "extra fields" },
  "ref":      "<file path>:<line> or <file path>@<byte offset>"
}
```

- **`t`:** convert every timestamp to UTC. The machine is US Central, CDT = UTC-5.
  - If a source's timezone is ambiguous, record `t_basis` and the evidence in `detail.tz_note`.
  - Never guess silently.
- **Normalization for `prefix` and `body_sha`:**
  1. strip ANSI escapes
  2. strip bracketed-paste markers (`ESC[200~`, `ESC[201~`)
  3. strip the courier envelope `[agentmux] from X (kind) ref R: `
  4. collapse all whitespace runs to one space and trim

  Envelope fields go in `detail`.

## Record types

| src | type | meaning |
|---|---|---|
| transcripts | `intent` | an orchestrator Bash call to `agentmux send\|ask\|key\|post\|unblock\|dispatch` (`detail`: argv, exit code, the stderr head) |
| transcripts | `observation` | the orchestrator noticed a delivery problem ("not submitted", "Pasted Content", "stuck", "modal", "never got", "had to press Enter", "--force") |
| panes | `arrived` | the message text appeared in a pane |
| panes | `pending_input` | text or a `[Pasted Content ...]` placeholder is still in the input box after a quiet interval |
| panes | `modal` | a modal or prompt screen was showing (`detail.modal` = update, trust, bypass, login, effort, yn, other) |
| panes | `death` | the pane showed "Please restart", npm install, exit, or the CLI quitting |
| panes | `busy` | a busy marker appeared (start of work) |
| receipts | `received` | the CLI's own log recorded a user turn (a message the agent actually got) |
| courier | `queued` | a line in `queue/<sender>.jsonl` |
| courier | `sent` / `defer` / `gave_up` / `dead_letter` | courier outcomes |
| courier | `kill` | an idle-watchdog or kill event against an agent |
| courier | `identity` | a journal or claim row filed under an unexpected agent name |
| courier | `dispatch` | a dispatch or run brief handed to a pane |

## Merge

`correlate.py` joins the four outputs on `(agent, body_sha or prefix, time window)` and
assigns each intended delivery exactly one outcome:
- `received`
- `typed-not-submitted`
- `into-modal`
- `deferred-then-received`
- `dead-lettered`
- `lost-silent`
- `wrong-recipient`
- `truncated`
- `duplicated`
- `unknown`

The results are written to `out/outcomes.jsonl` and `out/summary.md`.
