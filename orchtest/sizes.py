"""Operator-friendly formatting for byte counts."""


def human_bytes(n):
    """Format a nonnegative byte count using powers of 1024."""
    if n < 0:
        raise ValueError("Byte count must be nonnegative")
    if n < 1024:
        return f"{n} B"

    units = ("KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    value = n
    for unit in units:
        value /= 1024
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
