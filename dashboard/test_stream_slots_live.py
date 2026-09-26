"""The SSE slot guard over real HTTP, against a real dashboard on an ephemeral port.

TM-017 acceptance criterion 2. test_stream_slots.py covers the MECHANISM in
process - generations, supersession, the claim-before-acquire ordering, the
release in a finally - by calling the functions directly. Everything it asserts
could be true while the live server still wedged, because a handler is more than
its helpers: the claim has to happen on the request path, the refusal has to
still free the old holder, and the slot has to come back when a browser goes
away. This file asserts those over a socket.

THE LIVE PROPERTY, in the operator's words: reloading the dashboard must not
make the dashboard unusable. The measured bug (server.py's own comment, and the
reason the guard exists) was seven panes over a couple of reloads exhausting all
sixteen slots, after which three panes sat at HTTP 503 rendering nothing - which
looks exactly like three dead agents.

Stated as things a running server must do:

  1. Repeated streams for the SAME agent do not accumulate slots. Twenty reloads
     of one pane must leave the pool essentially untouched, so fourteen other
     agents can still stream.
  2. Exhaustion is real and it is what the source declares. Sixteen distinct
     agents fill the pool and the seventeenth is refused - it has nothing to
     supersede, so 503 is the correct answer and it must persist.
  3. A REFUSED reload still frees the way for the retry. This is the ordering,
     and it is the half of the guard whose EFFECT cannot be seen without a
     server: the sibling suite reads the source and asserts the claim is written
     above the acquire, which is a statement about the text. Reloading an
     agent that already holds a slot on a FULL pool is answered 503 - but the
     claim already happened, so the previous holder exits, its slot returns, and
     the retry a moment later succeeds. Acquire-then-claim answers the same 503
     and then stays wedged forever, and nothing in the response distinguishes
     the two.
  4. A slot comes back when the client disconnects.
  5. After more open/abandon cycles than there are slots - twenty-eight across
     seven panes, the measured shape - the dashboard still answers.

WHY A STUB TMUX. The gate has no populated tmux server, and /api/stream/<name>
answers 404 for a name that is not a live session. So this suite puts a stub
`tmux` on the child's PATH that reports the sessions it invented. That is the
only thing stubbed: the slot pool, the generations, the HTTP handling and the
socket lifetime are all the real ones. AGENTMUX_HOME is a throwaway directory
per test, so nothing here can see or touch the operator's agents, and the port
is asked of the OS rather than guessed, so it can run beside a live dashboard
and beside another copy of itself.

WHY A SERVER PER TEST. A slot is released when the handler notices the client is
gone, and the whole point of the bug is that it cannot notice promptly. So an
abandoned stream from one test would still be holding its slot during the next
one. Each test gets its own server rather than a shared one with a cleanup that
cannot be trusted.

NOT IN check_test_failability.sh, for the same reason test_stream_slots.py is
not: `git log -S claim_stream` puts the guard in the INITIAL COMMIT, so there is
no base revision where the bug was present and inventing one would make that
gate assert something untrue.

Proved by mutation instead, 2026-09-25. Each mutation was applied to a COPY of
the whole tree rather than to the shared checkout - server.py's sha256 was
identical before and after the run - and each case restored the pristine text
before the next:

    CONTROL: no mutation                      -> passed 4, failed 0
    take the slot before claiming the agent   -> passed 3, failed 1
    never supersede (stream_superseded=False) -> passed 1, failed 3
    block waiting for a slot (acquire())      -> passed 2, failed 2
    never release the slot (finally: pass)    -> passed 0, failed 4

Which test caught which, because the counts alone do not say:

    claim-after-acquire   only test_a_refused_reload_still_frees_the_way_for_
                          the_retry. That is the point of that test and the
                          reason it exists: every other assertion here is
                          satisfied by a server that wedges the moment the pool
                          is full, because a pool that never fills never
                          exercises the ordering.
    blocking acquire      that one, plus the disconnect test - both exhaust the
                          pool first, and a blocked request answers nothing at
                          all rather than 503.
    never supersede       all three that reload a pane; only the disconnect
                          test, which does not depend on supersession, survives.
    never release         all four.

THE CONTROL IS NOT DECORATION. Every test here needs the spawned server to boot,
so if server.py fails to import - or the tree it was copied into is missing
taskmgmt/, which is how the sibling suite's first mutation harness produced four
catches it had not made - all four fail identically and the run reads like a
perfect score. The last row above IS a uniform 0-passed result; it is readable
as a real catch only because the control passed in the same harness run and
because the three rows above it are partial and different from each other.

Run it alone:  python3 dashboard/test_stream_slots_live.py
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SERVER = ROOT / "server.py"

# A superseded handler notices on its next loop turn, which is a 0.1s sleep away.
SETTLE = 0.12
# How long an open that MUST succeed may spend retrying. The correct server needs
# at most one retry (the slot it is waiting for is being released as it asks); a
# broken one never recovers, so this is the price of each catch, not of a pass.
OPEN_DEADLINE = 4.0
RETRY = 0.2
# A client that has gone is only discovered by writing to it, so a disconnect is
# proved by making the agent produce output until the write fails.
DISCONNECT_DEADLINE = 15.0

# tmux, as much of it as /api/stream/<name> and /api/agents ask for. The sessions
# are whatever the test invented; a pane is 80 columns; nobody is attached.
STUB_TMUX = """#!/bin/sh
while [ $# -gt 0 ]; do
  case "$1" in
    list-sessions) cat "$SLOT_SUITE_SESSIONS"; exit 0 ;;
    list-panes)    echo 80; exit 0 ;;
    list-clients)  exit 0 ;;
    capture-pane)  exit 1 ;;
  esac
  shift
done
exit 0
"""


def declared_cap():
    """The pool size as server.py declares it, or None if the declaration moved.

    Read from the source rather than imported: importing server.py in the test
    process would resolve HOME_DIR against the operator's home and start the
    field services, and this suite is about the server it SPAWNS.
    """
    try:
        source = SERVER.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"STREAM_SLOTS\s*=\s*threading\.BoundedSemaphore\(\s*(\d+)\s*\)",
                      source)
    return int(match.group(1)) if match else None


DECLARED_CAP = declared_cap()
CAP = DECLARED_CAP or 16


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def read_status(sock):
    """The status code from an SSE response, leaving the body unread.

    Unread on purpose: an abandoned EventSource is a socket nobody is draining,
    and that is the case the guard exists for. Returns 0 when nothing arrived
    before the timeout - a handler that BLOCKS for a slot looks like this.
    """
    line = b""
    while not line.endswith(b"\n") and len(line) < 256:
        try:
            byte = sock.recv(1)
        except OSError:
            return 0
        if not byte:
            return 0
        line += byte
    parts = line.split()
    if len(parts) >= 2 and parts[1].isdigit():
        return int(parts[1])
    return 0


class Dashboard:
    """A real dashboard on an ephemeral port, on a home of its own."""

    def __init__(self, agents):
        self.agents = list(agents)
        self.home = Path(tempfile.mkdtemp(prefix="agentmux-slots-live-"))
        self.process = None
        self.port = None
        self.sockets = []
        self.log = self.home / "server.log"

    # -- lifecycle ---------------------------------------------------------
    def start(self):
        (self.home / "run").mkdir()
        logs = self.home / "logs"
        logs.mkdir()
        binaries = self.home / "bin"
        binaries.mkdir()
        sessions = self.home / "sessions"
        sessions.write_text("".join(name + "\n" for name in self.agents),
                            encoding="utf-8")
        stub = binaries / "tmux"
        stub.write_text(STUB_TMUX, encoding="utf-8")
        stub.chmod(0o755)
        for name in self.agents:
            (logs / (name + ".log")).write_bytes(b"agentmux slot suite\n")

        env = dict(os.environ)
        env["AGENTMUX_HOME"] = str(self.home)
        env["SLOT_SUITE_SESSIONS"] = str(sessions)
        env["PATH"] = str(binaries) + os.pathsep + env.get("PATH", "")
        env.pop("AGENTMUX_AGENT", None)

        # An ephemeral port asked of the OS, the way test_e2e.sh does it: bind 0,
        # read the number, hand it to --port (which rejects 0 itself). Retried,
        # because something else can take it in the gap.
        for _ in range(3):
            port = free_port()
            with open(self.log, "wb") as handle:
                self.process = subprocess.Popen(
                    [sys.executable, str(SERVER), "--port", str(port)],
                    cwd=str(ROOT.parent), env=env,
                    stdout=handle, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL)
            if self.wait_until_up(port):
                self.port = port
                return self
            self.kill_process()
        raise RuntimeError("the test dashboard never came up; server log:\n"
                           + self.log_tail())

    def wait_until_up(self, port, seconds=25.0):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.process.poll() is not None:
                return False
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/",
                                            timeout=2) as response:
                    response.read(1)
                return True
            except Exception:
                time.sleep(0.1)
        return False

    def log_tail(self, lines=20):
        try:
            return "\n".join(self.log.read_text(encoding="utf-8",
                                                errors="replace").splitlines()[-lines:])
        except OSError:
            return "(no server log)"

    def kill_process(self):
        if self.process is None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=10)
        self.process = None

    def stop(self):
        for sock in list(self.sockets):
            self.discard(sock)
        self.kill_process()
        shutil.rmtree(self.home, ignore_errors=True)

    # -- requests ----------------------------------------------------------
    def open_stream(self, name, tail=0, timeout=5.0):
        """Open an SSE stream and return (socket, status). The socket is HELD."""
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=timeout)
        sock.settimeout(timeout)
        self.sockets.append(sock)
        sock.sendall((f"GET /api/stream/{name}?tail={tail} HTTP/1.1\r\n"
                      f"Host: 127.0.0.1:{self.port}\r\n"
                      "Accept: text/event-stream\r\n\r\n").encode("ascii"))
        return sock, read_status(sock)

    def discard(self, sock):
        """Hang up, the way a closed tab does."""
        if sock in self.sockets:
            self.sockets.remove(sock)
        try:
            sock.close()
        except OSError:
            pass

    def api(self, path, timeout=10):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}",
                                    timeout=timeout) as response:
            return response.status, json.load(response)


class LiveDashboardTest(unittest.TestCase):
    """One dashboard per test; see WHY A SERVER PER TEST in the module docstring."""

    AGENTS = ()

    def setUp(self):
        self.board = Dashboard(self.AGENTS)
        self.addCleanup(self.board.stop)
        self.board.start()

    def open_ok(self, name, why):
        """Open a stream that must succeed, allowing for a slot in transit.

        A retry is legitimate here and it is not papering over the bug: the
        server answers 503 the instant the pool is full, and under the guard the
        slot the refused request needs is being released as it asks. What the
        guard promises is that the retry gets in. A server without it answers
        the same 503 to every retry until the deadline.
        """
        end = time.monotonic() + OPEN_DEADLINE
        seen = []
        while True:
            sock, code = self.board.open_stream(name)
            seen.append(code)
            if code == 200:
                return sock
            self.board.discard(sock)
            if time.monotonic() >= end:
                self.fail(f"/api/stream/{name} never answered 200 within "
                          f"{OPEN_DEADLINE:g}s - {why}. Codes seen: {seen} "
                          f"(0 = no status line before the timeout, which is what "
                          f"a handler that WAITS for a slot looks like). "
                          f"Server log:\n{self.board.log_tail(8)}")
            time.sleep(RETRY)


class ReloadTests(LiveDashboardTest):
    # One pane that gets reloaded, and enough others to measure what it holds.
    AGENTS = ("reload",) + tuple(f"pane{index:02d}" for index in range(CAP - 2))

    def test_repeated_streams_for_one_agent_do_not_accumulate_slots(self):
        rounds = CAP + 4
        for index in range(rounds):
            # Every socket is kept open and undrained: the server cannot tell
            # these clients have gone, which is precisely the reload.
            self.open_ok("reload", f"reload {index + 1} of {rounds} of a single "
                                   f"pane; if a reload cost a slot the pool would "
                                   f"have run out at {CAP}")
            time.sleep(SETTLE)

        # The accounting, stated as something the operator can see: after twenty
        # reloads of one pane, every other pane must still be able to stream. The
        # reload agent can hold at most two slots for this to pass.
        others = self.AGENTS[1:]
        for name in others:
            self.open_ok(name, f"after {rounds} reloads of one pane, {name} could "
                               f"not get a stream - the reloads are still holding "
                               f"slots")
        self.assertEqual(len(self.board.sockets), rounds + len(others))


class ExhaustionTests(LiveDashboardTest):
    AGENTS = tuple(f"hold{index:02d}" for index in range(CAP)) + ("latecomer",)

    def test_a_refused_reload_still_frees_the_way_for_the_retry(self):
        self.assertIsNotNone(DECLARED_CAP,
                             "STREAM_SLOTS is no longer declared as "
                             "threading.BoundedSemaphore(<n>); this suite is "
                             "measuring against a guessed cap")
        for name in self.AGENTS[:CAP]:
            self.open_ok(name, f"filling the pool: {name} should have had a slot")

        # A brand new agent has nothing to supersede, so 503 is CORRECT here and
        # it must persist. This is also the live measurement of the cap: the
        # pool the server enforces is the one the source declares.
        for attempt in range(3):
            sock, code = self.board.open_stream("latecomer")
            self.board.discard(sock)
            self.assertEqual(code, 503,
                             f"attempt {attempt + 1}: the pool was not full after "
                             f"{CAP} distinct agents took a slot each, so this "
                             f"suite is not testing exhaustion at all")
            time.sleep(RETRY)

        # THE ORDERING, and the only assertion here that needs a server. The
        # reload of an agent that already holds a slot is refused too - the pool
        # is full - but the claim happened BEFORE the acquire, so the previous
        # holder has already been told to stand down. Its slot comes back and the
        # retry gets in. Acquire-then-claim answers the identical 503 and then
        # never recovers.
        self.open_ok("hold00", "a reload of an already-streaming agent on a full "
                               "pool never got in; the refusal did not free its "
                               "own predecessor, so the dashboard is wedged at "
                               "503 for every pane the operator reloads")


class DisconnectTests(LiveDashboardTest):
    AGENTS = tuple(f"hold{index:02d}" for index in range(CAP)) + ("latecomer",)

    def test_a_disconnected_client_gives_its_slot_back(self):
        held = [self.open_ok(name, f"filling the pool: {name}")
                for name in self.AGENTS[:CAP]]
        sock, code = self.board.open_stream("latecomer")
        self.board.discard(sock)
        self.assertEqual(code, 503, "the pool was not full; nothing is being tested")

        # The browser tab closes. The server cannot know until it next writes to
        # that socket, so give the agent something to say until the write fails.
        self.board.discard(held[0])
        log = self.board.home / "logs" / "hold00.log"
        end = time.monotonic() + DISCONNECT_DEADLINE
        seen = []
        while time.monotonic() < end:
            with open(log, "ab") as handle:
                handle.write(b"x" * 1024 + b"\n")
            sock, code = self.board.open_stream("latecomer")
            seen.append(code)
            if code == 200:
                return
            self.board.discard(sock)
            time.sleep(RETRY)
        self.fail(f"a slot never came back after the client hung up, within "
                  f"{DISCONNECT_DEADLINE:g}s of the agent producing output. "
                  f"Codes seen: {seen}. Every disconnect that leaks a slot is "
                  f"one closer to a dashboard that renders nothing.")


class ReloadStormTests(LiveDashboardTest):
    # Seven panes: the shape that produced the measured bug.
    AGENTS = ("build", "plc-dev", "plc-test", "review", "docs", "field",
              "orchestrator")

    def test_the_dashboard_still_answers_after_more_reloads_than_slots(self):
        rounds = 4
        opens = rounds * len(self.AGENTS)
        self.assertGreater(opens, CAP,
                           "this test must open more streams than there are slots "
                           "or it proves nothing")
        for _ in range(rounds):
            for name in self.AGENTS:
                self.open_ok(name, f"{name} could not get a stream during the "
                                   f"reload storm")
            time.sleep(SETTLE)

        # The operator-visible property. Not "the semaphore has the right count"
        # but "the board still works": the agent list answers, and every pane can
        # still open a stream after 28 opens against a pool of 16.
        status, payload = self.board.api("/api/agents")
        self.assertEqual(status, 200)
        self.assertEqual(sorted(agent["name"] for agent in payload["agents"]),
                         sorted(self.AGENTS))
        for name in self.AGENTS:
            self.open_ok(name, f"after {opens} opens against a pool of {CAP}, "
                               f"{name} sat at 503 - which on the board is a pane "
                               f"rendering nothing, indistinguishable from a dead "
                               f"agent")


def main():
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    failed = len(result.failures) + len(result.errors)
    print(f"passed {result.testsRun - failed - len(result.skipped)}, failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
