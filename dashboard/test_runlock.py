#!/usr/bin/env python3
"""The run lock: who holds it decides when it may be broken.

THE DEFECT THIS EXISTS FOR. run_lock used to break any lock older than ten
seconds, with no idea whether the holder was still there. Ten seconds is not a
long time - a verdict writing a long reason file over /mnt, or a fold on a run
with a few hundred events, reaches it - so a LIVE holder had the lock taken away
and two writers entered the read-decide-write window together. That is exactly
the race the lock exists to prevent, arriving on a schedule rather than by chance.

And it cascaded. The breaker took the lock for itself; when the original holder
finished it removed the BREAKER's lock, letting a third writer in behind it. One
slow verdict unlocked the run for everyone.

Nothing tested any of it. These cases drive the liveness decision directly, with
the two ceilings patched down to fractions of a second, so they are about the
DECISION rather than about waiting.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "taskmgmt"))


class LockBase(unittest.TestCase):
    RUN = "aa11bb"

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="runlock-"))
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self._saved = os.environ.get("AGENTMUX_HOME")
        os.environ["AGENTMUX_HOME"] = str(self.home)
        self.addCleanup(self._restore)

        import importlib
        import run as runmod
        self.run = importlib.reload(runmod)
        self.lock = self.run.run_dir(self.RUN) / ".lock"
        self.lock.parent.mkdir(parents=True, exist_ok=True)

    def _restore(self):
        if self._saved is None:
            os.environ.pop("AGENTMUX_HOME", None)
        else:
            os.environ["AGENTMUX_HOME"] = self._saved

    def ceilings(self, wait, ceiling):
        self.run.LOCK_WAIT_S = wait
        self.run.LOCK_CEILING_S = ceiling

    def held_by(self, pid, token="deadbeef"):
        self.lock.mkdir()
        (self.lock / "owner").write_text(f"{pid} {token}\n")

    def a_dead_pid(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        child.wait(60)
        # The child is reaped, so its pid names nothing. Reuse would need the
        # kernel to wrap all the way round within this test.
        return child.pid

    def acquire_in_background(self):
        """Start a waiter. Returns (thread, got: Event, release: Event)."""
        got, release = threading.Event(), threading.Event()

        def waiter():
            try:
                with self.run.run_lock(self.RUN, "test"):
                    got.set()
                    release.wait(20)
            except OSError:
                pass            # the home was removed under a waiter still spinning

        thread = threading.Thread(target=waiter, daemon=True)
        thread.start()

        def stop():
            # A waiter that never got in would spin until the temp home is deleted
            # and then raise from a daemon thread - a traceback on a passing run.
            # Breaking the lock lets it through so it can finish normally.
            release.set()
            self.run.break_lock(self.lock, None)
            thread.join(5)

        self.addCleanup(stop)
        return thread, got, release


class TestALiveHolderKeepsIt(LockBase):
    def test_a_live_holder_is_not_interrupted_by_the_clock(self):
        # OUR OWN pid, which is unambiguously alive. The wait ceiling is a twentieth
        # of a second: under the old rule the lock would be gone almost at once.
        self.ceilings(wait=0.05, ceiling=3600)
        self.held_by(os.getpid())
        _, got, _ = self.acquire_in_background()
        self.assertFalse(got.wait(1.0), "a live holder's lock was broken")
        self.assertTrue((self.lock / "owner").exists())

    def test_it_is_taken_the_moment_the_holder_releases(self):
        self.ceilings(wait=0.05, ceiling=3600)
        self.held_by(os.getpid())
        _, got, _ = self.acquire_in_background()
        self.assertFalse(got.wait(0.3))
        self.run.break_lock(self.lock, None)
        self.assertTrue(got.wait(5), "the waiter did not notice the release")

    def test_a_wedged_live_holder_is_broken_at_the_ceiling(self):
        # Waiting forever behind a wedged agent is its own failure. The ceiling is
        # what stops it, and it must be the ceiling doing the work - the wait value
        # here is an hour, so only the ceiling can end this.
        self.ceilings(wait=3600, ceiling=0.3)
        self.held_by(os.getpid())
        _, got, _ = self.acquire_in_background()
        self.assertTrue(got.wait(10), "a wedged live holder wedged the run forever")


class TestAGoneHolderLosesIt(LockBase):
    def test_a_dead_holder_is_broken_without_waiting_out_any_clock(self):
        # Both ceilings are an hour, so a break here can only have come from asking
        # whether the pid is still running.
        self.ceilings(wait=3600, ceiling=3600)
        self.held_by(self.a_dead_pid())
        started = time.time()
        _, got, _ = self.acquire_in_background()
        self.assertTrue(got.wait(10), "a lock held by a dead pid wedged the run")
        self.assertLess(time.time() - started, 5)

    def test_a_lock_that_records_no_owner_waits_before_it_is_broken(self):
        # The nameless window is real but microscopic: between mkdir and the write of
        # `owner`. Treating it as abandoned on sight is the mistake that made the
        # dispatch pool's pidfile claim useless - ten concurrent starts, eight winners.
        self.ceilings(wait=0.4, ceiling=3600)
        self.lock.mkdir()
        started = time.time()
        _, got, _ = self.acquire_in_background()
        self.assertTrue(got.wait(10))
        self.assertGreaterEqual(time.time() - started, 0.3,
                                "a nameless lock was broken on sight")

    def test_a_claim_in_progress_is_not_mistaken_for_an_abandoned_one(self):
        self.ceilings(wait=0.4, ceiling=3600)
        self.lock.mkdir()
        _, got, _ = self.acquire_in_background()
        time.sleep(0.15)
        (self.lock / "owner").write_text(f"{os.getpid()} inflight\n")
        self.assertFalse(got.wait(1.5), "the lock was taken from a claim in progress")


class TestReleaseIsConditional(LockBase):
    def test_finishing_does_not_remove_a_lock_somebody_else_now_holds(self):
        # THE CASCADE. Under the old rule the holder's exit removed whatever lock was
        # there, including the one its breaker had just taken - so a single slow
        # operation let a third writer in behind the second.
        self.ceilings(wait=3600, ceiling=3600)
        with self.run.run_lock(self.RUN, "test"):
            self.run.break_lock(self.lock, None)
            self.held_by(4242, token="someone-else")
        self.assertTrue(self.lock.exists(), "the successor's lock was removed")
        self.assertEqual(self.run.lock_holder(self.lock), (4242, "someone-else"))

    def test_finishing_releases_your_own(self):
        self.ceilings(wait=3600, ceiling=3600)
        with self.run.run_lock(self.RUN, "test"):
            self.assertEqual(self.run.lock_holder(self.lock)[0], os.getpid())
        self.assertFalse(self.lock.exists())

    def test_only_one_waiter_gets_in_at_a_time(self):
        self.ceilings(wait=3600, ceiling=3600)
        inside, peak, seen = [], [0], threading.Lock()

        def contend():
            with self.run.run_lock(self.RUN, "test"):
                with seen:
                    inside.append(1)
                    peak[0] = max(peak[0], len(inside))
                time.sleep(0.02)
                with seen:
                    inside.pop()

        threads = [threading.Thread(target=contend) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        self.assertEqual(peak[0], 1, "two holders were inside the lock together")


if __name__ == "__main__":
    unittest.main(verbosity=2)
