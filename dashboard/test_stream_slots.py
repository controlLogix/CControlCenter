"""The SSE slot guard: a page reload must not cost a slot.

THE MEASURED BUG, quoted from server.py's own comment because it is the whole
specification: "Seven panes over a couple of reloads exhausted all sixteen
slots, and three panes then sat at HTTP 503 showing nothing at all."

Why a reload is the dangerous case: the server cannot tell a client has gone
until it next tries to write, and with a quiet agent that is up to a heartbeat
away. So a reload opens a fresh EventSource per pane while every previous one is
still established and still holding a slot. Slots held grows with how many times
the page has been loaded, which is unbounded.

THE FIX IS A GENERATION PER AGENT, and the ordering is what makes it work:
claim_stream() runs BEFORE STREAM_SLOTS.acquire(). The previous holder learns it
has been superseded and starts exiting - releasing its slot - even when this
request is itself refused. Acquire-then-claim would wedge at sixteen with
everybody waiting for somebody else to notice.

THERE ARE TWO SUITES WITH THIS NAME AND THEY COVER DIFFERENT HALVES.

  test_stream_slots.py   (this file, IN THE GATE)
      The mechanism: generations, supersession, the claim-before-acquire
      ordering, slot release. No server, no agents, no port - so it runs
      anywhere, on every commit.

  test_stream_slots.sh   (an OPERATOR COMMAND, deliberately not in the gate)
      The same property end to end against the live dashboard on 8787 with the
      operator's real agents: 28 opens across 7 agents, then check every stream
      is still available.

      It CANNOT run in the gate, and that is not an oversight. It needs
      /api/agents to return real agents, and the gate's dashboard runs on a
      throwaway AGENTMUX_HOME with none - so it would exit 1 with "no agents to
      test" for a reason that has nothing to do with the guard. It also talks to
      port 8787 directly, which the gate has leased for itself.

      So the mechanism is gated here; the end-to-end proof stays something you
      run against a dashboard that has something on it.

TM-017 parked this for Phase 3's Playwright work, and that is right for the
BROWSER half: the six-connection cap is a browser fact and needs a browser. The
SERVER half is a semaphore and a dict, and it is where the bug actually was.

NOT IN check_test_failability.sh, and that is not an oversight. That gate proves
a suite can fail by running it against a commit where the bug was present, and
`git log -S claim_stream` says the guard has been here since the INITIAL COMMIT.
There is no such base, and inventing one would make the gate say something
untrue.

Proved by mutation instead, 2026-09-25. Four realistic regressions, each caught,
and a CONTROL that must pass:

    CONTROL: no mutation                      -> passed 11, failed 0
    take the slot before claiming the agent   -> passed 10, failed 1
    use a plain Semaphore                     -> passed  9, failed 2
    block waiting for a slot                  -> passed 10, failed 1
    never supersede                           -> passed  7, failed 4

The control is not decoration. Without it the first run of that harness reported
four catches it had not made: the copied tree was missing taskmgmt/, server.py
failed to import, and every mutation "failed" for that reason. Specific partial
failures are what a real catch looks like; a uniform 0/11 is what a broken
fixture looks like, and the two are indistinguishable without a control.
"""

import ast
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import server
except ImportError as exc:
    server = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


class _NeedsServer(unittest.TestCase):
    def setUp(self):
        if server is None:
            self.fail(f"dashboard/server.py did not import: {IMPORT_ERROR}")
        # The generation table is module state; keep each test independent.
        with server._stream_gen_lock:
            self._saved = dict(server._stream_gen)
            server._stream_gen.clear()
        self.addCleanup(self._restore)

    def _restore(self):
        with server._stream_gen_lock:
            server._stream_gen.clear()
            server._stream_gen.update(self._saved)


class GenerationTests(_NeedsServer):
    def test_claiming_supersedes_the_previous_holder(self):
        first = server.claim_stream("plc-dev")
        self.assertFalse(server.stream_superseded("plc-dev", first))
        second = server.claim_stream("plc-dev")
        # The reload. The older thread now knows to exit and give its slot back.
        self.assertTrue(server.stream_superseded("plc-dev", first))
        self.assertFalse(server.stream_superseded("plc-dev", second))
        self.assertNotEqual(first, second)

    def test_agents_do_not_supersede_each_other(self):
        # The negative that makes the mechanism per-agent rather than global. If
        # one agent's stream cancelled another's, opening the page would kill
        # every pane but the last.
        a = server.claim_stream("plc-dev")
        b = server.claim_stream("plc-test")
        self.assertFalse(server.stream_superseded("plc-dev", a))
        self.assertFalse(server.stream_superseded("plc-test", b))

    def test_an_unknown_agent_reads_as_superseded(self):
        # A thread whose agent has gone entirely must exit, not linger holding a
        # slot for something that no longer exists.
        self.assertTrue(server.stream_superseded("never-claimed", 1))

    def test_many_reloads_leave_exactly_one_live_generation(self):
        # The measured bug, as arithmetic: twenty reloads of one pane.
        generations = [server.claim_stream("plc-dev") for _ in range(20)]
        live = [g for g in generations if not server.stream_superseded("plc-dev", g)]
        self.assertEqual(len(live), 1, "more than one stream thread thinks it is current")
        self.assertEqual(live[0], generations[-1])

    def test_concurrent_claims_still_leave_one_winner(self):
        # Seven panes reloading at once is the shape that produced the bug.
        winners = []
        barrier = threading.Barrier(12)

        def claim():
            barrier.wait()
            winners.append(server.claim_stream("plc-dev"))

        threads = [threading.Thread(target=claim) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(set(winners)), 12, "two threads were handed the same generation")
        live = [g for g in winners if not server.stream_superseded("plc-dev", g)]
        self.assertEqual(len(live), 1)


class OrderingTests(_NeedsServer):
    """The ordering IS the fix, so it is asserted rather than assumed."""

    def source(self):
        return (Path(__file__).resolve().parent / "server.py").read_text(encoding="utf-8")

    def test_every_stream_claims_before_it_takes_a_slot(self):
        # Acquire-then-claim would wedge at sixteen: nobody would learn they had
        # been superseded, so no slot would come back, so every reload would be
        # refused for as long as the old threads lived.
        tree = ast.parse(self.source())
        checked = 0
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = ast.get_source_segment(self.source(), node) or ""
            if "claim_stream(" not in body or "STREAM_SLOTS.acquire" not in body:
                continue
            checked += 1
            self.assertLess(body.index("claim_stream("), body.index("STREAM_SLOTS.acquire"),
                            f"{node.name} takes a slot before claiming the agent; the "
                            f"previous holder never learns to exit")
        self.assertGreater(checked, 0, "no stream handler claims and acquires; the guard moved")

    def test_every_acquired_slot_is_released_in_a_finally(self):
        # An exception on a dead client must not leak a slot. Sixteen leaks and
        # the dashboard is dark with nothing in any log to say why.
        source = self.source()
        acquires = source.count("STREAM_SLOTS.acquire")
        releases = source.count("STREAM_SLOTS.release")
        self.assertGreaterEqual(releases, acquires,
                                "a code path takes a stream slot and never gives it back")
        tree = ast.parse(source)
        released_in_finally = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Try) and node.finalbody:
                block = "\n".join(ast.get_source_segment(source, s) or ""
                                  for s in node.finalbody)
                if "STREAM_SLOTS.release" in block:
                    released_in_finally += 1
        self.assertGreaterEqual(released_in_finally, 1,
                                "no slot is released from a finally; an error leaks one")


class SemaphoreTests(_NeedsServer):
    def test_the_pool_is_bounded_so_a_double_release_is_caught(self):
        # BoundedSemaphore rather than Semaphore, deliberately: releasing one
        # you do not hold raises here instead of silently inflating the pool
        # until the cap means nothing.
        self.assertIsInstance(server.STREAM_SLOTS, threading.BoundedSemaphore().__class__)
        pool = threading.BoundedSemaphore(2)
        pool.acquire()
        pool.release()
        with self.assertRaises(ValueError):
            pool.release()

    def test_the_pool_refuses_rather_than_blocking_when_full(self):
        # acquire(blocking=False). A stream request that WAITED for a slot would
        # hold a handler thread, and the thread pool is what is being protected.
        source = (Path(__file__).resolve().parent / "server.py").read_text(encoding="utf-8")
        self.assertIn("STREAM_SLOTS.acquire(blocking=False)", source)
        self.assertNotIn("STREAM_SLOTS.acquire()", source)

    def test_exhaustion_answers_503_rather_than_hanging(self):
        source = (Path(__file__).resolve().parent / "server.py").read_text(encoding="utf-8")
        self.assertIn('503, {"error": "too many streams"}', source)

    def test_the_cap_is_small_enough_to_matter_and_large_enough_to_work(self):
        # A number worth pinning: below the browser's six-per-origin cap times a
        # couple of panes and the dashboard cannot show a normal board; far
        # above it and the pool stops protecting the thread count.
        self.assertGreaterEqual(server.STREAM_SLOTS._initial_value, 8)
        self.assertLessEqual(server.STREAM_SLOTS._initial_value, 64)


def main():
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    failed = len(result.failures) + len(result.errors)
    print(f"passed {result.testsRun - failed - len(result.skipped)}, failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
