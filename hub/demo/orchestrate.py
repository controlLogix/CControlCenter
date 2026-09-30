"""Run one orchestration scenario on the hub and score it. See hub/demo/README.md.

    python3 hub/demo/orchestrate.py <scenario> [--timeout-min 30] [--keep]

Runs as the OPERATOR (outside any pane). It registers repos, spawns agents through
`agentmux hub spawn`, posts the scenario's work, then watches the hub until every
top-level item is terminal or the timeout hits. It never types into a pane itself:
all delivery goes through the hub, which is the thing under test.

A run is ERROR-FREE only if all of these hold (scored in the report):
  E1  every top-level work item ended 'done'
  E2  no delivery ended 'dead'
  E3  no doorbell outcome 'failed' (text left unsubmitted / identity mismatch)
  E4  no agent went 'blocked' on a modal that needed a person, and none died
  E5  every message delivered to a live agent was acked
  E6  the scenario's own verification (repo tests, file checks) passed
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from hub.cli import Fail, call  # noqa: E402

BASE = os.environ.get("HUBDEMO_BASE", os.path.expanduser("~/hubdemo"))
RESULTS = os.path.join(os.path.dirname(os.path.dirname(HERE)), "evals", "orchestrations")


def sh(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr)[-2000:]


def tests_pass(repo):
    return sh(["python3", "-m", "unittest", "discover", "-s", "tests"], cwd=os.path.join(BASE, repo))


# -- scenarios ----------------------------------------------------------------------------
# Each: agents to spawn, teams, work to post, and a verify() -> (ok, detail).
# Agent tuples: (repo, role, agent, cli)

def sc_calib(tag):
    return {
        "agents": [("calc", "worker", f"codex_{tag}", "codex")],
        "teams": [],
        "work": [dict(to="role:calc/worker", title="Add calc.median",
                      body="In the calc repo checkout, add a function median(xs) to calc/__init__.py (raise ValueError "
                           "on empty input; average the two middle values for even length). Add tests for odd, even "
                           "and empty input to tests/test_calc.py. Run the tests. Commit with message 'add median'.")],
        "verify": lambda: _verify_fn("calc", "median", "from calc import median; assert median([3,1,2])==2 and median([1,2,3,4])==2.5"),
    }


def sc_team(tag):
    """O2: team work - the lead decomposes into worker and reviewer items."""
    return {
        "agents": [("calc", "lead", f"claude_{tag}", "claude"),
                   ("calc", "worker", f"codex_{tag}", "codex"),
                   ("calc", "reviewer", f"grok_{tag}", "grok")],
        "teams": [("calc", f"t_{tag}")],
        "work": [dict(to=f"team:calc/t_{tag}", title="Add variance and stdev to calc",
                      body="Goal: calc gains variance(xs) (population variance) and stdev(xs) (its square root), both "
                           "raising ValueError on empty input, with unit tests, committed.\n"
                           "As lead: create ONE work item for your team's worker role to implement both with tests, and "
                           f"after its result arrives, ONE work item for your team's reviewer role (use --to "
                           f"role:team:calc/t_{tag}/worker and role:team:calc/t_{tag}/reviewer, each with --parent <this "
                           "item id>). If the reviewer rejects, send the fixes back to a worker item and review again. "
                           "When the review approves, mark this item done with a one-line summary.")],
        "verify": lambda: _verify_fn("calc", "stdev", "from calc import variance, stdev; assert abs(variance([1,2,3,4])-1.25)<1e-9 and abs(stdev([2,4,4,4,5,5,7,9])-2.0)<1e-9"),
    }


def sc_crossrepo(tag):
    """O3: cross-repo - report's lead needs a function from the calc repo."""
    return {
        "agents": [("report", "lead", f"claude_{tag}", "claude"),
                   ("calc", "worker", f"codex_{tag}", "codex"),
                   ("report", "worker", f"grok_{tag}", "grok")],
        "teams": [("report", f"r_{tag}")],
        "work": [dict(to=f"team:report/r_{tag}", title="Report shows the median",
                      body="Goal: report.summary(name, xs) returns 'NAME: n=N mean=M.MM median=D.DD' (median to 2 decimals), "
                           "using a median(xs) function that must live in the OTHER repo, calc (checkout ~/hubdemo/calc), "
                           "with tests in both repos, committed in both.\n"
                           "As lead: (1) if calc has no median yet, create a work item for role:calc/worker (the calc "
                           "repo's workers are not on your team - that is expected) with --parent <this item id> asking "
                           "for median with tests; (2) after its result arrives, create a work item for "
                           f"role:team:report/r_{tag}/worker with --parent <this item id> to update report.summary and "
                           "its test; (3) verify both repos' tests pass (python3 -m unittest discover -s tests in "
                           "each), then mark this item done.")],
        "verify": lambda: _verify_all(
            _verify_fn("calc", "median", "from calc import median; assert median([1,2,3,4])==2.5"),
            _verify_fn("report", "summary", "from report import summary; s=summary('a',[1,2,3,4]); assert 'median=2.50' in s, s")),
    }


def sc_swarm(tag):
    """O4: first-claim contention - 3 workers of mixed CLIs, 4 role items, one repo."""
    fns = [("clamp", "clamp(x, lo, hi) returns x limited to [lo, hi]; ValueError if lo > hi",
            "from calc import clamp; assert clamp(5,0,3)==3 and clamp(-1,0,3)==0"),
           ("product", "product(xs) returns the product of xs (1 for empty input)",
            "from calc import product; assert product([2,3,4])==24 and product([])==1"),
           ("rng", "rng(xs) returns max(xs) - min(xs); ValueError on empty input",
            "from calc import rng; assert rng([3,9,1])==8"),
           ("mode", "mode(xs) returns the most common value, the smallest one on ties; ValueError on empty input",
            "from calc import mode; assert mode([1,2,2,3,3])==2")]
    return {
        "agents": [("calc", "worker", f"codex_{tag}", "codex"),
                   ("calc", "worker", f"claude_{tag}", "claude"),
                   ("calc", "worker", f"grok_{tag}", "grok")],
        "teams": [],
        "work": [dict(to="role:calc/worker", title=f"Add calc.{n}",
                      body=f"In the calc repo checkout, add {d} to calc/__init__.py, with unit tests in "
                           f"tests/test_calc.py. Other workers are editing the same files at the same time: before "
                           f"committing, run `git pull --rebase` is NOT available (no remote) - instead re-read the file "
                           f"right before editing, keep your edit minimal, run the tests, then `git add -A && git commit "
                           f"-m 'add {n}'` (retry the commit if the index is locked).") for n, d, _c in fns],
        "verify": lambda: _verify_all(*[_verify_fn("calc", n, c) for n, _d, c in fns]),
    }


SCENARIOS = {"calib": sc_calib, "team": sc_team, "crossrepo": sc_crossrepo, "swarm": sc_swarm}


def _verify_fn(repo, name, code):
    rc, out = tests_pass(repo)
    if rc != 0:
        return False, f"{repo} tests fail: {out[-600:]}"
    rc2, out2 = sh(["python3", "-c", code], cwd=os.path.join(BASE, repo))
    if rc2 != 0:
        return False, f"{repo}.{name} check failed: {out2[-400:]}"
    rc3, log = sh(["git", "log", "--oneline", "-5"], cwd=os.path.join(BASE, repo))
    dirty = sh(["git", "status", "--porcelain"], cwd=os.path.join(BASE, repo))[1].strip()
    return True, f"{repo}: tests pass, {name} ok; log: {log.strip().splitlines()[0] if log.strip() else '-'}" + \
        (f"; UNCOMMITTED: {dirty[:200]}" if dirty else "")


def _verify_all(*results):
    ok = all(r[0] for r in results)
    return ok, " | ".join(r[1] for r in results)


# -- run ----------------------------------------------------------------------------------
def main():
    args = sys.argv[1:]
    name = args[0]
    timeout_min = float(args[args.index("--timeout-min") + 1]) if "--timeout-min" in args else 30
    keep = "--keep" in args
    tag = time.strftime("%H%M")
    sc = SCENARIOS[name](tag)
    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{name}"
    os.makedirs(RESULTS, exist_ok=True)
    report = {"run": run_id, "scenario": name, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "agents": [],
              "work": [], "errors": [], "timeline": []}

    def note(msg):
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        report["timeline"].append(line)

    subprocess.run(["bash", os.path.join(HERE, "setup_repos.sh"), "--reset"], capture_output=True)
    subprocess.run([os.path.expanduser("~/.local/bin/agentmux"), "hub", "start"], capture_output=True)
    for repo in ("calc", "report"):
        call("repo_add", {"repo": repo, "paths": [os.path.join(BASE, repo)], "groups": ["demo"]})
    ev0 = max([e["seq"] for e in call("events", {"since": 0, "limit": 100000})["result"]] or [0])

    sessions = []
    for repo, role, agent, cli in sc["agents"]:
        r = call("spawn", {"repo": repo, "role": role, "agent": agent, "cli": cli}, timeout=180)["result"]
        sessions.append(r["session"])
        note(f"spawned {r['session']} ({cli}) {r['handle']}")
    for repo, team in sc["teams"]:
        members = [s for s in sessions if s.startswith(repo + "-")]
        call("team_add", {"repo": repo, "team": team, "members": members})
        note(f"team {repo}/{team}: {', '.join(members)}")
    report["agents"] = sessions

    tops = []
    for w in sc["work"]:
        r = call("work_add", w)["result"]
        tops.append(r["id"])
        note(f"posted {r['id']} -> {r['target']}: {r['title']}")

    deadline = time.time() + timeout_min * 60
    last = {}
    while time.time() < deadline:
        states = {}
        for wid in tops:
            w = call("work_show", {"work_id": wid})["result"]
            states[wid] = w["state"]
            sig = (w["state"], tuple((c["id"], c["state"], c["claimed_by"]) for c in w.get("children") or []),
                   w.get("claimed_by"))
            if last.get(wid) != sig:
                last[wid] = sig
                kids = ", ".join(f"{c['id']}[{c['state']}:{c['claimed_by'] or '-'}]" for c in w.get("children") or [])
                note(f"{wid} {w['state']} by {w.get('claimed_by') or '-'}" + (f" children: {kids}" if kids else ""))
        st = call("status")["result"]
        for a in st["agents"]:
            if a["session"] in sessions and a["state"] in ("blocked", "dead"):
                key = ("agent", a["session"], a["state"], a["state_note"])
                if key not in last:
                    last[key] = True
                    note(f"AGENT {a['session']} {a['state']}: {a['state_note']}")
        if all(s in ("done", "failed", "cancelled") for s in states.values()):
            break
        if any(a["session"] in sessions and a["state"] == "dead" for a in st["agents"]):
            note("an agent died; stopping early (the run is already not error-free)")
            break
        time.sleep(10)

    # -- score ----------------------------------------------------------------------------
    evs = [e for e in call("events", {"since": ev0, "limit": 100000})["result"]]
    all_work = call("work_list", {})["result"]
    mine = {w["id"]: w for w in all_work if w["id"] in tops or w.get("parent_id") in tops}
    # grandchildren too
    for w in all_work:
        if w.get("parent_id") in mine:
            mine[w["id"]] = w
    report["work"] = [{k: w[k] for k in ("id", "parent_id", "target", "title", "state", "claimed_by", "attempts", "result")}
                      for w in mine.values()]
    bells = [e for e in evs if e["entity"] == "bell"]
    dels = [e for e in evs if e["entity"] == "delivery" and any(e["entity_id"].endswith(">" + s) for s in sessions)]
    final = {}
    for e in dels:
        final[e["entity_id"]] = e["event"]
    agent_ev = [e for e in evs if e["entity"] == "agent" and e["entity_id"] in sessions]
    checks = {}
    checks["E1_all_top_done"] = all(mine[t]["state"] == "done" for t in tops)
    checks["E2_no_dead_delivery"] = not any(v == "dead" for v in final.values())
    checks["E3_no_failed_bell"] = not any(b["event"] == "failed" for b in bells)
    checks["E4_no_blocked_or_died"] = not any(e["event"] in ("blocked", "dead") for e in agent_ev
                                              if "killed by operator" not in (e["detail"] or ""))
    checks["E5_all_acked"] = all(v == "acked" for v in final.values())
    ok, detail = sc["verify"]()
    checks["E6_verified"] = ok
    report["verify"] = detail
    report["checks"] = checks
    report["error_free"] = all(checks.values())
    report["stats"] = {
        "deliveries": len(final), "acked": sum(1 for v in final.values() if v == "acked"),
        "bells": {k: sum(1 for b in bells if b["event"] == k) for k in sorted({b["event"] for b in bells})},
        "modal_answers": [json.loads(b["detail"]).get("modal_answers") for b in bells
                          if b["detail"] and json.loads(b["detail"]).get("modal_answers")],
        "extra_enters": sum(max(0, json.loads(b["detail"]).get("enters", 1) - 1) for b in bells if b["detail"]),
        "work_items": len(mine), "duration_s": int(time.time() - (deadline - timeout_min * 60)),
    }
    for b in bells:
        if b["event"] in ("failed", "blocked"):
            report["errors"].append(f"bell {b['entity_id']} {b['event']}: {json.loads(b['detail']).get('reason')}")
    for e in agent_ev:
        if e["event"] in ("blocked", "dead"):
            report["errors"].append(f"agent {e['entity_id']} {e['event']}: {e['detail']}")
    for k, v in final.items():
        if v != "acked":
            report["errors"].append(f"delivery {k} ended {v}")

    # pane tails for the record, then teardown
    report["pane_tails"] = {}
    for s in sessions:
        rc, out = sh(["tmux", "-L", "agentmux", "capture-pane", "-p", "-J", "-t", s])
        report["pane_tails"][s] = "\n".join([l for l in out.splitlines() if l.strip()][-25:])
    if not keep:
        for s in sessions:
            try:
                call("kill", {"session": s, "reason": "orchestration finished"})
            except Fail:
                pass
    with open(os.path.join(RESULTS, f"{run_id}.json"), "w") as f:
        json.dump(report, f, indent=2, default=str)
    note(f"ERROR-FREE={report['error_free']} checks={checks}")
    note(f"verify: {detail}")
    for e in report["errors"]:
        note(f"  error: {e}")
    note(f"report: {os.path.join(RESULTS, run_id + '.json')}")


if __name__ == "__main__":
    main()
