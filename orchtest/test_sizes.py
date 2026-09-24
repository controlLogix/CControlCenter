"""Tests for operator-friendly byte counts."""

import unittest

from orchtest.sizes import human_bytes


class HumanBytesTests(unittest.TestCase):
    def test_byte_counts(self):
        cases = (
            (0, "0 B"),
            (999, "999 B"),
            (1024, "1.0 KB"),
            (1536, "1.5 KB"),
            (1024**2, "1.0 MB"),
            (1536 * 1024, "1.5 MB"),
            (1024**3, "1.0 GB"),
            (2 * 1024**3, "2.0 GB"),
        )
        for count, expected in cases:
            with self.subTest(count=count):
                self.assertEqual(human_bytes(count), expected)

    def test_negative_count_is_refused(self):
        with self.assertRaisesRegex(ValueError, "Byte count must be nonnegative"):
            human_bytes(-1)


if __name__ == "__main__":
    unittest.main()
