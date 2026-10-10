"""Scoped Windows callback regression checks; no provider prompts or live config."""
import os
import asyncio
import tempfile
import subprocess
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch, AsyncMock, Mock

from agentmux_windows import command, environment, validate_callback
from hub import cli
from hub import server
from hub.store import HubError


class CallbackSelection(unittest.TestCase):
    def context(self):
        return {"AGENTMUX_WINDOWS_CALLBACK": "1", "AGENTMUX_HUB_URL": "tcp://127.0.0.1:43210",
                "AGENTMUX_HUB_TOKEN_FILE": "/tmp/private/token",
                "AGENTMUX_WSL_DISTRO": "Ubuntu-26.04", "AGENTMUX_WSL_BIN": "/tmp/private/agentmux",
                "AGENTMUX_HOME": "/tmp/private"}

    def test_missing_selection_never_launches(self):
        from agentmux_windows import main
        for key in ("AGENTMUX_WSL_DISTRO", "AGENTMUX_WSL_BIN", "AGENTMUX_HOME"):
            for value in (None, "", "relative" if key != "AGENTMUX_WSL_DISTRO" else "-bad"):
                env = self.context()
                if value is None:
                    env.pop(key)
                else:
                    env[key] = value
                with self.subTest(key=key, value=value), patch.dict(os.environ, env, clear=True), \
                        patch("sys.argv", ["agentmux_windows.py", "hub", "whoami"]), \
                        patch("agentmux_windows.subprocess.call") as run:
                    self.assertEqual(main(), 2)
                    run.assert_not_called()

    def test_shell_callback_rejection_creates_no_default_or_scoped_state(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            for missing_home in (True, False):
                env = {**os.environ, **self.context(), "HOME": str(home),
                       "AGENTMUX_HOME": str(Path(tmp) / "scoped"), "PYTHONDONTWRITEBYTECODE": "1"}
                if missing_home:
                    env.pop("AGENTMUX_HOME")
                result = subprocess.run(["bash", str(root / "agentmux.sh"), "hub", "start"],
                                        env=env, capture_output=True, text=True, timeout=10)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                expected = ("Windows agent callbacks need an explicit absolute AGENTMUX_HOME" if missing_home
                            else "This operation is not available through an agent callback")
                self.assertIn(expected, result.stderr)
                self.assertFalse((home / ".agentmux").exists())
                self.assertFalse((Path(tmp) / "scoped").exists())

    def test_shell_without_callback_keeps_native_hub_entrypoint(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp:
            env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTMUX_")}
            env.update(HOME=tmp, AGENTMUX_HOME=str(Path(tmp) / "private"), PYTHONDONTWRITEBYTECODE="1")
            result = subprocess.run(["bash", str(root / "agentmux.sh"), "hub", "--help"],
                                    env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("usage: agentmux hub", result.stdout)
            env["AGENTMUX_WINDOWS_CALLBACK"] = ""
            result = subprocess.run(["bash", str(root / "agentmux.sh"), "hub", "start"],
                                    env=env, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("AGENTMUX_WINDOWS_CALLBACK must be 1 when set", result.stderr)

    def test_nick_defaults_and_exact_received_arguments(self):
        args = ["ask", "worker", "", "a!b", "x y", "quote\"", "C:\\a\\b", "a\nb", "雪"]
        self.assertEqual(command(args, {}), ["wsl.exe", "--distribution", "Ubuntu", "--exec",
                                           "/home/nick/.local/bin/agentmux", *args])

    def test_explicit_selection(self):
        self.assertEqual(command(["hub", "whoami"], {
            **self.context(), "AGENTMUX_WSL_DISTRO": "Ubuntu-26.04",
            "AGENTMUX_WSL_BIN": "/tmp/private harness", "AGENTMUX_WSL_CWD": "/tmp/private project"}),
            ["wsl.exe", "--distribution", "Ubuntu-26.04", "--cd", "/tmp/private project",
             "--exec", "/tmp/private harness", "hub", "whoami"])
        for key in ("AGENTMUX_WSL_DISTRO", "AGENTMUX_WSL_BIN", "AGENTMUX_WSL_CWD"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                command([], {key: ""})

    def test_no_fallback_or_inline_token(self):
        for change in ({"AGENTMUX_HUB_URL": ""}, {"AGENTMUX_HUB_URL": "unix:///tmp/x"},
                       {"AGENTMUX_HUB_URL": "tcp://remote:22"}, {"AGENTMUX_HUB_URL": "tcp://127.0.0.1:0"},
                       {"AGENTMUX_HUB_TOKEN_FILE": ""}, {"AGENTMUX_HUB_TOKEN": "operator"},
                       {"AGENTMUX_WINDOWS_CALLBACK": "0"}):
            with self.subTest(change=change), patch.dict(os.environ, {**self.context(), **change}, clear=True):
                with patch.object(cli.socket, "socket") as unix, patch.object(cli.socket, "create_connection") as tcp:
                    with self.assertRaises(cli.Fail):
                        cli.connect(1)
                    unix.assert_not_called()
                    tcp.assert_not_called()

    def test_lifecycle_rejected_before_local_action(self):
        with patch.dict(os.environ, self.context(), clear=True), patch.object(cli.subprocess, "Popen") as launch:
            for verb in ("start", "stop", "fed", "mcp", "spawn", "kill"):
                with self.subTest(verb=verb), self.assertRaises(cli.Fail):
                    cli.main([verb])
            with self.assertRaises(cli.Fail):
                cli.start()
            launch.assert_not_called()
        with self.assertRaises(ValueError):
            command(["spawn", "worker"], self.context())

    def test_context_only_and_unrelated_wslenv_preserved(self):
        env = {**self.context(), "WSLENV": "KEEP/p:AGENTMUX_HUB_TOKEN_FILE/pw",
               "HOME": "unchanged", "SECRET": "not exported"}
        result = environment(env)
        self.assertEqual(result["HOME"], env["HOME"])
        self.assertIn("KEEP/p", result["WSLENV"].split(":"))
        self.assertIn("AGENTMUX_HUB_TOKEN_FILE/pu", result["WSLENV"].split(":"))
        self.assertNotIn("SECRET", result["WSLENV"])
        self.assertEqual(environment({"WSLENV": "KEEP/p"}), {"WSLENV": "KEEP/p"})


class SpawnContext(unittest.TestCase):
    def test_bad_opt_in_has_no_registration_side_effect(self):
        stub = SimpleNamespace(cfg={"tcp_port": 43210}, db=AsyncMock())
        for env, port in [({"AGENTMUX_WINDOWS_CALLBACKS": "0"}, 43210),
                          ({"AGENTMUX_WINDOWS_CALLBACKS": ""}, 43210),
                          ({"AGENTMUX_WINDOWS_CALLBACKS": "1"}, 43210),
                          ({"AGENTMUX_WINDOWS_CALLBACKS": "1", "AGENTMUX_WSL_DISTRO": "Ubuntu"}, "bad")]:
            stub.cfg["tcp_port"] = port
            with self.subTest(env=env, port=port), patch.dict(os.environ, env, clear=True):
                with self.assertRaises(HubError):
                    asyncio.run(server.Hub.spawn(stub, {}))
            stub.db.assert_not_called()

    def capture_spawn(self, root, env, agent):
        stub = SimpleNamespace(cfg={"tcp_port": 43210}, io=None,
                               store=SimpleNamespace(q=Mock(), register=Mock(), set_state=Mock()),
                               resolve_role=lambda *a: {}, db=AsyncMock(side_effect=[
                                   [{"path": root}], "alpha-worker-" + agent, None]))
        with patch.dict(os.environ, env, clear=True), patch.object(server, "ROOT", root), \
                patch.object(server.subprocess, "run", return_value=SimpleNamespace(returncode=1, stdout="", stderr="bounded stop")) as run:
            with self.assertRaisesRegex(HubError, "spawn failed"):
                asyncio.run(server.Hub.spawn(stub, {"repo": "alpha", "role": "worker", "agent": agent, "cli": "shell"}))
            return run.call_args.kwargs["env"]

    def test_two_spawns_get_distinct_token_paths_without_inline_tokens(self):
        with tempfile.TemporaryDirectory() as root:
            env = {"AGENTMUX_WINDOWS_CALLBACKS": "1", "AGENTMUX_WSL_DISTRO": "Ubuntu-26.04",
                   "AGENTMUX_HUB_TOKEN": "inherited-operator-token", "AGENTMUX_HUB_TOKEN_FILE": "/wrong/token"}
            first = self.capture_spawn(root, env, "one")
            second = self.capture_spawn(root, env, "two")
            self.assertNotEqual(first["AGENTMUX_HUB_TOKEN_FILE"], second["AGENTMUX_HUB_TOKEN_FILE"])
            for actual in (first, second):
                self.assertEqual(actual["AGENTMUX_SPAWN_WINDOWS_CALLBACK"], "1")
                self.assertNotIn("AGENTMUX_WINDOWS_CALLBACK", actual)
                self.assertEqual(actual["AGENTMUX_HUB_URL"], "tcp://127.0.0.1:43210")
                self.assertNotIn("AGENTMUX_HUB_TOKEN", actual)
                self.assertNotIn("AGENTMUX_AGENT", actual)

    def test_native_spawn_drops_stale_worker_but_preserves_explicit_native_context(self):
        with tempfile.TemporaryDirectory() as root:
            env = {"AGENTMUX_WINDOWS_CALLBACK": "1", "AGENTMUX_HUB_TOKEN_FILE": "/worker/token",
                   "AGENTMUX_HUB_URL": "tcp://127.0.0.1:43210", "AGENTMUX_WSL_BIN": "/worker/bin"}
            actual = self.capture_spawn(root, env, "one")
            self.assertFalse(set(env) & set(actual))
            env.pop("AGENTMUX_WINDOWS_CALLBACK")
            actual = self.capture_spawn(root, env, "two")
            for key, value in env.items():
                self.assertEqual(actual[key], value)


if __name__ == "__main__":
    unittest.main()
