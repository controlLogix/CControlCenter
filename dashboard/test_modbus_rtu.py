"""Private PTY slave exercises the real pyserial transport; no plant/state IO."""
import concurrent.futures
import json
import os
from pathlib import Path
import pty
import select
import struct
import tempfile
import threading
import time
import tty
import unittest
from unittest.mock import patch

import serial
import modbus_poll as mb
import modbus_rtu as rtu
import test_modbus_poll as tcp_tests


def slave_crc(data):
    # Independent MSB-first division, with reflected input/output.
    value = 0xffff
    for byte in data:
        value ^= int(f'{byte:08b}'[::-1], 2) << 8
        for _ in range(8):
            value = ((value << 1) ^ (0x8005 if value & 0x8000 else 0)) & 0xffff
    return int(f'{value:016b}'[::-1], 2)


def packet(data):
    return data + struct.pack('<H', slave_crc(data))


class Slave:
    def __init__(self):
        self.master, self.slave = pty.openpty()
        tty.setraw(self.slave)
        self.device = os.ttyname(self.slave)
        self.registers = [0] * 200
        self.coils = [False] * 200
        self.requests, self.errors, self.times = [], [], []
        self.mode = 'normal'
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            if not select.select([self.master], [], [], .02)[0]:
                continue
            raw = os.read(self.master, 1024)
            # Delimit requests by silence, never by assumed PDU length.
            while select.select([self.master], [], [], 3.5 * 10 / 9600)[0]:
                raw += os.read(self.master, 1024)
            self.requests.append(raw)
            self.times.append(time.monotonic())
            try:
                if slave_crc(raw) != 0:
                    raise ValueError('bad master CRC / overlapping requests')
                unit, fc = raw[:2]
                address, count = struct.unpack('!HH', raw[2:6])
                if fc in (1, 2):
                    bits = bytearray((count+7)//8)
                    for i, value in enumerate(self.coils[address:address+count]):
                        bits[i//8] |= int(value) << (i%8)
                    data = bytes([len(bits)]) + bits
                elif fc in (3, 4):
                    data = bytes([count*2]) + struct.pack('!'+'H'*count, *self.registers[address:address+count])
                elif fc in (5, 6):
                    if fc == 5:
                        self.coils[address] = count == 0xff00
                    else:
                        self.registers[address] = count
                    data = raw[2:6]
                elif fc == 15:
                    for i in range(count):
                        self.coils[address+i] = bool(raw[7+i//8] & (1 << (i%8)))
                    data = raw[2:6]
                elif fc == 16:
                    self.registers[address:address+count] = struct.unpack('!'+'H'*count, raw[7:-2])
                    data = raw[2:6]
                else:
                    raise ValueError('unexpected function')
                mode = self.mode
                if mode == 'hang':
                    continue
                if mode == 'exception':
                    fc, data = fc | 128, b'\x02'
                if mode == 'bad_echo':
                    data = b'\x00\x00\x00\x63'
                if mode == 'bad_count':
                    data = b'\xfa' + data[1:]
                response = packet(bytes([unit + (mode == 'unit'), fc + (mode == 'function')]) + data)
                if mode == 'crc':
                    response = response[:-1] + bytes([response[-1] ^ 1])
                if mode == 'truncated':
                    response = response[:3]
                if mode == 'merged':
                    response += response
                if mode == 'oversize':
                    response = b'\x01' * 257
                os.write(self.master, response)
            except Exception as err:
                self.errors.append(err)

    def close(self):
        self.stop.set()
        self.thread.join(1)
        os.close(self.master)
        os.close(self.slave)


class RTUTests(unittest.TestCase):
    def setUp(self):
        self.slave = Slave()
        self.tmp = tempfile.TemporaryDirectory()
        self.events = []
        self.client = rtu.Client(self.slave.device, parity='N', timeout=.3)
        self.config = dict(transport='rtu', device=self.slave.device, baud=9600,
                           parity='N', stopbits=1, interval=1,
                           tags=[dict(name='temperature', address=0, scale=.1)])
        self.poller = mb.Poller(Path(self.tmp.name)/'tags.json', self.events.append, autostart=False)

    def tearDown(self):
        self.poller.close()
        self.slave.close()
        self.tmp.cleanup()
        self.assertEqual(self.slave.errors, [])

    def test_spec_crc_vectors_and_wire_order(self):
        # Serial Line V1.02 Appendix B pp40-41: intermediate register 813E
        # after 02, final register 1241 after 02 07; low byte 41 goes first.
        # https://www.modbus.org/file/secure/modbusoverserial.pdf
        for data, expected in [('02', 0x813e), ('0207', 0x1241), ('02074112', 0)]:
            self.assertEqual(rtu.crc16(bytes.fromhex(data)), expected)
        self.assertEqual(rtu.frame(bytes.fromhex('0207')), bytes.fromhex('02074112'))
        self.assertEqual(rtu.crc16(b'123456789'), 0x4b37)

    def test_all_read_functions(self):
        self.slave.coils[:10] = [True, False]*5
        self.slave.registers[:2] = [65535, 1234]
        for fc in (1, 2):
            self.assertEqual(self.client.read(1, fc, 0, 10), [True, False]*5)
        for fc in (3, 4):
            self.assertEqual(self.client.read(2, fc, 0, 2), [65535, 1234])

    def test_all_writes_and_readback_with_intent_before_wire(self):
        def journal(event):
            if event['outcome'] == 'intent':
                self.assertEqual(len(self.slave.requests), len(self.events))
            self.events.append(event)
        for fc, values in [(5, [True]), (6, [65535]), (15, [True, False]*5), (16, [12, 34])]:
            self.client.write(1, fc, 3, values, confirm=True, actor='test-operator', journal=journal)
            self.assertEqual(self.client.read(1, 1 if fc in (5, 15) else 3, 3, len(values)), values)
        self.assertEqual([e['outcome'] for e in self.events], ['intent', 'acknowledged']*4)
        self.assertTrue(all(e['device'] == self.slave.device and e['transport'] == 'rtu' for e in self.events))

    def test_write_guards_and_failed_journal_prevent_open(self):
        with patch.object(serial, 'Serial') as opening:
            for options in [dict(confirm=False, actor='x', journal=self.events.append),
                            dict(confirm=True, actor='', journal=self.events.append),
                            dict(confirm=True, actor='x')]:
                with self.assertRaises(ValueError):
                    self.client.write(1, 6, 0, [1], **options)
            def fail(event):
                raise OSError('disk full')
            with self.assertRaises(OSError):
                self.client.write(1, 6, 0, [1], confirm=True, actor='x', journal=fail)
            opening.assert_not_called()

    def test_unknown_write_not_retried(self):
        for mode in ('bad_echo', 'hang'):
            self.slave.mode = mode
            before = len(self.slave.requests)
            with self.assertRaises((mb.ModbusError, TimeoutError)):
                self.client.write(1, 6, 0, [42], confirm=True, actor='x', journal=self.events.append)
            self.assertEqual(len(self.slave.requests), before+1)
            self.assertEqual(self.events[-1]['outcome'], 'unknown')
            self.assertEqual(self.slave.registers[0], 42)

    def test_reject_bad_frames(self):
        for mode in ('crc', 'unit', 'function', 'exception', 'bad_count', 'truncated', 'merged', 'oversize'):
            self.slave.mode = mode
            with self.subTest(mode=mode), self.assertRaises(mb.ModbusError):
                self.client.read(1, 3, 0)

    def test_silent_slave_deadline(self):
        self.slave.mode = 'hang'
        start = time.monotonic()
        with self.assertRaises(TimeoutError):
            self.client.read(1, 3, 0)
        self.assertLess(time.monotonic()-start, .5)

    def test_stale_input_flushed_each_request(self):
        real_serial = serial.Serial
        resets = []
        def opening(*args, **kwargs):
            port = real_serial(*args, **kwargs)
            reset = port.reset_input_buffer
            def tracked():
                resets.append(True)
                reset()
            port.reset_input_buffer = tracked
            os.write(self.slave.master, packet(b'\x01\x03\x02\x00\x63'))
            return port
        with patch.object(serial, 'Serial', side_effect=opening):
            for _ in range(2):
                self.assertEqual(self.client.read(1, 3, 0), [0])
        self.assertEqual(len(resets), 4)

    def test_one_request_in_flight_across_clients_and_port_alias(self):
        alias = Path(self.tmp.name)/'serial-alias'
        alias.symlink_to(self.slave.device)
        other = rtu.Client(str(alias), parity='N', timeout=1)
        self.assertIs(self.client.bus_lock, other.bus_lock)
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            results = list(pool.map(lambda i: (other if i%2 else self.client).read(1, 3, 0), range(8)))
        self.assertEqual(results, [[0]]*8)
        self.assertEqual(len(self.slave.requests), 8)
        self.assertTrue(all(b-a >= self.client.inter_frame for a, b in zip(self.slave.times, self.slave.times[1:])))

    def test_shared_table_scaling_word_order_staleness_and_persistence(self):
        self.assertIs(rtu.Client.read, mb.Client.read)
        self.assertIs(rtu.Client.write, mb.Client.write)
        for dtype, value in [('int32', -12345678), ('uint32', 3456789012), ('float32', -12.5)]:
            words = list(struct.unpack('!HH', struct.pack('!'+mb.FORMATS[dtype], value)))
            for order in ('high', 'low'):
                self.slave.registers[:2] = words if order == 'high' else words[::-1]
                config = dict(self.config, tags=[dict(name='x', address=0, type=dtype, word_order=order, scale=2, offset=1)])
                self.poller.save(config)
                self.poller.poll_once()
                state = self.poller.snapshot()
                self.assertTrue(state['connected'], state['error'])
                self.assertEqual(state['tags'][0]['value'], value*2+1)
        restored = mb.Poller(self.poller.path, self.events.append, autostart=False)
        self.assertEqual(restored.config, self.poller.config)
        with patch.object(mb.time, 'time', return_value=time.time()+2):
            self.assertTrue(self.poller.snapshot()['tags'][0]['stale'])
        self.slave.mode = 'hang'
        self.poller.next_poll = 0
        self.poller.poll_once()
        self.assertFalse(self.poller.snapshot()['connected'])
        self.assertEqual(self.poller.snapshot()['tags'][0]['value'], state['tags'][0]['value'])
        before = len(self.slave.requests)
        self.poller.poll_once()
        self.assertEqual(len(self.slave.requests), before)

    def test_write_target_binds_serial_settings(self):
        self.poller.save(self.config)
        body = dict(target=mb.target(self.poller.config), unit=1, function=6, address=0,
                    values=[42], confirm=True, actor='x')
        for key, value in [('baud', 19200), ('parity', 'E'), ('stopbits', 2), ('device', '/dev/absent')]:
            with self.assertRaises(ValueError):
                self.poller.write(dict(body, target=dict(body['target'], **{key: value})))
        self.assertEqual(self.slave.requests, [])
        self.poller.write(body)
        self.assertEqual(self.slave.registers[0], 42)

    def test_open_error_reaches_snapshot_with_usbipd_guidance(self):
        self.poller.save(dict(self.config, device='/dev/nonexistent-TM-082'))
        self.poller.poll_once()
        state = self.poller.snapshot()
        self.assertFalse(state['connected'])
        self.assertTrue(state['tags'][0]['stale'])
        for phrase in ('Cannot open', 'nonexistent-TM-082', 'usbipd', 'WSL2'):
            self.assertIn(phrase, state['error'])

    def test_invalid_config_preserves_table(self):
        self.poller.save(self.config)
        saved = self.poller.path.read_bytes()
        for change in [dict(baud=0), dict(baud=True), dict(parity='x'), dict(stopbits=3),
                       dict(device=''), dict(device='loop://'), dict(transport='ascii')]:
            with self.assertRaises(ValueError):
                self.poller.save(dict(self.config, **change))
            self.assertEqual(self.poller.path.read_bytes(), saved)

    def test_baud_and_character_format_timing(self):
        self.assertAlmostEqual(rtu.timing(9600, 'N', 1)[2], 3.5*10/9600)
        self.assertAlmostEqual(rtu.timing(9600, 'E', 2)[2], 3.5*12/9600)
        self.assertAlmostEqual(rtu.timing(19200, 'E', 1)[2], 3.5*11/19200)
        self.assertEqual(rtu.timing(115200, 'N', 1)[1:], (.00075, .00175))


class RTUHttpTests(tcp_tests.HttpTests):
    """Reuse the isolated HTTP harness and its existing TCP/API guard checks."""
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Also isolate module constants if server was imported by an earlier suite.
        cls.patches = [patch.object(cls.server, 'HOME_DIR', Path(cls.tmp.name)),
                       patch.object(cls.server, '_modbus_service', None),
                       patch.object(cls.server.ccstore, 'DB_PATH', Path(cls.tmp.name)/'cc.db')]
        for item in cls.patches:
            item.start()

    @classmethod
    def tearDownClass(cls):
        try:
            super().tearDownClass()
        finally:
            for item in reversed(cls.patches):
                item.stop()

    def test_rtu_api_roundtrip_and_durable_journal(self):
        slave = Slave()
        try:
            config = dict(transport='rtu', device=slave.device, baud=9600, parity='N',
                          stopbits=1, interval=1, tags=[dict(name='x', address=0)])
            status, _, raw = self.request('POST', '/api/modbus/tags', config)
            self.assertEqual(status, 200, raw)
            body = dict(target=mb.target(config), unit=1, function=6, address=0,
                        values=[42], actor='rtu-api-operator', confirm=True)
            status, _, raw = self.request('POST', '/api/modbus/write', body)
            self.assertEqual(status, 200, raw)
            self.assertEqual(slave.registers[0], 42)
            service = self.server.modbus_service()
            service.next_poll = 0
            service.poll_once()
            status, _, raw = self.request('GET', '/api/modbus/tags')
            state = json.loads(raw)
            self.assertEqual(status, 200)
            self.assertTrue(state['connected'], state['error'])
            self.assertEqual(state['tags'][0]['value'], 42)
            with self.server.ccstore.connection() as db:
                rows = list(db.execute("SELECT body FROM journal WHERE agent = 'rtu-api-operator' ORDER BY id"))
            events = [json.loads(row['body']) for row in rows]
            self.assertEqual([e['outcome'] for e in events], ['intent', 'acknowledged'])
            self.assertTrue(all(e['device'] == slave.device for e in events))
        finally:
            slave.close()


class TimedPort:
    """Virtual UART with byte arrival times and exact read timeout semantics."""
    def __init__(self, client, gap=None, second_frame=False):
        self.client, self.gap, self.second_frame = client, gap, second_frame
        self.now, self.sent_at, self.last_byte_at = 0., None, None
        self.timeout = 0
        self.queue = []
        self.resets = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def reset_input_buffer(self):
        self.resets += 1
        self.queue = [(at, byte) for at, byte in self.queue if at > self.now]

    def write(self, request):
        self.sent_at = self.now
        at = self.now + len(request)*self.client.character_time + self.client.inter_frame
        reply = packet(b'\x01\x03\x02\x00\x2a')
        for i, byte in enumerate(reply):
            at += self.gap if i == 3 and self.gap is not None else self.client.character_time
            self.queue.append((at, bytes([byte])))
        self.last_byte_at = at
        if self.second_frame:
            for byte in reply:
                at += 2*self.client.inter_frame
                self.queue.append((at, bytes([byte])))
        return len(request)

    def read(self, count):
        if self.queue and self.queue[0][0] <= self.now+self.timeout:
            at, byte = self.queue.pop(0)
            self.now = max(self.now, at)
            return byte
        self.now += self.timeout
        return b''


class TimingTests(unittest.TestCase):
    def test_fragmented_frame_and_full_silence_before_and_after(self):
        for baud in (9600, 19200, 115200):
            client = rtu.Client('/dev/virtual-TM-082', baud=baud, parity='N')
            port = TimedPort(client, second_frame=True)
            with patch.object(serial, 'Serial', return_value=port), patch.object(rtu.time, 'monotonic', side_effect=lambda: port.now):
                self.assertEqual(client.read(1, 3, 0), [42])
            self.assertGreaterEqual(port.sent_at, client.inter_frame)
            self.assertAlmostEqual(port.now-port.last_byte_at, client.inter_frame)
            self.assertEqual(port.resets, 2)
            self.assertEqual(len(port.queue), 7)  # Later frame not merged into reply.

    def test_gap_between_t1_5_and_t3_5_invalidates_frame(self):
        client = rtu.Client('/dev/virtual-TM-082', parity='N')
        port = TimedPort(client, gap=2*client.character_time)
        with patch.object(serial, 'Serial', return_value=port), patch.object(rtu.time, 'monotonic', side_effect=lambda: port.now):
            with self.assertRaisesRegex(mb.ModbusError, 'inter-character gap'):
                client.read(1, 3, 0)

    def test_gap_after_t3_5_ends_truncated_frame(self):
        client = rtu.Client('/dev/virtual-TM-082', parity='N')
        port = TimedPort(client, gap=4*client.character_time)
        with patch.object(serial, 'Serial', return_value=port), patch.object(rtu.time, 'monotonic', side_effect=lambda: port.now):
            with self.assertRaisesRegex(mb.ModbusError, 'length or CRC'):
                client.read(1, 3, 0)


if __name__ == '__main__':
    import sys
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    failures = len(result.failures) + len(result.errors)
    print(f'passed {result.testsRun - failures}, failed {failures}')
    sys.exit(bool(failures))
