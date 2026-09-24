"""Generate a deterministic capture; supports both classic pcap byte orders."""
import argparse
from pathlib import Path
import struct


def checksum(data):
    total = sum(struct.unpack('>' + 'H' * (len(data) // 2), data))
    while total >> 16:
        total = (total & 65535) + (total >> 16)
    return (~total) & 65535


def frame(protocol, host, payload_size):
    ethernet = bytes.fromhex('ffffffffffff0200000000010800')
    source, target = bytes((10, 0, 0, host)), bytes((10, 0, 0, 254))
    payload = bytes(range(payload_size))
    if protocol == 6:
        transport = struct.pack('>HHIIBBHHH', 12345, 80, 1, 0, 0x50, 2, 8192, 0, 0) + payload
        pseudo = source + target + struct.pack('>BBH', 0, protocol, len(transport))
        check = checksum(pseudo + transport + (b'\0' if len(transport) % 2 else b''))
        transport = transport[:16] + struct.pack('>H', check) + transport[18:]
    elif protocol == 17:
        transport = struct.pack('>HHHH', 12345, 53, 8 + len(payload), 0) + payload
    else:
        transport = struct.pack('>BBHHH', 8, 0, 0, 1, 1) + payload
        check = checksum(transport + (b'\0' if len(transport) % 2 else b''))
        transport = transport[:2] + struct.pack('>H', check) + transport[4:]
    ip = struct.pack('>BBHHHBBH4s4s', 0x45, 0, 20 + len(transport), 1, 0, 64, protocol, 0, source, target)
    ip = ip[:10] + struct.pack('>H', checksum(ip)) + ip[12:]
    return (ethernet + ip + transport).ljust(60, b'\0')


def capture(order='<'):
    out = bytearray(struct.pack(order + 'I H H i I I I', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
    for i in range(18):
        data = frame((6, 17, 1)[i % 3], i % 3 + 1, 10 + i * 2)
        out.extend(struct.pack(order + 'IIII', 1700000000 + i // 3, (i % 3) * 100000, len(data), len(data)))
        out.extend(data)
    return bytes(out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', nargs='?', type=Path, default=Path(__file__).parent / 'fixtures/sample.pcap')
    parser.add_argument('--big-endian', action='store_true')
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(capture('>' if args.big_endian else '<'))
