"""Tests for the satisfiable requirements of TM-090.

Finite tests cannot establish collision freedom; the required output space
makes that criterion impossible for arbitrary byte inputs.
"""

import unittest

from orchtest.digest8 import digest8


class Digest8Tests(unittest.TestCase):
    def test_documented_collision_demonstrates_unmet_ac3(self):
        # This records the limitation; passing this test does not satisfy AC3.
        first = bytes.fromhex("000000000000c66f")
        second = bytes.fromhex("000000000000e658")
        self.assertNotEqual(first, second)
        self.assertEqual(digest8(first), "7357966a")
        self.assertEqual(digest8(second), "7357966a")

    def test_known_vectors(self):
        for data, expected in (
            (b"", "e3b0c442"),
            (b"abc", "ba7816bf"),
            (b"hello", "2cf24dba"),
        ):
            with self.subTest(data=data):
                self.assertEqual(digest8(data), expected)

    def test_output_format_for_binary_and_large_inputs(self):
        inputs = [b"", bytes(range(256)), b"\x00\xff" * 500_000]
        inputs.extend(bytes([value]) for value in range(256))
        for data in inputs:
            with self.subTest(length=len(data), prefix=data[:8]):
                result = digest8(data)
                self.assertIsInstance(result, str)
                self.assertEqual(len(result), 8)
                self.assertRegex(result, r"\A[0-9a-f]{8}\Z")

    def test_deterministic_across_repeated_and_interleaved_calls(self):
        data = bytes(range(256)) * 17
        expected = digest8(data)
        for index in range(10):
            digest8(bytes([index]))
            self.assertEqual(digest8(bytes(bytearray(data))), expected)


if __name__ == "__main__":
    unittest.main()
