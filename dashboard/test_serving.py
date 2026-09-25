"""A dashboard left behind by a gate run must say so.

WHAT THIS IS FOR. run_tests.sh displaces the operator's dashboard onto a
throwaway home for the length of a gate run and restores it afterwards. When
that restore went wrong the page looked ENTIRELY NORMAL: it answered on 8787,
every panel rendered, and it simply served different files than the ones on
disk. Nothing warned, because by the takeover marker's own definition the
restore had succeeded - and an operator editing app.js saw no effect and no
reason to suspect the server. TM-020.

The server cannot tell the wrong checkout from the right one; both are a
directory with a dashboard/ in it. So these assert the two things it CAN say:
which checkout it is serving, always, and whether a gate left it behind.

NEVER RAISES is a property in its own right here. This runs on every page load,
and a status endpoint that can 500 is worse than one that reports what it could
not determine - the whole point is to be the thing still working when something
else is not.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# AGENTMUX_HOME is read at import time, so it has to be set before server is
# imported - and to a temporary directory, or these tests would read and write
# the operator's real home.
_TEMP = tempfile.TemporaryDirectory()
os.environ['AGENTMUX_HOME'] = _TEMP.name
try:
    import server
    import suite_server
except ImportError as exc:
    server = suite_server = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


def dead_pid():
    """A pid that is provably not running: allocate one and reap it."""
    import subprocess
    p = subprocess.Popen([sys.executable, '-c', ''])
    p.wait()
    return p.pid


class _NeedsServer(unittest.TestCase):
    def setUp(self):
        if server is None:
            self.fail(f'server/suite_server did not import: {IMPORT_ERROR}')
        self.home = Path(_TEMP.name)
        self.marker = self.home / suite_server.MARKER_NAME
        self.addCleanup(lambda: self.marker.unlink(missing_ok=True))

    def snapshot(self):
        return server.serving_snapshot()


class WhichCheckoutTests(_NeedsServer):
    def test_it_names_the_checkout_whose_files_are_being_served(self):
        # server.py resolves app.js, index.html, style.css and assets/ relative
        # to itself, so THIS is the answer to "which code am I looking at" -
        # not the working directory, which can differ.
        snapshot = self.snapshot()
        self.assertEqual(snapshot['root'], str(HERE.parent))
        self.assertTrue(Path(snapshot['root'], 'dashboard', 'server.py').is_file())

    def test_it_reports_the_home_and_the_pid(self):
        snapshot = self.snapshot()
        self.assertEqual(snapshot['home'], str(self.home))
        self.assertEqual(snapshot['pid'], os.getpid())
        self.assertIn('cwd', snapshot)

    def test_it_carries_nothing_but_paths_and_a_pid(self):
        # Rendered on every page load, so it must not become a place secrets
        # accumulate. Assert the shape rather than trusting future edits.
        allowed = {'root', 'cwd', 'home', 'pid', 'takeover', 'takeover_error'}
        self.assertLessEqual(set(self.snapshot()), allowed)


# read_marker refuses any marker it cannot prove is ours, which it does with
# os.getuid - so on Windows every marker reads as absent and these would fail for
# a reason that has nothing to do with the property. The gate runs in WSL; say
# why rather than quietly passing a weaker version here.
@unittest.skipUnless(hasattr(os, 'getuid'),
                     'marker ownership is checked with os.getuid, which this platform lacks')
class TakeoverTests(_NeedsServer):
    def mark(self, gate_pid):
        suite_server.write_marker(str(self.home), str(self.home / 'test-home'),
                                  gate_pid, str(HERE.parent))

    def test_no_marker_means_nothing_to_report(self):
        self.assertIsNone(self.snapshot()['takeover'])

    def test_a_marker_whose_gate_is_gone_is_stranded(self):
        # The invisible failure: the dashboard is up, the page is fine, and a
        # gate run displaced it and never put it back.
        self.mark(dead_pid())
        takeover = self.snapshot()['takeover']
        self.assertIsNotNone(takeover, 'a stranded dashboard reported nothing')
        self.assertEqual(takeover['state'], 'stranded')
        # The banner tells the operator what to run, so both halves have to be here.
        self.assertEqual(takeover['operator_home'], str(self.home))
        self.assertEqual(takeover['repo'], str(HERE.parent))

    def test_a_marker_whose_gate_is_alive_is_in_progress_not_an_alarm(self):
        # A gate run is MEANT to do this, and it restores on exit. Reporting it
        # as a fault would make the banner cry wolf on every gate run, and a
        # banner that cries wolf is one nobody reads.
        self.mark(os.getpid())
        takeover = self.snapshot()['takeover']
        self.assertEqual(takeover['state'], 'in_progress')

    def test_a_corrupt_marker_reports_nothing_rather_than_failing(self):
        # read_marker returns None on every anomaly, and this must inherit that:
        # a corrupt note turning the dashboard's status endpoint into a 500 is
        # the opposite of what it is for.
        self.marker.write_text('not json at all', encoding='utf-8')
        snapshot = self.snapshot()
        self.assertIsNone(snapshot['takeover'])
        self.assertNotIn('takeover_error', snapshot)

    def test_a_marker_of_an_unknown_version_is_refused(self):
        import json
        self.marker.write_text(json.dumps({'version': 99, 'operator_home': '/x',
                                           'test_home': '/y', 'repo': '/z',
                                           'gate_pid': 1}), encoding='utf-8')
        self.assertIsNone(self.snapshot()['takeover'])


def main():
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    failed = len(result.failures) + len(result.errors)
    print(f'passed {result.testsRun - failed - len(result.skipped)}, failed {failed}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
