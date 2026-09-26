"""The kill switch: armed unless recently and deliberately disarmed.

THE TESTS THAT MATTER HERE ARE THE NEGATIVE ONES. A kill switch that permits
when it should refuse fails silently and expensively; one that refuses when it
should permit is merely annoying, and the operator finds out immediately. So the
weight is on: what still refuses.

Two are named in the plan's own verification block and are the reason this file
exists rather than a few asserts elsewhere:

  test_broker_side_check_is_authoritative   the API says allow; the broker must
                                            still refuse
  -k rearm_on_                              every trigger that brings it back

No network, no browser, no clock dependence beyond an injected `now`.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import killswitch
except ImportError as exc:
    killswitch = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


GUARDRAILS = {"max_notional": 25000, "max_orders_per_day": 3}


class _NeedsSwitch(unittest.TestCase):
    def setUp(self):
        if killswitch is None:
            self.fail(f"agentmux-broker/killswitch.py is missing: {IMPORT_ERROR}")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "broker"
        self.root.mkdir(parents=True)

    def disarm(self, **kw):
        kw.setdefault("phrase", killswitch.DISARM_PHRASE)
        kw.setdefault("actor", "operator")
        kw.setdefault("config", GUARDRAILS)
        kw.setdefault("root", self.root)
        return killswitch.disarm(**kw)

    def armed(self, **kw):
        kw.setdefault("root", self.root)
        kw.setdefault("config", GUARDRAILS)
        return killswitch.state(**kw)


class DefaultTests(_NeedsSwitch):
    def test_it_is_armed_with_nothing_on_disk_at_all(self):
        # The default is not "permitted until someone switches it on".
        current = self.armed()
        self.assertTrue(current["armed"])
        self.assertIn("armed by default", current["reason"])
        self.assertFalse(killswitch.allowed(self.root, config=GUARDRAILS))

    def test_a_missing_directory_is_armed_not_an_error(self):
        missing = Path(self.temp.name) / "no-such-broker-dir"
        self.assertTrue(killswitch.state(missing)["armed"])

    def test_the_installer_sentinel_blocks_everything(self):
        (self.root / killswitch.SENTINEL_NAME).write_text("", encoding="utf-8")
        current = self.armed()
        self.assertTrue(current["armed"])
        self.assertIn(killswitch.SENTINEL_NAME, current["reason"])

    def test_a_disarm_cannot_quietly_remove_the_sentinel(self):
        # Removing it is a deliberate, separate act. A disarm that did it for
        # you would turn the hard stop into a soft one.
        (self.root / killswitch.SENTINEL_NAME).write_text("", encoding="utf-8")
        with self.assertRaises(killswitch.Armed):
            self.disarm()
        self.assertTrue((self.root / killswitch.SENTINEL_NAME).exists())
        self.assertTrue(self.armed()["armed"])


class DisarmTests(_NeedsSwitch):
    def test_a_correct_phrase_disarms_for_a_bounded_time(self):
        self.disarm(ttl=600)
        current = self.armed()
        self.assertFalse(current["armed"])
        self.assertEqual(current["disarmed_by"], "operator")
        self.assertGreater(current["expires_in"], 0)
        self.assertLessEqual(current["expires_in"], 600)

    def test_the_phrase_must_be_exact(self):
        for wrong in ("disarm trading", "DISARM", "yes", "", None, 7,
                      killswitch.DISARM_PHRASE + " "):
            with self.subTest(phrase=wrong), self.assertRaises(killswitch.Armed):
                self.disarm(phrase=wrong)
        # ...and none of those left anything behind.
        self.assertTrue(self.armed()["armed"])

    def test_disarming_requires_a_named_actor(self):
        for actor in (None, "", "   ", 7):
            with self.subTest(actor=actor), self.assertRaises(ValueError):
                self.disarm(actor=actor)

    def test_a_ttl_beyond_the_ceiling_is_refused(self):
        for ttl in (0, -1, killswitch.MAX_TTL_S + 1, "an hour", None):
            with self.subTest(ttl=ttl), self.assertRaises(ValueError):
                self.disarm(ttl=ttl)

    def test_the_record_is_owner_only(self):
        self.disarm()
        path = self.root / killswitch.DISARM_NAME
        self.assertTrue(path.is_file())
        if hasattr(os, "getuid"):
            import stat
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


class AuthorityTests(_NeedsSwitch):
    def test_broker_side_check_is_authoritative(self):
        """The API says allow. The broker must still refuse.

        Named in the plan's verification block. The API runs in WSL and this on
        Windows, so anything it told us is a claim about the past - and the
        click happens now. The design point is that there is no argument
        `allowed()` could be given that would override the disk, so the test is
        partly a check on the SIGNATURE.
        """
        import inspect
        params = set(inspect.signature(killswitch.allowed).parameters)
        for override in ("api_says_ok", "force", "override", "approved", "allow"):
            self.assertNotIn(override, params,
                             f"allowed() takes {override!r}; the broker must not be "
                             f"overridable by something it is told")
        # And with nothing on disk it refuses, whatever anyone else believes.
        self.assertFalse(killswitch.allowed(self.root, config=GUARDRAILS))
        with self.assertRaises(killswitch.Armed):
            killswitch.require_disarmed(self.root, config=GUARDRAILS)

    def test_the_state_is_re_read_every_time_never_cached(self):
        self.disarm(ttl=600)
        self.assertFalse(self.armed()["armed"])
        # Someone removes the record out from under us - a second operator, a
        # cleanup, a crash. The very next call must see it.
        (self.root / killswitch.DISARM_NAME).unlink()
        self.assertTrue(self.armed()["armed"])

    def test_a_corrupt_record_is_armed_not_trusted(self):
        self.disarm()
        (self.root / killswitch.DISARM_NAME).write_text("not json", encoding="utf-8")
        current = self.armed()
        self.assertTrue(current["armed"])

    def test_a_record_with_no_expiry_is_armed(self):
        # The shape of a hand-written file somebody hoped would work.
        (self.root / killswitch.DISARM_NAME).write_text(
            json.dumps({"actor": "someone", "pid": os.getpid()}), encoding="utf-8")
        self.assertTrue(self.armed()["armed"])

    def test_a_backdated_grant_cannot_buy_a_longer_life(self):
        # A clock that moved, or a file someone edited: expires_at far beyond
        # granted_at must not extend the disarm indefinitely.
        (self.root / killswitch.DISARM_NAME).write_text(json.dumps({
            "actor": "someone", "pid": os.getpid(),
            "granted_at": 1000.0, "expires_at": 1000.0 + 86400,
            "guardrails": killswitch.guardrails_digest(GUARDRAILS),
        }), encoding="utf-8")
        current = self.armed(now=2000.0)
        self.assertTrue(current["armed"])
        self.assertIn("longer life", current["reason"])


class RearmTests(_NeedsSwitch):
    def test_rearm_on_expiry(self):
        record = self.disarm(ttl=60, now=1000.0)
        self.assertFalse(self.armed(now=1030.0)["armed"])
        current = self.armed(now=1061.0)
        self.assertTrue(current["armed"])
        self.assertIn("expired", current["reason"])
        self.assertEqual(record["expires_at"], 1060.0)

    def test_rearm_on_process_restart(self):
        # A disarm belongs to the process that made it. A restart has no memory
        # of why it was granted, so it starts armed.
        self.disarm(ttl=600)
        self.assertFalse(self.armed()["armed"])
        record = json.loads((self.root / killswitch.DISARM_NAME).read_text())
        record["pid"] = os.getpid() + 99999          # some other process
        (self.root / killswitch.DISARM_NAME).write_text(json.dumps(record),
                                                        encoding="utf-8")
        current = self.armed()
        self.assertTrue(current["armed"])
        self.assertIn("process that has exited", current["reason"])

    def test_rearm_on_guardrails_changed(self):
        # Loosening a limit while disarmed would otherwise let an order through
        # under rules the operator never agreed to.
        self.disarm(ttl=600)
        self.assertFalse(self.armed()["armed"])
        loosened = dict(GUARDRAILS, max_notional=250000)
        current = killswitch.state(self.root, config=loosened)
        self.assertTrue(current["armed"])
        self.assertIn("guardrails changed", current["reason"])

    def test_reordering_the_config_does_not_rearm(self):
        # The negative that stops the rule being noise: a digest sensitive to
        # key order would re-arm on a reformat and get switched off.
        self.disarm(ttl=600)
        reordered = {k: GUARDRAILS[k] for k in reversed(list(GUARDRAILS))}
        self.assertFalse(killswitch.state(self.root, config=reordered)["armed"])

    def test_rearm_on_selector_drift(self):
        self.disarm(ttl=600)
        killswitch.arm("selector_drift", root=self.root)
        self.assertTrue(self.armed()["armed"])
        last = json.loads((self.root / "last-rearm.json").read_text())
        self.assertEqual(last["reason"], "selector_drift")

    def test_rearm_on_verification_mismatch(self):
        self.disarm(ttl=600)
        killswitch.arm("verification_mismatch", root=self.root)
        self.assertTrue(self.armed()["armed"])

    def test_rearm_on_unknown_outcome(self):
        self.disarm(ttl=600)
        killswitch.arm("unknown_outcome", root=self.root)
        self.assertTrue(self.armed()["armed"])

    def test_an_unrecognised_rearm_reason_is_refused(self):
        # The reason is recorded so the operator learns why it came back on. A
        # free-text field would fill with "" and teach them nothing.
        with self.assertRaises(ValueError):
            killswitch.arm("because", root=self.root)

    def test_rearming_when_already_armed_is_harmless(self):
        killswitch.arm("manual", root=self.root)
        killswitch.arm("manual", root=self.root)
        self.assertTrue(self.armed()["armed"])


class RootTests(_NeedsSwitch):
    def test_the_state_lives_outside_the_repo(self):
        # docs/investing-boundary.md: this repo is public, and switch state sits
        # beside order records.
        from unittest.mock import patch
        with patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Users\x\AppData\Local"}):
            root = killswitch.broker_root()
        self.assertIn("agentmux", str(root))
        self.assertIn("broker", str(root))
        repo = Path(__file__).resolve().parents[1]
        self.assertNotIn(str(repo).lower(), str(root).lower())


def main():
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    failed = len(result.failures) + len(result.errors)
    print(f"passed {result.testsRun - failed - len(result.skipped)}, failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
