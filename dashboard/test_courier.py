#!/usr/bin/env python3
"""Verify taskmgmt/courier.py - the piece that turns the write-only message queue
into actual agent-to-agent delivery.

    python3 dashboard/test_courier.py     # no dashboard, no tmux, no agents needed

NOTHING IS SENT TO A REAL AGENT. Two substitutions make that true, and they are the
hooks courier.py documents rather than test-only code paths bolted on:

  - AGENTMUX_HOME points at a throwaway directory, so the real ~/.agentmux/queue -
    which still holds the seeded 2026-09-19 traffic - is never read or advanced;
  - AGENTMUX_BIN points at a stub that records the argv it was handed and exits 0 or
    1 on demand, standing in for `agentmux send`.

`live_agents()` is replaced in the module rather than through an environment
variable, because a production switch that makes the courier believe an agent is up
is exactly the kind of thing that eventually gets left on.

The behaviours worth asserting are the ones that are silent when wrong: a first run
replaying history into live panes, a cursor that redelivers after a truncation, one
dead recipient stalling a sender's traffic to everybody else, and `send --force`
being used to push past a modal.
"""

import importlib.util
import json
import os
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
passed = failed = 0


def check(label, expected, actual):
    global passed, failed
    if expected == actual:
        print(f"  ok    {label:<58} {actual!r}")
        passed += 1
    else:
        print(f"  FAIL  {label:<58} got {actual!r} want {expected!r}")
        failed += 1


# ── isolation ────────────────────────────────────────────────────────────────

HOME = Path(tempfile.mkdtemp(prefix="courier-test-"))
os.environ["AGENTMUX_HOME"] = str(HOME)
QUEUE = HOME / "queue"
STATE = HOME / "courier"
QUEUE.mkdir(parents=True)

STUB_LOG = HOME / "stub.log"
STUB = HOME / "fake-agentmux"
# Written here with explicit "\n" rather than shipped in the repo: every other
# script in this project is invoked as `bash <(tr -d '\r' < ...)` because the
# checkout lives on a Windows drive, and a stub with CRLF endings fails to exec
# with a confusing "bad interpreter" instead of a test failure.
STUB.write_text(
    "#!/usr/bin/env bash\n"
    "printf '%s\\037%s\\037%s\\036' \"$1\" \"$2\" \"$3\" >> \"$STUB_LOG\"\n"
    "for a in \"$@\"; do [ \"$a\" = --force ] && echo FORCED >> \"$STUB_LOG.force\"; done\n"
    "if [ -f \"$STUB_FAIL\" ]; then\n"
    "  echo \"agentmux: '$2' is showing a prompt, not its normal input. Refusing to send:\" >&2\n"
    "  echo '  Enter would actuate that prompt.' >&2\n"
    "  exit 1\n"
    "fi\n"
    "exit 0\n",
    encoding="utf-8", newline="\n")
STUB.chmod(0o755)
os.environ["AGENTMUX_BIN"] = str(STUB)
os.environ["STUB_LOG"] = str(STUB_LOG)
os.environ["STUB_FAIL"] = str(HOME / "make-send-fail")

spec = importlib.util.spec_from_file_location("courier", REPO / "taskmgmt" / "courier.py")
courier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(courier)

RUNNING = {"dev", "rev"}
courier.live_agents = lambda: set(RUNNING)


# ── helpers ──────────────────────────────────────────────────────────────────

def post(sender, recipient, kind="request", body="do the thing", ref=None, raw=None):
    """Append one record to an outbox, the way `agentmux post` does."""
    path = QUEUE / f"{sender}.jsonl"
    line = raw if raw is not None else json.dumps({
        "at": time.strftime("%Y-%m-%dT%H:%M:%S") + time.strftime("%z"),
        "sender": sender, "recipient": recipient, "kind": kind,
        "body": body, "ref": ref})
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return path


def sent():
    """Deliveries the stub saw, as [(verb, recipient, text), ...]."""
    try:
        blob = STUB_LOG.read_text(encoding="utf-8")
    except OSError:
        return []
    return [tuple(record.split("\037"))
            for record in blob.split("\036") if record]


def clear_sent():
    STUB_LOG.unlink(missing_ok=True)
    Path(str(STUB_LOG) + ".force").unlink(missing_ok=True)


def fail_sends(on):
    marker = Path(os.environ["STUB_FAIL"])
    if on:
        marker.write_text("x", encoding="utf-8")
    else:
        marker.unlink(missing_ok=True)


def reset():
    """Back to a clean queue and a clean cursor set."""
    shutil.rmtree(QUEUE, ignore_errors=True)
    shutil.rmtree(STATE, ignore_errors=True)
    QUEUE.mkdir(parents=True)
    clear_sent()
    fail_sends(False)


# ── record parsing ───────────────────────────────────────────────────────────

print("--- parse_record rejects what the store would also reject ---")
good = json.dumps({"at": "2026-09-22T10:00:00+00:00", "sender": "dev",
                   "recipient": "rev", "kind": "request", "body": "hi", "ref": "T-1"})
check("a valid record parses", "rev", courier.parse_record(good.encode())["recipient"])
check("ref survives", "T-1", courier.parse_record(good.encode())["ref"])
check("not JSON", None, courier.parse_record(b"{nope"))
check("JSON but not an object", None, courier.parse_record(b"[1,2]"))
check("unknown kind", None, courier.parse_record(
    json.dumps({"sender": "dev", "recipient": "rev", "kind": "gossip", "body": "x"}).encode()))
check("no recipient is not deliverable", None, courier.parse_record(
    json.dumps({"sender": "dev", "recipient": None, "kind": "status", "body": "x"}).encode()))
check("recipient with a slash", None, courier.parse_record(
    json.dumps({"sender": "dev", "recipient": "../etc", "kind": "status", "body": "x"}).encode()))
check("sender with a space", None, courier.parse_record(
    json.dumps({"sender": "d v", "recipient": "rev", "kind": "status", "body": "x"}).encode()))
check("empty body", None, courier.parse_record(
    json.dumps({"sender": "dev", "recipient": "rev", "kind": "status", "body": "   "}).encode()))
check("body is capped", courier.BODY_MAX, len(courier.parse_record(
    json.dumps({"sender": "dev", "recipient": "rev", "kind": "status",
                "body": "x" * (courier.BODY_MAX + 500)}).encode())["body"]))
check("a missing 'at' is filled in", True, bool(courier.parse_record(
    json.dumps({"sender": "dev", "recipient": "rev", "kind": "status", "body": "x"}).encode())["at"]))

print("--- what the recipient sees is attributed ---")
rendered = courier.render({"sender": "dev", "kind": "finding", "body": "it leaks", "ref": None})
check("render names the sender", True, "from dev" in rendered)
check("render names the kind", True, "(finding)" in rendered)
check("render carries the body", True, rendered.endswith("it leaks"))
check("render is marked as relayed", True, rendered.startswith("[agentmux]"))
check("render includes a ref when set", True, "ref T-9" in courier.render(
    {"sender": "dev", "kind": "reply", "body": "b", "ref": "T-9"}))


# ── the replay guard ─────────────────────────────────────────────────────────

print("--- a first run must NOT replay existing history ---")
reset()
for i in range(3):
    post("dev", "rev", body=f"old message {i}")
summary = courier.tick()
check("nothing delivered from an unseen outbox", 0, summary["delivered"])
check("and nothing queued either", 0, summary["pending"])
check("the stub was never called", 0, len(sent()))
check("a cursor was written", True, (STATE / "dev.cursor").is_file())
check("the cursor is at EOF", (QUEUE / "dev.jsonl").stat().st_size,
      courier.load_cursor("dev")[2])
check("cursor is 0600", 0o600, stat.S_IMODE((STATE / "dev.cursor").stat().st_mode))

print("--- but an outbox created AFTER the baseline is read from the start ---")
reset()
courier.tick()                      # baseline: dev.jsonl does not exist yet
post("newbie", "rev", body="my first message")
summary = courier.tick()
check("a newly spawned agent's opening message is not swallowed", 1, summary["delivered"])
check("it reaches the recipient", True, "my first message" in sent()[0][2])
check("history and new files are told apart by the marker", True,
      (STATE / "adopted").is_file())

print("--- --from-start is the deliberate override ---")
reset()
post("dev", "rev", body="historic")
summary = courier.tick(from_start=True)
check("--from-start does replay", 1, summary["delivered"])
check("delivered to the right agent", "rev", sent()[0][1])
check("delivered with the send verb", "send", sent()[0][0])
check("no --force anywhere", False, Path(str(STUB_LOG) + ".force").exists())


# ── normal delivery and the cursor ───────────────────────────────────────────

print("--- steady state: new messages, delivered once ---")
reset()
courier.tick()                      # establishes the baseline: nothing to adopt
post("dev", "rev", body="first")
summary = courier.tick()
check("a new message is delivered", 1, summary["delivered"])
check("text reaches the pane", True, "first" in sent()[0][2])
clear_sent()
summary = courier.tick()
check("a second pass redelivers nothing", 0, summary["delivered"])
check("the stub stayed idle", 0, len(sent()))
post("dev", "rev", body="second")
post("dev", "rev", body="third")
summary = courier.tick()
check("two more are delivered in one pass", 2, summary["delivered"])
check("in file order", ["second", "third"],
      [record[2].rsplit(": ", 1)[1] for record in sent()])

print("--- a half-written record waits for its newline ---")
reset()
courier.tick()
with (QUEUE / "dev.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({"sender": "dev", "recipient": "rev",
                             "kind": "status", "body": "whole"}) + "\n")
    handle.write('{"sender": "dev", "recipient": "rev", "kind": "sta')
summary = courier.tick()
check("the complete record goes", 1, summary["delivered"])
check("the partial one does not", 1, len(sent()))
with (QUEUE / "dev.jsonl").open("a", encoding="utf-8") as handle:
    handle.write('tus", "body": "rest"}\n')
summary = courier.tick()
check("it is delivered once completed", 1, summary["delivered"])
check("with its body intact", True, "rest" in sent()[1][2])

print("--- truncation and rotation do not replay ---")
reset()
courier.tick()
post("dev", "rev", body="before truncate")
courier.tick()
clear_sent()
(QUEUE / "dev.jsonl").write_text("", encoding="utf-8")
post("dev", "rev", body="after truncate")
summary = courier.tick()
check("truncated outbox delivers only what is new", 1, summary["delivered"])
check("and it is the new message", True, "after truncate" in sent()[0][2])
clear_sent()
(QUEUE / "dev.jsonl").unlink()
post("dev", "rev", body="after rotate")
summary = courier.tick()
check("a replaced outbox restarts at 0", 1, summary["delivered"])
check("delivering the new file's contents", True, "after rotate" in sent()[0][2])


# ── addressing rules ─────────────────────────────────────────────────────────

print("--- addressing: self, courier, and the courier's own outbox ---")
reset()
courier.tick()
post("dev", "dev", body="talking to myself")
summary = courier.tick()
check("a self-addressed message is not delivered", 0, summary["delivered"])
check("it is not retried forever either", 1, summary["pending"])
reset()
courier.tick()
post("dev", "courier", body="hey courier")
summary = courier.tick()
check("nothing is delivered to the courier", 0, summary["delivered"])
reset()
post("courier", "rev", body="courier speaking")
summary = courier.tick()
check("the courier's own outbox is never harvested", 0, summary["delivered"])
check("and gets no cursor", False, (STATE / "courier.cursor").exists())

print("--- a symlinked outbox is refused ---")
reset()
target = HOME / "elsewhere.jsonl"
target.write_text(json.dumps({"sender": "evil", "recipient": "rev",
                              "kind": "status", "body": "via a link"}) + "\n",
                  encoding="utf-8")
try:
    (QUEUE / "evil.jsonl").symlink_to(target)
    summary = courier.tick(from_start=True)
    check("a symlinked outbox delivers nothing", 0, summary["delivered"])
except OSError:
    print("        (symlink not permitted here; check skipped)")


# ── failure handling ─────────────────────────────────────────────────────────

print("--- a recipient that is not running is retried, not lost ---")
reset()
courier.tick()
post("dev", "ghost", body="anyone there")
summary = courier.tick()
check("not delivered", 0, summary["delivered"])
check("held as pending", 1, summary["pending"])
check("never handed to send at all", 0, len(sent()))
check("the reason names the agent", True, "ghost" in courier.load_pending()[0]["reason"])
check("pending is 0600", 0o600, stat.S_IMODE(courier.PENDING.stat().st_mode))
RUNNING.add("ghost")
summary = courier.tick()
check("delivered once the agent appears", 1, summary["delivered"])
check("and pending drains", 0, summary["pending"])
check("the body survived the wait", True, "anyone there" in sent()[0][2])
RUNNING.discard("ghost")

print("--- a pane showing a modal defers; send is never forced ---")
reset()
courier.tick()
fail_sends(True)
post("dev", "rev", body="into a modal")
summary = courier.tick()
check("a refused send is not counted as delivered", 0, summary["delivered"])
check("it is pending", 1, summary["pending"])
check("the refusal reason is kept", True,
      "showing a prompt" in courier.load_pending()[0]["reason"])
check("attempts are counted", 1, courier.load_pending()[0]["attempts"])
courier.tick()
check("attempts increment on retry", 2, courier.load_pending()[0]["attempts"])
check("--force is never used", False, Path(str(STUB_LOG) + ".force").exists())
fail_sends(False)
summary = courier.tick()
check("it lands once the modal clears", 1, summary["delivered"])

print("--- giving up is reported through the queue, not silently ---")
reset()
courier.tick()
fail_sends(True)
post("dev", "rev", body="doomed")
dropped = 0
for _ in range(courier.MAX_ATTEMPTS + 1):
    summary = courier.tick()
    dropped += summary["dropped"]
check("the message is eventually dropped", 1, dropped)
check("after exactly MAX_ATTEMPTS tries", courier.MAX_ATTEMPTS, len(sent()))
check("and stops consuming retries", 0, summary["pending"])
notes = [json.loads(line) for line in
         (QUEUE / "courier.jsonl").read_text(encoding="utf-8").splitlines() if line]
check("a note was posted", 1, len(notes))
check("as an error", "error", notes[0]["kind"])
check("from the courier", "courier", notes[0]["sender"])
check("addressed to nobody, so it cannot loop", None, notes[0]["recipient"])
check("naming both ends", True,
      "dev" in notes[0]["body"] and "rev" in notes[0]["body"])
fail_sends(False)

print("--- one stuck recipient must not stall the others ---")
reset()
courier.tick()
RUNNING.add("stuck")
post("dev", "stuck", body="for the stuck one")
post("dev", "rev", body="for the live one")
# Only the stuck recipient fails: the stub fails everything, so instead drop the
# stuck agent out of the running set - same effect, one recipient undeliverable.
RUNNING.discard("stuck")
summary = courier.tick()
check("the live recipient still gets its message", 1, summary["delivered"])
check("it is the right one", "rev", sent()[0][1])
check("the stuck one is held", 1, summary["pending"])

print("--- per-recipient order survives a deferral ---")
reset()
courier.tick()
post("dev", "later", body="message one")
summary = courier.tick()
check("first is deferred", 1, summary["pending"])
post("dev", "later", body="message two")
summary = courier.tick()
check("the second queues behind it rather than overtaking", 2, summary["pending"])
RUNNING.add("later")
summary = courier.tick()
check("both go when the agent appears", 2, summary["delivered"])
check("in the order they were posted", ["message one", "message two"],
      [record[2].rsplit(": ", 1)[1] for record in sent()])
RUNNING.discard("later")


# ── process control ──────────────────────────────────────────────────────────

print("--- pidfile: a stale one is not a running courier ---")
reset()
courier.STATE_DIR.mkdir(parents=True, exist_ok=True)
courier.write_private(courier.PIDFILE, "999999\n")
check("a dead pid reads as not running", None, courier.running_pid())
courier.write_private(courier.PIDFILE, f"{os.getpid()}\n")
check("a live pid is reported", os.getpid(), courier.running_pid())
courier.write_private(courier.PIDFILE, "not-a-number\n")
check("a corrupt pidfile is not running", None, courier.running_pid())
courier.PIDFILE.unlink(missing_ok=True)
check("no pidfile is not running", None, courier.running_pid())

print("--- --status delivers nothing ---")
reset()
courier.tick()
post("dev", "rev", body="should not go")
summary = courier.tick(dry_run=True)
check("dry run sends nothing", 0, summary["delivered"])
check("dry run calls no stub", 0, len(sent()))
summary = courier.tick()
check("the cursor did not advance, so it still delivers", 1, summary["delivered"])
check("exactly once", 1, len(sent()))

print("--- oversized record does not stall an outbox forever ---")
reset()
courier.tick()
with (QUEUE / "dev.jsonl").open("a", encoding="utf-8") as handle:
    handle.write("x" * (courier.READ_BYTES + 10) + "\n")
post("dev", "rev", body="after the monster")
summary = courier.tick()
check("the monster line is stepped over, not parsed", 0, summary["delivered"])
summary = courier.tick()
check("the record behind it still arrives", 1, summary["delivered"])
check("intact", True, "after the monster" in sent()[0][2])

shutil.rmtree(HOME, ignore_errors=True)
print()
print(f"passed {passed}, failed {failed}")
sys.exit(1 if failed else 0)
