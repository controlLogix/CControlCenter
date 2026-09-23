"""Isolated hook/MCP tests. Override external checkout with AGENTMUX_PLUGIN_ROOT."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs


def plugin_root():
    if os.environ.get("AGENTMUX_PLUGIN_ROOT"):
        return Path(os.environ["AGENTMUX_PLUGIN_ROOT"])
    # Directory marketplace registration is the portable source of its location.
    registry = Path.home() / ".claude/plugins/known_marketplaces.json"
    try:
        entry = json.loads(registry.read_text())["adaggroup"]
        path = entry.get("source", {}).get("path") or entry["installLocation"]
        if os.name != "nt" and re.match(r"^[A-Za-z]:[\\/]", path):
            path = "/mnt/" + path[0].lower() + "/" + path[3:].replace("\\", "/")
        return Path(path) / "plugins/agentmux-orchestration"
    except (OSError, ValueError, KeyError):
        return Path(__file__).resolve().parents[2] / "marketplace/plugins/agentmux-orchestration"


PLUGIN = plugin_root()


@unittest.skipUnless(PLUGIN.is_dir(), "external plugin absent; set AGENTMUX_PLUGIN_ROOT")
class PluginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.plugin = cls.root / "installed plugin with spaces"
        shutil.copytree(PLUGIN, cls.plugin)
        cls.shim = cls.plugin / "hooks/agentmux-hook.sh"
        cls.entry = cls.plugin / "bin/agentmux-plugin"
        cls.members = []
        cls.workers = []
        cls.requests = []
        cls.broken = False

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                cls.requests.append(self.path)
                path = urlsplit(self.path)
                query = parse_qs(path.query)
                if cls.broken:
                    self.send_error(503)
                    return
                if path.path == "/api/agents":
                    data = {"agents": cls.workers}
                elif path.path == "/api/board/roster":
                    data = {"id": query["id"][0], "members": cls.members, "count": len(cls.members)}
                elif path.path == "/api/board/agents":
                    data = {"agents": [{"name": query.get("name", ["reviewer"])[0]}], "problems": []}
                else:
                    self.send_error(404)
                    return
                raw = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.env = dict(os.environ, AGENTMUX_DASHBOARD="http://127.0.0.1:%s" % cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def setUp(self):
        type(self).members = []
        type(self).workers = []
        type(self).requests = []
        type(self).broken = False

    def hook(self, value, event="pre-bash", env=None):
        return subprocess.run(["/bin/sh", str(self.shim), event],
            input=json.dumps({"tool_input": value}), text=True, capture_output=True,
            cwd=self.root, env=env or self.env, timeout=10)

    def shell(self, command, **kwargs):
        return self.hook({"command": command}, **kwargs)

    def deny(self, result, reason):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(reason, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_registration_covers_both_harnesses(self):
        hooks = json.loads((self.plugin / "hooks/hooks.json").read_text())["hooks"]["PreToolUse"]
        for tool in ("Bash", "exec_command", "shell_command", "shell", "Edit", "Write", "MultiEdit", "apply_patch"):
            self.assertTrue(any(re.fullmatch(h["matcher"], tool) for h in hooks), tool)
        for gate in hooks:
            self.assertIn("/hooks/agentmux-hook.sh", gate["hooks"][0]["command"])

    def test_irrelevant_bash_exits_before_external_process(self):
        # Empty PATH makes even an accidental dirname/cat/python launch fail.
        env = dict(self.env, PATH=str(self.root / "absent"))
        result = self.shell("git status --short", env=env)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertIn("exit 0", self.shim.read_text().splitlines()[2])
        self.assertEqual(self.requests, [])

    def test_no_roster_refuses_hire(self):
        self.deny(self.shell('python3 "/runtime path/taskmgmt/coordination.py" hire TM-059 --name reviewer'), "approve reviewer")
        self.assertEqual(self.requests, ["/api/board/roster?id=TM-059"])

    def test_only_matching_approved_member_allows_hire(self):
        for status in ("proposed", "rejected", "hired", "finished"):
            type(self).members = [{"agent_name": "reviewer", "status": status}]
            self.deny(self.shell("python3 coordination.py hire TM-059 --name reviewer"), "hire refused")
        type(self).members = [{"agent_name": "other", "status": "approved"}]
        self.deny(self.shell("python3 coordination.py hire TM-059 --name reviewer"), "hire refused")
        type(self).members = [{"agent_name": "reviewer", "status": "approved"}]
        result = self.hook({"cmd": "python3 coordination.py hire TM-059 --name=reviewer"})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_hire_unavailable_fails_closed(self):
        type(self).broken = True
        self.deny(self.shell("python3 coordination.py hire TM-059 --name reviewer"), "503")

    def test_installed_skill_launcher_uses_same_gates(self):
        prefix = 'python3 "/installed plugin/skills/agent-config/scripts/runtime.py" coordination '
        self.deny(self.shell(prefix + "hire TM-059 --name reviewer"), "approve reviewer")
        type(self).workers = [{"name": "worker", "agentdef": "reviewer", "state": "attached"}]
        self.deny(self.shell(prefix + "agentdef repo reviewer"), "live worker worker")

    def test_dynamic_and_multiple_hires_refuse(self):
        for command in ('python3 coordination.py hire "$TASK" --name reviewer',
                        'python3 coordination.py hire TM-059 --name reviewer && python3 coordination.py hire TM-060 --name reviewer'):
            self.assertEqual(self.shell(command).returncode, 2)

    def test_duplicate_name_cannot_check_a_different_member(self):
        type(self).members = [{"agent_name": "reviewer", "status": "approved"}]
        self.deny(self.shell("python3 coordination.py hire TM-059 --name reviewer --name=unapproved"), "exactly one")

    def test_live_definition_cli_writes_refuse(self):
        for state in ("attached", "detached"):
            type(self).workers = [{"name": "tm-059-reviewer", "agentdef": "reviewer", "state": state}]
            for verb in ("agentdef", "agentdrop"):
                self.deny(self.shell(f"python3 coordination.py {verb} repo reviewer"), "live worker tm-059-reviewer")

    def test_stale_and_unrelated_workers_allow_edit(self):
        type(self).workers = [{"name": "old", "agentdef": "reviewer", "state": "stale"},
                              {"name": "other", "agentdef": "builder", "state": "attached"}]
        self.assertEqual(self.shell("python3 coordination.py agentdef global reviewer").returncode, 0)

    def test_direct_file_and_patch_edits_refuse(self):
        type(self).workers = [{"name": "worker", "agentdef": "reviewer", "state": "detached"}]
        values = [{"file_path": "/repo/.agentmux/agents/reviewer.md"},
                  {"path": ".claude/agents/reviewer.md"},
                  "*** Begin Patch\n*** Update File: .agentmux/agents/reviewer.md\n@@\n-old\n+new\n*** End Patch",
                  {"patch": "*** Begin Patch\n*** Update File: unrelated.md\n*** Move to: .agentmux/agents/reviewer.md\n*** End Patch"}]
        for value in values:
            self.deny(self.hook(value, "pre-edit"), "live worker worker")
        self.deny(self.shell("rm '/a path/.agentmux/agents/reviewer.md'"), "live worker worker")

    def test_edit_service_failure_refuses_but_unrelated_edit_passes(self):
        type(self).broken = True
        self.deny(self.hook({"file_path": ".agentmux/agents/reviewer.md"}, "pre-edit"), "503")
        self.assertEqual(self.hook({"file_path": "app.py"}, "pre-edit").returncode, 0)

    def test_raw_api_mutations_refuse(self):
        for endpoint in ("hire", "agentdef", "agentdrop"):
            self.deny(self.shell(f"curl -X POST http://localhost/api/board/{endpoint}"), "use coordination.py")

    def exchange(self, messages, env=None):
        config = json.loads((self.plugin / ".mcp.json").read_text())["mcpServers"]["agentmux-roster"]
        argv = [config["command"], *[arg.replace("${CLAUDE_PLUGIN_ROOT}", str(self.plugin)) for arg in config["args"]]]
        result = subprocess.run(argv, input="".join(json.dumps(msg) + "\n" for msg in messages),
            capture_output=True, text=True, env=env or self.env, timeout=10, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return [json.loads(line) for line in result.stdout.splitlines()]

    def test_mcp_discovery_without_user_config_or_dashboard(self):
        env = dict(os.environ, HOME=str(self.root), AGENTMUX_HOME=str(self.root))
        env.pop("AGENTMUX_DASHBOARD", None)
        replies = self.exchange([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}], env)
        self.assertEqual(len(replies), 2)
        self.assertEqual(replies[0]["result"]["protocolVersion"], "2024-11-05")
        self.assertEqual({t["name"] for t in replies[1]["result"]["tools"]}, {"agent_roster", "team_roster"})
        self.assertEqual(self.requests, [])

    def test_mcp_roster_reads_correct_endpoints(self):
        messages = [{"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": args}}
                    for i, (name, args) in enumerate([("agent_roster", {}), ("agent_roster", {"name": "reviewer"}), ("team_roster", {"id": "TM-059"})])]
        replies = self.exchange(messages)
        self.assertTrue(all("isError" not in r["result"] for r in replies))
        self.assertEqual(self.requests, ["/api/board/agents", "/api/board/agents?name=reviewer", "/api/board/roster?id=TM-059"])

    def test_mcp_errors_do_not_kill_server(self):
        type(self).broken = True
        replies = self.exchange([
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "agent_roster"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "team_roster", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "unknown"}},
            {"jsonrpc": "2.0", "id": 4, "method": "unknown"},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/list", "params": []},
            {"jsonrpc": "2.0", "id": 6, "method": "ping"}])
        self.assertTrue(replies[0]["result"]["isError"])
        self.assertTrue(replies[1]["result"]["isError"])
        self.assertEqual([r["error"]["code"] for r in replies[2:5]], [-32602, -32601, -32602])
        self.assertEqual(replies[5]["result"], {})


if __name__ == "__main__":
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(PluginTests))
    failed = len(result.failures) + len(result.errors)
    print(f"passed {result.testsRun - failed - len(result.skipped)}, failed {failed}")
    sys.exit(bool(failed))
