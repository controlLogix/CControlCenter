"""Bounded, streaming classic libpcap reader (Ethernet only)."""
import struct

MAX_PACKET = 16 * 1024 * 1024
LINKTYPES = {0: 'NULL', 6: 'IEEE802_5', 101: 'RAW', 113: 'LINUX_SLL',
             127: 'IEEE802_11_RADIOTAP', 276: 'LINUX_SLL2'}


class CaptureError(ValueError):
    """An invalid or unsupported capture."""


class Reader:
    def __init__(self, stream):
        self.stream = stream
        start = stream.tell()
        stream.seek(0, 2)
        self.end = stream.tell()
        stream.seek(start)
        header = stream.read(24)
        if len(header) != 24:
            raise CaptureError('truncated global header: need 24 bytes')
        magics = {b'\xd4\xc3\xb2\xa1': ('<', 'little-endian', 1000000),
                  b'\xa1\xb2\xc3\xd4': ('>', 'big-endian', 1000000),
                  b'\x4d\x3c\xb2\xa1': ('<', 'little-endian', 1000000000),
                  b'\xa1\xb2\x3c\x4d': ('>', 'big-endian', 1000000000)}
        if header[:4] not in magics:
            raise CaptureError('unsupported pcap magic (expected classic libpcap)')
        self.order, self.byte_order, self.resolution = magics[header[:4]]
        self.magic = header[:4].hex()
        major, minor, _, _, self.snaplen, link = struct.unpack(
            self.order + 'HHiIII', header[4:])
        if (major, minor) != (2, 4):
            raise CaptureError(f'unsupported pcap version {major}.{minor}')
        if link != 1:
            raise CaptureError(f'unsupported linktype {LINKTYPES.get(link, "UNKNOWN")} ({link}); expected ETHERNET (1)')
        if self.snaplen == 0:
            raise CaptureError('invalid snaplen: zero')

    def __iter__(self):
        count = 0
        while self.stream.tell() < self.end:
            count += 1
            header = self.stream.read(16)
            if len(header) != 16:
                raise CaptureError(f'packet {count}: truncated packet header')
            sec, fraction, included, original = struct.unpack(self.order + 'IIII', header)
            if included > self.end - self.stream.tell():
                raise CaptureError(f'packet {count}: incl_len {included} exceeds remaining file bytes (truncated payload)')
            if included > MAX_PACKET:
                raise CaptureError(f'packet {count}: incl_len exceeds safety limit {MAX_PACKET}')
            if included > self.snaplen or included > original:
                raise CaptureError(f'packet {count}: incl_len exceeds snaplen or orig_len')
            if fraction >= self.resolution:
                raise CaptureError(f'packet {count}: invalid timestamp fraction')
            payload = self.stream.read(included)
            if len(payload) != included:
                raise CaptureError(f'packet {count}: truncated payload')
            yield sec, fraction, original, payload


def classify(data):
    """Return protocol and source; short headers are labelled, never guessed."""
    if len(data) < 14:
        return 'SHORT', 'UNKNOWN'
    source = ':'.join(f'{b:02X}' for b in data[6:12])
    kind = int.from_bytes(data[12:14], 'big')
    offset = 14
    while kind in (0x8100, 0x88a8):
        if len(data) < offset + 4:
            return 'SHORT', source
        kind = int.from_bytes(data[offset + 2:offset + 4], 'big')
        offset += 4
    if kind == 0x0806:
        return 'ARP', source
    if kind == 0x0800:
        ip = data[offset:]
        if len(ip) < 20 or ip[0] >> 4 != 4 or (ip[0] & 15) < 5 or len(ip) < (ip[0] & 15) * 4:
            return 'SHORT', source
        source = '.'.join(str(b) for b in ip[12:16])
        return {1: 'ICMP', 6: 'TCP', 17: 'UDP'}.get(ip[9], 'IPV4-OTHER'), source
    if kind == 0x86dd:
        ip = data[offset:]
        if len(ip) < 40 or ip[0] >> 4 != 6:
            return 'SHORT', source
        source = ':'.join(f'{int.from_bytes(ip[i:i+2], "big"):X}' for i in range(8, 24, 2))
        return {6: 'TCP', 17: 'UDP', 58: 'ICMPV6'}.get(ip[6], 'IPV6-OTHER'), source
    return 'ETH-OTHER', source
