"""Tests for filename-friendly slugs."""

import unittest

from orchtest.slug import slugify


class SlugifyTests(unittest.TestCase):
    def test_normal_sentence(self):
        self.assertEqual(slugify("Hello World 123"), "hello-world-123")

    def test_mixed_punctuation(self):
        self.assertEqual(slugify("Hello,,, / world___--again!!!"), "hello-world-again")

    def test_leading_and_trailing_spaces(self):
        self.assertEqual(slugify("  Hello World  "), "hello-world")

    def test_other_whitespace(self):
        self.assertEqual(slugify("Hello\t\nWorld"), "hello-world")

    def test_empty_or_punctuation_only(self):
        for text in ("", "   ", "../\\!?"):
            with self.subTest(text=text):
                self.assertEqual(slugify(text), "untitled")


if __name__ == "__main__":
    unittest.main()
