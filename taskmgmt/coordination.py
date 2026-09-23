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
import urllib.parse
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


class IdentityError(Exception):
    """Raised when a caller cannot be who it says it is. See resolve_identity."""


def resolve_identity(claimed, verb, require_live=True):
    """Return the identity to record, or raise IdentityError.

    `run verdict --by claude` used to be believed on the strength of the string. That
    is not a hypothetical weakness: during live testing the ORCHESTRATOR typed a
    verdict with --by set to the reviewer's name, and the ledger recorded a review
    that the reviewer never performed. The whole point of the reviewer field is that
    "verified" means someone other than the author looked.

    Rules:
      * $AGENTMUX_AGENT wins over --by, --holder, and --agent.
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
            f"identity: this pane is {env!r}, so it cannot {verb} as {claimed!r}.\n"
            f"  An explicit identity is not an override; drop it and the pane's own identity is used.")
    who = env or claimed
    if not who:
        raise IdentityError(f"identity: {verb} needs an identity "
                            f"(run it inside a pane, or pass an explicit identity)")
    if not NAME_PATTERN.fullmatch(who):
        raise IdentityError(f"identity: invalid identity {who!r}")
    if who == "orchestrator":
        return orchestrator_identity(verb, who, allow_test_identity=False)
    if require_live and os.environ.get("AGENTMUX_TRUST_IDENTITY") != "1":
        live = live_agents()
        if who not in live:
            raise IdentityError(
                f"identity: {who!r} is not a live agent, so it cannot {verb}.\n"
                f"  live: {', '.join(sorted(live)) or '(none)'}\n"
                f"  set AGENTMUX_TRUST_IDENTITY=1 only in tests, which run without tmux.")
    return who


def orchestrator_identity(verb, claimed=None, allow_test_identity=True):
    """Resolve the outside-pane identity, including run's legacy test bypass.

    Coordination disables that bypass: its virtual orchestrator identity must only
    be available outside panes, even when synthetic agent liveness is trusted.
    """
    env = os.environ.get("AGENTMUX_AGENT")
    if env and (not allow_test_identity or os.environ.get("AGENTMUX_TRUST_IDENTITY") != "1"):
        raise IdentityError(
            f"identity: {verb} is the orchestrator's to call, and this is the {env!r} pane.\n"
            f"  An agent closing out the run it is working in defeats the gate: ask the\n"
            f"  orchestrator to run it, or post a request for it.")
    if claimed and claimed != "orchestrator":
        # --by survives on these two verbs only as a compatibility shim. Accepting it
        # silently would put a name in the ledger that nobody could have been.
        raise IdentityError(
            f"identity: {verb} is always attributed to the orchestrator, so --by {claimed!r} "
            f"cannot be honoured.\n  Drop --by.")
    return "orchestrator"


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
                #
                # BUT THE STEAL MUST BE SERIALISED ON THE INODE WE READ. Unconditional
                # unlink is a TOCTOU: A and B both see the same expired claim, A
                # unlinks and links its own (now valid, unexpired) claim, then B - who
                # decided to steal several microseconds ago and never rechecked -
                # unlinks A'S BRAND NEW CLAIM and links its own. Both print "claimed".
                # Two winners, from a path whose whole job is to have one.
                #
                # Taking an exclusive token named for the inode we observed means only
                # one stealer proceeds per generation of the file; anyone working from
                # a stale read loses the token and retries against the new reality.
                token = None
                try:
                    observed = os.stat(path).st_ino
                    token = CLAIMS_DIR / f".steal.{flatten(args.resource)}.{observed}"
                    os.link(staging, token)          # exclusive: one stealer per inode
                except FileExistsError:
                    # Someone else is stealing this same generation. Re-read and retry.
                    if attempt == 1:
                        continue
                    staging.unlink(missing_ok=True)
                    print("coordination: lost the race to take an expired claim",
                          file=sys.stderr)
                    return 1
                except OSError:
                    pass
                try:
                    # Only remove the file if it is still the one we decided about.
                    if token is None or os.stat(path).st_ino == observed:
                        path.unlink()
                except OSError:
                    pass
                finally:
                    if token is not None:
                        try:
                            token.unlink()
                        except OSError:
                            pass
                if attempt == 1:
                    continue
                staging.unlink(missing_ok=True)
                print("coordination: could not take an expired claim", file=sys.stderr)
                return 1
            if existing.get("holder") == args.holder:
                # Re-claiming your own is a renewal, not a conflict.
                #
                # This used to be open(path, "w") - truncate the live claim, THEN
                # write - which is the same empty-file window the staging dance above
                # exists to close, sitting ten lines below it. Renewal is routine, so
                # a rival racing one reads an empty file, concludes "malformed,
                # therefore takeable", unlinks it and takes the claim, while the
                # holder is told it renewed successfully. Two holders of a mutual
                # exclusion primitive, silently.
                #
                # os.replace rather than os.link here: the holder check has already
                # passed, so we are deliberately replacing our own claim, and replace
                # is atomic - the file is never empty and never absent.
                os.replace(staging, path)
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


def release_still_ours(path, holder, observed_ino, force):
    """Is the claim on disk still the one we decided to release?

    Releasing is check-then-unlink, and the gap matters more than it looks. A claim
    three seconds from expiry passes the holder check; it then expires, someone else
    takes it legitimately with a fresh lease, and the original unlink deletes THEIR
    live claim. `agentmux claims` then shows the resource free, a third agent takes it,
    and two agents edit the same file - which is the one thing claims exist to stop.

    So re-read immediately before the unlink and compare both the holder and the inode.
    A different inode means the file has been replaced since we looked, whatever it
    says inside.
    """
    try:
        if os.stat(path).st_ino != observed_ino:
            return False
    except OSError:
        return False
    current = read_claim(path)
    if current is None:
        return False
    if force:
        return True
    return current.get("holder") == holder and not expired(current)


def cmd_release(args):
    path = CLAIMS_DIR / flatten(args.resource)
    existing = read_claim(path)
    if existing is None:
        print(f"no claim on {args.resource}")
        return 0
    try:
        observed_ino = os.stat(path).st_ino
    except OSError:
        print(f"no claim on {args.resource}")
        return 0
    if existing.get("holder") != args.holder and not args.force:
        print(f"REFUSED: {args.resource} is held by {existing['holder']}, not "
              f"{args.holder}. Use --force only if you know they are gone.",
              file=sys.stderr)
        return 1

    # Re-check immediately before the destructive act. See release_still_ours.
    if not release_still_ours(path, args.holder, observed_ino, args.force):
        print(f"REFUSED: {args.resource} changed hands since it was read - not "
              f"releasing someone else's claim.", file=sys.stderr)
        print("  Run `agentmux claims` to see who holds it now.", file=sys.stderr)
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
#
# Work is addressed by its MINTED KEY - TM-014, EP-001 - not by a row number. That
# is the identifier that goes in a commit message, a branch name and a handoff, and
# it is stable across a restore. The integer id every one of these verbs used to
# take is still accepted wherever a key is, because agentmux.sh and two suites
# already pass one; `--json` output and every printed line lead with the key.

TASK_STATUSES = ("backlog", "open", "in_progress", "blocked", "parked", "done", "deleted")
ISSUE_TYPES = ("task", "bug", "story", "spike", "chore")
PRIORITIES = ("highest", "high", "medium", "low", "lowest")
LINK_TYPES = ("relates", "duplicates", "blocks", "causes", "implements")
KEY_RE = re.compile(r"^(EP|TM|ADR|SP|CAP)-[0-9]{3,9}$")


class BoardError(Exception):
    """The board refused, and said why. Carries the remedy when there is one."""

    def __init__(self, message, missing=None):
        super().__init__(message)
        self.missing = missing or []


def api(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{DASHBOARD}/api/{path}", method=method, data=data,
        headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as err:
        # The board's refusals are the useful half of this CLI. Passing back
        # "HTTP Error 409" instead of "TM-014 cannot close: missing evidence"
        # and the command that fixes it would waste the whole gate.
        try:
            payload = json.loads(err.read())
        except (ValueError, OSError):
            raise BoardError(f"the board returned HTTP {err.code}") from None
        raise BoardError(payload.get("error") or f"HTTP {err.code}",
                         payload.get("missing")) from None


def board_call(method, path, body=None):
    """One place where every board verb's failure is turned into a message."""
    try:
        return api(method, path, body)
    except BoardError as err:
        print(f"coordination: {err}", file=sys.stderr)
        for item in err.missing:
            print(f"  fix: {item.get('hint', '')}", file=sys.stderr)
        return None
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as err:
        print(f"coordination: dashboard unreachable at {DASHBOARD} ({err})", file=sys.stderr)
        print("  start it with: python3 dashboard/server.py", file=sys.stderr)
        return None


def need_key(value, kind=None):
    """Accept a key, or the row id the older verbs took."""
    text = str(value)
    if KEY_RE.match(text):
        if kind and not text.startswith(kind + "-"):
            raise BoardError(f"{text} is not a {kind} key")
        return text
    if re.fullmatch(r"[0-9]{1,18}", text):
        return int(text)
    raise BoardError(f"not a board key: {text}")


def address(value, kind):
    """The {id: ...} or {key: ...} half of a legacy-endpoint request body."""
    resolved = need_key(value, kind)
    return {"key": resolved} if isinstance(resolved, str) else {"id": resolved}


def card_line(task):
    """One task, one line, key first."""
    labels = ",".join(task.get("labels") or [])
    flag = "!" if "needs-triage" in (task.get("labels") or []) else " "
    return (f"  {task.get('id', '?'):<9}{flag} {task.get('status', '?'):<12} "
            f"{(task.get('assignee') or task.get('agent') or '-'):<10} "
            f"{str(task.get('title', ''))[:56]:<56} {labels[:28]}")


def cmd_tasks(args):
    board = board_call("GET", "board")
    if board is None:
        return 1
    if args.json:
        print(json.dumps(board, indent=2))
        return 0
    epics = {epic["id"]: epic for epic in board.get("epics", [])}
    by_epic = {}
    for task in board.get("tasks", []):
        if args.mine and (task.get("assignee") or task.get("actor")) != args.mine:
            continue
        if not args.all and task.get("status") in ("done", "deleted"):
            continue
        by_epic.setdefault(task.get("epic"), []).append(task)
    shown = 0
    for epic_key in sorted(by_epic, key=lambda k: (k is None, k or "")):
        epic = epics.get(epic_key)
        title = epic.get("title", "") if epic else "(no epic)"
        status = epic.get("status", "") if epic else ""
        print(f"\n{epic_key or '(unfiled)':<9} {title}  [{status}]")
        for task in by_epic[epic_key]:
            shown += 1
            print(card_line(task))
    if not shown:
        print("no open tasks" + (f" for {args.mine}" if args.mine else ""))
        return 0
    active = board.get("state", {}).get("activeEpic")
    print(f"\n{shown} open  |  active epic: {active or 'none'}"
          f"  |  keys minted: {board.get('counters', {})}")
    return 0


def cmd_task_show(args):
    task = board_call("GET", f"board/entity?id={need_key(args.id)}")
    if task is None:
        return 1
    if args.json:
        print(json.dumps(task, indent=2))
        return 0
    print(f"{task['id']}  {task.get('title', '')}")
    print(f"  status     {task.get('status')}   epic {task.get('epic') or '-'}"
          f"   type {task.get('type')}   priority {task.get('priority') or '-'}")
    print(f"  assignee   {task.get('assignee') or '-'}   actor {task.get('actor') or '-'}")
    if task.get("labels"):
        print(f"  labels     {', '.join(task['labels'])}")
    if task.get("triageMissing"):
        print(f"  missing    {', '.join(task['triageMissing'])}")
    if task.get("blockedBy"):
        print(f"  blocked by {', '.join(task['blockedBy'])}")
    for index, item in enumerate(task.get("acceptance") or [], 1):
        print(f"  [{'x' if item['done'] else ' '}] {index}. {item['text']}")
    for ref in task.get("evidence") or []:
        print(f"  evidence   {ref}")
    for ref in task.get("commits") or []:
        print(f"  commit     {ref}")
    for comment in task.get("comments") or []:
        print(f"  note       {comment.get('author') or '?'}: {comment.get('text', '')[:70]}")
    if task.get("body"):
        print()
        for line in str(task["body"]).splitlines():
            print("  " + line)
    return 0


def cmd_task_new(args):
    fields = {"kind": "task", "title": args.title, "actor": args.agent}
    if args.body:
        fields["body"] = args.body
    if args.ac:
        fields["acceptance"] = args.ac
    if args.epic:
        fields["epic"] = args.epic
    if args.assignee:
        fields["assignee"] = args.assignee
    if args.type:
        fields["type"] = args.type
    if args.priority:
        fields["priority"] = args.priority
    if args.estimate is not None:
        fields["estimate"] = args.estimate
    if args.label:
        fields["labels"] = args.label
    if args.human:
        fields["human"] = True
    row = board_call("POST", "board/create", fields)
    if row is None:
        return 1
    print(f"{row['id']} created in {row.get('epic') or '(no epic)'}: "
          f"{row.get('title', '')[:60]}")
    journal("plan", f"{row['id']} created", row.get("title", ""), args.agent)
    return 0


def cmd_task_add(args):
    """The original verb, kept. It creates as a mirror - a bare title is enough -
    so every existing caller keeps working; `task-new` is the gated path."""
    row = board_call("POST", "tasks", {"epic_id": args.epic, "title": args.title,
                                       "agent": args.agent or None})
    if row is None:
        return 1
    print(f"{row['key']} created in epic {args.epic}: {row.get('title', '')[:60]}")
    journal("plan", f"{row['key']} created", row.get("title", ""), args.agent)
    return 0


def cmd_task_status(args):
    if args.status not in TASK_STATUSES:
        print(f"coordination: status must be one of {', '.join(TASK_STATUSES)}",
              file=sys.stderr)
        return 2
    try:
        target = need_key(args.id, "TM")
    except BoardError as err:
        print(f"coordination: {err}", file=sys.stderr)
        return 2
    if isinstance(target, int):
        # The row-id form predates keys and has no gated endpoint; it stays on
        # the compatibility surface so `agentmux task done 7` keeps working.
        row = board_call("POST", "status", {"kind": "task", "id": target,
                                            "status": args.status})
        if row is None:
            return 1
        key, title = row["key"], row.get("title", "")
    else:
        result = board_call("POST", "board/status",
                            {"id": target, "status": args.status, "actor": args.agent,
                             "reason": args.reason or None})
        if result is None:
            return 1
        key, title = result["id"], result["entity"].get("title", "")
        for name in ("closed", "reopened"):
            if result.get(name):
                print(f"  epic {result[name]} {name}")
    print(f"{key} -> {args.status}  {title[:60]}")
    # A status change is a coordination event, so it goes in the journal too - the
    # board records state, the journal records that a human or agent decided it.
    journal("done" if args.status == "done" else "note",
            f"{key} -> {args.status}", title, args.agent)
    return 0


def cmd_task_edit(args):
    patch = {}
    if args.title:
        patch["title"] = args.title
    if args.body is not None:
        patch["body"] = args.body
    if args.priority:
        patch["priority"] = args.priority
    if args.type:
        patch["type"] = args.type
    if args.estimate is not None:
        patch["estimate"] = args.estimate
    if not patch:
        print("coordination: nothing to change", file=sys.stderr)
        return 2
    row = board_call("POST", "board/update",
                     {"id": need_key(args.id), "patch": patch, "actor": args.agent})
    if row is None:
        return 1
    print(f"{row['id']} edited: {', '.join(sorted(patch))}")
    return 0


def cmd_task_ac(args):
    body = {"id": need_key(args.id), "actor": args.agent}
    if args.text:
        body["text"] = args.text
    elif args.remove is not None:
        body.update({"index": args.remove, "remove": True})
    elif args.untick is not None:
        body.update({"index": args.untick, "done": False})
    elif args.tick is not None:
        body.update({"index": args.tick, "done": True})
    else:
        print("coordination: give a criterion, or --tick/--untick/--remove <n>",
              file=sys.stderr)
        return 2
    row = board_call("POST", "board/acceptance", body)
    if row is None:
        return 1
    for index, item in enumerate(row.get("acceptance") or [], 1):
        print(f"  [{'x' if item['done'] else ' '}] {index}. {item['text']}")
    return 0


def cmd_task_label(args):
    row = board_call("POST", "board/label",
                     {"id": need_key(args.id), "label": args.label,
                      "present": not args.remove, "actor": args.agent})
    if row is None:
        return 1
    print(f"{row['id']} labels: {', '.join(row.get('labels') or []) or '(none)'}")
    return 0


def cmd_task_dep(args):
    row = board_call("POST", "board/dep",
                     {"id": need_key(args.id, "TM"), "blockedBy": args.on,
                      "present": not args.clear, "actor": args.agent})
    if row is None:
        return 1
    print(f"{row['id']} blocked by: "
          f"{', '.join(row.get('blockedBy') or []) or '(nothing)'}")
    return 0


def cmd_task_attach(args):
    # board_verb sets command to the PARSER's name, which is "task-evidence", not
    # "evidence". Keying on the bare word raised KeyError on every call. It went
    # unnoticed because nothing reached these three verbs: agentmux.sh exposed
    # start/done/block/todo/add and nothing else, so attaching evidence meant
    # invoking coordination.py by hand, which nobody did. The first dispatched
    # worker told to run `agentmux task evidence` found it immediately.
    op = args.command.split("task-", 1)[-1]
    if op not in ("evidence", "commit", "touch"):
        print(f"coordination: not an attach verb: {args.command}", file=sys.stderr)
        return 2
    field = {"evidence": "ref", "commit": "ref", "touch": "path"}[op]
    row = board_call("POST", f"board/{op}",
                     {"id": need_key(args.id), field: args.value, "actor": args.agent})
    if row is None:
        return 1
    print(f"{row['id']} {op}: {args.value}")
    return 0


def cmd_task_comment(args):
    row = board_call("POST", "board/comment",
                     {"id": need_key(args.id), "text": args.text, "actor": args.agent})
    if row is None:
        return 1
    print(f"{row['id']}: {len(row.get('comments') or [])} comment(s)")
    return 0


def cmd_task_link(args):
    row = board_call("POST", "board/link",
                     {"id": need_key(args.id), "type": args.type, "target": args.target,
                      "present": not args.remove, "actor": args.agent})
    if row is None:
        return 1
    pairs = [f"{item['type']} {item['id']}" for item in row.get("links") or []]
    print(f"{row['id']} links: " + (", ".join(pairs) or "(none)"))
    return 0


def cmd_task_assign(args):
    row = board_call("POST", "board/update",
                     {"id": need_key(args.id), "patch": {"assignee": args.who},
                      "actor": args.agent})
    if row is None:
        return 1
    print(f"{row['id']} assigned to {args.who}")
    return 0


def cmd_task_move(args):
    result = board_call("POST", "board/move",
                        {"id": need_key(args.id, "TM"), "epic": args.epic,
                         "actor": args.agent})
    if result is None:
        return 1
    print(f"{result['id']}: {result.get('from') or '(none)'} -> "
          f"{result.get('to') or '(none)'}")
    for name in ("closed", "reopened"):
        if result.get(name):
            print(f"  epic {result[name]} {name}")
    return 0


def cmd_task_why(args):
    answer = board_call("GET", f"board/why?id={need_key(args.id, 'TM')}")
    if answer is None:
        return 1
    print(answer["text"])
    for entry in answer.get("chain") or []:
        print(f"  {'  ' * entry['depth']}{entry['id']}  {entry.get('status')}"
              f"  {str(entry.get('title') or '')[:50]}")
    return 0


def cmd_task_next(args):
    result = board_call("GET", f"board/next?limit={args.limit}")
    if result is None:
        return 1
    tasks = result.get("tasks") or []
    if not tasks:
        print("nothing is startable: every open task is blocked or under-specified")
        return 0
    for task in tasks:
        print(card_line(task))
    return 0


def cmd_epic_new(args):
    row = board_call("POST", "board/create",
                     {"kind": "epic", "title": args.title, "body": args.body or "",
                      "actor": args.agent})
    if row is None:
        return 1
    print(f"{row['id']} created: {row.get('title', '')[:60]}")
    if args.active:
        board_call("POST", "board/state", {"name": "activeEpic", "value": row["id"]})
        print(f"  active epic is now {row['id']}")
    journal("plan", f"{row['id']} created", row.get("title", ""), args.agent)
    return 0


def cmd_epic_status(args):
    result = board_call("POST", "board/status",
                        {"id": need_key(args.id, "EP"), "status": args.status,
                         "actor": args.agent})
    if result is None:
        return 1
    print(f"{result['id']} -> {result['to']}")
    return 0


def cmd_active(args):
    result = board_call("POST", "board/state",
                        {"name": "activeEpic", "value": args.epic})
    if result is None:
        return 1
    print(f"active epic: {result.get('activeEpic') or 'none'}")
    return 0


def cmd_new_entity(args):
    kind = {"adr-new": "adr", "sprint-new": "sprint", "cap-new": "capability"}[args.command]
    row = board_call("POST", "board/create",
                     {"kind": kind, "title": args.title, "body": args.body or "",
                      "actor": args.agent})
    if row is None:
        return 1
    print(f"{row['id']} created: {row.get('title', '')[:60]}")
    return 0


def cmd_sprint_commit(args):
    failures = 0
    for key in args.tasks:
        row = board_call("POST", "board/update",
                         {"id": need_key(key, "TM"), "actor": args.agent,
                          "patch": {"sprint": args.sprint}})
        if row is None:
            failures += 1
        else:
            print(f"{row['id']} -> {args.sprint}")
    return 1 if failures else 0


def cmd_triage(args):
    result = board_call("POST", "board/triage",
                        {"all": args.all, "dryRun": args.dry_run, "actor": args.agent})
    if result is None:
        return 1
    for change in result.get("changed") or []:
        gaps = ", ".join(change.get("missing") or []) or "-"
        print(f"  {change['id']:<9} {change['label']:<16} {gaps}")
    print(f"{len(result.get('changed') or [])} task(s) "
          f"{'would change' if result.get('dryRun') else 'changed'}")
    return 0


def print_agent_definition(row):
    print(f"{row['name']} [scope: {row['scope']}] — {row.get('description', '')}")
    for key, value in row.items():
        if key in ("name", "scope", "description", "persona"):
            continue
        if isinstance(value, list):
            value = ", ".join(value) or "(none)"
        print(f"  {key}: {value}")
    if "persona" in row:
        print("  persona:")
        print(row["persona"])


def cmd_agents(args):
    path = "board/agents"
    if args.name is not None:
        path += "?" + urllib.parse.urlencode({"name": args.name})
    result = board_call("GET", path)
    if result is None:
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
    elif args.name is not None:
        print_agent_definition(result)
    else:
        rows = result.get("agents", [])
        print(f"{len(rows)} agent definition(s)")
        for row in rows:
            description = row.get("description", "")
            if len(description) > 80:
                description = description[:79] + "…"
            print(f"  {row['name']} [scope: {row['scope']}] — {description}")
        for problem in result.get("problems", []):
            print(f"  problem: {problem['path']}: {problem['error']}")
    return 0


def cmd_agentdef(args):
    body = {key: value for key, value in vars(args).items()
            if key not in ("command", "func", "json") and value is not None}
    result = board_call("POST", "board/agentdef", body)
    if result is None:
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("Saved agent definition:")
        print_agent_definition(result)
    return 0


def cmd_agentdrop(args):
    body = {"scope": args.scope, "name": args.name}
    if args.checksum is not None:
        body["checksum"] = args.checksum
    result = board_call("POST", "board/agentdrop", body)
    if result is None:
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Dropped agent definition {result['name']} ({result['scope']})")
    return 0


def cmd_team(args):
    if args.command == "roster":
        result = board_call("GET", "board/roster?" +
                            urllib.parse.urlencode({"id": args.id}))
    else:
        body = {"id": args.id}
        if args.command == "hire":
            body["name"] = args.name
        else:
            body["actor"] = args.agent
            if args.command == "approve":
                body["members"] = args.member
        result = board_call("POST", "board/" + args.command, body)
    if result is None:
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{result['id']}: {result['count']} roster member(s)")
        for row in result.get("members", []):
            pane = f" -> {row['member_name']}" if row.get("member_name") else ""
            print(f"  {row['agent_name']} [{row['role']}] {row['status']}{pane}")
    return 0


def cmd_config(args):
    """Read or change one board setting.

    Values are typed the way the board types them, so `dispatchEnabled true` sets a
    boolean and `dispatchWip 4` sets a number. A quoted value is always a string,
    which is how a setting whose value happens to look like a number stays text.
    """
    if args.name is None:
        meta = board_call("GET", "board/meta")
        if meta is None:
            return 1
        config = meta.get("config") or {}
        if args.json:
            print(json.dumps(config, indent=2))
            return 0
        for name in sorted(config):
            print(f"  {name:<22} {json.dumps(config[name])}")
        return 0
    if args.value is None:
        meta = board_call("GET", "board/meta")
        if meta is None:
            return 1
        config = meta.get("config") or {}
        if args.name not in config:
            print(f"coordination: unknown setting {args.name}", file=sys.stderr)
            return 2
        print(json.dumps(config[args.name]))
        return 0
    raw = args.value
    if raw.lower() in ("true", "false"):
        value = raw.lower() == "true"
    elif re.fullmatch(r"-?[0-9]{1,9}", raw):
        value = int(raw)
    elif raw.startswith("[") or raw.startswith("{"):
        try:
            value = json.loads(raw)
        except ValueError:
            print("coordination: value is not valid JSON", file=sys.stderr)
            return 2
    else:
        value = raw
    result = board_call("POST", "board/config", {"name": args.name, "value": value})
    if result is None:
        return 1
    print(json.dumps(result))
    return 0


def cmd_doctor(args):
    report = board_call("GET", "board/doctor")
    if report is None:
        return 1
    print(report["text"])
    print(f"\n{report['errors']} error(s), {report['warnings']} warning(s)")
    return 1 if report["errors"] and args.strict else 0


def cmd_history(args):
    query = f"board/history?limit={args.limit}"
    if args.id:
        query += f"&id={need_key(args.id)}"
    result = board_call("GET", query)
    if result is None:
        return 1
    for event in result.get("events") or []:
        print(f"  {event['ts'][:19]}  {(event.get('id') or '-'):<9} "
              f"{event['event']:<16} {event.get('actor') or '-'}")
    return 0


def cmd_find(args):
    result = board_call("GET", "board/find?q=" + urllib.parse.quote(args.query))
    if result is None:
        return 1
    for hit in result.get("hits") or []:
        print(f"  {hit['id']:<9} {hit['kind']:<11} {hit['status']:<12} "
              f"{str(hit['title'])[:56]}")
    return 0


def cmd_override(args):
    result = board_call("POST", "board/override",
                        {"reason": args.reason, "actor": args.agent})
    if result is None:
        return 1
    print(f"one gate will be bypassed: {result.get('reason')}")
    journal("note", "gate override armed", args.reason, args.agent)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="agent work coordination")
    sub = parser.add_subparsers(dest="command", required=True)

    # ── the board verbs ──────────────────────────────────────────────────────
    #
    # Every one of these takes --agent, and every one is bound by the identity
    # resolver below. That is not decoration: the board records who moved a task,
    # and a field the caller can set to any name it likes is not a record of who
    # did anything. RULE #-0.7.

    def board_verb(name, handler, *, agent=True, **kwargs):
        parser_ = sub.add_parser(name, **kwargs)
        if agent:
            parser_.add_argument("--agent", default=None)
        parser_.set_defaults(func=handler, command=name)
        return parser_

    tasks = board_verb("tasks", cmd_tasks, agent=False)
    tasks.add_argument("--mine", default=None, help="only this agent's tasks")
    tasks.add_argument("--all", action="store_true", help="include done and deleted")
    tasks.add_argument("--json", action="store_true")

    show = board_verb("task-show", cmd_task_show, agent=False)
    show.add_argument("id", help="TM-014, or the row id")
    show.add_argument("--json", action="store_true")

    new = board_verb("task-new", cmd_task_new)
    new.add_argument("title")
    new.add_argument("--epic", default=None, help="EP-001; defaults to the active epic")
    new.add_argument("--body", default=None, help="what and why")
    new.add_argument("--ac", action="append", default=[],
                     help="an acceptance criterion; repeat for more")
    new.add_argument("--assignee", default=None)
    new.add_argument("--type", default=None, choices=ISSUE_TYPES)
    new.add_argument("--priority", default=None, choices=PRIORITIES)
    new.add_argument("--estimate", type=float, default=None)
    new.add_argument("--label", action="append", default=[])
    new.add_argument("--human", action="store_true",
                     help="file it with the human veto already set")

    add = board_verb("task-add", cmd_task_add)
    add.add_argument("epic", type=int)
    add.add_argument("title")

    status = board_verb("task-status", cmd_task_status)
    status.add_argument("id")
    status.add_argument("status")
    status.add_argument("--reason", default=None, help="required reading for blocked/parked")

    edit = board_verb("task-edit", cmd_task_edit)
    edit.add_argument("id")
    edit.add_argument("--title", default=None)
    edit.add_argument("--body", default=None)
    edit.add_argument("--priority", default=None, choices=PRIORITIES)
    edit.add_argument("--type", default=None, choices=ISSUE_TYPES)
    edit.add_argument("--estimate", type=float, default=None)

    criterion = board_verb("task-ac", cmd_task_ac)
    criterion.add_argument("id")
    criterion.add_argument("text", nargs="?", default=None)
    criterion.add_argument("--tick", type=int, default=None)
    criterion.add_argument("--untick", type=int, default=None)
    criterion.add_argument("--remove", type=int, default=None)

    label = board_verb("task-label", cmd_task_label)
    label.add_argument("id")
    label.add_argument("label")
    label.add_argument("--remove", action="store_true")

    dep = board_verb("task-dep", cmd_task_dep)
    dep.add_argument("id")
    dep.add_argument("--on", required=True, help="the task this one waits for")
    dep.add_argument("--clear", action="store_true")

    for name, metavar in (("evidence", "PATH_OR_URL"), ("commit", "SHA_OR_URL"),
                          ("touch", "PATH")):
        attach = board_verb("task-" + name, cmd_task_attach)
        attach.add_argument("id")
        attach.add_argument("value", metavar=metavar)

    comment = board_verb("task-comment", cmd_task_comment)
    comment.add_argument("id")
    comment.add_argument("text")

    link = board_verb("task-link", cmd_task_link)
    link.add_argument("id")
    link.add_argument("type", choices=LINK_TYPES)
    link.add_argument("target")
    link.add_argument("--remove", action="store_true")

    assign = board_verb("task-assign", cmd_task_assign)
    assign.add_argument("id")
    assign.add_argument("who")

    move = board_verb("task-move", cmd_task_move)
    move.add_argument("id")
    move.add_argument("--epic", required=True, help="EP-002, or none")

    why = board_verb("task-why", cmd_task_why, agent=False)
    why.add_argument("id")

    nxt = board_verb("task-next", cmd_task_next, agent=False)
    nxt.add_argument("--limit", type=int, default=10)

    epic_new = board_verb("epic-new", cmd_epic_new)
    epic_new.add_argument("title")
    epic_new.add_argument("--body", default=None)
    epic_new.add_argument("--active", action="store_true",
                          help="make it the epic new tasks file into")

    epic_status = board_verb("epic-status", cmd_epic_status)
    epic_status.add_argument("id")
    epic_status.add_argument("status")

    active = board_verb("board-active", cmd_active, agent=False)
    active.add_argument("epic", help="EP-002, or none")

    for name in ("adr-new", "sprint-new", "cap-new"):
        entity_new = board_verb(name, cmd_new_entity)
        entity_new.add_argument("title")
        entity_new.add_argument("--body", default=None)

    commit_to = board_verb("sprint-commit", cmd_sprint_commit)
    commit_to.add_argument("sprint")
    commit_to.add_argument("tasks", nargs="+")

    sweep = board_verb("triage", cmd_triage)
    sweep.add_argument("--all", action="store_true", help="include resolved tasks")
    sweep.add_argument("--dry-run", action="store_true")

    report = board_verb("doctor", cmd_doctor, agent=False)
    report.add_argument("--strict", action="store_true",
                        help="exit non-zero when the board has errors")

    definitions = board_verb("agents", cmd_agents, agent=False)
    definitions.add_argument("name", nargs="?")
    definitions.add_argument("--json", action="store_true")

    definition = board_verb("agentdef", cmd_agentdef, agent=False,
                            help="create or replace a full agent definition")
    definition.add_argument("scope")
    definition.add_argument("name")
    for field in ("description", "cli", "model", "auth", "posture", "role",
                  "worktree", "persona", "checksum"):
        definition.add_argument("--" + field)
    for field in ("tools", "tools-deny", "capabilities"):
        definition.add_argument("--" + field, nargs="*",
                                help="space-separated values; omit values for an empty list")
    definition.add_argument("--max-instances", type=int)
    definition.add_argument("--json", action="store_true")

    drop = board_verb("agentdrop", cmd_agentdrop, agent=False)
    drop.add_argument("scope")
    drop.add_argument("name")
    drop.add_argument("--checksum")
    drop.add_argument("--json", action="store_true")

    for name in ("roster", "recruit", "approve", "hire"):
        team = board_verb(name, cmd_team, agent=name in ("recruit", "approve"))
        team.add_argument("id", help="board key, e.g. TM-042")
        team.add_argument("--json", action="store_true")
        if name == "approve":
            team.add_argument("--member", action="append", required=True,
                              help="agent definition name; repeat for each member")
        elif name == "hire":
            team.add_argument("--name", required=True)

    setting = board_verb("config", cmd_config, agent=False)
    setting.add_argument("name", nargs="?", default=None)
    setting.add_argument("value", nargs="?", default=None)
    setting.add_argument("--json", action="store_true")

    log = board_verb("history", cmd_history, agent=False)
    log.add_argument("id", nargs="?", default=None)
    log.add_argument("--limit", type=int, default=50)

    search = board_verb("find", cmd_find, agent=False)
    search.add_argument("query")

    bypass = board_verb("override", cmd_override)
    bypass.add_argument("reason")

    claim = sub.add_parser("claim")
    claim.add_argument("resource")
    claim.add_argument("--holder", required=True)
    claim.add_argument("--ttl", type=int, default=DEFAULT_TTL)
    claim.add_argument("--note", default="")
    claim.add_argument("--task", default="")
    claim.add_argument("--depends-on", action="append", default=[])
    # Delegation. NOT a second spelling of --holder: see the binding below for the
    # two conditions that make it safe, and why an agent can never use it.
    claim.add_argument("--for", dest="on_behalf_of", default=None,
                       help="claim for a live agent; orchestrator only")
    claim.set_defaults(func=cmd_claim)

    release = sub.add_parser("release")
    release.add_argument("resource")
    release.add_argument("--holder", required=True)
    release.add_argument("--force", action="store_true")
    release.add_argument("--for", dest="on_behalf_of", default=None,
                        help="release a live agent's claim; orchestrator only")
    release.set_defaults(func=cmd_release)

    listing = sub.add_parser("claims")
    listing.add_argument("--json", action="store_true")
    listing.add_argument("--all", action="store_true", help="include expired")
    listing.set_defaults(func=cmd_claims)

    entry = sub.add_parser("journal", aliases=["entry"])
    entry.add_argument("kind")
    entry.add_argument("subject")
    entry.add_argument("--body", default="")
    entry.add_argument("--agent", default=None)
    entry.set_defaults(func=cmd_journal)

    args = parser.parse_args(argv)
    # Resolve before a claim, journal write, or dashboard request can occur.
    writes = ("task-new", "task-add", "task-status", "task-edit", "task-ac",
              "task-label", "task-dep", "task-evidence", "task-commit", "task-touch",
              "task-comment", "task-link", "task-assign", "task-move", "epic-new",
              "epic-status", "adr-new", "sprint-new", "cap-new", "sprint-commit",
              "triage", "override", "recruit", "approve")
    field = {"claim": "holder", "release": "holder", "journal": "agent",
             "entry": "agent"}.get(args.command,
                                   "agent" if args.command in writes else None)
    if field:
        try:
            claimed = getattr(args, field)
            if not claimed and not os.environ.get("AGENTMUX_AGENT"):
                claimed = orchestrator_identity(args.command)
            setattr(args, field, resolve_identity(claimed, args.command))
            # ── delegation ───────────────────────────────────────────────────
            #
            # `--holder` is refused precisely so one agent cannot act in another's
            # name. Dispatch still has to put a claim in a WORKER's name, because
            # the worker is who must hold it - the orchestrator holding a file on
            # a worker's behalf would make every claim look like the
            # orchestrator's and the whole record useless.
            #
            # That is a different thing from impersonation, and it is safe under
            # exactly two conditions, both enforced here:
            #
            #   1. the caller really is the orchestrator - resolve_identity has
            #      already refused if $AGENTMUX_AGENT is set, so no pane can
            #      reach this line at all; and
            #   2. the delegate is a LIVE agent, so a claim cannot be parked in
            #      the name of something that does not exist.
            #
            # An agent that wants a file still claims it itself. This only lets
            # the thing that STARTED a worker hand it the files it was started for.
            delegate = getattr(args, "on_behalf_of", None)
            if delegate:
                if getattr(args, field) != "orchestrator":
                    raise IdentityError(
                        f"identity: --for is the orchestrator's, and this is the "
                        f"{getattr(args, field)!r} pane."
                        f"  Claim it yourself: drop --for.")
                if not NAME_PATTERN.fullmatch(delegate):
                    raise IdentityError(f"identity: invalid delegate {delegate!r}")
                # Liveness is required to TAKE a claim and must not be required to
                # give one back. A dead worker's claim is the only kind that needs
                # releasing on its behalf, so demanding the holder still be alive
                # made collect unable to do the one thing it exists for: the card
                # parked correctly and its file stayed locked to a process that no
                # longer existed, until the lease expired half an hour later.
                #
                # Releasing in a name is not a power: cmd_release re-reads the claim
                # and refuses unless it is genuinely that holder's.
                if (args.command == "claim" and delegate not in live_agents()
                        and os.environ.get("AGENTMUX_TRUST_IDENTITY") != "1"):
                    raise IdentityError(
                        f"identity: {delegate!r} is not a live agent, so a claim "
                        f"cannot be held in its name.")
                setattr(args, field, delegate)
        except IdentityError as err:
            print(str(err), file=sys.stderr)
            return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
