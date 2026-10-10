# Delivery outcomes (correlate.py)

Generated from `out/*.jsonl` only. Deterministic; no clock read.

Ledger rows: **3** (3 courier queue lines, 0 operator send/ask intents). Date range 2026-09-20T12:00:00Z .. 2026-09-20T12:00:00Z (UTC).

## Outcome totals

| outcome | count | share |
|---|---|---|
| received | 3 | 100.0% |
| typed-not-submitted | 0 | 0.0% |
| into-modal | 0 | 0.0% |
| deferred-then-received | 0 | 0.0% |
| dead-lettered | 0 | 0.0% |
| lost-silent | 0 | 0.0% |
| wrong-recipient | 0 | 0.0% |
| truncated | 0 | 0.0% |
| duplicated | 0 | 0.0% |
| unknown | 0 | 0.0% |

## Outcome x CLI

| outcome | claude | total |
|---|---|---|
| received | 3 | 3 |
| typed-not-submitted | . | 0 |
| into-modal | . | 0 |
| deferred-then-received | . | 0 |
| dead-lettered | . | 0 |
| lost-silent | . | 0 |
| wrong-recipient | . | 0 |
| truncated | . | 0 |
| duplicated | . | 0 |
| unknown | . | 0 |
| **total** | 3 | 3 |

## Outcome x path

| outcome | courier | total |
|---|---|---|
| received | 3 | 3 |
| typed-not-submitted | . | 0 |
| into-modal | . | 0 |
| deferred-then-received | . | 0 |
| dead-lettered | . | 0 |
| lost-silent | . | 0 |
| wrong-recipient | . | 0 |
| truncated | . | 0 |
| duplicated | . | 0 |
| unknown | . | 0 |
| **total** | 3 | 3 |

## Outcome x day (UTC)

| day | received | typed-not-submitted | into-modal | deferred-then-received | dead-lettered | lost-silent | wrong-recipient | truncated | duplicated | unknown | total |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-09-20 | 3 | . | . | . | . | . | . | . | . | . | 3 |
| **total** | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 |

## Reasons (blind spots are the `unknown` rows)

| outcome | reason | count |
|---|---|---|
| received | receipt matched by sha | 3 |

## Receipt match method (rows with a receipt)

| method | count |
|---|---|
| sha | 3 |

## Pane evidence outside the ledger

Pane records that no ledger row matched. These are mostly dispatch briefs and spawn prompts, which are typed by `dispatch`/`spawn` rather than queued, so they are counted here instead of labeled.

| pane record | cli | subkind / reason | total | matched a ledger row | unmatched |
|---|---|---|---|---|---|

## Excluded from the ledger

| why | count |
|---|---|

## Spot check

Sample: 3 random `received` rows (seed 20260930) and all 0 `lost-silent` rows, listed in `out/spotcheck.sample.jsonl`. `spotcheck.py` re-checks each against the RAW sources: it recovers the full body from the snapshot queue line or the transcript argv, then searches every one of the CLI session files that hold receipts (codex rollouts, claude projects and history, grok updates) and the recipient's pane log for start/middle/end needles. Verdicts are in `spotcheck.judgments.json`. `unverifiable` = the session file was deleted after extraction (claude-config removed at team teardown); those rows are left out of the rate.

### Pass 2 (current labels)

Checked 2 of 3 (1 unverifiable); disagreements **1 (50.0%)**.
- `received`: 1/2 disagree
- `lost-silent`: 0/0 disagree

| id | agent | label | verdict | raw-source note |
|---|---|---|---|---|
| q:agree-queue.jsonl:1 | agree | received | agree | raw user turn at agree-session.jsonl:1 (whole) |
| q:disagree-queue.jsonl:1 | disagree | received | disagree | no user turn with this body in the agent's session files |
| q:unverifiable-queue.jsonl:1 | unverifiable | received | unverifiable | the agent's session files are gone since extraction (1 missing) |

