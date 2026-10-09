"""The local loop must not turn failing subtests or missing fixtures into a pass."""
import io
import contextlib
import os
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hub.tests.run_local import TimedResult, main, selector


class RunnerTests(unittest.TestCase):
    def run_fixture(self, case):
        return unittest.TextTestRunner(stream=io.StringIO(), resultclass=TimedResult).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(case))

    def test_subtest_failure_saves_loadable_parent(self):
        class Example(unittest.TestCase):
            def test_case(self):
                with self.subTest(value=1):
                    self.fail("deliberate fixture failure")
        result = self.run_fixture(Example)
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(result.failed_names, {Example('test_case').id()})
        self.assertEqual(len(result.timings), 1)

    def test_class_setup_failure_saves_class(self):
        class Example(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                raise RuntimeError("deliberate setup failure")
            def test_case(self):
                pass
        result = self.run_fixture(Example)
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(result.failed_names, {Example('test_case').id().rsplit('.', 1)[0]})

    def test_regular_selector_is_unchanged(self):
        self.assertEqual(selector(self), self.id())

    def test_skipped_or_empty_selection_cannot_pass(self):
        class Example(unittest.TestCase):
            @unittest.skip("deliberately unavailable fixture")
            def test_case(self):
                pass
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"XDG_CACHE_HOME": tmp}), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            for suite in (unittest.defaultTestLoader.loadTestsFromTestCase(Example), unittest.TestSuite()):
                with patch('unittest.defaultTestLoader.loadTestsFromNames', return_value=suite):
                    self.assertEqual(main(['example']), 1)

    def test_failed_selection_can_be_retried_without_running_other_suites(self):
        class Example(unittest.TestCase):
            broken = True
            def test_case(self):
                self.assertFalse(self.broken)
        def suite(_):
            return unittest.defaultTestLoader.loadTestsFromTestCase(Example)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"XDG_CACHE_HOME": tmp}), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                patch('unittest.defaultTestLoader.loadTestsFromNames', side_effect=suite) as loader:
            self.assertEqual(main(['example']), 1)
            Example.broken = False
            self.assertEqual(main(['--failed']), 0)
            loader.assert_called_with([Example('test_case').id()])
            loader.reset_mock()
            self.assertEqual(main(['--failed']), 0)
            loader.assert_not_called()

    def test_import_error_retries_original_selection(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"XDG_CACHE_HOME": tmp}), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['hub.tests.does_not_exist']), 1)
            saved = next(Path(tmp).rglob('failed.json'))
            self.assertEqual(json.loads(saved.read_text())['tests'], ['hub.tests.does_not_exist'])
