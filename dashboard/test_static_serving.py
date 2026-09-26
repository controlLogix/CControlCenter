"""A filesystem that would not answer is not a request that was refused.

WHAT THIS IS FOR. The tree is on 9p, where a stat or a read raises EIO under
load. Two handlers in server.py caught that and answered about the REQUEST:
one said 403 forbidden, the other said 404 not found. Both are lies, and the
second one is the expensive kind, because it is a lie the browser believes.

TM-031, reproduced 2026-09-25 under 32-core load:

    The resource from "http://127.0.0.1:55633/kanban.js" was blocked due to
    MIME type ("application/json") mismatch (X-Content-Type-Options: nosniff)

That is the 404 body. send_json sets application/json, the handler sets nosniff
on every response, and Firefox correctly refuses to execute JSON as a script.
So kanban.js never loaded, the board never rendered its agent rows, and the e2e
suite reported `waitForFunction: Timeout exceeded` - three layers from the
cause. The first fix attempt raised that timeout from 25s to 60s and changed
nothing, which is the useful part of the story: no budget is long enough for a
script that is never going to load, and a symptom that looks like slowness is
not evidence of slowness.

WHAT IS ASSERTED HERE, and why each one is separate:

  - absence still reads as 404. The fix must not turn a genuinely missing file
    into a retryable error, or a typo in a script tag becomes a hang.
  - a transient failure reads as 503, never 404 and never 403. This is the
    whole bug.
  - a transient failure is RETRIED first, so the common case is that nobody
    ever sees the 503. A fix that only relabelled the error would leave the
    board still not rendering.
  - a non-transient error is not retried, so a real permission problem surfaces
    at once instead of three times slower.
  - and the shape that actually broke: a request for a .js path must never be
    answered with an application/json body under any failure this module can
    produce. That one is deliberately phrased as the browser saw it rather than
    as the code does it, because it is the assertion that survives someone
    rewriting the handler.
"""
import errno
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# Set before server is imported: AGENTMUX_HOME is read at import time, and
# without this the suite would read and write the operator's real home.
_TEMP = tempfile.TemporaryDirectory()
os.environ['AGENTMUX_HOME'] = _TEMP.name

import ninep
import server


def eio(message='Input/output error'):
    return OSError(errno.EIO, message)


class ReadRetryingTests(unittest.TestCase):
    """The unit that keeps 'absent' and 'could not tell' apart."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.file = Path(self.dir.name) / 'kanban.js'
        self.file.write_bytes(b'export const board = 1;\n')
        self.slept = []

    def read(self, path=None, **kw):
        kw.setdefault('_sleep', self.slept.append)
        return ninep.read_retrying(path or self.file, **kw)

    def test_a_readable_file_comes_back_whole(self):
        self.assertEqual(self.read(), b'export const board = 1;\n')
        self.assertEqual(self.slept, [], 'a successful read must not sleep')

    def test_a_transient_failure_is_retried_and_then_succeeds(self):
        with mock.patch.object(Path, 'read_bytes',
                               side_effect=[eio(), b'recovered']) as rb:
            self.assertEqual(self.read(), b'recovered')
        self.assertEqual(rb.call_count, 2, 'it must actually try again')
        self.assertEqual(len(self.slept), 1, 'and wait between attempts')

    def test_a_persistent_transient_failure_is_raised_not_disguised(self):
        with mock.patch.object(Path, 'read_bytes', side_effect=eio()):
            with self.assertRaises(OSError) as caught:
                self.read()
        self.assertEqual(caught.exception.errno, errno.EIO)
        self.assertNotIsInstance(caught.exception, FileNotFoundError,
                                 'EIO must never be reported as absence')

    def test_it_gives_up_after_the_stated_number_of_attempts(self):
        with mock.patch.object(Path, 'read_bytes', side_effect=eio()) as rb:
            with self.assertRaises(OSError):
                self.read(attempts=4)
        self.assertEqual(rb.call_count, 4)

    def test_a_missing_file_is_absence_not_a_transient_failure(self):
        with self.assertRaises(FileNotFoundError):
            self.read(Path(self.dir.name) / 'nope.js')

    def test_a_directory_is_absence_rather_than_an_unreadable_file(self):
        # A browser asking for a path that happens to be a directory has asked
        # for something that does not exist as a file. Retrying it forever
        # would be the wrong answer to a permanent condition.
        with self.assertRaises(FileNotFoundError):
            self.read(Path(self.dir.name))

    def test_a_permission_error_is_surfaced_immediately(self):
        with mock.patch.object(Path, 'read_bytes',
                               side_effect=PermissionError(errno.EACCES, 'denied')) as rb:
            with self.assertRaises(PermissionError):
                self.read()
        self.assertEqual(rb.call_count, 1, 'a permanent error must not be retried')
        self.assertEqual(self.slept, [])

    def test_eio_is_in_the_transient_set_and_enoent_is_not(self):
        # The two sets are the whole decision; assert them directly so a future
        # edit that empties TRANSIENT fails here rather than silently disabling
        # every retry above.
        self.assertIn(errno.EIO, ninep.TRANSIENT)
        self.assertNotIn(errno.ENOENT, ninep.TRANSIENT)
        self.assertIn(errno.ENOENT, ninep.ABSENT)
        self.assertFalse(ninep.TRANSIENT & ninep.ABSENT,
                         'an errno cannot mean both absent and retryable')


class StaticResponseTests(unittest.TestCase):
    """The same distinction, asserted through a real HTTP response."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def get(self, path):
        """Returns (status, content_type, body) without raising on 4xx/5xx."""
        url = f'http://127.0.0.1:{self.port}{path}'
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                return response.status, response.headers.get('Content-Type'), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers.get('Content-Type'), exc.read()

    def test_a_real_script_is_served_as_a_script(self):
        status, ctype, body = self.get('/kanban.js')
        self.assertEqual(status, 200)
        self.assertIn('text/javascript', ctype)
        self.assertTrue(body, 'the file is not empty on disk')

    def test_a_path_that_is_not_served_is_still_a_flat_404(self):
        status, _, _ = self.get('/not-a-real-file.js')
        self.assertEqual(status, 404)

    def test_a_missing_file_behind_a_served_path_is_404(self):
        with mock.patch.object(server.ninep, 'read_retrying',
                               side_effect=FileNotFoundError(errno.ENOENT, 'gone')):
            status, _, _ = self.get('/kanban.js')
        self.assertEqual(status, 404, 'absence has not changed meaning')

    def test_an_unreadable_file_is_503_and_not_404(self):
        # THE regression. 404 told the browser the script does not exist, which
        # is both false and unrecoverable; 503 says come back, and says it in a
        # status a script tag reports as a load failure rather than as a
        # confusing MIME warning.
        with mock.patch.object(server.ninep, 'read_retrying', side_effect=eio()):
            status, _, _ = self.get('/kanban.js')
        self.assertEqual(status, 503)

    def test_the_unreadable_response_tells_the_caller_to_retry(self):
        with mock.patch.object(server.ninep, 'read_retrying', side_effect=eio()):
            url = f'http://127.0.0.1:{self.port}/kanban.js'
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(url, timeout=10)
        self.assertEqual(caught.exception.headers.get('Retry-After'), '1')

    def test_an_unreadable_file_is_not_reported_as_forbidden_either(self):
        # The other half of the bug: resolve() crosses 9p too, and its failure
        # used to come back as 403. A caller chasing a permissions problem that
        # does not exist is no better off than one chasing a missing file.
        with mock.patch.object(server.Path, 'resolve', side_effect=eio()):
            status, _, _ = self.get('/kanban.js')
        self.assertEqual(status, 503)

    def test_a_forbidden_path_is_still_forbidden(self):
        # The transient branch must not swallow the traversal guard.
        status, _, _ = self.get('/../server.py')
        self.assertIn(status, (403, 404),
                      'path traversal must not become a retryable error')

    def test_an_unreadable_agent_log_is_503_not_404(self):
        # The stream handler had the identical defect. A 404 there says the
        # agent has produced no output, which is exactly what a dead pane looks
        # like - so the operator goes and stares at tmux instead of at the
        # filesystem that actually failed.
        with mock.patch.object(server, 'tmux', return_value='alpha\n'), \
             mock.patch.object(server, 'open_log', side_effect=eio()):
            status, _, _ = self.get('/api/stream/alpha')
        self.assertEqual(status, 503)

    def test_a_missing_agent_log_is_still_404(self):
        with mock.patch.object(server, 'tmux', return_value='alpha\n'), \
             mock.patch.object(server, 'open_log',
                               side_effect=FileNotFoundError(errno.ENOENT, 'gone')):
            status, _, _ = self.get('/api/stream/alpha')
        self.assertEqual(status, 404)

    def test_an_unsafe_agent_log_is_still_forbidden(self):
        # open_log raises PermissionError by design for a hard-linked or
        # symlinked log. That must stay a 403 and must not become retryable.
        with mock.patch.object(server, 'tmux', return_value='alpha\n'), \
             mock.patch.object(server, 'open_log',
                               side_effect=PermissionError('unsafe log file')):
            status, _, _ = self.get('/api/stream/alpha')
        self.assertEqual(status, 403)

    def test_no_failure_answers_a_script_request_with_a_json_body(self):
        # Phrased as the browser experienced it. Under nosniff - which this
        # handler sets on every response - a JSON body for a <script src> is
        # refused outright, and that silence is what cost a day. A 404 or 503
        # STATUS is fine; a 2xx carrying JSON for a .js path is not.
        for label, patch in (
            ('unreadable', mock.patch.object(server.ninep, 'read_retrying', side_effect=eio())),
            ('absent', mock.patch.object(server.ninep, 'read_retrying',
                                         side_effect=FileNotFoundError(errno.ENOENT, 'gone'))),
        ):
            with self.subTest(label):
                with patch:
                    status, ctype, _ = self.get('/kanban.js')
                if 200 <= status < 300:
                    self.assertIn('javascript', ctype or '',
                                  f'{label}: a successful .js response must be javascript')
                else:
                    self.assertGreaterEqual(status, 400,
                                            f'{label}: a JSON body must carry an error status')


class ResourceCheckTests(unittest.TestCase):
    """The reporting surface had it too, where it is quieter and no less wrong."""

    def check(self, path):
        return server._run_check({'id': 'x', 'label': 'x', 'type': 'file', 'path': str(path)})

    def test_a_missing_file_reads_as_absent(self):
        out = self.check('/definitely/not/here/at/all')
        self.assertFalse(out['ok'])
        self.assertEqual(out['detail'], 'absent')

    def test_an_unreadable_file_does_not_read_as_absent(self):
        # A panel whose job is to say whether a thing is configured must not
        # answer "no" when what happened is that it could not look. The operator
        # would go and re-create a file that is already there.
        with mock.patch.object(Path, 'lstat', side_effect=eio()):
            out = self.check('/mnt/c/Dev/agentmux/dashboard/server.py')
        self.assertFalse(out['ok'])
        self.assertNotEqual(out['detail'], 'absent')
        self.assertIn('unreadable', out['detail'])


def main():
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    failed = len(result.failures) + len(result.errors)
    print(f'passed {result.testsRun - failed - len(result.skipped)}, failed {failed}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
