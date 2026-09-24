"""Truncate text while counting the ellipsis in the length limit."""


def shorten(text, limit):
    """Return text within limit characters, using an ellipsis if truncated.

    Raise ValueError if limit cannot accommodate the one-character ellipsis.
    """
    ellipsis = "…"
    if limit < len(ellipsis):
        raise ValueError("limit must be at least 1 to fit the ellipsis")
    if len(text) <= limit:
        return text
    return text[:limit - len(ellipsis)] + ellipsis
