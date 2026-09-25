"""The field sidecar's HTTP shell: the secret, the bind, and what it refuses.

These assert the properties the write route inherits: the secret is checked
before a body is read, the bind is loopback, and the surface offers no way to
name a raw CIP service. If the shell is wrong, every protocol call through it is
wrong - which is why these came first and the write route came second.

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
        # In memory and per-server, exactly as main() wires it: a ticket that
        # outlived the process would be an authorisation nobody is still at the
        # desk for.
        self.server.tickets = field_app.tickets.TicketStore()
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    def request(self, method, path, headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            headers = dict(headers or {})
            payload = None
            if body is not None:
                payload = json.dumps(body).encode("utf-8")
                headers.setdefault("Content-Type", "application/json")
                headers["Content-Length"] = str(len(payload))
            conn.request(method, path, body=payload, headers=headers)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def json(self, method, path, headers=None, body=None):
        status, raw = self.request(method, path, headers, body)
        try:
            return status, json.loads(raw)
        except ValueError:
            return status, {"raw": raw.decode("utf-8", "replace")}


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


class WriteSurface(unittest.TestCase):
    """There is exactly one way in, and it cannot say what to write."""

    def test_an_invented_write_route_does_not_exist(self):
        with Sidecar() as s:
            status, body = s.json("POST", "/field/enip/write", AUTH, {"value": 1})
            self.assertEqual(status, 404)
            self.assertIn("no such route", body["error"])

    def test_post_without_the_key_is_401_before_any_route_is_considered(self):
        """Authorization is checked before anything else, including the path."""
        with Sidecar() as s:
            status, _ = s.request("POST", "/rockwell/write")
            self.assertEqual(status, 401)
            # And for a path that does not exist either, so a caller with no key
            # cannot map the surface by watching which paths answer differently.
            status, _ = s.request("POST", "/field/enip/write")
            self.assertEqual(status, 401)

    def test_the_write_route_refuses_a_request_that_states_the_write(self):
        """The target and the value live on the ticket. There is no way to
        supply them here, and an attempt is refused rather than ignored -
        ignoring it would let a caller believe it had specified something."""
        with Sidecar() as s:
            for field, value in (("tag", "CartonCount"), ("value", 7),
                                 ("path", "10.1.2.3/bp/1"), ("kind", "write_tag")):
                with self.subTest(field=field):
                    status, body = s.json("POST", "/rockwell/write", AUTH, {
                        "ticket_id": "x" * 32, "actor": "operator", "confirm": True,
                        field: value})
                    self.assertEqual(status, 400)
                    self.assertIn(field, body["error"])
                    self.assertIn("on the ticket", body["error"])

    def test_the_write_route_needs_an_actor_and_a_confirmation(self):
        with Sidecar() as s:
            status, body = s.json("POST", "/rockwell/write", AUTH,
                                  {"ticket_id": "x" * 32, "confirm": True})
            self.assertEqual(status, 400)
            self.assertIn("actor", body["error"])
            status, body = s.json("POST", "/rockwell/write", AUTH,
                                  {"ticket_id": "x" * 32, "actor": "operator"})
            self.assertEqual(status, 400)
            self.assertIn("confirm", body["error"])

    def test_the_body_guards_match_the_dashboard(self):
        """Same shape as read_cc_body: a write route is the last place to relax."""
        with Sidecar() as s:
            status, _ = s.request("POST", "/rockwell/ticket", AUTH, body=None)
            self.assertEqual(status, 415, "no content type should be refused")
            status, body = s.json("POST", "/rockwell/ticket",
                                  dict(AUTH, **{"Content-Type": "application/json"}),
                                  body=["not", "an", "object"])
            self.assertEqual(status, 400)
            self.assertIn("JSON object", body["error"])

    def test_minting_validates_before_it_authorises_anything(self):
        with Sidecar() as s:
            base = {"kind": "write_tag", "path": "10.1.2.3/bp/1",
                    "tag": "CartonCount", "value": 7}
            for missing in ("kind", "path", "tag", "value"):
                with self.subTest(missing=missing):
                    body = {k: v for k, v in base.items() if k != missing}
                    status, _ = s.json("POST", "/rockwell/ticket", AUTH, body)
                    self.assertEqual(status, 400)
            status, _ = s.json("POST", "/rockwell/ticket", AUTH,
                               dict(base, kind="generic_message"))
            self.assertEqual(status, 400, "an arbitrary CIP service must not be mintable")

    def test_a_minted_ticket_carries_the_write_and_is_not_the_write(self):
        with Sidecar() as s:
            status, body = s.json("POST", "/rockwell/ticket", AUTH, {
                "kind": "write_tag", "path": "10.1.2.3/bp/1",
                "tag": "CartonCount", "value": 7})
            self.assertEqual(status, 201)
            self.assertEqual(body["action"], {
                "kind": "write_tag", "path": "10.1.2.3/bp/1",
                "tag": "CartonCount", "value": 7})
            self.assertFalse(body["redeemed"])
            self.assertGreater(body["expires_in"], 0)
            # Minting sends nothing anywhere; it only records what was authorised.
            self.assertEqual(s.server.tickets.peek(body["ticket_id"])["action"]["tag"],
                             "CartonCount")

    def test_an_unknown_ticket_is_refused_and_nothing_is_attempted(self):
        with Sidecar() as s:
            status, body = s.json("POST", "/rockwell/write", AUTH, {
                "ticket_id": "0" * 32, "actor": "operator", "confirm": True})
            # 503 when pycomm3 is unavailable on this machine, 409 when it is
            # present and the ticket is simply not real. Either way: not 200,
            # and nothing was written.
            self.assertIn(status, (409, 503))
            self.assertNotEqual(status, 200)

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
