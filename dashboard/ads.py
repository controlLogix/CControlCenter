"""Stdlib ADS CLIENT over AMS/TCP (48898), not an EtherCAT master.

Does not exchange EtherCAT process data: that requires raw layer-2 frames and a
real-time capable stack, not reachable from a WSL userspace process.
Configure target AND source AMS NetIds; the target needs a route back to the
source NetId/IP. This module never installs routes. One client per thread.
Symbol operations acquire/release handles per call. If transport loss prevents
release, cleanup raises an error; remote reclamation cannot be guaranteed.
Writes (including arbitrary Read Write) require confirm=True and a named actor.
A durable intent precedes transmission; unknown outcomes must not be retried
blindly. The journal is the shared one in writejournal.py
(~/.agentmux/field-writes.jsonl), tagged transport='ads'.

Wire references: Beckhoff AMS Header / Structure AMS/TCP Packet and
https://github.com/Beckhoff/ADS/blob/master/AdsLib/standalone/AdsDef.h
The command-line diagnostic UI exposes reads only; use the explicit Python
write methods for confirmed control or value changes.
"""
import argparse
import json
import math
import socket
import struct
from contextlib import contextmanager

import writejournal

TCP = struct.Struct('<HI')
AMS = struct.Struct('<6sH6sHHHIII')
MAX_DATA = 1024 * 1024
STATES = {'RUN': 5, 'STOP': 6, 'CONFIG': 15}


class ProtocolError(Exception):
    pass


class ADSError(ProtocolError):
    def __init__(self, code):
        self.code = code
        super().__init__(f'ADS error 0x{code:08x}')


class RouteError(ADSError):
    def __init__(self, code=7):
        super().__init__(code)
        self.args = ('No ADS route / target machine not found. Configure a route '
                     'on the target for this client source AMS NetId and IP; '
                     'verify the target AMS NetId.',)


def net_id(value):
    try:
        parts = value.split('.')
        if len(parts) != 6 or any(not p.isdecimal() for p in parts):
            raise ValueError
        return bytes(int(p) for p in parts)
    except (AttributeError, ValueError):
        raise ValueError('AMS NetId must contain six decimal octets') from None


def _exact(sock, size):
    data = bytearray()
    while len(data) < size:
        part = sock.recv(size - len(data))
        if not part:
            raise ConnectionError('ADS connection closed by target')
        data.extend(part)
    return bytes(data)


class ADSClient:
    def __init__(self, host, target_net_id, source_net_id, *, target_port=851,
                 source_port=32905, tcp_port=48898, timeout=3.0, journal_path=None):
        self.target = net_id(target_net_id)
        self.source = net_id(source_net_id)
        for port in (target_port, source_port, tcp_port):
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError('ports must be integers from 1 to 65535')
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('timeout must be positive and finite')
        self.host, self.tcp_port, self.timeout = host, tcp_port, timeout
        self.target_port, self.source_port = target_port, source_port
        # One journal for every transport (writejournal.py). This client used to
        # keep a third separate file, which nothing but this module knew about.
        self.journal = writejournal.WriteJournal(journal_path, transport='ads')
        self.sock = None
        self.invoke = 0

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _request(self, command, data=b''):
        if len(data) > MAX_DATA:
            raise ValueError('ADS payload exceeds 1 MiB limit')
        self.invoke = self.invoke % 0xffffffff + 1
        header = AMS.pack(self.target, self.target_port, self.source,
                          self.source_port, command, 4, len(data), 0, self.invoke)
        try:
            if self.sock is None:
                self.sock = socket.create_connection((self.host, self.tcp_port), self.timeout)
            self.sock.sendall(TCP.pack(0, 32 + len(data)) + header + data)
            reserved, length = TCP.unpack(_exact(self.sock, 6))
            if reserved or not 32 <= length <= MAX_DATA + 32:
                raise ProtocolError('invalid AMS/TCP length or reserved field')
            dest, dp, src, sp, cmd, flags, size, error, invoke = AMS.unpack(_exact(self.sock, 32))
            if (dest, dp, src, sp, cmd, flags, invoke) != (
                    self.source, self.source_port, self.target, self.target_port,
                    command, 5, self.invoke) or size != length - 32:
                raise ProtocolError('mismatched AMS response header')
            response = _exact(self.sock, size)
            if error:
                raise RouteError(error) if error == 7 else ADSError(error)
            if len(response) < 4:
                raise ProtocolError('missing ADS result')
            result, = struct.unpack_from('<I', response)
            if result:
                raise RouteError(result) if result == 7 else ADSError(result)
            return response[4:]
        except ADSError:
            raise
        except (OSError, ConnectionError) as exc:
            self.close()
            raise ConnectionError(f'ADS connection failed: {exc}. Check the ADS route on '
                                  'the target for the source AMS NetId/IP, TCP 48898, '
                                  'and ADS service availability; a missing route is a common cause.') from exc
        except Exception:
            self.close()
            raise

    def _fixed(self, command, payload, size):
        data = self._request(command, payload)
        if len(data) != size:
            raise ProtocolError('unexpected ADS response size')
        return data

    def read_device_info(self):
        data = self._fixed(1, b'', 20)
        major, minor, build = struct.unpack_from('<BBH', data)
        return {'major': major, 'minor': minor, 'build': build,
                'name': data[4:].split(b'\0', 1)[0].decode('latin-1')}

    def read_state(self):
        ads, device = struct.unpack('<HH', self._fixed(4, b'', 4))
        return {'ads_state': ads, 'device_state': device,
                'state': next((k for k, v in STATES.items() if v == ads), str(ads))}

    @staticmethod
    def _size(size):
        if type(size) is not int or not 0 <= size <= MAX_DATA - 16:
            raise ValueError('invalid ADS data size')
        return size

    def _read_response(self, command, payload, requested):
        data = self._request(command, payload)
        if len(data) < 4:
            raise ProtocolError('missing ADS read length')
        size, = struct.unpack_from('<I', data)
        if size != len(data) - 4 or size > requested:
            raise ProtocolError('invalid ADS read length')
        return data[4:]

    def read(self, index_group, index_offset, size):
        return self._read_response(2, struct.pack('<III', index_group, index_offset,
                                                self._size(size)), size)

    @staticmethod
    def _authorize(confirm, actor):
        if confirm is not True:
            raise PermissionError('write requires explicit confirm=True')
        if not isinstance(actor, str) or not actor.strip():
            raise ValueError('write requires a named actor')

    @property
    def journal_path(self):
        # Kept: callers and tests name the path, not the object behind it.
        return self.journal.path

    def _write_operation(self, command, payload, operation, confirm, actor, read_size=None):
        self._authorize(confirm, actor)
        if len(payload) > MAX_DATA:
            raise ValueError('ADS payload exceeds 1 MiB limit')
        # Durable BEFORE transmission, and it raises if it cannot be - in which
        # case nothing below this line runs and nothing reaches the wire.
        handle = self.journal.intent(dict(
            actor=actor, operation=operation, host=self.host, tcp_port=self.tcp_port,
            target_net_id='.'.join(map(str, self.target)), target_port=self.target_port,
            command=command, payload_hex=payload.hex()))
        try:
            value = (self._fixed(command, payload, 0) if read_size is None else
                     self._read_response(command, payload, read_size))
        except Exception as exc:
            # An ADS error status means the device refused. Anything else means
            # we do not know whether it applied - investigated, never retried.
            handle.settle(writejournal.classify(isinstance(exc, ADSError)), error=str(exc))
            raise
        handle.settle('success')
        return value

    def write(self, index_group, index_offset, data, *, confirm=False, actor=None):
        payload = struct.pack('<III', index_group, index_offset, len(data)) + data
        return self._write_operation(3, payload, 'write', confirm, actor)

    def read_write(self, index_group, index_offset, size, data, *, confirm=False, actor=None):
        payload = struct.pack('<IIII', index_group, index_offset, self._size(size), len(data)) + data
        return self._write_operation(9, payload, 'read_write', confirm, actor, size)

    def write_control(self, state, device_state=0, data=b'', *, confirm=False, actor=None):
        if state not in STATES:
            raise ValueError('state must be RUN, CONFIG or STOP')
        payload = struct.pack('<HHI', STATES[state], device_state, len(data)) + data
        return self._write_operation(5, payload, 'write_control:' + state, confirm, actor)

    @contextmanager
    def _symbol_handle(self, name):
        if not isinstance(name, str) or not name or '\0' in name:
            raise ValueError('symbol name must be nonempty without NUL')
        name_bytes = name.encode('utf-8') + b'\0'
        payload = struct.pack('<IIII', 0xf003, 0, 4, len(name_bytes)) + name_bytes
        result = self._read_response(9, payload, 4)
        if len(result) != 4:
            raise ProtocolError('invalid symbol handle size')
        handle, = struct.unpack('<I', result)
        try:
            yield handle
        finally:
            # Handle lifecycle only; this exception to write gating cannot alter values.
            self._fixed(3, struct.pack('<III', 0xf006, 0, 4) + result, 0)

    def read_symbol(self, name, size):
        self._size(size)
        with self._symbol_handle(name) as handle:
            return self.read(0xf005, handle, size)

    def write_symbol(self, name, data, *, confirm=False, actor=None):
        self._authorize(confirm, actor)
        self._size(len(data))
        with self._symbol_handle(name) as handle:
            payload = struct.pack('<III', 0xf005, handle, len(data)) + data
            return self._write_operation(3, payload, 'write_symbol:' + name, confirm, actor)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host')
    parser.add_argument('--target-net-id', required=True)
    parser.add_argument('--source-net-id', required=True)
    parser.add_argument('--target-port', type=int, default=851)
    parser.add_argument('--source-port', type=int, default=32905)
    parser.add_argument('--tcp-port', type=int, default=48898)
    parser.add_argument('command', choices=('info', 'state'))
    args = vars(parser.parse_args(argv))
    command = args.pop('command')
    try:
        with ADSClient(**args) as client:
            print(json.dumps(client.read_device_info() if command == 'info' else client.read_state()))
    except (ProtocolError, OSError, ValueError) as exc:
        print(f'ADS: {exc}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
