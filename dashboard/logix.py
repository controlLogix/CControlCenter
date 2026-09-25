"""Logix tag data access per 1756-PM020I (September 2025), pp. 12-37.

This is EtherNet/IP data access, NOT the Logix Designer SDK: that licensed,
Windows/.NET SDK automates an installed Studio 5000 and is out of scope.
Uses TM-074's synchronous, unconnected CIP TCP transport; no routing or I/O.
Symbol instance addressing requires controller version 21 or later; callers
supply an instance ID obtained from the controller, not a persistent tag ID.

Atomic sizes/codes follow the table on p.12. DWORD represents packed BOOL arrays.
Structures are opaque bytes with a structure handle; template discovery/member
layout decoding is not included. For writes the caller must supply the handle
and element size from a known template (pp.12-13), not guess a UDT layout.

Every write requires confirm=True and an actor. A durable intent records the
observed old value and requested new value before any write, followed by outcome,
in the shared journal (writejournal.py) tagged transport='logix'.
Observations are not snapshots: controller logic can change tags between requests.
Fragmented transfers are not atomic. RMW executes controller-side OR then AND,
but its audit pre-read races with controller logic; predicted new value is not a
claim of the value at execution. Unknown/partial writes are never retried.
"""
import math
import struct

import writejournal
from enip import CIPClient, CIPError, ProtocolError, cip_request, _cpf_data, symbolic_path

# Manual p.12, including BOOL's n bit-position field (0..7).
ATOMIC_TYPES = {0xC1: ('BOOL', 'B'), 0xC2: ('SINT', 'b'),
                0xC3: ('INT', 'h'), 0xC4: ('DINT', 'i'),
                0xCA: ('REAL', 'f'), 0xD3: ('DWORD', 'I'), 0xC5: ('LINT', 'q')}


def symbol_instance_path(instance, *, version, suffix=''):
    """Symbol class 0x6B + instance (v21+); optional [indices]/.members."""
    if type(version) is not int or version < 21:
        raise ValueError('symbol instance addressing requires version 21 or later')
    if type(instance) is not int or not 1 <= instance <= 65535:
        raise ValueError('instance must be 1..65535 (manual logical segment table)')
    path = b'\x20\x6b\x25\0' + struct.pack('<H', instance)
    if suffix:
        if not suffix.startswith(('[', '.')):
            raise ValueError('instance suffix must start with [ or .')
        path += symbolic_path('X' + suffix)[4:]
    if len(path) > 510:
        raise ValueError('path too long')
    return path


def _type(descriptor):
    if len(descriptor) < 2:
        raise ProtocolError('missing tag type')
    code = int.from_bytes(descriptor[:2], 'little')
    if code == 0x2A0:
        if len(descriptor) < 4:
            raise ProtocolError('missing structure handle')
        return descriptor[:4], 'STRUCT', None
    base = 0xC1 if code & 0xF8FF == 0xC1 else code
    if base not in ATOMIC_TYPES:
        raise ProtocolError(f'unsupported tag type 0x{code:04x}')
    name, fmt = ATOMIC_TYPES[base]
    return descriptor[:2], name, fmt


def _decode(descriptor, raw, elements, structure_size=None):
    descriptor, name, fmt = _type(descriptor)
    code = int.from_bytes(descriptor[:2], 'little')
    if fmt is None:
        if not raw or (structure_size is not None and len(raw) != structure_size * elements):
            raise ProtocolError('invalid structure data length')
        value = raw
    else:
        if len(raw) != struct.calcsize('<' + fmt) * elements:
            raise ProtocolError('invalid atomic data length')
        values = list(struct.unpack('<' + fmt * elements, raw))
        if name == 'BOOL':
            bit = code >> 8
            values = [bool(v & (1 << bit)) for v in values]
        value = values[0] if elements == 1 else values
    result = dict(type=name, type_code=code, value=value, raw=raw,
                  descriptor=descriptor, elements=elements)
    if name == 'STRUCT':
        result['structure_handle'] = int.from_bytes(descriptor[2:], 'little')
    return result


class LogixClient(CIPClient):
    def __init__(self, host, port=44818, timeout=3.0, *, version=None,
                 journal_path=None, max_packet=500, max_read_bytes=16 * 1024 * 1024):
        super().__init__(host, port, timeout)
        if type(max_packet) is not int or not 32 <= max_packet <= 500:
            raise ValueError('max_packet must be 32..500 CIP bytes')
        if type(max_read_bytes) is not int or not 1 <= max_read_bytes <= 0xFFFFFFFF:
            raise ValueError('invalid read limit')
        self.version, self.max_packet, self.max_read_bytes = version, max_packet, max_read_bytes
        # One journal for every transport (writejournal.py). This client used to
        # keep its own file, with its own field names; two audit trails answer
        # "what did we send to that controller?" only for someone who remembers
        # both exist.
        self.journal = writejournal.WriteJournal(journal_path, transport='logix')

    def _path(self, tag):
        if type(tag) is int:
            return symbol_instance_path(tag, version=self.version)
        return symbolic_path(tag)

    def _tag_request(self, service, path, data):
        # CIPClient.request raises on 0x06 and drops its payload. Reuse its wire
        # transport/CPF framing, parsing partial replies only here in Logix.
        request = cip_request(service, path, data)
        if len(request) > self.max_packet:
            raise ValueError('request exceeds CIP packet budget')
        self.connect()
        cpf = struct.pack('<IHHHHHH', 0, 0, 2, 0, 0, 0xB2, len(request)) + request
        _, reply = self._exchange(0x6F, cpf)
        packet = _cpf_data(reply)
        if len(packet) < 4 or packet[0] != service | 0x80 or packet[1]:
            raise ProtocolError('invalid tag response header')
        end = 4 + packet[3] * 2
        if end > len(packet):
            raise ProtocolError('truncated extended status')
        status = packet[2]
        if status and not (status == 6 and service in (0x4C, 0x52)):
            raise CIPError(status, struct.unpack('<' + 'H' * packet[3], packet[4:end]))
        return status, packet[end:]

    def read_tag(self, tag, elements=1, *, fragmented=False, structure_size=None):
        """Read 0x4C, automatically continuing partial data with 0x52 byte offsets."""
        if type(elements) is not int or not 1 <= elements <= 65535:
            raise ValueError('elements must be 1..65535')
        if structure_size is not None and (type(structure_size) is not int or structure_size <= 0):
            raise ValueError('invalid structure size')
        path, raw, descriptor = self._path(tag), bytearray(), None
        service = 0x52 if fragmented else 0x4C
        while True:
            data = struct.pack('<H', elements)
            if service == 0x52:
                data += struct.pack('<I', len(raw))
            status, body = self._tag_request(service, path, data)
            current, _, fmt = _type(body)
            if descriptor is not None and current != descriptor:
                raise ProtocolError('type changed during fragmented read')
            descriptor = current
            chunk = body[len(current):]
            if not chunk:
                raise ProtocolError('read made no progress')
            raw.extend(chunk)
            expected = (struct.calcsize('<' + fmt) if fmt else structure_size)
            expected = expected * elements if expected else None
            if len(raw) > self.max_read_bytes or (expected is not None and len(raw) > expected):
                raise ProtocolError('read exceeds expected size or limit')
            if status == 0:
                return _decode(descriptor, bytes(raw), elements, structure_size)
            if expected is not None and len(raw) == expected:
                raise ProtocolError('partial status after all expected data')
            service = 0x52

    def read_tag_fragmented(self, tag, elements=1, *, structure_size=None):
        return self.read_tag(tag, elements, fragmented=True, structure_size=structure_size)

    @staticmethod
    def _authorize(confirm, actor):
        if confirm is not True:
            raise PermissionError('write requires confirm=True')
        if not isinstance(actor, str) or not actor.strip():
            raise ValueError('write requires a named actor')

    @property
    def journal_path(self):
        # Kept: callers and tests name the path, not the object behind it.
        return self.journal.path

    def _write(self, tag, actor, old, new_raw, requests, **extra):
        # Raw bytes preserve NaN/Inf and packed BOOL bits without JSON ambiguity.
        # Durable BEFORE transmission, and it raises if it cannot be - in which
        # case nothing below this line runs and nothing reaches the wire.
        handle = self.journal.intent(dict(actor=actor, host=self.host, port=self.port,
                                          tag=tag, old_value=old['raw'], new_value=new_raw,
                                          type_descriptor=old['descriptor'], **extra))
        completed = 0
        try:
            for service, path, data in requests:
                _, reply = self._tag_request(service, path, data)
                if reply:
                    raise ProtocolError('unexpected write response data')
                completed += 1
        except Exception as exc:
            # Fragments that already landed outrank why the rest failed: the
            # controller now holds a value neither side asked for, which is a
            # worse thing to know than either 'rejected' or 'unknown' alone.
            handle.settle(writejournal.classify(isinstance(exc, CIPError), completed),
                          completed_fragments=completed, error=str(exc))
            raise
        handle.settle('success', completed_fragments=completed)

    def write_tag(self, tag, value, data_type, *, confirm=False, actor=None,
                  fragmented=False, elements=None, structure_handle=None, structure_size=None):
        """Write 0x4D or automatically fragment with 0x53; STRUCT value is bytes."""
        self._authorize(confirm, actor)
        path = self._path(tag)
        if data_type == 'STRUCT':
            if (type(structure_handle) is not int or not 0 <= structure_handle <= 65535
                    or type(structure_size) is not int or structure_size <= 0
                    or type(elements) is not int or not 1 <= elements <= 65535
                    or not isinstance(value, bytes) or len(value) != elements * structure_size):
                raise ValueError('STRUCT requires bytes, template handle, size and element count')
            descriptor, raw, size = struct.pack('<HH', 0x2A0, structure_handle), value, structure_size
        else:
            entry = next(((code, fmt) for code, (name, fmt) in ATOMIC_TYPES.items() if name == data_type), None)
            if entry is None:
                raise ValueError('unsupported atomic type')
            code, fmt = entry
            values = list(value) if isinstance(value, (list, tuple)) else [value]
            if elements is None:
                elements = len(values)
            if type(elements) is not int or not 1 <= elements <= 65535 or len(values) != elements:
                raise ValueError('value count does not match elements')
            for item in values:
                valid = (type(item) is bool if data_type == 'BOOL' else
                         type(item) in (float, int) and math.isfinite(item) if data_type == 'REAL' else
                         type(item) is int)
                if not valid:
                    raise ValueError('value does not match atomic type')
            try:
                raw = struct.pack('<' + fmt * elements, *values)
            except (struct.error, OverflowError) as exc:
                raise ValueError('value outside atomic range') from exc
            descriptor, size = struct.pack('<H', code), struct.calcsize('<' + fmt)
        header = descriptor + struct.pack('<H', elements)
        fragmented = fragmented or 2 + len(path) + len(header) + len(raw) > self.max_packet
        capacity = self.max_packet - 2 - len(path) - len(header) - (4 if fragmented else 0)
        # Atomic fragments contain whole elements; structures may span packets.
        alignment = 1 if data_type == 'STRUCT' else size
        capacity -= capacity % alignment
        if capacity <= 0:
            raise ValueError('path leaves no room for data')
        old = self.read_tag(tag, elements, structure_size=structure_size)
        if data_type == 'BOOL' and old['type'] == 'BOOL':
            descriptor = old['descriptor']
            bit = old['type_code'] >> 8
            raw = bytes((1 << bit) if item else 0 for item in values)
            header = descriptor + struct.pack('<H', elements)
        if old['descriptor'] != descriptor or len(old['raw']) != len(raw):
            raise ValueError('write type/size differs from observed tag')
        requests = [(0x53, path, header + struct.pack('<I', offset) + raw[offset:offset + capacity])
                    for offset in range(0, len(raw), capacity)] if fragmented else [(0x4D, path, header + raw)]
        self._write(tag, actor, old, raw, requests, operation='write')

    def write_tag_fragmented(self, tag, value, data_type, **kwargs):
        return self.write_tag(tag, value, data_type, fragmented=True, **kwargs)

    def read_modify_write_tag(self, tag, or_mask, and_mask, *, confirm=False, actor=None):
        """0x4E: byte masks, OR then AND. Audit pre-read races with controller logic.

        Mask size must match the whole accessed type for data integrity (p.36).
        This service is not a compare-and-swap; no automatic retry is safe.
        """
        self._authorize(confirm, actor)
        if (not isinstance(or_mask, bytes) or not isinstance(and_mask, bytes)
                or len(or_mask) not in (1, 2, 4, 8, 12) or len(or_mask) != len(and_mask)):
            raise ValueError('equal byte masks of size 1, 2, 4, 8 or 12 required')
        path = self._path(tag)
        data = struct.pack('<H', len(or_mask)) + or_mask + and_mask
        if 2 + len(path) + len(data) > self.max_packet:
            raise ValueError('RMW request exceeds packet budget')
        old = self.read_tag(tag)
        if len(old['raw']) != len(or_mask):
            raise ValueError('mask size must match whole tag type')
        predicted = bytes((v | o) & a for v, o, a in zip(old['raw'], or_mask, and_mask))
        self._write(tag, actor, old, predicted, [(0x4E, path, data)],
                    operation='read_modify_write', or_mask=or_mask, and_mask=and_mask,
                    new_value_is_prediction=True, old_value_is_observation=True)
