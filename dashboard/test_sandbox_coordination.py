#!/usr/bin/env python3
"""TM-068 offline regressions: no live server, socket or operator state."""
import contextlib
from dataclasses import replace
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'taskmgmt'))
TEMP = tempfile.TemporaryDirectory(prefix='sandbox-coordination-')
os.environ['AGENTMUX_HOME'] = TEMP.name
import coordination as co
import dispatch
import agentdefs


class SandboxCoordination(unittest.TestCase):
    def test_live_and_empty(self):
        for output, expected in [('alice\nbob\n', {'alice', 'bob'}), ('', set())]:
            with patch.object(co.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output, '')):
                self.assertEqual(co.live_agents(), expected)
        for detail in ['no sessions', 'no server running on /tmp/tmux-1000/agentmux',
                       'error connecting to /tmp/tmux-1000/identity-test-1234 (No such file or directory)',
                       'error connecting to /tmp/tmux-1000/identity-test-1234 (ENOENT)']:
            with self.subTest(detail=detail), patch.object(co.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', detail)):
                self.assertEqual(co.live_agents(), set())

    def test_unreachable_is_not_empty(self):
        for detail in ['Operation not permitted', 'Permission denied', 'EACCES', 'EPERM', 'Connection refused', 'unexpected error']:
            with self.subTest(detail=detail), patch.object(co.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', detail)):
                with self.assertRaisesRegex(co.TmuxUnavailable, 'tmux unreachable.*' + detail):
                    co.live_agents()
        for error in [PermissionError('denied'), FileNotFoundError('tmux'), subprocess.TimeoutExpired('tmux', 10)]:
            with patch.object(co.subprocess, 'run', side_effect=error):
                with self.assertRaisesRegex(co.TmuxUnavailable, 'liveness is unknown'):
                    co.live_agents()

    def test_mutations_refuse_with_actual_cause(self):
        for args in [['claim', 'file.py', '--holder', 'worker'], ['journal', 'note', 'test'], ['task-evidence', 'TM-068', 'tmp/proof.txt']]:
            err = io.StringIO()
            with patch.dict(os.environ, {'AGENTMUX_AGENT': 'worker', 'AGENTMUX_TRUST_IDENTITY': '0'}), patch.object(co.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'Operation not permitted')), patch.object(co, 'journal') as journal, patch.object(co, 'board_call') as board, contextlib.redirect_stderr(err):
                self.assertEqual(co.main(args), 2)
                self.assertIn('tmux unreachable', err.getvalue())
                self.assertIn('sandbox', err.getvalue())
                self.assertNotIn('not a live agent', err.getvalue())
                journal.assert_not_called()
                board.assert_not_called()

    def test_dispatch_refuses_before_spawn_even_dry_run(self):
        fallback = agentdefs.choose_roster({}, {}, {})[0]
        for posture, brake in [('workspace-write', '0'), ('read-only', '0'), ('unrestricted', '1')]:
            for dry in [False, True]:
                spec = replace(fallback, posture=posture)
                task = {'id': 'TM-068', 'title': 'sandbox test'}
                with patch.dict(os.environ, {'AGENTMUX_NO_BYPASS': brake}), patch.object(dispatch, 'dispatch_view', return_value={'tasks': [task]}), patch.object(dispatch, 'entity', return_value=task), patch.object(dispatch, 'live_agents', return_value=set()), patch.object(agentdefs, 'load_all', return_value=({}, [])), patch.object(agentdefs, 'choose_roster', return_value=[spec]), patch.object(dispatch, 'agentmux') as spawn, patch.object(dispatch, 'claim_for') as claim, patch.object(dispatch, 'set_status') as status, patch.object(dispatch, 'log') as log:
                    self.assertIsNone(dispatch.dispatch_one('TM-068', dry_run=dry))
                    spawn.assert_not_called()
                    claim.assert_not_called()
                    status.assert_not_called()
                    self.assertIn('sandbox', log.call_args.args[0])
                    self.assertIn('posture=' + posture, log.call_args_list[0].args[0])

    def test_lead_selection_policy_and_visible_posture(self):
        fallback = agentdefs.choose_roster({}, {}, {})[0]
        self.assertEqual(fallback.posture, 'unrestricted')
        z = replace(fallback, name='z-lead', posture='workspace-write')
        a = replace(fallback, name='a-lead', posture='read-only')
        worker = replace(fallback, name='aaa-worker', role='worker')
        self.assertEqual(agentdefs.choose_roster({}, {s.name: s for s in [z, a, worker]}, {})[0], a)

    def test_team_spawn_refuses_effective_sandbox(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tmux = root / 'tmux'
            tmux.write_text('#!/bin/sh\nexit 1\n')
            tmux.chmod(0o755)
            shell = root / 'agentmux.sh'
            shell.write_text((REPO / 'agentmux.sh').read_text())
            for posture, brake in [('workspace-write', '0'), ('read-only', '0'), ('unrestricted', '1')]:
                env = dict(os.environ, AGENTMUX_HOME=str(root / 'state'), PATH=str(root) + ':' + os.environ['PATH'], AGENTMUX_NO_BYPASS=brake)
                result = subprocess.run(['bash', str(shell), 'spawn', 'sandbox-test', '--cli', 'codex', '--cwd', folder, '--team', 'TM-068', '--posture', posture], env=env, capture_output=True, text=True, timeout=15)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('sandbox posture', result.stderr)
                self.assertIn('coordination', result.stderr)
                self.assertEqual(list((root / 'state/run').iterdir()), [])

    def test_notification_reports_unknown_without_undoing_claim(self):
        err = io.StringIO()
        with patch.object(co, 'live_agents', side_effect=co.TmuxUnavailable('tmux unreachable')), patch.object(co, 'post') as post, contextlib.redirect_stderr(err):
            self.assertEqual(co.broadcast('worker', 'claim', 'claimed'), 0)
            self.assertIn('Notification skipped', err.getvalue())
            post.assert_not_called()

    def test_collect_aborts_when_liveness_unknown(self):
        with patch.object(dispatch, 'live_agents', side_effect=co.TmuxUnavailable('tmux unreachable')), patch.object(dispatch, 'set_status') as status, patch.object(dispatch, 'release_all') as release:
            with self.assertRaises(co.TmuxUnavailable):
                dispatch.collect_one('TM-068', {'id': 'TM-068'})
            status.assert_not_called()
            release.assert_not_called()


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SandboxCoordination))
    TEMP.cleanup()
    failed = len(result.failures) + len(result.errors)
    print(f'passed {result.testsRun - failed}, failed {failed}', flush=True)
    sys.exit(bool(failed))
