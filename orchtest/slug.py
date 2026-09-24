"""Filename-friendly slugs made with the standard library."""

import re


def slugify(text):
    """Lowercase text, collapse non-ASCII-alphanumeric runs, and trim dashes.

    Text without any ASCII letters or digits returns the fallback "untitled".
    """
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "untitled"
