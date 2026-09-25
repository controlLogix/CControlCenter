"""Isolated EtherCAT ADS service fixtures. No PLC or shared dashboard access."""
import contextlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

import ads
import ecat_diag as ec


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal = Path(self.temp.name) / 'writes.jsonl'
        self.client = ads.ADSClient('unused.invalid', '1.2.3.4.5.6', '6.5.4.3.2.1',
                                    target_port=65535, journal_path=self.journal)
        self.diag = ec.EtherCATDiagnostics(self.client)
        self.data = {(3, 256): struct.pack('<H', 8), (6, 0): struct.pack('<H', 2),
                     (7, 0): struct.pack('<HH', 1001, 1002),
                     (9, 1001): bytes([0x14, 0x24]), (9, 1002): bytes([8, 0]),
                     (18, 1001): struct.pack('<4I', 0, 19, 0, 3),
                     (18, 1002): struct.pack('<4I', 1, 2, 3, 0xffffffff)}
        self.calls = []
        self.write_error = None
        self.patch = patch.object(self.client, '_request', side_effect=self.request)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def request(self, cmd, payload):
        self.calls.append((cmd, payload))
        group, offset, size = struct.unpack('<III', payload[:12])
        if cmd == 2:
            data = self.data[group, offset]
            if isinstance(data, Exception):
                raise data
            return struct.pack('<I', len(data)) + data
        self.assertEqual(cmd, 3)
        self.assertEqual((group, offset, size), (9, 1001, 2))
        self.assertEqual(self.records()[-1]['outcome'], 'intent')
        if self.write_error:
            raise self.write_error
        self.data[9, offset] = payload[12:13] + b'\0'
        return b''

    def records(self):
        return [json.loads(s) for s in self.journal.read_text().splitlines()]

    def test_snapshot_full_configured_list_port_counters_and_state(self):
        result = self.diag.snapshot()
        self.assertEqual(result['master_state'], 'OP')
        self.assertEqual([s['configured_address'] for s in result['slaves']], [1001, 1002])
        first, last = result['slaves']
        self.assertEqual(first['state'], 'SAFEOP; error')
        self.assertEqual(first['link'], 'missing link; ports B')
        self.assertEqual(first['crc_per_port'], dict(A=0, B=19, C=0, D=3))
        self.assertEqual(last['crc_per_port']['D'], 0xffffffff)
        self.assertTrue(all(cmd == 2 for cmd, _ in self.calls))
        self.assertFalse(self.journal.exists())
        text = ec.render(result)
        self.assertIn('TwinCAT master reachable over ADS', text)
        self.assertIn('port B=19', text)
        self.assertIn('AL status codes and working-counter error counts: unavailable', text)
        self.assertIsNone(first['actual_address'])

    def test_empty_list(self):
        self.data[6, 0] = b'\0\0'
        self.assertEqual(self.diag.snapshot()['slaves'], [])
        self.assertEqual(len(self.calls), 3)

    def test_short_and_excess_responses_rejected(self):
        for data in (b'\x08', b'\x08\0\0'):
            self.data[3, 256] = data
            with self.assertRaises(ads.ProtocolError):
                self.diag.snapshot()

    def test_invalid_addresses_rejected(self):
        for pair in ((0, 1002), (65535, 1002), (1001, 1001)):
            self.data[7, 0] = struct.pack('<HH', *pair)
            with self.assertRaises(ads.ProtocolError):
                self.diag.snapshot()

    def test_topology_change_detected(self):
        with patch.object(self.diag, '_addresses', side_effect=[(1001,), (1002,)]):
            with self.assertRaisesRegex(ads.ProtocolError, 'configuration changed'):
                self.diag.snapshot()

    def test_unavailable_slave_does_not_hide_other_slaves_or_fake_zero(self):
        self.data[9, 1001] = ads.ADSError(0x710)
        self.data[18, 1001] = ads.ADSError(0x702)
        rows = self.diag.snapshot()['slaves']
        self.assertIsNone(rows[0]['state'])
        self.assertIsNone(rows[0]['crc_per_port'])
        self.assertEqual(len(rows[0]['errors']), 2)
        self.assertEqual(rows[1]['state'], 'OP')

    def test_gate_before_network(self):
        for confirm in (False, 1, 'yes'):
            with self.assertRaises(PermissionError):
                self.diag.request_state(1001, 'OP', confirm=confirm, actor='test')
        with self.assertRaises(ValueError):
            self.diag.request_state(1001, 'OP', confirm=True, actor=' ')
        self.assertEqual(self.calls, [])
        self.assertFalse(self.journal.exists())

    def test_state_request_wire_payload_and_durable_journal(self):
        self.diag.request_state(1001, 'SAFEOP', confirm=True, actor='commissioner')
        cmd, payload = self.calls[-1]
        self.assertEqual((cmd, payload), (3, struct.pack('<IIIH', 9, 1001, 2, 4)))
        before, after = self.records()
        self.assertEqual([before['outcome'], after['outcome']], ['intent', 'success'])
        self.assertEqual(before['actor'], 'commissioner')
        self.assertEqual(before['id'], after['id'])
        self.assertEqual(before['target_port'], 65535)
        self.assertEqual(before['payload_hex'], payload.hex())

    def test_rejected_or_unknown_outcome_no_retry(self):
        for exc, outcome in ((ads.ADSError(0x704), 'rejected'),
                             (ConnectionError('lost'), 'unknown')):
            self.write_error = exc
            with self.assertRaises(type(exc)):
                self.diag.request_state(1001, 'OP', confirm=True, actor='test')
            self.assertEqual(self.records()[-1]['outcome'], outcome)
        self.assertEqual(sum(cmd == 3 for cmd, _ in self.calls), 2)

    def test_failed_journal_prevents_write(self):
        # The seam is the journal object now: durability moved to
        # writejournal.py, so that is where a failure to record must stop the
        # write - ecat_diag reaches the wire through ADSClient, so it inherits
        # the guarantee rather than restating it.
        with patch.object(self.client.journal, 'append', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.diag.request_state(1001, 'OP', confirm=True, actor='test')
        self.assertTrue(all(cmd == 2 for cmd, _ in self.calls))

    def test_bad_state_or_address_no_write(self):
        for address, state in ((True, 'OP'), (0, 'OP'), (65535, 'OP'),
                               (1001, 'RUN'), (999, 'OP')):
            with self.assertRaises(ValueError):
                self.diag.request_state(address, state, confirm=True, actor='test')
        self.assertTrue(all(cmd == 2 for cmd, _ in self.calls))

    def test_decoders_and_wrong_port(self):
        for value, name in ec.STATES.items():
            self.assertEqual(ec.state_name(value), name)
        self.assertIn('identity mismatch', ec.state_name(0x22))
        self.assertIn('Unknown state', ec.state_name(0))
        self.assertIn('unknown flags', ec.state_name(0x108))
        self.client.target_port = 851
        with self.assertRaises(ValueError):
            ec.EtherCATDiagnostics(self.client)

    def test_cli_show_and_confirmation_failure(self):
        base = ['unused.invalid', '--target-net-id', '1.2.3.4.5.6',
                '--source-net-id', '6.5.4.3.2.1']
        with patch.object(ec, 'ADSClient', return_value=self.client):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(ec.main(base + ['show']), 0)
            self.assertIn('Configured slaves: 2', out.getvalue())
            self.calls.clear()
            with contextlib.redirect_stdout(out):
                self.assertEqual(ec.main(base + ['request-state', '1001', 'OP', '--actor', 'test']), 1)
            self.assertEqual(self.calls, [])
            self.assertIn('explicit confirm=True', out.getvalue())


if __name__ == '__main__':
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(DiagnosticsTests))
    failed = len({test.id() for test, _ in result.failures + result.errors})
    print(f'passed {result.testsRun - failed - len(result.skipped)}, failed {failed}', flush=True)
    raise SystemExit(0 if result.wasSuccessful() else 1)
