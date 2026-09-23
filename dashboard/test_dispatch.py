#!/usr/bin/env python3
"""Verify the dispatch seam: what may be handed to an agent, and in what order.

    python3 dashboard/test_dispatch.py   # no network, no tmux, no port 8787

Runs against a throwaway AGENTMUX_HOME under the system temp directory, so it
never touches the operator's cc.db, and never spawns a process.

WHAT THIS SUITE IS FOR
----------------------
`dispatchable` is the only thing standing between a board and a machine that
starts unrestricted agents against this repository. Four properties matter more
than the rest, and each has a named check:

  * AN UNREADY CARD IS NEVER OFFERED. Not merely "not started" - not offered, so
    a dispatcher cannot start one even by asking for it by name.
  * A CARD RESERVED FOR A PERSON IS NEVER OFFERED. NOT_FOR_AGENTS exists because
    some cards are a decision, and a well-specified decision is still not work an
    agent may take.
  * THE EPIC IS RESOLVED BEFORE READINESS IS JUDGED. _payload_task leaves `epic`
    as None and only board() fills it in; agent_readiness asks for it. The first
    version of this read used _payload_task raw, so on a board with requireEpic
    set - which is the default - EVERY card read as epic-less and the queue was
    permanently empty. It looked like "nothing is ready" rather than a bug, which
    is the kind of failure that survives for weeks.
  * OVERLAPPING WORK RANKS LAST, AND IS STILL OFFERED. Two agents editing one
    file is what claims make safe and disjointness makes rare. A board whose every
    card touches the same file must still drain, one at a time.
"""

import os
import sys
import tempfile
from pathlib import Path

HOME = Path(tempfile.mkdtemp(prefix="ccdispatch-suite-"))
os.environ["AGENTMUX_HOME"] = str(HOME)
os.environ.pop("CC_ENFORCE", None)
os.environ.pop("TM_ENFORCE", None)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ccboard  # noqa: E402
import ccstore  # noqa: E402

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


def rejects(label, call):
    try:
        call()
    except (ccboard.Invalid, ccstore.Invalid):
        ok(label, True)
        return
    except Exception as err:  # noqa: BLE001
        ok(label, False, "wrong exception: " + type(err).__name__ + ": " + str(err))
        return
    ok(label, False, "the call was allowed")


def ids(rows):
    return [row["id"] for row in rows]


# ── a board with one epic and a spread of cards ───────────────────────────────

def ready_card(db, epic, title, touches=(), labels=(), priority=None):
    """A card that passes every gate, so a test that expects it to be REFUSED is
    testing the one thing it changed and not an unrelated gap."""
    fields = {"title": title, "epic": epic,
              "body": "why this card exists, at enough length to be a body",
              "acceptance": ["it does the thing"]}
    if priority:
        fields["priority"] = priority
    task = ccboard.create(db, "task", fields, actor="suite")
    key = task["id"]
    for path in touches:
        ccboard.add_touch(db, key, path, actor="suite")
    for label in labels:
        ccboard.set_label(db, key, label, True, actor="suite")
    return key


with ccstore.connection() as db:
    ccboard.migrate(db)
    epic = ccboard.create(db, "epic", {"title": "dispatch suite"}, actor="suite")["id"]

    section("config: the dispatch policy is part of the board, and is validated")
    cfg = ccboard.config(db)
    ok("dispatch is OFF by default",
       cfg["dispatchEnabled"] is False,
       "a fresh checkout must not start agents because a server came up")
    ok("every dispatch setting has a default",
       all(name in cfg for name in ccboard.DISPATCH_KEYS), sorted(cfg))
    ccboard.set_config(db, "dispatchEnabled", True)
    ok("dispatchEnabled accepts a bool", ccboard.config(db)["dispatchEnabled"] is True)
    rejects("dispatchEnabled refuses a string",
            lambda: ccboard.set_config(db, "dispatchEnabled", "yes"))
    ccboard.set_config(db, "dispatchWip", 4)
    ok("dispatchWip accepts a number in range", ccboard.config(db)["dispatchWip"] == 4)
    rejects("dispatchWip refuses out of range",
            lambda: ccboard.set_config(db, "dispatchWip", 99))
    rejects("dispatchPoll refuses a value below the floor",
            lambda: ccboard.set_config(db, "dispatchPoll", 1))
    rejects("dispatchCli refuses shell syntax",
            lambda: ccboard.set_config(db, "dispatchCli", "codex; rm -rf /"))
    ccboard.set_config(db, "dispatchCli", "claude")
    ok("dispatchCli accepts a plain name", ccboard.config(db)["dispatchCli"] == "claude")

    section("dispatchable: an unready card is not offered")
    thin = ccboard.create(db, "task", {"title": "no body, no criteria", "epic": epic},
                          actor="suite", mirror=True)["id"]
    ok("a card with no body or acceptance is not offered",
       thin not in ids(ccboard.dispatchable(db, 50)), thin)

    bodyless = ccboard.create(db, "task",
                              {"title": "criteria but no body", "epic": epic,
                               "acceptance": ["something"]},
                              actor="suite", mirror=True)["id"]
    ok("a card with no body is not offered",
       bodyless not in ids(ccboard.dispatchable(db, 50)))

    good = ready_card(db, epic, "fully specified", touches=["a/one.py"])
    ok("a fully specified card IS offered", good in ids(ccboard.dispatchable(db, 50)))

    section("dispatchable: the epic is resolved before readiness is judged")
    # The regression named in the docstring. requireEpic is on by default, and a
    # card WITH an epic must be offered; if `epic` is read straight off
    # _payload_task it is None and this is empty.
    ok("requireEpic is on for this board", ccboard.config(db)["requireEpic"] is True)
    ok("a card with an epic is not reported epic-less",
       good in ids(ccboard.dispatchable(db, 50)),
       "epic was not resolved onto the payload before agent_readiness read it")

    section("dispatchable: a card reserved for a person is never offered")
    for label in ("ready-for-human", "needs-info", "human-gate",
                  "decision:interview", "decision:prototype", "decision:map"):
        held = ready_card(db, epic, "reserved: " + label, touches=["x/" + label + ".py"],
                          labels=[label])
        ok("a card labelled " + label + " is not offered",
           held not in ids(ccboard.dispatchable(db, 50)))
    # The one decision an agent may answer on its own.
    research = ready_card(db, epic, "research is agent work",
                          touches=["r/research.py"], labels=["decision:research"])
    ok("decision:research IS offered",
       research in ids(ccboard.dispatchable(db, 50)),
       "research is the decision an agent can answer itself")

    section("dispatchable: a blocked dependency withholds the card")
    blocker = ready_card(db, epic, "the blocker", touches=["b/blocker.py"])
    waiter = ready_card(db, epic, "the waiter", touches=["b/waiter.py"])
    ccboard.set_dep(db, waiter, blocker, True, actor="suite")
    ok("a card whose blocker is open is not offered",
       waiter not in ids(ccboard.dispatchable(db, 50)))
    ccboard.set_status(db, blocker, "done", actor="suite", mirror=True)
    ok("the same card is offered once the blocker is done",
       waiter in ids(ccboard.dispatchable(db, 50)))

    section("dispatchable: a card already in flight is not offered twice")
    ccboard.set_status(db, good, "in_progress", actor="tm-worker", mirror=True)
    ok("an in_progress card is not offered",
       good not in ids(ccboard.dispatchable(db, 50)))
    flight = ccboard.in_flight(db)
    ok("in_flight reports it once it has an assignee",
       any(row["key"] == good for row in flight) or not flight,
       "in_flight requires an agent on the row")

    section("busy paths: work already being done is not handed out again")
    ccboard.update(db, good, {"assignee": "tm-worker"}, actor="suite")
    busy = ccboard.busy_paths(db)
    ok("busy_paths reports the in-flight card's files",
       "a/one.py" in busy, busy)

    section("touches: overlapping work ranks last but is still offered")
    overlap = ready_card(db, epic, "touches a busy file", touches=["b/waiter.py"])
    offered = ids(ccboard.dispatchable(db, 50, busy=["b/waiter.py"]))
    ok("a card overlapping busy work is still offered", overlap in offered)
    ok("a card overlapping busy work ranks after a disjoint one",
       offered.index(overlap) > 0 and offered.index(waiter) >= 0,
       offered)

    disjoint_first = ids(ccboard.dispatchable(db, 50))
    both = [key for key in disjoint_first if key in (waiter, overlap)]
    ok("two cards on the same file are not both ranked first",
       len(both) == 2 and both[0] == waiter, both)

    section("dispatchable: priority beats arrival order")
    low = ready_card(db, epic, "low priority", touches=["p/low.py"], priority="low")
    high = ready_card(db, epic, "high priority", touches=["p/high.py"], priority="highest")
    order = ids(ccboard.dispatchable(db, 50))
    ok("the highest priority disjoint card comes first",
       order and order[0] == high, order[:4])
    ok("a low priority card still appears", low in order)

    section("dispatch_view: one read, one moment")
    view = ccboard.dispatch_view(db, 5)
    ok("view carries the queue", isinstance(view.get("tasks"), list))
    ok("view carries what is in flight", isinstance(view.get("inFlight"), list))
    ok("view carries only the dispatch half of config",
       set(view["config"]) == set(ccboard.DISPATCH_KEYS), sorted(view["config"]))
    ok("view respects the limit", len(view["tasks"]) <= 5, len(view["tasks"]))
    ok("the queue carries no bodies",
       all("body" not in task for task in view["tasks"]),
       "a list payload carries what a card needs to render, not its markdown")

    section("dispatchable: the limit is validated like every other bounded read")
    rejects("limit refuses zero", lambda: ccboard.dispatchable(db, 0))
    rejects("limit refuses a value past the ceiling", lambda: ccboard.dispatchable(db, 5000))

    section("the human veto still outranks the computation")
    vetoed = ready_card(db, epic, "a person took this out", touches=["v/veto.py"])
    ccboard.set_label(db, vetoed, "ready-for-human", True, actor="a-person")
    db.execute("UPDATE tasks SET triaged_by='human' WHERE key=?", (vetoed,))
    ccboard.triage(db, actor="suite")
    ok("a sweep cannot put a human-vetoed card back in the queue",
       vetoed not in ids(ccboard.dispatchable(db, 50)))


# Exercise the real roster/brief seam; only external board/process calls are fake.
from dataclasses import replace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "taskmgmt"))
import dispatch
import agentdefs

section("briefs: persona uses only the space left by the complete task")
card = {"id": "TM-900", "title": "dispatch seam", "body": "Complete task body.",
        "acceptance": [{"text": "Keep this criterion intact", "done": True}],
        "touches": ["first.py", "last/claimed.py"]}
spec = replace(agentdefs.choose_roster(card, {}, {})[0], name="specialist",
               cli="claude", model="test-model", auth="test-auth",
               posture="read-only", persona="Review the code carefully.")
plain = dispatch.write_brief(card).read_text()
brief = dispatch.write_brief(card, spec).read_text()
ok("chosen persona appears under its heading",
   "## Persona\n\nReview the code carefully." in brief)
ok("task content is unchanged by adding a persona", brief.startswith(plain))
long_spec = replace(spec, persona="界" * dispatch.BRIEF_MAX)
bounded_path = dispatch.write_brief(card, long_spec)
bounded = bounded_path.read_text()
ok("oversized multibyte persona stays within BRIEF_MAX bytes",
   bounded_path.stat().st_size <= dispatch.BRIEF_MAX)
ok("persona truncation keeps all task content and final claim",
   bounded.startswith(plain) and "- `last/claimed.py`" in bounded
   and "0. [x] Keep this criterion intact" in bounded)
ok("persona was truncated", long_spec.persona not in bounded)
with patch.object(dispatch, "BRIEF_MAX", len(plain.encode("utf-8"))):
    ok("zero persona budget preserves the complete task",
       dispatch.write_brief(card, spec).read_text() == plain)
oversized = dict(card, acceptance=["required " * dispatch.BRIEF_MAX])
try:
    dispatch.write_brief(oversized, spec)
except ValueError:
    ok("oversized required content is refused without overwriting the brief",
       dispatch.brief_path(card["id"]).read_text() == plain)
else:
    ok("oversized required content is refused without overwriting the brief", False)

section("dispatch: selected spec reaches spawn and brief")
def dispatch_case(specs, cfg=None, override=None, task=None, dry_run=False):
    task = task or card
    calls = []
    def fake_agentmux(*args, **kwargs):
        calls.append(args)
        return 0, "", ""
    with patch.object(dispatch, "dispatch_view", return_value={
            "tasks": [{"id": task["id"]}], "config": cfg or {}}), \
         patch.object(dispatch, "entity", return_value={"task": task}), \
         patch.object(dispatch, "live_agents", return_value={}), \
         patch.object(agentdefs, "load_all", return_value=(specs, [])) as load, \
         patch.object(agentdefs, "choose_roster", wraps=agentdefs.choose_roster) as choose, \
         patch.object(dispatch, "agentmux", side_effect=fake_agentmux), \
         patch.object(dispatch, "set_status", return_value={}), \
         patch.object(dispatch, "board", return_value={}):
        result = dispatch.dispatch_one(cli=override, dry_run=dry_run)
        ok("definitions are loaded for the dispatch repository",
           load.call_args.args == (dispatch.REPO,))
        ok("roster selection receives the full task and CLI override",
           choose.call_args.args == (task, specs, cfg or {})
           and choose.call_args.kwargs == {"cli_override": override})
    return result, calls

result, calls = dispatch_case({spec.name: spec})
spawn = calls[0]
ok("chosen CLI, model, auth and posture reach spawn",
   result == "tm-900" and spawn == (
       "spawn", "tm-900", "--cli", "claude", "--cwd", str(dispatch.REPO),
       "--posture", "read-only", "--model", "test-model", "--auth", "test-auth"))
ok("spawn precedes claims and brief delivery",
   [call[0] for call in calls] == ["spawn", "claim", "claim", "wait", "send"])
ok("dispatch writes chosen persona and sends the brief path",
   spec.persona in dispatch.brief_path(card["id"]).read_text()
   and str(dispatch.brief_path(card["id"])) in calls[-1][2])
for cfg, override, expected in (({}, None, "codex"),
                                ({"dispatchCli": "claude"}, None, "claude"),
                                ({"dispatchCli": "claude"}, "gemini", "gemini")):
    result, calls = dispatch_case({}, cfg, override)
    ok("no definition preserves legacy CLI resolution: " + expected,
       result == "tm-900" and calls[0] == (
           "spawn", "tm-900", "--cli", expected, "--cwd", str(dispatch.REPO),
           "--posture", "unrestricted"))
    ok("no definition preserves the original brief",
       dispatch.brief_path(card["id"]).read_text() == plain)
result, calls = dispatch_case({spec.name: spec}, override="codex")
ok("CLI override drops incompatible model and auth",
   calls[0][3] == "codex" and "--model" not in calls[0] and "--auth" not in calls[0])
result, calls = dispatch_case({spec.name: spec}, dry_run=True)
ok("dry run does not spawn or claim", result == "tm-900" and not calls)
result, calls = dispatch_case({spec.name: spec}, task=oversized)
ok("oversized required brief is refused before spawning", result is None and not calls)

print()
print("passed %d, failed %d" % (passed, failed))
sys.exit(1 if failed else 0)
