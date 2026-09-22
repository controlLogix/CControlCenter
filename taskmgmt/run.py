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
    if len(line.encode("utf-8")) > EVENT_MAX:
        # Truncating detail is preferable to a torn record. If this still overflows the
        # caller put something structural in the event that belongs in a sidecar file.
        record["detail"] = (record.get("detail") or "")[:80]
        record["truncated"] = True
        line = json.dumps(record, separators=(",", ":")) + "\n"
    path = events_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
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


# ── verbs ────────────────────────────────────────────────────────────────────

def cmd_start(args):
    for _ in range(8):
        run_id = secrets.token_hex(3)
        directory = run_dir(run_id)
        try:
            directory.mkdir(parents=True)          # implicit exclusivity
        except FileExistsError:
            continue
        os.chmod(directory, 0o700)
        (directory / "request.md").write_text(args.request, encoding="utf-8")
        append_event(run_id, {"event": "start", "by": args.by or "orchestrator",
                              "detail": args.request[:DETAIL_MAX]})
        coordination.journal("plan", f"run {run_id} started", args.request[:2000],
                             args.by or "orchestrator")
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
    state = fold(load_events(run_id))
    row = state["jobs"].get(args.job)
    if row is None:
        print(f"run: no such job {args.job}", file=sys.stderr)
        return 2
    if args.by and row["worker"] and args.by != row["worker"]:
        print(f"run: {args.job} belongs to {row['worker']}, not {args.by}",
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
                          "by": row["worker"] or args.by, "files": files,
                          "hashes": hashes, "detail": (args.summary or "")[:DETAIL_MAX]})
    print(f"submitted {args.job} ({len(files)} file(s))")
    return 0


def cmd_verdict(args):
    run_id, index = split_job(args.job)
    if not run_id:
        print(f"run: invalid job id {args.job!r}", file=sys.stderr)
        return 2
    state = fold(load_events(run_id))
    row = state["jobs"].get(args.job)
    if row is None:
        print(f"run: no such job {args.job}", file=sys.stderr)
        return 2

    # THIS is what makes "verified by a reviewer" a mechanism rather than a note in a
    # brief. A worker cannot sign off its own work, and the orchestrator cannot
    # transcribe a verdict on the reviewer's behalf.
    if args.by and row["worker"] and args.by == row["worker"]:
        print(f"run: {args.by} submitted {args.job} and cannot verify it",
              file=sys.stderr)
        return 2
    if row["reviewer"] and args.by and args.by != row["reviewer"]:
        print(f"run: {args.job} is reviewed by {row['reviewer']}, not {args.by}",
              file=sys.stderr)
        return 2
    if row["state"] not in ("submitted", "rejected"):
        print(f"run: {args.job} is {row['state']}, nothing to verify", file=sys.stderr)
        return 2

    attempt = int(row.get("attempts", 0)) + 1
    reason = args.reason or ""
    if args.reason_file:
        try:
            reason = Path(args.reason_file).read_text(encoding="utf-8")
        except OSError as err:
            print(f"run: cannot read {args.reason_file}: {err}", file=sys.stderr)
            return 2
    directory = job_dir(run_id, index)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"verdict-{attempt}.md").write_text(reason, encoding="utf-8")

    result = "pass" if args.passed else "fail"
    append_event(run_id, {"event": "verdict", "job": args.job, "by": args.by,
                          "result": result, "attempt": attempt,
                          "file": f"verdict-{attempt}.md",
                          "detail": reason[:DETAIL_MAX]})

    after = fold(load_events(run_id))["jobs"][args.job]
    print(f"{args.job}: {result} (attempt {attempt}) -> {after['state']}")
    if after["state"] == "escalated":
        message = (f"ESCALATED {args.job} after {MAX_ATTEMPTS} failed reviews. "
                   f"Last reason: {reason[:400]}")
        notify_orchestrator("error", message, ref=args.job)
        coordination.journal("blocked", f"{args.job} escalated", message, args.by)
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
    state = fold(load_events(args.run))
    if not state["jobs"]:
        print("run: no jobs in this run - nothing to complete", file=sys.stderr)
        return 2

    blocking = sorted(j for j, r in state["jobs"].items() if r["state"] in BLOCKING)

    # THE GATE.
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
                            "by": args.by or "orchestrator",
                            "detail": f"{len(state['jobs']) - len(blocking)}"
                                      f"/{len(state['jobs'])} verified"})
    verified = len(state["jobs"]) - len(blocking)
    summary = (f"run {args.run} {'FORCED' if blocking else 'COMPLETE'}: "
               f"{verified}/{len(state['jobs'])} jobs verified")
    if blocking:
        summary += f"; unverified: {', '.join(blocking)}; see {report}"
    coordination.journal("done" if not blocking else "conflict",
                         summary, state["request"] or "", args.by or "orchestrator")
    notify_orchestrator("complete" if not blocking else "error", summary,
                        ref=args.run)
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
