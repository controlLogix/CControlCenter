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
        self.assertEqual(self.read(), (200, {"id": self.key, "members": [], "count": 0}))
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
