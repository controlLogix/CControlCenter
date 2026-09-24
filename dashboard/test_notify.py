#!/usr/bin/env python3
"""Notification channels, and the routing that decides who hears about what.

THE STANDARD THESE ARE HELD TO. A notification path nobody has ever fired is a
notification path nobody knows is broken, and this one has a worse failure mode than
most: every channel is allowed to fail quietly so it can never stop a run, which means
a channel that is silently off looks exactly like a quiet day. So each test below
proves a channel actually carried the payload, not merely that calling it returned.

No test here raises a real toast. The desktop channel shells out to powershell.exe and
a suite that pops notifications on someone's screen is a suite people stop running.
AGENTMUX_NO_TOAST is the opt-out and these set it.
"""
import importlib
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "taskmgmt"))
import notify


class NotifyBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="notify-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self._saved = {k: os.environ.get(k) for k in
                       ("AGENTMUX_NO_TOAST", "AGENTMUX_AGENT", "TMUX_PANE",
                        "AGENTMUX_POWERSHELL")}
        os.environ["AGENTMUX_NO_TOAST"] = "1"
        self.addCleanup(self._restore)

    def _restore(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def hook(self, body="cat >> \"$LOG\"", name="hook.sh"):
        """A command hook that records exactly what it was handed."""
        path = self.tmp / name
        path.write_text(
            "#!/usr/bin/env bash\n"
            f'LOG="{self.tmp}/hook.log"\n'
            'printf "urgency=%s ref=%s subject=%s\\n" "$AGENTMUX_NOTIFY_URGENCY" '
            '"$AGENTMUX_NOTIFY_REF" "$AGENTMUX_NOTIFY_SUBJECT" >> "$LOG"\n'
            f"{body}\n"
            'printf "\\n" >> "$LOG"\n', encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
        return str(path)

    def log(self):
        try:
            return (self.tmp / "hook.log").read_text(encoding="utf-8")
        except OSError:
            return ""


class TestCommandHook(NotifyBase):
    def test_the_payload_reaches_the_command_on_stdin(self):
        ok, reason = notify.run_command(self.hook(), "a subject", "a body", "warn", "r1")
        self.assertTrue(ok, reason)
        written = self.log()
        self.assertIn("urgency=warn ref=r1 subject=a subject", written)
        payload = json.loads(written.splitlines()[1])
        self.assertEqual(payload["subject"], "a subject")
        self.assertEqual(payload["body"], "a body")
        self.assertEqual(payload["ref"], "r1")

    def test_a_missing_command_is_reported_not_raised(self):
        ok, reason = notify.run_command(str(self.tmp / "nope.sh"), "s", "b")
        self.assertFalse(ok)
        self.assertIn("could not be run", reason)

    def test_a_failing_command_reports_its_exit_code(self):
        path = self.tmp / "bad.sh"
        path.write_text("#!/usr/bin/env bash\necho 'it broke' >&2\nexit 3\n",
                        encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
        ok, reason = notify.run_command(str(path), "s", "b")
        self.assertFalse(ok)
        self.assertIn("exited 3", reason)
        self.assertIn("it broke", reason)

    def test_no_command_configured_is_not_an_error_state(self):
        for value in ("", "   ", None):
            ok, reason = notify.run_command(value, "s", "b")
            self.assertFalse(ok)
            self.assertIn("no command", reason)

    def test_an_unparseable_command_is_refused_by_name(self):
        ok, reason = notify.run_command('curl "unclosed', "s", "b")
        self.assertFalse(ok)
        self.assertIn("not parseable", reason)


class TestTheSubjectIsNeverCode(NotifyBase):
    """A subject carries a reviewer's free-text reason. If that text can reach a shell
    or a PowerShell parser, every notification is an injection site."""

    def test_shell_metacharacters_in_a_subject_stay_data(self):
        canary = self.tmp / "pwned"
        subject = f'"; touch {canary}; echo "'
        ok, _ = notify.run_command(self.hook(), subject, "body", "info", "r")
        self.assertTrue(ok)
        self.assertFalse(canary.exists(),
                         "the subject was interpreted instead of being passed as data")
        self.assertIn(subject, self.log())

    def test_a_body_full_of_metacharacters_stays_data(self):
        canary = self.tmp / "pwned2"
        body = f"$(touch {canary})`touch {canary}`"
        ok, _ = notify.run_command(self.hook(), "s", body, "info", "r")
        self.assertTrue(ok)
        self.assertFalse(canary.exists())

    def test_the_command_is_never_run_through_a_shell(self):
        # A configured command is split once, by shlex, from something a person typed.
        # If it went through a shell, this pipeline would work - and then any text in a
        # subject could introduce metacharacters of its own.
        canary = self.tmp / "piped"
        ok, _ = notify.run_command(f"echo hi > {canary}", "s", "b")
        self.assertFalse(canary.exists(),
                         "the command ran through a shell; > was interpreted")

    def test_the_toast_text_is_not_interpolated_into_the_script(self):
        # The script is a constant. Proving that here rather than by launching
        # PowerShell, because the property being protected is textual.
        for marker in ("$env:AGENTMUX_TOAST_TITLE", "$env:AGENTMUX_TOAST_BODY"):
            self.assertIn(marker, notify.TOAST_SCRIPT)
        self.assertNotIn("param(", notify.TOAST_SCRIPT,
                         "-Command cannot bind param(); that shipped an empty toast once")


class TestBounds(NotifyBase):
    def test_a_hanging_command_is_given_up_on(self):
        path = self.tmp / "slow.sh"
        path.write_text("#!/usr/bin/env bash\nsleep 60\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
        saved = notify.COMMAND_TIMEOUT_S
        notify.COMMAND_TIMEOUT_S = 1
        try:
            ok, reason = notify.run_command(str(path), "s", "b")
        finally:
            notify.COMMAND_TIMEOUT_S = saved
        self.assertFalse(ok)
        self.assertIn("did not finish", reason)

    def test_an_enormous_body_is_truncated_before_it_is_sent(self):
        ok, _ = notify.run_command(self.hook(), "s" * 5000, "b" * 50_000, "info", "r")
        self.assertTrue(ok)
        payload = json.loads(self.log().splitlines()[1])
        self.assertLessEqual(len(payload["subject"]), notify.SUBJECT_MAX)
        self.assertLessEqual(len(payload["body"]), notify.BODY_MAX)

    def test_a_multiline_subject_is_flattened(self):
        # It becomes a toast title and a status line; a newline there is a broken widget.
        self.assertEqual(notify.one_line("two\nlines\there", 100), "two lines here")


class TestDeliverFansOut(NotifyBase):
    def test_nothing_configured_returns_an_empty_list_not_a_failure(self):
        # An empty list means "no channel was asked for", which a caller must be able
        # to tell apart from "every channel failed".
        self.assertEqual(notify.deliver("s", "b", toast_enabled=False, command=""), [])

    def test_a_box_with_no_desktop_does_not_report_a_failed_channel(self):
        # Otherwise every plant-box run prints a warning about a channel nobody asked
        # for, and warnings that are always there stop being read.
        out = notify.deliver("s", "b", toast_enabled=True, command="")
        self.assertEqual(out, [])

    def test_every_channel_is_tried_even_after_one_succeeds(self):
        # They are different people at different desks, not a failover chain: a toast
        # on this machine does nothing for someone who has gone home.
        out = notify.deliver("s", "b", command=self.hook(), pane="%999")
        channels = {row["channel"] for row in out}
        self.assertEqual(channels, {"command", "terminal"})
        self.assertTrue(next(r for r in out if r["channel"] == "command")["ok"])

    def test_a_broken_channel_does_not_stop_the_others(self):
        out = notify.deliver("s", "b", command=str(self.tmp / "missing.sh"),
                             pane="%999")
        self.assertEqual(len(out), 2)
        self.assertFalse(any(row["ok"] for row in out))


class TestOriginId(NotifyBase):
    def test_an_agent_pane_is_named_by_its_agent(self):
        os.environ["AGENTMUX_AGENT"] = "netcap-dev"
        self.assertEqual(notify.origin_id(), "netcap-dev")

    def test_a_plain_terminal_in_tmux_is_named_by_its_pane(self):
        os.environ.pop("AGENTMUX_AGENT", None)
        os.environ["TMUX_PANE"] = "%17"
        self.assertEqual(notify.origin_id(), "pane17")

    def test_anything_else_is_the_orchestrator(self):
        os.environ.pop("AGENTMUX_AGENT", None)
        os.environ.pop("TMUX_PANE", None)
        self.assertEqual(notify.origin_id(), "orchestrator")

    def test_a_malformed_pane_is_not_turned_into_a_name(self):
        os.environ.pop("AGENTMUX_AGENT", None)
        for bad in ("../etc", "%", "pane", "%x1", ""):
            os.environ["TMUX_PANE"] = bad
            self.assertEqual(notify.origin_id(), "orchestrator", bad)


class TestTerminalChannelIsNeverInput(NotifyBase):
    """The rule that makes this channel safe to point at an LLM's terminal."""

    def test_send_keys_appears_nowhere_in_this_module(self):
        # send-keys types into whatever is reading stdin - an agent's prompt, a
        # half-typed command, a y/n confirmation. That is remote input, not a
        # notification, and it turns any text in a verdict into an instruction.
        import ast
        tree = ast.parse(Path(notify.__file__).read_text(encoding="utf-8"))
        # The docstrings and comments SAY "never send-keys", so a text search finds the
        # prohibition itself and passes for the wrong reason. Only executable code
        # counts, so the docstrings are stripped before looking.
        for node in ast.walk(tree):
            if (isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef))
                    and node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body[0].value.value = ""
        code = ast.unparse(tree)
        self.assertNotIn("send-keys", code)
        self.assertNotIn("send_keys", code)

    def test_the_status_line_is_what_is_written(self):
        self.assertIn("display-message",
                      Path(notify.__file__).read_text(encoding="utf-8"))

    def test_an_absent_pane_is_reported_rather_than_guessed_at(self):
        ok, reason = notify.tmux_status(None, "s")
        self.assertFalse(ok)
        self.assertIn("no pane", reason)

    def test_a_pane_that_does_not_exist_is_never_reported_as_delivered(self):
        # THE BUG THIS CAUGHT. `display-message -t <anything>` exits 0 whether or not
        # the target resolves - a pane id that does not exist and a plain string that
        # is not an id at all both return 0 and draw nothing. Trusting that exit code
        # reported a notification as delivered when it had gone nowhere.
        #
        # This only failed with a tmux server running, so it passed standalone and went
        # red in the full gate, where earlier suites leave one up. Both cases are
        # asserted below so it cannot go back to passing for the wrong reason.
        for target in ("%999999", "no-such-pane-name"):
            ok, reason = notify.tmux_status(target, "subject")
            self.assertFalse(ok, f"{target} was reported as delivered")
            self.assertTrue(reason, "a refusal must say why")

    def test_the_target_is_resolved_with_a_command_that_can_refuse(self):
        source = Path(notify.__file__).read_text(encoding="utf-8")
        self.assertIn("list-panes", source,
                      "resolution must not rest on display-message's exit code")


# ── the routing: who hears about what ────────────────────────────────────────

class TestNoticeRouting(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="notify-home-"))
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self._env = os.environ.get("AGENTMUX_HOME")
        os.environ["AGENTMUX_HOME"] = str(self.home)
        os.environ["AGENTMUX_NO_TOAST"] = "1"
        os.environ["AGENTMUX_NOTIFY_TOAST"] = "0"
        os.environ.pop("AGENTMUX_AGENT", None)
        os.environ.pop("TMUX_PANE", None)
        self.addCleanup(self._restore)
        import run as runmod
        self.run = importlib.reload(runmod)

    def _restore(self):
        if self._env is None:
            os.environ.pop("AGENTMUX_HOME", None)
        else:
            os.environ["AGENTMUX_HOME"] = self._env
        os.environ.pop("AGENTMUX_NOTIFY_TOAST", None)

    def seed(self, run_id="aa11cc", origin=None):
        self.run.run_dir(run_id).mkdir(parents=True, exist_ok=True)
        event = {"event": "start", "by": "orchestrator", "detail": "a request"}
        if origin:
            event["origin"] = origin
        self.run.append_event(run_id, event)
        self.run.append_event(run_id, {"event": "assign", "job": f"{run_id}/1",
                                       "by": "orchestrator", "worker": "w",
                                       "reviewer": "r"})
        return run_id

    def inbox(self, who):
        path = self.home / "inbox" / f"{who}.jsonl"
        if not path.is_file():
            return []
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
                if l.strip()]

    def test_a_notice_reaches_the_terminal_that_opened_the_run(self):
        rid = self.seed(origin="my-session")
        self.run.record_notice(rid, "waiting", "needs you", "body", "orchestrator",
                               ref=rid)
        self.assertEqual(len(self.inbox("my-session")), 1)
        # And the shared tray keeps its copy: that is what the dashboard and
        # `agentmux inbox` read, so moving it out would remove it from both.
        self.assertEqual(len(self.inbox("orchestrator")), 1)

    def test_a_run_with_no_recorded_origin_only_uses_the_shared_tray(self):
        rid = self.seed()
        self.run.record_notice(rid, "waiting", "needs you", "", "orchestrator", ref=rid)
        self.assertEqual(len(self.inbox("orchestrator")), 1)
        self.assertEqual(sorted(p.name for p in (self.home / "inbox").glob("*.jsonl")),
                         ["orchestrator.jsonl"])

    def test_an_origin_that_is_not_a_valid_name_cannot_choose_the_file(self):
        # "../../etc/passwd" is the obvious traversal and it is a WEAK test: the
        # directory does not exist, so an unguarded write fails on its own and the
        # assertion passes without the guard existing. "../escaped" lands in a
        # directory that is definitely there, so only the name check stops it.
        rid = self.seed(origin="../escaped")
        self.run.record_notice(rid, "waiting", "needs you", "", "orchestrator", ref=rid)
        names = sorted(q.name for q in (self.home / "inbox").iterdir())
        self.assertEqual(names, ["orchestrator.jsonl"],
                         "a malformed origin chose its own filename")
        self.assertFalse((self.home / "escaped.jsonl").exists(),
                         "the origin escaped the inbox directory")
        self.assertTrue(self.inbox("orchestrator"),
                        "the notice was dropped instead of falling back")

    def test_waiting_is_a_warning_and_escalation_is_an_error(self):
        # Collapsing these teaches people that red means nothing, which costs the
        # escalations that genuinely are red.
        rid = self.seed(origin="s1")
        self.run.record_notice(rid, "waiting", "needs review", "", "by", ref=rid)
        self.run.record_notice(rid, "blocked", "escalated", "", "by", ref=rid)
        kinds = [row["kind"] for row in self.inbox("s1")]
        self.assertEqual(kinds, ["status", "error"])


class TestUnreadNotices(TestNoticeRouting):
    def test_unread_are_surfaced_then_cleared(self):
        rid = self.seed()
        self.run.record_notice(rid, "waiting", "one", "", "by", ref=rid)
        self.run.record_notice(rid, "blocked", "two", "", "by", ref=rid)
        self.assertEqual(len(self.run.unread_notices()), 2)
        self.run.mark_notices_read()
        self.assertEqual(self.run.unread_notices(), [])

    def test_a_new_notice_after_reading_is_unread_again(self):
        rid = self.seed()
        self.run.record_notice(rid, "waiting", "one", "", "by", ref=rid)
        self.run.mark_notices_read()
        self.run.record_notice(rid, "waiting", "two", "", "by", ref=rid)
        rows = self.run.unread_notices()
        self.assertEqual(len(rows), 1)
        self.assertIn("two", rows[0]["body"])

    def test_a_truncated_inbox_shows_everything_rather_than_nothing(self):
        # A marker ahead of the file means it was rotated. Silently showing nothing
        # for the rest of time is the worse failure.
        rid = self.seed()
        for n in range(3):
            self.run.record_notice(rid, "waiting", f"n{n}", "", "by", ref=rid)
        self.run.mark_notices_read()
        (self.home / "inbox" / "orchestrator.jsonl").write_text(
            json.dumps({"at": "now", "kind": "status", "body": "fresh", "ref": rid})
            + "\n", encoding="utf-8")
        self.assertEqual(len(self.run.unread_notices()), 1)

    def test_no_inbox_at_all_is_quiet_rather_than_an_error(self):
        self.assertEqual(self.run.unread_notices(), [])

    def test_a_torn_line_is_skipped_not_fatal(self):
        rid = self.seed()
        self.run.record_notice(rid, "waiting", "good", "", "by", ref=rid)
        with (self.home / "inbox" / "orchestrator.jsonl").open("a", encoding="utf-8") as fh:
            fh.write('{"at": "broken"\n')
        self.assertEqual(len(self.run.unread_notices()), 1)

    def test_the_read_marker_is_not_world_readable(self):
        rid = self.seed()
        self.run.record_notice(rid, "waiting", "one", "", "by", ref=rid)
        self.run.mark_notices_read()
        mode = self.run.unread_path("orchestrator").stat().st_mode & 0o077
        self.assertEqual(mode, 0)


# ── the feed block, and not letting one source starve the rest ───────────────

class TestFeedRationing(unittest.TestCase):
    """The run notices were wired into the feed and still did not appear.

    They were not dropped - they were CROWDED OUT. The journal and chatter blocks each
    fetch up to `limit` rows of their own, so a busy day puts several hundred newer
    entries ahead of everything else and a plain truncation cuts every other source
    entirely. The client filters by source afterwards, so anything lost here is
    invisible no matter what the operator ticks, which is what makes the truncation the
    wrong place to be purely chronological.
    """

    def setUp(self):
        sys.path.insert(0, str(HERE))
        import server
        self.server = server
        import ccstore
        self.ccstore = ccstore

    def entry(self, at, source):
        return self.ccstore.feed_entry(at, source, "info", "who", "text")

    def test_a_flood_from_one_source_cannot_erase_another(self):
        flood = [self.entry(f"2026-09-24T12:{m:02d}:00+00:00", "journal")
                 for m in range(59)]
        rare = [self.entry("2020-01-01T00:00:00+00:00", "run")]
        out = self.server.ration(sorted(flood + rare,
                                        key=lambda e: e["at"], reverse=True), 20)
        self.assertEqual(len(out), 20)
        self.assertIn("run", {e["source"] for e in out},
                      "the one entry a person was waiting on was cut")

    def test_the_result_is_still_newest_first(self):
        # The reserved picks are taken per source, so they land in the intermediate
        # list ahead of newer entries from a busier source. A uniform spread hides
        # that - it comes out sorted by luck - so this deliberately makes the quiet
        # source OLD and the busy one NEW, which is the shape that actually scrambles.
        old_rare = [self.entry(f"2020-01-01T00:{m:02d}:00+00:00", "run")
                    for m in range(10)]
        new_busy = [self.entry(f"2026-09-24T12:{m:02d}:00+00:00", "journal")
                    for m in range(50)]
        out = self.server.ration(
            sorted(old_rare + new_busy, key=lambda e: e["at"], reverse=True), 30)
        self.assertEqual([e["at"] for e in out],
                         sorted((e["at"] for e in out), reverse=True),
                         "the feed came back out of chronological order")

    def test_feed_snapshot_actually_rations_what_it_returns(self):
        # THE GAP THAT LET THIS SHIP BROKEN ONCE. Testing ration() in isolation says
        # nothing about whether feed_snapshot uses it, and the first version of these
        # tests passed happily with the call removed.
        called = {}
        real = self.server.ration

        def spy(entries, limit):
            called["entries"] = len(entries)
            called["limit"] = limit
            return real(entries, limit)

        self.server.ration = spy
        try:
            out = self.server.feed_snapshot(25)
        finally:
            self.server.ration = real
        self.assertIn("limit", called, "feed_snapshot truncated without rationing")
        self.assertEqual(called["limit"], 25)
        self.assertLessEqual(len(out["entries"]), 25)

    def test_nothing_is_invented_or_duplicated(self):
        mixed = [self.entry(f"2026-09-24T00:{m:02d}:00+00:00", s)
                 for m in range(30) for s in ("journal", "run")]
        out = self.server.ration(sorted(mixed, key=lambda e: e["at"], reverse=True), 25)
        self.assertEqual(len(out), 25)
        self.assertEqual(len({id(e) for e in out}), 25, "an entry appeared twice")
        for entry in out:
            self.assertIn(entry, mixed)

    def test_a_short_feed_is_returned_untouched(self):
        few = [self.entry("2026-09-24T00:00:00+00:00", "run")] * 3
        self.assertEqual(self.server.ration(few, 200), few)

    def test_the_busiest_source_still_dominates(self):
        # A floor, not a quota: the feed must still read as what is happening, and a
        # quiet source must not be padded up to parity with a busy one.
        flood = [self.entry(f"2026-09-24T12:{m:02d}:00+00:00", "journal")
                 for m in range(59)]
        rare = [self.entry("2020-01-01T00:00:00+00:00", "run")]
        out = self.server.ration(sorted(flood + rare,
                                        key=lambda e: e["at"], reverse=True), 40)
        journal = sum(1 for e in out if e["source"] == "journal")
        # 39 of 40: the floor costs the busy source exactly the one slot the quiet
        # source needed. An equal-share quota would give it 40/6 = 6 and turn the feed
        # into a summary of every source rather than a record of what is happening.
        self.assertEqual(journal, 39, "the floor became a quota")


class TestRunNoticesReachTheFeed(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(HERE))
        import server
        self.server = server
        self.tmp = Path(tempfile.mkdtemp(prefix="feed-home-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self._saved = server.HOME_DIR
        server.HOME_DIR = self.tmp
        self.addCleanup(lambda: setattr(server, "HOME_DIR", self._saved))
        (self.tmp / "inbox").mkdir(parents=True)

    def write(self, rows):
        (self.tmp / "inbox" / "orchestrator.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def test_a_waiting_notice_is_a_warning_not_an_error(self):
        self.write([{"at": "2026-09-24T12:00:00-0500", "kind": "status",
                     "body": "run abc123 is waiting on your review", "ref": "abc123"}])
        out = self.server.run_notice_entries()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["severity"], "warn")
        self.assertEqual(out[0]["source"], "run")
        self.assertEqual(out[0]["ref"], "abc123")

    def test_an_escalation_is_an_error(self):
        self.write([{"at": "2026-09-24T12:00:00-0500", "kind": "error",
                     "body": "job escalated", "ref": "abc123"}])
        self.assertEqual(self.server.run_notice_entries()[0]["severity"], "error")

    def test_a_completion_is_information(self):
        self.write([{"at": "2026-09-24T12:00:00-0500", "kind": "status",
                     "body": "run abc123 COMPLETE: 2/2", "ref": "abc123"}])
        self.assertEqual(self.server.run_notice_entries()[0]["severity"], "info")

    def test_a_torn_or_missing_inbox_is_quiet(self):
        self.assertEqual(self.server.run_notice_entries(), [])
        (self.tmp / "inbox" / "orchestrator.jsonl").write_text(
            '{"at": "broken"\nnot json at all\n', encoding="utf-8")
        self.assertEqual(self.server.run_notice_entries(), [])

    def test_the_reader_never_marks_anything_read(self):
        # Opening the dashboard must not silently clear the terminal's copy.
        rows = [{"at": "2026-09-24T12:00:00-0500", "kind": "status",
                 "body": "one", "ref": "r"}]
        self.write(rows)
        before = (self.tmp / "inbox" / "orchestrator.jsonl").read_bytes()
        self.server.run_notice_entries()
        self.assertEqual((self.tmp / "inbox" / "orchestrator.jsonl").read_bytes(),
                         before)
        self.assertFalse((self.tmp / "inbox" / "orchestrator.read").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
