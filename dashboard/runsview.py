"""Runs, read-only, for the dashboard - plus the one human gate in front of completion.

WHY THIS EXISTS. The run gate in taskmgmt/run.py decides whether work is finished, and
until now it had no HTTP surface at all: nothing under dashboard/ ever opened
~/.agentmux/runs/. You could watch panes scroll and read the journal, but the question
an operator actually has during a run - what is blocking completion, and who is it
waiting on - could only be answered by running `agentmux run status` in a terminal.

THE RULE THIS MODULE OBEYS. It never re-implements the fold. run.fold() is the single
answer to "what happened in this run", derived from an append-only log, and a second
implementation here would be a second answer that drifts from the first. Everything
below imports run.py and calls it. For the same reason this module never writes
events.jsonl directly: run.append_event is O_APPEND with records bounded by EVENT_MAX
so one append is atomic, and a second writer that does not share that discipline breaks
the guarantee the whole design rests on. Where an event is needed, run.append_event
writes it.
"""
from pathlib import Path
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "taskmgmt"))
import coordination
import run as runmod

REPO = Path(__file__).resolve().parents[1]

LIST_MAX = 50               # runs returned at once
DIFF_MAX = 120_000          # bytes of diff served for one review
DIFF_FILES = 60             # paths a single diff request will name
NOTE_MAX = 2000


class ReviewError(Exception):
    """Refused for a stated reason the operator should read."""


# ── approval: the human gate in front of completion ──────────────────────────
#
# An orchestrating AGENT can verify every job and still be wrong about whether the work
# was what was wanted. A reviewer verdict answers "was the job done"; it cannot answer
# "was that the right job", because the same orchestrator wrote the brief the reviewer
# is checking against. So a run driven by the CCC orchestrator stops here and waits for
# a person, who reads the diff and says yes.
#
# The approval PINS BYTES. run.digest() exists because a verdict naming files without
# hashing them describes bytes that may since have changed; approval has the same
# exposure and a worse consequence, being the last gate. An approval records the digest
# of every submitted file, and completion re-digests and refuses if anything moved.
# Otherwise "approved" only ever meant "approved something".

# The approval itself lives in run.py, which owns the run directory and the gate that
# reads it. Keeping a second copy here would give the gate and the surface that drives
# it two definitions of what an approval is, and they would drift.

approval_path = runmod.approval_path
submitted_files = runmod.submitted_files
load_approval = runmod.load_approval


def approval_drift(run_id):
    # A wrapper rather than an alias: the repo this module digests against is a
    # module attribute so a suite can point it at a scratch checkout, and a bare
    # alias would bind run.py's default instead and silently hash the wrong tree.
    return runmod.approval_drift(run_id, REPO)


def write_approval(run_id, by, note, decision="approved"):
    try:
        return runmod.write_approval(run_id, by, note, decision, repo=REPO)
    except ValueError as err:
        # run.py raises ValueError because it is a library; the HTTP layer wants one
        # exception type it can map to 409 with the reason intact.
        raise ReviewError(str(err)) from None


def review_state(run_id, state, complete):
    """What the operator is being asked for on this run, if anything."""
    blank = {"state": None, "by": None, "at": None, "note": None, "drift": []}
    record = load_approval(run_id)
    blocking = [j for j, r in state["jobs"].items() if r["state"] in runmod.BLOCKING]
    if record and record.get("decision") == "changes":
        return dict(blank, state="changes", by=record.get("by"),
                    at=record.get("at"), note=record.get("note"))
    if record and record.get("decision") == "approved":
        drift = approval_drift(run_id) or ()
        return dict(blank, state=("stale" if drift else "approved"),
                    by=record.get("by"), at=record.get("at"),
                    note=record.get("note"), drift=list(drift))
    if complete or not state["jobs"] or blocking:
        return blank
    return dict(blank, state="pending")


# ── the diff an operator reviews ─────────────────────────────────────────────

def review_diff(run_id):
    """`git diff` over exactly the paths this run's jobs submitted.

    Scoped rather than a whole-repo diff on purpose. The question being asked is "did
    this run do what it said", and a diff carrying unrelated working-tree changes
    invites approving something the run never touched.
    """
    if not runmod.valid_run(run_id):
        raise ReviewError(f"invalid run id {run_id!r}")
    if not runmod.run_dir(run_id).is_dir():
        raise ReviewError(f"no such run {run_id}")
    state = runmod.fold(runmod.load_events(run_id))
    files = submitted_files(state)
    if not files:
        return {"files": [], "rejected": [], "diff": "", "base": state.get("base"),
                "against": None, "truncated": False,
                "note": "no job in this run named any files"}
    safe, rejected = [], []
    for name in files[:DIFF_FILES]:
        # A submitted path is agent-authored text. It names a file inside the repo, or
        # it does not get near git.
        if name.startswith("-") or "\x00" in name:
            rejected.append(name)         # never let a path become a git flag
            continue
        try:
            (REPO / name).resolve().relative_to(REPO)
        except (OSError, ValueError):
            rejected.append(name)
            continue
        safe.append(name)
    # DIFF AGAINST THE RUN'S STARTING COMMIT, not against HEAD.
    #
    # `git diff HEAD` was the obvious thing and it is wrong here: the moment a worker
    # commits, that diff goes empty and this review surface shows nothing while the
    # work sits in the history. Diffing from the base recorded at `run start` covers
    # committed and uncommitted work in one comparison, for the whole life of the run.
    # Runs opened before the base was recorded fall back to HEAD and say so, rather
    # than silently showing an operator a diff that means something else.
    base = state.get("base")
    if base and not re.fullmatch(r"[0-9a-f]{40}", str(base)):
        base = None
    if base and not _have_commit(base):
        base = None                      # rebased or garbage-collected since
    against = base or "HEAD"
    out, truncated = "", len(files) > DIFF_FILES
    if safe:
        try:
            proc = subprocess.run(
                ["git", "-C", str(REPO), "diff", against, "--"] + safe,
                capture_output=True, text=True, timeout=25, errors="replace")
            out = proc.stdout or ""
            if proc.returncode != 0 and not out:
                out = f"(git diff failed: {(proc.stderr or '').strip()[:400]})"
        except (OSError, subprocess.SubprocessError) as err:
            out = f"(git diff unavailable: {type(err).__name__})"
        # A FILE GIT HAS NEVER SEEN IS INVISIBLE TO `git diff`.
        #
        # Most runs create files rather than editing them - the nettraffic run
        # submitted eight, every one of them new - and every one was absent from the
        # review with no indication anything was missing. An operator approving an
        # empty diff would have approved work they were never shown, which is the one
        # failure this whole gate exists to prevent. `--no-index` renders them as the
        # new files they are without touching the index.
        for name in untracked(safe):
            out += new_file_diff(name)
    if len(out) > DIFF_MAX:
        out, truncated = out[:DIFF_MAX], True
    note = "" if base else ("This run predates the recorded base commit, so the diff "
                            "is against HEAD - anything already committed will not "
                            "appear.")
    return {"files": safe, "rejected": rejected, "diff": out, "base": base,
            "against": against, "truncated": truncated, "note": note}


def untracked(names):
    """Of these paths, the ones git does not track. Asked in one call, not N."""
    if not names:
        return []
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO), "ls-files", "--others", "--exclude-standard",
             "--"] + list(names),
            capture_output=True, text=True, timeout=20, errors="replace")
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    found = {line.strip() for line in (proc.stdout or "").splitlines() if line.strip()}
    # Preserve the caller's order; a review reads better in submission order.
    return [n for n in names if n in found]


def new_file_diff(name):
    """A new file rendered as a diff, without staging it."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO), "diff", "--no-index", "--", os.devnull, name],
            capture_output=True, text=True, timeout=20, errors="replace")
    except (OSError, subprocess.SubprocessError) as err:
        return f"\n(new file {name}: unreadable, {type(err).__name__})\n"
    body = proc.stdout or ""
    if not body.strip():
        return f"\n(new file {name}: empty)\n"
    # --no-index labels the left side /dev/null, which is accurate but reads as
    # noise next to the tracked diffs above it. Say what it is instead.
    return f"\n=== new file: {name} ===\n{body}"


def _have_commit(sha):
    try:
        proc = subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", sha + "^{commit}"],
                              capture_output=True, timeout=10)
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# ── reading runs ─────────────────────────────────────────────────────────────

def live_or_unknown():
    """Live agent names, or None when tmux could not be asked.

    None and set() are different answers and the difference matters: an empty roster
    says every agent is gone, an unreachable tmux says nothing at all. Rendering the
    second as the first reports a whole run as stale because a socket blinked, which is
    the exact lie the stale flag exists to prevent.
    """
    try:
        return set(coordination.live_agents())
    except Exception:
        return None


def stale_for(state, live):
    if live is None:
        return None
    stale = {}
    for job, row in state["jobs"].items():
        if row["state"] in ("working", "assigned", "submitted"):
            who = row["worker"] if row["state"] != "submitted" else row["reviewer"]
            if who and who not in live:
                stale[job] = who
    return stale


def blocking_prose(state, stale):
    """The sentence an operator wants: what is holding this run, and on whom.

    The job table answers it eventually; this answers it at a glance, which is the
    difference between a status surface and a log.
    """
    parts = []
    for job, row in sorted(state["jobs"].items()):
        if row["state"] not in runmod.BLOCKING:
            continue
        gone = " (gone)" if stale and job in stale else ""
        if row["state"] == "submitted":
            parts.append(f"{job} submitted, waiting on "
                         f"{row['reviewer'] or 'an unnamed reviewer'}{gone}")
        elif row["state"] in ("assigned", "working"):
            verb = "working" if row["state"] == "working" else "assigned to"
            parts.append(f"{job} {verb} {row['worker'] or 'an unnamed worker'}{gone}")
        elif row["state"] == "rejected":
            parts.append(f"{job} rejected, attempt {row['attempts']} of "
                         f"{runmod.MAX_ATTEMPTS}")
        elif row["state"] == "escalated":
            parts.append(f"{job} escalated after {row['attempts']} failed reviews "
                         "- parked for you")
    return " · ".join(parts)


def summarise(run_id, live):
    state = runmod.fold(runmod.load_events(run_id))
    complete = runmod.complete_path(run_id).exists()
    stale = stale_for(state, live)
    jobs = state["jobs"]
    blocking = sorted(j for j, r in jobs.items() if r["state"] in runmod.BLOCKING)
    stamps = [r["last"] for r in jobs.values() if r["last"]]
    return {
        "run": run_id,
        "request": state["request"],
        "complete": complete,
        "forced": state["forced"],
        "jobs": len(jobs),
        "verified": len(jobs) - len(blocking),
        "blocking": blocking,
        "blockingText": blocking_prose(state, stale),
        "escalated": sorted(j for j, r in jobs.items() if r["state"] == "escalated"),
        "stale": stale,
        "started": min(stamps, default=None),
        "last": max(stamps, default=None),
        "review": review_state(run_id, state, complete),
    }


def run_ids():
    """Run ids newest first, by when the ledger was last appended to."""
    try:
        names = [p.name for p in runmod.RUNS_DIR.iterdir() if p.is_dir()]
    except OSError:
        return []
    out = []
    for name in names:
        if not runmod.valid_run(name):
            continue
        try:
            mtime = runmod.events_path(name).stat().st_mtime
        except OSError:
            mtime = 0.0
        out.append((mtime, name))
    out.sort(reverse=True)
    return [name for _, name in out]


def list_runs(limit=20):
    limit = max(1, min(int(limit or 20), LIST_MAX))
    live = live_or_unknown()
    return {"runs": [summarise(name, live) for name in run_ids()[:limit]],
            "maxAttempts": runmod.MAX_ATTEMPTS,
            "tmux": live is not None, "at": time.time()}


def detail(run_id):
    """One run, with per-job sidecar PRESENCE - never the sidecar bodies.

    A brief or a submission is unbounded agent-authored text, and serving it would put
    this read-only endpoint in the business of hosting it. Counts answer what the view
    actually asks ("has it submitted yet", "how many verdicts") without owning that.
    """
    if not runmod.valid_run(run_id):
        raise ReviewError(f"invalid run id {run_id!r}")
    if not runmod.run_dir(run_id).is_dir():
        raise ReviewError(f"no such run {run_id}")
    live = live_or_unknown()
    state = runmod.fold(runmod.load_events(run_id))
    stale = stale_for(state, live)
    try:
        claims = {c["resource"]: c["holder"] for c in coordination.all_claims()}
    except Exception:
        claims = {}
    jobs = []
    for job, row in sorted(state["jobs"].items()):
        _, index = runmod.split_job(job)
        directory = runmod.job_dir(run_id, index) if index is not None else None
        verdicts, has_brief, has_submission = 0, False, False
        if directory and directory.is_dir():
            has_brief = (directory / "brief.md").is_file()
            has_submission = (directory / "submission.md").is_file()
            try:
                verdicts = sum(1 for p in directory.iterdir()
                               if p.name.startswith("verdict-") and p.suffix == ".md")
            except OSError:
                verdicts = 0
        jobs.append(dict(row, stale=(None if stale is None else job in stale),
                         brief=has_brief, submission=has_submission,
                         verdicts=verdicts))
    return dict(summarise(run_id, live), jobs=jobs, claims=claims,
                maxAttempts=runmod.MAX_ATTEMPTS, tmux=live is not None)
