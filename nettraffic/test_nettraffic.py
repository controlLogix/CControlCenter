"""Run with python3 nettraffic/test_nettraffic.py or python3 -m nettraffic.test_nettraffic."""
import io
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

# Direct script execution puts nettraffic/, rather than its parent, on sys.path.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nettraffic import analyze, make_fixture, pcap, png

ROOT = Path(__file__).resolve().parent


class CaptureTests(unittest.TestCase):
    def test_both_orders(self):
        for order, name in [('<', 'little-endian'), ('>', 'big-endian')]:
            reader = pcap.Reader(io.BytesIO(make_fixture.capture(order)))
            self.assertEqual(reader.byte_order, name)
            packets = list(reader)
            self.assertEqual(len(packets), 18)
            self.assertEqual(packets[0][:3], (1700000000, 0, 64))
            self.assertEqual(pcap.classify(packets[0][3]), ('TCP', '10.0.0.1'))

    def test_fixture_reproducible(self):
        self.assertEqual((ROOT / 'fixtures/sample.pcap').read_bytes(), make_fixture.capture())

    def test_classification(self):
        for number, name in [(6, 'TCP'), (17, 'UDP'), (1, 'ICMP')]:
            frame = make_fixture.frame(number, 2, 12)
            self.assertEqual(pcap.classify(frame), (name, '10.0.0.2'))
            vlan = frame[:12] + bytes.fromhex('81000001') + frame[12:]
            self.assertEqual(pcap.classify(vlan), (name, '10.0.0.2'))
        self.assertEqual(pcap.classify(b'')[0], 'SHORT')
        self.assertEqual(pcap.classify(make_fixture.frame(6, 1, 12)[:30])[0], 'SHORT')
        ethernet = bytes.fromhex('ffffffffffff02000000000186dd')
        ipv6 = bytes.fromhex('6000000000001140') + bytes.fromhex('20010db8000000000000000000000001') + bytes(16)
        self.assertEqual(pcap.classify(ethernet + ipv6), ('UDP', '2001:DB8:0:0:0:0:0:1'))

    def test_nanosecond_capture(self):
        data = bytearray(make_fixture.capture())
        data[:4] = bytes.fromhex('4d3cb2a1')
        self.assertEqual(pcap.Reader(io.BytesIO(data)).resolution, 1000000000)
        self.assertEqual(len(list(pcap.Reader(io.BytesIO(data)))), 18)

    def test_oversized_read_is_never_attempted(self):
        class Guarded(io.BytesIO):
            def read(self, size=-1):
                if size < 0 or size > 24:
                    raise AssertionError(f'unbounded read: {size}')
                return super().read(size)
        data = bytearray(make_fixture.capture()[:40])
        struct.pack_into('<I', data, 32, 0xffffffff)
        with self.assertRaisesRegex(pcap.CaptureError, 'remaining file'):
            list(pcap.Reader(Guarded(data)))

    def test_cli_invalid_captures(self):
        base = make_fixture.capture()
        invalid = [(base[:10], 'truncated global header'),
                   (base[:30], 'truncated packet header'),
                   (base[:-1], 'truncated payload'),
                   (b'xxxx' + base[4:], 'magic')]
        for offset, value, reason in [(20, 113, 'LINUX_SLL'), (20, 999, 'UNKNOWN'),
                                      (32, 0xffffffff, 'incl_len'), (36, 0, 'orig_len'),
                                      (28, 1000000, 'timestamp'), (16, 1, 'snaplen')]:
            data = bytearray(base)
            struct.pack_into('<I', data, offset, value)
            invalid.append((data, reason))
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / 'bad.pcap', Path(tmp) / 'bad.png'
            for data, reason in invalid:
                with self.subTest(reason=reason):
                    source.write_bytes(data)
                    result = subprocess.run([sys.executable, str(ROOT / 'analyze.py'), str(source), '-o', str(output)], capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(reason, result.stderr)
                    self.assertNotIn('Traceback', result.stderr)
                    self.assertFalse(output.exists())

    def test_summary_exact_counts(self):
        summary = analyze.summarize(ROOT / 'fixtures/sample.pcap')
        self.assertEqual(summary['total'], 18)
        self.assertEqual(summary['protocols'], {'TCP': [6, 474], 'UDP': [6, 420], 'ICMP': [6, 430]})
        self.assertEqual(dict(summary['talkers']), {'10.0.0.1': 474, '10.0.0.2': 420, '10.0.0.3': 430})
        self.assertEqual(summary['bins'], [3] * 6)
        self.assertEqual(summary['bucket_seconds'], 1)

    def test_empty_and_long_unordered_timeline(self):
        base = make_fixture.capture()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.pcap'
            path.write_bytes(base[:24])
            result = analyze.summarize(path)
            self.assertEqual(result['total'], 0)
            self.assertEqual(result['bins'], [0])
            analyze.render(result, Path(tmp) / 'empty.png')
            data = bytearray(base)
            struct.pack_into('<I', data, 24, 4000000000)
            path.write_bytes(data)
            result = analyze.summarize(path)
            self.assertLessEqual(len(result['bins']), 60)
            self.assertEqual(sum(result['bins']), 18)
            self.assertEqual(result['first'], 1700000000)


class PngTests(unittest.TestCase):
    def test_cli_and_full_png_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            for order, name in [('<', 'little-endian'), ('>', 'big-endian')]:
                source, output = Path(tmp) / 'capture.pcap', Path(tmp) / 'out.png'
                source.write_bytes(make_fixture.capture(order))
                result = subprocess.run([sys.executable, str(ROOT / 'analyze.py'), str(source), '-o', str(output)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(name, result.stdout)
                self.assertIn('1000x900', result.stdout)
                raw = output.read_bytes()
                self.assertEqual(raw[:8], b'\x89PNG\r\n\x1a\n')
                pos, kinds, compressed = 8, [], bytearray()
                while pos < len(raw):
                    length = struct.unpack_from('>I', raw, pos)[0]
                    kind = raw[pos + 4:pos + 8]
                    payload = raw[pos + 8:pos + 8 + length]
                    crc = struct.unpack_from('>I', raw, pos + 8 + length)[0]
                    self.assertEqual(crc, zlib.crc32(kind + payload) & 0xffffffff)
                    kinds.append(kind)
                    if kind == b'IHDR':
                        self.assertEqual(struct.unpack('>IIBBBBB', payload), (1000, 900, 8, 2, 0, 0, 0))
                    if kind == b'IDAT':
                        compressed.extend(payload)
                    pos += length + 12
                self.assertEqual(kinds, [b'IHDR', b'IDAT', b'IEND'])
                self.assertEqual(pos, len(raw))
                pixels = zlib.decompress(compressed)
                self.assertEqual(len(pixels), 900 * 3001)
                self.assertTrue(all(pixels[i] == 0 for i in range(0, len(pixels), 3001)))
                self.assertIn(bytes((46, 123, 190)), pixels)
                self.assertIn(bytes((30, 44, 65)), pixels)

    def test_pixels_and_clipping(self):
        canvas = png.Canvas(2, 2)
        canvas.rect(-1, -1, 2, 2, (1, 2, 3))
        self.assertEqual(canvas.pixels, bytes((1, 2, 3)) + bytes((245, 248, 252)) * 3)
        canvas.rect(5, 0, 1, 1, (0, 0, 0))
        self.assertEqual(len(canvas.pixels), 12)


if __name__ == '__main__':
    unittest.main()
