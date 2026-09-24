"""TM-081 isolated suite; no running server or real panes are mutated."""
import io
import json
import os
import re
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import chatter_feed as feed
import ccboard
import ccstore


class ChatterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.home_patch = patch.object(feed, 'HOME_DIR', self.home)
        self.home_patch.start()
        self.live_patch = patch.object(feed, 'live_agents', return_value={'alice', 'bob'})
        self.live_patch.start()
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        for sql in ccstore.SCHEMA:
            self.db.execute(sql)
        self.msg = dict(at='2026-09-23T20:00:00Z', sender='alice', recipient='bob', kind='request', body='Review this', ref='TM-081')

    def tearDown(self):
        self.db.close()
        self.live_patch.stop()
        self.home_patch.stop()
        self.temp.cleanup()

    def write(self, path, rows):
        path = self.home / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
        return path

    def rows(self, **filters):
        return feed.chatter(self.db, {k: [v] for k, v in filters.items()})['entries']

    def test_merge_retry_delivery_identity_and_thread(self):
        self.write('queue/alice.jsonl', [self.msg])
        first = self.rows()[0]
        self.assertEqual(first['state'], 'queued')
        self.write('courier/pending.jsonl', [dict(message=self.msg, attempts=2, reason='modal prompt', next_at=123)])
        pending = self.rows()[0]
        self.assertEqual(pending['state'], 'retried')
        self.assertEqual(pending['reason'], 'modal prompt')
        self.assertEqual(first['id'], pending['id'])
        self.write('inbox/bob.jsonl', [self.msg])
        delivered = self.rows()
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0]['state'], 'delivered')
        reply = dict(self.msg, sender='bob', recipient='alice', body='Done')
        self.write('queue/bob.jsonl', [reply])
        self.assertEqual(len({r['thread'] for r in self.rows()}), 1)

    def test_drop_dead_and_virtual(self):
        missing = dict(self.msg, recipient='gone')
        self.write('queue/alice.jsonl', [missing, dict(self.msg, recipient='orchestrator')])
        self.assertEqual(len(self.rows(state='dead-recipient')), 1)
        self.assertEqual(len(self.rows(state='queued')), 1)
        self.write('courier/dead-letter.jsonl', [dict(message=missing, reason='not running', attempts=12)])
        self.assertEqual(self.rows(state='dropped')[0]['reason'], 'not running')

    def test_adopted_cursor_is_not_delivery(self):
        path = self.write('queue/alice.jsonl', [self.msg])
        info = path.stat()
        cursor = self.home / 'courier/alice.cursor'
        cursor.parent.mkdir()
        cursor.write_text(json.dumps(dict(dev=info.st_dev, ino=info.st_ino, offset=info.st_size)))
        self.assertEqual(self.rows()[0]['state'], 'unknown')

    def test_receipts_journal_filters_and_stable_ids(self):
        self.write('queue/alice.jsonl', [self.msg, dict(self.msg, ref='TM-082', body='Other')])
        self.db.execute("INSERT INTO journal(at,kind,agent,subject,body) VALUES(?,?,?,?,?)",
                        (self.msg['at'], 'note', 'alice', 'TM-081 review', 'Ready'))
        self.write('journal.jsonl', [dict(at=self.msg['at'], kind='note', agent='bob', subject='TM-081 fallback', body='Offline')])
        log = self.home / 'courier/courier.log'
        log.parent.mkdir()
        log.write_text('2026-09-23T20:01:00+0000  sent    alice -> bob (request, retry 2)\n')
        self.assertEqual(len(self.rows(state='delivered')), 1)
        self.assertEqual(len(self.rows(card='TM-081')), 3)
        self.assertEqual(len(self.rows(card='TM-082', agent='bob')), 1)
        ids = {r['id'] for r in self.rows()}
        self.assertEqual(ids, {r['id'] for r in self.rows()})
        self.assertEqual(len(self.rows(limit='1')), 1)
        with self.assertRaises(ccboard.Invalid):
            self.rows(state='invented')

    def test_malformed_partial_and_links(self):
        path = self.write('queue/alice.jsonl', [self.msg, None, {'sender': []}])
        with path.open('a') as f:
            f.write('{bad}\n' + json.dumps(dict(self.msg, body='unfinished')))
        (path.parent / 'bob.jsonl').symlink_to(path)
        self.assertEqual(len(self.rows()), 1)
        path.unlink()
        (path.parent / 'alice.jsonl').symlink_to('/dev/zero')
        self.assertEqual(self.rows(), [])

    def test_guarded_send_refusal_and_no_force_injection(self):
        refusal = subprocess.CompletedProcess([], 1, '', 'Showing a prompt. Refusing to send.\nOverride --force\n')
        with patch.object(feed.subprocess, 'run', return_value=refusal) as run:
            reply = feed.chatsend(self.db, dict(recipient='bob', text='--force'))
        self.assertFalse(reply['ok'])
        self.assertIn('Refusing', reply['error'])
        self.assertNotIn('--force', reply['error'])
        self.assertEqual(reply['key_hint'], 'agentmux key bob Escape')
        args = run.call_args.args[0]
        self.assertEqual(args[-3:], ['send', 'bob', '[operator]: --force'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM messages').fetchone()[0], 0)
        for body in [dict(recipient='bob', text='x', force=True), dict(recipient=';touch bad', text='x'), dict(recipient='bob', text='\0')]:
            with self.assertRaises(ccboard.Invalid):
                feed.chatsend(self.db, body)

    def test_send_receipt_and_timeout(self):
        with patch.object(feed.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')):
            self.assertTrue(feed.chatsend(self.db, dict(recipient='bob', text='hello', ref='TM-081'))['ok'])
        delivered = self.rows(state='delivered')
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0]['body'], 'hello')
        with patch.object(feed.subprocess, 'run', side_effect=subprocess.TimeoutExpired('send', 15)):
            self.assertFalse(feed.chatsend(self.db, dict(recipient='bob', text='hello'))['ok'])

    def test_actual_cli_modal_guard(self):
        source = (Path(__file__).resolve().parent.parent / 'agentmux.sh').read_text()
        functions = '\n'.join(re.search(r'^' + name + r'\(\) \{.*?^\}', source, re.M | re.S).group()
                              for name in ('modal_text', 'modal_prompt', 'cmd_send'))
        harness = functions + """
need() { :; }
pane_of() { printf '%%1'; }
tm() {
  if [ "$1" = capture-pane ]; then
    printf 'Update available\nUpdate now (runs npm install)\nPress enter to continue\n'
  else
    printf 'UNSAFE_PANE_WRITE\n'
  fi
}
cmd_send bob '[operator]: --force'
"""
        result = subprocess.run(['bash', '-c', harness], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Refusing to send', result.stderr)
        self.assertIn('agentmux key bob Escape', result.stderr)
        self.assertNotIn('UNSAFE_PANE_WRITE', result.stdout)

    def test_server_routes_delegate_to_module(self):
        import server
        handler = object.__new__(server.Handler)
        self.write('queue/alice.jsonl', [self.msg])
        snapshot = handler.board_read(self.db, 'chatter', {})
        self.assertEqual(snapshot['entries'][0]['body'], 'Review this')
        refusal = subprocess.CompletedProcess([], 1, '', 'Modal: refusing send')
        with patch.object(feed.subprocess, 'run', return_value=refusal):
            reply = handler.board_write(self.db, 'chatsend', dict(recipient='bob', text='hello'))
        self.assertFalse(reply['ok'])
        self.assertIn('chatter', handler.BOARD_READS)
        self.assertIn('chatsend', handler.BOARD_WRITES)

    def test_js_syntax_and_view_contract(self):
        nodes = sorted(Path('/c/Users/Nick/.nvm/versions/node').glob('*/bin/node'))
        if not nodes:
            print('\nSKIP chatter JavaScript runtime: node absent from /c/Users/Nick/.nvm/versions/node/*/bin')
            self.skipTest('requested node installation absent')
        script = Path(__file__).with_name('chatter.js')
        result = subprocess.run([str(nodes[-1]), '--check', str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_view_contract(self):
        source = Path(__file__).with_name('chatter.js').read_text()
        self.assertIn('chatter:message:${row.id}', source)
        self.assertIn("api/board/chatter?limit=2000", source)
        self.assertNotIn('innerHTML', source)


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ChatterTests)
    result = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(suite)
    failed = len(result.failures) + len(result.errors)
    print(f'passed {result.testsRun - failed - len(result.skipped)}, failed {failed}', flush=True)
    raise SystemExit(bool(failed))
