#!/usr/bin/env python3
"""Work claims, dependency declarations, and the shared journal.

WHY THIS EXISTS
---------------
Three agents on one repo with unrestricted permissions will, given the chance, edit the
same file at the same time. Nothing in the harness stopped that: the message queue
carried conversation, and conversation is not coordination. An agent could announce "I
am editing courier.py" into a pane and another agent could simply not be listening.

So a claim is a FILE, taken atomically, not a message. `O_CREAT | O_EXCL` means exactly
one agent wins a race; the loser is told who holds it and since when. The broadcast that
follows is a courtesy for humans and for agents that are paying attention - it is not
what provides the mutual exclusion.

Claims carry a LEASE. An agent that crashes, is killed, or simply wanders off must not
hold a file forever, so every claim expires and an expired claim is takeable. The
default is deliberately short enough that a forgotten claim clears itself within an hour
and long enough that real work is not interrupted.

DEPENDENCIES are declarations, not locks: "my work on X assumes Y". They are recorded on
the claim and reported by `claims`, so an agent about to touch Y can see who is relying
on it. Enforcing them would mean building a scheduler; surfacing them costs nothing and
catches the common case, which is two agents unknowingly pulling in opposite directions.

    python3 taskmgmt/coordination.py claim <resource> --holder <agent> [--ttl S]
    python3 taskmgmt/coordination.py release <resource> --holder <agent>
    python3 taskmgmt/coordination.py claims [--json]
    python3 taskmgmt/coordination.py journal <kind> <subject> [--body B] [--agent A]
"""
import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("AGENTMUX_HOME", str(Path.home() / ".agentmux")))
CLAIMS_DIR = ROOT / "claims"
QUEUE_DIR = ROOT / "queue"
JOURNAL_FALLBACK = ROOT / "journal.jsonl"

DASHBOARD = os.environ.get("AGENTMUX_DASHBOARD", "http://127.0.0.1:8787")
SOCKET = os.environ.get("AGENTMUX_SOCKET", "agentmux")

NAME_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,64}")
# A resource is usually a repo-relative path, so slashes are allowed - but nothing
# that would escape the claims directory once flattened.
RESOURCE_PATTERN = re.compile(r"[A-Za-z0-9_./-]{1,200}")

DEFAULT_TTL = 1800          # 30 minutes
MAX_TTL = 86400

# Journal kinds this CLI accepts.
#
# CORRECTION (2026-09-22): an earlier version of this comment claimed the dashboard
# rejects anything else. It does not - ccstore.validate_write accepts any token up to
# 64 characters and stores it, and app.js uses its own four-value set only to pick a
# CSS class. So the three sets disagree and nothing is dropped; the effect is purely
# cosmetic, and the kinds below render unstyled. Do not "fix" that by narrowing this
# list to app.js's four, which would lose `claim`, `release`, `handoff` and `blocked`
# - the ones that carry coordination meaning.
JOURNAL_KINDS = ("claim", "release", "conflict", "note", "handoff", "blocked",
                 "done", "plan")


def flatten(resource):
    """One claim file per resource, with no path traversal possible."""
    return resource.strip("/").replace("/", "%2F") + ".json"


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S") + time.strftime("%z")


def live_agents():
    try:
        done = subprocess.run(["tmux", "-L", SOCKET, "list-sessions", "-F",
                               "#{session_name}"],
                              capture_output=True, text=True, timeout=10)
        if done.returncode != 0:
            return set()
        return {line.strip() for line in done.stdout.splitlines() if line.strip()}
    except (OSError, subprocess.SubprocessError):
        return set()


def read_claim(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def expired(claim):
    try:
        return float(claim.get("expires_at", 0)) <= time.time()
    except (TypeError, ValueError):
        return True


def all_claims(include_expired=False):
    out = []
    if not CLAIMS_DIR.is_dir():
        return out
    for path in sorted(CLAIMS_DIR.glob("*.json")):
        claim = read_claim(path)
        if claim is None:
            continue
        claim["_expired"] = expired(claim)
        if claim["_expired"] and not include_expired:
            continue
        out.append(claim)
    return out


# ── the queue and the journal ────────────────────────────────────────────────

def post(sender, recipient, kind, body, ref=None):
    """Append straight to the sender's outbox - the same format `agentmux post` uses."""
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    path = QUEUE_DIR / f"{sender}.jsonl"
    if path.is_symlink() or (path.exists() and path.stat().st_nlink != 1):
        return False
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": now(), "sender": sender, "recipient": recipient,
                                 "kind": kind, "body": body[:65536], "ref": ref}) + "\n")
    os.chmod(path, 0o600)
    return True


def interested_in(resource, sender):
    """Who actually needs to hear about this resource changing hands.

    WHY NOT EVERYONE. A delivered message is typed into a pane and Entered, which
    starts a FULL INFERENCE TURN in the recipient: a 30-token notice costs whatever
    that agent's whole context costs. Telling every agent about every claim was 29.8%
    of all deliveries measured on this machine, and almost all of it was noise - an
    agent that never touches the resource gains nothing from being interrupted.

    It is safe to say nothing, and the codebase already says so twice: exclusion comes
    from the claim FILE. An agent that never heard about a claim discovers it the
    moment it tries to take the resource, and is then told the holder, their note, the
    expiry and how to reach them - the information arrives when it is actionable.

    What genuinely IS lost by silence is the dependency warning, so that is exactly the
    target set: agents whose declared dependencies touch this resource, and agents
    holding something this resource depends on. In the common case that set is empty
    and no one is interrupted at all.
    """
    targets = set()
    for claim in all_claims():
        holder = claim.get("holder")
        if not holder or holder == sender:
            continue
        depends = claim.get("depends_on") or []
        if resource in depends:
            targets.add(holder)                 # they are relying on this resource
        elif claim.get("resource") == resource:
            targets.add(holder)                 # stale duplicate; tell them anyway
    return targets


def broadcast(sender, kind, body, skip=(), resource=None, everyone=False):
    """Notify the agents that need to know. Best effort by design.

    Mutual exclusion comes from the claim file, never from this. If an agent is down
    or not reading, the claim still holds and the next `claim` attempt still fails.

    Pass `everyone=True` only for something that genuinely concerns all agents. The
    default is the interested set, which is usually nobody.
    """
    live = live_agents()
    if everyone or resource is None:
        audience = live
    else:
        audience = interested_in(resource, sender) & live
    sent = 0
    for agent in sorted(audience):
        if agent == sender or agent in skip:
            continue
        if post(sender, agent, kind, body):
            sent += 1
    return sent


def journal(kind, subject, body="", agent=None):
    """Write to the shared journal the dashboard renders.

    Falls back to a local file when the dashboard is down, because a coordination
    record that only exists when a web server happens to be running is not a record.
    """
    payload = {"kind": kind, "subject": subject[:2000], "body": (body or "")[:8192]}
    if agent:
        payload["agent"] = agent
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(f"{DASHBOARD}/api/journal", method="POST",
                                     data=data,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            json.loads(response.read())
        return "dashboard"
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        try:
            with JOURNAL_FALLBACK.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"at": now(), **payload}) + "\n")
            os.chmod(JOURNAL_FALLBACK, 0o600)
            return "local file (dashboard unreachable)"
        except OSError:
            return "NOWHERE - journal write failed"


# ── claim / release ──────────────────────────────────────────────────────────

def cmd_claim(args):
    if not RESOURCE_PATTERN.fullmatch(args.resource) or ".." in args.resource:
        print(f"coordination: invalid resource name {args.resource!r}", file=sys.stderr)
        return 2
    if not NAME_PATTERN.fullmatch(args.holder):
        print(f"coordination: invalid holder {args.holder!r}", file=sys.stderr)
        return 2
    ttl = max(60, min(args.ttl, MAX_TTL))
    CLAIMS_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(CLAIMS_DIR, 0o700)
    path = CLAIMS_DIR / flatten(args.resource)

    record = {
        "resource": args.resource, "holder": args.holder, "at": now(),
        "ttl": ttl, "expires_at": time.time() + ttl,
        "note": (args.note or "")[:500],
        "task": args.task or None,
        "depends_on": [d for d in (args.depends_on or []) if RESOURCE_PATTERN.fullmatch(d)],
    }

    # WRITE FIRST, THEN PUBLISH ATOMICALLY.
    #
    # The obvious version - O_EXCL create, then write the JSON into the fd - has a
    # window where the claim file EXISTS BUT IS EMPTY. A concurrent claimant opening
    # it in that window gets None from read_claim, concludes the claim is malformed
    # and therefore takeable, unlinks it and creates its own. Two winners, silently.
    #
    # Caught by the 12-way race in test_coordination.sh only after an unrelated change
    # shifted the timing, which is the usual way a latent race announces itself.
    #
    # os.link() is atomic and fails with FileExistsError if the target exists, so the
    # file becomes visible only once it already contains a complete record.
    staging = CLAIMS_DIR / f".{os.getpid()}.{secrets.token_hex(4)}.tmp"
    staging.write_text(json.dumps(record), encoding="utf-8")
    os.chmod(staging, 0o600)

    for attempt in (1, 2):
        try:
            os.link(staging, path)
            staging.unlink()
            break
        except FileExistsError:
            existing = read_claim(path)
            if existing is None or expired(existing):
                # Genuinely dead or corrupt - takeable. An empty file from a crashed
                # claimant also lands here, which is correct: nobody holds it.
                try:
                    path.unlink()
                except OSError:
                    pass
                if attempt == 1:
                    continue
                staging.unlink(missing_ok=True)
                print("coordination: could not take an expired claim", file=sys.stderr)
                return 1
            if existing.get("holder") == args.holder:
                # Re-claiming your own is a renewal, not a conflict.
                staging.unlink(missing_ok=True)
                with path.open("w", encoding="utf-8") as handle:
                    json.dump(record, handle)
                print(f"renewed claim on {args.resource} "
                      f"({ttl}s, expires {time.strftime('%H:%M:%S', time.localtime(record['expires_at']))})")
                return 0
            staging.unlink(missing_ok=True)
            held_for = int(time.time() - float(existing.get("expires_at", 0)) + existing.get("ttl", 0))
            print(f"REFUSED: '{args.resource}' is held by {existing['holder']}"
                  f" since {existing.get('at')} ({held_for}s ago)", file=sys.stderr)
            if existing.get("note"):
                print(f"  their note: {existing['note']}", file=sys.stderr)
            print(f"  it expires in "
                  f"{max(0, int(float(existing.get('expires_at', 0)) - time.time()))}s",
                  file=sys.stderr)
            print(f"  talk to them: agentmux post {existing['holder']} --kind request "
                  f"\"...\"", file=sys.stderr)
            journal("conflict",
                    f"{args.holder} blocked on {args.resource}",
                    f"held by {existing['holder']}; {args.note or ''}", args.holder)
            post(args.holder, existing["holder"], "request",
                 f"CLAIM CONFLICT: I need {args.resource}, you hold it. "
                 f"{args.note or ''}".strip())
            return 1

    where = journal("claim", f"{args.holder} claimed {args.resource}",
                    args.note or "", args.holder)
    depends = (" depends-on=" + ",".join(record["depends_on"])) if record["depends_on"] else ""
    told = broadcast(args.holder, "claim",
                     f"CLAIM {args.resource} by {args.holder} for {ttl}s"
                     f"{depends}. {args.note or ''}".strip(),
                     resource=args.resource)
    print(f"claimed {args.resource} for {ttl}s")
    print(f"  journal: {where}")
    print(f"  told {told} interested agent(s)"
          + ("" if told else " - nobody else depends on this"))
    if record["depends_on"]:
        holders = {c["resource"]: c["holder"] for c in all_claims()}
        for dep in record["depends_on"]:
            other = holders.get(dep)
            if other and other != args.holder:
                print(f"  NOTE: you depend on {dep}, currently held by {other}")
    return 0


def cmd_release(args):
    path = CLAIMS_DIR / flatten(args.resource)
    existing = read_claim(path)
    if existing is None:
        print(f"no claim on {args.resource}")
        return 0
    if existing.get("holder") != args.holder and not args.force:
        print(f"REFUSED: {args.resource} is held by {existing['holder']}, not "
              f"{args.holder}. Use --force only if you know they are gone.",
              file=sys.stderr)
        return 1
    try:
        path.unlink()
    except OSError as err:
        print(f"coordination: could not release: {err}", file=sys.stderr)
        return 1
    journal("release", f"{args.holder} released {args.resource}", "", args.holder)
    broadcast(args.holder, "release", f"RELEASE {args.resource} by {args.holder}",
              resource=args.resource)
    print(f"released {args.resource}")
    return 0


def cmd_claims(args):
    claims = all_claims(include_expired=args.all)
    if args.json:
        print(json.dumps(claims, indent=2))
        return 0
    if not claims:
        print("no active claims")
        return 0
    live = live_agents()
    print(f"{'RESOURCE':<44} {'HOLDER':<12} {'EXPIRES IN':<11} {'TASK':<10} NOTE")
    for claim in claims:
        left = int(float(claim.get("expires_at", 0)) - time.time())
        holder = claim.get("holder", "?")
        flag = "" if holder in live else "  (holder not running)"
        print(f"{claim.get('resource', '?')[:44]:<44} {holder:<12} "
              f"{(str(max(0, left)) + 's'):<11} {str(claim.get('task') or '-'):<10} "
              f"{(claim.get('note') or '')[:40]}{flag}")
        for dep in claim.get("depends_on") or []:
            print(f"    depends on: {dep}")
    return 0


def cmd_journal(args):
    if args.kind not in JOURNAL_KINDS:
        print(f"coordination: kind must be one of {', '.join(JOURNAL_KINDS)}",
              file=sys.stderr)
        return 2
    where = journal(args.kind, args.subject, args.body or "", args.agent)
    print(f"journalled ({args.kind}): {args.subject}")
    print(f"  written to: {where}")
    return 0


# ── the task board ───────────────────────────────────────────────────────────
#
# The board already existed and agents did not use it, because using it meant hand
# writing JSON at an HTTP endpoint. A rule that says "use the task board" and a board
# that takes a curl invocation are not compatible; one of them loses, and it is never
# the convenient one. These verbs make the board the path of least resistance.

TASK_STATUSES = ("todo", "in_progress", "blocked", "done", "cancelled")


def api(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{DASHBOARD}/api/{path}", method=method, data=data,
        headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def cmd_tasks(args):
    try:
        epics = api("GET", "epics").get("epics", [])
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as err:
        print(f"coordination: dashboard unreachable at {DASHBOARD} ({err})",
              file=sys.stderr)
        print("  start it with: python3 dashboard/server.py", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(epics, indent=2))
        return 0
    mine = args.mine
    shown = 0
    for epic in epics:
        tasks = [t for t in epic.get("tasks", [])
                 if (not mine or t.get("agent") == mine)
                 and (args.all or t.get("status") not in ("done", "cancelled"))]
        if not tasks:
            continue
        print(f"\nepic {epic['id']}  {epic.get('title', '')}  [{epic.get('status')}]")
        for task in tasks:
            shown += 1
            print(f"  {task['id']:>4}  {task.get('status', '?'):<12} "
                  f"{(task.get('agent') or '-'):<10} {task.get('title', '')[:70]}")
    if not shown:
        print("no open tasks" + (f" for {mine}" if mine else ""))
    return 0


def cmd_task_status(args):
    if args.status not in TASK_STATUSES:
        print(f"coordination: status must be one of {', '.join(TASK_STATUSES)}",
              file=sys.stderr)
        return 2
    try:
        row = api("POST", "status", {"kind": "task", "id": args.id,
                                     "status": args.status})
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as err:
        print(f"coordination: could not update task {args.id}: {err}", file=sys.stderr)
        return 1
    print(f"task {row['id']} -> {row['status']}  {row.get('title', '')[:60]}")
    # A status change is a coordination event, so it goes in the journal too - the
    # board records state, the journal records that a human or agent decided it.
    journal("done" if args.status == "done" else "note",
            f"task {row['id']} -> {args.status}", row.get("title", ""), args.agent)
    return 0


def cmd_task_add(args):
    try:
        row = api("POST", "tasks", {"epic_id": args.epic, "title": args.title,
                                    "agent": args.agent or None})
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as err:
        print(f"coordination: could not create the task: {err}", file=sys.stderr)
        return 1
    print(f"task {row['id']} created in epic {args.epic}: {row.get('title', '')[:60]}")
    journal("plan", f"task {row['id']} created", row.get("title", ""), args.agent)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="agent work coordination")
    sub = parser.add_subparsers(dest="command", required=True)

    tasks = sub.add_parser("tasks")
    tasks.add_argument("--mine", default=None, help="only this agent's tasks")
    tasks.add_argument("--all", action="store_true", help="include done and cancelled")
    tasks.add_argument("--json", action="store_true")
    tasks.set_defaults(func=cmd_tasks)

    status = sub.add_parser("task-status")
    status.add_argument("id", type=int)
    status.add_argument("status")
    status.add_argument("--agent", default=None)
    status.set_defaults(func=cmd_task_status)

    add = sub.add_parser("task-add")
    add.add_argument("epic", type=int)
    add.add_argument("title")
    add.add_argument("--agent", default=None)
    add.set_defaults(func=cmd_task_add)

    claim = sub.add_parser("claim")
    claim.add_argument("resource")
    claim.add_argument("--holder", required=True)
    claim.add_argument("--ttl", type=int, default=DEFAULT_TTL)
    claim.add_argument("--note", default="")
    claim.add_argument("--task", default="")
    claim.add_argument("--depends-on", action="append", default=[])
    claim.set_defaults(func=cmd_claim)

    release = sub.add_parser("release")
    release.add_argument("resource")
    release.add_argument("--holder", required=True)
    release.add_argument("--force", action="store_true")
    release.set_defaults(func=cmd_release)

    listing = sub.add_parser("claims")
    listing.add_argument("--json", action="store_true")
    listing.add_argument("--all", action="store_true", help="include expired")
    listing.set_defaults(func=cmd_claims)

    entry = sub.add_parser("journal")
    entry.add_argument("kind")
    entry.add_argument("subject")
    entry.add_argument("--body", default="")
    entry.add_argument("--agent", default=None)
    entry.set_defaults(func=cmd_journal)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
