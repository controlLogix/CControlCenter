"""Acceptance and boundary tests for English ordinals."""

import unittest

from orchtest.ordinal import ordinal


class OrdinalTests(unittest.TestCase):
    def test_requested_examples(self):
        expected = {
            1: "1st", 2: "2nd", 3: "3rd", 4: "4th",
            11: "11th", 12: "12th", 13: "13th",
            21: "21st", 101: "101st", 111: "111th",
        }
        for n, result in expected.items():
            with self.subTest(n=n):
                self.assertEqual(ordinal(n), result)

    def test_suffix_boundaries_repeat_in_each_hundred(self):
        suffixes = {
            0: "th", 1: "st", 2: "nd", 3: "rd", 4: "th", 5: "th",
            6: "th", 7: "th", 8: "th", 9: "th", 10: "th", 11: "th",
            12: "th", 13: "th", 14: "th", 20: "th", 21: "st",
            22: "nd", 23: "rd", 24: "th", 99: "th",
        }
        for hundreds in (0, 100, 200, 1000, 10**30):
            for ending, suffix in suffixes.items():
                n = hundreds + ending
                with self.subTest(n=n):
                    self.assertEqual(ordinal(n), f"{n}{suffix}")

    def test_negatives_are_refused_with_reason(self):
        for n in (-1, -11, -100):
            with self.subTest(n=n):
                with self.assertRaisesRegex(ValueError, "non-negative"):
                    ordinal(n)

    def test_non_integers_are_refused_with_reason(self):
        for n in (1.0, 1.5, -1.5, "1", None, True, False, [], {}, 1j):
            with self.subTest(n=n):
                with self.assertRaisesRegex(TypeError, "must be an integer"):
                    ordinal(n)


if __name__ == "__main__":
    unittest.main()
