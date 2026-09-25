"""Single-use, expiring write authorisations.

The property under test is not "tickets work" but "a ticket cannot authorise
more than the one write it was minted for, and cannot do it twice". Everything
here is about what the mechanism REFUSES.

The concurrency test matters more than it looks: the sidecar is a
ThreadingHTTPServer, so two requests redeeming the same ticket at the same
instant is an ordinary thing rather than an exotic one, and "single use" has to
survive it.
"""
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'field'))
try:
    import tickets
except ImportError as exc:      # a tree without the module - see _NeedsTickets
    tickets = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None

ACTION = {'kind': 'write_tag', 'path': '10.1.2.3/bp/1', 'tag': 'CartonCount', 'value': 7}


class _NeedsTickets(unittest.TestCase):
    """The absence of the module under test must FAIL, never crash the suite."""

    def setUp(self):
        if tickets is None:
            self.fail(f'field/tickets.py is missing, so nothing here holds: {IMPORT_ERROR}')
        self.store = tickets.TicketStore()


class MintTests(_NeedsTickets):
    def test_a_ticket_needs_an_action(self):
        for bad in (None, {}, 'write', 7, []):
            with self.subTest(action=bad), self.assertRaises(ValueError):
                self.store.mint(bad)

    def test_the_action_is_copied_so_the_caller_cannot_change_it_afterwards(self):
        # A caller holding a reference could otherwise change the target after
        # minting, and the ticket would authorise something nobody looked at.
        action = dict(ACTION)
        ticket = self.store.mint(action)
        action['tag'] = 'SomethingElse'
        action['value'] = 9999
        self.assertEqual(self.store.peek(ticket.id)['action']['tag'], 'CartonCount')
        self.assertEqual(self.store.redeem(ticket.id, actor='operator')['value'], 7)

    def test_redeeming_hands_back_a_copy_too(self):
        ticket = self.store.mint(ACTION)
        redeemed = self.store.redeem(ticket.id, actor='operator')
        redeemed['value'] = 0
        self.assertEqual(ticket.action['value'], 7)

    def test_ids_are_long_and_random(self):
        ids = {self.store.mint(ACTION).id for _ in range(20)}
        self.assertEqual(len(ids), 20, 'ids collided')
        for value in ids:
            self.assertGreaterEqual(len(value), 32)
            self.assertTrue(all(c in '0123456789abcdef' for c in value))

    def test_a_flood_is_refused_rather_than_evicting_something_in_use(self):
        # Evicting the oldest would silently invalidate a ticket somebody is
        # about to confirm, and the write would then fail at the least
        # explicable moment.
        store = tickets.TicketStore(max_outstanding=3)
        first = store.mint(ACTION)
        for _ in range(2):
            store.mint(ACTION)
        with self.assertRaises(tickets.TicketError) as caught:
            store.mint(ACTION)
        self.assertIn('outstanding', str(caught.exception))
        # The one that was already minted still works: nothing was thrown away.
        self.assertEqual(store.redeem(first.id, actor='operator')['tag'], 'CartonCount')

    def test_a_nonsense_ttl_is_refused(self):
        for bad in (0, -1, 'soon', None):
            with self.subTest(ttl=bad), self.assertRaises(ValueError):
                tickets.TicketStore(ttl=bad)


class RedeemTests(_NeedsTickets):
    def test_a_ticket_works_exactly_once(self):
        ticket = self.store.mint(ACTION)
        self.assertEqual(self.store.redeem(ticket.id, actor='operator'), ACTION)
        with self.assertRaises(tickets.TicketError) as caught:
            self.store.redeem(ticket.id, actor='operator')
        self.assertIn('no such ticket', str(caught.exception))

    def test_an_expired_ticket_is_refused_and_says_so(self):
        store = tickets.TicketStore(ttl=0.05)
        ticket = store.mint(ACTION)
        time.sleep(0.08)
        with self.assertRaises(tickets.TicketError) as caught:
            store.redeem(ticket.id, actor='operator')
        # The reason is specific on purpose: this is a loopback sidecar on one
        # operator's machine, and "expired" and "never existed" lead to
        # different next actions.
        self.assertIn('expired', str(caught.exception))

    def test_an_unknown_ticket_is_refused(self):
        for bad in ('', None, 7, 'f' * 32):
            with self.subTest(ticket_id=bad), self.assertRaises(tickets.TicketError):
                self.store.redeem(bad, actor='operator')

    def test_redeeming_requires_a_named_actor(self):
        ticket = self.store.mint(ACTION)
        for bad in (None, '', '   ', 7):
            with self.subTest(actor=bad), self.assertRaises(ValueError):
                self.store.redeem(ticket.id, actor=bad)
        # ...and the ticket survives a refused redemption, so a typo in the
        # actor does not cost the operator their authorisation.
        self.assertEqual(self.store.redeem(ticket.id, actor='operator'), ACTION)

    def test_only_one_of_two_simultaneous_redemptions_wins(self):
        # The sidecar is threaded, so this is ordinary rather than exotic.
        ticket = self.store.mint(ACTION)
        results, errors = [], []
        barrier = threading.Barrier(8)

        def attempt():
            barrier.wait()
            try:
                results.append(self.store.redeem(ticket.id, actor='operator'))
            except tickets.TicketError as exc:
                errors.append(exc)

        threads = [threading.Thread(target=attempt) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(results), 1, f'{len(results)} threads redeemed one ticket')
        self.assertEqual(len(errors), 7)


class HousekeepingTests(_NeedsTickets):
    def test_peek_does_not_consume(self):
        ticket = self.store.mint(ACTION)
        self.assertEqual(self.store.peek(ticket.id)['action'], ACTION)
        self.assertEqual(self.store.peek(ticket.id)['action'], ACTION)
        self.assertEqual(self.store.redeem(ticket.id, actor='operator'), ACTION)
        self.assertIsNone(self.store.peek(ticket.id))

    def test_expired_tickets_are_swept_rather_than_accumulating(self):
        store = tickets.TicketStore(ttl=0.05, max_outstanding=4)
        for _ in range(4):
            store.mint(ACTION)
        self.assertEqual(len(store.outstanding()), 4)
        time.sleep(0.08)
        self.assertEqual(store.outstanding(), [])
        # And the slots came back, so an expired flood cannot wedge the store.
        store.mint(ACTION)

    def test_nothing_is_written_to_disk(self):
        # A ticket that survived a restart would be an authorisation that
        # outlived the thing that authorised it - and the operator who approved
        # it is not necessarily still at the desk.
        import ast
        source = (Path(__file__).resolve().parents[1] / 'field' / 'tickets.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        written = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, 'attr', None) or getattr(node.func, 'id', None)
                if name in ('open', 'write_text', 'write_bytes', 'dump', 'dumps'):
                    written.append(f'line {node.lineno}: {name}')
        self.assertEqual(written, [], f'the ticket store persists something: {written}')
        for module in ('json', 'pathlib', 'sqlite3', 'pickle', 'shelve'):
            self.assertNotIn(f'import {module}', source,
                             f'tickets.py imports {module}; tickets must stay in memory')


def main():
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    failed = len(result.failures) + len(result.errors)
    print(f'passed {result.testsRun - failed - len(result.skipped)}, failed {failed}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
