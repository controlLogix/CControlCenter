"""Additional behavior checks for the maintained hook and roster MCP gateway."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.parse import urlsplit

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "lib"))
import gateway


class HookAndMCP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                cls.requests.append(self.path)
                if cls.delay:
                    time.sleep(cls.delay)
                data = ({"id": "TM-059", "members": cls.members}
                        if urlsplit(self.path).path == "/api/board/roster" else {"agents": cls.workers})
                raw = cls.raw if cls.raw is not None else json.dumps(data).encode()
                self.send_response(cls.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(cls.length if cls.length is not None else len(raw)))
                if cls.status == 302:
                    self.send_header("Location", "/redirected")
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    pass
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        cls = type(self)
        cls.members = [{"agent_name": "reviewer", "status": "approved"}]
        cls.workers = [{"name": "worker", "agentdef": "reviewer", "state": "attached"}]
        cls.requests = []
        cls.raw = None
        cls.length = None
        cls.status = 200
        cls.delay = 0
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {**os.environ, "HOME": str(self.root), "AGENTMUX_HOME": str(self.root / ".agentmux"),
                    "AGENTMUX_DASHBOARD": "http://127.0.0.1:" + str(self.server.server_port)}

    def hook(self, value, mode="pre-bash", raw=False):
        data = value if raw else json.dumps({"tool_input": value}).encode()
        return subprocess.run(["/bin/sh", str(PLUGIN / "hooks/agentmux-hook.sh"), mode], input=data,
                              cwd=self.root, env=self.env, capture_output=True, timeout=8)

    def deny(self, result, phrase=None):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, b"")
        if phrase:
            self.assertIn(phrase.encode(), result.stderr)

    def test_supported_json_hire_and_unique_approval(self):
        command = 'python3 "runtime path/coordination.py" hire TM-059 --name "reviewer" --json'
        self.assertEqual(self.hook({"command": command}).returncode, 0)
        type(self).members *= 2
        self.deny(self.hook({"command": command}), "approve reviewer")

    def test_ambiguous_mutations_never_execute_command_text(self):
        for command in ["python3 coordination.py hire $(touch sentinel) --name reviewer",
                        "python3 coordination.py hire `touch sentinel` --name reviewer",
                        "python3 coordination.py hire TM-059 --name reviewer; touch sentinel",
                        "python3 coordination.py hire TM-059 --name reviewer | cat",
                        "env OTHER=value python3 coordination.py hire TM-059 --name reviewer",
                        "python3 coordination.py hire TM-059 --name reviewer --cli shell",
                        "python3 coordination.py hire TM-059 --name reviewer --name reviewer"]:
            with self.subTest(command=command):
                self.deny(self.hook({"command": command}))
        self.assertFalse((self.root / "sentinel").exists())

    def test_raw_encoded_http_and_escaped_json_hire_are_checked(self):
        self.deny(self.hook({"command": "curl -X POST http://localhost/api/board/%68ire"}), "use coordination.py")
        type(self).members = []
        raw = b'{"tool_input":{"command":"python3 coordin\\u0061tion.py h\\u0069re TM-059 --name reviewer"}}'
        self.deny(self.hook(raw, raw=True), "approve reviewer")

    def test_relevant_bad_json_duplicate_keys_newlines_and_large_input_refuse(self):
        metadata = {"session_id": "fixture", "cwd": "/tmp/agentmux-project",
                    "transcript_path": "/tmp/agentmux-session.jsonl",
                    "hook_event_name": "PreToolUse", "tool_name": "Bash"}
        for frame in [dict(metadata, tool_input={"command": "pwd"}),
                      dict(tool_input={"command": "pwd"}, **metadata)]:
            with patch.dict(self.env, {"PATH": ""}):
                result = self.hook(json.dumps(frame).encode(), raw=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, b"")
        type(self).members = []
        for command in ["python3 coordination.py hire TM-059 --name reviewer",
                        "rm .agentmux/agents/reviewer.md"]:
            self.deny(self.hook(json.dumps(dict(metadata, tool_input={"command": command})).encode(), raw=True))
        fake = dict(metadata, cwd='agentmux/"tool_input":{"command":"pwd"}',
                    tool_input={"command": "rm .agentmux/agents/reviewer.md"})
        self.deny(self.hook(json.dumps(fake).encode(), raw=True), "live worker")
        for raw in [b'{"tool_input":{"command":"hire',
                    b'{"cwd":"agentmux","tool_input":{"command":"pwd","command":"hire"}}',
                    b'{"cwd":"agentmux","tool_input":{"command":"pwd"},"tool_input":{"command":"hire"}}',
                    b'{"cwd":"agentmux","tool_input":{"command":"pwd","comm\\u0061nd":"hire"}}',
                    b'{"cwd":"agentmux","tool_input":{"command":"pwd"},"cwd":"elsewhere"}',
                    b'{"tool_input":{"command":"hire","command":"git status"}}',
                    b'{"tool_input":{"command":"python3 coordination.py hire\nTM-059 --name reviewer"}}',
                    b'{"tool_input":{"command":"hire ' + b'x' * (256 * 1024) + b'"}}']:
            with self.subTest(length=len(raw)):
                self.deny(self.hook(raw, raw=True))

    def test_normalized_symlink_parent_and_option_destinations_are_protected(self):
        directory = self.root / ".agentmux/agents"
        directory.mkdir(parents=True)
        (self.root / "alias").symlink_to(directory, target_is_directory=True)
        for command in ["rm .agentmux/agents/../agents/reviewer.md", "rm alias/reviewer.md",
                        "rm -rf .", "cp input.md --target-directory=.agentmux/agents",
                        "mv input.md -t.agentmux/agents"]:
            with self.subTest(command=command):
                self.deny(self.hook({"command": command}), "live worker worker")
        self.deny(self.hook({"path": str(self.root / "alias/reviewer.md")}, "pre-edit"), "live worker worker")

    def test_literal_read_is_allowed_but_redirected_read_is_not(self):
        self.assertEqual(self.hook({"command": "cat .agentmux/agents/reviewer.md"}).returncode, 0)
        self.assertEqual(self.requests, [])
        self.deny(self.hook({"command": "cat source.md > .agentmux/agents/reviewer.md"}), "ambiguous shell mutation")

    def test_multi_edit_and_patch_move_protect_all_destinations(self):
        self.deny(self.hook({"edits": [{"path": "ordinary.py"}, {"path": ".claude/agents/reviewer.md"}]}, "pre-edit"), "live worker")
        self.deny(self.hook({"patch": "*** Begin Patch\n*** Add File: ordinary.md\n*** Move to: .agentmux/agents/reviewer.md\n*** End Patch"}, "pre-edit"), "live worker")
        self.deny(self.hook({"patch": "unknown patch format"}, "pre-edit"), "unsupported patch")
        self.assertEqual(self.hook({"path": "ordinary.py"}, "pre-edit").returncode, 0)

    def test_bad_worker_or_roster_response_fails_closed(self):
        type(self).raw = b'{"agents": null}'
        self.deny(self.hook({"path": ".agentmux/agents/reviewer.md"}, "pre-edit"), "invalid agents")
        type(self).raw = b'{"id":"TM-060","members":[{"agent_name":"reviewer","status":"approved"}]}'
        self.deny(self.hook({"command": "python3 coordination.py hire TM-059 --name reviewer"}), "does not match")

    def exchange(self, raw):
        result = subprocess.run([sys.executable, str(PLUGIN / "bin/agentmux-plugin"), "mcp"],
                                input=raw, env=self.env, capture_output=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b"")
        return [json.loads(line) for line in result.stdout.splitlines()]

    def frames(self, *messages):
        return b"".join(json.dumps(message).encode() + b"\n" for message in messages)

    def request(self, identity, method, params=None):
        return {"jsonrpc": "2.0", "id": identity, "method": method, "params": params or {}}

    def test_bad_frames_and_oversized_frame_do_not_end_session(self):
        raw = b'{bad\n' + b'\xff\n' + b'x' * (64 * 1024 + 100) + b'\n' + b'{"jsonrpc":"2.0","id":NaN}\n'
        raw += self.frames(self.request(9, "ping"))
        replies = self.exchange(raw)
        self.assertEqual([r["error"]["code"] for r in replies[:-1]], [-32700] * 4)
        self.assertEqual(replies[-1]["result"], {})

    def test_notifications_discovery_and_invalid_arguments(self):
        replies = self.exchange(self.frames(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "agent_roster"}},
            self.request(1, "initialize", {"protocolVersion": "2024-11-05"}),
            self.request(2, "tools/list"),
            self.request(3, "tools/call", {"name": "agent_roster", "arguments": {"name": []}}),
            self.request(4, "tools/call", {"name": "agent_roster", "arguments": {"secret": "x"}}),
            self.request(5, "ping")))
        self.assertEqual(len(replies), 5)
        self.assertEqual(self.requests, [])
        self.assertEqual([r["error"]["code"] for r in replies[2:4]], [-32602, -32602])
        self.assertEqual(replies[-1]["result"], {})

    def test_query_encoding_prevents_injected_parameters(self):
        value = "reviewer & secret=do-not-add"
        replies = self.exchange(self.frames(self.request(1, "tools/call", {"name": "agent_roster", "arguments": {"name": value}})))
        self.assertNotIn("isError", replies[0]["result"])
        self.assertEqual(self.requests, ["/api/board/agents?name=reviewer+%26+secret%3Ddo-not-add"])

    def test_http_failure_redirect_size_and_json_errors_preserve_service(self):
        for status, raw, length in [(503, b'{}', None), (302, b'{}', None), (200, b'not json', None),
                                    (200, b'{}', 600000), (200, b'{}', 20)]:
            with self.subTest(status=status, raw=raw, length=length):
                type(self).status, type(self).raw, type(self).length = status, raw, length
                replies = self.exchange(self.frames(self.request(1, "tools/call", {"name": "agent_roster"}), self.request(2, "ping")))
                self.assertTrue(replies[0]["result"]["isError"])
                self.assertEqual(replies[1]["result"], {})
        self.assertNotIn("/redirected", self.requests)

    def test_lookup_timeout_is_a_service_error(self):
        type(self).delay = 0.2
        with patch.dict(os.environ, self.env), patch.object(gateway, "TIMEOUT", 0.05):
            with self.assertRaises(gateway.Refused):
                gateway.read("/api/agents")


if __name__ == "__main__":
    unittest.main()
