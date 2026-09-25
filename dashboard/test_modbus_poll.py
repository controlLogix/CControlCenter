"""Isolated simulated Modbus slave; never touches the shared dashboard/state."""
import contextlib
import http.client
import json
import os
from pathlib import Path
import socket
import socketserver
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import modbus_poll as mb


def exact(sock, count):
    result = b''
    while len(result) < count:
        chunk = sock.recv(count-len(result))
        if not chunk:
            raise EOFError
        result += chunk
    return result


class Slave(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self):
        super().__init__(('127.0.0.1', 0), SlaveHandler)
        self.registers = [0] * 100
        self.coils = [False] * 100
        self.requests = []
        self.mode = 'normal'
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.shutdown()
        self.server_close()
        self.thread.join()


class SlaveHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            tx, proto, size, unit = struct.unpack('!HHHB', exact(self.request, 7))
            pdu = exact(self.request, size-1)
            fc = pdu[0]
            self.server.requests.append((unit, pdu))
            if self.server.mode == 'hang':
                time.sleep(0.4)
                return
            address, count = struct.unpack('!HH', pdu[1:5])
            if fc in (1, 2):
                values = self.server.coils[address:address+count]
                data = bytearray((count+7)//8)
                for i, value in enumerate(values):
                    data[i//8] |= int(value) << (i%8)
                response = bytes([fc, len(data)]) + data
            elif fc in (3, 4):
                data = struct.pack('!'+'H'*count, *self.server.registers[address:address+count])
                response = bytes([fc, len(data)]) + data
            elif fc == 5:
                self.server.coils[address] = count == 0xff00
                response = pdu
            elif fc == 6:
                self.server.registers[address] = count
                response = pdu
            elif fc == 15:
                for i in range(count):
                    self.server.coils[address+i] = bool(pdu[6+i//8] & 1 << (i%8))
                response = pdu[:5]
            elif fc == 16:
                self.server.registers[address:address+count] = struct.unpack('!'+'H'*count, pdu[6:])
                response = pdu[:5]
            if self.server.mode == 'exception':
                response = bytes([fc | 128, 2])
            if self.server.mode == 'bad_count':
                response = bytes([fc, 250]) + response[2:]
            if self.server.mode == 'bad_echo':
                response = bytes([fc, 0, 0, 0, 99])
            packet = struct.pack('!HHHB', tx + (self.server.mode == 'bad_tx'), 0,
                                 65535 if self.server.mode == 'bad_length' else len(response)+1, unit) + response
            if self.server.mode == 'truncated':
                self.request.sendall(packet[:8])
                return
            for byte in packet:  # Exercise fragmented MBAP and payload reads.
                self.request.sendall(bytes([byte]))
        except (OSError, EOFError):
            pass


class ModbusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.slave = Slave()
        self.events = []
        self.client = mb.Client('127.0.0.1', self.slave.server_address[1], .15)
        self.config = dict(host='127.0.0.1', port=self.slave.server_address[1], interval=.2,
                           tags=[dict(name='temperature', address=0, type='uint16', scale=.1,
                                      engineering_unit='C')])
        self.poller = mb.Poller(Path(self.tmp.name)/'tags.json', self.events.append, autostart=False)

    def tearDown(self):
        self.poller.close()
        self.slave.close()
        self.tmp.cleanup()

    def test_all_read_functions_fragmented(self):
        self.slave.coils[:10] = [True, False]*5
        self.slave.registers[:2] = [65535, 1234]
        for fc in (1, 2):
            self.assertEqual(self.client.read(1, fc, 0, 10), [True, False]*5)
        for fc in (3, 4):
            self.assertEqual(self.client.read(1, fc, 0, 2), [65535, 1234])

    def test_all_write_functions_and_readback(self):
        for fc, values in [(5, [True]), (6, [65535]), (15, [True, False]*5), (16, [12, 34])]:
            self.client.write(1, fc, 3, values, confirm=True, actor='operator', journal=self.events.append)
            read_fc = 1 if fc in (5, 15) else 3
            self.assertEqual(self.client.read(1, read_fc, 3, len(values)), values)
        self.assertEqual([e['outcome'] for e in self.events], ['intent', 'acknowledged']*4)
        self.assertTrue(all(e['actor'] == 'operator' and 'value' in e for e in self.events))

    def test_confirmation_actor_and_journal_required_before_network(self):
        for kwargs in [dict(confirm=False, actor='x', journal=self.events.append),
                       dict(confirm='true', actor='x', journal=self.events.append),
                       dict(confirm=True, actor='', journal=self.events.append),
                       dict(confirm=True, actor='x')]:
            with self.assertRaises(ValueError):
                self.client.write(1, 6, 0, [1], **kwargs)
        self.assertEqual(self.slave.requests, [])

    def test_journal_failure_prevents_send(self):
        def fail(event):
            raise OSError('disk full')
        with self.assertRaises(OSError):
            self.client.write(1, 6, 0, [1], confirm=True, actor='x', journal=fail)
        self.assertEqual(self.slave.requests, [])

    def test_unknown_write_outcome_never_retried(self):
        self.slave.mode = 'bad_echo'
        with self.assertRaises(mb.ModbusError):
            self.client.write(1, 6, 0, [1], confirm=True, actor='x', journal=self.events.append)
        self.assertEqual(len(self.slave.requests), 1)
        self.assertEqual(self.events[-1]['outcome'], 'unknown')

    def test_invalid_frames_and_exception(self):
        for mode in ('bad_tx', 'bad_length', 'bad_count', 'exception', 'truncated'):
            self.slave.mode = mode
            with self.subTest(mode=mode), self.assertRaises(mb.ModbusError):
                self.client.read(1, 3, 0)

    def test_timeout_bounded(self):
        self.slave.mode = 'hang'
        start = time.monotonic()
        with self.assertRaises(TimeoutError):
            self.client.read(1, 3, 0)
        self.assertLess(time.monotonic()-start, .3)

    def test_word_order_all_32bit_types(self):
        for dtype, value in [('int32', -12345678), ('uint32', 3456789012), ('float32', -12.5)]:
            words = list(struct.unpack('!HH', struct.pack('!'+mb.FORMATS[dtype], value)))
            for order in ('high', 'low'):
                tag = dict(type=dtype, word_order=order, scale=2, offset=1)
                self.assertEqual(mb.decode(words if order == 'high' else words[::-1], tag), value*2+1)

    def test_16bit_and_bool(self):
        for dtype, value in [('int16', -1), ('uint16', 65535), ('bool', True)]:
            self.assertEqual(mb.decode([65535], dict(type=dtype, word_order='high', scale=1, offset=0)), value)

    def test_nonfinite_decode_rejected(self):
        with self.assertRaises(ValueError):
            mb.decode([0x7f80, 0], dict(type='float32', word_order='high', scale=1, offset=0))

    def test_persistence_scaling_and_staleness(self):
        self.slave.registers[0] = 123
        self.poller.save(self.config)
        self.poller.poll_once()
        first = self.poller.snapshot()
        self.assertTrue(first['connected'])
        self.assertAlmostEqual(first['tags'][0]['value'], 12.3)
        self.assertFalse(first['tags'][0]['stale'])
        restored = mb.Poller(self.poller.path, self.events.append, autostart=False)
        self.assertEqual(restored.config, self.poller.config)
        self.assertFalse(restored.snapshot()['connected'])
        with patch.object(mb.time, 'time', return_value=time.time()+.21):
            stale = self.poller.snapshot()
        self.assertFalse(stale['connected'])
        self.assertTrue(stale['tags'][0]['stale'])
        self.assertEqual(stale['tags'][0]['last_good'], first['tags'][0]['last_good'])
        self.assertEqual(stale['tags'][0]['value'], first['tags'][0]['value'])

    def test_age_is_measured_here_not_by_the_browser(self):
        # The browser cannot compute this: subtracting our epoch from its own is
        # two different clocks, and they only agree by luck. iiot.js:11-14 is
        # right that a WRONG age is worse than none, because it still looks
        # authoritative. So the age travels with the reading.
        self.slave.registers[0] = 123
        self.poller.save(self.config)
        self.poller.poll_once()
        fresh = self.poller.snapshot()['tags'][0]
        self.assertIsNotNone(fresh['age_ms'])
        self.assertLess(fresh['age_ms'], 1000, 'a just-polled tag should be ~0ms old')

        # Age grows with the SERVER's clock, and tracks it.
        with patch.object(mb.time, 'time', return_value=time.time() + 5):
            later = self.poller.snapshot()['tags'][0]
        self.assertGreaterEqual(later['age_ms'], 4500)
        self.assertLessEqual(later['age_ms'], 6000)

    def test_a_tag_never_read_has_no_age_rather_than_a_zero_one(self):
        # A zero age reads as "just now", which is the opposite of the truth for
        # a tag that has never returned a value.
        self.poller.save(self.config)
        never = self.poller.snapshot()['tags'][0]
        self.assertIsNone(never['last_good'])
        self.assertIsNone(never['age_ms'])
        self.assertTrue(never['stale'])

    def test_disconnect_within_interval_and_backoff(self):
        self.poller.save(self.config)
        self.poller.poll_once()
        self.slave.mode = 'hang'
        self.poller.next_poll = 0
        start = time.monotonic()
        self.poller.poll_once()
        self.assertLess(time.monotonic()-start, self.config['interval'])
        self.assertFalse(self.poller.snapshot()['connected'])
        self.assertTrue(self.poller.snapshot()['tags'][0]['stale'])
        count = len(self.slave.requests)
        self.poller.poll_once()
        self.assertEqual(len(self.slave.requests), count)
        self.poller.next_poll = 0
        self.poller.poll_once()
        self.assertGreater(self.poller.snapshot()['retry_in'], .35)
        self.slave.mode = 'normal'
        self.poller.next_poll = 0
        self.poller.poll_once()
        self.assertTrue(self.poller.snapshot()['connected'])
        self.assertEqual(self.poller.failures, 0)

    def test_background_polling(self):
        self.poller.save(self.config)
        worker = mb.Poller(self.poller.path, self.events.append)
        try:
            deadline = time.monotonic()+1
            while not worker.snapshot()['connected'] and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(worker.snapshot()['connected'])
        finally:
            worker.close()

    def test_invalid_table_does_not_replace_saved_table(self):
        self.poller.save(self.config)
        old = self.poller.path.read_bytes()
        for change in [dict(host='localhost'), dict(interval=0), dict(interval=float('nan')),
                       dict(tags=[]), dict(tags=[dict(name='x', address=65535, type='float32')]),
                       dict(tags=[dict(name='x', address=0, function=1, type='float32')])]:
            with self.assertRaises(ValueError):
                self.poller.save(dict(self.config, **change))
            self.assertEqual(self.poller.path.read_bytes(), old)

    def test_invalid_write_rejected_without_io(self):
        for fc, values in [(5, [1]), (6, [-1]), (16, [65536]), (15, []), (4, [1])]:
            with self.assertRaises(ValueError):
                self.client.write(1, fc, 0, values, confirm=True, actor='x', journal=self.events.append)
        self.assertEqual(self.events, [])
        self.assertEqual(self.slave.requests, [])

    def test_write_target_binding(self):
        self.poller.save(self.config)
        with self.assertRaises(ValueError):
            self.poller.write(dict(target={'host': '127.0.0.2', 'port': 502}, unit=1,
                                   function=6, address=0, values=[1], confirm=True, actor='x'))
        self.assertEqual(self.slave.requests, [])


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Import server only after isolating its state paths. No suite_server or
        # restart.sh: bind a private ephemeral listener in this process.
        cls.tmp = tempfile.TemporaryDirectory()
        cls.env = patch.dict(os.environ, {'AGENTMUX_HOME': cls.tmp.name})
        cls.env.start()
        import server
        cls.server = server
        cls.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()
        if cls.server._modbus_service:
            cls.server._modbus_service.close()
        cls.env.stop()
        cls.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection(*self.http.server_address, timeout=3)
        try:
            conn.request(method, path, body=json.dumps(body) if body is not None else None,
                         headers=headers or ({'Content-Type': 'application/json'} if body is not None else {}))
            response = conn.getresponse()
            return response.status, response.getheader('Content-Type'), response.read()
        finally:
            conn.close()

    def test_javascript_mime_and_page_inclusion(self):
        status, mime, body = self.request('GET', '/iiot.js')
        self.assertEqual(status, 200)
        self.assertIn('text/javascript', mime)
        self.assertIn(b'Review and confirm write', body)
        self.assertIn(b'iiot.js', self.request('GET', '/')[2])

    def test_api_persistence_confirm_guard_and_shared_journal(self):
        slave = Slave()
        try:
            config = dict(host='127.0.0.1', port=slave.server_address[1], interval=1,
                          tags=[dict(name='x', address=0)])
            self.assertEqual(self.request('POST', '/api/modbus/tags', config)[0], 200)
            status, _, raw = self.request('GET', '/api/modbus/tags')
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(raw)['config']['host'], '127.0.0.1')
            body = dict(target={k: config[k] for k in ('host', 'port')}, unit=1,
                        function=6, address=0, values=[42], actor='test-operator')
            self.assertEqual(self.request('POST', '/api/modbus/write', body)[0], 400)
            body['confirm'] = True
            self.assertEqual(self.request('POST', '/api/modbus/write', body)[0], 200)
            self.assertEqual(slave.registers[0], 42)
            with self.server.ccstore.connection() as db:
                rows = list(db.execute("SELECT agent, body FROM journal WHERE subject LIKE 'Modbus write %'"))
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(row['agent'] == 'test-operator' for row in rows))
            self.assertEqual(json.loads(rows[1]['body'])['value'], [42])
        finally:
            slave.close()

    def test_api_origin_and_method_guards(self):
        self.assertEqual(self.request('POST', '/api/modbus/tags', {},
            {'Content-Type': 'application/json', 'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.request('GET', '/api/modbus/write')[0], 405)


if __name__ == '__main__':
    import sys
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    failures = len(result.failures) + len(result.errors)
    # A skipped test is not a passed one. result.testsRun counts skips, so the old
    # `testsRun - failures` reported them as passes and a suite that silently ran
    # nothing looked identical to one that ran everything. run_tests.sh:175 already
    # greps for '^SKIP ', so naming them here is what makes them visible in the gate.
    for case, reason in result.skipped:
        print(f'SKIP {case} - {reason}')
    print(f'passed {result.testsRun - failures - len(result.skipped)}, '
          f'failed {failures}')
    sys.exit(bool(failures))
