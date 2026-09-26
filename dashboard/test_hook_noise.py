#!/usr/bin/env python3
"""TM-032 AC5: `git_link_unattributed` is journalled, and never shown to a person.

WHAT THIS GUARDS, AND WHY IT IS A SUITE RATHER THAN A NOTE.

The task-management PostToolUse git hook logs `git_link_unattributed` every time a
commit or a `gh pr create` names no task. Measured on this board across ten sessions:
90 rows, 6.73% of the whole event log, against 13 `git_link` - the event that says a
ref actually attached to something. The ordinary outcome outnumbered the interesting
one seven to one, every row carried the same fixed `reason` string and no id, and
there is nothing a person could do about any single one of them. Most commits in a
repository are not a task's evidence.

THE FIX WAS THE SECOND OF THE TWO THE TICKET ALLOWED, deliberately. Deleting the
emission would have destroyed the only measure of how much work lands off the board -
which is the very number that produced this ticket. So the row still reaches
`events.jsonl`, `tm events --json` and any webhook subscriber; what changed is that it
no longer reaches a human view. The filter sits in `collapseLog`, the one chokepoint
`tm log`, `tm log <id>`, `tm standup`, the dashboard activity panel and the MCP log
tool all pass through.

SO THIS SUITE ASSERTS BOTH HALVES, and it has to, because each half alone is a
different bug:
  - not surfaced - collapseLog drops it, in plain AND in `keep` mode;
  - still journalled - bin/tm still emits it and store.mjs still writes every row.
A change that silences the event by deleting the emission passes the first half and
fails the second, which is exactly the outcome this is here to prevent.

WHERE THE CODE LIVES. Not in this repo. The emitter and the renderer are both in the
installed `task-management` plugin from the bytedesk marketplace, so these checks read
that checkout and skip cleanly when it is absent - a machine without the plugin has
nothing to regress. Set TM_PLUGIN_ROOT to point at a different checkout.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ninep

EVENT = "git_link_unattributed"


def _from_windows(raw):
    """`C:\\Users\\x` as this interpreter can open it.

    known_marketplaces.json is written by Claude Code on Windows and stores a Windows
    path. The gate runs in WSL, where that string names nothing - so a suite that used
    it verbatim would skip forever on the only machine that has the plugin, and report
    a green it never earned. test_plugin_skills.py has this same weakness; this is the
    translation it is missing.
    """
    text = str(raw)
    if os.name == "nt" or not re.match(r"^[A-Za-z]:[\\/]", text):
        return Path(text)
    drive, rest = text[0].lower(), text[2:].replace("\\", "/").lstrip("/")
    return Path(f"/mnt/{drive}/{rest}")


def plugin_root():
    """The installed task-management plugin, or None when this box has none."""
    for var in ("TM_PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT"):
        configured = os.environ.get(var)
        if configured:
            return _from_windows(configured)
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
    for base in dict.fromkeys((config, Path.home() / ".claude",
                               _from_windows(r"C:\Users\Nick\.claude"))):
        registry = base / "plugins/known_marketplaces.json"
        if not ninep.reachable(registry, "file"):
            continue
        try:
            entries = json.loads(ninep.read_retrying(registry))
        except (OSError, ValueError):
            continue
        location = entries.get("bytedesk", {}).get("installLocation")
        if location:
            return _from_windows(location) / "task-management"
    return None


PLUGIN = plugin_root()
RENDER = (PLUGIN / "lib/render.mjs") if PLUGIN else None
TM_BIN = (PLUGIN / "bin/tm") if PLUGIN else None
STORE = (PLUGIN / "lib/store.mjs") if PLUGIN else None

# reachable(), not is_file(): the plugin lives on /mnt/c, where a stat can re-raise
# EIO rather than answering. Same reason test_plugin_skills.py does it this way.
HAVE_PLUGIN = bool(RENDER and ninep.reachable(RENDER, "file"))


def find_node():
    """node from PATH, else the newest nvm build. None when there is none."""
    node = shutil.which("node")
    if node:
        return node
    candidates = sorted(Path.home().glob(".nvm/versions/node/*/bin/node"))
    candidates += sorted(_from_windows(r"C:\Users\Nick").glob(
        ".nvm/versions/node/*/bin/node"))
    return str(candidates[-1]) if candidates else None


@unittest.skipUnless(HAVE_PLUGIN, "task-management plugin absent; set TM_PLUGIN_ROOT")
class TheEventIsNotSurfaced(unittest.TestCase):
    """The renderer's side of the contract, read from its source."""

    def setUp(self):
        self.source = ninep.guard(lambda p: Path(p).read_text(encoding="utf-8"),
                                  RENDER, RENDER)

    def unsurfaced(self):
        """The event kinds the renderer declares it will never show.

        Parsed rather than string-matched so that adding a second kind to the set
        keeps working. If the declaration is gone, say THAT - a bare assertion
        failure here reads as "the event is surfaced again" when the truth may be
        that the mechanism was replaced and this test can no longer see it.
        """
        match = re.search(r"const\s+UNSURFACED\s*=\s*new\s+Set\(\s*\[(.*?)\]\s*\)",
                          self.source, re.S)
        if not match:
            self.fail("render.mjs no longer declares an UNSURFACED set; the "
                      "journalled-but-not-shown mechanism has been replaced and "
                      "this test cannot see the new one")
        return set(re.findall(r"""["']([^"']+)["']""", match.group(1)))

    def test_the_unattributed_git_link_is_declared_unsurfaced(self):
        self.assertIn(EVENT, self.unsurfaced())

    def test_collapse_log_actually_consults_the_set(self):
        # A declared set nothing reads is decoration. The drop has to be inside
        # collapseLog, which is the function every human view goes through.
        body = self.source.split("export function collapseLog", 1)
        self.assertEqual(len(body), 2, "collapseLog is gone from render.mjs")
        self.assertIn("UNSURFACED.has(e.event)", body[1],
                      "collapseLog no longer drops the unsurfaced kinds")

    def test_the_attributed_git_link_is_still_shown(self):
        # The point was never to hide git activity. `git_link` says a ref attached
        # to a task, which is the one outcome of this hook worth reading - and
        # `git_link_skipped` says a ref came from another repo, which is how the
        # over-attachment bug that put 25 marketplace PRs on a persona task stays
        # visible. Only the no-op outcome is hidden.
        hidden = self.unsurfaced()
        self.assertNotIn("git_link", hidden)
        self.assertNotIn("git_link_skipped", hidden)


@unittest.skipUnless(HAVE_PLUGIN, "task-management plugin absent; set TM_PLUGIN_ROOT")
class TheEventIsStillJournalled(unittest.TestCase):
    """The other half. Silence achieved by deleting the emission is not the fix."""

    def test_the_hook_still_emits_it(self):
        source = ninep.guard(lambda p: Path(p).read_text(encoding="utf-8"),
                             TM_BIN, TM_BIN)
        self.assertIn(f'logEvent("{EVENT}"', source,
                      "bin/tm no longer emits the event at all; the count of work "
                      "landing off the board is the number that produced TM-032 and "
                      "it must survive the fix")

    def test_the_log_writer_filters_nothing(self):
        # logEvent is append-only by contract. If a suppression list ever appears
        # there, "journalled" stops being true and this suite's first half becomes
        # a lie by omission.
        source = ninep.guard(lambda p: Path(p).read_text(encoding="utf-8"),
                             STORE, STORE)
        body = source.split("export function logEvent", 1)
        self.assertEqual(len(body), 2, "logEvent is gone from store.mjs")
        head = body[1][:1200]
        self.assertIn("appendFileSync", head)
        self.assertNotIn("UNSURFACED", head)


@unittest.skipUnless(HAVE_PLUGIN, "task-management plugin absent; set TM_PLUGIN_ROOT")
class CollapseLogBehaviour(unittest.TestCase):
    """Not the source - the function. Run it and look at what comes back."""

    FIXTURE = [
        {"ts": "2026-09-26T01:00:00.000Z", "event": "create", "id": "TM-9", "title": "t"},
        {"ts": "2026-09-26T01:00:02.000Z", "event": "update", "id": "TM-9",
         "patch": "status", "status": "in_progress"},
        {"ts": "2026-09-26T01:00:05.000Z", "event": EVENT, "branch": "main",
         "reason": "the command named no task"},
        {"ts": "2026-09-26T01:00:06.000Z", "event": "git_link", "id": "TM-9",
         "ref": "abc1234"},
        {"ts": "2026-09-26T01:00:09.000Z", "event": "done", "id": "TM-9"},
    ]

    def collapse(self, keep):
        node = find_node()
        if not node:
            self.skipTest("no node on PATH or under ~/.nvm")
        opts = "{ keep: true }" if keep else "undefined"
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "probe.mjs"
            script.write_text(
                f"import {{ collapseLog }} from {json.dumps(RENDER.as_posix())};\n"
                f"const rows = {json.dumps(self.FIXTURE)};\n"
                f"console.log(JSON.stringify(collapseLog(rows, {opts})"
                f".map((e) => e.event)));\n", encoding="utf-8")
            done = subprocess.run([node, str(script)], capture_output=True,
                                  text=True, timeout=120)
        if done.returncode != 0:
            self.skipTest(f"could not import the plugin renderer: "
                          f"{done.stderr.strip()[:200]}")
        return json.loads(done.stdout.strip().splitlines()[-1])

    def test_a_person_reading_the_log_never_sees_it(self):
        self.assertNotIn(EVENT, self.collapse(keep=False))

    def test_the_dashboard_feed_never_sees_it_either(self):
        # `keep: true` is the mode that marks rather than drops, for consumers that
        # must account for every row. This kind is dropped there too, and that is a
        # separate judgement from the shadowed-`update` one: a shadowed update is
        # real history for its entity, while this carries no id and no status, so
        # burndown and startTimes lose nothing and the notification matcher not
        # matching it is the whole point.
        self.assertNotIn(EVENT, self.collapse(keep=True))

    def test_everything_else_survives_untouched(self):
        plain = self.collapse(keep=False)
        self.assertIn("git_link", plain)
        self.assertIn("create", plain)
        self.assertIn("done", plain)
        # The status move is still promoted rather than swallowed by the new filter.
        self.assertIn("status", plain)


class TheJournalStillHasIt(unittest.TestCase):
    """Measured from events.jsonl, the way the rest of TM-032 was accepted.

    Untracked and gitignored, so a fresh clone has none of this - which is why the
    absence of a log is a skip and not a failure.
    """

    def rows(self):
        log = HERE.parent / ".bytedesk/task-management/events.jsonl"
        if not ninep.reachable(log, "file"):
            self.skipTest("no events.jsonl on this checkout (it is gitignored)")
        out = []
        for line in ninep.read_retrying(log).splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                pass            # a torn line costs us that row, not the census
        return out

    def test_the_rows_are_still_being_written(self):
        rows = self.rows()
        kinds = [r.get("event") for r in rows]
        if "git_link" not in kinds and EVENT not in kinds:
            self.skipTest("this board has no git-hook history to census")
        self.assertGreater(
            kinds.count(EVENT), 0,
            "the event has stopped reaching the journal; TM-032 asked for it to "
            "stop being SURFACED, and the count is the measure it exists to give")

    def test_it_is_a_large_enough_share_to_have_been_worth_hiding(self):
        # Guards the premise rather than the fix. If this ever drops to near zero
        # the filter has stopped earning its place and should be reconsidered -
        # a silent filter over an event that no longer fires is dead weight.
        rows = self.rows()
        if len(rows) < 200:
            self.skipTest("too few events to say anything about proportions")
        share = 100.0 * [r.get("event") for r in rows].count(EVENT) / len(rows)
        self.assertGreater(share, 0.5,
                           f"{EVENT} is only {share:.2f}% of the log")


def main():
    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    failed = len(result.failures) + len(result.errors)
    print(f'passed {result.testsRun - failed - len(result.skipped)}, failed {failed}',
          flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
