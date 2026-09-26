---
id: "TM-034"
kind: "task"
status: "done"
created: "2026-09-25T23:50:17.036Z"
board: "controllogix/ccontrolcenter"
title: "The financial artifact boundary, gated before Phase 5 exists"
epic: "EP-002"
acceptance: [{"text":"Nothing financial can be committed: tracked artifacts, brokerage filenames, labelled account numbers and missing .gitignore pins all fail the gate","done":true,"at":"2026-09-25T23:50:23.917Z"},{"text":"Where artifacts DO go is written down, and the check verifies that document exists","done":true,"at":"2026-09-25T23:50:24.114Z"},{"text":"The guard does not fire on ordinary code containing bare digits or the word account","done":true,"at":"2026-09-25T23:50:24.318Z"},{"text":"The guard reads a CRLF .gitignore correctly, and a rule genuinely removed from one still fails","done":true,"at":"2026-09-25T23:50:24.511Z"},{"text":"Every case is proved by construction in a throwaway clone, since no commit exists where the bug was present","done":true,"at":"2026-09-25T23:50:24.703Z"}]
evidence: [".bytedesk\\task-management\\evidence\\TM-034-1790380243306.log"]
commits: ["b8041df"]
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T23:50:52.084Z"
assignee: "claude"
evidenceSources: {".bytedesk\\task-management\\evidence\\TM-034-1790380243306.log":{"source":null,"sha256":"7cfce707bf03d78ecd4dbd6ff18925d12e054a571eebc9b54a2148610ccc270c","bytes":3633,"at":"2026-09-25T23:50:43.307Z"}}
closed: "2026-09-25T23:50:51.153Z"
---

Done 2026-09-25, plan §5.0. Commits `8748261`, `d280e42`, `e5ba78c`.

`gh repo view` → `controlLogix/CControlCenter`, **`isPrivate: false`**. Phase 5 adds a brokerage session: positions, balances, account numbers, order records, research packs. **A push cannot be taken back** — a file deleted in the next commit stays in the history, and by then it has been cloned and indexed. It is the one mistake in Phase 5 that cannot be undone by writing the old value back, unlike a PLC tag and unlike a board row.

So the guard exists before the feature that needs it, the same discipline as the write ticket before the write route.

**Three parts, covering different failure modes.** `.gitignore` pins `investing/`, `broker/`, `agentmux-broker/`, `research/sessions/` so an artifact written into the tree lands ignored rather than staged. `docs/investing-boundary.md` records where they go instead (`%LOCALAPPDATA%\agentmux\broker\`, `$AGENTMUX_HOME/investing/`), because pins can only say where something must *not* go. `check_no_financial_artifacts.sh` fails on any tracked artifact, any filename that is a brokerage record, any value labelled as an account number — **and on the pins themselves going missing**, since a check that only looked at today's tree would pass the moment someone removed them.

**Deliberately precise, not broad.** The account-number check anchors on the *word*, not the digit shape. Nine digits are a port or a timestamp far more often than an account, and flagging the shape would fire across half the repo and be switched off within a week. The limit is written into the doc rather than implied away: this makes the careless case impossible and the determined case no harder.

`check_test_failability` cannot prove this one — its method needs a commit where the bug was present, and there has never been a financial artifact here. So it is proved by construction: plant each violation in a throwaway clone, require the catch, remove it, require the pass. **11 checks**, including the negative one (ordinary code with bare digits and the word "account" must not trip it).

### Writing the proof found four defects, three in the guard and one in the proof

1. `grep -qF investing/` was satisfied by `.gitignore`'s own comment naming `$AGENTMUX_HOME/investing/` — deleting the actual rule still passed. **Matching prose about the thing rather than the thing**, for the third time today.
2. The "is it documented" check grepped `docs/*.md` and `.gitignore` together, which the same comment satisfied — deleting the document entirely still passed.
3. Anchoring the pin match (the fix for #1) made it **line-ending sensitive**: `.gitignore` is not pinned in `.gitattributes`, so under `core.autocrlf` it reads as `investing/\r` and an exact whole-line match finds nothing. Passed locally on LF, failed in the gate clone — local green and gate red for the same tree.
4. The proof's own removal used `grep -v '^investing/$'` against that CRLF copy, so it removed nothing and reported `MISSED` — a test claiming to have removed something that had not, which reads as a defect in the thing under test.

And the fix for #4 arrived mangled through a shell heredoc as a **literal carriage return** inside a tracked script. It worked — `tr` deletes the CR either way — which is why it survived. `check_line_endings.sh` caught it with the lone-CR distinction added earlier the same day.</body>
