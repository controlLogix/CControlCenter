#!/usr/bin/env python3
"""The orchestrator warrant: what it permits, and everything it must still refuse.

WHY IT EXISTS. coordination.orchestrator_identity proves orchestrator-ness by the
ABSENCE of $AGENTMUX_AGENT. Every pane sets that variable, so an orchestrator agent
running in its own pane - the whole point of driving a run from the CCC - is refused by
start, assign, complete and teardown. A negative test is not extensible: there is no
value you can put in the environment meaning "yes, more so". The warrant is a positive
credential added as a NARROWING condition on that refusal, never a replacement.

WHAT IT IS NOT, and this file is the wrong place to forget it: not authentication.
Every agent here runs unrestricted and can read the warrant. It stops mistakes - a
worker pane wandering into `run complete` - which is what actually goes wrong.

THE SHAPE OF THESE TESTS. A refusal test proves nothing on its own: "it refused" is
indistinguishable from "it was broken". Every negative below is paired with the
positive that proves the call would otherwise have succeeded.
"""
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "taskmgmt"))

AGENT = "ccc-orchestrator"


class WarrantBase(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="warrant-"))
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self._saved = {k: os.environ.get(k) for k in
                       ("AGENTMUX_HOME", "AGENTMUX_AGENT",
                        "AGENTMUX_ORCHESTRATOR_WARRANT", "AGENTMUX_TRUST_IDENTITY")}
        os.environ["AGENTMUX_HOME"] = str(self.home)
        for key in ("AGENTMUX_AGENT", "AGENTMUX_ORCHESTRATOR_WARRANT",
                    "AGENTMUX_TRUST_IDENTITY"):
            os.environ.pop(key, None)
        self.addCleanup(self._restore)
        import coordination
        self.co = importlib.reload(coordination)

    def _restore(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def issue(self, agent=AGENT, hours=8):
        secret = self.co.issue_warrant(agent, cli="shell", hours=hours)
        os.environ["AGENTMUX_AGENT"] = agent
        os.environ["AGENTMUX_ORCHESTRATOR_WARRANT"] = secret
        return secret

    def tamper(self, **fields):
        record = json.loads(self.co.WARRANT.read_text(encoding="utf-8"))
        record.update(fields)
        self.co.WARRANT.write_text(json.dumps(record), encoding="utf-8")
        os.chmod(self.co.WARRANT, 0o600)


class TestTheWarrantItself(WarrantBase):
    def test_a_valid_warrant_names_its_pane(self):
        # THE PAIRED POSITIVE. Without it every refusal below is indistinguishable
        # from the function simply being broken.
        self.issue()
        self.assertEqual(self.co.orchestrator_warrant(), AGENT)
        self.assertEqual(self.co.orchestrator_pane(), AGENT)

    def test_it_authorises_only_the_pane_it_names(self):
        self.issue()
        os.environ["AGENTMUX_AGENT"] = "worker-x"
        self.assertIsNone(self.co.orchestrator_warrant(),
                          "a different pane used a warrant issued for another")

    def test_the_file_alone_is_not_authority(self):
        self.issue()
        os.environ.pop("AGENTMUX_ORCHESTRATOR_WARRANT")
        self.assertIsNone(self.co.orchestrator_warrant())

    def test_a_wrong_secret_is_refused(self):
        self.issue()
        os.environ["AGENTMUX_ORCHESTRATOR_WARRANT"] = "f" * 64
        self.assertIsNone(self.co.orchestrator_warrant())

    def test_a_malformed_secret_never_reaches_the_file(self):
        self.issue()
        for bad in ("", "short", "g" * 64, "F" * 64, " " + "a" * 63):
            os.environ["AGENTMUX_ORCHESTRATOR_WARRANT"] = bad
            self.assertIsNone(self.co.orchestrator_warrant(), bad)

    def test_a_readable_warrant_is_refused(self):
        # The same check agentmux.sh applies to $ROOT/env. A credential every process
        # on the box can read is not one.
        self.issue()
        os.chmod(self.co.WARRANT, 0o644)
        self.assertIsNone(self.co.orchestrator_warrant())

    def test_an_expired_warrant_is_refused(self):
        # Expiry is the dead-man's switch: a warrant nobody revoked revokes itself.
        self.issue()
        self.tamper(expires_at=int(time.time()) - 1)
        self.assertIsNone(self.co.orchestrator_warrant())

    def test_a_warrant_from_a_different_home_is_not_in_scope(self):
        self.issue()
        other = Path(tempfile.mkdtemp(prefix="warrant-other-"))
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        os.environ["AGENTMUX_HOME"] = str(other)
        import coordination
        co2 = importlib.reload(coordination)
        self.assertIsNone(co2.orchestrator_warrant())

    def test_an_unknown_version_is_refused(self):
        self.issue()
        self.tamper(version=2)
        self.assertIsNone(self.co.orchestrator_warrant())

    def test_a_torn_warrant_is_refused_rather_than_crashing(self):
        self.issue()
        self.co.WARRANT.write_text("{not json", encoding="utf-8")
        os.chmod(self.co.WARRANT, 0o600)
        self.assertIsNone(self.co.orchestrator_warrant())

    def test_no_warrant_at_all_is_quiet(self):
        os.environ["AGENTMUX_AGENT"] = "worker-x"
        os.environ["AGENTMUX_ORCHESTRATOR_WARRANT"] = "a" * 64
        self.assertIsNone(self.co.orchestrator_warrant())


class TestTheReservedName(WarrantBase):
    """LOAD-BEARING. resolve_identity routes who == "orchestrator" straight into
    orchestrator_identity with allow_test_identity=False. A warrant naming it would let
    a pane acquire the VIRTUAL identity, which test_coordination.sh forbids."""

    def test_minting_a_warrant_for_orchestrator_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            self.co.issue_warrant("orchestrator")
        self.assertIn("reserved", str(caught.exception))

    def test_a_hand_written_warrant_naming_orchestrator_is_ignored(self):
        # Both sides, because a rule enforced in only one place is a rule that gets
        # removed as redundant by whoever finds the other.
        secret = self.issue()
        self.tamper(agent="orchestrator")
        os.environ["AGENTMUX_AGENT"] = "orchestrator"
        os.environ["AGENTMUX_ORCHESTRATOR_WARRANT"] = secret
        self.assertIsNone(self.co.orchestrator_warrant())
        with self.assertRaises(self.co.IdentityError):
            self.co.orchestrator_identity("complete", allow_test_identity=False)

    def test_an_invalid_agent_name_is_refused(self):
        for bad in ("../etc", "a b", "", "x" * 65):
            with self.assertRaises(ValueError):
                self.co.issue_warrant(bad)


class TestTheGuardItself(WarrantBase):
    def test_a_warranted_pane_may_act_as_the_orchestrator(self):
        self.issue()
        self.assertEqual(self.co.orchestrator_identity("complete"), "orchestrator")

    def test_an_unwarranted_pane_is_still_refused(self):
        os.environ["AGENTMUX_AGENT"] = "worker-x"
        with self.assertRaises(self.co.IdentityError) as caught:
            self.co.orchestrator_identity("complete")
        # Every suite in this repo substring-matches this text.
        self.assertIn("orchestrator's to call", str(caught.exception))

    def test_outside_a_pane_is_unaffected(self):
        self.assertEqual(self.co.orchestrator_identity("start"), "orchestrator")

    def test_the_warrant_does_not_excuse_a_claimed_by(self):
        # --by survives as a compatibility shim and must stay refused: a warrant buys
        # the right to act, not the right to be someone else in the ledger.
        self.issue()
        with self.assertRaises(self.co.IdentityError):
            self.co.orchestrator_identity("complete", claimed="rev-a")

    def test_revoking_removes_the_authority(self):
        self.issue()
        self.assertEqual(self.co.orchestrator_warrant(), AGENT)
        removed = self.co.revoke_warrant()
        self.assertIn("orchestrator.warrant", removed)
        self.assertIsNone(self.co.orchestrator_warrant())

    def test_the_env_file_is_separate_from_the_shared_env(self):
        # An earlier draft put the secret in $AGENTMUX_HOME/env, which agentmux.sh
        # sources into EVERY pane - handing the credential to every worker and leaving
        # only the name binding standing.
        self.issue()
        self.assertTrue(self.co.WARRANT_ENV.is_file())
        self.assertNotEqual(self.co.WARRANT_ENV, self.home / "env")
        self.assertFalse((self.home / "env").exists())

    def test_both_files_are_private(self):
        self.issue()
        for path in (self.co.WARRANT, self.co.WARRANT_ENV):
            self.assertEqual(path.stat().st_mode & 0o077, 0, path.name)


class TestItBuysExactlyFourVerbs(WarrantBase):
    """THE CONTAINMENT. resolve_identity is untouched, so verdicts, submits, claims and
    every board write never consult the warrant. If that leaked, the warrant would be a
    general-purpose impersonation token."""

    def run_cli(self, *args, env=None):
        # A None value UNSETS. Updating a copy of os.environ is not enough: popping
        # from the local dict leaves the inherited variable in place, so a test that
        # meant "run this outside a pane" ran it inside one and passed for the wrong
        # reason - which is how the --force positive first went green.
        environ = dict(os.environ)
        for key, value in (env or {}).items():
            if value is None:
                environ.pop(key, None)
            else:
                environ[key] = value
        return subprocess.run(
            [sys.executable, str(REPO / "taskmgmt" / "run.py")] + list(args),
            capture_output=True, text=True, env=environ, cwd=str(REPO), timeout=60)

    def seeded_run(self):
        secret = self.issue()
        env = {"AGENTMUX_AGENT": AGENT, "AGENTMUX_ORCHESTRATOR_WARRANT": secret}
        start = self.run_cli("start", "warrant e2e", env=env)
        self.assertEqual(start.returncode, 0, start.stderr)
        rid = start.stdout.strip()
        assign = self.run_cli("assign", rid, "--worker", "w-a", "--reviewer", "r-a",
                              env=env)
        self.assertEqual(assign.returncode, 0, assign.stderr)
        return rid, assign.stdout.strip(), secret, env

    def test_a_warranted_pane_can_start_assign_and_complete(self):
        rid, job, secret, env = self.seeded_run()
        trust = dict(env, AGENTMUX_TRUST_IDENTITY="1")
        self.run_cli("submit", job, "--by", "w-a", "--summary", "done",
                     env=dict(trust, AGENTMUX_AGENT="w-a"))
        self.run_cli("verdict", job, "--by", "r-a", "--pass", "--reason", "ok",
                     env=dict(trust, AGENTMUX_AGENT="r-a"))
        done = self.run_cli("complete", rid, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("COMPLETE", done.stdout)

    def test_the_ledger_records_that_it_was_not_a_person(self):
        # Without this the log cannot tell an autonomous run from an operator-driven
        # one at all, which is the first question asked after a surprise.
        rid, _, _, _ = self.seeded_run()
        events = [json.loads(l) for l in
                  (self.home / "runs" / rid / "events.jsonl").read_text().splitlines()
                  if l.strip()]
        start = next(e for e in events if e["event"] == "start")
        self.assertEqual(start.get("via"), AGENT)

    def test_a_worker_still_cannot_verdict_its_own_job(self):
        # WITH a valid warrant in scope. This is the containment check: the warrant
        # must not leak past the four verbs into resolve_identity.
        rid, job, secret, env = self.seeded_run()
        out = self.run_cli("verdict", job, "--by", "w-a", "--pass", "--reason", "x",
                           env=dict(env, AGENTMUX_AGENT="w-a",
                                    AGENTMUX_ORCHESTRATOR_WARRANT=secret))
        self.assertNotEqual(out.returncode, 0,
                            "a warrant let a worker sign off its own work")

    def test_the_warranted_pane_cannot_verdict_either(self):
        rid, job, secret, env = self.seeded_run()
        self.run_cli("submit", job, "--by", "w-a", "--summary", "done",
                     env=dict(env, AGENTMUX_AGENT="w-a", AGENTMUX_TRUST_IDENTITY="1"))
        for extra in (["--by", "r-a"], []):
            out = self.run_cli("verdict", job, "--pass", "--reason", "x", *extra,
                               env=env)
            self.assertNotEqual(out.returncode, 0,
                                f"the orchestrator signed off work itself ({extra})")

    def test_force_is_refused_to_a_warranted_pane(self):
        # Without this the entire verification gate is one flag deep for an agent that
        # decides it has waited long enough.
        rid, job, secret, env = self.seeded_run()
        out = self.run_cli("complete", rid, "--force", env=env)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("--force is not available", out.stderr)
        self.assertFalse((self.home / "runs" / rid / "COMPLETE").exists())

    def test_force_still_works_for_a_person_outside_a_pane(self):
        # The paired positive: --force is denied to the ORCHESTRATOR, not removed.
        rid, job, secret, env = self.seeded_run()
        plain = dict(env, AGENTMUX_AGENT=None, AGENTMUX_ORCHESTRATOR_WARRANT=None)
        out = self.run_cli("complete", rid, "--force", env=plain)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue((self.home / "runs" / rid / "COMPLETE").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
