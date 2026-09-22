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

# Journal kinds the dashboard accepts; anything else is rejected there, so validate
# here and say so rather than failing silently over HTTP.
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


def broadcast(sender, kind, body, skip=()):
    """Tell every other live agent. Best effort by design.

    Mutual exclusion comes from the claim file, never from this. If an agent is down
    or not reading, the claim still holds and the next `claim` attempt still fails.
    """
    sent = 0
    for agent in sorted(live_agents()):
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

    for attempt in (1, 2):
        try:
            # O_EXCL is the whole mechanism: exactly one writer wins.
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            existing = read_claim(path)
            if existing is None or expired(existing):
                # A dead or malformed claim is takeable. Remove and retry once.
                try:
                    path.unlink()
                except OSError:
                    pass
                if attempt == 1:
                    continue
                print("coordination: could not take an expired claim", file=sys.stderr)
                return 1
            if existing.get("holder") == args.holder:
                # Re-claiming your own is a renewal, not a conflict.
                with path.open("w", encoding="utf-8") as handle:
                    json.dump(record, handle)
                print(f"renewed claim on {args.resource} "
                      f"({ttl}s, expires {time.strftime('%H:%M:%S', time.localtime(record['expires_at']))})")
                return 0
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
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(record, handle)
            break

    where = journal("claim", f"{args.holder} claimed {args.resource}",
                    args.note or "", args.holder)
    depends = (" depends-on=" + ",".join(record["depends_on"])) if record["depends_on"] else ""
    told = broadcast(args.holder, "claim",
                     f"CLAIM {args.resource} by {args.holder} for {ttl}s"
                     f"{depends}. {args.note or ''}".strip())
    print(f"claimed {args.resource} for {ttl}s")
    print(f"  journal: {where}")
    print(f"  told {told} other agent(s)")
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
    broadcast(args.holder, "release", f"RELEASE {args.resource} by {args.holder}")
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


def main(argv=None):
    parser = argparse.ArgumentParser(description="agent work coordination")
    sub = parser.add_subparsers(dest="command", required=True)

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
