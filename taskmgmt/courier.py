#!/usr/bin/env python3
"""Deliver queued agent-to-agent messages into the agents' panes.

Until this existed the queue was write-only: `dashboard/seed_queue.py` appended to
~/.agentmux/queue/<sender>.jsonl, the dashboard rendered it, and nothing ever handed
a message to its recipient. Every exchange had to be relayed by the orchestrator.

The courier closes that loop. It tails each outbox, and for every record carrying a
`recipient` it runs `agentmux send <recipient> <text>`.

Design decisions that are easy to get wrong, so they are stated here:

* **A new outbox starts at EOF, not at byte 0.** ~/.agentmux/queue already holds the
  seeded 2026-09-19 traffic. Starting from the beginning would type dozens of stale
  hand-offs into live agents the first time the courier ever ran. `--from-start`
  overrides it deliberately.
* **The cursor is (dev, ino, offset).** A rotated or truncated outbox is a different
  file or a shorter one; either way the offset is meaningless and reading from it
  would deliver garbage or replay. Both cases reset to 0 and are logged.
* **Undeliverable messages spill to pending.jsonl rather than blocking the outbox.**
  In-order delivery per outbox sounds right until one dead recipient stalls that
  sender's traffic to everybody else. The spill keeps per-recipient order (a new
  message queues behind anything already pending for the same recipient) without the
  head-of-line block across recipients.
* **A give-up is reported through the queue itself**, as sender `courier` with a null
  recipient. It shows up in the dashboard's Message Queue view like any other
  message, and a null recipient means the courier will never try to deliver its own
  error - which is what stops a failure loop.
* **`send` is never forced.** Its modal guard exists because Enter into a codex
  "Update available" prompt once ran npm install and took an agent down. A pane
  showing a prompt is simply a delivery that has not succeeded yet.

Usage:
    python3 taskmgmt/courier.py --once        # one pass, exit
    python3 taskmgmt/courier.py --watch       # loop until killed
    python3 taskmgmt/courier.py --status      # what it would do, delivers nothing
"""
import argparse
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("AGENTMUX_HOME", str(Path.home() / ".agentmux")))
QUEUE_DIR = ROOT / "queue"
STATE_DIR = ROOT / "courier"
PENDING = STATE_DIR / "pending.jsonl"
LOG = STATE_DIR / "courier.log"
PIDFILE = STATE_DIR / "courier.pid"

# Kept identical to dashboard/ccstore.py on purpose: a message the courier accepts
# but the store rejects (or the reverse) would appear in one view and not the other.
NAME_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,64}")
MESSAGE_KINDS = frozenset(("plan", "request", "reply", "status", "finding", "error"))

READ_BYTES = 262144        # per outbox per tick
BODY_MAX = 65536
MAX_ATTEMPTS = 5           # then give up on that message and say so
PENDING_MAX = 500          # a runaway sender must not grow this file without bound
SOCKET = os.environ.get("AGENTMUX_SOCKET", "agentmux")

# The courier's own reserved name. Nothing is delivered to it, so an agent cannot
# aim traffic at the courier and nothing it writes can be addressed back to it.
COURIER = "courier"


# ─────────────────────────────────────────────────────────────────── plumbing ──

def log(message):
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    line = f"{stamp}  {message}\n"
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(line)
        os.chmod(LOG, 0o600)
    except OSError:
        pass
    sys.stdout.write(line)
    sys.stdout.flush()


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S") + time.strftime("%z")


def agentmux_bin():
    """Resolve the harness the same way a pane would.

    AGENTMUX_BIN wins so a test can point the courier at a stub; then the installed
    launcher on PATH; then the checkout. Returns a list because the checkout form
    needs an interpreter.
    """
    explicit = os.environ.get("AGENTMUX_BIN")
    if explicit:
        return [explicit]
    found = shutil.which("agentmux")
    if found:
        return [found]
    repo = os.environ.get("AGENTMUX_REPO")
    if repo and (Path(repo) / "agentmux.sh").is_file():
        return ["bash", str(Path(repo) / "agentmux.sh")]
    return []


def live_agents():
    """Session names on the agentmux tmux socket. Empty set if no server is up."""
    try:
        done = subprocess.run(["tmux", "-L", SOCKET, "list-sessions", "-F",
                               "#{session_name}"],
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return set()
    if done.returncode != 0:
        return set()
    return {line.strip() for line in done.stdout.splitlines() if line.strip()}


def write_private(path, text):
    """Replace a state file atomically at mode 0600.

    Atomically because a cursor half-written by a kill is worse than a stale one:
    the next tick would parse the fragment, fail, and reset to EOF, silently
    dropping whatever arrived in between.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


# ───────────────────────────────────────────────────────────────────── cursors ──

def cursor_path(agent):
    return STATE_DIR / f"{agent}.cursor"


def load_cursor(agent):
    try:
        value = json.loads(cursor_path(agent).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError
        return (int(value["dev"]), int(value["ino"]), int(value["offset"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_cursor(agent, info, offset):
    write_private(cursor_path(agent), json.dumps(
        {"dev": info.st_dev, "ino": info.st_ino, "offset": offset}))


# ───────────────────────────────────────────────────────────────────── reading ──

def open_outbox(directory, filename):
    """Open an outbox without following links, mirroring ccstore's guards.

    A queue file is written by agents; treating it as trusted input would make it a
    route to read anything on the box through a symlink, or through a hardlink to
    credential material.
    """
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | os.O_NONBLOCK
    before = os.stat(filename, dir_fd=directory, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        return None, None
    fd = os.open(filename, flags, dir_fd=directory)
    handle = os.fdopen(fd, "rb", buffering=0)
    info = os.fstat(handle.fileno())
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino)):
        handle.close()
        return None, None
    return handle, info


def parse_record(raw):
    """One JSON line to a message dict, or None. Never raises on agent input."""
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        return None
    if not isinstance(value, dict):
        return None
    kind = value.get("kind")
    recipient = value.get("recipient")
    sender = value.get("sender")
    if kind not in MESSAGE_KINDS:
        return None
    if not isinstance(recipient, str) or not NAME_PATTERN.fullmatch(recipient):
        return None
    if not isinstance(sender, str) or not NAME_PATTERN.fullmatch(sender):
        return None
    body = value.get("body")
    if not isinstance(body, str) or not body.strip():
        return None
    ref = value.get("ref")
    return {
        "at": value.get("at") if isinstance(value.get("at"), str) else now(),
        "sender": sender,
        "recipient": recipient,
        "kind": kind,
        "body": body[:BODY_MAX],
        "ref": ref if isinstance(ref, str) and ref[:256] else None,
    }


def harvest(agent, adopt_at_eof):
    """New complete records from one outbox, and the offset they end at.

    A trailing partial line is left unconsumed: it is a writer mid-append, and the
    rest of it arrives on the next tick.

    `adopt_at_eof` says what an outbox with no cursor means. On the courier's very
    first pass it means history - the file predates the courier, so its contents were
    handled some other way and replaying them would type stale hand-offs into live
    panes. On any later pass it means a new agent that has just posted for the first
    time, and skipping to EOF there would swallow that agent's opening message.
    """
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | os.O_DIRECTORY
    directory = os.open(QUEUE_DIR, flags)
    try:
        handle, info = open_outbox(directory, f"{agent}.jsonl")
        if handle is None:
            return [], None, None
        with handle:
            saved = load_cursor(agent)
            if saved is None:
                start = info.st_size if adopt_at_eof else 0
                save_cursor(agent, info, start)
                if adopt_at_eof:
                    log(f"cursor  {agent} predates the courier - adopting at EOF "
                        f"(offset {start})")
                    return [], info, start
                if start == 0 and info.st_size:
                    log(f"cursor  {agent} is a new outbox - reading from the start")
            else:
                dev, ino, start = saved
                if (dev, ino) != (info.st_dev, info.st_ino):
                    log(f"cursor  {agent} outbox replaced - restarting at 0")
                    start = 0
                elif start > info.st_size:
                    log(f"cursor  {agent} outbox truncated - restarting at 0")
                    start = 0
            if start >= info.st_size:
                return [], info, start
            handle.seek(start)
            raw = handle.read(min(info.st_size - start, READ_BYTES))
            if os.fstat(handle.fileno()).st_nlink != 1:
                return [], None, None
    finally:
        os.close(directory)

    # A record with no newline inside a whole read is not a writer mid-append - it
    # is a line longer than the courier will ever read, so waiting for its
    # terminator stalls this outbox permanently. Step over it and say so.
    if b"\n" not in raw and len(raw) >= READ_BYTES:
        log(f"skip    {agent} has a record longer than {READ_BYTES} bytes")
        return [], info, start + len(raw)

    consumed, records = 0, []
    for chunk in raw.split(b"\n")[:-1]:
        consumed += len(chunk) + 1
        record = parse_record(chunk)
        if record is not None:
            records.append(record)
    return records, info, start + consumed


# ──────────────────────────────────────────────────────────────────── pending ──

def load_pending():
    try:
        rows = []
        for line in PENDING.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict) and isinstance(value.get("message"), dict):
                rows.append(value)
        return rows
    except OSError:
        return []


def save_pending(rows):
    write_private(PENDING, "".join(json.dumps(row) + "\n" for row in rows[-PENDING_MAX:]))


def report(text):
    """Post a courier-authored note into the queue with NO recipient.

    Null recipient is load-bearing: it is what the dashboard shows and what the
    courier skips, so reporting a failed delivery can never itself be delivered.
    """
    path = QUEUE_DIR / f"{COURIER}.jsonl"
    try:
        QUEUE_DIR.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "at": now(), "sender": COURIER, "recipient": None,
                "kind": "error", "body": text, "ref": None}) + "\n")
        os.chmod(path, 0o600)
    except OSError:
        pass


# ─────────────────────────────────────────────────────────────────── delivery ──

def render(message):
    """What the recipient actually sees typed into its pane.

    Prefixed and attributed because an agent has no other way to tell a relayed
    message from something its operator typed.
    """
    head = f"[agentmux] from {message['sender']} ({message['kind']})"
    if message.get("ref"):
        head += f" ref {message['ref']}"
    return f"{head}: {message['body']}"


def deliver(message, running):
    """Attempt one delivery. Returns (ok, reason)."""
    recipient = message["recipient"]
    if recipient == message["sender"]:
        return False, "addressed to itself"
    if recipient == COURIER:
        return False, "addressed to the courier"
    if recipient not in running:
        return False, f"'{recipient}' is not running"
    binary = agentmux_bin()
    if not binary:
        return False, "cannot locate the agentmux launcher"
    try:
        done = subprocess.run(binary + ["send", recipient, render(message)],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as err:
        return False, f"send failed: {err.__class__.__name__}"
    if done.returncode == 0:
        return True, ""
    # send exits 1 with its modal explanation on stderr; keep the first line, which
    # names the cause, and drop the four lines of operator advice after it.
    detail = (done.stderr or done.stdout or "").strip().splitlines()
    return False, detail[0] if detail else f"send exited {done.returncode}"


def tick(from_start=False, dry_run=False):
    """One pass: retry what is pending, then drain each outbox. Returns a summary."""
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)
    running = live_agents()
    pending = load_pending()
    delivered = failed = dropped = 0

    # "History" is whatever existed before the courier's first ever pass, and this
    # marker is what draws that line. Without it every outbox created later - i.e.
    # every agent spawned after the courier - would also be adopted at EOF and would
    # lose its first message.
    baseline = STATE_DIR / "adopted"
    adopt_at_eof = not baseline.exists() and not from_start

    # Retries first, so a message that has been waiting keeps its place ahead of
    # anything new for the same recipient.
    blocked, keep = set(), []
    for row in pending:
        message = row["message"]
        if dry_run:
            keep.append(row)
            blocked.add(message["recipient"])
            continue
        ok, reason = deliver(message, running)
        if ok:
            delivered += 1
            log(f"sent    {message['sender']} -> {message['recipient']} "
                f"({message['kind']}, retry {row.get('attempts', 0) + 1})")
            continue
        row["attempts"] = int(row.get("attempts", 0)) + 1
        row["reason"] = reason
        if row["attempts"] >= MAX_ATTEMPTS:
            dropped += 1
            log(f"gave up {message['sender']} -> {message['recipient']}: {reason}")
            report(f"undelivered after {MAX_ATTEMPTS} attempts: "
                   f"{message['sender']} -> {message['recipient']} "
                   f"({message['kind']}) - {reason}")
            continue
        failed += 1
        blocked.add(message["recipient"])
        keep.append(row)

    # Then whatever is new. `sorted` only to make a pass deterministic when two
    # outboxes have traffic; ordering within one outbox is the file's own.
    for entry in sorted(os.listdir(QUEUE_DIR)) if QUEUE_DIR.is_dir() else []:
        if not entry.endswith(".jsonl") or not NAME_PATTERN.fullmatch(entry[:-6]):
            continue
        agent = entry[:-6]
        if agent == COURIER:
            continue           # the courier's own notes are never redelivered
        try:
            records, info, offset = harvest(agent, adopt_at_eof)
        except OSError:
            continue
        if info is None:
            continue
        for message in records:
            if dry_run:
                failed += 1
                continue
            if message["recipient"] in blocked:
                # Something for this recipient is already waiting; queueing behind
                # it is what keeps per-recipient order intact.
                keep.append({"attempts": 0, "reason": "queued behind an earlier message",
                             "message": message})
                failed += 1
                continue
            ok, reason = deliver(message, running)
            if ok:
                delivered += 1
                log(f"sent    {message['sender']} -> {message['recipient']} "
                    f"({message['kind']})")
            else:
                failed += 1
                blocked.add(message["recipient"])
                keep.append({"attempts": 1, "reason": reason, "message": message})
                log(f"defer   {message['sender']} -> {message['recipient']}: {reason}")
        if not dry_run:
            save_cursor(agent, info, offset)

    if not dry_run:
        save_pending(keep)
        # Only after a real pass: a --status run must not consume the one chance to
        # adopt history, or the next real pass would deliver all of it.
        if not baseline.exists():
            write_private(baseline, now() + "\n")
    return {"delivered": delivered, "pending": len(keep), "failed": failed,
            "dropped": dropped, "running": sorted(running)}


# ──────────────────────────────────────────────────────────────────────── main ──

def running_pid():
    """PID of a live courier, or None. A stale pidfile is not a running courier."""
    try:
        pid = int(PIDFILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        return pid
    return pid


def watch(interval, from_start):
    existing = running_pid()
    if existing and existing != os.getpid():
        log(f"another courier is already running (pid {existing}) - refusing to start")
        return 1

    # `--stop` sends SIGTERM, whose default action terminates the process outright -
    # so the `finally` below never ran and every stop left a stale pidfile behind.
    # running_pid() sees through a stale one, so this was cosmetic rather than
    # harmful, but a pidfile for a dead process is exactly the kind of debris that
    # makes the next person distrust the whole mechanism.
    def on_term(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, on_term)
    write_private(PIDFILE, f"{os.getpid()}\n")
    log(f"courier watching {QUEUE_DIR} every {interval}s (pid {os.getpid()})")
    first = from_start
    try:
        while True:
            summary = tick(from_start=first)
            first = False
            if summary["delivered"] or summary["dropped"]:
                log(f"tick    delivered {summary['delivered']}  "
                    f"pending {summary['pending']}  dropped {summary['dropped']}")
            time.sleep(interval)
    except KeyboardInterrupt:
        log("courier stopped")
        return 0
    finally:
        try:
            if running_pid() == os.getpid():
                PIDFILE.unlink()
        except OSError:
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(description="deliver queued agent-to-agent messages")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="one pass, then exit")
    mode.add_argument("--watch", action="store_true", help="loop until killed")
    mode.add_argument("--status", action="store_true", help="report state, deliver nothing")
    mode.add_argument("--stop", action="store_true", help="stop a running courier")
    parser.add_argument("--interval", type=float, default=3.0, help="seconds between passes")
    parser.add_argument("--from-start", action="store_true",
                        help="read outboxes from byte 0 - replays existing history")
    args = parser.parse_args(argv)

    if args.stop:
        pid = running_pid()
        if not pid:
            print("no courier running")
            return 0
        try:
            os.kill(pid, 15)
        except OSError as err:
            print(f"could not stop pid {pid}: {err}")
            return 1
        print(f"stopped courier (pid {pid})")
        return 0

    if args.status:
        pid = running_pid()
        summary = tick(dry_run=True)
        print(f"courier:   {'running, pid ' + str(pid) if pid else 'not running'}")
        print(f"queue:     {QUEUE_DIR}")
        print(f"agents:    {', '.join(summary['running']) or 'none running'}")
        print(f"pending:   {summary['pending']} message(s) awaiting delivery")
        for row in load_pending()[:10]:
            message = row["message"]
            print(f"  {message['sender']} -> {message['recipient']} "
                  f"({message['kind']}) attempts {row.get('attempts', 0)}: "
                  f"{row.get('reason', '')}")
        return 0

    if args.watch:
        return watch(max(0.5, args.interval), args.from_start)

    summary = tick(from_start=args.from_start)
    print(f"delivered {summary['delivered']}  pending {summary['pending']}  "
          f"dropped {summary['dropped']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
