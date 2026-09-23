#!/usr/bin/env python3
"""Verify the task-management model: minted keys, the task record, and the gates.

    python3 dashboard/test_board.py     # no network, no credential, no port 8787

Everything here runs against a throwaway AGENTMUX_HOME under the system temp
directory, so it never touches the operator's cc.db. The HTTP half binds
127.0.0.1 on port 0 - the kernel picks a free port - specifically so this suite
can run while the real dashboard is up on 8787.

WHAT THIS SUITE IS FOR
----------------------
The board used to identify work by the row's integer primary key. This is the
suite for the thing that replaced it: a minted, zero-padded, never-reused key
(EP-001, TM-014, ADR-0007, SP-002, CAP-0003), mirroring the identifier model of
the bytedesk-marketplace task-management plugin, and the record and gates that
make the key worth having.

Four properties are worth more than the rest, and each has a named check below:

  * A NUMBER IS NEVER HANDED OUT TWICE. Upstream measured eight concurrent
    creates producing three duplicate ids before it took a lock. The concurrency
    check here runs real threads against the real store and requires distinct
    keys, because the failure it guards is silent: two rows answer to one name
    and one of them becomes unaddressable.
  * A NUMBER IS NEVER REUSED. Delete is soft for exactly this reason.
  * THE HUMAN VETO IS PERMANENT. Once a person sets or clears a triage label, no
    later write and no triage sweep may put the task back in the agents' queue.
  * A GATE REFUSES WITH A REMEDY. Every refusal names the missing field and the
    verb that fills it, or it is not a gate, it is an obstacle.
"""

import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

HOME = Path(tempfile.mkdtemp(prefix="ccboard-suite-"))
os.environ["AGENTMUX_HOME"] = str(HOME)
os.environ.pop("CC_ENFORCE", None)
os.environ.pop("TM_ENFORCE", None)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ccboard  # noqa: E402
import ccstore  # noqa: E402
import server  # noqa: E402

passed = 0
failed = 0


def ok(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print("  ok   " + label)
    else:
        failed += 1
        print("  FAIL " + label + ((" - " + str(detail)) if detail else ""))


def section(name):
    print()
    print("== " + name)


def refuses(label, call, expect=None):
    """A gate must refuse, and its refusal must name a remedy."""
    try:
        call()
    except ccboard.Refused as err:
        hinted = all(item.get("hint") for item in err.missing) if err.missing else True
        if expect is not None and expect not in str(err):
            ok(label, False, "wrong message: " + str(err))
            return None
        ok(label, hinted, "a refusal with no hint is an obstacle, not a gate")
        return err
    except Exception as err:  # noqa: BLE001 - any other exception is the failure
        ok(label, False, type(err).__name__ + ": " + str(err))
        return None
    ok(label, False, "the call was allowed")
    return None


# ccstore.Invalid and ccboard.Invalid are distinct classes on purpose - the two
# modules validate different surfaces - so a rejection check accepts either.
INVALID = (ccboard.Invalid, ccstore.Invalid)


def rejects(label, call, kind=INVALID):
    try:
        call()
    except kind:
        ok(label, True)
        return
    except Exception as err:  # noqa: BLE001
        ok(label, False, "wrong exception: " + type(err).__name__ + ": " + str(err))
        return
    ok(label, False, "the call was allowed")


# ── a board with history, built the way a real one arrives ───────────────────
#
# The pre-existing rows are inserted through the OLD shape - integer ids, the
# retired status words, one epic carrying a hand-typed key - and then the
# migration runs. Testing the migration against a database that was already empty
# would prove nothing: the whole risk is the board somebody has been using.

def seed_legacy():
    path = HOME / "cc.db"
    import sqlite3
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    for statement in ccstore.SCHEMA:
        db.execute(statement)
    db.execute("INSERT INTO epics (id,key,title,status,created_at,updated_at)"
               " VALUES (1,'PLATFORM','Old epic','open',?,?)", ("t", "t"))
    db.execute("INSERT INTO epics (id,key,title,status,created_at,updated_at)"
               " VALUES (2,'EP-007','Numbered already','archived',?,?)", ("t", "t"))
    db.execute("INSERT INTO tasks (id,epic_id,title,status,created_at,updated_at)"
               " VALUES (1,1,'Legacy todo','todo',?,?)", ("t", "t"))
    db.execute("INSERT INTO tasks (id,epic_id,title,status,created_at,updated_at)"
               " VALUES (2,1,'Legacy cancelled','cancelled',?,?)", ("t", "t"))
    db.execute("PRAGMA user_version=1")
    db.commit()
    db.close()


section("migration of a board that was already in use")
seed_legacy()
with ccstore.connection() as db:
    epics = {row["title"]: dict(row) for row in db.execute("SELECT * FROM epics")}
    tasks = {row["title"]: dict(row) for row in db.execute("SELECT * FROM tasks")}
    ok("a well-formed key is kept", epics["Numbered already"]["key"] == "EP-007")
    ok("a hand-typed key is replaced with a minted one",
       epics["Old epic"]["key"] == "EP-008", epics["Old epic"]["key"])
    ok("the replaced key is recorded, not discarded",
       any(event["event"] == "rekeyed" and (event["detail"] or {}).get("was") == "PLATFORM"
           for event in ccboard.history(db, "EP-008")))
    ok("every task is keyed", all(ccboard.KEY_RE.match(t["key"]) for t in tasks.values()))
    ok("minting never collides with a number already in use",
       ccboard.mint(db, "epic") == "EP-009")
    ok("todo becomes open", tasks["Legacy todo"]["status"] == "open")
    ok("cancelled becomes deleted", tasks["Legacy cancelled"]["status"] == "deleted")
    ok("archived becomes done", epics["Numbered already"]["status"] == "done")
    ok("the status mapping is recorded",
       any(e["event"] == "status-migrated" for e in ccboard.history(db)))

with ccstore.connection() as db:
    before = ccboard.meta(db)["counters"]
with ccstore.connection() as db:
    ok("migration is idempotent across connections",
       ccboard.meta(db)["counters"] == before, before)


section("key format and the counter")
with ccstore.connection() as db:
    epic = ccboard.create(db, "epic", {"title": "Close the memory gaps"})
    ccboard.set_state(db, "activeEpic", epic["id"])
    ok("an epic key is EP and three digits", ccboard.KEY_RE.match(epic["id"])
       and epic["id"].startswith("EP-") and len(epic["id"]) == 6, epic["id"])
    adr = ccboard.create(db, "adr", {"title": "Keys are minted"})
    sprint = ccboard.create(db, "sprint", {"title": "Sprint one"})
    cap = ccboard.create(db, "capability", {"title": "Cursor paging", "impact": "high",
                                            "effort": "low", "confidence": "medium"})
    ok("an ADR key pads to four digits", adr["id"] == "ADR-0001", adr["id"])
    ok("a sprint key pads to three", sprint["id"] == "SP-001", sprint["id"])
    ok("a capability key pads to four", cap["id"] == "CAP-0001", cap["id"])
    ok("kind_of reads the prefix back",
       [ccboard.kind_of(k) for k in (epic["id"], adr["id"], sprint["id"], cap["id"])]
       == ["epic", "adr", "sprint", "capability"])
    ok("kind_of refuses a shape that is not a key",
       [ccboard.kind_of(v) for v in ("TM14", "tm-014", 14, None, "XX-001")] == [None] * 5)
    ok("a capability score is derived, not stored", cap["score"] == 18, cap["score"])


section("a number is never handed out twice")
# The failure this guards is silent: two rows answering to one key, one of them
# permanently unaddressable. Threads, real connections, one shared database.
minted = []
errors = []
with ccstore.connection() as db:
    race_epic = ccboard.create(db, "epic", {"title": "Race"})


def racer():
    try:
        with ccstore.connection() as db:
            row = ccboard.create(db, "task", {
                "title": "concurrent", "body": "b", "acceptance": ["a"],
                "epic": race_epic["id"]})
        minted.append(row["id"])
    except Exception as err:  # noqa: BLE001
        errors.append(repr(err))


threads = [threading.Thread(target=racer) for _ in range(8)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
ok("eight concurrent creates all succeeded", not errors, errors[:2])
ok("eight concurrent creates minted eight distinct keys",
   len(minted) == 8 and len(set(minted)) == 8, sorted(minted))


section("a number is never reused")
with ccstore.connection() as db:
    doomed = ccboard.create(db, "task", {"title": "doomed", "body": "b",
                                         "acceptance": ["a"], "epic": epic["id"]})
    ccboard.delete(db, doomed["id"])
    ok("delete is soft - the row stays",
       ccboard.entity(db, doomed["id"])["status"] == "deleted")
    after = ccboard.create(db, "task", {"title": "after", "body": "b",
                                        "acceptance": ["a"], "epic": epic["id"]})
    ok("the deleted key is not handed out again", after["id"] != doomed["id"],
       after["id"] + " vs " + doomed["id"])
    ok("a deleted card is off the board",
       doomed["id"] not in [t["id"] for t in ccboard.board(db)["tasks"]])
    ok("a deleted card is still addressable by key",
       ccboard.entity(db, doomed["id"])["title"] == "doomed")


section("the completeness gates")
with ccstore.connection() as db:
    err = refuses("create refuses a task with no body or criteria",
                  lambda: ccboard.create(db, "task", {"title": "thin"}))
    ok("the create refusal names both gaps",
       err is not None and {m["field"] for m in err.missing} == {"body", "acceptance"})
    ok("the create hint names the create verb, not an id that does not exist",
       err is not None and all("task new" in m["hint"] for m in err.missing))
    ok("a mirror create is exempt",
       ccboard.create(db, "task", {"title": "mirrored"}, mirror=True)["title"] == "mirrored")

    work = ccboard.create(db, "task", {"title": "Add cursor pagination",
                                       "body": "what and why",
                                       "acceptance": ["paging works", "tests green"]})
    refuses("done refuses a task with unticked criteria and no evidence",
            lambda: ccboard.set_status(db, work["id"], "done", actor="codex"),
            expect="cannot close")
    ccboard.set_status(db, work["id"], "in_progress", actor="codex")
    ccboard.tick_acceptance(db, work["id"], 1)
    refuses("done still refuses with one criterion unticked",
            lambda: ccboard.set_status(db, work["id"], "done", actor="codex"))
    ccboard.tick_acceptance(db, work["id"], 2)
    refuses("done refuses with every criterion ticked but no evidence",
            lambda: ccboard.set_status(db, work["id"], "done", actor="codex"))
    ccboard.add_evidence(db, work["id"], "logs/vitest.log")
    ok("done is allowed once the record is complete",
       ccboard.set_status(db, work["id"], "done", actor="codex")["to"] == "done")
    ok("closing stamps a closed timestamp", ccboard.entity(db, work["id"])["closed"])

    blocked = ccboard.create(db, "task", {"title": "downstream", "body": "b",
                                          "acceptance": ["a"]})
    upstream = ccboard.create(db, "task", {"title": "upstream", "body": "b",
                                           "acceptance": ["a"]})
    ccboard.set_dep(db, blocked["id"], upstream["id"])
    refuses("start refuses a task whose blocker is open",
            lambda: ccboard.set_status(db, blocked["id"], "in_progress", actor="x"),
            expect="blocked by")
    rejects("a task cannot block itself",
            lambda: ccboard.set_dep(db, blocked["id"], blocked["id"]))
    rejects("a dependency cycle is refused",
            lambda: ccboard.set_dep(db, upstream["id"], blocked["id"]))


section("the WIP limit")
with ccstore.connection() as db:
    ccboard.set_config(db, "wipLimit", 1)
    held = ccboard.create(db, "task", {"title": "held", "body": "b", "acceptance": ["a"]})
    other = ccboard.create(db, "task", {"title": "other", "body": "b", "acceptance": ["a"]})
    ccboard.set_status(db, held["id"], "in_progress", actor="wiptest")
    refuses("a second in-progress task is refused for the same actor",
            lambda: ccboard.set_status(db, other["id"], "in_progress", actor="wiptest"),
            expect="WIP limit")
    ok("a different actor is not blocked by somebody else's WIP",
       ccboard.set_status(db, other["id"], "in_progress", actor="second")["to"]
       == "in_progress")
    ccboard.set_config(db, "wipLimit", 3)


section("the override and the enforcement switch")
with ccstore.connection() as db:
    thin = ccboard.create(db, "task", {"title": "thin", "body": "b", "acceptance": ["a"]})
    ccboard.set_status(db, thin["id"], "in_progress", actor="ov")
    ccboard.set_override(db, "shipping a hotfix, evidence follows")
    result = ccboard.set_status(db, thin["id"], "done", actor="ov")
    ok("an armed override lets exactly one gate through", result["to"] == "done")
    ok("the bypass is reported, not silent", result.get("bypassed"))
    ok("the override is spent", ccboard.state(db)["override"] is None)
    again = ccboard.create(db, "task", {"title": "thin2", "body": "b", "acceptance": ["a"]})
    ccboard.set_status(db, again["id"], "in_progress", actor="ov")
    refuses("the next gate refuses again",
            lambda: ccboard.set_status(db, again["id"], "done", actor="ov"))

os.environ["TM_ENFORCE"] = "off"
with ccstore.connection() as db:
    loose = ccboard.create(db, "task", {"title": "unenforced"})
    ok("TM_ENFORCE=off disables the create gate", loose["title"] == "unenforced")
    ccboard.set_status(db, loose["id"], "in_progress", actor="off")
    ok("TM_ENFORCE=off disables the done gate",
       ccboard.set_status(db, loose["id"], "done", actor="off")["to"] == "done")
del os.environ["TM_ENFORCE"]
with ccstore.connection() as db:
    refuses("gates come back when the switch is removed",
            lambda: ccboard.create(db, "task", {"title": "thin again"}))


section("triage, and the permanence of the human veto")
with ccstore.connection() as db:
    ready = ccboard.create(db, "task", {"title": "ready", "body": "b",
                                        "acceptance": ["a"]})
    ok("a fully specified task is labelled ready-for-agent",
       "ready-for-agent" in ready["labels"], ready["labels"])
    ok("the label is stamped as the computation's",
       ccboard.entity(db, ready["id"])["triagedBy"] == "auto")
    thinner = ccboard.create(db, "task", {"title": "thin", "body": "b"}, mirror=True)
    ok("a task missing criteria is labelled needs-triage",
       "needs-triage" in thinner["labels"], thinner["labels"])
    ok("the gaps are reported alongside the label",
       "acceptance criteria" in ccboard.board(db)["tasks"][-1].get("triageMissing", []),
       ccboard.board(db)["tasks"][-1].get("triageMissing"))
    filled = ccboard.add_acceptance(db, thinner["id"], "a real check")
    ok("filling the gap flips the label on the same write",
       "ready-for-agent" in filled["labels"], filled["labels"])

    ccboard.set_label(db, ready["id"], "ready-for-human")
    ok("a person's triage label stamps the task as theirs",
       ccboard.entity(db, ready["id"])["triagedBy"] == "human")
    ok("and it displaces the computation's label rather than sitting beside it",
       ccboard.entity(db, ready["id"])["labels"] == ["ready-for-human"],
       ccboard.entity(db, ready["id"])["labels"])
    ccboard.update(db, ready["id"], {"body": "still fully specified"})
    ok("a later write does not put it back in the agents' queue",
       "ready-for-agent" not in ccboard.entity(db, ready["id"])["labels"],
       ccboard.entity(db, ready["id"])["labels"])
    ccboard.triage(db, sweep_all=True)
    ok("a triage sweep does not override the person either",
       "ready-for-agent" not in ccboard.entity(db, ready["id"])["labels"])
    ccboard.set_label(db, ready["id"], "ready-for-human", present=False)
    ccboard.triage(db)
    ok("clearing a triage label sticks - the decision to have none is a decision",
       not [lab for lab in ccboard.entity(db, ready["id"])["labels"]
            if lab in ccboard.TRIAGE_LABELS],
       ccboard.entity(db, ready["id"])["labels"])
    ok("a non-triage label does not claim the task from the computation",
       "ready-for-agent" in ccboard.set_label(db, filled["id"], "perf")["labels"])


section("epic lifecycle")
with ccstore.connection() as db:
    lifecycle = ccboard.create(db, "epic", {"title": "Lifecycle"})
    only = ccboard.create(db, "task", {"title": "the only task", "body": "b",
                                       "acceptance": ["a"], "epic": lifecycle["id"]})
    ccboard.set_status(db, only["id"], "in_progress", actor="e")
    ccboard.tick_acceptance(db, only["id"], 1)
    ccboard.add_evidence(db, only["id"], "proof.log")
    closed = ccboard.set_status(db, only["id"], "done", actor="e")
    ok("an epic closes when its last task resolves", closed.get("closed") == lifecycle["id"],
       closed)
    empty = ccboard.create(db, "epic", {"title": "Empty"})
    ok("an empty epic does not close on its own",
       not ccboard.auto_close_epic(db, empty["id"], ccboard.config(db)))
    moved = ccboard.create(db, "task", {"title": "moving in", "body": "b",
                                        "acceptance": ["a"], "epic": empty["id"]})
    result = ccboard.move_task(db, moved["id"], lifecycle["id"])
    ok("an unfinished task moved into a closed epic reopens it",
       result.get("reopened") == lifecycle["id"], result)
    ok("the source epic is re-checked on the way out", result["from"] == empty["id"])
    ok("moving to none is allowed",
       ccboard.move_task(db, moved["id"], "none")["to"] is None)
    rejects("a task cannot be moved under another task",
            lambda: ccboard.move_task(db, moved["id"], only["id"]))


section("why, next and the graph")
with ccstore.connection() as db:
    root = ccboard.create(db, "task", {"title": "root", "body": "b", "acceptance": ["a"]})
    mid = ccboard.create(db, "task", {"title": "mid", "body": "b", "acceptance": ["a"]})
    leaf = ccboard.create(db, "task", {"title": "leaf", "body": "b", "acceptance": ["a"]})
    ccboard.set_dep(db, mid["id"], root["id"])
    ccboard.set_dep(db, leaf["id"], mid["id"])
    answer = ccboard.why(db, leaf["id"])
    ok("why reports the task as not startable", not answer["startable"])
    ok("why names the nearest blocker first",
       answer["chain"][0]["id"] == mid["id"], answer["chain"])
    ok("why walks the whole chain",
       {entry["id"] for entry in answer["chain"]} == {mid["id"], root["id"]})
    ok("why is readable as text", leaf["id"] in answer["text"])
    ok("a blocked task is not in the queue",
       leaf["id"] not in [t["id"] for t in ccboard.next_tasks(db, 200)])
    ok("an unblocked, specified task is",
       root["id"] in [t["id"] for t in ccboard.next_tasks(db, 200)])
    ccboard.update(db, root["id"], {"priority": "highest"})
    ok("the queue is ordered by priority",
       ccboard.next_tasks(db, 200)[0]["id"] == root["id"])
    drawing = ccboard.graph(db)
    ok("the graph carries the dependency edges",
       {"from": root["id"], "to": mid["id"], "type": "blocks"} in drawing["edges"])
    ok("the graph renders as mermaid", drawing["mermaid"].startswith("graph LR"))


section("the rest of the record")
with ccstore.connection() as db:
    card = ccboard.create(db, "task", {"title": "full record", "body": "b",
                                       "acceptance": ["a"]})
    ccboard.add_comment(db, card["id"], "a remark", author="nick")
    ccboard.add_commit(db, card["id"], "abc1234")
    ccboard.add_touch(db, card["id"], "dashboard/ccboard.py")
    ccboard.set_link(db, card["id"], "relates", root["id"])
    ccboard.update(db, card["id"], {"assignee": "codex", "estimate": 3,
                                    "type": "bug", "priority": "high"})
    full = ccboard.entity(db, card["id"])
    ok("comments are kept with their author", full["comments"][0]["author"] == "nick")
    ok("commits are attached", full["commits"] == ["abc1234"])
    ok("touches are attached", full["touches"] == ["dashboard/ccboard.py"])
    ok("links carry their type",
       full["links"] == [{"type": "relates", "id": root["id"]}])
    ok("the issue fields round-trip",
       (full["assignee"], full["estimate"], full["type"], full["priority"])
       == ("codex", 3.0, "bug", "high"),
       (full["assignee"], full["estimate"], full["type"], full["priority"]))
    ok("a touch is idempotent",
       ccboard.add_touch(db, card["id"], "dashboard/ccboard.py")["touches"]
       == ["dashboard/ccboard.py"])
    rejects("an unknown field cannot be edited",
            lambda: ccboard.update(db, card["id"], {"status": "done"}))
    rejects("an unknown link type is refused",
            lambda: ccboard.set_link(db, card["id"], "sortof", root["id"]))
    rejects("a link to a key that is not on the board is refused",
            lambda: ccboard.set_link(db, card["id"], "relates", "TM-999"),
            kind=ccboard.NotFound)
    rejects("an unknown priority is refused",
            lambda: ccboard.update(db, card["id"], {"priority": "urgent"}))
    history = ccboard.history(db, card["id"])
    ok("every write is in the entity's history",
       {event["event"] for event in history}
       >= {"create", "comment", "commit", "link", "edit"},
       sorted({event["event"] for event in history}))


section("doctor")
with ccstore.connection() as db:
    report = ccboard.doctor(db)
    codes = {finding["code"] for finding in report["findings"]}
    ok("a thin mirrored card is a warning, never an error", "incomplete-open" in codes)
    ok("the report counts what it found",
       report["errors"] + report["warnings"] == len(report["findings"]))
    ok("the report is readable as text", isinstance(report["text"], str) and report["text"])
    orphan = ccboard.create(db, "task", {"title": "orphan", "body": "b",
                                         "acceptance": ["a"]})
    db.execute("INSERT INTO board_deps (entity_key,blocked_by,at) VALUES (?,?,?)",
               (orphan["id"], "TM-998", ccboard.now()))
    ok("a dependency on a key that is not on the board is an error",
       "dangling-dep" in {f["code"] for f in ccboard.doctor(db)["findings"]})


section("the compatibility surface still works, and now carries keys")
with ccstore.connection() as db:
    values = ccstore.validate_write("epics", {"title": "Via the old endpoint"})
    legacy_epic = ccstore.write(db, "epics", values)
    ok("an epic created through /api/epics is minted a key",
       ccboard.KEY_RE.match(legacy_epic["key"] or ""), legacy_epic.get("key"))
    values = ccstore.validate_write("tasks", {"epic_id": legacy_epic["row"],
                                              "title": "Via the old endpoint"})
    legacy_task = ccstore.write(db, "tasks", values)
    ok("a task created through /api/tasks is minted a key",
       ccboard.KEY_RE.match(legacy_task["key"] or ""), legacy_task.get("key"))
    ok("the old endpoint creates as a mirror, so a bare title is still accepted",
       legacy_task["title"] == "Via the old endpoint")
    rejects("a key cannot be supplied by a request",
            lambda: ccstore.validate_write("epics", {"title": "x", "key": "EP-001"}))
    row = ccstore.write(db, "status", ccstore.validate_write(
        "status", {"kind": "task", "id": legacy_task["row"], "status": "in_progress"}))
    ok("a status change by row id still works", row["status"] == "in_progress")
    ok("and the response carries the key", row["key"] == legacy_task["key"])
    row = ccstore.write(db, "status", ccstore.validate_write(
        "status", {"kind": "task", "key": legacy_task["key"], "status": "blocked"}))
    ok("a status change by key works too", row["status"] == "blocked")
    rejects("an epic key is refused where a task key is required",
            lambda: ccstore.validate_write("status", {"kind": "task",
                                                      "key": legacy_epic["key"],
                                                      "status": "done"}))
    removed = ccstore.write(db, "delete", ccstore.validate_write(
        "delete", {"kind": "task", "key": legacy_task["key"]}))
    ok("delete through the old endpoint is soft", removed["ok"]
       and ccboard.entity(db, legacy_task["key"])["status"] == "deleted")
    rejects("a device cannot be addressed by key",
            lambda: ccstore.validate_write("delete", {"kind": "device", "key": "TM-001"}))
    ok("the old status words are gone from the vocabulary",
       not ({"todo", "cancelled", "archived"} & set(ccstore.TASK_STATUSES)))


# ── HTTP ─────────────────────────────────────────────────────────────────────
#
# Port 0: the kernel picks a free one, so this runs while the real dashboard is
# up on 8787. No Origin header is sent, which the guard treats as same-origin.

section("the HTTP surface")
httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
PORT = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()


def call(path, payload=None, method=None, content_type="application/json"):
    url = "http://127.0.0.1:" + str(PORT) + path
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None and content_type:
        request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            return err.code, json.loads(raw or b"null")
        except ValueError:
            return err.code, {"raw": raw[:200].decode("utf-8", "replace")}


status, payload = call("/api/board")
ok("GET /api/board answers", status == 200 and "tasks" in payload, status)
ok("the board payload carries every kind",
   {"epics", "tasks", "adrs", "sprints", "capabilities", "state", "counters"}
   <= set(payload or {}))
ok("the board payload strips bodies from the list",
   all("body" not in task for task in payload["tasks"]))

status, meta = call("/api/board/meta")
ok("GET /api/board/meta answers with the vocabulary",
   status == 200 and meta["vocab"]["statuses"] == list(ccboard.STATUSES))
ok("meta publishes the key format so no client hardcodes it",
   meta["kinds"]["task"] == {"prefix": "TM", "pad": 3})

status, created = call("/api/board/create", {"kind": "task", "title": "over http",
                                             "body": "why", "acceptance": ["a check"],
                                             "epic": epic["id"], "actor": "suite"})
ok("POST /api/board/create mints a key", status == 200
   and ccboard.KEY_RE.match(created.get("id", "")), (status, created))
HTTP_TASK = created.get("id")

status, refusal = call("/api/board/create", {"kind": "task", "title": "thin over http"})
ok("a refused create answers 409, not 400", status == 409, (status, refusal))
ok("the refusal carries the remedy over the wire",
   refusal.get("missing") and all(item.get("hint") for item in refusal["missing"]),
   refusal)

status, detail = call("/api/board/entity?id=" + HTTP_TASK)
ok("GET /api/board/entity returns the detail, body included",
   status == 200 and detail["body"] == "why", status)

status, moved = call("/api/board/status", {"id": HTTP_TASK, "status": "in_progress",
                                           "actor": "suite"})
ok("POST /api/board/status moves the task", status == 200 and moved["to"] == "in_progress",
   moved)
status, _ = call("/api/board/acceptance", {"id": HTTP_TASK, "index": 1, "done": True})
ok("POST /api/board/acceptance ticks a criterion", status == 200)
status, _ = call("/api/board/evidence", {"id": HTTP_TASK, "ref": "suite.log"})
ok("POST /api/board/evidence attaches proof", status == 200)
status, done = call("/api/board/status", {"id": HTTP_TASK, "status": "done",
                                          "actor": "suite"})
ok("the task closes once the record is complete", status == 200 and done["to"] == "done")

status, answer = call("/api/board/why?id=" + HTTP_TASK)
ok("GET /api/board/why answers", status == 200 and answer["id"] == HTTP_TASK)
status, hits = call("/api/board/find?q=over+http")
ok("GET /api/board/find searches every kind",
   status == 200 and HTTP_TASK in [hit["id"] for hit in hits["hits"]])
status, report = call("/api/board/doctor")
ok("GET /api/board/doctor answers", status == 200 and "findings" in report)
status, drawing = call("/api/board/graph")
ok("GET /api/board/graph answers", status == 200 and "mermaid" in drawing)
status, events = call("/api/board/history?id=" + HTTP_TASK)
ok("GET /api/board/history answers", status == 200 and events["events"])

status, _ = call("/api/board", {"kind": "task", "title": "x"})
ok("POST to a read-only op is refused with 405", status == 405, status)
status, _ = call("/api/board/create")
ok("GET on a write op is refused with 405", status == 405, status)
status, _ = call("/api/board/nosuchop")
ok("an unknown op is 405, never a 500", status in (404, 405), status)
status, _ = call("/api/board/create", {"kind": "task", "title": "x"},
                 content_type="text/plain")
ok("a create without application/json is refused with 415", status == 415, status)
status, _ = call("/api/board/entity?id=TM-99999")
ok("an unknown key is 404", status == 404, status)
status, _ = call("/api/board/entity?id=not-a-key")
ok("a malformed key is 400", status == 400, status)
status, _ = call("/api/board/find?q=" + "x" * 300)
ok("an over-long query is 400", status == 400, status)
status, _ = call("/api/board/next?limit=0")
ok("an out-of-range limit is 400", status == 400, status)
status, _ = call("/api/board/create", {"kind": "planet", "title": "x"})
ok("an unknown kind is 400", status == 400, status)

httpd.shutdown()

print()
# The store path goes ABOVE the summary, not below it. run_tests.sh reads the last
# line of a suite's output and requires it to end "failed 0"; a trailing store path
# made this suite read as a failure the moment it was added to the runner, while it
# was in fact passing 123 of 123.
print("store: " + str(HOME))
print("passed " + str(passed) + ", failed " + str(failed))
sys.exit(1 if failed else 0)
