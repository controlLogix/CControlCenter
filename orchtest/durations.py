"""Operator-friendly formatting for durations."""

import math
from numbers import Real


def human_time(seconds):
    """Format nonnegative real seconds, discarding fractions and smaller units.

    Show seconds, minutes and seconds, hours and minutes, or days and hours.
    """
    if isinstance(seconds, bool) or not isinstance(seconds, Real):
        raise ValueError("Duration must be numeric (a real number of seconds)")
    if seconds < 0:
        raise ValueError("Duration must be nonnegative")
    if seconds != seconds or seconds == math.inf:
        raise ValueError("Duration must be finite")

    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        minutes, remainder = divmod(seconds, 60)
        return f"{minutes}m {remainder}s"
    if seconds < 86400:
        hours, remainder = divmod(seconds, 3600)
        return f"{hours}h {remainder // 60:02d}m"
    days, remainder = divmod(seconds, 86400)
    return f"{days}d {remainder // 3600:02d}h"
