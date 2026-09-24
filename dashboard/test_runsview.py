#!/usr/bin/env python3
"""The Runs read surface and the human approval gate.

EVERY TEST RUNS AGAINST A THROWAWAY AGENTMUX_HOME. That is not politeness about tidy
tests: approval writes a real file into a real run directory and appends to a real
append-only ledger, so a suite pointed at ~/.agentmux would leave a decision in the
history of somebody's actual run - and an append-only log is exactly the thing you
cannot quietly clean up afterwards.

The shape of the checks is deliberate. A refusal test only means something when a
matching positive proves the call would otherwise have succeeded; otherwise "it
refused" is indistinguishable from "it was broken". Each gate below is paired.
"""
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "taskmgmt"))


class RunsBase(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="runsview-home-"))
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self._env = os.environ.get("AGENTMUX_HOME")
        os.environ["AGENTMUX_HOME"] = str(self.home)
        self.addCleanup(self._restore_env)
        # Both modules read AGENTMUX_HOME at import, so reload after setting it.
        import run as runmod
        import runsview
        self.run = importlib.reload(runmod)
        self.rv = importlib.reload(runsview)
        self.rv.runmod = self.run

    def _restore_env(self):
        if self._env is None:
            os.environ.pop("AGENTMUX_HOME", None)
        else:
            os.environ["AGENTMUX_HOME"] = self._env

    # ── fixtures written the way run.py writes them ───────────────────────────

    def make_run(self, run_id="a1b2c3", request="do the thing", base=None):
        directory = self.run.run_dir(run_id)
        directory.mkdir(parents=True, exist_ok=True)
        event = {"event": "start", "by": "orchestrator", "detail": request}
        if base:
            event["base"] = base
        self.run.append_event(run_id, event)
        return run_id

    def assign(self, run_id, index, worker="dev-a", reviewer="rev-a", task="TM-1"):
        self.run.append_event(run_id, {
            "event": "assign", "job": f"{run_id}/{index}", "by": "orchestrator",
            "worker": worker, "reviewer": reviewer, "task": task})

    def submit(self, run_id, index, files=("one.txt",)):
        self.run.append_event(run_id, {
            "event": "submit", "job": f"{run_id}/{index}", "by": "dev-a",
            "files": list(files)})

    def verdict(self, run_id, index, result="pass", by="rev-a"):
        self.run.append_event(run_id, {
            "event": "verdict", "job": f"{run_id}/{index}", "by": by,
            "result": result, "detail": "because"})

    def verified_run(self, run_id="a1b2c3", jobs=1, files=("one.txt",)):
        self.make_run(run_id)
        for i in range(1, jobs + 1):
            self.assign(run_id, i)
            self.submit(run_id, i, files)
            self.verdict(run_id, i, "pass")
        return run_id


class TestListing(RunsBase):
    def test_no_runs_is_an_empty_list_not_an_error(self):
        out = self.rv.list_runs(10)
        self.assertEqual(out["runs"], [])
        self.assertEqual(out["maxAttempts"], self.run.MAX_ATTEMPTS)

    def test_max_attempts_comes_from_run_py(self):
        # The view renders "2/3" from this. Hardcoding 3 in JS would leave the ceiling
        # reading 3 forever after someone raised MAX_ATTEMPTS here.
        self.verified_run()
        self.assertEqual(self.rv.list_runs(10)["maxAttempts"], self.run.MAX_ATTEMPTS)

    def test_a_run_is_summarised_from_the_fold(self):
        self.verified_run("aaaaaa", jobs=2)
        row = self.rv.list_runs(10)["runs"][0]
        self.assertEqual(row["run"], "aaaaaa")
        self.assertEqual((row["jobs"], row["verified"]), (2, 2))
        self.assertEqual(row["blocking"], [])
        self.assertFalse(row["complete"])

    def test_limit_is_bounded_not_trusted(self):
        # More runs than the ceiling, or a huge `limit` is clamped by having nothing
        # to return and the assertion passes without the clamp existing at all.
        for n in range(self.rv.LIST_MAX + 5):
            self.verified_run(f"{n:06x}")
        self.assertEqual(len(self.rv.list_runs(2)["runs"]), 2)
        self.assertEqual(len(self.rv.list_runs(10_000)["runs"]), self.rv.LIST_MAX)
        # A zero or negative limit must not mean "no ceiling" or "everything".
        self.assertEqual(len(self.rv.list_runs(0)["runs"]), 20)
        self.assertEqual(len(self.rv.list_runs(-5)["runs"]), 1)

    def test_a_directory_that_is_not_a_run_id_is_skipped(self):
        (self.run.RUNS_DIR / "not-a-run").mkdir(parents=True)
        self.verified_run("cccccc")
        self.assertEqual([r["run"] for r in self.rv.list_runs(10)["runs"]], ["cccccc"])


class TestBlockingProse(RunsBase):
    """The sentence is the product here. A job table answers eventually; this answers
    at a glance, and an operator who has to decode it has gained nothing."""

    def prose(self, run_id):
        return self.rv.summarise(run_id, set())["blockingText"]

    def test_waiting_on_a_reviewer_names_the_reviewer(self):
        rid = self.make_run("d1d1d1")
        self.assign(rid, 1, reviewer="rev-zed")
        self.submit(rid, 1)
        self.assertIn("waiting on rev-zed", self.prose(rid))

    def test_assigned_work_names_the_worker(self):
        rid = self.make_run("d2d2d2")
        self.assign(rid, 1, worker="dev-zed")
        self.assertIn("dev-zed", self.prose(rid))

    def test_a_rejection_shows_the_attempt_against_the_ceiling(self):
        rid = self.make_run("d3d3d3")
        self.assign(rid, 1)
        self.submit(rid, 1)
        self.verdict(rid, 1, "fail")
        self.assertIn(f"attempt 1 of {self.run.MAX_ATTEMPTS}", self.prose(rid))

    def test_escalation_says_it_is_parked_for_you(self):
        rid = self.make_run("d4d4d4")
        self.assign(rid, 1)
        for _ in range(self.run.MAX_ATTEMPTS):
            self.submit(rid, 1)
            self.verdict(rid, 1, "fail")
        self.assertIn("parked for you", self.prose(rid))

    def test_a_verified_run_says_nothing(self):
        self.assertEqual(self.prose(self.verified_run("d5d5d5")), "")


class TestStaleIsUnknownNotEmpty(RunsBase):
    """None and {} are different answers. Rendering an unreachable tmux as "nobody is
    stale" reports every agent alive because a socket blinked - the exact lie the
    stale flag exists to prevent."""

    def test_unreachable_tmux_gives_null_not_an_empty_map(self):
        rid = self.make_run("e1e1e1")
        self.assign(rid, 1)
        self.assertIsNone(self.rv.stale_for(self.run.fold(self.run.load_events(rid)),
                                            None))

    def test_a_known_empty_roster_marks_the_agent_gone(self):
        rid = self.make_run("e2e2e2")
        self.assign(rid, 1, worker="ghost")
        stale = self.rv.stale_for(self.run.fold(self.run.load_events(rid)), set())
        self.assertEqual(stale, {"e2e2e2/1": "ghost"})

    def test_a_live_worker_is_not_stale(self):
        rid = self.make_run("e3e3e3")
        self.assign(rid, 1, worker="alive")
        stale = self.rv.stale_for(self.run.fold(self.run.load_events(rid)), {"alive"})
        self.assertEqual(stale, {})

    def test_a_submitted_job_is_judged_on_its_REVIEWER(self):
        # The worker has finished and may legitimately be gone; the run is waiting on
        # the reviewer, so the reviewer is the one whose absence blocks it.
        rid = self.make_run("e4e4e4")
        self.assign(rid, 1, worker="dev-a", reviewer="rev-a")
        self.submit(rid, 1)
        state = self.run.fold(self.run.load_events(rid))
        self.assertEqual(self.rv.stale_for(state, {"dev-a"}), {"e4e4e4/1": "rev-a"})
        self.assertEqual(self.rv.stale_for(state, {"rev-a"}), {})


class TestDetail(RunsBase):
    def test_sidecar_presence_is_reported_without_serving_bodies(self):
        rid = self.verified_run("f1f1f1")
        job = self.run.job_dir(rid, 1)
        job.mkdir(parents=True, exist_ok=True)
        (job / "brief.md").write_text("the brief", encoding="utf-8")
        (job / "submission.md").write_text("SECRET SUBMISSION TEXT", encoding="utf-8")
        (job / "verdict-1.md").write_text("ok", encoding="utf-8")
        row = self.rv.detail(rid)["jobs"][0]
        self.assertEqual((row["brief"], row["submission"], row["verdicts"]),
                         (True, True, 1))
        # Unbounded agent-authored text must not travel over this endpoint.
        self.assertNotIn("SECRET SUBMISSION TEXT", json.dumps(self.rv.detail(rid)))

    def test_missing_sidecars_read_as_absent_rather_than_raising(self):
        row = self.rv.detail(self.verified_run("f2f2f2"))["jobs"][0]
        self.assertEqual((row["brief"], row["submission"], row["verdicts"]),
                         (False, False, 0))

    def test_an_unknown_run_is_refused_by_name(self):
        with self.assertRaises(self.rv.ReviewError) as caught:
            self.rv.detail("ffffff")
        self.assertIn("no such run", str(caught.exception))

    def test_a_malformed_id_never_reaches_a_path_join(self):
        for bad in ("../../etc", "ZZZZZZ", "", "a" * 40, "a1b2c"):
            with self.assertRaises(self.rv.ReviewError):
                self.rv.detail(bad)


class TestApprovalGate(RunsBase):
    """The human gate in front of completion."""

    def test_a_fully_verified_run_can_be_approved(self):
        # The paired positive. Without it every refusal below proves nothing.
        rid = self.verified_run("a0a0a0")
        record = self.rv.write_approval(rid, "operator", "looks right")
        self.assertEqual(record["decision"], "approved")
        self.assertTrue(self.rv.approval_path(rid).is_file())

    def test_approval_cannot_substitute_for_an_unfinished_review(self):
        rid = self.make_run("a1a1a1")
        self.assign(rid, 1)
        self.submit(rid, 1)                       # submitted, never verdicted
        with self.assertRaises(self.rv.ReviewError) as caught:
            self.rv.write_approval(rid, "operator", "ship it")
        self.assertIn("not verified yet", str(caught.exception))

    def test_a_completed_run_has_nothing_left_to_approve(self):
        rid = self.verified_run("a2a2a2")
        self.run.complete_path(rid).touch()
        with self.assertRaises(self.rv.ReviewError):
            self.rv.write_approval(rid, "operator", "")

    def test_a_run_with_no_jobs_cannot_be_approved(self):
        rid = self.make_run("a3a3a3")
        with self.assertRaises(self.rv.ReviewError) as caught:
            self.rv.write_approval(rid, "operator", "")
        self.assertIn("no jobs", str(caught.exception))

    def test_requesting_changes_is_allowed_while_work_is_unfinished(self):
        # Asymmetric on purpose: approval is a gate that must not open early, but
        # "this is not what I wanted" is useful the moment you can see it.
        rid = self.make_run("a4a4a4")
        self.assign(rid, 1)
        self.submit(rid, 1)
        record = self.rv.write_approval(rid, "operator", "wrong shape", "changes")
        self.assertEqual(record["decision"], "changes")

    def test_an_unknown_decision_is_refused(self):
        rid = self.verified_run("a5a5a5")
        with self.assertRaises(self.rv.ReviewError):
            self.rv.write_approval(rid, "operator", "", "maybe")

    def test_the_decision_reaches_the_ledger_through_run_pys_writer(self):
        rid = self.verified_run("a6a6a6")
        self.rv.write_approval(rid, "operator", "fine")
        events = [e for e in self.run.load_events(rid) if e.get("event") == "review"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["result"], "approved")
        self.assertEqual(events[0]["by"], "operator")

    def test_a_review_event_does_not_disturb_the_fold(self):
        # fold() must ignore it. If a review event created a phantom job the gate
        # would start counting a decision as work.
        rid = self.verified_run("a7a7a7")
        before = self.run.fold(self.run.load_events(rid))
        self.rv.write_approval(rid, "operator", "fine")
        after = self.run.fold(self.run.load_events(rid))
        self.assertEqual(set(before["jobs"]), set(after["jobs"]))

    def test_the_approval_file_is_not_world_readable(self):
        rid = self.verified_run("a8a8a8")
        self.rv.write_approval(rid, "operator", "")
        mode = self.rv.approval_path(rid).stat().st_mode & 0o077
        self.assertEqual(mode, 0, "approval must not be group or world readable")


class TestApprovalPinsBytes(RunsBase):
    """An approval that names files without hashing them approved *something*."""

    def setUp(self):
        super().setUp()
        self.repo = Path(tempfile.mkdtemp(prefix="runsview-repo-"))
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        self.rv.REPO = self.repo

    def test_an_untouched_approval_still_holds(self):
        (self.repo / "one.txt").write_text("original", encoding="utf-8")
        rid = self.verified_run("b1b1b1", files=("one.txt",))
        self.rv.write_approval(rid, "operator", "")
        self.assertEqual(self.rv.approval_drift(rid), ())

    def test_editing_an_approved_file_invalidates_the_approval(self):
        (self.repo / "one.txt").write_text("original", encoding="utf-8")
        rid = self.verified_run("b2b2b2", files=("one.txt",))
        self.rv.write_approval(rid, "operator", "")
        (self.repo / "one.txt").write_text("changed after you looked", encoding="utf-8")
        self.assertEqual(self.rv.approval_drift(rid), ("one.txt",))

    def test_deleting_an_approved_file_invalidates_the_approval(self):
        (self.repo / "one.txt").write_text("original", encoding="utf-8")
        rid = self.verified_run("b3b3b3", files=("one.txt",))
        self.rv.write_approval(rid, "operator", "")
        (self.repo / "one.txt").unlink()
        self.assertEqual(self.rv.approval_drift(rid), ("one.txt",))

    def test_drifted_approval_surfaces_as_stale_not_approved(self):
        (self.repo / "one.txt").write_text("original", encoding="utf-8")
        rid = self.verified_run("b4b4b4", files=("one.txt",))
        self.rv.write_approval(rid, "operator", "")
        (self.repo / "one.txt").write_text("moved", encoding="utf-8")
        state = self.run.fold(self.run.load_events(rid))
        self.assertEqual(self.rv.review_state(rid, state, False)["state"], "stale")

    def test_no_approval_means_no_drift_to_report(self):
        rid = self.verified_run("b5b5b5")
        self.assertIsNone(self.rv.approval_drift(rid))


class TestReviewState(RunsBase):
    def state(self, rid, complete=False):
        return self.rv.review_state(rid, self.run.fold(self.run.load_events(rid)),
                                    complete)["state"]

    def test_a_verified_open_run_is_pending_your_review(self):
        self.assertEqual(self.state(self.verified_run("c1c1c1")), "pending")

    def test_an_unfinished_run_asks_nothing_of_you_yet(self):
        rid = self.make_run("c2c2c2")
        self.assign(rid, 1)
        self.assertIsNone(self.state(rid))

    def test_a_completed_run_asks_nothing(self):
        self.assertIsNone(self.state(self.verified_run("c3c3c3"), complete=True))

    def test_an_empty_run_asks_nothing(self):
        self.assertIsNone(self.state(self.make_run("c4c4c4")))

    def test_changes_requested_is_reported_back(self):
        rid = self.verified_run("c5c5c5")
        self.rv.write_approval(rid, "operator", "no", "changes")
        self.assertEqual(self.state(rid), "changes")


class TestDiff(RunsBase):
    def setUp(self):
        super().setUp()
        self.repo = Path(tempfile.mkdtemp(prefix="runsview-git-"))
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        self.rv.REPO = self.repo
        for cmd in (["init", "-q"], ["config", "user.email", "t@example.invalid"],
                    ["config", "user.name", "t"]):
            subprocess.run(["git", "-C", str(self.repo)] + cmd, check=True,
                           capture_output=True)

    def commit(self, message):
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], check=True,
                       capture_output=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-m", message],
                       check=True, capture_output=True)
        out = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=True)
        return out.stdout.strip()

    def test_committed_work_still_appears_in_the_review(self):
        # THE BUG THIS EXISTS FOR. `git diff HEAD` goes empty the moment a worker
        # commits, so the review surface showed nothing while the work sat in the
        # history. Diffing from the run's recorded base covers both.
        (self.repo / "one.txt").write_text("before\n", encoding="utf-8")
        base = self.commit("base")
        rid = self.make_run("aa11bb", base=base)
        self.assign(rid, 1)
        self.submit(rid, 1, ("one.txt",))
        self.verdict(rid, 1)
        (self.repo / "one.txt").write_text("after\n", encoding="utf-8")
        self.commit("the run's work, committed")
        out = self.rv.review_diff(rid)
        self.assertIn("+after", out["diff"])
        self.assertEqual(out["base"], base)
        self.assertEqual(out["note"], "")

    def test_uncommitted_work_appears_too(self):
        (self.repo / "one.txt").write_text("before\n", encoding="utf-8")
        base = self.commit("base")
        rid = self.make_run("aa22bb", base=base)
        self.assign(rid, 1)
        self.submit(rid, 1, ("one.txt",))
        self.verdict(rid, 1)
        (self.repo / "one.txt").write_text("working tree\n", encoding="utf-8")
        self.assertIn("+working tree", self.rv.review_diff(rid)["diff"])

    def test_a_run_with_no_base_falls_back_to_head_and_says_so(self):
        (self.repo / "one.txt").write_text("before\n", encoding="utf-8")
        self.commit("base")
        rid = self.make_run("aa33bb")                 # no base recorded
        self.assign(rid, 1)
        self.submit(rid, 1, ("one.txt",))
        self.verdict(rid, 1)
        out = self.rv.review_diff(rid)
        self.assertIsNone(out["base"])
        self.assertIn("predates", out["note"])

    def test_a_base_that_no_longer_exists_falls_back_rather_than_erroring(self):
        (self.repo / "one.txt").write_text("before\n", encoding="utf-8")
        self.commit("base")
        rid = self.make_run("aa44bb", base="0" * 40)
        self.assign(rid, 1)
        self.submit(rid, 1, ("one.txt",))
        self.verdict(rid, 1)
        out = self.rv.review_diff(rid)
        self.assertIsNone(out["base"])
        self.assertNotIn("fatal", out["diff"])

    def test_a_file_the_run_CREATED_appears_in_the_review(self):
        # THE SECOND BUG THIS EXISTS FOR. Most runs create files rather than editing
        # them, and `git diff` cannot see a file git has never tracked - so the review
        # showed an empty diff with no hint anything was missing, and approving it
        # would have approved work that was never displayed.
        (self.repo / "old.txt").write_text("a\n", encoding="utf-8")
        base = self.commit("base")
        rid = self.make_run("aa99bb", base=base)
        self.assign(rid, 1)
        self.submit(rid, 1, ("brand_new.py",))
        self.verdict(rid, 1)
        (self.repo / "brand_new.py").write_text("print('hello')\n", encoding="utf-8")
        out = self.rv.review_diff(rid)
        self.assertIn("brand_new.py", out["diff"])
        self.assertIn("print('hello')", out["diff"])

    def test_a_created_file_is_shown_alongside_an_edited_one(self):
        (self.repo / "edited.txt").write_text("before\n", encoding="utf-8")
        base = self.commit("base")
        rid = self.make_run("aaa1bb", base=base)
        self.assign(rid, 1)
        self.submit(rid, 1, ("edited.txt", "created.txt"))
        self.verdict(rid, 1)
        (self.repo / "edited.txt").write_text("after\n", encoding="utf-8")
        (self.repo / "created.txt").write_text("fresh\n", encoding="utf-8")
        diff = self.rv.review_diff(rid)["diff"]
        self.assertIn("+after", diff)
        self.assertIn("+fresh", diff)

    def test_an_untracked_file_that_is_gitignored_is_not_smuggled_in(self):
        (self.repo / ".gitignore").write_text("secret.env\n", encoding="utf-8")
        base = self.commit("base")
        rid = self.make_run("aaa2bb", base=base)
        self.assign(rid, 1)
        self.submit(rid, 1, ("secret.env",))
        self.verdict(rid, 1)
        (self.repo / "secret.env").write_text("TOKEN=abc123\n", encoding="utf-8")
        self.assertNotIn("TOKEN=abc123", self.rv.review_diff(rid)["diff"])

    def test_the_diff_is_scoped_to_what_the_run_submitted(self):
        # A whole-repo diff invites approving a change the run never made.
        (self.repo / "mine.txt").write_text("a\n", encoding="utf-8")
        (self.repo / "unrelated.txt").write_text("a\n", encoding="utf-8")
        base = self.commit("base")
        rid = self.make_run("aa55bb", base=base)
        self.assign(rid, 1)
        self.submit(rid, 1, ("mine.txt",))
        self.verdict(rid, 1)
        (self.repo / "mine.txt").write_text("b\n", encoding="utf-8")
        (self.repo / "unrelated.txt").write_text("b\n", encoding="utf-8")
        out = self.rv.review_diff(rid)
        self.assertIn("mine.txt", out["diff"])
        self.assertNotIn("unrelated.txt", out["diff"])

    def test_a_submitted_path_can_never_become_a_git_flag(self):
        base = self.commit_empty()
        rid = self.make_run("aa66bb", base=base)
        self.assign(rid, 1)
        self.submit(rid, 1, ("--output=/tmp/pwned", "../../etc/passwd", "ok.txt"))
        self.verdict(rid, 1)
        out = self.rv.review_diff(rid)
        self.assertEqual(out["files"], ["ok.txt"])
        self.assertEqual(sorted(out["rejected"]),
                         ["--output=/tmp/pwned", "../../etc/passwd"])
        self.assertFalse(Path("/tmp/pwned").exists())

    def commit_empty(self):
        (self.repo / "ok.txt").write_text("x\n", encoding="utf-8")
        return self.commit("base")

    def test_a_run_naming_no_files_says_so_rather_than_diffing_everything(self):
        rid = self.verified_run("aa77bb", files=())
        out = self.rv.review_diff(rid)
        self.assertEqual(out["files"], [])
        self.assertIn("named any files", out["note"])

    def test_the_diff_is_bounded(self):
        big = "x" * 200 + "\n"
        (self.repo / "big.txt").write_text(big, encoding="utf-8")
        base = self.commit("base")
        rid = self.make_run("aa88bb", base=base)
        self.assign(rid, 1)
        self.submit(rid, 1, ("big.txt",))
        self.verdict(rid, 1)
        (self.repo / "big.txt").write_text(big * 4000, encoding="utf-8")
        out = self.rv.review_diff(rid)
        self.assertLessEqual(len(out["diff"]), self.rv.DIFF_MAX)
        self.assertTrue(out["truncated"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
