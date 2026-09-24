"""The voice-cli MCP server, driven over real stdio against a stub of Voice CLI's API.

No Voice CLI, no microphone, no network beyond loopback. The stub enforces the same three
guards the app does (loopback Host, no Origin, bearer token), so a request the real app
would refuse fails here too. Runs under Windows python and WSL python3 alike.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "mcp" / "voice_mcp.py"
TOKEN = "t" * 40
STATUS = {"state": "idle", "mode": "ptt", "ptt_key": "rctrl", "device": {"index": 1, "name": "Stub Mic"},
          "target": None, "model": "small.en", "type_text": True, "auto_enter": False}
TOOLS = {"voice_status", "voice_devices", "voice_windows", "voice_lock", "voice_unlock", "voice_mode",
         "voice_listening", "voice_device", "voice_show", "voice_listen"}


class Stub:
    """What the fake app saw, and what its event stream should say next."""
    requests = []
    events = []
    event_delay = 0.2


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _guard(self):
        port = self.server.server_address[1]
        if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return self._reply(403, {"error": "bad Host header"}) or False
        if self.headers.get("Origin") is not None:
            return self._reply(403, {"error": "browser requests are not allowed"}) or False
        if self.headers.get("Authorization") != "Bearer " + TOKEN:
            return self._reply(401, {"error": "missing or wrong bearer token"}) or False
        return True

    def do_GET(self):
        Stub.requests.append(("GET", self.path, None, dict(self.headers)))
        if not self._guard():
            return
        if self.path == "/health":
            self._reply(200, {"ok": True, "app": "voicecli", "version": "1.0.0", **STATUS})
        elif self.path == "/devices":
            self._reply(200, [{"index": 1, "name": "Stub Mic"}])
        elif self.path == "/windows":
            self._reply(200, [{"hwnd": 42, "title": "Claude Code", "process": "WindowsTerminal.exe"}])
        elif self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(f"data: {json.dumps({'type': 'hello', **STATUS})}\n\n".encode())
            self.wfile.flush()
            for ev in Stub.events:
                time.sleep(Stub.event_delay)
                self.wfile.write(b": keepalive\n\n" if ev is None else f"data: {json.dumps(ev)}\n\n".encode())
                self.wfile.flush()
            time.sleep(5)  # hold the stream open, as the app does
        else:
            self._reply(404, {"error": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        Stub.requests.append(("POST", self.path, body, dict(self.headers)))
        if not self._guard():
            return
        if self.headers.get("Content-Type") != "application/json":
            return self._reply(415, {"error": "Content-Type must be application/json"})
        if self.path == "/quit":
            return self._reply(200, {"ok": True})
        if self.path == "/device" and body.get("device") == "missing":
            return self._reply(400, {"error": "no input device like 'missing'"})
        self._reply(200, {"ok": True, **STATUS})


class Client:
    def __init__(self, env):
        self.proc = subprocess.Popen([sys.executable, str(SERVER)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        self.next_id = 0

    def send(self, msg):
        self.proc.stdin.write(json.dumps(msg).encode() + b"\n")
        self.proc.stdin.flush()

    def request(self, method, params=None):
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}})
        return json.loads(self.proc.stdout.readline())

    def call(self, name, args=None):
        reply = self.request("tools/call", {"name": name, "arguments": args or {}})
        result = reply["result"]
        return result["isError"], result["content"][0]["text"]

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=10)
        self.proc.stdout.close()
        self.proc.stderr.close()


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.httpd.daemon_threads = True
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.token_file = Path(cls.tmp.name) / "api-token"
        cls.token_file.write_text(TOKEN, encoding="ascii")
        cls.env = {**os.environ,
                   "APPDATA": cls.tmp.name,  # never the real %APPDATA%\voicecli
                   "VOICECLI_URL": f"http://127.0.0.1:{cls.httpd.server_address[1]}",
                   "VOICECLI_TOKEN_FILE": str(cls.token_file)}
        cls.client = Client(cls.env)
        cls.transcript = []

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        Stub.requests.clear()
        Stub.events = []
        Stub.event_delay = 0.2

    def call(self, name, args=None, client=None):
        is_error, text = (client or self.client).call(name, args)
        self.transcript.append(text)
        return is_error, text

    # protocol

    def test_initialize_echoes_protocol_and_names_server(self):
        reply = self.client.request("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                                   "clientInfo": {"name": "test", "version": "0"}})
        self.assertEqual(reply["result"]["protocolVersion"], "2025-03-26")
        self.assertEqual(reply["result"]["serverInfo"]["name"], "voice-cli")
        self.assertIn("tools", reply["result"]["capabilities"])

    def test_notifications_get_no_reply_and_unknown_methods_are_errors(self):
        self.client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        reply = self.client.request("resources/list")  # the next line read must be THIS reply
        self.assertEqual(reply["id"], self.client.next_id)
        self.assertEqual(reply["error"]["code"], -32601)
        self.assertEqual(self.client.request("ping")["result"], {})

    def test_malformed_json_is_a_parse_error_not_a_crash(self):
        self.client.proc.stdin.write(b"{not json\n")
        self.client.proc.stdin.flush()
        self.assertEqual(json.loads(self.client.proc.stdout.readline())["error"]["code"], -32700)
        self.assertEqual(self.client.request("ping")["result"], {})

    def test_tool_list_is_exact_and_has_no_quit(self):
        tools = self.client.request("tools/list")["result"]["tools"]
        self.assertEqual({t["name"] for t in tools}, TOOLS)
        for t in tools:
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertNotIn("run", t)
        self.assertFalse(any("quit" in t["name"] for t in tools))

    # reads

    def test_status_is_authenticated_loopback_without_origin(self):
        is_error, text = self.call("voice_status")
        self.assertFalse(is_error, text)
        self.assertEqual(json.loads(text)["device"]["name"], "Stub Mic")
        method, path, _, headers = Stub.requests[-1]
        self.assertEqual((method, path), ("GET", "/health"))
        self.assertEqual(headers["Authorization"], "Bearer " + TOKEN)
        self.assertNotIn("Origin", headers)

    def test_devices_and_windows(self):
        self.assertEqual(json.loads(self.call("voice_devices")[1])[0]["name"], "Stub Mic")
        self.assertEqual(json.loads(self.call("voice_windows")[1])[0]["hwnd"], 42)

    # writes

    def test_lock_by_hwnd_by_title_and_unlock(self):
        self.assertFalse(self.call("voice_lock", {"hwnd": 42})[0])
        self.assertFalse(self.call("voice_lock", {"title": "Claude"})[0])
        self.assertFalse(self.call("voice_unlock")[0])
        self.assertEqual([(r[1], r[2]) for r in Stub.requests],
                         [("/target", {"hwnd": 42}), ("/target", {"title": "Claude"}), ("/target", {})])
        self.assertTrue(all(r[3]["Content-Type"] == "application/json" for r in Stub.requests))

    def test_lock_without_a_window_is_refused_before_the_app(self):
        is_error, text = self.call("voice_lock")
        self.assertTrue(is_error)
        self.assertIn("voice_unlock", text)
        self.assertEqual(Stub.requests, [])

    def test_mode_listening_device_show(self):
        self.assertFalse(self.call("voice_mode", {"mode": "open"})[0])
        self.assertFalse(self.call("voice_listening", {"on": False})[0])
        self.assertFalse(self.call("voice_device", {"device": "hyperx"})[0])
        self.assertFalse(self.call("voice_show")[0])
        self.assertEqual([(r[1], r[2]) for r in Stub.requests],
                         [("/mode", {"mode": "open"}), ("/listening", {"on": False}),
                          ("/device", {"device": "hyperx"}), ("/show", {})])

    def test_bad_arguments_never_reach_the_app(self):
        for name, args in (("voice_mode", {"mode": "loud"}), ("voice_mode", {}),
                           ("voice_listening", {"on": "no"}), ("voice_lock", {"hwnd": True}),
                           ("voice_status", {"extra": 1}), ("voice_listen", {"timeout_s": 0}),
                           ("voice_listen", {"timeout_s": 10_000}), ("voice_device", {"device": ""})):
            with self.subTest(name=name, args=args):
                self.assertTrue(self.call(name, args)[0])
        self.assertEqual(Stub.requests, [])
        self.assertTrue(self.call("voice_quit")[0])

    def test_app_error_is_reported_as_its_own_sentence(self):
        is_error, text = self.call("voice_device", {"device": "missing"})
        self.assertTrue(is_error)
        self.assertIn("400", text)
        self.assertIn("no input device like 'missing'", text)

    # listening

    def test_listen_returns_the_next_final_phrase(self):
        Stub.events = [{"type": "speech_start"}, {"type": "partial", "text": "hello"},
                       None, {"type": "final", "text": "hello world", "audio_s": 1.2, "latency_s": 0.4}]
        is_error, text = self.call("voice_listen", {"timeout_s": 10, "partials": True})
        self.assertFalse(is_error, text)
        heard = json.loads(text)
        self.assertEqual((heard["heard"], heard["text"], heard["partials"]), (True, "hello world", ["hello"]))

    def test_listen_times_out_quietly(self):
        started = time.monotonic()
        is_error, text = self.call("voice_listen", {"timeout_s": 1})
        self.assertFalse(is_error, text)
        self.assertFalse(json.loads(text)["heard"])
        self.assertLess(time.monotonic() - started, 5)

    # failures

    def test_missing_token_says_how_to_fix_it(self):
        client = Client({**self.env, "VOICECLI_TOKEN_FILE": str(Path(self.tmp.name) / "absent")})
        try:
            is_error, text = self.call("voice_status", client=client)
        finally:
            client.close()
        self.assertTrue(is_error)
        self.assertIn("No Voice CLI API token", text)
        self.assertEqual(Stub.requests, [])

    def test_wrong_token_is_a_401_with_advice(self):
        wrong = Path(self.tmp.name) / "wrong-token"
        wrong.write_text("w" * 40, encoding="ascii")
        client = Client({**self.env, "VOICECLI_TOKEN_FILE": str(wrong)})
        try:
            is_error, text = self.call("voice_status", client=client)
        finally:
            client.close()
        self.assertTrue(is_error)
        self.assertIn("401", text)
        self.assertIn("restart Voice CLI", text)

    def test_app_not_running(self):
        client = Client({**self.env, "VOICECLI_URL": "http://127.0.0.1:9"})
        try:
            is_error, text = self.call("voice_status", client=client)
        finally:
            client.close()
        self.assertTrue(is_error)
        self.assertIn("not reachable", text)

    def test_zz_token_never_appears_in_any_result(self):
        # Named to run last: it checks every result the other tests produced.
        self.assertTrue(self.transcript)
        for text in self.transcript:
            self.assertNotIn(TOKEN, text)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
    failed = len(result.failures) + len(result.errors)
    print(f"passed {result.testsRun - failed}, failed {failed}")
    sys.exit(bool(failed))
