---
id: "TM-023"
kind: "task"
status: "open"
created: "2026-09-25T19:31:59.836Z"
board: "controllogix/ccontrolcenter"
title: "BUG: a git checkout on Windows silently blanks the task board"
epic: "EP-002"
acceptance: [{"text":"The task store is pinned to LF in .gitattributes so a checkout cannot rewrite its line endings","done":false},{"text":"A fresh clone on a machine with core.autocrlf=true yields a readable board","done":false},{"text":"tm reindex recovers a board whose documents are intact but whose index entries are empty","done":false},{"text":"tm doctor distinguishes a document that is absent from one that is present but unparseable, rather than reporting both as orphan-epic","done":false},{"text":"The .gitattributes rationale is recorded, so the pin is not removed later as noise","done":false}]
evidence: []
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T19:31:59.913Z"
---

Hit for real on 2026-09-25, and it looks exactly like data loss when it is not.

`core.autocrlf` is `true` on this machine. The task-management plugin writes its documents with newline endings and parses them by splitting on the frontmatter fence. Under autocrlf they **check out** with CRLF, the fence stops matching, and every document parses to an **empty object**. `tm board` then renders:

    ## Epics
    ○ undefined undefined — 0/19 done
    ○ undefined undefined — 0/19 done

The `.md` files are perfectly intact. Only the reader breaks. That is what makes it dangerous — the obvious reaction to a board full of `undefined` is to assume the store is corrupt and start restoring things, when nothing has been lost.

**Measured, and the split is exact:**

    EP-002-agentmux-the-node-rewrite.md   CRLF  -> parses to {}
    TM-001-pin-boardid-in-the-task-store-config.md  CRLF  -> parses to {}
    TM-020-...md   LF   -> parses fine

TM-020 is the one the plugin had written *after* the checkout. Everything git had re-materialised was CRLF and therefore unreadable: 2 of 2 epics, 19 of 22 tasks, 10 of 25 ADRs.

**So a plain `git clone` of this repo onto a Windows machine produces an empty-looking board.** So does a branch switch, or any `git checkout -- .`. I triggered it with the latter while fixing the same class of problem for shell scripts.

**Fixed** by pinning `.bytedesk/task-management/**` to `text eol=lf` in `.gitattributes`, the same treatment `*.sh` needed and for the same underlying reason — and the same reason the `.pyc` above it was pinned: a line-ending rewrite that looks cosmetic silently breaks a file that is *parsed* rather than read by a human.

**Recovery, once the endings are right, is `tm reindex`** — it rebuilds the index from the documents, which were never damaged. That took the board straight back to `EP-002 — 16/22 done`.

Worth knowing: `tm doctor` reported the symptom as `orphan-epic: epic EP-002 does not exist` against the three newest tasks. That is a true observation and a misleading diagnosis — EP-002 exists, it simply could not be parsed. A doctor check that distinguished "absent" from "unparseable" would have named the real problem in one line.