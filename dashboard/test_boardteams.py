#!/usr/bin/env python3
"""Roster contract through an isolated store and port-0 HTTP server."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from dataclasses import replace

TEMP = tempfile.TemporaryDirectory(prefix="boardteams-suite-")
BASE = Path(TEMP.name)
os.environ["AGENTMUX_HOME"] = str(BASE / ".agentmux")
os.environ["HOME"] = str(BASE)
os.environ.pop("CC_ENFORCE", None)
os.environ.pop("TM_ENFORCE", None)
OLD_CWD = Path.cwd()
os.chdir(BASE)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import server
import ccboard
import ccstore
import boardteams


class TeamsHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()

    def setUp(self):
        with ccstore.connection() as db:
            epic = ccboard.create(db, "epic", {"title": "Test epic"}, mirror=True)["id"]
            self.epic = epic
            self.key = ccboard.create(db, "task", {"title": "Roster test", "epic": epic},
                                     mirror=True)["id"]
        lead = boardteams.agentdefs.choose_roster({}, {}, {})[0]
        self.selection = [lead, replace(lead, name="reviewer", role="reviewer")]
        self.mock = patch.object(boardteams.agentdefs, "choose_roster", return_value=self.selection)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def call(self, op, body=None, query="", method=None, content_type="application/json"):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.httpd.server_address[1]}/api/board/{op}{query}",
            data=data, method=method)
        if data is not None and content_type:
            request.add_header("Content-Type", content_type)
        try:
            response = urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.code, json.loads(response.read())

    def write(self, op, **extra):
        return self.call(op, {"id": self.key, "actor": "suite", **extra})

    def read(self):
        return self.call("roster", query="?id=" + self.key)

    def events(self):
        status, payload = self.call("history", query="?id=" + self.key)
        self.assertEqual(status, 200)
        return payload["events"]

    def test_roundtrip_idempotence_and_all_transitions(self):
        self.assertEqual(self.read(), (200, {"id": self.key, "members": [], "count": 0, "gaps": []}))
        status, proposed = self.write("recruit")
        self.assertEqual(status, 200)
        self.assertEqual(proposed["count"], 2)
        self.assertTrue(all(r["status"] == "proposed" and r["proposed_by"] == "suite"
                            for r in proposed["members"]))
        events = self.events()
        self.assertEqual(self.write("recruit"), (200, proposed))
        self.assertEqual(self.events(), events)
        status, approved = self.write("approve", members=["lead"])
        self.assertEqual(status, 200)
        lead, reviewer = approved["members"]
        self.assertEqual((lead["status"], lead["approved_by"]), ("approved", "suite"))
        self.assertTrue(lead["approved_at"])
        self.assertEqual(reviewer["status"], "rejected")
        self.assertEqual(self.read(), (200, approved))
        events = self.events()
        self.assertEqual({e["event"] for e in events} & {"recruit", "approve", "reject"},
                         {"recruit", "approve", "reject"})
        self.assertTrue(all(e["actor"] == "suite" for e in events
                            if e["event"] in ("recruit", "approve", "reject")))
        self.assertEqual(self.write("approve", members=["lead"], actor="retry"), (200, approved))
        self.assertEqual(self.events(), events)
        status, error = self.write("approve", members=[])
        self.assertEqual(status, 409)
        self.assertTrue(error["missing"][0]["hint"])

    def test_recruit_replaces_non_hired_preserves_hired(self):
        self.write("recruit")
        self.write("approve", members=["lead", "reviewer"])
        with ccstore.connection() as db:
            db.execute("UPDATE board_roster SET status='hired',member_name='test-lead',"
                       "worktree='/test',branch='test' WHERE entity_key=? AND agent_name='lead'",
                       (self.key,))
        before = self.read()[1]["members"][0]
        self.selection[:] = [self.selection[0], replace(self.selection[1], name="new-reviewer")]
        status, payload = self.write("recruit")
        self.assertEqual(status, 200)
        self.assertEqual(payload["members"][0], before)
        self.assertEqual(payload["members"][1]["agent_name"], "new-reviewer")
        self.assertEqual(payload["members"][1]["status"], "proposed")
        self.assertIsNone(payload["members"][1]["approved_at"])
        approved = self.write("approve", members=["new-reviewer"])
        self.assertEqual(approved[0], 200)
        self.assertEqual(self.write("approve", members=["new-reviewer"]), approved)

    def test_invalid_approval_is_atomic(self):
        self.write("recruit")
        before, events = self.read(), self.events()
        for members in (["lead", "unknown"], ["lead", "lead"], [None], [1], ["Bad"],
                        "lead", None, ["a"] * 33):
            with self.subTest(members=members):
                self.assertEqual(self.write("approve", members=members)[0], 400)
                self.assertEqual(self.read(), before)
                self.assertEqual(self.events(), events)

    def test_reject_all_is_idempotent(self):
        self.write("recruit")
        result = self.write("approve", members=[])
        self.assertEqual(result[0], 200)
        self.assertTrue(all(r["status"] == "rejected" for r in result[1]["members"]))
        events = self.events()
        self.assertEqual(self.write("approve", members=[]), result)
        self.assertEqual(self.events(), events)

    def test_http_checklist(self):
        for op in ("recruit", "approve"):
            self.assertEqual(self.call(op)[0], 405)
            self.assertEqual(self.call(op, {}, content_type=None)[0], 415)
            for key in (None, "none", "bad", "TM-001\n", "a" * 300):
                self.assertEqual(self.write(op, id=key, members=[])[0], 400)
            self.assertEqual(self.write(op, id="TM-999999999", members=[])[0], 404)
            self.assertEqual(self.write(op, actor=None, members=[])[0], 400)
        self.assertEqual(self.call("roster", {})[0], 405)
        self.assertEqual(self.call("roster", query="?id=TM-999999999")[0], 404)
        for query in ("", "?id=", "?id=none", "?id=Bad", "?id=" + "x" * 300,
                      "?id=TM-001&id=TM-002"):
            self.assertEqual(self.call("roster", query=query)[0], 400)
        self.assertIn(self.call("unknown")[0], (404, 405))
        self.assertEqual(self.write("approve", members=["unknown"])[0], 400)
        status, error = self.write("approve", members=[])
        self.assertEqual(status, 409)
        self.assertTrue(error["missing"][0]["hint"])
        with ccstore.connection() as db:
            db.execute("UPDATE tasks SET status='deleted' WHERE key=?", (self.key,))
        for op in ("recruit", "approve"):
            status, error = self.write(op, members=[])
            self.assertEqual(status, 409)
            self.assertTrue(error["missing"][0]["hint"])

    def test_real_selector_defaults_to_solo_lead(self):
        self.mock.stop()
        with ccstore.connection() as db:
            self.assertTrue(ccboard.config(db)["teamRequireApproval"])
        status, payload = self.write("recruit")
        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["members"][0]["role"], "lead")
        # No approved roster is required to select the dispatcher fallback lead.
        selected = boardteams.agentdefs.choose_roster({}, {}, {"teamRequireApproval": True})
        self.assertEqual([(s.name, s.role) for s in selected], [("lead", "lead")])

    def test_real_recruitment_worker_approval_and_persisted_gaps(self):
        self.mock.stop()
        directory = BASE / ".agentmux/agents"
        directory.mkdir(parents=True, exist_ok=True)
        for name, extra in (("frontend", "capabilities: ui\n"),
                            ("senior-backend", "capabilities: backend\n"),
                            ("reviewer", "role: reviewer\n")):
            path = directory / (name + ".md")
            path.write_text(f"---\nname: {name}\ndescription: Real worker\n{extra}---\n")
            self.addCleanup(path.unlink)
        with ccstore.connection() as db:
            for path in ("dashboard/view.js", "taskmgmt/work.py"):
                ccboard.add_touch(db, self.key, path, actor="suite")
            ccboard.set_label(db, self.key, "missing-capability", True, actor="suite")
        status, proposal = self.write("recruit")
        self.assertEqual(status, 200, proposal)
        self.assertEqual([r["role"] for r in proposal["members"]], ["lead", "worker", "worker"])
        self.assertIn("Capability missing-capability: no definition provides it", proposal["gaps"])
        self.assertEqual(self.read(), (200, proposal))
        self.assertEqual(self.write("recruit"), (200, proposal))
        # A changed diagnostic alone is a new proposal; unchanged retry stays quiet.
        before = len([e for e in self.events() if e["event"] == "recruit"])
        with ccstore.connection() as db:
            ccboard.set_label(db, self.key, "another-missing", True, actor="suite")
        status, proposal = self.write("recruit")
        self.assertEqual(status, 200)
        self.assertIn("Capability another-missing: no definition provides it", proposal["gaps"])
        self.assertEqual(len([e for e in self.events() if e["event"] == "recruit"]), before + 1)
        self.assertEqual(self.write("recruit"), (200, proposal))
        status, approved = self.write("approve", members=[r["agent_name"] for r in proposal["members"]])
        self.assertEqual(status, 200)
        self.assertTrue(all(r["status"] == "approved" for r in approved["members"]))
        self.assertEqual(approved["gaps"], proposal["gaps"])
        with ccstore.connection() as db:
            previous = self.key
            for i in range(3):
                key = ccboard.create(db, "task", {"title": f"Dependency {i}", "epic": self.epic},
                                     mirror=True)["id"]
                ccboard.set_dep(db, previous, key, True, actor="suite")
                previous = key
        status, deep = self.write("recruit")
        self.assertEqual(status, 200, deep)
        self.assertEqual([r["agent_name"] for r in deep["members"]], ["lead", "senior-backend"])
        # Diagnostics describe the saved proposal, even if definitions change.
        (directory / "senior-backend.md").write_text("invalid")
        self.assertEqual(self.read(), (200, deep))

    def prepare_hire(self):
        self.write("recruit")
        self.write("approve", members=["lead"])
        with ccstore.connection() as db:
            ccboard.set_config(db, "dashboardMayHire", True)
            ccboard.set_config(db, "dispatchEnabled", True)
        self.addCleanup(self.reset_hire_config)
        directory = BASE / ".agentmux/agents"
        directory.mkdir(parents=True, exist_ok=True)
        definition = directory / "lead.md"
        definition.write_text("---\nname: lead\ndescription: Hire test\ncli: codex\n"
                              "role: lead\nposture: unrestricted\nmodel: disk-model\n"
                              "---\nDisk persona\n")
        self.addCleanup(definition.unlink)
        repo = patch.object(boardteams.dispatch, "REPO", BASE)
        repo.start()
        self.addCleanup(repo.stop)
        spawn = patch.object(boardteams.dispatch, "agentmux", return_value=(0, "", ""))
        mocked = spawn.start()
        self.addCleanup(spawn.stop)
        return mocked

    def reset_hire_config(self):
        with ccstore.connection() as db:
            ccboard.set_config(db, "dashboardMayHire", False)
            ccboard.set_config(db, "dispatchEnabled", False)

    def test_hire_ignores_injected_launch_fields_and_resolves_disk(self):
        spawn = self.prepare_hire()
        def spawned(*args):
            self.assertEqual(Path(args[args.index("--persona-file") + 1]).read_text(),
                             "Disk persona")
            return 0, "", ""
        spawn.side_effect = spawned
        status, result = self.call("hire", {
            "id": self.key, "name": "lead", "cli": "evil-cli", "cwd": "/evil",
            "argv": ["--evil"], "model": "evil-model", "posture": "read-only",
            "flags": ["--evil"], "actor": "evil-actor"})
        self.assertEqual(status, 200, result)
        args = spawn.call_args.args
        self.assertEqual(args[args.index("--cli") + 1], "codex")
        self.assertEqual(args[args.index("--cwd") + 1], str(BASE))
        self.assertEqual(args[args.index("--model") + 1], "disk-model")
        for injected in ("evil-cli", "/evil", "--evil", "evil-model", "evil-actor"):
            self.assertNotIn(injected, args)
        self.assertEqual(result["members"][0]["status"], "hired")
        self.assertEqual([e["actor"] for e in self.events() if e["event"] == "hire"],
                         ["dashboard"])
        self.assertEqual(self.call("hire", {"id": self.key, "name": "lead"})[0], 409)
        spawn.assert_called_once()

    def test_hire_requires_approval_on_this_card(self):
        spawn = self.prepare_hire()
        for state in ("proposed", "rejected", "hired", "finished"):
            with self.subTest(state=state):
                with ccstore.connection() as db:
                    db.execute("UPDATE board_roster SET status=? WHERE entity_key=?",
                               (state, self.key))
                self.assertEqual(self.call("hire", {"id": self.key, "name": "lead"})[0], 409)
        self.assertEqual(self.call("hire", {"id": self.key, "name": "unknown"})[0], 409)
        with ccstore.connection() as db:
            other = ccboard.create(db, "task", {"title": "Other card", "epic": self.epic},
                                   mirror=True)["id"]
        self.assertEqual(self.call("hire", {"id": other, "name": "lead"})[0], 409)
        spawn.assert_not_called()

    def test_hire_config_and_listener_gates(self):
        spawn = self.prepare_hire()
        for flag in ("dashboardMayHire", "dispatchEnabled"):
            with self.subTest(flag=flag):
                with ccstore.connection() as db:
                    ccboard.set_config(db, flag, False)
                self.assertEqual(self.call("hire", {"id": self.key, "name": "lead"})[0], 403)
                with ccstore.connection() as db:
                    ccboard.set_config(db, flag, True)
        with ccstore.connection() as db:
            for host in (None, "0.0.0.0", "::1", "192.168.1.1"):
                with self.assertRaises(boardteams.HireForbidden):
                    boardteams.hire(db, {"id": self.key, "name": "lead"}, bind_host=host)
        spawn.assert_not_called()

    def test_hire_slots_and_spawn_failure_release(self):
        spawn = self.prepare_hire()
        slots = boardteams.HIRE_SLOTS
        self.assertTrue(slots.acquire(blocking=False))
        self.assertTrue(slots.acquire(blocking=False))
        try:
            self.assertEqual(self.call("hire", {"id": self.key, "name": "lead"})[0], 503)
            spawn.assert_not_called()
        finally:
            slots.release()
            slots.release()
        spawn.return_value = (1, "", "failed")
        self.assertEqual(self.call("hire", {"id": self.key, "name": "lead"})[0], 503)
        self.assertEqual(self.read()[1]["members"][0]["status"], "approved")
        spawn.return_value = (0, "", "")
        self.assertEqual(self.call("hire", {"id": self.key, "name": "lead"})[0], 200)

    def test_hire_posture_ceiling_and_missing_definition(self):
        spawn = self.prepare_hire()
        path = BASE / ".agentmux/agents/lead.md"
        original = path.read_text()
        path.write_text("invalid definition")
        self.assertEqual(self.call("hire", {"id": self.key, "name": "lead"})[0], 409)
        spawn.assert_not_called()
        path.write_text(original)
        with patch.dict(os.environ, {"AGENTMUX_NO_BYPASS": "1"}):
            self.assertEqual(self.call("hire", {"id": self.key, "name": "lead"})[0], 200)
        args = spawn.call_args.args
        self.assertEqual(args[args.index("--posture") + 1], "workspace-write")


if __name__ == "__main__":
    try:
        result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(TeamsHTTP))
    finally:
        os.chdir(OLD_CWD)
        TEMP.cleanup()
    failed = len(result.failures) + len(result.errors)
    print(f"passed {result.testsRun - failed}, failed {failed}")
    sys.exit(bool(failed))
