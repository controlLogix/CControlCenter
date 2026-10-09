#!/usr/bin/env python3
"""DNS rebinding: only this server's own loopback Host may read or write.

Binding 127.0.0.1 keeps other machines out, but not a page in the operator's own
browser. A page re-points its name at 127.0.0.1 and is then same-origin with this
server, so it can read /api/stream/<agent> (live terminal content) without any
Origin header. What it cannot change is the Host the browser sends, so that is what
Handler.host_allowed checks.

    python3 dashboard/test_host_guard.py
"""
import http.client
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ["AGENTMUX_HOME"] = tempfile.mkdtemp(prefix="ccc-host-")

import server  # noqa: E402


class HostGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.port = cls.httpd.server_port

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def status(self, method, path, host):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.putrequest(method, path, skip_host=True)
            if host is not None:
                conn.putheader("Host", host)
            conn.putheader("Content-Length", "0")
            conn.endheaders()
            r = conn.getresponse()
            r.read()
            return r.status
        finally:
            conn.close()

    def test_own_names_are_served(self):
        for host in (f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"LOCALHOST:{self.port}"):
            self.assertNotEqual(self.status("GET", "/", host), 421, host)

    def test_rebound_name_is_refused_for_reads_and_writes(self):
        for method in ("GET", "HEAD", "POST"):
            self.assertEqual(self.status(method, "/api/stream-all", f"evil.example:{self.port}"), 421, method)

    def test_wrong_port_is_refused(self):  # another local listener's name is not ours either
        self.assertEqual(self.status("GET", "/", "127.0.0.1:1"), 421)

    def test_missing_host_is_allowed(self):  # HTTP/1.0 tooling; a browser always sends Host
        self.assertNotEqual(self.status("GET", "/", None), 421)


if __name__ == "__main__":
    unittest.main()
