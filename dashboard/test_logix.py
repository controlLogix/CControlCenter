#!/usr/bin/env python3
"""Isolated TCP simulator and manual vectors; no dashboard or physical PLC.

Vectors: 1756-PM020I pp.18-37. The printed tables contain typos (ControlWord
has '7H'; fragmented offsets disagree with element ranges on pp.24/33).
Tests use ASCII 't' and the normative byte-offset rule, not those typos.
"""
import json
from pathlib import Path
import socket
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import logix
import writejournal


def exact(sock, size):
    result = b''
    while len(result) < size:
        block = sock.recv(size - len(result))
        if not block:
            raise EOFError
        result += block
    return result


class Controller:
    """Independent explicit-message simulator with bounded replies and tag storage."""
    def __init__(self, fault=None):
        self.sock = socket.socket()
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen()
        self.sock.settimeout(2)
        self.port = self.sock.getsockname()[1]
        self.errors, self.requests, self.writes = [], [], []
        self.fault = fault
        self.tags = {'TotalCount': (b'\xc4\0', struct.pack('<i', 534), 4),
                     'CartonSize': (b'\xc4\0', struct.pack('<i', 10), 4),
                     'ControlWord': (b'\xc4\0', struct.pack('<i', 32), 4)}
        self.instances = {0xF68F: 'TotalCount', 0x7136: 'CartonSize', 0xE01A: 'TotalCount'}

    def __enter__(self):
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.thread.join(3)
        self.sock.close()
        if self.thread.is_alive():
            raise AssertionError('simulator thread still running')
        if self.errors:
            raise self.errors[0]

    def run(self):
        try:
            conn, _ = self.sock.accept()
            with conn:
                conn.settimeout(2)
                while True:
                    try:
                        header = exact(conn, 24)
                    except (EOFError, ConnectionResetError):
                        return
                    cmd, size, session, status, context, options = struct.unpack('<HHII8sI', header)
                    assert status == options == 0
                    payload = exact(conn, size)
                    if cmd == 0x65:
                        assert session == 0 and payload == b'\x01\0\0\0'
                        reply = payload
                    elif cmd == 0x66:
                        assert session == 123 and not payload
                        return
                    else:
                        assert cmd == 0x6F and session == 123
                        assert payload[:14] == bytes.fromhex('00000000 0000 0200 0000 0000 b200')
                        request = payload[16:]
                        assert len(request) == int.from_bytes(payload[14:16], 'little')
                        assert len(request) <= 500
                        cip = self.handle(request)
                        if cip is None:
                            return
                        reply = payload[:14] + struct.pack('<H', len(cip)) + cip
                    packet = struct.pack('<HHII8sI', cmd, len(reply), 123, 0, context, 0) + reply
                    # Exercise TCP stream framing, not just complete reads.
                    conn.sendall(packet[:13])
                    conn.sendall(packet[13:])
        except Exception as exc:
            self.errors.append(exc)

    def handle(self, packet):
        self.requests.append(packet)
        service, words = packet[:2]
        path, data = packet[2:2 + 2 * words], packet[2 + 2 * words:]
        if path[:2] == b'\x20\x6b':
            assert path[2:4] == b'\x25\0' and len(path) == 6
            name = self.instances[int.from_bytes(path[4:], 'little')]
        else:
            assert path[0] == 0x91 and len(path) == 2 + path[1] + path[1] % 2
            name = path[2:2 + path[1]].decode('ascii')
        descriptor, value, size = self.tags[name]
        status, body = 0, b''
        if service in (0x4C, 0x52):
            assert len(data) == (2 if service == 0x4C else 6)
            count = int.from_bytes(data[:2], 'little')
            offset = int.from_bytes(data[2:], 'little') if service == 0x52 else 0
            assert count * size <= len(value) and offset < count * size
            # Manual's symbolic read example returns 490 SINTs per fragment.
            chunk = value[offset:min(offset + 490, count * size)]
            status = 6 if offset + len(chunk) < count * size else 0
            body = descriptor + chunk
            if self.fault == 'empty':
                status, body = 6, descriptor
            elif self.fault == 'type_change' and offset:
                body = b'\xc3\0' + chunk
            elif self.fault == 'short':
                status, body = 0, descriptor + chunk[:-1]
            elif self.fault == 'unsupported':
                body = b'\xff\0' + chunk
        else:
            assert service in (0x4D, 0x53, 0x4E)
            if self.fault == 'reject' or self.fault == 'reject_second' and self.writes:
                return bytes((service | 0x80, 0, 0xFF, 1)) + b'\x07\x21'
            self.writes.append(packet)
            if service == 0x4E:
                length = int.from_bytes(data[:2], 'little')
                assert length in (1, 2, 4, 8, 12) and length <= size
                assert len(data) == 2 + length * 2
                value = bytes((v | o) & a for v, o, a in zip(value, data[2:2 + length], data[2 + length:]))
            else:
                assert data[:len(descriptor)] == descriptor
                pos = len(descriptor)
                count = int.from_bytes(data[pos:pos + 2], 'little')
                pos += 2
                offset = 0
                if service == 0x53:
                    offset = int.from_bytes(data[pos:pos + 4], 'little')
                    pos += 4
                chunk = data[pos:]
                assert chunk and offset + len(chunk) <= count * size <= len(value)
                value = value[:offset] + chunk + value[offset + len(chunk):]
            self.tags[name] = descriptor, value, size
            if self.fault == 'disconnect':
                return None  # Applied, but client cannot know that.
        return bytes((service | 0x80, 0, status, 0)) + body


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal = Path(self.temp.name) / 'writes.jsonl'

    def client(self, device):
        return logix.LogixClient('127.0.0.1', device.port, version=21, journal_path=self.journal)

    def records(self):
        return [json.loads(line) for line in self.journal.read_text().splitlines()]

    def test_manual_read_vectors_both_paths(self):
        with Controller() as device, self.client(device) as client:
            self.assertEqual(client.read_tag('TotalCount')['value'], 534)
            self.assertEqual(client.read_tag(0xF68F)['value'], 534)
        self.assertEqual(device.requests, [bytes.fromhex('4c06 910a 546f74616c436f756e74 0100'),
                                           bytes.fromhex('4c03 206b25008ff6 0100')])

    def test_manual_write_vectors_both_paths(self):
        with Controller() as device, self.client(device) as client:
            for tag in ('CartonSize', 0x7136):
                client.write_tag(tag, 14, 'DINT', confirm=True, actor='operator')
                self.assertEqual(client.read_tag(tag)['value'], 14)
        self.assertEqual(device.writes, [bytes.fromhex('4d06 910a 436172746f6e53697a65 c400 0100 0e000000'),
                                        bytes.fromhex('4d03 206b25003671 c400 0100 0e000000')])
        records = self.records()
        self.assertEqual([r['outcome'] for r in records], ['intent', 'success'] * 2)
        self.assertEqual(records[0]['old_value'], {'hex': '0a000000'})
        self.assertEqual(records[0]['new_value'], {'hex': '0e000000'})
        self.assertEqual(records[0]['actor'], 'operator')
        self.assertEqual(records[0]['id'], records[1]['id'])

    def test_manual_rmw_vector(self):
        with Controller() as device, self.client(device) as client:
            client.read_modify_write_tag('ControlWord', b'\x04\0\0\0', b'\xdf\xff\xff\xff',
                                         confirm=True, actor='operator')
            self.assertEqual(client.read_tag('ControlWord')['value'], 4)
        self.assertEqual(device.writes, [bytes.fromhex('4e07 910b 436f6e74726f6c576f726400 0400 04000000 dfffffff')])
        self.assertTrue(self.records()[0]['new_value_is_prediction'])
        self.assertEqual(self.records()[0]['old_value']['hex'], '20000000')

    def test_manual_1750_sint_read_and_write_both_paths(self):
        for tag in ('TotalCount', 0xE01A):
            with self.subTest(tag=tag), Controller() as device, self.client(device) as client:
                original = bytes(i % 128 for i in range(1750))
                if isinstance(tag, str):
                    client.max_packet = 496  # p.29: 474 data bytes + 22 request bytes
                device.tags['TotalCount'] = b'\xc2\0', original, 1
                result = client.read_tag_fragmented(tag, 1750)
                self.assertEqual(result['value'], list(original))
                reads = list(device.requests)
                self.assertEqual([int.from_bytes(p[-4:], 'little') for p in reads], [0, 490, 980, 1470])
                self.assertTrue(all(p[0] == 0x52 and p[-6:-4] == b'\xd6\x06' for p in reads))
                client.write_tag_fragmented(tag, [-5] * 1750, 'SINT', confirm=True, actor='operator')
                self.assertEqual(client.read_tag(tag, 1750)['value'], [-5] * 1750)
                offsets = []
                total = 0
                for p in device.writes:
                    data = p[2 + p[1] * 2:]
                    self.assertEqual(data[:4], bytes.fromhex('c200 d606'))
                    offset = int.from_bytes(data[4:8], 'little')
                    self.assertEqual(offset, total)
                    offsets.append(offset)
                    total += len(data[8:])
                self.assertEqual(total, 1750)
                self.assertGreater(len(offsets), 1)
                if isinstance(tag, str):
                    self.assertEqual(offsets, [0, 474, 948, 1422])
                    self.assertEqual(device.writes[0][:22], bytes.fromhex(
                        '5306 910a 546f74616c436f756e74 c200 d606 00000000'))

    def test_auto_fragment_dint_byte_offsets(self):
        with Controller() as device, self.client(device) as client:
            device.tags['TotalCount'] = b'\xc4\0', b'\0' * 2400, 4
            client.write_tag('TotalCount', list(range(600)), 'DINT', confirm=True, actor='operator')
            self.assertEqual(client.read_tag('TotalCount', 600)['value'], list(range(600)))
            self.assertEqual(device.requests[0][0], 0x4C)
            self.assertEqual(device.requests[1][-4:], struct.pack('<I', 490))
            self.assertTrue(all(p[0] == 0x53 for p in device.writes))

    def test_large_structure_roundtrip(self):
        with Controller() as device, self.client(device) as client:
            device.tags['TotalCount'] = bytes.fromhex('a002 3412'), b'x' * 1800, 900
            self.assertEqual(client.read_tag('TotalCount', 2, structure_size=900)['value'], b'x' * 1800)
            client.write_tag('TotalCount', b'y' * 1800, 'STRUCT', elements=2,
                             structure_handle=0x1234, structure_size=900, confirm=True, actor='operator')
            self.assertEqual(client.read_tag_fragmented('TotalCount', 2)['value'], b'y' * 1800)
            self.assertTrue(all(p[0] == 0x53 for p in device.writes))

    def test_manual_atomic_table_and_bool_bit_field(self):
        cases = [('BOOL', 0xC1, b'\xff', True, False),
                 ('SINT', 0xC2, b'\x80', -128, 127),
                 ('INT', 0xC3, b'\0\x80', -32768, 32767),
                 ('DINT', 0xC4, b'\0\0\0\x80', -2147483648, 2147483647),
                 ('REAL', 0xCA, bytes.fromhex('00004841'), 12.5, -2.25),
                 ('DWORD', 0xD3, b'\xff' * 4, 4294967295, 0),
                 ('LINT', 0xC5, b'\0' * 7 + b'\x80', -(2**63), 2**63 - 1)]
        with Controller() as device, self.client(device) as client:
            for name, code, raw, old, new in cases:
                device.tags['TotalCount'] = struct.pack('<H', code), raw, len(raw)
                result = client.read_tag('TotalCount')
                self.assertEqual((result['type'], result['value']), (name, old))
                client.write_tag('TotalCount', new, name, confirm=True, actor='operator')
                self.assertEqual(client.read_tag('TotalCount')['value'], new)
            for bit in range(8):
                device.tags['TotalCount'] = struct.pack('<H', 0xC1 | bit << 8), bytes([1 << bit]), 1
                self.assertTrue(client.read_tag('TotalCount')['value'])
                device.tags['TotalCount'] = struct.pack('<H', 0xC1 | bit << 8), bytes([255 ^ (1 << bit)]), 1
                self.assertFalse(client.read_tag('TotalCount')['value'])
                client.write_tag('TotalCount', True, 'BOOL', confirm=True, actor='operator')
                self.assertTrue(client.read_tag('TotalCount')['value'])

    def test_rmw_all_documented_mask_sizes(self):
        with Controller() as device, self.client(device) as client:
            for size, descriptor in [(1, b'\xc2\0'), (2, b'\xc3\0'),
                                     (4, b'\xc4\0'), (8, b'\xc5\0'),
                                     (12, bytes.fromhex('a002 3412'))]:
                device.tags['TotalCount'] = descriptor, b'\x20' * size, size
                client.read_modify_write_tag('TotalCount', b'\x04' * size, b'\xdf' * size,
                                             confirm=True, actor='operator')
                self.assertEqual(client.read_tag('TotalCount')['raw'], b'\x04' * size)

    def test_paths_and_version_constraint(self):
        self.assertEqual(logix.symbolic_path('A[1,256,65536].B'), bytes.fromhex('91014100 2801 29000001 2a0000000100 91014200'))
        self.assertEqual(logix.symbol_instance_path(0xF68F, version=21, suffix='[2].B'),
                         bytes.fromhex('206b25008ff6 2802 91014200'))
        for version in (None, 20, True):
            with self.assertRaises(ValueError):
                logix.symbol_instance_path(1, version=version)
        for tag in ('', 'X..Y', 'A[-1]'):
            with self.assertRaises(ValueError):
                logix.symbolic_path(tag)

    def test_confirm_and_actor_gate_before_network(self):
        client = logix.LogixClient('invalid', journal_path=self.journal)
        with patch.object(client, 'connect', side_effect=AssertionError('network used')):
            for method, args in ((client.write_tag, ('X', 1, 'DINT')),
                                 (client.write_tag_fragmented, ('X', [1], 'DINT')),
                                 (client.read_modify_write_tag, ('X', b'\0', b'\xff'))):
                with self.assertRaises(PermissionError):
                    method(*args, actor='operator')
                with self.assertRaises(PermissionError):
                    method(*args, confirm=1, actor='operator')
                with self.assertRaises(ValueError):
                    method(*args, confirm=True, actor=' ')
        self.assertFalse(self.journal.exists())

    def test_journal_failure_prevents_write(self):
        with Controller() as device, self.client(device) as client:
            # The seam is the journal object now: durability moved to
            # writejournal.py, so that is where a failure to record must stop
            # the write before it reaches the controller.
            with patch.object(client.journal, 'append', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    client.write_tag('CartonSize', 14, 'DINT', confirm=True, actor='operator')
            self.assertEqual(device.writes, [])

    def test_intent_is_durable_before_transmission(self):
        with Controller() as device, self.client(device) as client:
            original = client._tag_request
            def checked(service, path, data):
                if service == 0x4D:
                    self.assertEqual(self.records()[-1]['outcome'], 'intent')
                return original(service, path, data)
            # fsync is checked at the syscall, not inferred from the code: the
            # ordering guarantee is worth nothing if the bytes are only buffered.
            # Two calls for one write - the intent and its outcome.
            with patch.object(client, '_tag_request', side_effect=checked),                  patch('writejournal.os.fsync', wraps=writejournal.os.fsync) as sync:
                client.write_tag('CartonSize', 14, 'DINT', confirm=True, actor='operator')
                self.assertEqual(sync.call_count, 2)

    def test_rejected_unknown_and_partial_outcomes_no_retry(self):
        for fault, outcome in [('reject', 'rejected'), ('disconnect', 'unknown'), ('reject_second', 'partial')]:
            self.journal.unlink(missing_ok=True)
            with self.subTest(fault=fault), Controller(fault) as device, self.client(device) as client:
                device.tags['TotalCount'] = b'\xc2\0', b'\0' * 1750, 1
                with self.assertRaises(logix.ProtocolError):
                    client.write_tag('TotalCount', [1] * 1750, 'SINT', confirm=True, actor='operator')
            self.assertEqual(self.records()[-1]['outcome'], outcome)
            self.assertEqual(len(device.writes), 0 if fault == 'reject' else 1)

    def test_invalid_partial_data_and_type(self):
        for fault in ('empty', 'type_change', 'short', 'unsupported'):
            with self.subTest(fault=fault), Controller(fault) as device, self.client(device) as client:
                device.tags['TotalCount'] = b'\xc2\0', b'\0' * 1750, 1
                with self.assertRaises(logix.ProtocolError):
                    client.read_tag('TotalCount', 1750)

    def test_limits_and_type_mismatch(self):
        with Controller() as device, self.client(device) as client:
            with self.assertRaises(ValueError):
                client.write_tag('CartonSize', 14, 'INT', confirm=True, actor='operator')
            with self.assertRaises(ValueError):
                client.read_modify_write_tag('ControlWord', b'\x01', b'\xff', confirm=True, actor='operator')
            client.max_read_bytes = 3
            with self.assertRaises(logix.ProtocolError):
                client.read_tag('CartonSize')
            self.assertEqual(device.writes, [])

    def test_invalid_response_framing_and_extended_error(self):
        client = logix.LogixClient('invalid')
        for cip in (b'', bytes.fromhex('cc000001'), bytes.fromhex('cd000000'), bytes.fromhex('cc010000')):
            cpf = bytes.fromhex('00000000 0000 0200 0000 0000 b200') + struct.pack('<H', len(cip)) + cip
            with patch.object(client, 'connect'), patch.object(client, '_exchange', return_value=(1, cpf)):
                with self.assertRaises(logix.ProtocolError):
                    client.read_tag('X')
        cip = bytes.fromhex('cc00ff01 0521')
        cpf = bytes.fromhex('00000000 0000 0200 0000 0000 b200') + struct.pack('<H', len(cip)) + cip
        with patch.object(client, 'connect'), patch.object(client, '_exchange', return_value=(1, cpf)):
            with self.assertRaises(logix.CIPError) as error:
                client.read_tag('X')
        self.assertEqual(error.exception.additional_status, (0x2105,))


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2).run(suite)
    failed = len(result.failures) + len(result.errors)
    print(f'passed {result.testsRun - failed}, failed {failed}')
    sys.exit(bool(failed))
