---
id: "TM-031"
kind: "task"
status: "open"
created: "2026-09-25T22:18:40.518Z"
board: "controllogix/ccontrolcenter"
title: "BUG: test_e2e.sh flakes, and a failing e2e run reports nothing at all"
epic: "EP-002"
acceptance: [{"text":"A failing test_e2e.sh reports passed/failed counts as its last line, never a log tail","done":true,"at":"2026-09-25T22:18:45.853Z"},{"text":"The runner prints the FAIL lines of a failing e2e run, not just the suite name","done":true,"at":"2026-09-25T22:18:46.061Z"},{"text":"A run that dies before counting anything says that, rather than reporting an unrelated line","done":true,"at":"2026-09-25T22:18:46.277Z"},{"text":"The root cause of the intermittent failure is identified, with evidence from a captured failing run","done":true,"at":"2026-09-26T01:40:04.714Z"},{"text":"The gate gives the same verdict on three consecutive runs of an unchanged tree, e2e included","done":false}]
evidence: [".bytedesk\\task-management\\evidence\\TM-031-1790375058608.log"]
commits: ["09bc170","9ac33cc","87b2c5e","cff7911"]
blockedBy: []
blocks: []
session: "5748a917-ba3c-4a23-9c48-424b6c04104f"
labels: ["ready-for-agent"]
triagedBy: "human"
updated: "2026-09-26T01:43:35.034Z"
evidenceSources: {".bytedesk\\task-management\\evidence\\TM-031-1790375058608.log":{"source":null,"sha256":"7e71f6ed32241b022a3b46f5d2d831dbe3043240b4890137fca165049a15c77f","bytes":3042,"at":"2026-09-25T22:24:18.609Z"}}
---

Found 2026-09-25 by running the gate twice on the **same commit** (`77696cb`): `1 suite(s) failed`, then `all suites passed`. The suite was `test_e2e.sh`, which also passes 50/0 when run on its own.

**Two separate problems, and the second is why the first cost a full re-run.**

### 1. The flake itself — ROOT CAUSE FOUND, see below

### 2. A failing e2e reported nothing — FIXED

Two causes, both in how the gate reads a suite:

- **`test_e2e.sh` printed its diagnostic after its summary.** `run_tests.sh` reports a suite by its **final line**, and the failure branch dumped `tail -40 server.log` last — so the gate printed the tail of an unrelated log where the counts should have been. Fixed: the diagnostic goes first, the summary is re-printed last, and a run that died before counting anything says so instead of letting the last line be whatever was on stdout.

- **The runner could not see e2e's failure lines.** It knew two shapes — `  FAIL  <what>` (indented, testlib) and `FAIL: <test>` (column zero with a colon, unittest). `test_e2e.mjs:50` prints **`FAIL <name>`** — column zero, no colon — which matched neither, so a failing e2e produced no detail whatsoever. Fixed by matching `^(FAIL|ERROR)[: ]`.

So the gate said `1 suite(s) failed` and nothing else, and finding out which suite it had been required re-running the whole thing.

### `dashboard/test_gate_reporting.sh`

This property — can the gate say **what** broke, not just **that** something did — has now been violated four separate ways here (TM-012, TM-014, the `passed -1` count, and this), each time silently. It now has its own suite rather than being an implicit assumption.

---

## Root cause, 2026-09-25 — and my first diagnosis was wrong

**The wrong diagnosis is the useful part.** Six runs (three idle, three loaded) showed 32s idle vs 130s loaded with one failure at the tail, so I read it as "the 25s UI budget is too small under contention" and raised it to 60s. Re-running under the same load: still 2 of 4 failing, now timing out at *60s*, and an **earlier** test failing too. A wait that still times out after you double it is not waiting for something slow.

**The actual cause** came from the console-error assertion that had been in the suite all along — "the page logged no errors while all of that happened":

```
The resource from "http://127.0.0.1:55633/kanban.js" was blocked due to
MIME type ("application/json") mismatch (X-Content-Type-Options: nosniff)
```

That is a **404 body**. `server.py` had two handlers catching `OSError` around a static file and answering about the **request** rather than about the filesystem: `403 forbidden` around `resolve()`, `404 not found` around `is_file()`/`read_bytes()`. The tree is on 9p, where both raise EIO under load. R29, in the request path this time — the same class as TM-013 and TM-027.

The 404 is the expensive one because it is a lie the browser believes: `send_json` sets `application/json`, the handler sets `nosniff` on every response, Firefox correctly refuses to execute JSON as a script, `kanban.js` never loads, the board never renders its agent rows, and the suite reports a **timeout three layers from the cause**.

### Fixed in `87b2c5e`

- `ninep.read_retrying()` retries a transient failure — 3 attempts over ~30ms — **before deciding anything**. That is the difference between the board rendering and not, and it is invisible when nothing is wrong.
- Absence stays 404. A directory stays 404. A permission error is **not** retried, so a permanent problem surfaces at once rather than 3x slower.
- "Could not tell" is now **503 with `Retry-After`**, in both handlers — and it is the more *visible* answer, since a script that 503s trips the load-failure banner `index.html` installs, where the 404 surfaced only as a MIME warning in a console nobody was reading.

`dashboard/test_static_serving.py`, 16 assertions, proved against `9ac33cc` where **13 of 16 fail**. The three that pass at the base are the control: they assert what did *not* change, so this is not a suite that merely fails to import against its own base. One of the 13 is a plain behavioural failure, `403 != 503` — the `resolve()` half of the same bug.

The e2e budget stays at 60s but its justification is corrected in place: contention alone costs about **1.6x** (32s idle, 51s loaded and healthy), not the 4x that was measured off the bug. The comment now says not to raise it again to make a failure go away.

**This also clears TM-027's AC 5 qualification** recorded above: the "two verdicts for one tree" family had a second cause, and it was 9p after all — just in the request path rather than in a test.
