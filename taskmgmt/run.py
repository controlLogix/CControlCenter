#!/usr/bin/env python3
"""Runs: assignment, verified completion, and the gate that holds it shut.

WHY THIS EXISTS
---------------
Multi-agent work had no completion protocol. A brief told a worker to print
"ORCHESTRATION COMPLETE" into its pane and the orchestrator grepped for it; the wording
changed per run and nothing validated it. Nothing verified work before it was delivered,
and nothing ever closed an agent - so context grew until someone remembered to kill it.

A run is an explicit boundary. Every job inside it is verified by a reviewer that is not
the worker, and `run complete` REFUSES until every job is verified. That refusal is the
whole point: it is a mechanism, not a convention, in the same spirit as a claim being an
O_EXCL file rather than a polite request.

WHY APPEND-ONLY
---------------
The obvious design - one mutable runs/<id>.json - has a lost update. Two workers submit
at the same time: both read, both write, one submission is gone. With a gate that waits
for every job, a lost `submit` hangs the run forever, and a lost `reject` lets a bad job
sit as still-in-flight and be re-verified. There is no flock anywhere in this repo.

So state is never stored, only derived. events.jsonl is append-only; a single write under
O_APPEND is atomic, and every record is capped so it stays that way. Concurrent writers
both survive; `status` folds the log. A torn final line is discarded on parse, exactly as
courier.parse_record already does for outboxes. Long text never goes in an event - it
goes in a sidecar file and the event carries the filename.

COMPLETE is taken with O_CREAT|O_EXCL, so completion cannot fire twice however many
orchestrators, retries or resumed sessions race for it.

    python3 taskmgmt/run.py start "<request>"
    python3 taskmgmt/run.py assign <run> --worker <agent> --reviewer <agent> [--task N]
    python3 taskmgmt/run.py submit <job> --by <agent> [--files a.py,b.py]
    python3 taskmgmt/run.py verdict <job> --by <agent> --pass|--fail [--reason ...]
    python3 taskmgmt/run.py status <run> [--json]
    python3 taskmgmt/run.py complete <run> [--force]
"""
import argparse
import contextlib
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coordination                                    # noqa: E402  reuse, do not restate

ROOT = Path(os.environ.get("AGENTMUX_HOME", str(Path.home() / ".agentmux")))
RUNS_DIR = ROOT / "runs"
INBOX_DIR = ROOT / "inbox"

RUN_PATTERN = re.compile(r"[0-9a-f]{6}")
JOB_PATTERN = re.compile(r"([0-9a-f]{6})/([0-9]{1,4})")
NAME_PATTERN = coordination.NAME_PATTERN

EVENT_MAX = 1024            # keeps one append atomic; long text goes in a sidecar
DETAIL_MAX = 200
MAX_ATTEMPTS = 3            # third failure escalates to the human
LOCK_WAIT_S = 10            # before a run lock is treated as abandoned


class IdentityError(Exception):
    """Raised when a caller cannot be who it says it is. See resolve_identity."""

# The states a job can be folded into. `verified` is terminal success; there is no
# separate `accepted`, because an orchestrator that always accepts adds a write, a way
# to hang the gate, and a reason to re-read the artifact it is trying not to read.
OPEN_STATES = ("assigned", "working", "submitted", "rejected")
BLOCKING = OPEN_STATES + ("escalated",)


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S") + time.strftime("%z")


def run_dir(run_id):
    return RUNS_DIR / run_id


def job_dir(run_id, index):
    return run_dir(run_id) / "jobs" / str(index)


def events_path(run_id):
    return run_dir(run_id) / "events.jsonl"


def complete_path(run_id):
    return run_dir(run_id) / "COMPLETE"


def valid_run(run_id):
    return bool(run_id) and bool(RUN_PATTERN.fullmatch(run_id))


def split_job(job_id):
    match = JOB_PATTERN.fullmatch(job_id or "")
    if not match:
        return None, None
    return match.group(1), int(match.group(2))


# ── the log ──────────────────────────────────────────────────────────────────

def append_event(run_id, record):
    """One atomic append. Never a read-modify-write."""
    record = dict(record, at=now(), run=run_id)
    if "detail" in record and isinstance(record["detail"], str):
        record["detail"] = record["detail"][:DETAIL_MAX]
    line = json.dumps(record, separators=(",", ":")) + "\n"
    path = events_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if len(line.encode("utf-8")) > EVENT_MAX:
        # Truncating detail is preferable to a torn record. If this STILL overflows,
        # the caller put something structural in the event - a file list, a captured
        # diff - that belongs in a sidecar.
        record["detail"] = (record.get("detail") or "")[:80]
        record["truncated"] = True
        line = json.dumps(record, separators=(",", ":")) + "\n"
    if len(line.encode("utf-8")) > EVENT_MAX:
        # #23. EVENT_MAX was declared as the thing that "keeps one append atomic" and
        # then the oversized line was written anyway - so the one guarantee the whole
        # append-only design rests on was documentation, not behaviour. A write past
        # the filesystem's atomic-append size can interleave with a concurrent
        # append, and fold() then reads a torn record and silently skips it: a
        # verdict, a submit or a start vanishes from the ledger that is meant to BE
        # the record.
        #
        # So the oversized payload goes to a sidecar and the event references it. The
        # event stays small, the append stays atomic, and nothing is lost.
        overflow = path.parent / f"event-overflow-{secrets.token_hex(4)}.json"
        try:
            overflow.write_text(json.dumps(record, indent=2), encoding="utf-8")
            os.chmod(overflow, 0o600)
            spilled = overflow.name
        except OSError:
            spilled = None
        record = {k: v for k, v in record.items() if k in
                  ("at", "run", "event", "job", "by", "result", "attempt", "file")}
        record["truncated"] = True
        record["overflow"] = spilled
        record["detail"] = f"oversized event; full record in {spilled}" if spilled \
            else "oversized event; sidecar write failed"
        line = json.dumps(record, separators=(",", ":")) + "\n"
        if len(line.encode("utf-8")) > EVENT_MAX:
            # Nothing left to shed. Refusing is correct: a ledger that silently
            # accepts a record it cannot write atomically is worse than a loud error.
            raise ValueError(f"run: event exceeds EVENT_MAX ({EVENT_MAX}) even after "
                             f"spilling to a sidecar; refusing to write a torn record")
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600),
                   "a", encoding="utf-8") as handle:
        handle.write(line)
    return record


def load_events(run_id):
    path = events_path(run_id)
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except ValueError:
                continue                 # a torn final line, same as courier does
            if isinstance(value, dict):
                out.append(value)
    except OSError:
        pass
    return out


def fold(events):
    """Derive every job's current state from the log. Never reads stored state."""
    jobs = {}
    request = None
    forced = False
    for event in events:
        kind = event.get("event")
        if kind == "start":
            request = event.get("detail")
            continue
        if kind == "forced":
            forced = True
            continue
        job = event.get("job")
        if not job:
            continue
        row = jobs.setdefault(job, {
            "job": job, "state": "assigned", "worker": None, "reviewer": None,
            "attempts": 0, "task": None, "files": [], "last": None, "detail": None,
        })
        row["last"] = event.get("at")
        if kind == "assign":
            row.update(state="assigned", worker=event.get("by"),
                       reviewer=event.get("reviewer"), task=event.get("task"))
        elif kind == "working":
            row["state"] = "working"
        elif kind == "submit":
            row["state"] = "submitted"
            row["files"] = event.get("files") or row["files"]
        elif kind == "verdict":
            if event.get("result") == "pass":
                row["state"] = "verified"
            else:
                row["attempts"] = int(row.get("attempts", 0)) + 1
                row["state"] = ("escalated" if row["attempts"] >= MAX_ATTEMPTS
                                else "rejected")
            row["detail"] = event.get("detail")
        elif kind == "escalate":
            row["state"] = "escalated"
            row["detail"] = event.get("detail")
    return {"request": request, "jobs": jobs, "forced": forced}


def digest(repo, files):
    """Bind a verdict to bytes. Without this, `verified` describes files that may
    have changed since - and a worker editing during review launders a fail into a
    pass."""
    out = {}
    for name in files or []:
        path = Path(repo) / name if repo else Path(name)
        try:
            out[name] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        except OSError:
            out[name] = "missing"
    return out


# ── notification (never the record) ──────────────────────────────────────────

def notify_orchestrator(kind, body, ref=None):
    """Append straight to the orchestrator's inbox.

    NOT `agentmux post`. courier.deliver() refuses a self-addressed message, and
    cmd_post defaults the sender to `orchestrator` outside a pane - so posting to
    orchestrator FROM the orchestrator is refused forever. Worse, that failure marks
    the recipient blocked and head-of-line-blocks the whole inbox for the backoff
    window. The ledger is the record; this is only a notification.
    """
    try:
        INBOX_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(INBOX_DIR, 0o700)
        path = INBOX_DIR / "orchestrator.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "at": now(), "sender": "run", "recipient": "orchestrator",
                "kind": kind, "body": body[:8192], "ref": ref}) + "\n")
        os.chmod(path, 0o600)
        return True
    except OSError:
        return False


# ── serialising the gate ─────────────────────────────────────────────────────

@contextlib.contextmanager
def run_lock(run_id, what="operation"):
    """Serialise the read-decide-write windows that the append-only log cannot.

    Appends are atomic, so the LEDGER is always consistent. The decisions taken from
    it are not: `complete` folds the events, checks the gate, and only then takes the
    COMPLETE marker, and `verdict` folds, computes `verdict-N.md` and only then
    appends. Both are read-decide-write across a shared file.

    Two consequences, both observed rather than theoretical in shape:
      * a `verdict --fail` landing between complete's fold and its COMPLETE marker
        completes a run with a rejected job in it - the gate reports "all verified"
        about a state that no longer exists;
      * two reviewers verdicting different jobs at the same attempt number compute the
        same `verdict-N.md` and one silently overwrites the other's reasoning.

    mkdir is atomic everywhere this runs. The stale-lock ceiling matters because an
    agent killed mid-verdict must not wedge every later completion.
    """
    directory = run_dir(run_id)
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / ".lock"
    deadline = time.time() + LOCK_WAIT_S
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            if time.time() > deadline:
                # Break it rather than fail: the holder is gone, and refusing every
                # future complete because one agent was killed is the worse outcome.
                try:
                    lock.rmdir()
                except OSError:
                    pass
                deadline = time.time() + LOCK_WAIT_S
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            lock.rmdir()
        except OSError:
            pass


# ── identity ─────────────────────────────────────────────────────────────────

def resolve_identity(claimed, verb, require_live=True):
    """Return the identity to record, or raise IdentityError.

    `run verdict --by claude` used to be believed on the strength of the string. That
    is not a hypothetical weakness: during live testing the ORCHESTRATOR typed a
    verdict with --by set to the reviewer's name, and the ledger recorded a review
    that the reviewer never performed. The whole point of the reviewer field is that
    "verified" means someone other than the author looked.

    Rules:
      * $AGENTMUX_AGENT wins. A pane cannot rename itself by passing --by.
      * The identity must be a LIVE tmux session, so a name that never existed, or an
        agent that has since died, cannot sign anything.
      * The orchestrator has no session, which is exactly how `complete` can tell it
        is not being run from inside a pane.

    THE HONEST LIMIT, stated here because it belongs next to the code and not only in
    a rule file: every agent runs unrestricted with full filesystem access, so any of
    them could set $AGENTMUX_AGENT, write the ledger directly, or call tmux itself.
    This is not a security boundary and cannot be made into one at this layer. It
    stops MISTAKES - a mistyped --by, a reviewer name transcribed by the orchestrator,
    a verdict from an agent that is no longer running - which is what actually went
    wrong.
    """
    env = os.environ.get("AGENTMUX_AGENT") or None
    if env and claimed and claimed != env:
        raise IdentityError(
            f"run: this pane is {env!r}, so it cannot {verb} as {claimed!r}.\n"
            f"  --by is not an override; drop it and the pane's own identity is used.")
    who = env or claimed
    if not who:
        raise IdentityError(f"run: {verb} needs an identity "
                            f"(run it inside a pane, or pass --by)")
    if not NAME_PATTERN.fullmatch(who):
        raise IdentityError(f"run: invalid identity {who!r}")
    if require_live and os.environ.get("AGENTMUX_TRUST_IDENTITY") != "1":
        live = coordination.live_agents()
        if who not in live:
            raise IdentityError(
                f"run: {who!r} is not a live agent, so it cannot {verb}.\n"
                f"  live: {', '.join(sorted(live)) or '(none)'}\n"
                f"  set AGENTMUX_TRUST_IDENTITY=1 only in tests, which run without tmux.")
    return who


def orchestrator_identity(verb, claimed=None):
    """`start` and `complete` are the orchestrator's, and refuse to run from a pane."""
    env = os.environ.get("AGENTMUX_AGENT")
    if env and os.environ.get("AGENTMUX_TRUST_IDENTITY") != "1":
        raise IdentityError(
            f"run: {verb} is the orchestrator's to call, and this is the {env!r} pane.\n"
            f"  An agent closing out the run it is working in defeats the gate: ask the\n"
            f"  orchestrator to run it, or post a request for it.")
    if claimed and claimed != "orchestrator":
        # --by survives on these two verbs only as a compatibility shim. Accepting it
        # silently would put a name in the ledger that nobody could have been.
        raise IdentityError(
            f"run: {verb} is always attributed to the orchestrator, so --by {claimed!r} "
            f"cannot be honoured.\n  Drop --by.")
    return "orchestrator"


# ── notification failures are never swallowed ────────────────────────────────

def record_notice(run_id, kind, subject, body, by, ref=None):
    """Journal AND notify, and make any failure of either visible.

    #24. Both calls used to be fired and discarded. `journal()` returns a STRING
    saying where it landed - including the literal "NOWHERE - journal write failed" -
    and nobody read it; `notify_orchestrator()` returns False on OSError and nobody
    read that either. So an escalation could fail to reach the dashboard, fail to
    reach the fallback file and fail to reach the inbox, while the command printed
    "escalated after 3 attempts" and exited 0. The one message whose entire purpose
    is to reach a human was the one that could vanish silently.

    The ledger is the durable record, so a failure is written THERE as well as said on
    stderr: whatever else is down, the run's own events file is local and already open.
    """
    where = coordination.journal(kind, subject, body, by)
    delivered = notify_orchestrator("error" if kind in ("blocked", "conflict") else "status",
                                    subject if not body else f"{subject}\n{body}"[:8192],
                                    ref=ref)
    if where.startswith("NOWHERE") or not delivered:
        problem = (f"notification degraded: journal={where}, "
                   f"orchestrator inbox={'ok' if delivered else 'FAILED'}")
        print(f"  WARNING: {problem}", file=sys.stderr)
        print(f"  The ledger still has it: agentmux run status {run_id}", file=sys.stderr)
        try:
            append_event(run_id, {"event": "notify-failed", "by": by,
                                  "detail": f"{problem}; subject={subject[:200]}"})
        except (OSError, ValueError):
            pass
    return where, delivered


# ── verbs ────────────────────────────────────────────────────────────────────

def cmd_start(args):
    try:
        by = orchestrator_identity("start", args.by)
    except IdentityError as err:
        print(err, file=sys.stderr)
        return 2
    for _ in range(8):
        run_id = secrets.token_hex(3)
        directory = run_dir(run_id)
        try:
            directory.mkdir(parents=True)          # implicit exclusivity
        except FileExistsError:
            continue
        os.chmod(directory, 0o700)
        (directory / "request.md").write_text(args.request, encoding="utf-8")
        append_event(run_id, {"event": "start", "by": by,
                              "detail": args.request[:DETAIL_MAX]})
        coordination.journal("plan", f"run {run_id} started", args.request[:2000], by)
        print(run_id)
        return 0
    print("run: could not allocate a run id", file=sys.stderr)
    return 1


def cmd_assign(args):
    if not valid_run(args.run):
        print(f"run: invalid run id {args.run!r}", file=sys.stderr)
        return 2
    if not run_dir(args.run).is_dir():
        print(f"run: no such run {args.run}", file=sys.stderr)
        return 2
    for label, value in (("worker", args.worker), ("reviewer", args.reviewer)):
        if not NAME_PATTERN.fullmatch(value or ""):
            print(f"run: invalid {label} {value!r}", file=sys.stderr)
            return 2
    # The operator's standing rule: a reviewer must not be the worker, and should be
    # a different CLI. The first half is enforceable here; the second is a spawn-time
    # choice the orchestrator makes.
    if args.worker == args.reviewer:
        print("run: the reviewer must not be the worker", file=sys.stderr)
        return 2

    jobs_root = run_dir(args.run) / "jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)
    for index in range(1, 10000):
        directory = jobs_root / str(index)
        try:
            directory.mkdir()                      # atomic id allocation
        except FileExistsError:
            continue
        job = f"{args.run}/{index}"
        if args.brief:
            (directory / "brief.md").write_text(args.brief, encoding="utf-8")
        append_event(args.run, {"event": "assign", "job": job, "by": args.worker,
                                "reviewer": args.reviewer, "task": args.task,
                                "detail": (args.brief or "")[:DETAIL_MAX]})
        print(job)
        return 0
    print("run: too many jobs", file=sys.stderr)
    return 1


def cmd_submit(args):
    run_id, index = split_job(args.job)
    if not run_id:
        print(f"run: invalid job id {args.job!r}", file=sys.stderr)
        return 2
    try:
        by = resolve_identity(args.by, f"submit {args.job}")
    except IdentityError as err:
        print(err, file=sys.stderr)
        return 2

    state = fold(load_events(run_id))
    row = state["jobs"].get(args.job)
    if row is None:
        print(f"run: no such job {args.job}", file=sys.stderr)
        return 2
    if row["worker"] and by != row["worker"]:
        print(f"run: {args.job} belongs to {row['worker']}, not {by}", file=sys.stderr)
        return 2
    if complete_path(run_id).exists():
        print(f"run: {run_id} is already complete; {args.job} cannot be submitted now",
              file=sys.stderr)
        return 2

    files = [f for f in (args.files or "").split(",") if f.strip()]
    hashes = digest(args.repo, files)
    directory = job_dir(run_id, index)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "submission.md").write_text(
        (args.summary or "") + "\n\n## files\n"
        + "\n".join(f"- {name}  sha256:{h}" for name, h in hashes.items()) + "\n",
        encoding="utf-8")
    append_event(run_id, {"event": "submit", "job": args.job,
                          "by": row["worker"] or by, "files": files,
                          "hashes": hashes, "detail": (args.summary or "")[:DETAIL_MAX]})
    print(f"submitted {args.job} ({len(files)} file(s))")
    return 0


def cmd_verdict(args):
    run_id, index = split_job(args.job)
    if not run_id:
        print(f"run: invalid job id {args.job!r}", file=sys.stderr)
        return 2
    try:
        by = resolve_identity(args.by, f"verify {args.job}")
    except IdentityError as err:
        print(err, file=sys.stderr)
        return 2

    state = fold(load_events(run_id))
    row = state["jobs"].get(args.job)
    if row is None:
        print(f"run: no such job {args.job}", file=sys.stderr)
        return 2

    # THIS is what makes "verified by a reviewer" a mechanism rather than a note in a
    # brief. A worker cannot sign off its own work, and the orchestrator cannot
    # transcribe a verdict on the reviewer's behalf.
    if row["worker"] and by == row["worker"]:
        print(f"run: {by} submitted {args.job} and cannot verify it", file=sys.stderr)
        return 2
    if row["reviewer"] and by != row["reviewer"]:
        print(f"run: {args.job} is reviewed by {row['reviewer']}, not {by}",
              file=sys.stderr)
        return 2

    reason = args.reason or ""
    if args.reason_file:
        try:
            reason = Path(args.reason_file).read_text(encoding="utf-8")
        except OSError as err:
            print(f"run: cannot read {args.reason_file}: {err}", file=sys.stderr)
            return 2

    # Everything from here is read-decide-write, so it happens under the run lock.
    # The state is re-folded inside it: the checks above used a snapshot taken before
    # we held anything, and a rival verdict on the same job could have landed since.
    with run_lock(run_id, "verdict"):
        if complete_path(run_id).exists():
            # A verdict after the gate closed is not a late record, it is a record
            # about a run whose result has already been reported. Refuse loudly.
            print(f"run: {run_id} is already complete; {args.job} cannot be verified now",
                  file=sys.stderr)
            return 2
        row = fold(load_events(run_id))["jobs"][args.job]
        if row["state"] not in ("submitted", "rejected"):
            print(f"run: {args.job} is {row['state']}, nothing to verify", file=sys.stderr)
            return 2

        attempt = int(row.get("attempts", 0)) + 1
        directory = job_dir(run_id, index)
        directory.mkdir(parents=True, exist_ok=True)

        # O_EXCL rather than write_text. Two reviewers landing on the same attempt
        # number computed the same verdict-N.md and the loser's reasoning was silently
        # overwritten - the only copy of why a job was rejected, gone. The lock makes
        # that unreachable; the O_EXCL means it stays unreachable if the lock ever
        # fails to hold, and the bump keeps a name rather than erroring out.
        for bump in range(attempt, attempt + 64):
            candidate = directory / f"verdict-{bump}.md"
            try:
                fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(reason)
            break
        else:
            print(f"run: cannot name a verdict file for {args.job}", file=sys.stderr)
            return 1

        result = "pass" if args.passed else "fail"
        append_event(run_id, {"event": "verdict", "job": args.job, "by": by,
                              "result": result, "attempt": attempt,
                              "file": candidate.name,
                              "detail": reason[:DETAIL_MAX]})
        after = fold(load_events(run_id))["jobs"][args.job]

    print(f"{args.job}: {result} (attempt {attempt}) -> {after['state']}")
    if after["state"] == "escalated":
        message = (f"ESCALATED {args.job} after {MAX_ATTEMPTS} failed reviews. "
                   f"Last reason: {reason[:400]}")
        record_notice(run_id, "blocked", f"{args.job} escalated", message, by,
                      ref=args.job)
        print(f"  escalated after {MAX_ATTEMPTS} attempts - the run cannot complete")
    return 0


def derive_stale(state):
    """A job whose agent is gone. Derived, never stored - no daemon, no timer.

    The 3-attempt bound only covers a reviewer saying no. The commoner failure is an
    agent that goes silent, and without this the gate waits forever for a submission
    that will never come.
    """
    live = coordination.live_agents()
    stale = {}
    for job, row in state["jobs"].items():
        if row["state"] in ("working", "assigned", "submitted"):
            who = row["worker"] if row["state"] != "submitted" else row["reviewer"]
            if who and who not in live:
                stale[job] = who
    return stale


def cmd_status(args):
    if not valid_run(args.run):
        print(f"run: invalid run id {args.run!r}", file=sys.stderr)
        return 2
    state = fold(load_events(args.run))
    stale = derive_stale(state)
    claims = {c["resource"]: c["holder"] for c in coordination.all_claims()}
    done = complete_path(args.run).exists()

    if args.json:
        print(json.dumps({
            "run": args.run, "request": state["request"],
            "complete": done, "forced": state["forced"],
            "jobs": [dict(row, stale=job in stale) for job, row in
                     sorted(state["jobs"].items())],
            "claims": claims}, indent=2))
        return 0

    # One line per job, short enough that a resumed orchestrator can be handed the
    # whole thing for a few hundred tokens.
    print(f"run {args.run}  {'COMPLETE' if done else 'open'}"
          f"{' (FORCED)' if state['forced'] else ''}")
    if state["request"]:
        print(f"  request: {state['request'][:70]}")
    if not state["jobs"]:
        print("  no jobs assigned")
        return 0
    for job, row in sorted(state["jobs"].items()):
        flag = "  STALE" if job in stale else ""
        print(f"  {job:<12} {row['state']:<10} w={row['worker'] or '-':<12}"
              f" r={row['reviewer'] or '-':<12} tries={row['attempts']}{flag}")
    blocking = [j for j, r in state["jobs"].items() if r["state"] in BLOCKING]
    print(f"  {len(state['jobs']) - len(blocking)}/{len(state['jobs'])} verified")
    if blocking and not done:
        print(f"  BLOCKING completion: {', '.join(sorted(blocking))}")
    if stale:
        print(f"  agents gone: {', '.join(sorted(set(stale.values())))}")
    return 0


def capture_forced(run_id, state, blocking):
    """What was not finished, captured BEFORE anything is torn down.

    Ordering is load-bearing: a pane dies with its tmux session, so a report written
    after teardown would describe nothing. This is the operator's requirement - a
    forced completion has to leave evidence of what was incomplete.
    """
    lines = [f"# Run {run_id} - FORCED completion", "",
             f"Forced at {now()}.",
             f"{len(blocking)} job(s) were not verified.", ""]
    claims = coordination.all_claims()
    for job in sorted(blocking):
        row = state["jobs"][job]
        lines += [f"## {job} - {row['state']}", "",
                  f"- worker: {row['worker']}", f"- reviewer: {row['reviewer']}",
                  f"- attempts: {row['attempts']}",
                  f"- last event: {row['last']}",
                  f"- last detail: {(row['detail'] or '')[:400]}", ""]
        held = [c["resource"] for c in claims if c["holder"] == row["worker"]]
        if held:
            lines += [f"- still holding: {', '.join(held)}", ""]
        for who in (row["worker"], row["reviewer"]):
            if not who:
                continue
            try:
                pane = subprocess.run(
                    ["tmux", "-L", coordination.SOCKET, "capture-pane", "-p", "-J",
                     "-S", "-40", "-t", who],
                    capture_output=True, text=True, timeout=10).stdout
            except (OSError, subprocess.SubprocessError):
                pane = ""
            if pane.strip():
                lines += [f"### {who} pane at force time", "", "```",
                          pane.strip()[-3000:], "```", ""]
            else:
                lines += [f"### {who}", "", "(no pane - agent already gone)", ""]
    report = run_dir(run_id) / "FORCED.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    return report


def cmd_complete(args):
    if not valid_run(args.run):
        print(f"run: invalid run id {args.run!r}", file=sys.stderr)
        return 2
    if not run_dir(args.run).is_dir():
        print(f"run: no such run {args.run}", file=sys.stderr)
        return 2
    try:
        by = orchestrator_identity("complete", args.by)
    except IdentityError as err:
        print(err, file=sys.stderr)
        return 2

    # THE GATE, AND WHY IT IS TAKEN UNDER A LOCK.
    #
    # The fold, the gate decision and the COMPLETE marker were three separate steps on
    # shared state. A `verdict --fail` landing between the fold and the marker produced
    # a completed run containing a rejected job, and the summary printed "all verified"
    # about a state that had already stopped being true. The window is small and the
    # consequence is the one thing this whole file exists to prevent, which is the
    # worst combination to leave in.
    #
    # cmd_verdict takes the same lock and refuses once COMPLETE exists, so the two
    # orderings are the only two possible: the verdict lands and the gate sees it, or
    # the run completes and the verdict is refused with a reason.
    with run_lock(args.run, "complete"):
        state = fold(load_events(args.run))
        if not state["jobs"]:
            print("run: no jobs in this run - nothing to complete", file=sys.stderr)
            return 2

        blocking = sorted(j for j, r in state["jobs"].items() if r["state"] in BLOCKING)

        if blocking and not args.force:
            print(f"REFUSED: {len(blocking)} of {len(state['jobs'])} job(s) are not "
                  f"verified.", file=sys.stderr)
            stale = derive_stale(state)
            for job in blocking:
                row = state["jobs"][job]
                note = "  (agent gone)" if job in stale else ""
                print(f"  {job:<12} {row['state']:<10} worker={row['worker']}"
                      f" tries={row['attempts']}{note}", file=sys.stderr)
            print("\n  Every job must be verified by its reviewer before this run can "
                  "complete.", file=sys.stderr)
            print("  Override with --force; it records what was left unfinished.",
                  file=sys.stderr)
            return 1

        report = None
        if blocking:
            report = capture_forced(args.run, state, blocking)     # BEFORE teardown

        try:
            os.close(os.open(complete_path(args.run),
                             os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
        except FileExistsError:
            print(f"run {args.run} was already completed", file=sys.stderr)
            return 1

        append_event(args.run, {"event": "forced" if blocking else "complete",
                                "by": by,
                                "detail": f"{len(state['jobs']) - len(blocking)}"
                                          f"/{len(state['jobs'])} verified"})
    verified = len(state["jobs"]) - len(blocking)
    summary = (f"run {args.run} {'FORCED' if blocking else 'COMPLETE'}: "
               f"{verified}/{len(state['jobs'])} jobs verified")
    if blocking:
        summary += f"; unverified: {', '.join(blocking)}; see {report}"
    record_notice(args.run, "done" if not blocking else "conflict",
                  summary, state["request"] or "", by, ref=args.run)
    print(summary)
    if report:
        print(f"  forced report: {report}")
    print("  agents are still running - tear them down with: "
          f"agentmux run teardown {args.run}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="agentmux runs")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start")
    start.add_argument("request")
    start.add_argument("--by", default=None)
    start.set_defaults(func=cmd_start)

    assign = sub.add_parser("assign")
    assign.add_argument("run")
    assign.add_argument("--worker", required=True)
    assign.add_argument("--reviewer", required=True)
    assign.add_argument("--task", default=None)
    assign.add_argument("--brief", default="")
    assign.set_defaults(func=cmd_assign)

    submit = sub.add_parser("submit")
    submit.add_argument("job")
    submit.add_argument("--by", default=os.environ.get("AGENTMUX_AGENT"))
    submit.add_argument("--files", default="")
    submit.add_argument("--summary", default="")
    submit.add_argument("--repo", default=os.environ.get("AGENTMUX_REPO"))
    submit.set_defaults(func=cmd_submit)

    verdict = sub.add_parser("verdict")
    verdict.add_argument("job")
    verdict.add_argument("--by", default=os.environ.get("AGENTMUX_AGENT"))
    group = verdict.add_mutually_exclusive_group(required=True)
    group.add_argument("--pass", dest="passed", action="store_true")
    group.add_argument("--fail", dest="passed", action="store_false")
    verdict.add_argument("--reason", default="")
    verdict.add_argument("--reason-file", default=None)
    verdict.set_defaults(func=cmd_verdict)

    status = sub.add_parser("status")
    status.add_argument("run")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    complete = sub.add_parser("complete")
    complete.add_argument("run")
    complete.add_argument("--force", action="store_true")
    complete.add_argument("--by", default=None)
    complete.set_defaults(func=cmd_complete)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
