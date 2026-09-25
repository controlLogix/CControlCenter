"""The field sidecar's HTTP shell: the secret, the bind, and what it refuses.

These assert the properties that are load-bearing BEFORE any write route exists,
because a write route added later inherits whatever posture is already here. If
the shell is wrong, every protocol call through it is wrong.

Nothing here talks to hardware, and nothing here needs a protocol module to be
importable - the shell must come up and SAY what is unavailable rather than dying.
"""
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "field"))
import app as field_app  # noqa: E402


class Sidecar:
    """A real server on an ephemeral port, so two of these can run at once."""

    def __init__(self, key="k" * 64):
        from http.server import ThreadingHTTPServer
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), field_app.Handler)
        self.server.key = key
        self.server.verbose = False
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    def request(self, method, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, headers=headers or {})
            response = conn.getresponse()
            body = response.read()
            return response.status, body
        finally:
            conn.close()


KEY = "k" * 64
AUTH = {"X-AgentMux-Field-Key": KEY}


class SharedSecret(unittest.TestCase):
    def test_no_key_is_refused_with_no_body(self):
        """An unauthenticated caller learns nothing about what is behind this."""
        with Sidecar() as s:
            status, body = s.request("GET", "/health")
            self.assertEqual(status, 401)
            self.assertEqual(body, b"")

    def test_a_wrong_key_is_refused(self):
        with Sidecar() as s:
            status, _ = s.request("GET", "/health", {"X-AgentMux-Field-Key": "x" * 64})
            self.assertEqual(status, 401)

    def test_a_prefix_of_the_key_is_refused(self):
        """compare_digest, not startswith."""
        with Sidecar() as s:
            status, _ = s.request("GET", "/health", {"X-AgentMux-Field-Key": KEY[:-1]})
            self.assertEqual(status, 401)

    def test_the_right_key_is_accepted(self):
        with Sidecar() as s:
            status, body = s.request("GET", "/health", AUTH)
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(body)["ok"])

    def test_an_unknown_route_still_requires_nothing_it_should_not_reveal(self):
        with Sidecar() as s:
            status, _ = s.request("GET", "/does-not-exist", AUTH)
            self.assertEqual(status, 404)


class NoWriteRoutes(unittest.TestCase):
    """Writes arrive with the ticket mechanism, not before it."""

    def test_post_is_refused_even_with_the_key(self):
        with Sidecar() as s:
            status, body = s.request("POST", "/field/enip/write", AUTH)
            self.assertEqual(status, 405)
            self.assertIn("no write routes", json.loads(body)["error"])

    def test_post_without_the_key_is_401_not_405(self):
        """Authorization is checked before anything else, including the method."""
        with Sidecar() as s:
            status, _ = s.request("POST", "/field/enip/write")
            self.assertEqual(status, 401)

    def test_there_is_no_raw_cip_route(self):
        """The ABSENCE of a generic-message passthrough is the audit boundary.

        A capability wrapper around pycomm3 is defence in depth - Python has no
        private, and a determined caller reaches the driver anyway. What actually
        holds is that the HTTP surface offers no way to name a CIP service, class,
        instance or attribute. This asserts that stays true.

        It inspects CODE, not the file text. The first version grepped the whole
        source and tripped on the docstring that explains this very rule - a test
        that cannot tell an implementation from a comment about the implementation
        is not asserting what it claims to.
        """
        import ast
        tree = ast.parse(Path(field_app.__file__).read_text(encoding="utf-8"))

        # Docstrings are prose and are exempt; every other string constant is not.
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc is not None:
                    docstrings.add(doc)

        surface = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value not in docstrings:
                    surface.append(node.value)
            elif isinstance(node, ast.Attribute):
                surface.append(node.attr)
            elif isinstance(node, ast.Name):
                surface.append(node.id)

        for forbidden in ("generic_message", "raw_cip", "service_code"):
            # Name the offending items, not the whole haystack: a failure that
            # prints three kilobytes of identifiers tells you something broke and
            # not what.
            hits = sorted({item for item in surface if forbidden in item.lower()})
            self.assertEqual(hits, [],
                             f"{forbidden} is reachable in the sidecar shell via "
                             f"{hits} - that reopens the unaudited write path")


class Health(unittest.TestCase):
    def test_health_reports_which_protocols_loaded_and_why_any_did_not(self):
        with Sidecar() as s:
            _, body = s.request("GET", "/health", AUTH)
            payload = json.loads(body)
            self.assertIn("protocols", payload)
            self.assertIn("protocol_errors", payload)
            # The stdlib-only modules must always be importable; if one is not,
            # that is a real breakage rather than a missing optional wheel.
            for required in ("enip", "logix", "ads", "mqtt", "modbus_poll"):
                self.assertIn(required, payload["protocols"],
                              f"{required} failed to import: "
                              f"{payload['protocol_errors'].get(required)}")

    def test_health_names_the_bind_it_is_actually_on(self):
        with Sidecar() as s:
            _, body = s.request("GET", "/health", AUTH)
            self.assertEqual(json.loads(body)["bind"], "127.0.0.1")


class LoopbackOnly(unittest.TestCase):
    """The bind is asserted, not assumed."""

    def test_a_non_loopback_bind_is_refused(self):
        for host in ("0.0.0.0", "192.168.1.10", "::"):
            with self.subTest(host=host):
                with self.assertRaises(SystemExit) as caught:
                    field_app.assert_loopback((host, 8788))
                self.assertIn("refusing to bind", str(caught.exception))

    def test_loopback_is_allowed(self):
        field_app.assert_loopback(("127.0.0.1", 8788))
        field_app.assert_loopback(("::1", 8788))


class KeyFile(unittest.TestCase):
    def test_a_minted_key_is_owner_only_and_long_enough(self):
        with tempfile.TemporaryDirectory() as temp:
            previous = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = temp
            try:
                key = field_app.load_key(create=True)
                self.assertGreaterEqual(len(key), 64)
                path = field_app.key_path()
                self.assertTrue(path.is_file())
                if os.name != "nt":
                    # Windows does not carry POSIX modes; the check is meaningful
                    # where it is meaningful.
                    self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
                # Reading it back must not mint a second one.
                self.assertEqual(field_app.load_key(), key)
            finally:
                if previous is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = previous


if __name__ == "__main__":
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    failures = len(result.failures) + len(result.errors)
    for case, reason in result.skipped:
        print(f"SKIP {case} - {reason}")
    print(f"passed {result.testsRun - failures - len(result.skipped)}, "
          f"failed {failures}")
    sys.exit(bool(failures))
