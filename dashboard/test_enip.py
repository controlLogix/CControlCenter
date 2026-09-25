#!/usr/bin/env python3
"""Self-contained wire-level tests: python3 dashboard/test_enip.py -v.

Loopback simulator checks literal protocol fields independently of client helpers;
no PLC, dashboard process, third-party package, or live journal is used.
"""
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

import enip


def receive(sock, size):
    data = b''
    while len(data) < size:
        part = sock.recv(size - len(data))
        if not part:
            raise EOFError('client disconnected')
        data += part
    return data


class Device:
    def __init__(self, fault=None):
        self.fault = fault
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen()
        self.listener.settimeout(3)
        self.port = self.listener.getsockname()[1]
        self.errors, self.writes = [], []
        self.unregistered = False
        self.values = {'Flag': (0xC1, b'\xff'), 'Small': (0xC2, b'\x80'),
                       'Short': (0xC3, b'\x00\x80'), 'Count': (0xC4, b'\x00\x00\x00\x80'),
                       'Ratio': (0xCA, b'\x00\x00\x48\x41')}

    def __enter__(self):
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.thread.join(4)
        self.listener.close()
        if self.thread.is_alive():
            raise AssertionError('simulator did not stop')
        if self.errors:
            raise self.errors[0]

    def run(self):
        try:
            conn, _ = self.listener.accept()
            with conn:
                conn.settimeout(2)
                registered = False
                while True:
                    try:
                        header = receive(conn, 24)
                    except (EOFError, ConnectionResetError):
                        return
                    command, length, session, status, context, options = struct.unpack('<HHII8sI', header)
                    assert status == options == 0
                    payload = receive(conn, length)
                    if command == 0x65:
                        assert not registered and session == 0 and payload == b'\x01\0\0\0'
                        registered = True
                        reply = payload
                    elif command == 0x66:
                        assert registered and session == 0x12345678 and length == 0
                        self.unregistered = True
                        return
                    else:
                        assert registered and session == 0x12345678 and command == 0x6F
                        assert payload[:14] == bytes.fromhex('00000000 0000 0200 0000 0000 b200')
                        size, = struct.unpack_from('<H', payload, 14)
                        request = payload[16:]
                        assert len(request) == size
                        service, words = request[:2]
                        path, data = request[2:2 + words * 2], request[2 + words * 2:]
                        if service == 1:
                            assert path == b'\x20\x01\x24\x01' and not data
                            body = bytes.fromhex('0100 0e00 3412 2107 6000 efcdab89') + b'\x07TestPLC'
                        else:
                            assert path[0] == 0x91
                            length = path[1]
                            tag = path[2:2 + length].decode('ascii')
                            assert len(path) == 2 + length + length % 2
                            if length % 2:
                                assert path[-1] == 0
                            if service == 0x4C:
                                assert data == b'\x01\0'
                                code, value = self.values[tag]
                                body = struct.pack('<H', code) + value
                            else:
                                assert service == 0x4D
                                code, count = struct.unpack_from('<HH', data)
                                assert count == 1 and code == self.values[tag][0]
                                assert len(data[4:]) == len(self.values[tag][1])
                                self.writes.append((tag, code, data[4:]))
                                self.values[tag] = (code, data[4:])
                                body = b''
                        cip = bytes((service | 0x80, 0, 0, 0)) + body
                        if self.fault == 'cip':
                            cip = bytes((service | 0x80, 0, 5, 1, 7, 0x21))
                        if self.fault == 'type':
                            cip = bytes((service | 0x80, 0, 0, 0, 0xFF, 0))
                        reply = bytes.fromhex('00000000 0000 0200 0000 0000 b200') + struct.pack('<H', len(cip)) + cip
                        if self.fault == 'cpf':
                            reply = reply[:-1]
                        if self.fault == 'disconnect':
                            return
                    out_session = 0x12345678
                    out_status = 1 if self.fault == 'encapsulation' else 0
                    echo = b'bad-echo' if self.fault == 'context' else context
                    if self.fault == 'session' and command == 0x6F:
                        out_session += 1
                    packet = struct.pack('<HHII8sI', command, len(reply), out_session,
                                         out_status, echo, 0) + reply
                    # Deliberately split TCP headers and payloads.
                    for offset in range(0, len(packet), 3):
                        try:
                            conn.sendall(packet[offset:offset + 3])
                        except (BrokenPipeError, ConnectionResetError):
                            return
        except Exception as exc:
            self.errors.append(exc)


class Tests(unittest.TestCase):
    def test_identity_and_session(self):
        with Device() as device:
            with enip.CIPClient('127.0.0.1', device.port) as client:
                self.assertEqual(client.session, 0x12345678)
                self.assertEqual(client.identity(), {
                    'vendor_id': 1, 'device_type': 14, 'product_code': 0x1234,
                    'revision': (33, 7), 'status': 0x60,
                    'serial_number': 0x89ABCDEF, 'product_name': 'TestPLC'})
        self.assertTrue(device.unregistered)

    def test_all_atomic_reads_writes_and_audit(self):
        cases = [('Flag', 'BOOL', True, False), ('Small', 'SINT', -128, 127),
                 ('Short', 'INT', -32768, 32767), ('Count', 'DINT', -2147483648, 2147483647),
                 ('Ratio', 'REAL', 12.5, -2.25)]
        with tempfile.TemporaryDirectory() as temp, Device() as device:
            journal = Path(temp) / 'audit.jsonl'
            with enip.LogixClient('127.0.0.1', device.port, journal_path=journal) as client:
                for tag, kind, old, new in cases:
                    result = client.read_tag(tag)
                    self.assertEqual((result['type'], result['value']), (kind, old))
                    self.assertEqual(result['type_code'], device.values[tag][0])
                    client.write_tag(tag, new, kind, confirm=True, actor='test-operator')
                    self.assertEqual(client.read_tag(tag)['value'], new)
            records = [json.loads(line) for line in journal.read_text().splitlines()]
            self.assertEqual(len(records), 10)
            for pos, (_, kind, _, new) in enumerate(cases):
                intent, success = records[2 * pos:2 * pos + 2]
                self.assertEqual((intent['outcome'], success['outcome']), ('intent', 'success'))
                self.assertEqual(intent['id'], success['id'])
                self.assertEqual((success['actor'], success['value'], success['type']),
                                 ('test-operator', new, kind))
        self.assertEqual(len(device.writes), 5)

    def test_bool_true_wire_value(self):
        with tempfile.TemporaryDirectory() as temp, Device() as device:
            with enip.LogixClient('127.0.0.1', device.port,
                                  journal_path=Path(temp) / 'audit') as client:
                client.write_tag('Flag', True, 'BOOL', confirm=True, actor='tester')
                self.assertIs(client.read_tag('Flag')['value'], True)
        self.assertEqual(device.writes, [('Flag', 0xC1, b'\xff')])

    def test_write_guards_prevent_network(self):
        client = enip.LogixClient('unused')
        # The seam is the journal object now, not a private method on the client:
        # durability moved to writejournal.py, so that is where a failure to
        # record has to stop the write.
        with patch.object(client, 'request') as request, patch.object(client.journal, 'append') as journal:
            for confirm in (False, 1, 'true', None):
                with self.assertRaises(PermissionError):
                    client.write_tag('Count', 1, 'DINT', confirm=confirm, actor='tester')
            for actor in (None, '', ' '):
                with self.assertRaises(ValueError):
                    client.write_tag('Count', 1, 'DINT', confirm=True, actor=actor)
            for kind, value in [('SINT', 128), ('INT', -32769), ('DINT', 2**31),
                                ('BOOL', 1), ('REAL', float('nan')), ('REAL', 1e100), ('DINT', True)]:
                with self.assertRaises(ValueError):
                    client.write_tag('Count', value, kind, confirm=True, actor='tester')
            request.assert_not_called()
            journal.assert_not_called()
            journal.side_effect = OSError('journal unavailable')
            with self.assertRaises(OSError):
                client.write_tag('Count', 1, 'DINT', confirm=True, actor='tester')
            request.assert_not_called()

    def test_intent_is_durable_before_send_and_timeout_closes(self):
        with tempfile.TemporaryDirectory() as temp:
            journal = Path(temp) / 'audit.jsonl'
            client = enip.LogixClient('unused', journal_path=journal)
            def send(*args):
                rows = [json.loads(line) for line in journal.read_text().splitlines()]
                self.assertEqual(rows[0]['outcome'], 'intent')
                self.assertEqual(rows[0]['value'], 10)
                return b''
            with patch.object(client, 'request', side_effect=send):
                client.write_tag('Count', 10, 'DINT', confirm=True, actor='tester')
        from unittest.mock import Mock
        client = enip.CIPClient('unused')
        sock = Mock()
        sock.recv.side_effect = socket.timeout('timed out')
        client.sock, client.session = sock, 123
        with self.assertRaises(socket.timeout):
            client._exchange(0x6F, b'')
        self.assertIsNone(client.sock)
        self.assertEqual(client.session, 0)
        sock.close.assert_called_once()

    def test_failure_audit(self):
        for fault, outcome in [('cip', 'rejected'), ('disconnect', 'unknown')]:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temp, Device(fault) as device:
                journal = Path(temp) / 'audit.jsonl'
                with enip.LogixClient('127.0.0.1', device.port, journal_path=journal) as client:
                    with self.assertRaises(enip.ProtocolError):
                        client.write_tag('Count', 5, 'DINT', confirm=True, actor='tester')
                rows = [json.loads(line) for line in journal.read_text().splitlines()]
                self.assertEqual([r['outcome'] for r in rows], ['intent', outcome])
                # One journal now carries every transport, so each row has to say
                # which one it came from - otherwise a shared file is less
                # informative than the two separate ones it replaced.
                self.assertEqual({r['transport'] for r in rows}, {'enip'})
                # Both rows are the same write, and the id is how anyone reading
                # the file pairs an outcome back to its intent.
                self.assertEqual(len({r['id'] for r in rows}), 1)

    def test_protocol_failures(self):
        for fault in ['context', 'session', 'encapsulation', 'cpf', 'type', 'cip', 'disconnect']:
            with self.subTest(fault=fault), Device(fault) as device:
                client = enip.LogixClient('127.0.0.1', device.port)
                try:
                    with self.assertRaises(enip.ProtocolError) as error:
                        client.read_tag('Count')
                    if fault == 'cip':
                        self.assertEqual(error.exception.status, 5)
                        self.assertEqual(error.exception.additional_status, (0x2107,))
                finally:
                    client.close()

    def test_paths_and_malformed_cip(self):
        self.assertEqual(enip.symbolic_path('Abc'), b'\x91\x03Abc\0')
        self.assertEqual(enip.symbolic_path('A[1,256,65536].B'),
                         bytes.fromhex('91014100 2801 29000001 2a0000000100 91014200'))
        self.assertEqual(enip.symbolic_path('Program:Main.X'), b'\x91\x0cProgram:Main\x91\x01X\0')
        for tag in ['', 'A..B', 'A[-1]', 'A[4294967296]', 'A.' , 'é', 'X' * 256]:
            with self.assertRaises(ValueError):
                enip.symbolic_path(tag)
        for packet in [b'', b'\xcc\0\0', b'\xcd\0\0\0', b'\xcc\0\0\x01']:
            with self.assertRaises(enip.ProtocolError):
                enip.cip_response(0x4C, packet)
        with self.assertRaises(ValueError):
            enip.cip_request(1, b'\x20')


if __name__ == '__main__':
    # run_tests.sh matches the LAST line against "failed 0"; unittest's own
    # "OK" scores a passing suite as a failure. Print the summary it reads.
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
