"""Stdlib EtherNet/IP explicit TCP client (port 44818).

No implicit messaging (class 1 cyclic I/O), no connected messaging, no UDP.
No routing through a chassis/backplane, fragmented tag transfers, or structures.
CIPClient is device-neutral; LogixClient adds symbolic atomic tag services.
Clients are synchronous and must not be shared across threads. Use as context
managers. Reads return the device's type code, type name and scalar value.
Writes require confirm=True and a nonempty actor; a durable JSONL intent is
recorded BEFORE transmission, then success/rejected/unknown is recorded. An
unknown outcome must be investigated, never automatically retried. The journal
is the shared one in writejournal.py (~/.agentmux/field-writes.jsonl), tagged
transport='enip'; pass journal_path to override it.

Wire references: ODVA-compatible OpENer enet_encap/encap.c and Rockwell
publication 1756-PM020 (Logix 5000 Controllers Data Access).
"""

import math
import os
import re
import socket
import struct

import writejournal


class ProtocolError(Exception):
    """Malformed or mismatched EtherNet/IP/CIP response."""


class CIPError(ProtocolError):
    def __init__(self, status, additional_status=()):
        self.status = status
        self.additional_status = tuple(additional_status)
        super().__init__(f"CIP status 0x{status:02x}, additional={self.additional_status}")


HEADER = struct.Struct('<HHII8sI')
ATOMIC_TYPES = {'BOOL': (0xC1, '?'), 'SINT': (0xC2, 'b'),
                'INT': (0xC3, 'h'), 'DINT': (0xC4, 'i'), 'REAL': (0xCA, 'f')}


def _exact(sock, size):
    result = bytearray()
    while len(result) < size:
        part = sock.recv(size - len(result))
        if not part:
            raise ProtocolError('connection closed during response')
        result.extend(part)
    return bytes(result)


def cip_request(service, path, data=b''):
    """Encode a service with an already encoded, word-aligned CIP EPATH."""
    if not 0 <= service < 0x80 or len(path) % 2 or len(path) > 510:
        raise ValueError('invalid service or CIP path')
    return bytes((service, len(path) // 2)) + path + data


def cip_response(service, packet):
    if len(packet) < 4 or packet[0] != service | 0x80 or packet[1] != 0:
        raise ProtocolError('invalid CIP response header')
    end = 4 + packet[3] * 2
    if len(packet) < end:
        raise ProtocolError('truncated CIP additional status')
    extra = struct.unpack('<' + 'H' * packet[3], packet[4:end])
    if packet[2]:
        raise CIPError(packet[2], extra)
    return packet[end:]


def _cpf_data(packet):
    if len(packet) < 8:
        raise ProtocolError('truncated SendRRData')
    interface, _, count = struct.unpack_from('<IHH', packet)
    if interface != 0 or count != 2:
        raise ProtocolError('invalid SendRRData interface or item count')
    items = []
    pos = 8
    for _ in range(count):
        if pos + 4 > len(packet):
            raise ProtocolError('truncated CPF header')
        kind, size = struct.unpack_from('<HH', packet, pos)
        pos += 4
        if pos + size > len(packet):
            raise ProtocolError('truncated CPF item')
        items.append((kind, packet[pos:pos + size]))
        pos += size
    if pos != len(packet) or items[0] != (0, b'') or items[1][0] != 0xB2:
        raise ProtocolError('invalid unconnected CPF items')
    return items[1][1]


class CIPClient:
    """Reusable RegisterSession / SendRRData transport and Identity object."""

    def __init__(self, host, port=44818, timeout=3.0):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('timeout must be positive and finite')
        self.host, self.port, self.timeout = host, port, timeout
        self.session = 0
        self.sock = None

    def connect(self):
        if self.sock is not None:
            return self
        self.sock = socket.create_connection((self.host, self.port), self.timeout)
        try:
            session, data = self._exchange(0x65, b'\x01\x00\x00\x00')
            if not session or data != b'\x01\x00\x00\x00':
                raise ProtocolError('invalid RegisterSession response')
            self.session = session
        except Exception:
            self.close()
            raise
        return self

    def _exchange(self, command, payload):
        if len(payload) > 65535:
            raise ValueError('encapsulation payload too large')
        context = os.urandom(8)
        try:
            self.sock.sendall(HEADER.pack(command, len(payload), self.session,
                                         0, context, 0) + payload)
            cmd, size, session, status, echo, options = HEADER.unpack(_exact(self.sock, 24))
            if cmd != command or echo != context or options:
                raise ProtocolError('mismatched encapsulation response')
            if status:
                raise ProtocolError(f'encapsulation status 0x{status:08x}')
            if command != 0x65 and session != self.session:
                raise ProtocolError('mismatched session handle')
            return session, _exact(self.sock, size)
        except Exception:
            # Never reuse a stream after a timeout or framing error.
            sock, self.sock = self.sock, None
            self.session = 0
            sock.close()
            raise

    def request(self, service, path, data=b''):
        request = cip_request(service, path, data)
        self.connect()
        cpf = struct.pack('<IHHHHHH', 0, 0, 2, 0, 0, 0xB2, len(request)) + request
        _, response = self._exchange(0x6F, cpf)
        return cip_response(service, _cpf_data(response))

    def identity(self):
        """Read Identity class 1, instance 1, mandatory attributes 1 through 7."""
        data = self.request(0x01, b'\x20\x01\x24\x01')
        if len(data) < 15 or len(data) < 15 + data[14]:
            raise ProtocolError('truncated Identity object')
        vendor, device_type, product, major, minor, status, serial = struct.unpack_from('<HHHBBHI', data)
        return {'vendor_id': vendor, 'device_type': device_type,
                'product_code': product, 'revision': (major, minor),
                'status': status, 'serial_number': serial,
                'product_name': data[15:15 + data[14]].decode('latin-1')}

    def close(self):
        sock, self.sock = self.sock, None
        session, self.session = self.session, 0
        if sock is not None:
            try:
                if session:
                    sock.sendall(HEADER.pack(0x66, 0, session, 0, b'\0' * 8, 0))
            except OSError:
                pass
            finally:
                sock.close()

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()


def symbolic_path(tag):
    """ANSI extended symbols plus logical element segments for array indices.

    Supports Tag, Program:Main.Tag, Struct.Member, and Array[1,2].Member.
    """
    if not isinstance(tag, str) or not tag:
        raise ValueError('tag must be a nonempty string')
    path = bytearray()
    for part in tag.split('.'):
        match = re.fullmatch(r'([A-Za-z_][A-Za-z_0-9]*(?::[A-Za-z_][A-Za-z_0-9]*)?)(?:\[([0-9]+(?:,[0-9]+)*)\])?', part)
        if not match:
            raise ValueError('invalid symbolic tag path')
        symbol = match[1].encode('ascii')
        if len(symbol) > 255:
            raise ValueError('symbol too long')
        path.extend(bytes((0x91, len(symbol))) + symbol + b'\0' * (len(symbol) % 2))
        if match[2]:
            for index in map(int, match[2].split(',')):
                if index <= 255:
                    path.extend(bytes((0x28, index)))
                elif index <= 65535:
                    path.extend(b'\x29\0' + struct.pack('<H', index))
                elif index <= 0xFFFFFFFF:
                    path.extend(b'\x2a\0' + struct.pack('<I', index))
                else:
                    raise ValueError('array index too large')
    if len(path) > 510:
        raise ValueError('tag path too long')
    return bytes(path)


class LogixClient(CIPClient):
    """Single-element Logix atomic tag access on a directly reachable controller."""

    def __init__(self, host, port=44818, timeout=3.0, *, journal_path=None):
        super().__init__(host, port, timeout)
        # One journal for every transport (writejournal.py). This client used to
        # keep its own file; two audit trails answer "what did we send to that
        # controller?" only for someone who remembers both exist.
        self.journal = writejournal.WriteJournal(journal_path, transport='enip')

    def read_tag(self, tag):
        data = self.request(0x4C, symbolic_path(tag), b'\x01\x00')
        if len(data) < 2:
            raise ProtocolError('missing atomic type code')
        code, = struct.unpack_from('<H', data)
        for name, (type_code, fmt) in ATOMIC_TYPES.items():
            if code == type_code:
                if len(data) != 2 + struct.calcsize(fmt):
                    raise ProtocolError('invalid atomic value length')
                return {'type': name, 'type_code': code,
                        'value': struct.unpack('<' + fmt, data[2:])[0]}
        raise ProtocolError(f'unsupported atomic type 0x{code:04x}')

    @property
    def journal_path(self):
        # Kept: callers and tests name the path, not the object behind it.
        return self.journal.path

    def write_tag(self, tag, value, data_type, *, confirm=False, actor=None):
        """Write one atomic value; errors after transmission may mean it was applied."""
        if confirm is not True:
            raise PermissionError('write requires confirm=True')
        if not isinstance(actor, str) or not actor.strip():
            raise ValueError('write requires a named actor')
        path = symbolic_path(tag)
        if data_type not in ATOMIC_TYPES:
            raise ValueError('unsupported atomic type')
        code, fmt = ATOMIC_TYPES[data_type]
        if data_type == 'BOOL':
            valid = type(value) is bool
        elif data_type == 'REAL':
            valid = type(value) in (int, float) and math.isfinite(value)
        else:
            valid = type(value) is int
        if not valid:
            raise ValueError('value does not match atomic type')
        try:
            encoded = (b'\xff' if value else b'\x00') if data_type == 'BOOL' else struct.pack('<' + fmt, value)
        except (struct.error, OverflowError) as exc:
            raise ValueError('value outside atomic type range') from exc
        # Durable BEFORE transmission, and it raises if it cannot be - in which
        # case nothing below this line runs and nothing reaches the wire.
        handle = self.journal.intent({'actor': actor, 'host': self.host,
                                      'port': self.port, 'tag': tag,
                                      'type': data_type, 'value': value})
        try:
            response = self.request(0x4D, path, struct.pack('<HH', code, 1) + encoded)
            if response:
                raise ProtocolError('unexpected Write Tag response data')
        except Exception as exc:
            # A CIP status means the device refused and nothing changed. Anything
            # else means we do not know whether it applied - a different fact,
            # investigated at the equipment and never automatically retried.
            handle.settle(writejournal.classify(isinstance(exc, CIPError)), error=str(exc))
            raise
        handle.settle('success')
