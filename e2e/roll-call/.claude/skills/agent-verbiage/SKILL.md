---
name: agent-verbiage
description: The one shared vocabulary every agent in a coordinated run uses — message verbs, the header line, verdicts, and the close handshake. Read at bootstrap by every agent (Claude or Grok, any role) so that all messages, replies, and board posts use the same words.
---

# Shared agent vocabulary

Every agent in this run uses exactly these words, whatever its model or role. Do not invent
synonyms ("LGTM", "shipped", "finished", "ok to merge"). If none of these verbs fits, use `ASK`.

## The header line

The **first line** of every mailbox message and every reply is one header line:

```
<VERB> <ticket-or-deliverable> from=<agent-id> to=<agent-id|all> [key=value ...]
```

Example: `DELIVER backend from=developer to=conductor files=server/index.js,test/api.test.js`

Put the details under the header in plain Markdown. Keep the verb in capitals.

## Verbs

| Verb | Who sends it | Meaning |
|---|---|---|
| `BRIEF` | conductor | Here is your task, its acceptance criteria, and the files you may touch. |
| `CLAIM` | any worker | I have started this deliverable. |
| `TOUCH` | any worker | I am about to edit these paths (list them). Send this before editing anything shared. |
| `PROGRESS` | any worker | Partway status: what is done and what is next. Optional. |
| `ASK` | anyone | I need an answer before I can go on (one concrete question). |
| `DELIVER` | worker | The deliverable is ready for review. List every file and how to check it. |
| `REVIEW` | reviewer | Verdict on a deliverable: `REVIEW APPROVE`, `REVIEW CHANGES`, or `REVIEW BLOCKED`, each with numbered findings (`file:line` — what — why). |
| `REVISE` | conductor | Pass the reviewer's `CHANGES` findings back to the worker. |
| `ACCEPT` | conductor | I agree that the deliverable meets the brief. Sent only after `REVIEW APPROVE`. |
| `CLOSE` | conductor | Your work is finished: stop working, write your final note, and answer `CLOSED`. |
| `CLOSED` | the agent being closed | Final reply: what I made, what I did not do, and any known risk. After this I do nothing. |
| `HANDOFF` | anyone | I am stopping before I am done. Here is what is left and where it is. |
| `DONE` | conductor | The whole run is complete (the last message of the run). |

## Verdict rules (reviewer)

- `APPROVE`: it meets every acceptance criterion in the brief. Minor nits may be listed but do not block.
- `CHANGES`: at least one criterion is not met or there is a real defect; every finding says how to fix it.
- `BLOCKED`: the review cannot be done (missing files, the app will not start); say what is missing.
- The reviewer checks the actual files and runs the stated checks (`node --test`, starting the
  server, opening the avatars). It never edits files.

## The close handshake (an agent's session ends only like this)

1. The worker sends `DELIVER`.
2. The reviewer sends `REVIEW APPROVE` for that deliverable (after as many `REVISE` rounds as it takes).
3. The conductor checks it and sends `ACCEPT`.
4. Only once it holds **both** `REVIEW APPROVE` and `ACCEPT` does the conductor send `CLOSE` to that worker.
5. The worker answers `CLOSED`, and the conductor then ends that agent's pane.
6. The reviewer is closed after its last verdict has been accepted. The conductor posts `DONE`
   and stops the run last.

No agent closes itself, and no agent is closed without steps 2 and 3.

## Board mirror

The conductor mirrors key events to the machine-wide forum with the same words:
`tm comment TM-001 "CLAIM ..."`, `"DONE ..."`, `"HANDOFF ..."`. Workers do not post to the board.
