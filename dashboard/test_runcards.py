#!/usr/bin/env python3
"""`run complete` reporting the board cards a run leaves behind.

THE FAILURE THIS EXISTS FOR. Run bdae05 completed on 2026-09-24 with 2/2 jobs
verified, printed COMPLETE, and said nothing about TM-083 - the card it had been
assigned. That card sat `open` with five unticked acceptance criteria until someone
noticed by eye, and EP-021 stayed open behind it. Two correct gates with no wire
between them.

WHAT IS DELIBERATELY NOT TESTED HERE, because it is deliberately not built: closing the
card. ccboard.gate_done decides whether a card may close, and a second opinion living
in run.py would be a way around it. This reports; it does not decide.
"""
import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "taskmgmt"))


class CardsBase(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="runcards-"))
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self._saved = {k: os.environ.get(k) for k in
                       ("AGENTMUX_HOME", "CC_DB", "AGENTMUX_NOTIFY_TOAST")}
        os.environ["AGENTMUX_HOME"] = str(self.home)
        os.environ["AGENTMUX_NOTIFY_TOAST"] = "0"
        self.addCleanup(self._restore)

        import ccstore
        self.ccstore = importlib.reload(ccstore)
        import ccboard
        self.ccboard = importlib.reload(ccboard)
        import run as runmod
        self.run = importlib.reload(runmod)
        # The board modules are already imported here, so hand them over directly
        # rather than making run.py find them by path a second time.
        self.run._board = (self.ccstore, self.ccboard)

    def _restore(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    # ── fixtures ──────────────────────────────────────────────────────────────

    def make_run(self, run_id="cc11aa", tasks=("TM-1",)):
        self.run.run_dir(run_id).mkdir(parents=True, exist_ok=True)
        self.run.append_event(run_id, {"event": "start", "by": "orchestrator",
                                       "detail": "a request"})
        for index, key in enumerate(tasks, start=1):
            job = f"{run_id}/{index}"
            self.run.append_event(run_id, {
                "event": "assign", "job": job, "by": "orchestrator",
                "worker": "w", "reviewer": "r", "task": key})
            self.run.append_event(run_id, {"event": "submit", "job": job, "by": "w",
                                           "files": ["x.txt"]})
            self.run.append_event(run_id, {"event": "verdict", "job": job, "by": "r",
                                           "result": "pass", "attempt": 1})
        return run_id

    def state(self, run_id):
        return self.run.fold(self.run.load_events(run_id))


class TestCardsOf(CardsBase):
    def test_task_keys_are_collected_in_job_order(self):
        rid = self.make_run(tasks=("TM-9", "TM-3"))
        self.assertEqual(self.run.cards_of(self.state(rid)), ["TM-9", "TM-3"])

    def test_a_key_assigned_twice_is_reported_once(self):
        rid = self.make_run(tasks=("TM-5", "TM-5"))
        self.assertEqual(self.run.cards_of(self.state(rid)), ["TM-5"])

    def test_a_run_whose_jobs_carry_no_task_reports_nothing(self):
        rid = "dd22bb"
        self.run.run_dir(rid).mkdir(parents=True, exist_ok=True)
        self.run.append_event(rid, {"event": "start", "by": "o", "detail": "x"})
        self.run.append_event(rid, {"event": "assign", "job": f"{rid}/1", "by": "o",
                                    "worker": "w", "reviewer": "r"})
        self.assertEqual(self.run.cards_of(self.state(rid)), [])
        self.assertEqual(self.run.report_cards(self.state(rid)), ("", []))


class TestReporting(CardsBase):
    """These run against a REAL board, because the whole point is that the report and
    the board's own refusal cannot disagree."""

    def seed_card(self, key="TM-1", **fields):
        with self.ccstore.connection() as db:
            epic = self.ccboard.create(db, {"kind": "epic", "title": "E2E epic"}) \
                if hasattr(self.ccboard, "create") else None
        return epic

    def test_an_unknown_card_is_named_rather_than_skipped(self):
        # A run assigned to a card that is not on the board is a real state - a typo
        # in a brief, or a card deleted mid-run. Silence would be the worst answer.
        rid = self.make_run(tasks=("TM-404",))
        summary, lines = self.run.report_cards(self.state(rid))
        text = "\n".join(lines)
        self.assertIn("TM-404", text)
        self.assertIn("TM-404", summary)

    def test_the_summary_is_empty_when_there_is_nothing_to_chase(self):
        # Used as a fragment appended to the completion notice, so "" must mean
        # "say nothing" rather than "unknown".
        rid = "ee33cc"
        self.run.run_dir(rid).mkdir(parents=True, exist_ok=True)
        self.run.append_event(rid, {"event": "start", "by": "o", "detail": "x"})
        summary, lines = self.run.report_cards(self.state(rid))
        self.assertEqual((summary, lines), ("", []))

    def test_an_unavailable_board_says_so_instead_of_claiming_all_is_well(self):
        # Degrading to "nothing to report" would recreate the exact silence this
        # exists to remove, and would do it precisely when something is wrong.
        rid = self.make_run(tasks=("TM-7",))
        self.run._board = False
        try:
            summary, lines = self.run.report_cards(self.state(rid))
        finally:
            self.run._board = (self.ccstore, self.ccboard)
        self.assertEqual(summary, "")
        self.assertIn("board unavailable", "\n".join(lines))
        self.assertIn("TM-7", "\n".join(lines))

    def test_a_board_that_raises_is_caught_rather_than_failing_the_run(self):
        # A completion that has already passed its verification gate must not be
        # turned into a failure by a reporting problem.
        rid = self.make_run(tasks=("TM-8",))

        class Broken:
            def connection(self):
                raise RuntimeError("db is gone")

        self.run._board = (Broken(), self.ccboard)
        try:
            summary, lines = self.run.report_cards(self.state(rid))
        finally:
            self.run._board = (self.ccstore, self.ccboard)
        self.assertEqual(summary, "")
        self.assertIn("board unavailable", "\n".join(lines))

    def test_card_status_returns_none_when_the_board_cannot_be_reached(self):
        self.run._board = False
        try:
            self.assertIsNone(self.run.card_status(["TM-1"]))
        finally:
            self.run._board = (self.ccstore, self.ccboard)

    def test_no_keys_means_no_query(self):
        self.assertIsNone(self.run.card_status([]))


class TestCompletionMentionsTheBoard(CardsBase):
    def test_the_notice_carries_the_open_cards(self):
        # The notice is what reaches the inbox, the feed and the toast. A report that
        # only ever appeared on a terminal nobody was watching would not have caught
        # the original failure either.
        rid = self.make_run(tasks=("TM-404",))
        summary, _ = self.run.report_cards(self.state(rid))
        self.assertTrue(summary.startswith("cards still open:"))
        self.assertIn("TM-404", summary)


if __name__ == "__main__":
    unittest.main(verbosity=2)
