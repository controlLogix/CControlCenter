"""Tests for operator-friendly durations."""

import unittest

from orchtest.durations import human_time


class HumanTimeTests(unittest.TestCase):
    def test_durations(self):
        cases = (
            (45, "45s"),
            (90, "1m 30s"),
            (7500, "2h 05m"),
            (273600, "3d 04h"),
            (0, "0s"),
            (59, "59s"),
            (60, "1m 0s"),
            (3599, "59m 59s"),
            (3600, "1h 00m"),
            (86399, "23h 59m"),
            (86400, "1d 00h"),
            (45.9, "45s"),
        )
        for seconds, expected in cases:
            with self.subTest(seconds=seconds):
                self.assertEqual(human_time(seconds), expected)

    def test_negative_duration_is_refused(self):
        for seconds in (-1, -0.5):
            with self.subTest(seconds=seconds):
                with self.assertRaisesRegex(ValueError, "nonnegative"):
                    human_time(seconds)

    def test_nonnumeric_duration_is_refused(self):
        for seconds in ("45", "invalid", None, [], 1j, True):
            with self.subTest(seconds=seconds):
                with self.assertRaisesRegex(ValueError, "numeric"):
                    human_time(seconds)

    def test_nonfinite_duration_is_refused(self):
        for seconds in (float("nan"), float("inf")):
            with self.subTest(seconds=seconds):
                with self.assertRaisesRegex(ValueError, "finite"):
                    human_time(seconds)


if __name__ == "__main__":
    unittest.main()
