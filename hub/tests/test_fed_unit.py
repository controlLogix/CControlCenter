"""EP-032 unit tests: every guard filter on its own, config round trip, envelopes,
the MCP protocol surface and the privileged-tool hook. No NATS, no hub process.

  python3 -m unittest hub.tests.test_fed_unit -v
"""
import io
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from hub.fed import config, envelope, guard, redact  # noqa: E402
from hub.fed.hooks import privileged_gate  # noqa: E402
from hub.fed.policy import Policy, normalize_remote, rid_for_remote  # noqa: E402

REMOTE = "git@github.com:Adag/Falcon.git"


def policy(me="nick", repos=None, peers=None):
    cfg = {"federation": {**config.DEFAULTS, "peer": me}, "repos": repos if repos is not None else {"falcon": {"peers": ["*"]}},
           "peers": peers or {"alice": {"trust": "auto"}, "bob": {"trust": "flag"}, "eve": {"trust": "deny"}}}
    return Policy(cfg, {"falcon": normalize_remote(REMOTE)})


class Identity(unittest.TestCase):
    def test_same_repo_same_rid_whatever_the_url_spelling(self):
        spellings = ["git@github.com:Adag/Falcon.git", "https://github.com/adag/falcon", "ssh://git@github.com/Adag/Falcon.git",
                     "https://user@github.com/Adag/Falcon.git/"]
        self.assertEqual(len({rid_for_remote(s) for s in spellings}), 1)
        self.assertRegex(rid_for_remote(REMOTE), r"^r[0-9a-f]{12}$")

    def test_local_names_differ_rid_does_not(self):
        a, b = policy(), Policy({"federation": {"peer": "alice"}, "repos": {"falcon_fork": {}}, "peers": {}},
                                {"falcon_fork": normalize_remote("https://github.com/adag/falcon.git")})
        self.assertEqual(a.rid_of("falcon"), b.rid_of("falcon_fork"))
        self.assertEqual(b.local_of(a.rid_of("falcon")), "falcon_fork")

    def test_unshared_and_unmatched(self):
        p = Policy({"federation": {"peer": "n"}, "repos": {"nogit": {}}, "peers": {}}, {})
        self.assertEqual(p.shared(), {})
        self.assertEqual(p.unmatched(), ["nogit"])


class Redaction(unittest.TestCase):
    def test_redacts_known_tokens_and_keeps_the_rest(self):
        text = ("key AKIAABCDEFGHIJKLMNOP gh ghp_" + "a" * 36 + " sk-ant-api03-" + "b" * 30 +
                "\nDB_PASSWORD=supersecret1\nnormal text")
        out, kinds = redact.scrub({"body": text, "n": 3, "list": ["xoxb-1234567890-abc"]})
        self.assertNotIn("AKIA", out["body"])
        self.assertNotIn("supersecret1", out["body"])
        self.assertIn("DB_PASSWORD=[REDACTED:assignment]", out["body"])
        self.assertIn("normal text", out["body"])
        self.assertEqual(out["n"], 3)
        self.assertIn("[REDACTED:slack_token]", out["list"][0])
        self.assertTrue({"aws_access_key", "github_token", "anthropic_key", "assignment", "slack_token"} <= set(kinds))

    def test_blocks_private_keys_and_seeds(self):
        for bad in ("-----BEGIN RSA PRIVATE KEY-----\nx", "SUAM" + "A" * 54, "-----BEGIN NATS USER JWT-----"):
            with self.assertRaises(redact.Blocked):
                redact.scrub({"body": bad})

    def test_clean_payload_is_untouched(self):
        d = {"title": "Parser rejects BOM", "body": "strip \\ufeff first", "tags": ["parser"]}
        self.assertEqual(redact.scrub(d), (d, []))


class Outbound(unittest.TestCase):
    def env(self, data=None, rid=None):
        return envelope.make("message", "nick", "mac", rid, "alice", data or {"body": "hi"})

    def test_scope(self):
        p = policy(repos={"falcon": {"peers": ["alice"]}})
        guard.outbound(p, self.env(rid=p.rid_of("falcon")), "falcon", "alice")
        with self.assertRaises(guard.Refused) as e:
            guard.outbound(p, self.env(), "falcon", "bob")
        self.assertEqual(e.exception.decision, "not_shared")
        with self.assertRaises(guard.Refused):
            guard.outbound(p, self.env(), "other_repo", "alice")

    def test_redact_block_and_size(self):
        p = policy()
        clean, kinds = guard.outbound(p, self.env({"body": "token=abcdefghijk"}), None, "alice")
        self.assertIn("REDACTED", clean["data"]["body"])
        with self.assertRaises(guard.Refused) as e:
            guard.outbound(p, self.env({"body": "-----BEGIN PRIVATE KEY-----"}), None, "alice")
        self.assertEqual(e.exception.decision, "blocked")
        with self.assertRaises(guard.Refused) as e:
            guard.outbound(p, self.env({"body": "x" * (guard.MAX_PAYLOAD + 1)}), None, "alice")
        self.assertEqual(e.exception.decision, "too_large")


class Inbound(unittest.TestCase):
    def setUp(self):
        self.p = policy()
        self.rid = self.p.rid_of("falcon")

    def d(self, frm, type_="message", rid="default", data=None, subj_from=None):
        rid = self.rid if rid == "default" else rid
        env = envelope.make(type_, frm, "x", rid, "nick", data or {"body": "b"})
        plane = envelope.PLANE_OF[type_]
        return guard.inbound(self.p, f"am.{plane}.{subj_from or frm}.nick", env)

    def test_trust_levels(self):
        self.assertEqual(self.d("alice").action, "deliver")
        self.assertFalse(self.d("alice").untrusted)
        self.assertTrue(self.d("bob").untrusted)
        self.assertEqual(self.d("eve").reason, "denied")
        self.assertEqual(self.d("mallory").action, "quarantine")            # unlisted: approve
        k = self.d("mallory", "knowledge")
        self.assertEqual((k.action, k.untrusted), ("deliver", True))       # data planes still mirror

    def test_spoof_self_and_scope(self):
        self.assertIn("spoof", self.d("alice", subj_from="mallory").reason)
        self.assertEqual(self.d("nick").reason, "self")
        self.assertEqual(self.d("alice", rid="r000000000000").reason, "not_shared")
        self.assertEqual(self.d("alice", "knowledge", rid=None).reason, "no rid")

    def test_privileged_work_is_quarantined_even_from_auto(self):
        dec = self.d("alice", "work", data={"title": "t", "requirements": {"capabilities": ["plc_write"]}})
        self.assertEqual(dec.action, "quarantine")
        self.assertIn("plc_write", dec.reason)
        self.assertEqual(self.d("alice", "work", data={"title": "t"}).action, "deliver")

    def test_wrap(self):
        self.assertIn("REMOTE DATA from peer bob", guard.wrap("x", "bob", "flag", True))
        self.assertTrue(guard.wrap("x", "alice", "auto", False).startswith("[federated from peer alice]"))


class Config(unittest.TestCase):
    def test_round_trip(self):
        d = tempfile.mkdtemp()
        cfg = config.load(d)
        cfg["federation"].update(enabled=True, peer="nick", url="tls://h:4222", creds="/c", ca="/ca")
        cfg["repos"]["falcon"] = {"peers": ["alice", "bob"], "board_prefix": "FAL"}
        cfg["peers"]["*"] = {"trust": "approve"}
        cfg["peers"]["alice"] = {"trust": "auto"}
        config.save(d, cfg)
        self.assertEqual(oct(os.stat(config.path_for(d)).st_mode & 0o777), "0o600")
        back = config.load(d)
        self.assertEqual(back["repos"], cfg["repos"])
        self.assertEqual(back["peers"], cfg["peers"])
        self.assertEqual(back["federation"]["peer"], "nick")


class Envelope(unittest.TestCase):
    def test_subjects_refuse_bad_tokens(self):
        self.assertEqual(envelope.subject("msg", "nick", "alice"), "am.msg.nick.alice")
        for bad in ("Nick", "a.b", "a>", "*", ""):
            with self.assertRaises(envelope.BadEnvelope):
                envelope.subject("msg", bad, "alice")

    def test_validate(self):
        e = envelope.make("knowledge", "nick", "n", "r0123456789ab", "*", {"title": "t"})
        self.assertIs(envelope.validate(e), e)
        for bad in ({**e, "v": 1}, {**e, "type": "x"}, {**e, "rid": "nope"}, {**e, "data": []}):
            with self.assertRaises(envelope.BadEnvelope):
                envelope.validate(bad)


class Mcp(unittest.TestCase):
    def run_lines(self, lines, fake):
        from hub.fed import mcp
        old = mcp.cli.call
        mcp.cli.call = fake
        try:
            out = io.StringIO()
            mcp.main(io.StringIO("\n".join(json.dumps(x) for x in lines) + "\n"), out)
        finally:
            mcp.cli.call = old
        return [json.loads(x) for x in out.getvalue().splitlines()]

    def test_protocol(self):
        calls = []

        def fake(verb, args=None, as_=None, timeout=30):
            calls.append((verb, args))
            if verb == "fed_verbs":
                return {"result": [
                    {"verb": "fed_board_add", "help": "h", "operator_only": False,
                     "params": {"repo": {"type": "string", "required": True, "help": "", "positional": False}}},
                    {"verb": "fed_kill", "help": "h", "operator_only": True, "params": {}},
                    {"verb": "fed_status", "help": "h", "operator_only": False, "params": {}}]}
            return {"result": {"echo": verb, "args": args}}
        out = self.run_lines([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "board_add", "arguments": {"repo": "f"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "hub_work_add",
                                                                         "arguments": {"to": "role:f/w", "title": "t",
                                                                                       "require": ["x"]}}},
            {"jsonrpc": "2.0", "id": 5, "method": "nope"},
        ], fake)
        self.assertEqual([o["id"] for o in out], [1, 2, 3, 4, 5], "no reply to the notification")
        self.assertEqual(out[0]["result"]["protocolVersion"], "2025-06-18")
        names = {t["name"] for t in out[1]["result"]["tools"]}
        self.assertTrue({"hub_inbox", "hub_post", "board_add", "fed_status"} <= names)
        self.assertNotIn("fed_kill", names, "operator-only verbs are not offered to agents")
        self.assertFalse(out[2]["result"]["isError"])
        self.assertIn(("fed_board_add", {"repo": "f", "cwd": os.getcwd()}), calls)
        self.assertEqual([a for v, a in calls if v == "work_add"][0]["requirements"], {"capabilities": ["x"]})
        self.assertEqual(out[4]["error"]["code"], -32601)


class Gate(unittest.TestCase):
    def ev(self, tool, cmd=None):
        return {"tool_name": tool, "tool_input": {"command": cmd} if cmd else {}}

    def test_only_privileged_tools_are_gated(self):
        never = lambda: (_ for _ in ()).throw(AssertionError("gate not consulted for harmless tools"))  # noqa: E731
        self.assertEqual(privileged_gate.decide(self.ev("Read"), never), (True, ""))
        self.assertEqual(privileged_gate.decide(self.ev("Bash", "pytest -q"), never), (True, ""))
        self.assertEqual(privileged_gate.decide(self.ev("mcp__pcm600__scl_summary"), never), (True, ""))

    def test_remote_work_blocks_privileged(self):
        held = lambda: {"remote_work": [{"id": "W-1", "peer": "alice", "privileged_ok": False}]}  # noqa: E731
        ok = lambda: {"remote_work": [{"id": "W-1", "peer": "alice", "privileged_ok": True}]}  # noqa: E731
        none = lambda: {"remote_work": []}  # noqa: E731
        for ev in (self.ev("mcp__pcm600__pcm_import_parameters"), self.ev("mcp__codesys_local__write_runtime_values"),
                   self.ev("Bash", "sudo python3 taskmgmt/pn_dcp.py --set-name x")):
            allow, why = privileged_gate.decide(ev, held)
            self.assertFalse(allow, ev)
            self.assertIn("W-1 from alice", why)
            self.assertTrue(privileged_gate.decide(ev, ok)[0])
            self.assertTrue(privileged_gate.decide(ev, none)[0])


if __name__ == "__main__":
    unittest.main()
