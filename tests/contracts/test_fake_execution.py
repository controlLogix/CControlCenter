"""Independent expected histories for the reusable controlled execution fixture."""
import unittest

from fake_execution import FakeProvider, FakeWorker, ResponsePlan


class ControlledExecution(unittest.TestCase):
    def setUp(self):
        self.provider = FakeProvider()
        self.worker = FakeWorker(self.provider)

    def test_success_uses_real_callback_and_separate_output_history(self):
        self.worker.start('one', 'input one', ResponsePlan(output='answer one'))
        self.provider.advance(0)
        self.assertEqual(self.worker.snapshot('one')['status'], 'running')
        self.provider.deliver('one')
        self.assertEqual(self.worker.snapshot('one')['output'], 'answer one')
        self.assertEqual(self.worker.snapshot('one')['status'], 'completed')
        self.assertEqual([r['kind'] for r in self.provider.history], ['admitted', 'completed', 'delivered'])
        self.assertEqual(self.worker.history[-1]['reply'], {'operation':'one','status':'completed','output':'answer one'})
        with self.assertRaisesRegex(ValueError, 'no queued reply'):
            self.provider.deliver('one')

    def test_delay_and_explicit_reordering_preserve_each_operation(self):
        self.worker.start('first', 'one', ResponsePlan(delay=2, output='A'), timeout=10)
        self.worker.start('second', 'two', ResponsePlan(delay=2, output='B'), timeout=10)
        self.provider.advance(1)
        self.assertEqual(self.provider.pending, {})
        self.provider.advance(1)
        self.provider.deliver('second')
        self.assertEqual(self.worker.snapshot('first')['status'], 'running')
        self.provider.deliver('first')
        callbacks = [r['operation'] for r in self.worker.history if r['kind'] == 'callback']
        self.assertEqual(callbacks, ['second', 'first'])
        self.assertEqual([self.worker.snapshot(k)['output'] for k in ('first','second')], ['A','B'])

    def test_timeout_before_execution_does_not_retry_and_late_reply_needs_lookup(self):
        self.worker.start('one', 'input', ResponsePlan(delay=8, output='late'), timeout=2)
        self.provider.advance(2); self.worker.poll_timeouts()
        self.assertEqual(self.worker.snapshot('one')['status'], 'unknown')
        with self.assertRaisesRegex(ValueError, 'reconcile'):
            self.worker.start('one', 'input', ResponsePlan())
        self.provider.advance(6); self.provider.deliver('one')
        self.assertEqual(self.worker.snapshot('one')['status'], 'unknown')
        self.assertIsNone(self.worker.snapshot('one')['output'])
        self.assertEqual(self.worker.reconcile('one')['output'], 'late')
        self.assertEqual(sum(r['kind']=='admitted' for r in self.provider.history), 1)

    def test_reply_at_deadline_is_unknown_without_polling(self):
        self.worker.start('one', '', ResponsePlan(delay=2), timeout=2)
        self.provider.advance(2); self.provider.deliver('one')
        self.assertEqual(self.worker.snapshot('one')['status'], 'unknown')
        self.assertEqual(self.worker.history[-1]['kind'], 'late_observation')

    def test_provider_unavailable_proves_no_dispatch(self):
        self.provider.available = False
        result = self.worker.start('one', '', ResponsePlan())
        self.assertEqual((result['status'], result['admitted']), ('unavailable', False))
        self.assertEqual(self.provider.requests, {})
        self.assertEqual(self.provider.pending, {})
        self.assertEqual(self.provider.history, [{'kind':'not_admitted','operation':'one','tick':0}])
        with self.assertRaisesRegex(ValueError, 'never admitted'):
            self.worker.reconcile('one')
        self.provider.available = True
        self.assertEqual(self.worker.start('two', '', ResponsePlan())['status'], 'running')

    def test_lost_reply_is_unknown_despite_completed_provider(self):
        self.worker.start('one', '', ResponsePlan(drop_reply=True, output='hidden'), timeout=2)
        self.provider.advance(2); self.worker.poll_timeouts()
        self.assertEqual(self.worker.snapshot('one')['status'], 'unknown')
        self.assertEqual(self.provider.requests['one']['state'], 'completed')
        self.assertEqual(self.provider.pending, {})
        self.assertEqual([r['kind'] for r in self.provider.history], ['admitted','completed','reply_lost'])
        self.assertEqual(self.worker.reconcile('one')['output'], 'hidden')

    def test_confirmed_cancel_stops_output_and_requires_reconciliation(self):
        self.worker.start('one', '', ResponsePlan(delay=10))
        self.assertTrue(self.worker.cancel('one'))
        self.provider.deliver('one')
        self.assertEqual(self.worker.snapshot('one')['status'], 'unknown')
        self.assertTrue(self.worker.snapshot('one')['cancellationPending'])
        result = self.worker.reconcile('one')
        self.assertEqual((result['status'], result['cancellationPending']), ('cancelled', False))
        self.provider.advance(20)
        self.assertNotIn('completed', [r['kind'] for r in self.provider.history])
        self.assertIsNone(self.worker.snapshot('one')['output'])

    def test_unconfirmed_cancel_retains_intent_after_late_completion(self):
        self.worker.start('one', '', ResponsePlan(delay=2, cancel_confirmed=False))
        self.assertFalse(self.worker.cancel('one'))
        self.provider.advance(2); self.provider.deliver('one')
        result = self.worker.reconcile('one')
        self.assertEqual((result['status'],result['cancellationPending'],result['output']), ('unknown', True, None))
        self.assertEqual(self.provider.requests['one']['state'], 'completed')

    def test_histories_and_snapshots_are_detached_from_delivered_objects(self):
        callbacks = []
        self.provider.submit('direct', '', ResponsePlan(output='original'), callbacks.append)
        self.provider.advance(0); self.provider.deliver('direct')
        callbacks[0]['output'] = 'changed'
        self.assertEqual(self.provider.history[1]['output'], 'original')
        self.assertEqual(self.provider.inspect('direct')['output'], 'original')
        self.worker.start('one', '', ResponsePlan())
        snapshot = self.worker.snapshot('one'); snapshot['status'] = 'completed'
        self.assertEqual(self.worker.snapshot('one')['status'], 'running')

    def test_invalid_controls_and_duplicate_dispatch_have_no_second_effect(self):
        for value in (-1, True, 1.5):
            with self.assertRaises(ValueError): ResponsePlan(delay=value)
            with self.assertRaises(ValueError): self.provider.advance(value)
        with self.assertRaises(ValueError): ResponsePlan(drop_reply='yes')
        with self.assertRaises(ValueError): self.worker.start('bad', '', ResponsePlan(), timeout=0)
        self.assertEqual(self.provider.history, [])
        self.worker.start('one', '', ResponsePlan())
        with self.assertRaisesRegex(ValueError, 'duplicate dispatch'):
            self.provider.submit('one', 'changed', ResponsePlan(), lambda _: None)
        self.assertEqual(len(self.provider.requests), 1)
        self.assertEqual(len(self.provider.history), 1)
