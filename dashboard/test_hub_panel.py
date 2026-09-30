"""TM-216: the dashboard as a hub client.

Starts a REAL agentmux-hub on a throwaway AGENTMUX_HOME, registers a repo and a
work item through its socket, and checks that the dashboard's hub helper and its
HTTP endpoints hand them back - plus the hub-down path, and that nothing in the
dashboard opens hub.db itself.

Run inside WSL from the repo root:  python3 dashboard/test_hub_panel.py
"""
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))

import hub_panel  # noqa: E402


def raw_call(sock_path, verb, args):
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(10)
    s.connect(sock_path)
    s.sendall((json.dumps({"verb": verb, "args": args}) + "\n").encode())
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
    s.close()
    return json.loads(buf)


class HubPanelLive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp(prefix="hubpanel-")
        cls.checkout = os.path.join(cls.home, "checkout")
        os.makedirs(cls.checkout)
        env = {**os.environ, "AGENTMUX_HOME": cls.home, "AGENTMUX_SOCKET": "hubpanel-test-nonexistent"}
        env.pop("AGENTMUX_AGENT", None)
        cls.proc = subprocess.Popen([sys.executable, str(REPO / "hub" / "server.py")], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    stdin=subprocess.DEVNULL, start_new_session=True)
        cls.sock = os.path.join(cls.home, "hub", "hub.sock")
        for _ in range(100):
            if os.path.exists(cls.sock):
                try:
                    if raw_call(cls.sock, "ping", {}).get("ok"):
                        break
                except OSError:
                    pass
            time.sleep(0.1)
        else:
            cls.tearDownClass()
            raise RuntimeError("hub did not come up")
        r = raw_call(cls.sock, "repo_add", {"repo": "hubpanel", "paths": [cls.checkout]})
        assert r["ok"], r
        w = raw_call(cls.sock, "work_add", {"to": "role:hubpanel/worker", "title": "dashboard sees this"})
        assert w["ok"], w
        cls.work_id = w["result"]["id"]

    @classmethod
    def tearDownClass(cls):
        try:
            raw_call(cls.sock, "shutdown", {})
        except Exception:
            pass
        try:
            cls.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
            cls.proc.wait(timeout=5)
        shutil.rmtree(cls.home, ignore_errors=True)

    # -- the helper -------------------------------------------------------------------
    def test_helper_lists_the_work_item_and_its_state(self):
        status, body = hub_panel.endpoint("work", {}, self.home)
        self.assertEqual(status, 200, body)
        self.assertTrue(body["ok"])
        self.assertEqual(body["caller"], "operator")
        rows = {w["id"]: w for w in body["result"]}
        self.assertIn(self.work_id, rows)
        self.assertEqual(rows[self.work_id]["state"], "ready")
        self.assertEqual(rows[self.work_id]["title"], "dashboard sees this")
        self.assertEqual(rows[self.work_id]["target"], "role:hubpanel/worker")
        self.assertIsNone(rows[self.work_id]["claimed_by"])

    def test_helper_work_show_and_filters(self):
        status, body = hub_panel.endpoint(f"work/{self.work_id}", {}, self.home)
        self.assertEqual(status, 200, body)
        self.assertEqual(body["result"]["id"], self.work_id)
        self.assertEqual(body["result"]["children"], [])
        self.assertEqual(hub_panel.endpoint("work", {"state": ["done"]}, self.home)[1]["result"], [])
        self.assertEqual(hub_panel.endpoint("work/W-nope", {}, self.home)[0], 404)
        self.assertEqual(hub_panel.endpoint("work/..%2F", {}, self.home)[0], 400)
        self.assertEqual(hub_panel.endpoint("work", {"state": ["bogus"]}, self.home)[0], 400)

    def test_helper_status_counts_and_events(self):
        status, body = hub_panel.endpoint("status", {}, self.home)
        self.assertEqual(status, 200, body)
        self.assertGreaterEqual(body["result"]["work"].get("ready", 0), 1)
        self.assertIn("hubpanel", body["result"]["repos"])
        status, tail = hub_panel.endpoint("events", {"tail": ["50"]}, self.home)
        self.assertEqual(status, 200, tail)
        self.assertIsInstance(tail["next"], int)
        status, after = hub_panel.endpoint("events", {"since": [str(tail["next"])]}, self.home)
        self.assertEqual(status, 200, after)
        self.assertTrue(all(e["seq"] > tail["next"] for e in after["result"]))
        self.assertEqual(hub_panel.endpoint("agents", {}, self.home)[0], 200)

    def test_only_read_verbs_can_be_sent(self):
        with self.assertRaises(ValueError):
            hub_panel.call("work_cancel", {"work_id": self.work_id}, home=self.home)
        with self.assertRaises(ValueError):
            hub_panel.call("inbox", {}, home=self.home)

    # -- through HTTP -----------------------------------------------------------------
    def test_http_endpoints_pass_the_hub_through(self):
        import server
        from http.server import ThreadingHTTPServer
        with patch.object(server, "HOME_DIR", Path(self.home)):
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=10)
                conn.request("GET", "/api/hub/work")
                r = conn.getresponse()
                self.assertEqual(r.status, 200)
                data = json.loads(r.read())
                self.assertIn(self.work_id, [w["id"] for w in data["result"]])
                conn.request("GET", f"/api/hub/work/{self.work_id}")
                r = conn.getresponse()
                self.assertEqual(r.status, 200)
                self.assertEqual(json.loads(r.read())["result"]["state"], "ready")
                for path in ("/api/hub/status", "/api/hub/agents", "/api/hub/events?since=0"):
                    conn.request("GET", path)
                    r = conn.getresponse()
                    self.assertEqual(r.status, 200, path)
                    self.assertTrue(json.loads(r.read())["ok"], path)
                conn.request("POST", "/api/hub/work", "{}", {"Content-Type": "application/json"})
                r = conn.getresponse()
                self.assertEqual(r.status, 405)
                r.read()
                conn.request("GET", "/hub.js")
                r = conn.getresponse()
                self.assertEqual(r.status, 200)
                self.assertIn("registerView('hub', load, 2000)", r.read().decode())
                conn.close()
            finally:
                httpd.shutdown()
                httpd.server_close()


class HubDown(unittest.TestCase):
    def test_absent_socket_is_a_graceful_503(self):
        home = tempfile.mkdtemp(prefix="hubpanel-down-")
        self.addCleanup(shutil.rmtree, home, True)
        for sub in ("status", "work", "work/W-1", "events", "agents"):
            status, body = hub_panel.endpoint(sub, {}, home)
            self.assertEqual((status, body), (503, {"error": "hub not running"}), sub)

    def test_stale_socket_file_is_a_graceful_503(self):
        home = tempfile.mkdtemp(prefix="hubpanel-stale-")
        self.addCleanup(shutil.rmtree, home, True)
        os.makedirs(os.path.join(home, "hub"))
        path = os.path.join(home, "hub", "hub.sock")
        s = socket.socket(socket.AF_UNIX)
        s.bind(path)
        s.close()                       # the file stays; nobody listens: refused
        self.assertEqual(hub_panel.endpoint("status", {}, home), (503, {"error": "hub not running"}))

    def test_http_says_hub_not_running(self):
        import server
        from http.server import ThreadingHTTPServer
        home = tempfile.mkdtemp(prefix="hubpanel-down-")
        self.addCleanup(shutil.rmtree, home, True)
        with patch.object(server, "HOME_DIR", Path(home)):
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=10)
                conn.request("GET", "/api/hub/status")
                r = conn.getresponse()
                self.assertEqual(r.status, 503)
                self.assertEqual(json.loads(r.read()), {"error": "hub not running"})
                conn.close()
            finally:
                httpd.shutdown()
                httpd.server_close()


class NeverOpensHubDb(unittest.TestCase):
    def test_no_sqlite_connect_to_the_hub_database(self):
        # docs/PROTOCOL.md sections 3 and 8: hub/ is the hub's alone.
        pattern = re.compile(r"sqlite3?\.connect\([^)]*(hub\.db|[\"'/]hub[\"'/])", re.S)
        for name in ("server.py", "hub_panel.py"):
            source = (HERE / name).read_text()
            self.assertIsNone(pattern.search(source), f"{name} opens hub.db directly")
            for line in source.splitlines():
                code = line.split("#", 1)[0]
                if "hub.db" in code and "connect" in code:
                    self.fail(f"{name}: {line.strip()}")
        self.assertNotIn("import sqlite3", (HERE / "hub_panel.py").read_text())


if __name__ == "__main__":
    unittest.main(verbosity=1)
