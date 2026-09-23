#!/usr/bin/env python3
"""C2 contract checks against isolated files and a real port-0 HTTP server."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

# Set all discovery/store roots before importing any dashboard module.
TEMP = tempfile.TemporaryDirectory(prefix="boardagents-suite-")
BASE = Path(TEMP.name)
os.environ["HOME"] = str(BASE / "home")
os.environ["AGENTMUX_HOME"] = str(BASE / "home/.agentmux")
os.environ.pop("CC_ENFORCE", None)
os.environ.pop("TM_ENFORCE", None)
REPO = BASE / "repo"
REPO.mkdir()
OLD_CWD = Path.cwd()
os.chdir(REPO)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import server  # noqa: E402


class AgentsHTTP(unittest.TestCase):
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
        self.dirs = [REPO / ".agentmux/agents",
                     Path(os.environ["AGENTMUX_HOME"]) / "agents",
                     REPO / ".claude/agents", Path.home() / ".claude/agents"]
        for directory in self.dirs:
            directory.mkdir(parents=True, exist_ok=True)
            for path in directory.iterdir():
                path.unlink()

    def write(self, name, scope=0, extra="", body="Persona\nwith details"):
        path = self.dirs[scope] / (name + ".md")
        path.write_text(f"---\nname: {name}\ndescription: Useful agent\ncli: codex\n"
                        f"{extra}---\n{body}", encoding="utf-8")
        return path

    def call(self, query="", method="GET", path="/api/board/agents"):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.httpd.server_address[1]}{path}{query}",
            method=method)
        try:
            response = urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.code, json.loads(response.read())

    def test_empty_contract(self):
        self.assertEqual(self.call(), (200, {"agents": [], "scopes":
                         ["claude", "global", "repo"], "problems": [], "count": 0}))

    def test_all_scopes_exact_payload_and_detail(self):
        for index, scope in enumerate(("repo", "global", "claude", "claude")):
            name = "agent-" + str(index)
            path = self.write(name, index)
            expected = dict(name=name, scope=scope, description="Useful agent", cli="codex",
                            model=None, auth=None, posture="workspace-write", tools=[],
                            tools_deny=[], role="worker", capabilities=[], worktree="per-member",
                            max_instances=1, path=str(path), editable=scope != "claude",
                            checksum="sha256:" + hashlib.sha256(path.read_bytes()).hexdigest())
            status, detail = self.call("?name=" + name)
            self.assertEqual(status, 200)
            self.assertEqual(detail, dict(expected, persona="Persona\nwith details"))
            status, payload = self.call()
            self.assertEqual(status, 200)
            self.assertEqual(set(payload), {"agents", "scopes", "problems", "count"})
            self.assertEqual(payload["agents"][index], expected)
            self.assertTrue(all("persona" not in row for row in payload["agents"]))
            self.assertEqual(payload["count"], index + 1)
            self.assertEqual(payload["scopes"], ["claude", "global", "repo"])
            self.assertEqual(payload["problems"], [])

    def test_problems_survive_and_collisions_are_excluded(self):
        warned = self.write("warned", 1, "tool: Read\n")
        bad = self.write("bad", 0, "posture: invalid\n")
        first = self.write("duplicate", 0)
        second = self.write("duplicate", 2)
        status, payload = self.call()
        self.assertEqual(status, 200)
        self.assertEqual([row["name"] for row in payload["agents"]], ["warned"])
        self.assertEqual(payload["count"], 1)
        problems = payload["problems"]
        self.assertEqual(len(problems), 3)
        self.assertTrue(all(set(p) == {"path", "scope", "error"} for p in problems))
        self.assertTrue(any(p["path"] == str(warned) and p["scope"] == "global"
                            and "tool" in p["error"] for p in problems))
        self.assertTrue(any(p["path"] == str(bad) and "posture" in p["error"] for p in problems))
        self.assertTrue(any(str(first) in str(p) and str(second) in str(p) for p in problems))
        self.assertEqual(self.call("?name=duplicate")[0], 404)

    def test_collection_fields(self):
        path = self.dirs[0] / "reviewer.md"
        path.write_text("---\nname: reviewer\ndescription: Review\ncli: claude\n"
                        "tools: Read, Grep\ntools-deny: Write\ncapabilities: review, security\n"
                        "role: reviewer\nworktree: none\nposture: read-only\n---\nReview it")
        status, payload = self.call()
        self.assertEqual(status, 200)
        row = payload["agents"][0]
        self.assertEqual(row["tools"], ["Read", "Grep"])
        self.assertEqual(row["tools_deny"], ["Write"])
        self.assertEqual(row["capabilities"], ["review", "security"])

    def test_http_errors(self):
        self.assertEqual(self.call(method="POST")[0], 405)
        self.assertEqual(self.call("?name=unknown")[0], 404)
        for query in ("?name=", "?name=Bad", "?name=../secret", "?name=a.b",
                      "?name=a%00", "?name=a%0A", "?name=" + "a" * 65,
                      "?name=" + "a" * 300, "?name=a&name=b"):
            with self.subTest(query=query):
                status, payload = self.call(query)
                self.assertEqual(status, 400)
                self.assertIn("error", payload)
        self.assertIn(self.call(path="/api/board/nosuchop")[0], (404, 405))


if __name__ == "__main__":
    try:
        result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(AgentsHTTP))
    finally:
        os.chdir(OLD_CWD)
        TEMP.cleanup()
    failed = len(result.failures) + len(result.errors)
    print(f"passed {result.testsRun - failed}, failed {failed}")
    sys.exit(bool(failed))
