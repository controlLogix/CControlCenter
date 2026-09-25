"""Format non-negative integers with English ordinal suffixes."""


def ordinal(n):
    """Return the ordinal for n; reject non-integers and negative integers.

    Booleans are not accepted as integers. Zero is formatted as ``0th``.
    """
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError("n must be an integer; booleans are not accepted")
    if n < 0:
        raise ValueError("n must be non-negative")
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
