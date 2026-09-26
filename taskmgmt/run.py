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
import tempfile
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coordination
import notify                                    # noqa: E402  reuse, do not restate

ROOT = Path(os.environ.get("AGENTMUX_HOME", str(Path.home() / ".agentmux")))
RUNS_DIR = ROOT / "runs"
INBOX_DIR = ROOT / "inbox"

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_PATTERN = re.compile(r"[0-9a-f]{6}")
JOB_PATTERN = re.compile(r"([0-9a-f]{6})/([0-9]{1,4})")
NAME_PATTERN = coordination.NAME_PATTERN

EVENT_MAX = 1024            # keeps one append atomic; long text goes in a sidecar
DETAIL_MAX = 200
MAX_ATTEMPTS = 3            # third failure escalates to the human
LOCK_WAIT_S = 10            # before a run lock is treated as abandoned


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
    base = None
    origin = None
    pane = None
    forced = False
    for event in events:
        kind = event.get("event")
        if kind == "start":
            request = event.get("detail")
            base = event.get("base") or base
            origin = event.get("origin") or origin
            pane = event.get("pane") or pane
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
            # Old ledgers used by for the worker; new ones record the actor in by
            # and the assignment separately. Keep existing runs readable.
            row.update(state="assigned", worker=event.get("worker", event.get("by")),
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
    return {"request": request, "base": base, "origin": origin, "pane": pane,
            "jobs": jobs, "forced": forced}


def repo_head(repo=None):
    """The commit this run starts from, or None outside a repo.

    WHY IT IS RECORDED AT ALL. A reviewer - human or agent - asked to look at what a
    run changed needs a base to compare against, and `git diff HEAD` is not it: the
    moment a worker commits, that diff goes empty and the review surface shows nothing
    while the work is sitting right there in the history. Pinning the starting commit
    makes "what did this run change" answerable for the whole life of the run and
    afterwards, whether or not anything was committed along the way.
    """
    try:
        proc = subprocess.run(["git", "-C", str(repo or Path.cwd()), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    sha = (proc.stdout or "").strip()
    return sha if proc.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", sha) else None


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


# ── the operator's approval, which the gate consults ─────────────────────────
#
# WHY THIS GATE EXISTS ON TOP OF THE REVIEWER GATE. A reviewer verdict answers "was
# the job done as briefed". It cannot answer "was that the right job", because the
# same orchestrator wrote the brief the reviewer checked against - so an orchestrator
# that misreads what was wanted produces a run where every job passes review and the
# whole thing is wrong. Only the person who asked for the work can catch that, and the
# last moment they can catch it is before the run is declared finished.
#
# THE APPROVAL PINS BYTES. digest() above exists because a verdict naming files without
# hashing them describes bytes that may since have changed. Approval has the same
# exposure and a worse consequence, being the final gate: without the pin, work could
# be approved and then quietly changed before completion, and "approved" would only
# ever have meant "approved something".

APPROVAL_VERSION = 1
NOTE_MAX = 2000


def approval_path(run_id):
    return run_dir(run_id) / "APPROVAL.json"


def submitted_files(state):
    """Every file any job in this run submitted, deduplicated, in job order."""
    out = []
    for _, row in sorted(state["jobs"].items()):
        for name in row.get("files") or []:
            if isinstance(name, str) and name and name not in out:
                out.append(name)
    return out


def load_approval(run_id):
    try:
        value = json.loads(approval_path(run_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def write_approval(run_id, by, note, decision="approved", repo=None):
    """Record the operator's decision. Atomic: a torn approval is a half-open gate."""
    if decision not in ("approved", "changes"):
        raise ValueError(f"unknown decision {decision!r}")
    if not valid_run(run_id):
        raise ValueError(f"invalid run id {run_id!r}")
    directory = run_dir(run_id)
    if not directory.is_dir():
        raise ValueError(f"no such run {run_id}")
    if complete_path(run_id).exists():
        raise ValueError(f"run {run_id} is already complete - nothing left to approve")
    state = fold(load_events(run_id))
    if not state["jobs"]:
        raise ValueError("no jobs in this run - nothing to review")
    if decision == "approved":
        blocking = sorted(j for j, r in state["jobs"].items() if r["state"] in BLOCKING)
        if blocking:
            # Approving unverified work would wave through exactly what the reviewer
            # gate catches. The two reviews are not interchangeable: the reviewer
            # checks the job was done, the operator checks it was worth doing.
            raise ValueError(
                f"{len(blocking)} job(s) are not verified yet: {', '.join(blocking)}. "
                "Approval is the gate after review, not instead of it.")
    record = {"version": APPROVAL_VERSION, "run": run_id, "decision": decision,
              "by": by, "at": now(), "note": (note or "")[:NOTE_MAX],
              "files": digest(str(repo or REPO_ROOT), submitted_files(state))}
    handle, tmp = tempfile.mkstemp(dir=str(directory), prefix=".approval-")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, approval_path(run_id))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    append_event(run_id, {"event": "review", "by": by, "result": decision,
                          "detail": (note or "")[:DETAIL_MAX]})
    return record


def approval_drift(run_id, repo=None):
    """Files that moved since approval. () means it still holds; None means there is
    no standing approval to hold."""
    record = load_approval(run_id)
    if not record or record.get("decision") != "approved":
        return None
    pinned = record.get("files") or {}
    current = digest(str(repo or REPO_ROOT), sorted(pinned))
    return tuple(sorted(name for name, was in pinned.items()
                        if current.get(name) != was))


def approval_blocks_completion(run_id, repo=None, agent=None):
    """Why this run may not complete yet, or None. Consulted by the gate.

    TWO DIFFERENT CALLERS, two different rules, and the difference is the whole point.

    A PERSON at a terminal is the approval. Demanding they first click a button in a
    browser to approve work they are in the middle of finishing would be ceremony, so
    for them this refuses only a decision that was MADE and defied: changes asked for,
    or an approval that no longer covers the bytes on disk.

    AN ORCHESTRATOR must have one. It wrote the brief the reviewer checked against, so
    a passing review only says the job matched the brief - it cannot say the brief was
    right. If the orchestrator misread what was wanted, every job passes and the run is
    still wrong, and the only person who can catch that is the one who asked. So a
    warranted caller needs an explicit approval on record, not merely the absence of an
    objection.
    """
    record = load_approval(run_id)
    if not record:
        if agent:
            return (f"{agent} has not been approved to complete this run.\n"
                    "  Every job is verified, which says the work matched its brief -\n"
                    "  and you wrote that brief. Only the operator can say it was the\n"
                    "  right brief. Approve it in the CCC's Runs view, then retry.")
        return None
    if record.get("decision") == "changes":
        note = (record.get("note") or "").strip()
        return (f"the operator asked for changes on {record.get('at')}"
                + (f": {note[:300]}" if note else "")
                + "\n  Approve the run once the changes are in, or record a new"
                  " decision.")
    drift = approval_drift(run_id, repo)
    if drift:
        return (f"{len(drift)} file(s) changed after the operator approved this run: "
                f"{', '.join(drift[:6])}"
                + ("" if len(drift) <= 6 else f" (+{len(drift) - 6} more)")
                + "\n  The approval covered different bytes. Have it reviewed"
                  " again.")
    return None


# ── notification (never the record) ──────────────────────────────────────────

def notify_orchestrator(kind, body, ref=None, recipient="orchestrator"):
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
        safe = recipient if NAME_PATTERN.fullmatch(recipient or "") else "orchestrator"
        path = INBOX_DIR / f"{safe}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "at": now(), "sender": "run", "recipient": safe,
                "kind": kind, "body": body[:8192], "ref": ref}) + "\n")
        os.chmod(path, 0o600)
        return True
    except OSError:
        return False


# ── the board cards this run was supposed to close ───────────────────────────
#
# THE FAILURE THIS EXISTS FOR, exactly. Run bdae05 completed on 2026-09-24 with 2/2
# jobs verified, printed "COMPLETE", and said nothing about TM-083 - the card it had
# been assigned. That card sat `open` with five unticked acceptance criteria until
# somebody noticed by eye, and EP-021 stayed open behind it. Two correct gates with no
# wire between them: `run complete` knew the task key on every job and never mentioned
# it, and the board had no idea a run had finished.
#
# This is the wire. It only REPORTS - it does not tick acceptance or close anything,
# because the board's own gate_done is the thing that decides whether a card may close
# and a second opinion here would be a way around it. What it removes is the silence.

_board = None


def board_modules():
    """(ccstore, ccboard) or None. Never raises: a missing board is not a reason to
    fail a completion that has already been verified."""
    global _board
    if _board is not None:
        return _board or None
    directory = str(REPO_ROOT / "dashboard")
    try:
        if directory not in sys.path:
            sys.path.append(directory)      # append, not insert: the dashboard's
        import ccstore                      # modules must never shadow taskmgmt's
        import ccboard
        _board = (ccstore, ccboard)
    except Exception:
        _board = False
        return None
    return _board


def cards_of(state):
    """Task keys this run's jobs were assigned to, in job order."""
    out = []
    for _, row in sorted(state["jobs"].items()):
        key = row.get("task")
        if isinstance(key, str) and key and key not in out:
            out.append(key)
    return out


def card_status(keys):
    """For each key: its status and what the BOARD says still blocks closing it.

    The gaps come from ccboard.gate_done, so this can never disagree with the refusal
    an operator would get trying to close the card by hand.
    """
    modules = board_modules()
    if not modules or not keys:
        return None
    ccstore, ccboard = modules
    out = []
    try:
        with ccstore.connection() as db:
            cfg = ccboard.config(db) if hasattr(ccboard, "config") else {}
            for key in keys:
                try:
                    task = ccboard.entity(db, key)
                except Exception:
                    out.append({"key": key, "status": "unknown",
                                "gaps": [], "error": "not on the board"})
                    continue
                status = str(task.get("status") or "unknown")
                gaps = []
                if status != "done":
                    # gate_done RAISES Refused; it does not return it. Catching
                    # Exception and shrugging would have reported every open card with
                    # no reason attached, which is the silence this whole function
                    # exists to remove.
                    try:
                        ccboard.gate_done(db, task, cfg)
                    except ccboard.Refused as refusal:
                        gaps = sorted({g.get("field", "?")
                                       for g in (refusal.missing or [])})
                    except Exception:
                        gaps = []
                out.append({"key": key, "status": status, "gaps": gaps,
                            "epic": task.get("epic")})
    except Exception:
        return None
    return out


def report_cards(state):
    """What this run leaves behind on the board.

    Returns (summary_fragment, lines). Computed rather than printed so the caller can
    put the headline first - the detail belongs under the result, not above it.
    """
    keys = cards_of(state)
    if not keys:
        return "", []
    rows = card_status(keys)
    if rows is None:
        return "", [f"  cards: {', '.join(keys)} "
                    f"(board unavailable - check them by hand)"]
    still_open = [r for r in rows if r["status"] != "done"]
    if not still_open:
        return "", [f"  board: all {len(rows)} card(s) already closed - "
                    f"{', '.join(r['key'] for r in rows)}"]
    lines = [f"  BOARD: {len(still_open)} of {len(rows)} card(s) are still open:"]
    for row in still_open:
        gaps = f" - missing {', '.join(row['gaps'])}" if row["gaps"] else ""
        note = f" ({row['error']})" if row.get("error") else ""
        lines.append(f"    {row['key']:<10} {row['status']}{gaps}{note}")
    lines += ["    A verified run is not a closed card. Tick the acceptance criteria",
              "    and attach evidence, or the epic behind these stays open too."]
    return (f"cards still open: {', '.join(r['key'] for r in still_open)}"), lines


# ── unread notices, surfaced in whatever terminal asks next ──────────────────
#
# THE CASE THIS EXISTS FOR. A tmux pane can be drawn on and a desktop can be toasted.
# A Claude Code session is neither: it has no tty of its own (each command is a fresh
# non-interactive process), no pane, and nothing polling on its behalf. So the only
# honest way to reach it is to leave the message where it will be picked up, and make
# every subsequent command say so.
#
# "Non-blocking" is the whole design. Nothing is injected into anyone's input, nothing
# waits for acknowledgement, and a terminal that never asks simply never sees it - the
# ledger and the inbox are still the record. It is a comment, not a prompt.

def unread_path(who):
    return INBOX_DIR / f"{who}.read"


def unread_notices(who=None, cap=20):
    """Notices this terminal has not been shown yet. Never raises."""
    who = who or notify.origin_id()
    if not NAME_PATTERN.fullmatch(who or ""):
        return []
    try:
        lines = [l for l in (INBOX_DIR / f"{who}.jsonl").read_text(
            encoding="utf-8", errors="replace").splitlines() if l.strip()]
    except OSError:
        return []
    try:
        seen = int(unread_path(who).read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        seen = 0
    out = []
    # A marker ahead of the file means the inbox was rotated or truncated. Showing
    # everything again beats silently showing nothing for the rest of time.
    for line in lines[seen:] if seen <= len(lines) else lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out[-cap:]


def mark_notices_read(who=None):
    who = who or notify.origin_id()
    if not NAME_PATTERN.fullmatch(who or ""):
        return
    try:
        count = len([l for l in (INBOX_DIR / f"{who}.jsonl").read_text(
            encoding="utf-8", errors="replace").splitlines() if l.strip()])
        INBOX_DIR.mkdir(parents=True, exist_ok=True)
        unread_path(who).write_text(str(count), encoding="utf-8")
        os.chmod(unread_path(who), 0o600)
    except OSError:
        pass


def print_unread(stream=None):
    """One compact block, above whatever the command was actually asked to do."""
    stream = stream or sys.stderr
    rows = unread_notices()
    if not rows:
        return 0
    who = notify.origin_id()
    print(f"\n  {len(rows)} notice(s) for this terminal since you last looked:",
          file=stream)
    for row in rows:
        mark = "!!" if row.get("kind") == "error" else " ·"
        first = (row.get("body") or "").splitlines()[0][:110]
        print(f"  {mark} {first}", file=stream)
        if row.get("ref"):
            print(f"       agentmux run status {row['ref']}", file=stream)
    print(f"  (clear with: agentmux run notices --read)\n", file=stream)
    return len(rows)


def cmd_notices(args):
    rows = unread_notices(args.who)
    if args.json:
        print(json.dumps({"who": args.who or notify.origin_id(), "notices": rows},
                         indent=2))
    elif not rows:
        print("no unread notices")
    else:
        for row in rows:
            print(f"[{row.get('at', '?')}] {row.get('kind', '?')} "
                  f"{('(' + row['ref'] + ')') if row.get('ref') else ''}")
            for line in (row.get("body") or "").splitlines():
                print(f"  {line}")
    if args.read:
        mark_notices_read(args.who)
        print(f"marked {len(rows)} notice(s) read", file=sys.stderr)
    return 0


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
    # TWO SEPARATE QUESTIONS, and collapsing them was a real mistake in the first draft
    # of this. "Does it interrupt someone" is not "is it a failure": a run waiting on
    # your review needs you now, and is the gate working exactly as designed. Shipping
    # that as an error teaches people that red means nothing, which costs you the
    # escalations that genuinely are red.
    interrupts = kind in ("blocked", "conflict", "waiting", "done")
    severity = ("error" if kind in ("blocked", "conflict")
                else "warn" if kind == "waiting" else "info")
    urgent = severity == "error"
    where = coordination.journal(kind, subject, body, by)
    message = subject if not body else f"{subject}\n{body}"[:8192]
    delivered = notify_orchestrator("error" if urgent else "status", message, ref=ref)

    # AND BACK TO WHOEVER ASKED FOR THE WORK.
    #
    # The orchestrator inbox is a shared tray; it is not the session that opened this
    # run and is waiting on the answer. Written as a SECOND copy rather than instead of
    # the first, because the shared tray is what `agentmux inbox` and the dashboard
    # already read, and a notice that moved out of it would vanish from both.
    state = fold(load_events(run_id))
    origin = state.get("origin")
    if origin and origin != "orchestrator":
        notify_orchestrator("error" if urgent else "status", message, ref=ref,
                            recipient=origin)

    # OUT-OF-PROCESS CHANNELS, and only for what is worth interrupting someone for.
    # A passing verdict is not. These are bounded and never raise: a toast that could
    # not be drawn must not be able to stop a run from completing.
    channels = []
    if interrupts:
        try:
            channels = notify.deliver(
                subject, body, severity, ref=ref,
                toast_enabled=os.environ.get("AGENTMUX_NOTIFY_TOAST", "1") != "0",
                command=os.environ.get("AGENTMUX_NOTIFY_COMMAND", ""),
                pane=state.get("pane"))
        except Exception as err:               # never trust an operator-supplied command
            channels = [{"channel": "notify", "ok": False, "reason": type(err).__name__}]
    for row in [c for c in channels if not c["ok"]]:
        print(f"  WARNING: {row['channel']} notification failed: {row['reason']}",
              file=sys.stderr)

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
        by = coordination.orchestrator_identity("start", args.by)
    except coordination.IdentityError as err:
        print(err, file=sys.stderr)
        return 2
    # A run is identified on the board by its request line. An empty one produces a
    # blank row that nobody can match to anything, and the reviewer of every job in it
    # has no statement of what was wanted to check against.
    if not (args.request or "").strip():
        print("run: a run needs a request - say what it is for", file=sys.stderr)
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
        # WHERE THIS WAS ASKED FOR, so a notice can go back to it. The toast reaches
        # whoever is at this machine's desktop; it does not reach the session holding
        # the context that knows what the run was for. That session is the one that has
        # to look when the run stops at the operator gate.
        append_event(run_id, {"event": "start", "by": by,
                              "base": repo_head(REPO_ROOT),
                              "via": coordination.orchestrator_pane(),
                              "origin": notify.origin_id(),
                              "pane": os.environ.get("TMUX_PANE") or None,
                              "detail": args.request[:DETAIL_MAX]})
        coordination.journal("plan", f"run {run_id} started", args.request[:2000], by)
        print(run_id)
        return 0
    print("run: could not allocate a run id", file=sys.stderr)
    return 1


def cmd_assign(args):
    try:
        by = coordination.orchestrator_identity("assign")
    except coordination.IdentityError as err:
        print(err, file=sys.stderr)
        return 2
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

    # A COMPLETE RUN TAKES NO NEW WORK, AND THE CHECK IS TAKEN UNDER THE SAME LOCK
    # cmd_complete HOLDS.
    #
    # submit and verdict have always refused once the marker exists; assign did not,
    # so a job could be added to a run that had already passed the gate - leaving a
    # run that reads COMPLETE and "1/2 verified" at the same time. That is the exact
    # contradiction the gate exists to prevent, arrived at from the other side.
    #
    # Checking it outside the lock only narrows the window rather than closing it:
    # assign reads the marker as absent, complete then takes the lock, folds, writes
    # COMPLETE and releases, and assign's append lands afterwards - producing the same
    # contradiction concurrently instead of sequentially. cmd_verdict already takes
    # its marker check inside run_lock for precisely this reason; assign now matches.
    with run_lock(args.run, "assign"):
        if complete_path(args.run).exists():
            print(f"run: {args.run} is already complete; no job can be assigned to it "
                  f"now", file=sys.stderr)
            return 2
        jobs_root = run_dir(args.run) / "jobs"
        jobs_root.mkdir(parents=True, exist_ok=True)
        for index in range(1, 10000):
            directory = jobs_root / str(index)
            try:
                directory.mkdir()                  # atomic id allocation
            except FileExistsError:
                continue
            job = f"{args.run}/{index}"
            if args.brief:
                (directory / "brief.md").write_text(args.brief, encoding="utf-8")
            append_event(args.run, {"event": "assign", "job": job, "by": by,
                                    "via": coordination.orchestrator_pane(),
                                    "worker": args.worker,
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
        by = coordination.resolve_identity(args.by, f"submit {args.job}")
    except coordination.IdentityError as err:
        print(err, file=sys.stderr)
        return 2

    # UNDER THE LOCK, for the same reason assign is: the fold, the marker check and
    # the append are a read-decide-write across a file that cmd_complete also writes.
    # Outside it, a submission can land after COMPLETE was taken.
    with run_lock(run_id, "submit"):
        return _submit_locked(args, run_id, index, by)


def _submit_locked(args, run_id, index, by):
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
    # ONLY AN OPEN JOB TAKES A SUBMISSION, and the two states this excludes are the
    # two that matter.
    #
    # `verified` - a worker resubmitting onto its own passed job silently un-verified
    # it. Measured: verified -> submitted, and one `verdict --fail` later the run that
    # was ready to complete is blocked again. Review is meant to be a ratchet.
    #
    # `escalated` - three failed reviews park a job for a person. A fourth submission
    # moved it back to `submitted`, so the worker could hand itself a fourth review
    # and the MAX_ATTEMPTS bound meant nothing. Worse, it cleared the one state the
    # human was told to come and look at.
    if row["state"] not in OPEN_STATES:
        extra = ("\n  It is parked for the operator after "
                 f"{MAX_ATTEMPTS} failed reviews; only they can restart it."
                 if row["state"] == "escalated" else "")
        print(f"run: {args.job} is {row['state']}; it cannot be submitted now.{extra}",
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
        by = coordination.resolve_identity(args.by, f"verify {args.job}")
    except coordination.IdentityError as err:
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

    # THE RUN HAS STOPPED AND IS WAITING ON A PERSON.
    #
    # This is the notice the operator gate made necessary. Everything else the harness
    # announces is something that happened; this one is a request, and until it is
    # answered nothing else moves. Without it the gate turns an orchestration into a
    # thing that silently stalls the moment nobody happens to be looking at the Runs
    # view - which is most of the time, because the whole point was not having to watch.
    #
    # Fired from the LAST verdict rather than from the orchestrator, so it is true for
    # a run driven by hand as well as an autonomous one, and so a persona that forgets
    # to announce itself cannot suppress it.
    settled = fold(load_events(run_id))
    if (args.passed and settled["jobs"]
            and not any(r["state"] in BLOCKING for r in settled["jobs"].values())
            and not complete_path(run_id).exists()
            and not load_approval(run_id)):
        total = len(settled["jobs"])
        record_notice(run_id, "waiting", f"run {run_id} is waiting on your review",
                      f"All {total} job(s) verified. Read the diff and approve it "
                      f"before this run can complete: agentmux run status {run_id}",
                      by, ref=run_id)
        print(f"  all {total} job(s) verified - this run now needs YOUR approval "
              f"before it can complete")

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
    if not args.json:
        print_unread()
    if not valid_run(args.run):
        print(f"run: invalid run id {args.run!r}", file=sys.stderr)
        return 2
    # A well-formed id for a run that was never started folded to an empty state and
    # printed "open / no jobs assigned" with exit 0, so a mistyped id polls as a live
    # run forever. assign, complete and write_approval all check the directory; the
    # dashboard checks it too (runsview.detail). status was the one that did not.
    if not run_dir(args.run).is_dir():
        print(f"run: no such run {args.run}", file=sys.stderr)
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
        by = coordination.orchestrator_identity("complete", args.by)
    except coordination.IdentityError as err:
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

        # WHO IS CALLING. None for a person at a terminal, the pane name for a
        # warranted orchestrator. Both rules below turn on this distinction, so it is
        # resolved once, first.
        via = coordination.orchestrator_pane()

        # --FORCE IS NOT THE ORCHESTRATOR'S TO USE, and this is checked FIRST.
        #
        # Ordering matters for the message rather than the outcome: an orchestrator
        # forcing without an approval is refused either way, but "get approval" would
        # send it off to obtain one and bring it straight back to a second, different
        # refusal. The flag is never available to it, so say that.
        #
        # Without this the whole verification gate is one flag deep for an agent that
        # decides it has waited long enough, and "FORCED" in a ledger is only a control
        # if somebody reads ledgers. --force exists for a run whose agents died, which
        # is an accident a person judges; an autonomous orchestrator meeting that case
        # should escalate, not overrule.
        if args.force and via:
            print(f"REFUSED: --force is not available to {via!r}.", file=sys.stderr)
            print("  A warranted pane may complete a VERIFIED run; forcing past an "
                  "unverified one\n  is a person's call. Escalate it instead.",
                  file=sys.stderr)
            return 2

        # THE OPERATOR'S DECISION, CHECKED INSIDE THE SAME LOCK AS THE GATE.
        #
        # Taken before the verification gate because it outranks it: if the person who
        # asked for the work has said it is not what they wanted, how many reviewers
        # passed it is beside the point. --force does not reach here at all for a
        # warranted caller, and for a person it does not override a stated objection.
        objection = approval_blocks_completion(args.run, agent=via)
        if objection:
            print(f"REFUSED: {objection}", file=sys.stderr)
            return 1

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
                                "by": by, "via": via,
                                "detail": f"{len(state['jobs']) - len(blocking)}"
                                          f"/{len(state['jobs'])} verified"})
    verified = len(state["jobs"]) - len(blocking)
    summary = (f"run {args.run} {'FORCED' if blocking else 'COMPLETE'}: "
               f"{verified}/{len(state['jobs'])} jobs verified")
    # THE WIRE THE EP-021 FAILURE EXPOSED: say what this leaves on the board.
    cards, card_lines = report_cards(state)
    if cards:
        summary += f"; {cards}"
    if blocking:
        summary += f"; unverified: {', '.join(blocking)}; see {report}"
    record_notice(args.run, "done" if not blocking else "conflict",
                  summary, state["request"] or "", by, ref=args.run)
    print(summary)
    for line in card_lines:
        print(line)
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

    notices = sub.add_parser("notices")
    notices.add_argument("--who", default=None)
    notices.add_argument("--read", action="store_true",
                         help="mark them read so they stop being surfaced")
    notices.add_argument("--json", action="store_true")
    notices.set_defaults(func=cmd_notices)

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
