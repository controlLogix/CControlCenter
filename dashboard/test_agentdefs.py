#!/usr/bin/env python3
"""Offline C1/C3 regressions; no live board writes or third-party imports."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "taskmgmt"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import agentdefs as ad
import ninep

# Captured at import, BEFORE setUp relocates HOME into a fixture directory.
# Path.home() inside a test resolves to that fixture, so reading it there would
# quietly turn "check this machine's real definitions" into "check the ones this
# test just wrote" - a test that passes while checking nothing.
REAL_HOME = Path.home()


class AgentDefinitions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="agentdefs-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        self.repo = self.base / "repo"
        self.root = self.home / ".agentmux"
        self.root.mkdir(parents=True)
        self.repo.mkdir()
        env = patch.dict(os.environ, {"HOME": str(self.home), "AGENTMUX_HOME": str(self.root)})
        env.start()
        self.addCleanup(env.stop)
        self.dirs = [self.repo / ".agentmux/agents", self.root / "agents",
                     self.repo / ".claude/agents", self.home / ".claude/agents"]

    def write(self, name="worker", scope=0, extra="", body="Persona\nsecond line", raw=None):
        directory = self.dirs[scope]
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (name + ".md")
        path.write_bytes(raw if raw is not None else
                         f"---\nname: {name}\ndescription: Useful agent\n{extra}---\n{body}".encode())
        return path

    def load(self):
        return ad.load_all(self.repo)

    def test_four_scopes_and_defaults(self):
        for i in range(4):
            self.write("agent" + str(i), i)
        specs, problems = self.load()
        self.assertEqual(problems, [])
        self.assertEqual(len(specs), 4)
        for i, scope in enumerate(("repo", "global", "claude", "claude")):
            s = specs["agent" + str(i)]
            self.assertEqual(s.scope, scope)
            self.assertEqual((s.cli, s.role, s.posture, s.worktree, s.max_instances),
                             ("codex", "worker", "workspace-write", "per-member", 1))
            self.assertEqual((s.model, s.auth, s.tools, s.tools_deny, s.capabilities),
                             (None, None, (), (), ()))
            self.assertTrue(Path(s.path).is_absolute())

    def test_duplicates_every_pair_of_scopes(self):
        for i in range(4):
            for j in range(i + 1, 4):
                with self.subTest(pair=(i, j)):
                    a, b = self.write(scope=i), self.write(scope=j)
                    specs, problems = self.load()
                    self.assertEqual(specs, {})
                    self.assertEqual(len(problems), 1)
                    self.assertIn(str(a), problems[0]["error"])
                    self.assertIn(str(b), problems[0]["error"])
                    a.unlink()
                    b.unlink()

    def test_three_duplicates_and_invalid_duplicate(self):
        for i in range(3):
            self.write(scope=i)
        specs, problems = self.load()
        self.assertEqual(specs, {})
        self.assertEqual(len(problems), 1)
        self.write(scope=1, extra="posture: unsafe\n")
        specs, problems = self.load()
        self.assertEqual(specs, {})
        self.assertEqual(sum("duplicate name" in p["error"] for p in problems), 1)

    def test_flat_quotes_csv_checksum_crlf(self):
        raw = (b'---\r\nname: worker\r\ndescription: "Colon: # text"\r\n'
               b"cli: claude\r\ntools: Read, Bash(git diff:*)\r\ntools-deny: Write, Edit\r\n"
               b"capabilities: review, security\r\nrole: lead\r\nmax_instances: 8\r\n"
               b"model: 'model''s name'\r\n---\r\n\r\nBody\r\nnext\r\n")
        self.write(raw=raw)
        specs, problems = self.load()
        self.assertEqual(problems, [])
        s = specs["worker"]
        self.assertEqual(s.description, "Colon: # text")
        self.assertEqual(s.tools, ("Read", "Bash(git diff:*)"))
        self.assertEqual(s.tools_deny, ("Write", "Edit"))
        self.assertEqual(s.capabilities, ("review", "security"))
        self.assertEqual(s.worktree, "integration")
        self.assertEqual(s.model, "model's name")
        self.assertEqual(s.persona, "Body\nnext")
        self.assertEqual(s.checksum, "sha256:" + hashlib.sha256(raw).hexdigest())

    def test_unknown_keys_warn_and_still_load(self):
        p = self.write(extra="tool: Read\ncolour: green\n")
        specs, problems = self.load()
        self.assertIn("worker", specs)
        self.assertEqual(len(problems), 2)
        self.assertTrue(all(x["path"] == str(p) for x in problems))
        self.assertTrue(any("'tool'" in x["error"] for x in problems))
        self.assertTrue(any("'colour'" in x["error"] for x in problems))

    def test_validation_rejections_are_named(self):
        base = "---\nname: worker\ndescription: Useful\n"
        cases = [
            ("missing", "missing opening"),
            (base, "missing closing"),
            ("---\nname: worker\n---\n", "description"),
            (base.replace("worker", "Wrong") + "---", "name"),
            (base.replace("worker", "other") + "---", "filename"),
            (base + "name: worker\n---", "duplicate frontmatter"),
            (base + "tools:\n  allow: Read\n---", "flat"),
        ]
        for field, value in [("cli", "bad;cli"), ("posture", "unsafe"), ("role", "boss"),
                             ("worktree", "shared"), ("max_instances", "0"),
                             ("max_instances", "9"), ("max_instances", "1.5"),
                             ("capabilities", "Upper"), ("capabilities", ",review"),
                             ("capabilities", ",".join(["tag"] * 17)),
                             ("tools", "Read,,Write"), ("tools", "[Read, Write]"),
                             ("model", '"bad\\nmodel"'), ("auth", "not-a-method")]:
            cases.append((base + f"{field}: {value}\n---", field))
        cases.extend([(base + "---\n" + "x" * 4097, "persona"),
                      (base + "---\nBad\x00", "persona"),
                      (base.replace("Useful", "x" * 2049) + "---", "description"),
                      (base.replace("Useful", "bad\tvalue") + "---", "description")])
        for text, reason in cases:
            with self.subTest(reason=reason, text=text[:100]):
                p = self.write(raw=text.encode())
                specs, problems = self.load()
                self.assertEqual(specs, {})
                self.assertTrue(any(reason in x["error"] and x["path"] == str(p)
                                    for x in problems), problems)

    def test_size_encoding_backups_symlinks_and_directories(self):
        good = self.write("good")
        (good.parent / "backup.md.bak_123").write_bytes(b"invalid")
        self.write("huge", raw=b"x" * (ad.MAX_BYTES + 1))
        self.write("invalid", raw=b"\xff")
        (good.parent / "link.md").symlink_to(good)
        (good.parent / "directory.md").mkdir()
        specs, problems = self.load()
        self.assertEqual(set(specs), {"good"})
        self.assertEqual(len(problems), 4)
        self.assertTrue(any("64 KiB" in x["error"] for x in problems))
        self.assertTrue(any("symlink" in x["error"] for x in problems))

    def test_listing_cap(self):
        for i in range(201):
            self.write("a" + str(i))
        specs, problems = self.load()
        self.assertEqual(specs, {})
        self.assertEqual(len(problems), 1)
        self.assertIn("200", problems[0]["error"])

    def test_board_auth_model_defaults_and_resolve(self):
        with sqlite3.connect(self.root / "cc.db") as db:
            db.execute("CREATE TABLE board_config (name TEXT, value TEXT)")
            db.execute("INSERT INTO board_config VALUES ('dispatchCli', '\"claude\"')")
        methods = json.loads(ad.MANIFEST.read_text())["methods"]
        auth = next(m["id"] for m in methods if m["cli"] == "claude")
        (self.root / "auth.json").write_text(json.dumps({"active": {"claude": auth},
                                                       "methods": {auth: {"model": "chosen"}}}))
        self.write()
        specs, problems = self.load()
        self.assertEqual(problems, [])
        s = specs["worker"]
        self.assertEqual((s.cli, s.auth, s.model), ("claude", auth, "chosen"))
        self.assertEqual(ad.resolve("worker", self.repo), s)
        self.assertIsNone(ad.resolve("missing", self.repo))
        self.write(extra="cli: codex\nauth: " + auth + "\n")
        self.assertEqual(self.load()[0], {})

    def test_io_and_config_failures_do_not_raise(self):
        self.write()
        with patch.object(ad.os, "open", side_effect=PermissionError("denied")):
            specs, problems = self.load()
        self.assertEqual(specs, {})
        self.assertIn("denied", problems[0]["error"])
        (self.root / "auth.json").write_text("{")
        specs, problems = self.load()
        self.assertIn("worker", specs)
        self.assertTrue(any("auth configuration" in p["error"] for p in problems))
        specs, problems = ad.load_all(object())
        self.assertEqual(specs, {})
        self.assertTrue(problems)

    def test_same_directory_not_a_collision(self):
        self.write("homeagent", 3)
        specs, problems = ad.load_all(self.home)
        self.assertEqual(problems, [])
        self.assertEqual(set(specs), {"homeagent"})

    def test_roster_fallback_and_override(self):
        for cfg, override, cli in [({}, None, "codex"), ({"dispatchCli": "claude"}, None, "claude"),
                                   ({"dispatchCli": "claude"}, "grok", "grok"),
                                   ({"dispatchCli": ""}, "", "codex")]:
            roster = ad.choose_roster({}, {}, cfg, override)
            self.assertEqual(len(roster), 1)
            self.assertEqual((roster[0].cli, roster[0].role), (cli, "lead"))
        self.write(extra="role: lead\ntools: Read\n")
        specs, problems = self.load()
        self.assertEqual(problems, [])
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            roster = ad.choose_roster({}, specs, {})
        self.assertEqual(roster[0], specs["worker"])
        self.assertIn("degrade", str(caught[0].message))

    def roster_specs(self):
        for name, extra in (
            ("alpha", "capabilities: frontend\n"),
            ("backend", "capabilities: backend\n"),
            ("senior-dev", "capabilities: senior, backend\nmax_instances: 8\n"),
            ("review", "role: reviewer\ncapabilities: security\n"),
            ("research", "role: researcher\n"),
        ):
            self.write(name, extra=extra)
        return self.load()[0]

    def test_worker_sizing_caps_and_determinism(self):
        specs = self.roster_specs()
        task = {"touches": ["ui/a", "ui/b", "api/c"]}
        roster = ad.choose_roster(task, specs, {"teamMaxWorkers": 8})
        self.assertEqual(len(roster), 3)
        self.assertEqual(roster, ad.choose_roster(task, dict(reversed(list(specs.items()))),
                                                 {"teamMaxWorkers": 8}))
        task["acceptance"] = [{"text": str(i)} for i in range(5)]
        self.assertEqual(len(ad.choose_roster(task, specs, {"teamMaxWorkers": 8})), 4)
        for cap in (0, 1, 2):
            self.assertEqual(len(ad.choose_roster(task, specs, {"teamMaxWorkers": cap})), cap + 1)
        roster = ad.choose_roster({"touches": [f"d{i}/a" for i in range(8)]},
                                  {"senior-dev": specs["senior-dev"]}, {"teamMaxWorkers": 8})
        self.assertEqual([s.name for s in roster], ["lead", "senior-dev"])
        self.assertTrue(roster.gaps)

    def test_labels_gaps_types_and_depth(self):
        specs = self.roster_specs()
        roster = ad.choose_roster({"labels": ["backend", "missing"]}, specs, {})
        self.assertIn("backend", [s.name for s in roster])
        self.assertIn("Capability missing: no definition provides it", roster.gaps)
        bug = ad.choose_roster({"type": "bug"}, specs, {"teamMaxWorkers": 8})
        self.assertEqual([s.role for s in bug], ["lead", "worker", "reviewer"])
        for kind in ("story", "spike"):
            self.assertEqual(len(ad.choose_roster({"type": kind}, specs, {})), 3)
        dependencies = {"A": ["B"], "B": ["C"], "C": ["A"]}
        task = {"type": "story", "blockedBy": ["A"], "labels": ["frontend"]}
        deep = ad.choose_roster(task, specs, {"teamMaxWorkers": 8}, dependencies=dependencies)
        self.assertEqual([s.name for s in deep], ["lead", "senior-dev"])
        self.assertIn("Capability frontend: not covered by selected roster", deep.gaps)
        self.assertFalse(ad._deep_chain({"blockedBy": ["A"]}, {"A": ["A"]}))
        self.assertFalse(ad._deep_chain({"key": "ROOT", "blockedBy": ["A"]},
                                        {"A": ["B"], "B": ["ROOT"]}))
        fallback = ad.choose_roster(task, {}, {"dispatchCli": "claude"}, dependencies=dependencies)
        self.assertEqual([(s.name, s.cli) for s in fallback], [("lead", "claude")])
        self.assertTrue(fallback.gaps)

    # The five this project ships as user-scope definitions.
    SHIPPED = ("hr-recruiter", "plc-dev", "plc-test-engineer", "scheduler", "senior-reviewer")

    def assert_worker_set(self, names):
        specs, problems = self.load()
        self.assertEqual(problems, [])
        self.assertEqual(set(specs), set(names))
        self.assertTrue(all(s.role == "worker" and s.posture == "workspace-write"
                            and s.max_instances == 1 for s in specs.values()))

    def test_representative_definitions_load_as_workers(self):
        # Repo-only, so this one always runs. It used to be entangled with the
        # check below, which meant the whole property depended on a directory
        # outside the repo that the gate does not control.
        for name in self.SHIPPED:
            self.write(name, 3)
        self.assert_worker_set(self.SHIPPED)

    def test_this_machines_own_definitions_still_load(self):
        """The real files, byte-for-byte - and a SKIP that says so when they are
        not readable, rather than a pass that quietly checked something else.

        REAL_HOME, not a hardcoded /home/nick and not Path.home(): the hardcode
        made this a test about one account rather than about the machine it runs
        on, and Path.home() here resolves to the fixture setUp created - which
        would have made it check the files it had just written itself.
        """
        source = REAL_HOME / ".claude/agents"
        copied = []
        for name in self.SHIPPED:
            p = source / (name + ".md")
            # Three outcomes, not two. ~/.claude can be a link onto /mnt/c, where
            # is_file() raises EIO instead of answering - and "we could not read
            # it" is neither "it is absent" nor a defect in the definitions.
            reason = ninep.unreachable_reason(p, "file")
            if reason is None:
                self.write(name, 3, raw=ninep.guard(p.read_bytes, p))
                copied.append(name)
            elif not reason.endswith("is absent"):
                self.skipTest(reason)
        if len(copied) != len(self.SHIPPED):
            # Portable CI has none of these. Say which were missing rather than
            # silently testing the representative ones and reporting a pass.
            missing = sorted(set(self.SHIPPED) - set(copied))
            self.skipTest(f"{source} does not carry {missing}; "
                          f"the representative definitions are covered separately")
        self.assert_worker_set(self.SHIPPED)


if __name__ == "__main__":
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(AgentDefinitions))
    failures = len(result.failures) + len(result.errors)
    # A skipped test is not a passed one. result.testsRun counts skips, so the old
    # `testsRun - failures` reported them as passes and a suite that silently ran
    # nothing looked identical to one that ran everything. run_tests.sh:175 already
    # greps for '^SKIP ', so naming them here is what makes them visible in the gate.
    for case, reason in result.skipped:
        print(f'SKIP {case} - {reason}')
    print(f'passed {result.testsRun - failures - len(result.skipped)}, '
          f'failed {failures}')
    sys.exit(bool(failures))
