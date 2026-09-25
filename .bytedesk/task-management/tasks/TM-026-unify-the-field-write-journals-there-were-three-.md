---
id: "TM-026"
kind: "task"
status: "done"
created: "2026-09-25T20:57:22.804Z"
board: "controllogix/ccontrolcenter"
title: "Unify the field write journals — there were three, not two"
epic: "EP-002"
acceptance: [{"text":"One module owns every write to field equipment: enip, logix and ads all journal through writejournal.py and none keeps a private _journal","done":true,"at":"2026-09-25T20:57:27.326Z"},{"text":"The intent is fsync'd before transmission and a journal failure prevents the write, proven for all three transports","done":true,"at":"2026-09-25T20:57:27.533Z"},{"text":"Every row names its transport and carries an id pairing its outcome back to its intent","done":true,"at":"2026-09-25T20:57:27.753Z"},{"text":"The legacy files migrate in timestamp order, are renamed rather than deleted, and a second run is a no-op","done":true,"at":"2026-09-25T20:57:27.974Z"},{"text":"A census test fails when a client that writes to equipment does not journal through this module","done":true,"at":"2026-09-25T20:57:28.178Z"},{"text":"Decide whether Modbus equipment writes join field-writes.jsonl or stay in the dashboard journal, and record which","done":true,"at":"2026-09-25T21:38:13.613Z"}]
evidence: [".bytedesk\\task-management\\evidence\\TM-026-1790372675029.log"]
commits: []
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-25T21:45:29.821Z"
assignee: "claude"
evidenceSources: {".bytedesk\\task-management\\evidence\\TM-026-1790372675029.log":{"source":null,"sha256":"a72f4b8c2defe0c024fbb7faed038678215180ad6e410f15937c43658b73a233","bytes":3348,"at":"2026-09-25T21:44:35.030Z"}}
closed: "2026-09-25T21:45:29.804Z"
---

Done, 2026-09-25. Filed as a record because the *finding* matters more than the refactor.

The rewrite plan's §4.1 and §1.3.8 both say there are **two** write journals, `enip.py:213` and `logix.py:99`, and that unifying them is a prerequisite for the pycomm3 work. There were **three**. `ads.py:85` kept `~/.agentmux/ads-writes.jsonl` with the same shape, the same guarantees and its own copy of the rejected/unknown decision — and nothing outside that module pointed at it.

That is exactly the failure a shared journal exists to prevent. An audit trail answers "what did we last send to that controller?" only for someone who already knows it is there — and a survey done carefully enough to be written into a plan still missed one of three.

**What was built.** `dashboard/writejournal.py`:

- `WriteJournal(path, transport=...)` → `intent(record) -> Handle` → `Handle.settle(outcome)`. One file, `~/.agentmux/field-writes.jsonl`, every row carrying `transport` and an `id` that pairs an outcome back to its intent.
- `intent()` flushes and **fsyncs before it returns**, so the record is on disk before a byte reaches the wire, and **fails closed** — the exception reaches the caller, which must not then transmit.
- `classify(rejected, completed)` — one definition of the rejected/unknown/partial decision instead of three near-copies. `partial` is kept (logix fragmented writes) rather than folded into `unknown`: it means the controller holds a value neither side asked for, which is a worse thing to know.
- `settle()` refuses a second outcome and refuses an unrecognised one.
- `migrate_legacy()` folds all three legacy files in **timestamp order** (concatenating would misrepresent when things happened), tags each row's transport from the filename stem, **renames rather than deletes** the sources, keeps unparseable lines rather than dropping them, and is idempotent.

`enip.py`, `logix.py` and `ads.py` now hold a `WriteJournal` and have no private `_journal`. `journal_path` survives as a property, since callers and tests name the path.

**The existing tests were the specification, and all of them still hold** — `test_enip.py:196` (intent readable off disk at the moment of transmission), `test_enip.py:177` / `test_logix.py:302` / `test_ads.py:195` (journal failure prevents the write), `test_logix.py:314` (fsync asserted at the syscall, `wraps=`, call_count 2). They were ported to the new seam — `client.journal.append` and `writejournal.os.fsync` — because that is where durability now lives; patching a vestigial forwarder would have proven nothing.

**New: `dashboard/test_writejournal.py`, 22 assertions.** Including a census test that lists every client which writes to equipment and asserts each one journals through this module — so a fourth client added later fails here until someone classifies it, rather than quietly starting a fourth file the way ads.py did. Its import is guarded so that a tree without the module FAILS cleanly rather than crashing, which is what makes the failability proof meaningful.

Registered in `run_tests.sh` and in `check_test_failability.sh` (base `aaa5cae`, 22 — all of them, since a tree without the module fails every test by construction).

**Still true and unchanged:** none of the three legacy files has ever existed on this machine. No live industrial write has been performed from this repo, so `migrate_legacy` is correct-but-never-exercised-in-anger by construction; its tests build the legacy files themselves.

**Not done here:** Modbus equipment writes (`modbus_poll.py:296`) go into the *dashboard's* journal — a callback into cc.db — not into `field-writes.jsonl`. That is a different shape and a separate decision.