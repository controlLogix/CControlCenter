"""Tests for length-bounded text truncation."""

import unittest

from orchtest.shorten import shorten


class ShortenTests(unittest.TestCase):
    def test_text_under_limit(self):
        self.assertEqual(shorten("hello", 10), "hello")
        self.assertEqual(shorten("", 1), "")

    def test_text_exactly_at_limit(self):
        self.assertEqual(shorten("hello", 5), "hello")

    def test_text_over_limit(self):
        result = shorten("hello world", 5)
        self.assertEqual(result, "hell…")
        self.assertLessEqual(len(result), 5)

    def test_limit_of_one(self):
        self.assertEqual(shorten("hello", 1), "…")
        self.assertEqual(shorten("a", 1), "a")
        self.assertEqual(len(shorten("hello", 1)), 1)

    def test_limit_too_small_is_refused(self):
        for limit in (0, -1, -10):
            for text in ("", "hello"):
                with self.subTest(limit=limit, text=text):
                    with self.assertRaisesRegex(ValueError, "at least 1.*ellipsis"):
                        shorten(text, limit)


if __name__ == "__main__":
    unittest.main()
