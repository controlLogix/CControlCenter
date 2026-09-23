#!/usr/bin/env python3
"""Dispatch: turning a board card into a running agent, and back again.

WHY THIS EXISTS
---------------
The board could say what was ready and agentmux could run an agent, and nothing
joined the two. So "use the task board" meant a person reading the queue, picking
a card, typing `spawn`, typing `claim`, pasting a brief, and remembering to move
the status. Every one of those is a step a machine should take, and every one of
them got skipped under load - which is how a board full of startable work came to
sit next to three idle agents.

This module is that join and nothing more. It does not decide what is ready:
`/api/board/dispatchable` does, because readiness is board policy and a dispatcher
that re-derived it would be a second opinion able to disagree with the gates. It
does not run agents: `agentmux spawn` does. It owns exactly the sequence between
them, and the sequence back.

THE SEQUENCE, AND WHY IT IS THIS ORDER
--------------------------------------
    spawn -> claim -> start -> brief

Claiming before spawning is impossible: a claim must be held by a LIVE agent
(coordination.resolve_identity), and a name nobody has spawned is not live.
Briefing before claiming is too late: the agent is already reading the card. So
the worker is spawned, claims its files while still sitting at an empty prompt,
and is briefed only once those files are actually its own. If a claim is refused,
the worker is killed and the card is left exactly as it was found.

`start` goes through the board's own gate. This module never writes a status it
has decided is allowed - it asks, and a refusal (HTTP 409) is the answer rather
than an error to route around. That is why an unready card cannot be dispatched
even by calling this directly: the gate is not in this file.

WHAT COLLECT DOES NOT DO
------------------------
It never closes a task. A worker that finished is a worker that CLAIMS to have
finished, and `requireOnDone` wants evidence and an actor. Collect reconciles the
world - releases claims, reaps the pane, parks what died - and leaves the closing
judgement to the gate, the only thing entitled to make it.

    python3 taskmgmt/dispatch.py dispatch [TM-014] [--cli codex] [--dry-run]
    python3 taskmgmt/dispatch.py collect  [TM-014] [--all]
    python3 taskmgmt/dispatch.py pool     once|start|stop|status|resume
    python3 taskmgmt/dispatch.py status   [--json]
"""
import argparse
import errno
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coordination                                    # noqa: E402  reuse, do not restate

ROOT = Path(os.environ.get("AGENTMUX_HOME", str(Path.home() / ".agentmux")))
DISPATCH_DIR = ROOT / "dispatch"
POOL_PID = DISPATCH_DIR / "pool.pid"
POOL_LOG = DISPATCH_DIR / "pool.log"
POOL_STATE = DISPATCH_DIR / "pool.state.json"

REPO = Path(__file__).resolve().parent.parent
KEY_RE = coordination.KEY_RE

# A dispatched worker is named for the card it holds, lowercased. That is not
# cosmetic: `collect` must be able to tell a worker this module started from one a
# person spawned by hand, and the alternative - a registry file - is a second
# source of truth that can disagree with tmux. The name IS the registry.
WORKER_RE = re.compile(r"(ep|tm|adr|sp|cap)-[0-9]{3,9}")
BRIEF_MAX = 8192
POOL_STALE_S = 120


def now():
    return coordination.now()


def worker_name(key):
    return key.lower()


def key_of_worker(name):
    """The card a worker name refers to, or None if it is not a dispatched worker."""
    if not WORKER_RE.fullmatch(name or ""):
        return None
    key = name.upper()
    return key if KEY_RE.match(key) else None


# True only inside the detached pool loop, where pool_start has already pointed
# stdout AT the log file. Without it every line the pool writes lands twice - once
# through print, once through the append below - and a log that repeats itself
# reads like the loop is running twice, which is the wrong thing to debug at the
# moment you are reading a log to find out what happened.
_STDOUT_IS_LOG = False


def log(message):
    """One line on stdout, and in the pool log unless stdout already is it."""
    line = "%s  %s" % (now(), message)
    print(line, flush=True)
    if _STDOUT_IS_LOG:
        return
    try:
        DISPATCH_DIR.mkdir(parents=True, exist_ok=True)
        with POOL_LOG.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


# ── the board side ───────────────────────────────────────────────────────────

def board(method, path, body=None):
    """A board call whose failure is a message rather than a traceback."""
    return coordination.board_call(method, path, body)


def dispatch_view(limit=10):
    return board("GET", "board/dispatchable?limit=%d" % limit)


def entity(key):
    return board("GET", "board/entity?id=" + key)


def set_status(key, status, actor, session=None, reason=None):
    body = {"id": key, "status": status, "actor": actor}
    if session:
        body["session"] = session
    if reason:
        body["reason"] = reason
    return board("POST", "board/status", body)


def comment(key, text, actor):
    return board("POST", "board/comment", {"id": key, "text": text[:1000], "actor": actor})


# ── the agentmux side ────────────────────────────────────────────────────────

def agentmux_bin():
    """How to invoke agentmux from here.

    The repo copy carries CRLF line endings (this checkout lives on a Windows
    drive) and bash will not run that - it reports a missing command named for a
    carriage return. The installed copy is already clean, so it is preferred; the
    repo copy is the fallback and is stripped on the way in, the same way
    restart.sh does it.
    """
    explicit = os.environ.get("AGENTMUX_BIN")
    if explicit:
        return [explicit]
    found = shutil.which("agentmux")
    if found:
        return [found]
    local = Path.home() / ".local" / "bin" / "agentmux"
    if local.is_file():
        return [str(local)]
    script = 'exec bash <(tr -d "\\r" < "$0") "$@"'
    return ["bash", "-c", script, str(REPO / "agentmux.sh")]


def agentmux(*args, timeout=180):
    """Run one agentmux verb. Returns (rc, stdout, stderr)."""
    cmd = agentmux_bin() + list(args)
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as err:
        return 1, "", str(err)
    return done.returncode, done.stdout or "", done.stderr or ""


def live_agents():
    return coordination.live_agents()


# ── briefs ───────────────────────────────────────────────────────────────────

def brief_path(key):
    return DISPATCH_DIR / ("%s.md" % key)


def write_brief(task):
    """The handoff, on disk.

    Deliberately a FILE the agent is pointed at rather than text typed into the
    pane. A brief pasted as keystrokes is at the mercy of the CLI's input handling
    - bracketed paste, autocomplete, a modal that eats the first line - and a
    truncated brief is worse than none, because the agent acts on the half it got.
    """
    key = task["id"]
    lines = [
        "# %s  %s" % (key, task.get("title") or ""),
        "",
        "You are a dispatched worker. This card is yours and its files are claimed",
        "in your name. RULE #-0.7 applies: claim before editing anything outside the",
        "list below, journal what you do, and do not touch another agent's files.",
        "",
        "- board key: **%s**" % key,
        "- epic: %s" % (task.get("epic") or "-"),
        "- priority: %s" % (task.get("priority") or "-"),
        "- type: %s" % (task.get("type") or "-"),
        "",
    ]
    if task.get("body"):
        lines += ["## What and why", "", str(task["body"]).strip(), ""]
    acceptance = task.get("acceptance") or []
    if acceptance:
        lines += ["## Acceptance criteria", ""]
        for index, item in enumerate(acceptance):
            text = item.get("text") if isinstance(item, dict) else str(item)
            ticked = bool(item.get("done")) if isinstance(item, dict) else False
            lines.append("%d. [%s] %s" % (index, "x" if ticked else " ", text))
        lines.append("")
    touches = task.get("touches") or []
    if touches:
        lines += ["## Files claimed for you", ""]
        lines += ["- `%s`" % item for item in touches]
        lines.append("")
    lines += [
        "## When you are done",
        "",
        "Attach evidence and say so on the board, then stop. Do NOT close the card",
        "yourself - the gate wants evidence and an actor, and the orchestrator",
        "collects:",
        "",
        "    agentmux task evidence %s <path-or-url>" % key,
        "    agentmux task comment  %s \"what you did\"" % key,
        "",
        "If you are blocked, say why on the card and stop rather than guessing:",
        "",
        "    agentmux task block %s --reason \"...\"" % key,
        "",
    ]
    text = "\n".join(lines)[:BRIEF_MAX]
    DISPATCH_DIR.mkdir(parents=True, exist_ok=True)
    brief_path(key).write_text(text, encoding="utf-8")
    return brief_path(key)


# ── claims ───────────────────────────────────────────────────────────────────

def claim_for(worker, key, paths, note):
    """Claim every path for the worker. All or nothing.

    Partial ownership is the worst outcome available: the agent edits what it got
    and blocks on what it did not, holding the rest of the queue behind it. So a
    refusal anywhere rolls the whole set back.
    """
    taken = []
    for path in paths:
        rc, out, err = agentmux("claim", path, "--for", worker,
                                "--task", key, "--note", note[:200])
        if rc != 0:
            for done in taken:
                agentmux("release", done, "--for", worker)
            return False, (err or out or "claim refused").strip().splitlines()[0]
        taken.append(path)
    return True, ""


def release_all(worker, paths):
    for path in paths:
        agentmux("release", path, "--for", worker)


# ── dispatch ─────────────────────────────────────────────────────────────────

def pick(view, wanted=None):
    """The card to dispatch, or (None, reason)."""
    tasks = view.get("tasks") or []
    if wanted:
        for task in tasks:
            if task["id"] == wanted:
                return task, ""
        return None, "%s is not dispatchable right now" % wanted
    if not tasks:
        return None, "nothing ready for an agent"
    return tasks[0], ""


def dispatch_one(key=None, cli=None, dry_run=False, limit=10, quiet=False):
    """Hand one card to a fresh agent. Returns the worker name, or None.

    `quiet` suppresses the "nothing ready" line. The pool asks on every tick and an
    empty queue is its normal state, so logging it would write a line every
    dispatchPoll seconds forever - a log that is almost entirely the word "no" is
    one nobody reads, which defeats having one. A person who typed `dispatch` is
    owed the answer, so the default stays loud.
    """
    view = dispatch_view(limit)
    if view is None:
        return None
    cfg = view.get("config") or {}
    task, why = pick(view, key)
    if task is None:
        if not quiet:
            log("dispatch: " + why)
        return None

    key = task["id"]
    worker = worker_name(key)
    cli = cli or cfg.get("dispatchCli") or "codex"

    if worker in live_agents():
        log("dispatch: %s already has a worker (%s)" % (key, worker))
        return None

    # The full record, because the list payload has its body stripped and the body
    # is most of the brief.
    full = entity(key)
    if full is None:
        return None
    task = full.get("task") or full.get("entity") or full

    if dry_run:
        log("dispatch: would spawn %s [%s] for %s - %s"
            % (worker, cli, key, task.get("title") or ""))
        return worker

    rc, out, err = agentmux("spawn", worker, "--cli", cli, "--cwd", str(REPO))
    if rc != 0:
        log("dispatch: spawn failed for %s: %s" % (key, (err or out).strip()[:200]))
        return None

    touches = list(task.get("touches") or [])
    ok, refusal = claim_for(worker, key, touches, "dispatched for " + key)
    if not ok:
        # Someone else holds a file this card needs. Leave the card untouched and
        # take the worker away again - a spawned agent with no work and no claim is
        # a context leak, and the next poll will retry.
        agentmux("kill", worker)
        log("dispatch: %s not claimable (%s)" % (key, refusal[:160]))
        return None

    started = set_status(key, "in_progress", worker, session=worker)
    if started is None:
        release_all(worker, touches)
        agentmux("kill", worker)
        log("dispatch: board refused to start %s; worker withdrawn" % key)
        return None

    board("POST", "board/update", {"id": key, "actor": worker,
                                   "patch": {"assignee": worker, "session": worker}})
    path = write_brief(task)

    # Let the CLI finish coming up before typing at it. A fresh pane is the most
    # likely moment for a modal - a directory-trust dialog, an update prompt, a
    # rate-limit notice - and `send` correctly refuses to type into one, because
    # Enter would actuate the prompt's default instead of talking to the agent.
    agentmux("wait", worker, "--timeout", "60", "--quiet", "3", timeout=90)
    pointer = "Read %s and do the work it describes. It is your brief." % path
    rc, out, err = agentmux("send", worker, pointer)
    if rc != 0:
        # UNDELIVERED IS NOT DISPATCHED. Leaving a worker up with a brief it never
        # received is the worst outcome available: the card reads in_progress, its
        # files are claimed, a slot is consumed, and the agent is sitting at a
        # prompt doing nothing. On the board that is indistinguishable from
        # progress, and it holds the queue behind it.
        #
        # But a refused send is usually a MODAL, not a dead agent - a fresh pane is
        # the likeliest moment for a directory-trust dialog, an update prompt or a
        # rate-limit notice, and `send` refuses rather than press Enter on someone
        # else's dialog. That is a wait, not a failure, and the courier already
        # solves waiting: it retries a recipient that is down or showing a modal,
        # and dead-letters after five attempts rather than dropping it silently.
        #
        # So the fast path is a direct send, and the fallback is the queue. Only a
        # failure to even QUEUE the brief is a failure to dispatch.
        queued, qout, qerr = agentmux("post", worker, "--kind", "request", pointer)
        if queued != 0:
            withdraw(worker, key, touches,
                     "brief could not be delivered or queued: "
                     + (qerr or qout or err or "send refused").strip().splitlines()[0])
            return None
        comment(key, "brief queued for %s rather than typed: the pane was showing a "
                     "prompt. The courier will deliver it." % worker, "orchestrator")
        log("dispatch: %s -> %s [%s] (brief queued - pane busy)  %s"
            % (key, worker, cli, task.get("title") or ""))
        return worker
    log("dispatch: %s -> %s [%s]  %s" % (key, worker, cli, task.get("title") or ""))
    return worker


def withdraw(worker, key, touches, reason):
    """Undo a dispatch that did not take. Leaves the card exactly as it was found."""
    release_all(worker, touches)
    agentmux("kill", worker)
    set_status(key, "open", "orchestrator")
    # Clear the assignee too. A card that reads open but still names a worker that
    # was killed is a board saying two things at once, and the next reader believes
    # the wrong one.
    board("POST", "board/update", {"id": key, "actor": "orchestrator",
                                   "patch": {"assignee": None, "session": None}})
    comment(key, "dispatch withdrawn: " + reason, "orchestrator")
    log("dispatch: %s withdrawn - %s" % (key, reason[:200]))


# ── collect ──────────────────────────────────────────────────────────────────

def dispatched_now():
    """Workers this module started, as {worker: key}, from tmux and nowhere else."""
    out = {}
    for name in live_agents():
        key = key_of_worker(name)
        if key:
            out[name] = key
    return out


def collect_one(key, task=None):
    """Reconcile one dispatched card with the world. Never closes it."""
    task = task or (entity(key) or {}).get("task") or entity(key)
    if not task:
        return None
    worker = worker_name(key)
    touches = list(task.get("touches") or [])
    alive = worker in live_agents()
    status = task.get("status")

    if alive and status == "in_progress":
        # A dispatched CLI does not exit when it finishes - codex and claude both
        # return to their prompt and sit there. So "the pane is gone" cannot be the
        # only completion signal, or a finished worker holds its slot and its files
        # forever and the pool stops after dispatchWip cards.
        #
        # `wait` already answers "is this CLI still working": 0 idle, 2 still busy,
        # 3 exited. It reads the CLI's own busy marker, so the usual case returns
        # in well under a second and a short timeout is not a guess.
        rc, _, _ = agentmux("wait", worker, "--timeout", "3", timeout=30)
        if rc == 2:
            return {"id": key, "outcome": "working"}
        if rc == 0:
            if not (task.get("evidence") or []):
                # Idle with nothing to show. NOT killed: an agent between turns and
                # an agent that is stuck look identical from here, and throwing away
                # a half-finished piece of work to reclaim a slot is the wrong trade.
                # Surfaced instead, so a person can look.
                return {"id": key, "outcome": "idle"}
            # Finished as briefed: evidence attached, card left open. Free the slot
            # and the files; the card stays in_progress because closing it is the
            # done gate's judgement, not the collector's.
            release_all(worker, touches)
            agentmux("kill", worker)
            comment(key, "worker %s finished and was reaped; evidence attached, "
                         "card left in_progress for review." % worker, "orchestrator")
            log("collect: %s submitted by %s; claims released, pane reaped"
                % (key, worker))
            return {"id": key, "outcome": "submitted"}

    # The worker is gone, or the card moved. Either way its files are no longer
    # its own.
    release_all(worker, touches)
    if alive:
        agentmux("kill", worker)

    if status in ("done", "deleted"):
        log("collect: %s finished (%s); worker reaped" % (key, status))
        return {"id": key, "outcome": status}
    if status == "blocked":
        log("collect: %s blocked by its worker; claims released" % key)
        return {"id": key, "outcome": "blocked"}

    # In progress with no worker: the agent died, was killed, or exited without
    # saying anything. Park rather than reopen - "this was tried and did not
    # finish" is information, and an open card silently re-enters the queue and is
    # dispatched again forever.
    reason = "dispatched worker %s exited without completing" % worker
    if set_status(key, "parked", "orchestrator", reason=reason) is not None:
        comment(key, reason + ". Brief: %s" % brief_path(key), "orchestrator")
        log("collect: %s parked (%s)" % (key, reason))
        return {"id": key, "outcome": "parked"}
    return {"id": key, "outcome": "unresolved"}


def collect_all():
    """Every card that is in flight or was, as far as the board is concerned."""
    view = dispatch_view(1)
    if view is None:
        return []
    results = []
    for row in view.get("inFlight") or []:
        key = row.get("key")
        if key and key_of_worker(worker_name(key)):
            outcome = collect_one(key)
            if outcome:
                results.append(outcome)
    return results


# ── the pool ─────────────────────────────────────────────────────────────────

def read_state():
    try:
        return json.loads(POOL_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_state(patch):
    state = read_state()
    state.update(patch)
    DISPATCH_DIR.mkdir(parents=True, exist_ok=True)
    POOL_STATE.write_text(json.dumps(state), encoding="utf-8")
    return state


def pool_alive():
    """The live pool's pid, or None. A pid file alone proves nothing."""
    try:
        pid = int(POOL_PID.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except OSError as err:
        if err.errno == errno.ESRCH:
            return None
        if err.errno != errno.EPERM:
            return None
    return pid


def pool_once():
    """One tick: collect what finished, then fill the free slots.

    Collect runs FIRST, always. Dispatching before collecting counts a dead
    worker's slot as occupied, so a pool whose workers all died would sit at its
    WIP limit forever, doing nothing, reporting itself full.
    """
    collected = collect_all()
    view = dispatch_view(20)
    if view is None:
        return {"collected": collected, "dispatched": [], "error": "board unreachable"}
    cfg = view.get("config") or {}
    if not cfg.get("dispatchEnabled"):
        return {"collected": collected, "dispatched": [], "disabled": True}
    wip = int(cfg.get("dispatchWip") or 0)
    running = len(dispatched_now())
    started = []
    while running + len(started) < wip:
        worker = dispatch_one(cli=cfg.get("dispatchCli"), limit=20, quiet=True)
        if not worker:
            break
        started.append(worker)
    return {"collected": collected, "dispatched": started}


def pool_loop():
    """The detached loop. Config is re-read every tick, on purpose: turning the
    pool off should not require finding and killing a process."""
    write_state({"startedAt": now(), "failures": 0, "paused": False})
    idle_since = time.time()
    while True:
        POOL_PID.write_text(str(os.getpid()), encoding="utf-8")
        state = read_state()
        result = pool_once()
        if result.get("error"):
            failures = int(state.get("failures") or 0) + 1
            write_state({"failures": failures, "lastError": result["error"]})
            view_cfg = {}
        else:
            failures = 0
            write_state({"failures": 0, "lastTick": now()})
        view = dispatch_view(1) or {}
        cfg = view.get("config") or {}
        if failures and failures >= int(cfg.get("dispatchMaxFailures") or 3):
            log("pool: %d consecutive failures; pausing" % failures)
            write_state({"paused": True})
            break
        if result.get("dispatched") or result.get("collected"):
            idle_since = time.time()
        idle_exit = int(cfg.get("dispatchIdleExit") or 0)
        if idle_exit and (time.time() - idle_since) > idle_exit * 60:
            log("pool: idle for %d minutes; exiting" % idle_exit)
            break
        time.sleep(max(5, int(cfg.get("dispatchPoll") or 20)))
    POOL_PID.unlink(missing_ok=True)


def pool_start():
    existing = pool_alive()
    if existing:
        return "pool already running (pid %d)" % existing
    DISPATCH_DIR.mkdir(parents=True, exist_ok=True)
    handle = POOL_LOG.open("a", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "pool", "run-loop"],
        stdout=handle, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        start_new_session=True)
    POOL_PID.write_text(str(process.pid), encoding="utf-8")
    return "pool started (pid %d), log %s" % (process.pid, POOL_LOG)


def pool_stop():
    pid = pool_alive()
    if not pid:
        POOL_PID.unlink(missing_ok=True)
        return "no pool running"
    try:
        os.kill(pid, 15)
    except OSError as err:
        return "could not stop pid %d: %s" % (pid, err)
    POOL_PID.unlink(missing_ok=True)
    return "pool stopped (pid %d)" % pid


def pool_status():
    view = dispatch_view(20) or {}
    cfg = view.get("config") or {}
    running = dispatched_now()
    state = read_state()
    return {
        "pid": pool_alive(),
        "enabled": bool(cfg.get("dispatchEnabled")),
        "wip": cfg.get("dispatchWip"),
        "workers": running,
        "ready": [task["id"] for task in view.get("tasks") or []],
        "paused": bool(state.get("paused")),
        "failures": state.get("failures") or 0,
        "log": str(POOL_LOG),
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def cmd_dispatch(args):
    worker = dispatch_one(args.id, args.cli, args.dry_run)
    return 0 if worker else 1


def cmd_collect(args):
    if args.id:
        result = collect_one(args.id)
        if result is None:
            return 1
        print("%s: %s" % (result["id"], result["outcome"]))
        return 0
    results = collect_all()
    if not results:
        print("nothing in flight")
    for result in results:
        print("%s: %s" % (result["id"], result["outcome"]))
    return 0


def cmd_pool(args):
    action = args.action
    if action == "run-loop":                 # internal: what pool_start execs
        global _STDOUT_IS_LOG
        _STDOUT_IS_LOG = True                # stdout is already POOL_LOG; see log()
        pool_loop()
        return 0
    if action == "once":
        result = pool_once()
        if result.get("disabled"):
            print("pool: dispatch is off "
                  "(agentmux board config dispatchEnabled true)")
        print(json.dumps(result, indent=2))
        return 0
    if action == "start":
        print(pool_start())
        return 0
    if action == "stop":
        print(pool_stop())
        return 0
    if action == "resume":
        write_state({"paused": False, "failures": 0})
        print("pool brake released")
        return 0
    status = pool_status()
    if args.json:
        print(json.dumps(status, indent=2))
        return 0
    print("pool:     %s" % ("running (pid %d)" % status["pid"] if status["pid"]
                            else "not running"))
    print("dispatch: %s" % ("on" if status["enabled"] else "off"))
    print("workers:  %d/%s  %s" % (len(status["workers"]), status["wip"],
                                   ", ".join(sorted(status["workers"])) or "-"))
    print("ready:    %s" % (", ".join(status["ready"]) or "-"))
    if status["paused"]:
        print("PAUSED after %d failures - agentmux pool resume" % status["failures"])
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="board-to-agent dispatch")
    sub = parser.add_subparsers(dest="command", required=True)

    one = sub.add_parser("dispatch", help="hand one ready card to a fresh agent")
    one.add_argument("id", nargs="?", default=None, help="TM-014; default is the top of the queue")
    one.add_argument("--cli", default=None)
    one.add_argument("--dry-run", action="store_true")
    one.set_defaults(func=cmd_dispatch)

    gather = sub.add_parser("collect", help="reconcile dispatched cards; never closes one")
    gather.add_argument("id", nargs="?", default=None)
    gather.add_argument("--all", action="store_true")
    gather.set_defaults(func=cmd_collect)

    pool = sub.add_parser("pool", help="the pickup loop")
    pool.add_argument("action", nargs="?", default="status",
                      choices=("once", "start", "stop", "status", "resume", "run-loop"))
    pool.add_argument("--json", action="store_true")
    pool.set_defaults(func=cmd_pool)

    status = sub.add_parser("status", help="what is dispatched right now")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_pool, action="status")

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
