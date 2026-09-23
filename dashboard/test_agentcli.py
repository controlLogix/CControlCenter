#!/usr/bin/env python3
"""Definition CLI integration suite; private port and roots, never the live server.

Run only this suite: python3 dashboard/test_agentcli.py
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

CLI = Path(__file__).resolve().parents[1] / "taskmgmt/coordination.py"
TEMP = tempfile.TemporaryDirectory(prefix="agentcli-suite-")
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


class AgentCLI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.env = dict(os.environ, AGENTMUX_DASHBOARD=
                       f"http://127.0.0.1:{cls.httpd.server_address[1]}")

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()

    def setUp(self):
        for directory in (REPO / ".agentmux/agents", BASE / "home/.agentmux/agents"):
            directory.mkdir(parents=True, exist_ok=True)
            for path in directory.iterdir():
                path.unlink()

    def cli(self, *args, code=0):
        result = subprocess.run([sys.executable, str(CLI), *args], env=self.env,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result

    def save(self, scope="repo", *extra):
        return self.cli("agentdef", scope, "cli-test", "--description", "CLI test",
                        "--cli", "codex", "--persona", "Line one\nLine two", *extra)

    def test_roundtrip_both_scopes_and_json(self):
        for scope in ("repo", "global"):
            saved = json.loads(self.save(scope, "--tools", "Read", "Grep",
                                         "--tools-deny", "Write", "--capabilities",
                                         "review", "--max-instances", "2", "--json").stdout)
            self.assertEqual(saved["tools"], ["Read", "Grep"])
            self.assertEqual(saved["tools_deny"], ["Write"])
            self.assertEqual(saved["capabilities"], ["review"])
            self.assertEqual(saved["max_instances"], 2)
            self.assertEqual(json.loads(self.cli("agents", "cli-test", "--json").stdout), saved)
            listing = json.loads(self.cli("agents", "--json").stdout)
            self.assertEqual(listing["count"], 1)
            self.assertNotIn("persona", listing["agents"][0])
            updated = json.loads(self.save(scope, "--checksum", saved["checksum"],
                                           "--tools", "--json").stdout)
            self.assertEqual(updated["tools"], [])
            self.assertNotEqual(updated["checksum"], saved["checksum"])
            dropped = json.loads(self.cli("agentdrop", scope, "cli-test", "--checksum",
                                          updated["checksum"], "--json").stdout)
            self.assertEqual(dropped, {"ok": True, "scope": scope, "name": "cli-test"})

    def test_human_output(self):
        self.assertIn("0 agent definition(s)", self.cli("agents").stdout)
        self.assertIn("Saved agent definition:", self.save().stdout)
        self.assertIn("cli-test [scope: repo] — CLI test", self.cli("agents").stdout)
        detail = self.cli("agents", "cli-test").stdout
        self.assertIn("Line one\nLine two", detail)
        self.assertIn("checksum: sha256:", detail)
        self.assertIn("Dropped agent definition cli-test (repo)",
                      self.cli("agentdrop", "repo", "cli-test").stdout)

    def test_list_truncates_description_but_detail_and_json_preserve_it(self):
        description = "A" * 2048
        self.cli("agentdef", "repo", "cli-test", "--description", description,
                 "--cli", "claude")
        self.assertEqual(self.cli("agents").stdout.splitlines()[1],
                         "  cli-test [scope: repo] — " + "A" * 79 + "…")
        self.assertIn(description, self.cli("agents", "cli-test").stdout)
        self.assertEqual(json.loads(self.cli("agents", "--json").stdout)
                         ["agents"][0]["description"], description)

    def test_refusal_retains_board_message_and_fix_hint(self):
        self.save()
        for command in (("agentdef", "repo", "cli-test", "--checksum", "stale"),
                        ("agentdrop", "repo", "cli-test", "--checksum", "stale")):
            result = self.cli(*command, "--json", code=1)
            self.assertEqual(result.stdout, "")
            self.assertIn("reload before saving", result.stderr)
            self.assertIn("fix: " + str(REPO / ".agentmux/agents/cli-test.md"), result.stderr)
            self.assertNotIn("HTTP Error", result.stderr)
        self.cli("agents", "cli-test")  # Refused deletion preserved the definition.

    def test_validation_and_encoded_name_reach_server(self):
        self.save()
        for command, message in (
            (("agents", "cli-test&name=another"), "name must match"),
            (("agents", "absent"), "agent not found"),
            (("agentdef", "claude", "other"), "read-only"),
            (("agentdef", "repo", "other", "--description", "Test", "--max-instances", "99"), "max_instances"),
            (("agentdrop", "repo", "absent"), "agent not found"),
        ):
            with self.subTest(command=command):
                result = self.cli(*command, code=1)
                self.assertIn(message, result.stderr)
                self.assertNotIn("HTTP Error", result.stderr)


if __name__ == "__main__":
    try:
        result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(AgentCLI))
    finally:
        os.chdir(OLD_CWD)
        TEMP.cleanup()
    failures = len(result.failures) + len(result.errors)
    print(f"passed {result.testsRun - failures}, failed {failures}")
    sys.exit(bool(failures))
