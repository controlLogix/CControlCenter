"""Isolated AMS/TCP simulator; never contacts the shared dashboard or a PLC."""
import contextlib
import io
import json
from pathlib import Path
import socket
import socketserver
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

import ads


def exact(sock, size):
    result = b''
    while len(result) < size:
        part = sock.recv(size - len(result))
        if not part:
            raise EOFError
        result += part
    return result


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        sim = self.server
        try:
            while True:
                reserved, size = struct.unpack('<HI', exact(self.request, 6))
                packet = exact(self.request, size)
                target, tp, source, sp, cmd, flags, count, error, invoke = struct.unpack('<6sH6sHHHIII', packet[:32])
                assert (reserved, flags, error, count) == (0, 4, 0, len(packet) - 32)
                assert (target, tp, source, sp) == (bytes([1,2,3,4,5,6]), 852, bytes([6,5,4,3,2,1]), 33001)
                data = packet[32:]
                sim.requests.append((cmd, data))
                body = b''
                result = 0
                if cmd == 1:
                    body = struct.pack('<BBH16s', 3, 1, 4026, b'Test PLC')
                elif cmd == 4:
                    body = struct.pack('<HH', sim.state, 42)
                elif cmd == 5:
                    state, device, size = struct.unpack('<HHI', data[:8])
                    assert len(data[8:]) == size
                    if sim.journal:
                        assert json.loads(sim.journal.read_text().splitlines()[-1])['outcome'] == 'intent'
                    sim.state = state
                elif cmd in (2, 3, 9):
                    group, offset, size = struct.unpack('<III', data[:12])
                    if cmd == 9:
                        written, = struct.unpack('<I', data[12:16])
                        assert len(data[16:]) == written
                        if group == 0xf003:
                            assert data[16:] == b'MAIN.counter\0'
                            sim.handles.add(1234)
                            body = struct.pack('<II', 4, 1234)
                        else:
                            old = sim.value[:size]
                            sim.value = data[16:]
                            body = struct.pack('<I', len(old)) + old
                    elif cmd == 2:
                        if group == 0xf005:
                            assert offset in sim.handles
                        result = 0x710 if sim.fail_read else 0
                        body = struct.pack('<I', len(sim.value[:size])) + sim.value[:size]
                    else:
                        assert len(data[12:]) == size
                        if group == 0xf006:
                            assert offset == 0 and size == 4
                            handle, = struct.unpack('<I', data[12:])
                            sim.handles.remove(handle)
                        else:
                            if group == 0xf005:
                                assert offset in sim.handles
                            result = 0x704 if sim.reject_write else 0
                            if not result:
                                sim.value = data[12:]
                response = struct.pack('<I', result) + (body if not result else b'')
                if sim.mode == 'route':
                    response = b''
                    error = 7
                if sim.mode == 'ads_route':
                    response = struct.pack('<I', 7)
                if sim.mode == 'drop':
                    return
                header = struct.pack('<6sH6sHHHIII', source, sp, target, tp, cmd, 5,
                                     len(response), error, invoke + (sim.mode == 'invoke'))
                reply = struct.pack('<HI', 0, 32 + len(response)) + header + response
                if sim.mode == 'oversize':
                    reply = struct.pack('<HI', 0, 2**30)
                # Fragment header and body to exercise real stream framing.
                for start in range(0, len(reply), 3):
                    self.request.sendall(reply[start:start + 3])
        except (EOFError, ConnectionError):
            pass
        except Exception as exc:
            sim.errors.append(exc)


class Simulator(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self):
        super().__init__(('127.0.0.1', 0), Handler)
        self.requests, self.errors, self.handles = [], [], set()
        self.state, self.value = 5, struct.pack('<i', 123)
        self.mode, self.fail_read, self.reject_write, self.journal = '', False, False, None
        self.thread = threading.Thread(target=self.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()


class ADSTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.sim = Simulator()
        self.journal = Path(self.temp.name) / 'writes.jsonl'
        self.client = ads.ADSClient('127.0.0.1', '1.2.3.4.5.6', '6.5.4.3.2.1',
                                    tcp_port=self.sim.server_address[1], target_port=852,
                                    source_port=33001, timeout=.5, journal_path=self.journal)

    def tearDown(self):
        self.client.close()
        self.sim.shutdown()
        self.sim.server_close()
        self.temp.cleanup()
        self.assertEqual(self.sim.errors, [])

    def records(self):
        return [json.loads(line) for line in self.journal.read_text().splitlines()]

    def test_info_and_state_are_decoded_and_read_only(self):
        self.assertEqual(self.client.read_device_info(), dict(major=3, minor=1, build=4026, name='Test PLC'))
        self.assertEqual(self.client.read_state(), dict(ads_state=5, device_state=42, state='RUN'))
        self.assertEqual([cmd for cmd, _ in self.sim.requests], [1, 4])
        self.assertFalse(self.journal.exists())

    def test_index_read_write_and_readwrite(self):
        self.assertEqual(self.client.read(0x4020, 8, 4), struct.pack('<i', 123))
        self.client.write(0x4020, 8, b'abcd', confirm=True, actor='test')
        self.assertEqual(self.client.read_write(0x4020, 8, 4, b'efgh', confirm=True, actor='test'), b'abcd')
        self.assertEqual(self.client.read(0x4020, 8, 4), b'efgh')
        self.assertEqual([r['outcome'] for r in self.records()], ['intent', 'success'] * 2)

    def test_symbols_release_after_read_and_write(self):
        for _ in range(3):
            self.assertEqual(self.client.read_symbol('MAIN.counter', 4), self.sim.value)
            self.assertEqual(self.sim.handles, set())
        self.client.write_symbol('MAIN.counter', b'abcd', confirm=True, actor='operator')
        self.assertEqual(self.sim.value, b'abcd')
        self.assertEqual(self.sim.handles, set())
        self.assertEqual(self.records()[0]['operation'], 'write_symbol:MAIN.counter')

    def test_release_after_read_error(self):
        self.sim.fail_read = True
        with self.assertRaises(ads.ADSError):
            self.client.read_symbol('MAIN.counter', 4)
        self.assertEqual(self.sim.handles, set())

    def test_release_after_write_rejection(self):
        self.sim.reject_write = True
        with self.assertRaises(ads.ADSError):
            self.client.write_symbol('MAIN.counter', b'bad!', confirm=True, actor='test')
        self.assertEqual(self.sim.handles, set())
        self.assertEqual(self.records()[-1]['outcome'], 'rejected')

    def test_every_write_requires_confirmation_before_network(self):
        calls = [lambda **kw: self.client.write(1, 2, b'x', **kw),
                 lambda **kw: self.client.read_write(1, 2, 1, b'x', **kw),
                 lambda **kw: self.client.write_control('STOP', **kw),
                 lambda **kw: self.client.write_symbol('MAIN.counter', b'x', **kw)]
        for call in calls:
            for confirm in (False, 1, 'yes'):
                with self.assertRaises(PermissionError):
                    call(confirm=confirm, actor='test')
            with self.assertRaises(ValueError):
                call(confirm=True, actor=' ')
        self.assertEqual(self.sim.requests, [])
        self.assertFalse(self.journal.exists())

    def test_control_all_states_journal_intent_before_transmission(self):
        self.sim.journal = self.journal
        for state in ('STOP', 'CONFIG', 'RUN'):
            self.client.write_control(state, confirm=True, actor='operator')
            self.assertEqual(self.client.read_state()['state'], state)
        records = self.records()
        self.assertEqual([r['outcome'] for r in records], ['intent', 'success'] * 3)
        self.assertEqual(records[0]['actor'], 'operator')
        self.assertEqual(records[0]['id'], records[1]['id'])

    def test_journal_failure_prevents_control(self):
        # The seam is the journal object now: durability moved to
        # writejournal.py, so that is where a failure to record must stop the
        # write before it reaches the device.
        with patch.object(self.client.journal, 'append', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.client.write_control('STOP', confirm=True, actor='operator')
        self.assertEqual(self.sim.requests, [])

    def test_transport_loss_records_unknown(self):
        self.sim.mode = 'drop'
        with self.assertRaisesRegex(ConnectionError, 'ADS route'):
            self.client.write_control('STOP', confirm=True, actor='operator')
        self.assertEqual(self.records()[-1]['outcome'], 'unknown')
        self.assertIsNone(self.client.sock)
        self.assertEqual(len(self.sim.requests), 1)

    def test_missing_route_at_ams_and_ads_layers(self):
        for mode in ('route', 'ads_route'):
            self.sim.mode = mode
            with self.assertRaisesRegex(ads.RouteError, 'No ADS route'):
                self.client.read_state()

    def test_refused_connection_has_route_guidance(self):
        with patch('ads.socket.create_connection', side_effect=ConnectionRefusedError('refused')):
            with self.assertRaisesRegex(ConnectionError, 'ADS route on the target'):
                self.client.read_state()

    def test_ui_displays_missing_route(self):
        self.sim.mode = 'route'
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = ads.main(['127.0.0.1', '--target-net-id', '1.2.3.4.5.6',
                           '--source-net-id', '6.5.4.3.2.1', '--target-port', '852',
                           '--source-port', '33001', '--tcp-port', str(self.sim.server_address[1]), 'state'])
        self.assertEqual(rc, 1)
        self.assertIn('No ADS route', out.getvalue())

    def test_invalid_invoke_discards_stream(self):
        self.sim.mode = 'invoke'
        with self.assertRaises(ads.ProtocolError):
            self.client.read_state()
        self.assertIsNone(self.client.sock)

    def test_oversize_frame_rejected_without_allocation(self):
        self.sim.mode = 'oversize'
        with self.assertRaises(ads.ProtocolError):
            self.client.read_state()
        self.assertIsNone(self.client.sock)

    def test_malformed_read_payload_rejected(self):
        for data in (b'', struct.pack('<I', 10) + b'x', struct.pack('<I', 5) + b'abcde'):
            with patch.object(self.client, '_request', return_value=data):
                with self.assertRaises(ads.ProtocolError):
                    self.client.read(1, 2, 4)

    def test_validation_and_scope(self):
        for value in ('1.2.3', '1.2.3.4.5.256', '1.2.3.4.5.-1'):
            with self.assertRaises(ValueError):
                ads.net_id(value)
        with self.assertRaises(ValueError):
            self.client.read_symbol('bad\0symbol', 4)
        with self.assertRaises(ValueError):
            self.client.read(1, 2, ads.MAX_DATA)
        self.assertIn('not an EtherCAT master', ads.__doc__)
        self.assertEqual(self.sim.requests, [])


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ADSTests))
    failed = len({test.id() for test, _ in result.failures + result.errors})
    print(f'passed {result.testsRun - failed - len(result.skipped)}, failed {failed}', flush=True)
    raise SystemExit(0 if result.wasSuccessful() else 1)
