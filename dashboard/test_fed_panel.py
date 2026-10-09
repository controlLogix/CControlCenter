"""EP-032: the dashboard's Federation view (fed_panel.py, fed.js, the /api/fed/ route).

A fake hub on a unix socket records what reaches it, so the tests prove which verbs
and arguments can cross from HTTP to the hub - and that nothing else can.
  python3 dashboard/test_fed_panel.py
"""
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

import fed_panel

HERE = Path(__file__).resolve().parent


class FakeHub:
    def __init__(self):
        self.home = tempfile.mkdtemp(prefix="fedpanel-", dir="/tmp")
        os.makedirs(os.path.join(self.home, "hub"))
        self.path = os.path.join(self.home, "hub", "hub.sock")
        self.seen = []
        self.srv = socket.socket(socket.AF_UNIX)
        self.srv.bind(self.path)
        self.srv.listen(8)
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            buf = b""
            while not buf.endswith(b"\n"):
                buf += c.recv(65536)
            req = json.loads(buf)
            self.seen.append((req["verb"], req["args"]))
            res = {"ok": True, "result": {"verb": req["verb"]}} if req["verb"] != "fed_deny" else \
                {"ok": False, "error": "no held quarantine item"}
            c.sendall((json.dumps(res) + "\n").encode())
            c.close()

    def close(self):
        self.srv.close()
        shutil.rmtree(self.home, ignore_errors=True)


class Panel(unittest.TestCase):
    def setUp(self):
        self.hub = FakeHub()

    def tearDown(self):
        self.hub.close()

    def test_panel_reads(self):
        self.assertEqual(fed_panel.panel(self.hub.home), (200, {"result": {"verb": "fed_panel"}}))

    def test_hub_down_is_503(self):
        self.assertEqual(fed_panel.panel("/nonexistent")[0], 503)

    def test_only_allowlisted_actions_cross(self):
        ok = [("fed_approve", {"id": "Q-01ABCDEFGH"}), ("fed_approve", {"id": "Q-01ABCDEFGH", "privileged": True}),
              ("fed_kill", {"revoke": True}), ("fed_resume", {}), ("fed_board_move", {"key": "SH-12", "status": "done"})]
        for verb, args in ok:
            self.assertEqual(fed_panel.action({"verb": verb, "args": args}, self.hub.home)[0], 200, verb)
        bad = [("fed_share", {"repo": "x"}), ("fed_trust", {"peer": "eve", "level": "auto"}), ("post", {}),
               ("fed_approve", {"id": "Q-1; rm"}), ("fed_approve", {"id": "Q-01ABCDEFGH", "extra": 1}),
               ("fed_kill", {"revoke": "yes"}), ("fed_board_move", {"key": "SH-1", "status": "gone"}),
               ("fed_board_move", {"key": "SH-1"}), ("fed_approve", {})]
        before = len(self.hub.seen)
        for verb, args in bad:
            self.assertEqual(fed_panel.action({"verb": verb, "args": args}, self.hub.home)[0], 400, (verb, args))
        self.assertEqual(len(self.hub.seen), before, "a refused action never reaches the hub")
        self.assertEqual(fed_panel.action({"verb": "fed_deny", "args": {"id": "Q-01ABCDEFGH"}}, self.hub.home)[0], 409)


class Static(unittest.TestCase):
    def test_wired_into_the_page(self):
        index = (HERE / "index.html").read_text()
        self.assertIn('data-view="fed"', index)
        self.assertIn('id="viewFed"', index)
        self.assertLess(index.index('src="fed.js"'), index.index('src="app.js"'))
        self.assertIn('"/fed.js"', (HERE / "server.py").read_text())

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_fed_js_parses(self):
        r = subprocess.run(["node", "--check", str(HERE / "fed.js")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
